"""Thread-safe event evidence, secret masking, and portable script-free reports."""

from __future__ import annotations

import copy
import html
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from release_workbench.application.ports import Masker

from .documents import atomic_write


class SecretMasker:
    def __init__(self, values: list[str]):
        self.values = sorted({value for value in values if value}, key=len, reverse=True)

    def text(self, text: str) -> str:
        for value in self.values:
            text = text.replace(value, "[REDACTED]")
        return text

    def object(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.text(data)
        if type(data) in (int, float) and str(data) in self.values:
            return "[REDACTED]"
        if isinstance(data, list):
            return [self.object(item) for item in data]
        if isinstance(data, dict):
            return {key: self.object(item) for key, item in data.items()}
        return data

    def contains(self, data: Any) -> bool:
        return self.object(data) != data


class EvidenceStore:
    def __init__(self, directory: Path, state: dict[str, Any], masker: SecretMasker):
        self.directory, self.state = directory, state
        self.masker: Masker = masker
        self.lock = threading.RLock()
        self.pending_logs: dict[str, str] = {}
        self.observers: list[
            tuple[Callable[[str, str], None], Callable[[dict[str, Any]], None]]
        ] = []
        directory.mkdir(parents=True, exist_ok=True)

    def observe(
        self, log: Callable[[str, str], None], event: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        observer = (log, event)
        self.observers.append(observer)

        def remove() -> None:
            if observer in self.observers:
                self.observers.remove(observer)

        return remove

    def emit(self, kind: str, path: str, **data: Any) -> None:
        import datetime

        event = self.masker.object(
            {
                "time": datetime.datetime.now(datetime.UTC).isoformat(),
                "kind": kind,
                "execution": path,
                **data,
            }
        )
        with self.lock:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, allow_nan=False) + "\n")
            self.state.setdefault("events", []).append(event)
            self.state["events"] = self.state["events"][-500:]
            for _, listener in tuple(self.observers):
                listener(copy.deepcopy(event))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self.masker.object(copy.deepcopy(self.state))

    def save(self) -> None:
        with self.lock:
            atomic_write(
                self.directory / "summary.json",
                json.dumps(self.snapshot(), indent=2, allow_nan=False),
            )

    def log(self, path: str, text: str) -> None:
        from .documents import digest

        name = digest(path)[:20] + ".log"
        with self.lock:
            raw = self.pending_logs.get(path, "") + text
            retained = 0
            for secret in self.masker.values:
                for size in range(1, min(len(secret), len(raw) + 1)):
                    if raw.endswith(secret[:size]):
                        retained = max(retained, size)
            self.pending_logs[path] = raw[-retained:] if retained else ""
            safe = self.masker.text(raw[:-retained] if retained else raw)
            with (self.directory / name).open("a", encoding="utf-8") as stream:
                stream.write(safe)
            entry = self.state["executions"].get(path)
            if entry is not None:
                entry["log"] = name
                entry["tail"] = (entry.get("tail", "") + safe)[-16000:]
            for listener, _ in tuple(self.observers):
                listener(path, safe)

    def report(self) -> Path:
        # A terminal prefix of a declared secret is also redacted.
        for path, pending in list(self.pending_logs.items()):
            if pending:
                self.pending_logs[path] = ""
                self.log(path, "[REDACTED]")
        from .attachments import snapshot_reports

        self.state["attachments"] = snapshot_reports(self.directory, self.state, self.masker)
        self.save()
        state = self.snapshot()

        def escape(value: Any) -> str:
            return html.escape(str(value))

        rows = []
        for path, value in state.get("executions", {}).items():
            evidence = f'<a href="{escape(value["log"])}">Log</a>' if value.get("log") else ""
            reason = "<p>" + escape(value["reason"]) + "</p>" if value.get("reason") else ""
            rows.append(
                f'<tr><td>{escape(path)}</td><td class="{escape(value["status"])}">{escape(value["status"])}</td><td>{escape(value.get("seconds", ""))}</td><td>{evidence}{reason}<pre>{escape(json.dumps(value.get("outcome", value.get("error", "")), indent=2))}</pre></td></tr>'
            )
        page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Workflow report</title><style>body{font:16px/1.5 system-ui;background:#f5f8f9;color:#182a30;max-width:1200px;margin:auto;padding:24px}table{width:100%;border-collapse:collapse;background:white}td,th{padding:12px;border-bottom:1px solid #cbd7db;text-align:left;vertical-align:top;overflow-wrap:anywhere}pre{white-space:pre-wrap;max-width:65ch;overflow-wrap:anywhere}.passed,.recorded{color:#146040}.failed{color:#a12424}a{color:#165c73}@media(max-width:700px){table,tr,td{display:block}thead{display:none}body{padding:16px}}</style>'
        links = "".join(
            f'<li><a href="{escape(item["snapshot"])}">{escape(item["path"])}</a></li>'
            for item in state.get("attachments", [])
            if item.get("snapshot")
        )
        page += "<h2>Report attachments</h2><ul>" + links + "</ul>" if links else ""
        warning = (
            "<p>Cards were skipped by the user. This run does not verify the full workflow.</p>"
            if state.get("user_skips")
            or state.get("skip_parent")
            or any(e.get("user_skip") for e in state.get("executions", {}).values())
            else ""
        )
        page += f"<h1>{escape(state['name'])}</h1><p>{escape(state['status'])} · {escape(state['run_id'])}</p>{warning}<p>Workflow fingerprint: {escape(state['fingerprint'])}</p><table><thead><tr><th>Execution</th><th>Status</th><th>Seconds</th><th>Evidence / result</th></tr></thead><tbody>{''.join(rows)}</tbody></table></html>"
        atomic_write(self.directory / "report.html", page)
        return self.directory / "report.html"
