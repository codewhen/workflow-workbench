"""Typed graph interpreter with explicit frames, ownership and hierarchical evidence."""

from __future__ import annotations

import asyncio
import copy
import datetime
import hashlib
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from release_workbench.domain.cards import get_spec
from release_workbench.domain.models import (
    Card,
    CardResult,
    Outcome,
    Workflow,
)
from release_workbench.domain.values import ContractError, TypedValue

from .coordinator import Coordinator
from .errors import SkipRequested
from .executors import EvidenceRequired, ExecutionFailure
from .frame import Frame
from .ports import Services
from .skip_plan import plan_skips


class Run:
    def __init__(
        self,
        workflow: Workflow,
        root: Path,
        storage: Path,
        services: Services,
        inputs: dict[str, Any] | None = None,
        interactive: bool = False,
        resume: str | None = None,
        retry: bool = False,
        coordinator: Coordinator | None = None,
        stack: tuple[Path, ...] = (),
        selection: tuple[str, str] | None = None,
        checkpoint: dict[str, Any] | None = None,
    ):
        self.workflow, self.root, self.storage = (
            workflow,
            (root / workflow.raw.get("workspace", ".")).resolve(),
            storage.resolve(),
        )
        if not self.root.is_dir():
            raise ValueError("Workflow workspace directory does not exist.")
        self.selection = selection
        self.checkpoint = checkpoint
        definitions = workflow.inputs
        if selection:
            if resume:
                raise ValueError("Start a new Run from here instead of resuming a workflow run.")
            graph_id, card_id = selection
            graph = workflow.graphs.get(graph_id)
            if graph is None or card_id not in graph.cards:
                raise ValueError("Select an executable card in this workflow.")
            card = graph.cards[card_id]
            if card.owner is not None or card.kind in {"break", "continue"}:
                raise ValueError(
                    card.name
                    + " belongs to a controlled body. Start from its enclosing Loop, Parallel or Try card instead."
                )
            if graph_id != "main":
                function = next(
                    item for item in workflow.functions.values() if item["graph"] == graph_id
                )
                definitions = function.get("inputs", {})
        self.inputs = self.parameters(definitions, inputs or {})
        self.globals = {
            name: copy.deepcopy(value["initial"]) for name, value in workflow.globals.items()
        }
        self.interactive, self.retry, self.stack = interactive, retry, stack
        self.coordinator = coordinator or Coordinator(workflow.concurrency)
        self.services, self.clock = services, services.clock
        self.cancelled = threading.Event()
        self.cancelled_paths: set[str] = set()
        self.skipped_paths: set[str] = set()
        self.control_lock = threading.RLock()
        self.skip_plan = plan_skips(workflow)
        if self.skip_plan["blockers"]:
            raise ValueError("\n".join(self.skip_plan["blockers"]))
        self.skipped_cards = {(x["graph"], x["card"]) for x in self.skip_plan["affected"]}
        self.manual_answers: dict[str, dict[str, Any]] = {}
        self.children: list[tuple[str, Run]] = []
        self.deadlines: dict[str, float] = {}
        environment = services.environment(workflow)
        self.environment = environment
        self.fingerprint = services.fingerprint(workflow, self.root, self.inputs)
        self.base_fingerprint = self.fingerprint
        if selection:
            self.fingerprint = hashlib.sha256(
                (self.fingerprint + "from_here" + repr(selection)).encode()
            ).hexdigest()
        run_id = (
            resume
            or datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        if Path(run_id).name != run_id or run_id in (".", ".."):
            raise ValueError("Invalid run ID.")
        directory = self.storage / run_id
        if resume:
            state = services.load_state(directory)
            if state.get("skip_plan_changed") or state["fingerprint"] != self.fingerprint:
                raise ValueError("Workflow, source or inputs changed. Start a new run.")
        else:
            state = {
                "run_id": run_id,
                "name": workflow.name,
                "fingerprint": self.fingerprint,
                "status": "pending",
                "executions": {},
                "events": [],
                "manual": {},
            }
        if selection:
            state["name"] = (
                workflow.name
                + " · Run from: "
                + workflow.graphs[selection[0]].cards[selection[1]].name
            )
            state["selection"] = {
                "mode": "from_here",
                "graph": selection[0],
                "card": selection[1],
                "name": workflow.graphs[selection[0]].cards[selection[1]].name,
            }
        state["base_fingerprint"] = self.base_fingerprint
        state["report_sources"] = {
            "workspace": str(self.root),
            "patterns": workflow.raw.get("report_paths", []),
        }
        state["manual"] = {}
        self.evidence = services.evidence(directory, state, workflow, environment)
        self.thread: threading.Thread | None = None
        self.evidence.state["skip_plan"] = copy.deepcopy(self.skip_plan)
        self.evidence.state["user_skips"] = copy.deepcopy(self.skip_plan["marks"])
        self._executing = False

    @staticmethod
    def parameters(definitions: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
        unexpected = supplied.keys() - definitions.keys()
        if unexpected:
            raise ContractError("Unknown inputs: " + ", ".join(sorted(unexpected)))
        values = {}
        for name, definition in definitions.items():
            if name not in supplied and "default" not in definition:
                raise ContractError("Required input: " + name)
            value = supplied.get(name, definition.get("default"))
            TypedValue.checked(value, definition["type"])
            values[name] = copy.deepcopy(value)
        return values

    def start(self) -> None:
        if self.busy:
            raise ValueError("Workflow is already running.")
        self.thread = threading.Thread(target=lambda: asyncio.run(self.execute()), daemon=True)
        self.thread.start()

    @property
    def busy(self) -> bool:
        return self._executing or (self.thread is not None and self.thread.is_alive())

    def stop(self, path: str | None = None) -> None:
        with self.control_lock:
            if path:
                self.cancelled_paths.add(path)
            else:
                self.cancelled.set()
            for parent_path, child in self.children:
                if path is None or parent_path == path or parent_path.startswith(path + "/"):
                    child.stop()
            self.evidence.emit("stop_requested", path or "root")

    def record(self, path: str, note: str, decision: Any = None) -> None:
        pending = self.evidence.state["manual"].get(path)
        if not pending:
            raise ValueError("This manual execution is no longer waiting.")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("Record evidence notes before continuing.")
        if pending["mode"] == "decision" and type(decision) is not bool:
            raise ValueError("Choose True or False.")
        self.manual_answers[path] = {"note": note, "decision": decision}

    def apply_skip_plan(self, plan: dict[str, Any]) -> None:
        """Called under control_lock after the document has been saved successfully."""
        self.skip_plan = copy.deepcopy(plan)
        self.skipped_cards = {(x["graph"], x["card"]) for x in plan["affected"]}
        for item in list(self.evidence.state["executions"].values()):
            if (item["graph"], item["card"]) in self.skipped_cards and item["status"] in {
                "running",
                "queued",
                "manual",
            }:
                self.skipped_paths.add(item["path"])
                if item["kind"] == "if":
                    item["skip_continuation"] = next(
                        (
                            x["next"]
                            for x in plan["continuations"]
                            if x["graph"] == item["graph"] and x["card"] == item["card"]
                        ),
                        None,
                    )
                for parent_path, child in self.children:
                    if parent_path == item["path"] or parent_path.startswith(item["path"] + "/"):
                        child.bypass("Skipped because of parent " + item["path"])
        self.evidence.state["user_skips"] = copy.deepcopy(plan["marks"])
        self.evidence.state["skip_plan"] = copy.deepcopy(plan)
        self.evidence.state["skip_plan_changed"] = True
        self.evidence.emit(
            "skip_plan_changed",
            "root",
            marks=plan["marks"],
            affected=plan["affected"],
            continuations=plan["continuations"],
        )
        self.evidence.save()

    def skip(self, graph: str, card_id: str, path: str | None = None) -> None:
        """Internal execution control. HTTP callers must use preview and confirmation."""
        with self.control_lock:
            if not self.busy:
                raise ValueError("Cards can only be skipped during an active run.")
            marks = self.skip_plan["marks"] + [{"graph": graph, "card": card_id}]
            plan = plan_skips(self.workflow, marks)
            if plan["blockers"]:
                raise ValueError("\n".join(plan["blockers"]))
            self.apply_skip_plan(plan)

    def bypass(self, reason: str) -> None:
        """Cancel an invocation as owned work, preserving its completed evidence."""
        with self.control_lock:
            self.skipped_paths.add("root")
            self.evidence.state["skip_parent"] = reason
            for _, child in self.children:
                child.bypass(reason)

    def check(self, path: str) -> None:
        if self.cancelled.is_set() or any(
            path == key or path.startswith(key + "/") for key in tuple(self.cancelled_paths)
        ):
            raise asyncio.CancelledError("Stopped by user.")
        if any(path == key or path.startswith(key + "/") for key in tuple(self.skipped_paths)):
            raise SkipRequested("Skipped by user.")
        for parent, deadline in list(self.deadlines.items()):
            if (
                path == parent or path.startswith(parent + "/")
            ) and self.clock.monotonic() >= deadline:
                raise ExecutionFailure("Configured time limit exceeded at " + parent)

    async def execute(self) -> int:
        with self.control_lock:
            self._executing = True
        self.evidence.state.pop("error", None)
        self.evidence.state.update(status="running", started=time.time())
        self.evidence.save()
        try:
            graph_id = self.selection[0] if self.selection else "main"
            graph = self.workflow.graphs[graph_id]
            frame = Frame(self, graph, self.inputs, "root/" + graph_id)
            if self.selection and self.checkpoint:
                from .start_context import restore_context

                restore_context(self, frame, self.selection[1], self.checkpoint)
            outcome = await self.walk(frame, self.selection[1] if self.selection else None)
            expected = "finish" if graph_id == "main" else "return"
            if outcome.signal != expected:
                raise ExecutionFailure(
                    "Run from here must reach " + ("Finish." if expected == "finish" else "Return.")
                )
            if graph_id != "main":
                function = next(
                    item for item in self.workflow.functions.values() if item["graph"] == graph_id
                )
                TypedValue.checked(outcome.value.value, function["returns"])
            with self.control_lock:
                self.evidence.state.update(status="passed", result=outcome.value.to_dict())
            visited = {
                entry["card"]
                for entry in self.evidence.state["executions"].values()
                if entry["graph"] == "main"
            }
            for card in [] if self.selection else self.workflow.graphs["main"].cards.values():
                if card.id not in visited:
                    path = "root/main/" + card.id
                    self.evidence.state["executions"][path] = {
                        "card": card.id,
                        "graph": "main",
                        "name": card.name,
                        "kind": card.kind,
                        "path": path,
                        "status": "skipped",
                        "started": time.time(),
                        "seconds": 0,
                        "attempts": [],
                        "reason": next(
                            (
                                "; ".join(r["reason"] + ": " + r["source"] for r in x["reasons"])
                                for x in self.skip_plan["affected"]
                                if x["graph"] == "main" and x["card"] == card.id
                            ),
                            "Execution followed another branch or the loop ran zero times.",
                        ),
                    }
        except EvidenceRequired as error:
            self.evidence.state.update(status="blocked", error=str(error))
        except asyncio.CancelledError:
            self.evidence.state.update(status="cancelled", error="Stopped by user.")
            if self.evidence.state.get("skip_parent"):
                self.evidence.state.update(
                    status="skipped", reason=self.evidence.state["skip_parent"]
                )
                visited = {
                    (e["graph"], e["card"]) for e in self.evidence.state["executions"].values()
                }
                for g, graph in self.workflow.graphs.items():
                    for c, card in graph.cards.items():
                        if (g, c) not in visited:
                            path = "root/" + g + "/" + c
                            self.evidence.state["executions"][path] = {
                                "graph": g,
                                "card": c,
                                "name": card.name,
                                "kind": card.kind,
                                "path": path,
                                "status": "skipped",
                                "attempts": [],
                                "started": time.time(),
                                "seconds": 0,
                                "reason": self.evidence.state["skip_parent"],
                            }

        except Exception as error:
            self.evidence.state.update(status="failed", error=self.evidence.masker.text(str(error)))
        finally:
            self.evidence.state.update(
                finished=time.time(), globals=self.evidence.masker.object(self.globals)
            )
            self.evidence.state["manual"] = {}
            try:
                self.evidence.report()
            finally:
                with self.control_lock:
                    self._executing = False
        return {"passed": 0, "failed": 1, "blocked": 2, "cancelled": 130, "skipped": 0}[
            self.evidence.state["status"]
        ]

    async def walk(self, frame: Frame, first: str | None = None) -> Outcome:
        if first is None:
            first = next(card.id for card in frame.graph.cards.values() if card.kind == "start")
        current = first
        while True:
            self.check(frame.path)
            card = frame.graph.cards[current]
            outcome = await self.node(frame, card)
            await self.clock.sleep(0)
            frame.results[current] = outcome.value
            if outcome.signal:
                return outcome
            continuation = next(
                (
                    x["next"]
                    for x in self.skip_plan["continuations"]
                    if x["graph"] == frame.graph.id and x["card"] == current
                ),
                None,
            )
            execution = self.evidence.state["executions"].get(frame.path + "/" + current, {})
            continuation = execution.get("skip_continuation", continuation)
            if card.kind == "if" and continuation and execution.get("status") == "skipped":
                current = continuation
                continue
            edges = frame.graph.outgoing(current, outcome.port)
            if len(edges) != 1:
                raise ExecutionFailure(f"{current}.{outcome.port}: expected one next card.")
            edge = edges[0]
            if edge.target_port == "next_iteration":
                return Outcome(signal="continue")
            current = edge.target

    async def node(self, frame: Frame, definition: Card) -> Outcome:
        path = frame.path + "/" + definition.id
        old = self.evidence.state["executions"].get(path)
        if old and old["status"] in ("passed", "recorded"):
            if old.get("redacted_result"):
                raise EvidenceRequired(
                    "Saved output was redacted; explicitly start a new run to recompute it safely."
                )
            for key, value in old.get("global_changes", {}).items():
                self.globals[key] = copy.deepcopy(value)
            self.evidence.emit("resumed", path)
            return Outcome.from_dict(old["outcome"])
        if old and old["status"] == "skipped" and old.get("outcome"):
            return Outcome.from_dict(old["outcome"])
        if (
            old
            and old["status"] in ("running", "cancelled", "failed", "blocked")
            and not self.retry
        ):
            raise EvidenceRequired(
                "Interrupted or failed execution requires an explicit retry: " + path
            )
        context = frame.for_node(path)
        card = definition
        entry: dict[str, Any] = {
            "card": card.id,
            "graph": frame.graph.id,
            "name": card.name,
            "kind": card.kind,
            "status": "running",
            "started": time.time(),
            "path": path,
            "attempts": [],
            "expected_seconds": card.settings.get("expected_seconds"),
            "global_changes": {},
        }
        if old:
            entry["previous_attempt"] = copy.deepcopy(old)
        with self.control_lock:
            self.evidence.state["executions"][path] = entry
        started = self.clock.monotonic()
        self.evidence.emit("started", path, card=card.id, graph=frame.graph.id)
        self.evidence.save()
        try:
            with self.control_lock:
                if (frame.graph.id, definition.id) in self.skipped_cards:
                    self.skipped_paths.add(path)
                    if card.kind == "if":
                        entry["skip_continuation"] = next(
                            (
                                x["next"]
                                for x in self.skip_plan["continuations"]
                                if x["graph"] == frame.graph.id and x["card"] == card.id
                            ),
                            None,
                        )
            self.check(path)
            await self.coordinator.ready(lambda: self.check(path))
            config = context.resolve(definition.config)
            inputs = context.resolve(definition.inputs)
            for edge in frame.graph.edges:
                if edge.kind == "value" and edge.target == definition.id:
                    value = context.reference("card:" + edge.source, edge.path)
                    if edge.target_port.startswith("config:"):
                        config[edge.target_port[7:]] = value
                    else:
                        inputs[edge.target_port.removeprefix("input:")] = value
            if definition.kind == "join":
                inputs["branches"] = context.reference("card:" + config["parallel"])
            context.inputs = copy.deepcopy(frame.inputs) if definition.kind == "start" else inputs
            card = replace(definition, config=config, inputs=inputs)
            timeout = (
                card.config.get("timeout")
                if card.kind in ("loop", "poll")
                else card.settings.get("timeout")
            )
            if timeout is not None:
                self.deadlines[path] = self.clock.monotonic() + timeout
            retry = card.settings.get("retry", {"attempts": 1})
            for attempt in range(retry["attempts"]):
                try:
                    validation_errors = get_spec(card.kind).validate(card)
                    if validation_errors:
                        raise ExecutionFailure("; ".join(validation_errors))
                    outcome = await context.execute(card)
                    with self.control_lock:
                        context.check()
                        entry.update(
                            status="recorded" if card.kind == "manual" else "passed",
                            outcome=outcome.to_dict(),
                            redacted_result=self.evidence.masker.contains(outcome.to_dict()),
                            result=CardResult(
                                "recorded" if card.kind == "manual" else "passed", outcome, (path,)
                            ).to_dict(),
                        )
                        entry["attempts"].append({"status": entry["status"], "number": attempt + 1})
                    break
                except (EvidenceRequired, asyncio.CancelledError):
                    raise
                except Exception as error:
                    entry["attempts"].append(
                        {
                            "status": "failed",
                            "number": attempt + 1,
                            "error": self.evidence.masker.text(str(error)),
                        }
                    )
                    self.evidence.emit(
                        "attempt_failed", path, attempt=attempt + 1, error=str(error)
                    )
                    if attempt + 1 == retry["attempts"] or (
                        retry.get("errors_contain")
                        and not any(text in str(error) for text in retry["errors_contain"])
                    ):
                        raise ExecutionFailure(str(error)) from error
                    await context.sleep(retry.get("delay", 1) * retry.get("backoff", 1) ** attempt)
            # Collect only descendants' declared writes, never unrelated parallel state.
            for child_path, child in self.evidence.state["executions"].items():
                if child_path.startswith(path + "/"):
                    entry["global_changes"].update(child.get("global_changes", {}))
            entry["redacted_result"] = entry.get(
                "redacted_result", False
            ) or self.evidence.masker.contains(entry["global_changes"])
            return outcome
        except asyncio.CancelledError:
            skipping = (
                not self.cancelled.is_set()
                and any(
                    path == key or path.startswith(key + "/") for key in tuple(self.skipped_paths)
                )
                and not any(
                    path == key or path.startswith(key + "/") for key in tuple(self.cancelled_paths)
                )
            )
            if not skipping:
                with self.control_lock:
                    entry.update(status="cancelled", error="Stopped by user.")
                raise
            reasons: list[dict[str, str]] = next(
                (
                    x["reasons"]
                    for x in self.skip_plan["affected"]
                    if x["graph"] == frame.graph.id and x["card"] == card.id
                ),
                [],
            )
            with self.control_lock:
                entry.update(
                    status="skipped",
                    user_skip=True,
                    reason="; ".join(x["reason"] + ": " + x["source"] for x in reasons)
                    or "Child of a skipped parent.",
                )
            self.evidence.state["manual"].pop(path, None)
            if path not in self.skipped_paths:
                raise
            outcome = Outcome(port="done" if card.kind in {"loop", "parallel", "try"} else "next")
            entry["outcome"] = outcome.to_dict()
            if card.kind == "if" and "skip_continuation" not in entry:
                entry["skip_continuation"] = next(
                    (
                        x["next"]
                        for x in self.skip_plan["continuations"]
                        if x["graph"] == frame.graph.id and x["card"] == card.id
                    ),
                    None,
                )
            return outcome
        except EvidenceRequired as error:
            with self.control_lock:
                entry.update(status="blocked", error=str(error))
            raise
        except Exception as error:
            with self.control_lock:
                entry.update(status="failed", error=self.evidence.masker.text(str(error)))
            raise ExecutionFailure(str(error)) from error
        finally:
            entry.setdefault("result", CardResult(entry["status"], Outcome(), (path,)).to_dict())
            self.deadlines.pop(path, None)
            entry["seconds"] = round(self.clock.monotonic() - started, 3)
            self.evidence.emit("finished", path, status=entry["status"], seconds=entry["seconds"])
            self.evidence.save()
