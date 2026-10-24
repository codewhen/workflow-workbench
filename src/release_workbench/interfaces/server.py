"""Localhost-only HTTP adapter. Execution and validation belong to application services."""

from __future__ import annotations

import contextlib
import copy
import difflib
import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from release_workbench.application.compiler import CompilationError
from release_workbench.application.runtime import Run
from release_workbench.application.skip_plan import plan_skips
from release_workbench.application.starters import TEMPLATES
from release_workbench.domain.cards import REGISTRY
from release_workbench.domain.models import Workflow
from release_workbench.infrastructure.documents import (
    MAX_BYTES,
    SCHEMA,
    DocumentStore,
    compile_document,
    digest,
    document_readiness,
    parse_document,
    render_document,
    validate_document_schema,
)
from release_workbench.infrastructure.drafts import DraftStore
from release_workbench.infrastructure.folder_picker import FolderPicker, WorkflowPicker
from release_workbench.infrastructure.library import Library
from release_workbench.infrastructure.services import LocalServices
from release_workbench.infrastructure.sessions import LocalSessions


class WorkbenchApplication:
    def __init__(self, project: Path, storage: Path):
        self.project, self.storage = project.resolve(), storage.resolve()
        self.library = Library(self.storage, self.project)
        from release_workbench.infrastructure.projects import register_starters

        register_starters(self.library)
        self.services = LocalServices()
        self.folder_picker = FolderPicker()
        self.workflow_picker = WorkflowPicker()
        self.drafts = DraftStore(self.storage / "drafts")
        self.runs: dict[str, Run] = {}
        self.run_roots: dict[str, Run] = {}
        self.lock = threading.RLock()
        self.sessions = LocalSessions(self.storage / "browser-sessions.json")
        self.token = self.sessions.token
        self.skip_previews: dict[str, dict[str, Any]] = {}

    def selected_run(self, key: str, context: str = "") -> Run | None:
        """Resolve an exact invocation, never alias children by their workflow ID."""
        if not context:
            return self.runs.get(key)
        source = self.library.file(key).resolve()
        pending = list(self.run_roots.values())
        while pending:
            run = pending.pop()
            if run.evidence.state["run_id"] == context:
                if not run.stack or run.stack[-1].resolve() != source:
                    raise ValueError("This execution belongs to a different workflow.")
                return run
            pending.extend(child for _, child in run.children)
        raise ValueError(
            "This execution is no longer available in this server session. Open the workflow definition or its saved report."
        )

    def configuration(self, key: str, context: str = "") -> dict[str, Any]:
        if context:
            run = self.selected_run(key, context)
            assert run is not None
            raw = run.workflow.raw
            return {
                "workflow": raw,
                "yaml": render_document(raw),
                "revision": run.fingerprint,
                "path": str(self.library.file(key)),
                "inspection": context,
                **document_readiness(raw),
            }
        record = DocumentStore(self.library.file(key)).read()
        return {
            **record,
            **document_readiness(record["workflow"]),
            "recovery": self.drafts.matching(key, record["revision"]),
        }

    def state(self, key: str, context: str = "") -> dict[str, Any]:
        run = self.selected_run(key, context)
        return (
            {
                **run.evidence.snapshot(),
                "busy": run.busy,
                "can_run_from_here": not run.busy
                and not any(item.busy for item in self.runs.values()),
                "paused": run.coordinator.paused,
                "report_base": "/reports/"
                + quote(str(run.evidence.directory.relative_to(self.storage / "runs")), safe="/"),
            }
            if run
            else {
                "status": "pending",
                "executions": {},
                "manual": {},
                "events": [],
                "busy": False,
                "paused": False,
            }
        )

    def skip_review(self, key: str, data: dict[str, Any], context: str = "") -> dict[str, Any]:
        record = DocumentStore(self.library.file(key)).read()
        if data.get("revision") and data["revision"] != record["revision"]:
            raise ValueError("Workflow changed. Reload before reviewing skips.")
        run = self.selected_run(key, context)
        if context and (not run or not run.busy):
            raise ValueError("Historical completed executions are read-only. Open the definition.")
        raw = copy.deepcopy(record["workflow"])
        if run and run.busy:
            snapshot = copy.deepcopy(run.workflow.raw)
            snapshot.pop("skip_cards", None)
            comparison = copy.deepcopy(raw)
            comparison.pop("skip_cards", None)
            if comparison != snapshot:
                raise ValueError("Workflow changed during execution. Reload before changing skips.")
        marks = raw.get("skip_cards", [])
        mark = {"graph": data["graph"], "card": data["card"]} if data.get("card") else None
        if mark:
            marks = (
                [x for x in marks if x != mark]
                if data.get("unmark")
                else marks + ([] if mark in marks else [mark])
            )
        raw.pop("skip_cards", None)
        workflow = compile_document(raw)
        plan = plan_skips(workflow, marks)

        # Expand statically resolved workspace children for review, without altering their YAML.
        def children(
            file: Path, workflow: Workflow, items: list[dict[str, Any]], seen: set[Path]
        ) -> list[dict[str, Any]]:
            result = []
            for item in items:
                card = workflow.graphs[item["graph"]].cards[item["card"]]
                if card.kind != "workspace" or not isinstance(card.config.get("path"), str):
                    continue
                child = (
                    file.parent / workflow.raw.get("workspace", ".") / card.config["path"]
                ).resolve()
                if child in seen or not child.is_file():
                    continue
                try:
                    nested = compile_document(DocumentStore(child).read()["workflow"])
                except (ValueError, OSError):
                    continue
                entries = [
                    {
                        "graph": g,
                        "card": c.id,
                        "name": c.name,
                        "scope": str(child),
                        "reasons": [
                            {
                                "reason": "child of a skipped parent",
                                "source": item["graph"] + "/" + item["card"],
                            }
                        ],
                    }
                    for g, graph in nested.graphs.items()
                    for c in graph.cards.values()
                ]
                result.extend(entries)
                result.extend(children(child, nested, entries, seen | {child}))
            return result

        plan["children"].extend(
            children(
                self.library.file(key),
                workflow,
                plan["affected"] + plan["children"],
                {self.library.file(key).resolve()},
            )
        )
        relevant = {(x["graph"], x["card"]) for x in plan["affected"]}
        if mark:
            relevant.add((mark["graph"], mark["card"]))
        executions = (
            sorted(
                (p, e["status"])
                for p, e in list(run.evidence.state["executions"].items())
                if (e["graph"], e["card"]) in relevant
            )
            if run and run.busy
            else []
        )
        plan.update(
            revision=record["revision"],
            run_id=run.evidence.state["run_id"] if run and run.busy else None,
            consumed=[
                p for p, status in executions if status not in {"running", "queued", "manual"}
            ],
        )
        return {
            "plan": plan,
            "signature": digest({"plan": plan, "executions": executions}),
            "request": data,
        }

    def mutation(
        self, route: str, key: str, data: dict[str, Any], context: str = ""
    ) -> dict[str, Any]:
        if (
            context
            and route
            not in {
                "open-workspace",
                "stop",
                "pause",
                "record",
                "skip",
                "skip-preview",
                "skip-confirm",
                "skip-plan",
            }
            and not (route == "run" and data.get("selection"))
        ):
            raise ValueError(
                "This page inspects an existing execution. Open its definition to edit or start a new run."
            )
        if route == "detect-inputs":
            from release_workbench.infrastructure.discovery import discover

            if any(run.busy for run in self.runs.values()):
                raise ValueError("Input discovery is disabled during execution.")
            file = self.library.file(key)
            return discover(DocumentStore(file).read()["workflow"], file.parent, self.services)
        if route == "pick-file":
            return {"path": self.workflow_picker.choose()}
        if route == "pick-folder":
            # Native dialogs must not block run controls or library requests.
            return {"path": self.folder_picker.choose()}
        with self.lock:
            if route == "register":
                path = Path(data["path"]).expanduser()
                if path.is_dir():
                    self.library.register_project(path)
                    return self.library.listing()
                return self.library.register(path)
            if route == "remove":
                project = data.get("project", "")
                keys = self.library.removal_keys(key=key, project=project)
                if any(self.runs[item].busy for item in keys if item in self.runs):
                    raise ValueError("Stop active runs before removing this workflow or project.")
                self.library.remove(key=key, project=project)
                return self.library.listing()
            if route == "create":
                return self.library.create(
                    Path(data.get("project", self.project)),
                    data["filename"],
                    data["name"],
                    data.get("template", "blank"),
                )
            if route == "organize":
                self.library.organize(data["action"], key, data)
                return self.library.listing()
            if route == "import":
                raw = parse_document(data["yaml"])
                validate_document_schema(raw)
                project = Path(data.get("project", self.project)).resolve()
                filename = data["filename"]
                entry = self.library.create(project, filename, raw["name"], "blank")
                file = self.library.file(entry["id"])
                from release_workbench.infrastructure.documents import atomic_write

                atomic_write(file, data["yaml"])
                return self.library.register(file)
            file = self.library.file(key)
            store = DocumentStore(file)
            if route == "open-workspace":
                from .workspace_navigation import child_definition

                raw = data.get("workflow") or store.read()["workflow"]
                run = self.selected_run(key, context)
                if context and run:
                    raw = run.workflow.raw
                execution_id = data.get("execution")
                if not execution_id and data.get("view") == "run" and run:
                    matching = [
                        path
                        for path, item in run.evidence.state["executions"].items()
                        if item.get("card") == data["card"] and item.get("graph") == data["graph"]
                    ]
                    execution_id = matching[-1] if matching else None
                execution = None
                if execution_id:
                    if not run or execution_id not in run.evidence.state["executions"]:
                        raise ValueError("The selected child execution is no longer available.")
                    execution = run.evidence.state["executions"][execution_id]
                child = child_definition(file, raw, data["graph"], data["card"], execution)
                entry = self.library.register(child)
                view = "edit" if data.get("view") == "edit" else "run"
                url = "/workflows/" + quote(entry["id"], safe="") + "/" + view
                if view == "run" and run and execution_id:
                    child_run = next(
                        (
                            child
                            for path, child in reversed(getattr(run, "children", []))
                            if path == execution_id
                        ),
                        None,
                    )
                    if child_run:
                        url += "?run=" + quote(child_run.evidence.state["run_id"], safe="")
                return {"id": entry["id"], "url": url}
            if route in {"skip-preview", "skip-confirm", "skip-plan", "skip"}:
                if route == "skip":
                    raise ValueError("Preview and confirm the affected cards before skipping.")
                run = self.selected_run(key, context)
                with run.control_lock if run else contextlib.nullcontext():
                    if route == "skip-plan" and context and run and not run.busy:
                        return {
                            **copy.deepcopy(run.skip_plan),
                            "token": "",
                            "revision": run.fingerprint,
                            "run_id": run.evidence.state["run_id"],
                            "consumed": [],
                        }
                    if route in {"skip-preview", "skip-plan"}:
                        review = self.skip_review(key, data, context)
                        token = secrets.token_urlsafe(32)
                        review.update(key=key, context=context)
                        if len(self.skip_previews) > 128:
                            self.skip_previews.clear()
                        self.skip_previews[token] = review
                        return {**review["plan"], "token": token}
                    preview = self.skip_previews.pop(data.get("token", ""), None)
                    if not preview or preview["key"] != key or preview["context"] != context:
                        raise ValueError("Skip preview expired. Review the affected cards again.")
                    current = self.skip_review(key, preview["request"], context)
                    if current["signature"] != preview["signature"]:
                        raise ValueError(
                            "Execution changed. Review the affected cards again before confirming."
                        )
                    plan = current["plan"]
                    if plan["blockers"]:
                        raise ValueError("\n".join(plan["blockers"]))
                    record = store.read()
                    raw = copy.deepcopy(record["workflow"])
                    if plan["marks"]:
                        raw["skip_cards"] = plan["marks"]
                    else:
                        raw.pop("skip_cards", None)
                    compile_document(raw)
                    saved = store.save(render_document(raw, record["yaml"]), plan["revision"])
                    if run and run.busy:
                        run.apply_skip_plan(plan)
                    return {"document": saved, "plan": plan, "state": self.state(key, context)}
            if route in ("validate", "save", "draft", "diagnostics"):
                if any(run.busy for run in self.runs.values()):
                    raise ValueError("Editing is disabled during execution.")
                current = store.read()
                raw = data.get("workflow") or parse_document(data["yaml"])
                validate_document_schema(raw)
                if route == "diagnostics":
                    return document_readiness(raw)
                validation_errors: list[str] = []
                issues: list[dict[str, str]] = []
                try:
                    compile_document(raw)
                except CompilationError as error:
                    validation_errors, issues = error.errors, error.issues
                    if route == "validate":
                        self.drafts.save(key, raw, current)
                        raise CompilationError(
                            [
                                "Draft backed up. You can save incomplete work in the updated editor; Run still requires the following fixes.",
                                *error.errors,
                            ],
                            error.issues,
                        ) from error
                yaml = render_document(raw, current["yaml"])
                if route == "save":
                    result = store.save(yaml, data["revision"])
                    self.runs.pop(key, None)
                    self.drafts.clear(key)
                    return {
                        **result,
                        "runnable": not validation_errors,
                        "validation_errors": validation_errors,
                        "issues": issues,
                    }
                return {
                    "workflow": raw,
                    "yaml": yaml,
                    "runnable": not validation_errors,
                    "validation_errors": validation_errors,
                    "issues": issues,
                    "diff": "".join(
                        difflib.unified_diff(
                            current["yaml"].splitlines(True),
                            yaml.splitlines(True),
                            fromfile="Saved",
                            tofile="Draft",
                        )
                    ),
                }
            if route == "run":
                if any(run.busy for run in self.runs.values()):
                    raise ValueError(
                        "Another workflow is executing. Stop it or wait before starting another."
                    )
                record = self.configuration(key, context) if context else store.read()
                if data.get("revision") != record["revision"]:
                    raise ValueError("Configuration changed. Save/reload before running.")
                workflow = compile_document(record["workflow"])
                selection = data.get("selection")
                if selection is not None and (
                    not isinstance(selection, dict)
                    or not isinstance(selection.get("graph"), str)
                    or not isinstance(selection.get("card"), str)
                ):
                    raise ValueError("Select a graph and executable card.")
                previous = self.selected_run(key, context) if selection else None
                run = Run(
                    workflow,
                    file.parent,
                    self.storage / "runs",
                    self.services,
                    data.get("inputs", {}),
                    interactive=True,
                    resume=data.get("resume"),
                    retry=data.get("retry", False),
                    stack=(file,),
                    selection=(selection["graph"], selection["card"]) if selection else None,
                )
                if selection:
                    from release_workbench.application.start_context import compatible
                    from release_workbench.infrastructure.run_checkpoints import latest_checkpoint

                    candidate = (
                        previous.evidence.snapshot()
                        if previous
                        else latest_checkpoint(self.storage / "runs", run.base_fingerprint)
                    )
                    if candidate and compatible(candidate, run.base_fingerprint):
                        run.checkpoint = candidate
                self.runs[key] = run
                self.run_roots[run.evidence.state["run_id"]] = run
                run.start()
                return self.state(key)
            elif route in {
                "stop",
                "pause",
                "record",
                "skip",
                "skip-preview",
                "skip-confirm",
                "skip-plan",
            }:
                selected = self.selected_run(key, context)
                if selected is None:
                    raise ValueError("No execution is available.")
                if route == "stop":
                    selected.stop(data.get("execution"))
                elif route == "skip":
                    selected.skip(data["graph"], data["card"], data.get("execution"))
                elif route == "pause":
                    selected.coordinator.paused = bool(data["paused"])
                else:
                    selected.record(data["execution"], data["note"], data.get("decision"))
            else:
                raise ValueError("Unknown action.")
            return self.state(key, context)


def create_server(
    project: Path, storage: Path, port: int = 0
) -> tuple[ThreadingHTTPServer, WorkbenchApplication]:
    """Construct a disposable server without starting it, for hosts and acceptance tests."""
    app = WorkbenchApplication(project, storage)
    static = Path(__file__).resolve().parents[1] / "static"

    class Handler(BaseHTTPRequestHandler):
        server: ThreadingHTTPServer

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send(
            self, data: bytes, status: int = 200, content_type: str = "application/json"
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def json(self, data: Any, status: int = 200) -> None:
            self.send(json.dumps(data, allow_nan=False).encode(), status)

        def authorized_host(self) -> bool:
            return self.headers.get("Host") in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            )

        def do_GET(self) -> None:
            if not self.authorized_host():
                self.json({"error": "Localhost access only."}, 403)
                return
            parsed = urlsplit(self.path)
            key = parse_qs(parsed.query).get("workflow", [""])[0]
            context = parse_qs(parsed.query).get("run", [""])[0]
            route = parsed.path
            try:
                if route == "/docs":
                    self.send_response(308)
                    self.send_header("Location", "/docs/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif route.startswith("/docs/"):
                    from .documentation import documentation_file

                    file, status = documentation_file(unquote(route[len("/docs/") :]))
                    if file is None:
                        self.json(
                            {
                                "error": "Documentation page not found. Build the bundled manual first."
                            },
                            404,
                        )
                    else:
                        self.send(
                            file.read_bytes(),
                            status,
                            mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                        )
                elif route == "/api/instance":
                    self.json({"application": "workflow-workbench-v3", "storage": str(app.storage)})
                elif route == "/api/library":
                    self.json(app.library.listing())
                elif route == "/api/catalog":
                    self.json(
                        {
                            "cards": [spec.metadata() for spec in REGISTRY.values()],
                            "templates": TEMPLATES,
                            "schema": SCHEMA,
                        }
                    )
                elif route == "/api/schema":
                    self.json(SCHEMA)
                elif route == "/api/config":
                    self.json(app.configuration(key, context))
                elif route == "/api/state":
                    from release_workbench.infrastructure.attachments import attachments

                    state = app.state(key, context)
                    run = app.selected_run(key, context)
                    if run:
                        state["attachments"] = attachments(
                            run.root,
                            run.workflow.raw,
                            key,
                            run.evidence.state.get("started", 0),
                        )
                    if context:
                        for attachment in state.get("attachments", []):
                            attachment["url"] += "&run=" + quote(context, safe="")
                    self.json(state)
                elif route == "/api/attachment":
                    from release_workbench.infrastructure.attachments import report_files

                    run = app.selected_run(key, context)
                    name = parse_qs(parsed.query).get("path", [""])[0]
                    files = (
                        report_files(
                            run.root,
                            run.workflow.raw.get("report_paths", []),
                            run.evidence.state.get("started", 0),
                        )
                        if run
                        else {}
                    )
                    file = files.get(name)
                    if file is None:
                        self.json({"error": "Report not found."}, 404)
                    else:
                        content = file.read_bytes()
                        if file.suffix.lower() in {".json", ".html", ".log", ".txt", ".csv"}:
                            assert run is not None
                            content = run.evidence.masker.text(
                                content.decode("utf-8", "replace")
                            ).encode("utf-8")
                        self.send_response(200)
                        self.send_header(
                            "Content-Type",
                            mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                        )
                        self.send_header("Content-Length", str(len(content)))
                        self.send_header("Content-Security-Policy", "sandbox allow-scripts")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        self.wfile.write(content)
                elif route == "/api/history":
                    records = []
                    for file in sorted((app.storage / "runs").glob("*/summary.json"), reverse=True):
                        value = json.loads(file.read_text(encoding="utf-8"))
                        records.append(
                            {k: value[k] for k in ("run_id", "name", "status", "fingerprint")}
                        )
                    self.json(records)
                elif route.startswith("/api/"):
                    self.json({"error": "Unknown endpoint."}, 404)
                else:
                    base = app.storage / "runs" if route.startswith("/reports/") else static
                    name = unquote(
                        route[len("/reports/") :]
                        if route.startswith("/reports/")
                        else route.lstrip("/") or "index.html"
                    )
                    from .application_routes import application_page

                    if application_page(route):
                        name = "index.html"
                    file = (base / name).resolve()
                    if not file.is_relative_to(base.resolve()) or not file.is_file():
                        self.json({"error": "File not found."}, 404)
                        return
                    content = file.read_bytes()
                    if file.name == "index.html":
                        content = content.replace(b"__TOKEN__", app.token.encode())
                    self.send(
                        content,
                        content_type=mimetypes.guess_type(file.name)[0]
                        or "application/octet-stream",
                    )
            except Exception as error:
                self.json(
                    {
                        "error": str(error),
                        "issues": error.issues if isinstance(error, CompilationError) else [],
                    },
                    400,
                )

        def do_POST(self) -> None:
            origin = self.headers.get("Origin")
            if (
                not self.authorized_host()
                or not app.sessions.accepts(self.headers.get("X-Workbench-Token"))
                or origin
                not in (
                    None,
                    f"http://localhost:{self.server.server_port}",
                    f"http://127.0.0.1:{self.server.server_port}",
                )
            ):
                self.json({"error": "Invalid local request token or origin."}, 403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BYTES:
                    raise ValueError("Request body must be between 1 byte and 1 MiB.")
                data = json.loads(self.rfile.read(size))
                parsed = urlsplit(self.path)
                key = parse_qs(parsed.query).get("workflow", [""])[0]
                context = parse_qs(parsed.query).get("run", [""])[0]
                self.json(app.mutation(parsed.path.removeprefix("/api/"), key, data, context))
            except Exception as error:
                self.json(
                    {
                        "error": str(error),
                        "issues": error.issues if isinstance(error, CompilationError) else [],
                    },
                    400,
                )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server, app


def serve(
    project: Path,
    storage: Path,
    port: int = 3104,
    open_browser: bool = True,
    workflow: str | None = None,
) -> None:
    import webbrowser

    from .dashboard import reuse_dashboard

    page = "workflows/" + quote(workflow, safe="") if workflow else "workspace"
    url = f"http://127.0.0.1:{port}/" + page
    if port and reuse_dashboard(project, storage, port):
        print(f"Opened existing Workbench dashboard: {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    server, app = create_server(project, storage, port)
    from release_workbench import __version__

    print(f"Workflow Workbench {__version__}: http://127.0.0.1:{port}/", flush=True)
    print(f"Storage: {storage}", flush=True)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/" + page)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        for run in app.runs.values():
            if run.busy:
                run.stop()
        for run in app.runs.values():
            if run.thread:
                run.thread.join(timeout=10)
    finally:
        server.server_close()
