"""Restore completed upstream data without re-executing earlier operations."""

from __future__ import annotations

import copy
import hashlib
from typing import TYPE_CHECKING, Any

from release_workbench.domain.values import TypedValue

if TYPE_CHECKING:
    from .frame import Frame
    from .runtime import Run


def compatible(state: dict[str, Any], fingerprint: str) -> bool:
    """Require identical workflow, source, inputs, secrets and workspace."""
    if state.get("skip_plan_changed"):
        return False
    if state.get("base_fingerprint"):
        return state["base_fingerprint"] == fingerprint
    selection = state.get("selection")
    expected = fingerprint
    if selection:
        marker = "from_here" if selection.get("mode") == "from_here" else ""
        expected = hashlib.sha256(
            (fingerprint + marker + repr((selection["graph"], selection["card"]))).encode()
        ).hexdigest()
    return state.get("fingerprint") == expected


def restore_context(run: Run, frame: Frame, first: str, source: dict[str, Any]) -> None:
    if not compatible(source, run.base_fingerprint):
        return
    graph = frame.graph
    # Reuse only actual ancestors of the starting card. Loop back edges never
    # make results from later iterations appear to be upstream evidence.
    upstream: set[str] = set()
    pending = [first]
    while pending:
        target = pending.pop()
        for edge in graph.edges:
            if edge.kind != "flow" or edge.target != target or edge.target_port == "next_iteration":
                continue
            if edge.source != first and edge.source not in upstream:
                upstream.add(edge.source)
                pending.append(edge.source)
    prefix = frame.path + "/"
    saved = source.get("input_context", {})
    results = {
        key: copy.deepcopy(value)
        for key, value in saved.get("results", {}).items()
        if key in upstream
    }
    changes: dict[str, Any] = {}
    # Chained partial runs preserve their previously imported variable state.
    for key, item in saved.get("global_changes", {}).items():
        if key in upstream:
            changes[key] = copy.deepcopy(item)
    entries = [
        item
        for path, item in source.get("executions", {}).items()
        if path.startswith(prefix)
        and "/" not in path[len(prefix) :]
        and item.get("graph") == graph.id
        and item.get("card") in upstream
    ]
    for entry in sorted(entries, key=lambda item: item.get("started", 0)):
        card = entry["card"]
        # A later failure invalidates any previously imported value for it.
        results.pop(card, None)
        changes.pop(card, None)
        if entry.get("status") not in {"passed", "recorded"} or entry.get("redacted_result"):
            continue
        outcome = entry.get("outcome", {})
        if "value" in outcome:
            results[card] = copy.deepcopy(outcome["value"])
            changes[card] = copy.deepcopy(entry.get("global_changes", {}))
    for card, data in results.items():
        frame.results[card] = TypedValue.from_dict(data)
    for item in changes.values():
        run.globals.update(copy.deepcopy(item))
    if results or changes:
        run.evidence.state["input_context"] = {
            "source_run": source["run_id"],
            "results": results,
            "global_changes": changes,
        }
        run.evidence.emit(
            "reused_upstream_data", frame.path, source_run=source["run_id"], cards=sorted(results)
        )
