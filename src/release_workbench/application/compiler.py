"""Compile public documents into validated, framework-independent execution graphs."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

from release_workbench.domain.cards import get_spec
from release_workbench.domain.models import Card, Edge, Graph, Owner, Workflow
from release_workbench.domain.values import ContractError, TypedValue


class CompilationError(ContractError):
    def __init__(self, errors: list[str], issues: list[dict[str, str]] | None = None):
        self.errors = list(dict.fromkeys(errors))
        self.issues = issues or []
        super().__init__("\n".join(self.errors))


def references(value: Any) -> Iterator[dict[str, str]]:
    if isinstance(value, dict):
        if "$ref" in value:
            yield value
        else:
            for item in value.values():
                yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


class Compiler:
    """Own semantic validation; adapters own parsing and schema validation."""

    def compile(self, raw: dict[str, Any]) -> Workflow:
        self.issues: list[dict[str, str]] = []
        self.graph_labels = {"main": "Main workflow"}
        self.graph_labels.update(
            {
                definition["graph"]: f"Function “{name}”"
                for name, definition in raw.get("functions", {}).items()
            }
        )
        if raw.get("version") != 3:
            raise CompilationError(
                [
                    "Unsupported workflow version. This preview accepts schema v3 only; the original file was not changed."
                ]
            )
        from pathlib import PurePosixPath, PureWindowsPath

        for pattern in raw.get("report_paths", []):
            if (
                PurePosixPath(pattern).is_absolute()
                or PureWindowsPath(pattern).is_absolute()
                or ".." in PurePosixPath(pattern.replace("\\", "/")).parts
            ):
                raise CompilationError(["Report paths must stay inside the workspace."])
        graphs: dict[str, Graph] = {}
        errors: list[str] = []
        for graph_id, data in raw["graphs"].items():
            cards = {}
            card_errors: list[str] = []
            for item in data["cards"]:
                spec = get_spec(item["kind"])
                owner = Owner(**item["owner"]) if item.get("owner") else None
                card = Card(
                    item["id"],
                    item["kind"],
                    item["name"],
                    {**copy.deepcopy(spec.defaults), **copy.deepcopy(item.get("config", {}))},
                    item.get("inputs", {}),
                    owner,
                    item.get("settings", {}),
                )
                if card.id in cards:
                    errors.append(f"{graph_id}: duplicate card ID {card.id}.")
                cards[card.id] = card
                card_errors.extend(spec.validate(card))
            edges = tuple(Edge(**edge) for edge in data["edges"])
            if len({edge.id for edge in edges}) != len(edges):
                errors.append(f"{graph_id}: connection IDs must be unique.")
            graphs[graph_id] = Graph(graph_id, cards, edges)
            errors.extend(self._diagnostics(card_errors, graphs[graph_id]))
        if errors:
            raise CompilationError(errors, self._complete_issues(errors))
        workflow = Workflow(
            raw["name"],
            graphs,
            raw.get("functions", {}),
            raw.get("inputs", {}),
            raw.get("globals", {}),
            raw.get("concurrency", 4),
            raw,
        )
        if "main" not in graphs:
            errors.append("Provide the main execution graph.")
        for name, definition in workflow.globals.items():
            try:
                TypedValue.checked(definition["initial"], definition["type"])
            except ContractError as error:
                errors.append(f"Global {name}: {error}")
        for definitions in [
            workflow.inputs,
            *(f.get("inputs", {}) for f in workflow.functions.values()),
        ]:
            for name, definition in definitions.items():
                if "default" in definition:
                    try:
                        TypedValue.checked(definition["default"], definition["type"])
                    except ContractError as error:
                        errors.append(f"Input {name}: {error}")
        function_graphs = [value["graph"] for value in workflow.functions.values()]
        if len(function_graphs) != len(set(function_graphs)) or "main" in function_graphs:
            errors.append("Each function must own a distinct graph, separate from main.")
        for name, function in workflow.functions.items():
            if function["graph"] not in graphs:
                errors.append(f"Function {name}: graph is missing.")
        if set(graphs) - {"main", *function_graphs}:
            errors.append("Every non-main graph must belong to a function.")
        for graph in graphs.values():
            errors.extend(self._validate_graph(workflow, graph))
        errors.extend(self._function_cycles(workflow))
        if not errors:
            for graph in graphs.values():
                errors.extend(self._parallel_conflicts(workflow, graph))
        if errors:
            raise CompilationError(errors, self._complete_issues(errors))
        from .skip_plan import plan_skips

        skip_errors = plan_skips(workflow)["blockers"]
        if skip_errors:
            raise CompilationError(skip_errors)
        return workflow

    def _complete_issues(self, errors: list[str]) -> list[dict[str, str]]:
        described = {
            f"{issue['label']}{' · ' + issue['port'] if issue['port'] else ''}: {issue['message']}"
            for issue in self.issues
        }
        return self.issues + [
            {"graph": "", "card": "", "port": "", "label": "Workflow settings", "message": error}
            for error in dict.fromkeys(errors)
            if error not in described
        ]

    def _diagnostics(self, errors: list[str], graph: Graph) -> list[str]:
        """Keep navigation identity separate from names shown to workflow authors."""
        messages = []
        for error in errors:
            location, separator, detail = error.partition(": ")
            local = location.removeprefix(graph.id + "/")
            card = next(
                (
                    item
                    for item in graph.cards.values()
                    if local == item.id or local.startswith(item.id + ".")
                ),
                None,
            )
            port = local[len(card.id) + 1 :] if card and local.startswith(card.id + ".") else ""
            if card is None:
                edge = next((item for item in graph.edges if item.id == local), None)
                if edge:
                    card = graph.cards.get(edge.target) or graph.cards.get(edge.source)
            graph_label = self.graph_labels.get(graph.id, graph.id)
            label = f"{graph_label} › {card.name}" if card else graph_label
            message = detail if separator else error
            messages.append(f"{label}{' · ' + port if port else ''}: {message}")
            self.issues.append(
                {
                    "graph": graph.id,
                    "card": card.id if card else "",
                    "port": port,
                    "label": label,
                    "message": message,
                }
            )
        return messages

    def _validate_graph(self, workflow: Workflow, graph: Graph) -> list[str]:
        errors: list[str] = []
        starts = [card for card in graph.cards.values() if card.kind == "start"]
        if len(starts) != 1 or starts and starts[0].owner:
            errors.append(f"{graph.id}: provide one unowned Start marker.")
        regions: dict[str, set[str]] = {}
        for card in graph.cards.values():
            if card.kind == "loop":
                regions[card.id] = {"body"}
            elif card.kind == "parallel":
                regions[card.id] = set(card.config.get("branches", []))
            elif card.kind == "try":
                regions[card.id] = {"body", "catch", "finally"}
        for card in graph.cards.values():
            owner = card.owner
            seen = {card.id}
            while owner:
                if owner.card in seen:
                    errors.append(f"{card.id}: cyclic ownership.")
                    break
                seen.add(owner.card)
                if owner.region not in regions.get(owner.card, set()):
                    errors.append(f"{card.id}: invalid control-flow owner or region.")
                    break
                owner = graph.cards[owner.card].owner
            if (
                card.kind in ("if", "poll")
                or card.kind == "loop"
                and card.config.get("mode") == "while"
            ):
                function = workflow.functions.get(card.config.get("function", ""))
                if not function or function["returns"] != "boolean":
                    errors.append(f"{card.id}: select a function that returns Boolean.")
            if card.kind == "call" and card.config.get("function") not in workflow.functions:
                errors.append(f"{card.id}: function does not exist.")
            if card.kind == "variable" and card.config.get("name") not in workflow.globals:
                errors.append(f"{card.id}: declare this global in workflow settings.")
            if card.kind in ("break", "continue") and not self._inside_loop(graph, card):
                errors.append(
                    f"{card.id}: Break/Continue requires a loop body in this graph; it cannot target a caller."
                )
            if card.kind == "finish" and (graph.id != "main" or card.owner):
                errors.append(
                    f"{card.id}: Finish belongs to the main workflow, outside controlled branches. Replace it with a Return card to complete this function or branch."
                )
            if (
                card.kind == "finish"
                and not list(references(card.config.get("value")))
                and not any(
                    e.kind == "value" and e.target == card.id and e.target_port == "config:value"
                    for e in graph.edges
                )
            ):
                try:
                    TypedValue.checked(card.config.get("value"), card.config.get("returns", "void"))
                except ContractError as error:
                    errors.append(
                        f"{card.id}: {str(error).rstrip('.')}. The execution connection does not supply a result. Choose Result source to use a Python or Calculate result, or enter a value matching the return type."
                    )
            if card.kind == "return" and not card.owner:
                function = next(
                    (f for f in workflow.functions.values() if f["graph"] == graph.id),
                    None,
                )
                if not function:
                    errors.append(f"{card.id}: Return belongs in a function or controlled branch.")
                elif not list(references(card.config.get("value"))) and not any(
                    e.kind == "value" and e.target == card.id and e.target_port == "config:value"
                    for e in graph.edges
                ):
                    try:
                        TypedValue.checked(card.config.get("value"), function["returns"])
                    except ContractError as error:
                        errors.append(
                            f"{card.id}: {str(error).rstrip('.')}. The execution connection does not supply a result. Choose Result source to use a Python or Calculate result, or enter a value matching the return type."
                        )
            if card.settings.get("retry") and not get_spec(card.kind).supports_retry:
                errors.append(f"{card.id}: retry applies to executable operations only.")
            if not get_spec(card.kind).holds_slot and any(
                card.settings.get(key) for key in ("resources", "exclusive", "interactive")
            ):
                errors.append(
                    f"{card.id}: put execution locks on operations, not structural containers."
                )
            for binding in references([card.config, card.inputs]):
                ref = binding["$ref"]
                if not isinstance(ref, str):
                    errors.append(f"{card.id}: value references must be text.")
                    continue
                if ref.startswith("card:") and ref[5:] not in graph.cards:
                    errors.append(f"{card.id}: missing value source {ref[5:]}.")
                if ref.startswith("global:"):
                    errors.append(
                        f"{card.id}: access globals through Variable cards so parallel conflicts can be checked."
                    )
                if not ref.startswith(("card:", "input:", "env:")) and ref not in (
                    "error",
                    "loop",
                    "runtime:python",
                ):
                    errors.append(f"{card.id}: unknown reference {ref}.")
        flows: dict[tuple[str, str], list[Edge]] = {}
        values: set[tuple[str, str]] = set()
        for edge in graph.edges:
            source, target = graph.cards.get(edge.source), graph.cards.get(edge.target)
            if not source or not target:
                errors.append(f"{edge.id}: connection references a missing card.")
                continue
            if edge.kind == "value":
                source_type = get_spec(source.kind).result_type(source, workflow)
                target_type = None
                if (
                    edge.target_port.startswith("input:")
                    and target.config.get("function") in workflow.functions
                ):
                    parameter = (
                        workflow.functions[target.config["function"]]
                        .get("inputs", {})
                        .get(edge.target_port[6:])
                    )
                    target_type = parameter["type"] if parameter else None
                if (
                    source_type == "void"
                    or target_type
                    and target_type != "json"
                    and source_type not in ("json", target_type)
                ):
                    errors.append(
                        f"{edge.id}: incompatible value types {source_type} → {target_type or 'value'}."
                    )
                key = (edge.target, edge.target_port)
                if key in values:
                    errors.append(f"{edge.id}: a value input accepts one connection.")
                values.add(key)
                if edge.source_port != "value" or edge.target_port == "entry":
                    errors.append(f"{edge.id}: value connections use Value → a named input.")
                if edge.target_port.startswith("config:") and edge.target_port[7:] not in {
                    f["key"] for f in get_spec(target.kind).fields
                }:
                    errors.append(f"{edge.id}: unknown configuration value port.")
                if not edge.target_port.startswith(("config:", "input:")):
                    errors.append(f"{edge.id}: choose a typed config:FIELD or input:NAME port.")
                continue
            flows.setdefault((source.id, edge.source_port), []).append(edge)
            if edge.source_port not in get_spec(source.kind).flow_outputs(source):
                errors.append(f"{edge.id}: unknown execution output {edge.source_port}.")
            if edge.target_port == "next_iteration":
                if target.kind != "loop" or source.owner != Owner(target.id, "body"):
                    errors.append(
                        f"{edge.id}: Next iteration only accepts this loop's Body completion."
                    )
            elif edge.target_port != "entry":
                errors.append(f"{edge.id}: execution targets Entry or Next iteration.")
            elif edge.source_port in regions.get(source.id, set()):
                if target.owner != Owner(source.id, edge.source_port):
                    errors.append(
                        f"{edge.id}: control branches must declare their owner explicitly."
                    )
            elif source.owner != target.owner:
                errors.append(f"{edge.id}: execution cannot bypass a control boundary.")
            if target.kind == "start":
                errors.append(f"{edge.id}: Start cannot have an incoming execution connection.")
        for card in graph.cards.values():
            for port in get_spec(card.kind).flow_outputs(card):
                connections = flows.get((card.id, port), [])
                optional = card.kind == "try" and port in ("catch", "finally")
                if len(connections) != 1 and not (optional and not connections):
                    message = (
                        f"{graph.id}/{card.id}.{port}: no execution connection. Connect {card.name}'s {port} output to the next card or a completion marker."
                        if not connections
                        else f"{graph.id}/{card.id}.{port}: has {len(connections)} execution connections. Keep one, or use Parallel for concurrent work."
                    )
                    errors.append(message)
            if card.kind == "parallel":
                next_edges = graph.outgoing(card.id, "done")
                join = graph.cards.get(next_edges[0].target) if next_edges else None
                if not join or join.kind != "join" or join.config.get("parallel") != card.id:
                    errors.append(f"{card.id}: Done must connect to its matching Join.")
            if card.kind == "join":
                parallel = graph.cards.get(card.config.get("parallel", ""))
                if not parallel or parallel.kind != "parallel":
                    errors.append(f"{card.id}: choose its Parallel card.")
        errors.extend(self._cycles_and_values(graph, starts))
        return self._diagnostics(errors, graph)

    def _inside_loop(self, graph: Graph, card: Card) -> bool:
        owner = card.owner
        seen: set[str] = set()
        while owner and owner.card not in seen and owner.card in graph.cards:
            seen.add(owner.card)
            parent = graph.cards[owner.card]
            if parent.kind == "loop" and owner.region == "body":
                return True
            owner = parent.owner
        return False

    def _cycles_and_values(self, graph: Graph, starts: list[Card]) -> list[str]:
        errors: list[str] = []
        active: set[str] = set()
        done: set[str] = set()
        predecessors: dict[str, set[str]] = {key: set() for key in graph.cards}
        for edge in graph.edges:
            if (
                edge.kind == "flow"
                and edge.target_port != "next_iteration"
                and edge.source in graph.cards
                and edge.target in graph.cards
            ):
                predecessors[edge.target].add(edge.source)

        def visit(key: str) -> None:
            if key in active:
                raise ContractError(f"{graph.id}: ordinary execution cycle at {key}; use Loop.")
            if key in done:
                return
            active.add(key)
            for edge in graph.edges:
                if (
                    edge.kind == "flow"
                    and edge.source == key
                    and edge.target_port != "next_iteration"
                    and edge.target in graph.cards
                ):
                    visit(edge.target)
            active.remove(key)
            done.add(key)

        try:
            for key in graph.cards:
                visit(key)
        except ContractError as error:
            errors.append(str(error))
            return errors
        if len(starts) != 1:
            return errors
        start = starts[0].id
        reachable: set[str] = set()

        def reach(key: str) -> None:
            if key in reachable:
                return
            reachable.add(key)
            for edge in graph.edges:
                if (
                    edge.kind == "flow"
                    and edge.source == key
                    and edge.target_port != "next_iteration"
                    and edge.target in graph.cards
                ):
                    reach(edge.target)

        reach(start)
        for key in set(graph.cards) - reachable:
            errors.append(f"{key}: card is unreachable from Start; connect or delete it.")
        dominators = {key: ({start} if key == start else set(reachable)) for key in reachable}
        changed = True
        while changed:
            changed = False
            for key in reachable - {start}:
                parents = predecessors[key] & reachable
                value = {key} | (
                    set.intersection(*(dominators[p] for p in parents)) if parents else set()
                )
                if value != dominators[key]:
                    dominators[key] = value
                    changed = True
        for target in graph.cards.values():
            sources = [
                b["$ref"][5:]
                for b in references([target.config, target.inputs])
                if b["$ref"].startswith("card:")
            ]
            sources += [
                e.source for e in graph.edges if e.kind == "value" and e.target == target.id
            ]
            for source in sources:
                if source == target.id or source not in dominators.get(target.id, set()):
                    errors.append(
                        f"{target.id}: {source}'s value is not guaranteed on every incoming path. Pass branch outputs through Join."
                    )
        return errors

    def _function_cycles(self, workflow: Workflow) -> list[str]:
        active: set[str] = set()
        done: set[str] = set()

        def visit(name: str) -> None:
            if name in active:
                raise ContractError("Recursive function calls are not supported.")
            if name in done or name not in workflow.functions:
                return
            active.add(name)
            graph = workflow.graphs.get(workflow.functions[name]["graph"])
            for card in graph.cards.values() if graph else []:
                if card.kind in ("call", "if", "poll", "loop") and card.config.get("function"):
                    visit(card.config["function"])
            active.remove(name)
            done.add(name)

        try:
            for name in workflow.functions:
                visit(name)
        except ContractError as error:
            return [str(error)]
        return []

    def _access(
        self, workflow: Workflow, graph: Graph, cards: list[Card], seen: set[str]
    ) -> tuple[set[str], set[str]]:
        reads: set[str] = set()
        writes: set[str] = set()
        for card in cards:
            if card.kind == "variable":
                name = card.config["name"]
                if card.config.get("operation") == "get":
                    reads.add(name)
                else:
                    writes.add(name)
                    if card.config.get("operation") == "update":
                        reads.add(name)
            function = card.config.get("function")
            if function in workflow.functions and function not in seen:
                child = workflow.graphs[workflow.functions[function]["graph"]]
                r, w = self._access(workflow, child, list(child.cards.values()), seen | {function})
                reads |= r
                writes |= w
        return reads, writes

    def _parallel_conflicts(self, workflow: Workflow, graph: Graph) -> list[str]:
        errors = []
        for parallel in (c for c in graph.cards.values() if c.kind == "parallel"):
            branches = []
            for region in parallel.config["branches"]:
                cards = []
                for card in graph.cards.values():
                    owner = card.owner
                    while owner:
                        if owner == Owner(parallel.id, region):
                            cards.append(card)
                            break
                        owner = graph.cards[owner.card].owner
                branches.append(self._access(workflow, graph, cards, set()))
            for index, (reads, writes) in enumerate(branches):
                for other_reads, other_writes in branches[index + 1 :]:
                    conflicts = (writes & (other_reads | other_writes)) | (other_writes & reads)
                    if conflicts:
                        errors.append(
                            f"{parallel.id}: parallel global conflict: {', '.join(sorted(conflicts))}. Sequence these operations or return branch values through Join."
                        )
        return self._diagnostics(errors, graph)
