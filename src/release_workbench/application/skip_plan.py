"""Pure, shared planning for persisted card skips. Flow is not a value dependency."""

from __future__ import annotations

from typing import Any

from release_workbench.domain.models import Card, Graph, Workflow

FORBIDDEN = {"start", "finish", "return", "break", "continue"}


def references(value: Any) -> set[str]:
    if isinstance(value, dict):
        ref = value.get("$ref", "")
        found = {ref[5:]} if isinstance(ref, str) and ref.startswith("card:") else set()
        return found.union(*(references(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(references(v) for v in value))
    return set()


def plan_skips(workflow: Workflow, marks: list[dict[str, str]] | None = None) -> dict[str, Any]:
    marks = workflow.raw.get("skip_cards", []) if marks is None else marks
    affected: dict[tuple[str, str], dict[str, Any]] = {}
    blockers: list[str] = []
    continuations: dict[tuple[str, str], str] = {}

    def add(g: str, c: str, reason: str, source: str) -> None:
        key = (g, c)
        item = affected.setdefault(
            key, {"graph": g, "card": c, "name": workflow.graphs[g].cards[c].name, "reasons": []}
        )
        detail = {"reason": reason, "source": source}
        if detail not in item["reasons"]:
            item["reasons"].append(detail)

    for mark in marks:
        g, c = mark["graph"], mark["card"]
        if g not in workflow.graphs or c not in workflow.graphs[g].cards:
            blockers.append(f"Unknown skip card: {g}/{c}.")
        elif workflow.graphs[g].cards[c].kind in FORBIDDEN:
            blockers.append(f"{g}/{c}: this control card cannot be marked to skip.")
        else:
            add(g, c, "explicitly selected", f"{g}/{c}")

    # A branch merge must postdominate both branch entries, in the same owned scope.
    def branch_region(graph: Graph, card: Card) -> tuple[str | None, set[str]]:
        starts = [
            e.target
            for e in graph.edges
            if e.kind == "flow" and e.source == card.id and e.source_port in {"true", "false"}
        ]
        nodes = {c.id for c in graph.cards.values() if c.owner == card.owner and c.id != card.id}
        successors = {
            n: {
                e.target
                for e in graph.edges
                if e.kind == "flow"
                and e.source == n
                and e.source_port in {"next", "done", "true", "false"}
                and e.target in nodes
                and e.target_port != "next_iteration"
            }
            for n in nodes
        }
        # Fixed-point postdominators avoid enumerating exponentially many branch paths.
        post = {n: ({n} if not successors[n] else set(nodes)) for n in nodes}
        changed = True
        while changed:
            changed = False
            for n in sorted(nodes):
                value = {n} | (
                    set.intersection(*(post[x] for x in successors[n])) if successors[n] else set()
                )
                if value != post[n]:
                    post[n] = value
                    changed = True
        common = (
            set.intersection(*(post.get(s, set()) for s in starts)) if len(starts) == 2 else set()
        )

        # First common node is the one from which every other common node is reachable.
        def reachable(start: str, stop: str | None = None) -> set[str]:
            seen, pending = set(), [start]
            while pending:
                n = pending.pop()
                if n == stop or n in seen:
                    continue
                seen.add(n)
                pending.extend(
                    e.target
                    for e in graph.edges
                    if e.kind == "flow"
                    and e.source == n
                    and e.target_port != "next_iteration"
                    and graph.cards[e.target].owner == card.owner
                    and e.source_port in {"next", "done", "true", "false"}
                )
            return seen

        first = [n for n in common if common <= reachable(n)]
        if len(first) != 1:
            return None, set()
        continuation = first[0]
        return continuation, set().union(*(reachable(s, continuation) for s in starts))

    changed = True
    while changed:
        before = set(affected)
        for g, graph in workflow.graphs.items():
            for c, card in graph.cards.items():
                key = (g, c)
                if card.owner and (g, card.owner.card) in affected:
                    add(g, c, "child of a skipped parent", f"{g}/{card.owner.card}")
                inherited = key in affected and any(
                    r["reason"] == "child of a skipped parent" for r in affected[key]["reasons"]
                )
                if key in affected and card.kind == "if" and not inherited:
                    continuation, region = branch_region(graph, card)
                    if continuation is None:
                        message = (
                            f"{g}/{c}: no unambiguous common continuation for both If branches."
                        )
                        if message not in blockers:
                            blockers.append(message)
                    else:
                        continuations[key] = continuation
                        for child in region:
                            add(g, child, "child of a skipped parent", f"{g}/{c}")
                deps = references(card.config) | references(card.inputs)
                deps |= {e.source for e in graph.edges if e.kind == "value" and e.target == c}
                if card.kind == "join":
                    deps.add(card.config.get("parallel", ""))
                for dep in deps:
                    if (g, dep) in affected and key not in affected:
                        if card.kind not in {"finish", "return"}:
                            add(g, c, "dependent on a missing result", f"{g}/{dep}")
        changed = before != set(affected)

    for (g, c), item in affected.items():
        if any(r["reason"] == "child of a skipped parent" for r in item["reasons"]):
            continuations.pop((g, c), None)
            blockers = [
                b
                for b in blockers
                if b != f"{g}/{c}: no unambiguous common continuation for both If branches."
            ]

    # Terminals are validated after closure, so bypassed child Returns do not block.
    for g, graph in workflow.graphs.items():
        for c, card in graph.cards.items():
            if card.kind not in {"finish", "return"} or (g, c) in affected:
                continue
            deps = references(card.config) | references(card.inputs)
            deps |= {e.source for e in graph.edges if e.kind == "value" and e.target == c}
            for dep in sorted(deps):
                if (g, dep) in affected:
                    blockers.append(f"{g}/{c}: required {card.kind} loses its result from {dep}.")

    for g, c in affected:
        if any(r["reason"] == "child of a skipped parent" for r in affected[(g, c)]["reasons"]):
            continue
        card = workflow.graphs[g].cards[c]
        if card.kind in {"if", "finish", "return", "break", "continue"}:
            continue
        port = "done" if card.kind in {"parallel", "try", "loop"} else "next"
        edges = workflow.graphs[g].outgoing(c, port)
        if len(edges) == 1:
            continuations[(g, c)] = edges[0].target

    children = []

    def describe_children(g: str, c: str, scope: str, seen: set[str]) -> None:
        card = workflow.graphs[g].cards[c]
        function = card.config.get("function")
        if function in workflow.functions and function not in seen:
            child_graph = workflow.functions[function]["graph"]
            for child in workflow.graphs[child_graph].cards.values():
                child_scope = scope + " → " + function
                children.append(
                    {
                        "graph": child_graph,
                        "card": child.id,
                        "name": child.name,
                        "scope": child_scope,
                        "reasons": [{"reason": "child of a skipped parent", "source": scope}],
                    }
                )
                describe_children(
                    child_graph, child.id, child_scope + "/" + child.id, seen | {function}
                )
        if card.kind == "workspace":
            path = card.config.get("path")
            children.append(
                {
                    "graph": g,
                    "card": c,
                    "name": "Entire child workspace",
                    "scope": scope
                    + " → "
                    + (
                        path if isinstance(path, str) else "dynamic workspace (contents unresolved)"
                    ),
                    "reasons": [{"reason": "child of a skipped parent", "source": scope}],
                }
            )

    for g, c in list(affected):
        describe_children(g, c, f"{g}/{c}", set())
    return {
        "marks": marks,
        "affected": list(affected.values()),
        "children": children,
        "continuations": [
            {"graph": g, "card": c, "next": n} for (g, c), n in continuations.items()
        ],
        "blockers": blockers,
    }
