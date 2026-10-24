"""Preview-only multi-project workflow library; organizing entries never moves files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ruamel.yaml.error import YAMLError

from release_workbench.application.starters import starter
from release_workbench.domain.library_folders import FolderOrganizer

from .documents import (
    DocumentStore,
    atomic_write,
    compile_document,
    digest,
    render_document,
    validate_document_schema,
)


class Library:
    def __init__(self, storage: Path, project: Path):
        self.storage = storage.resolve()
        self.path = self.storage / "library.json"
        self.data = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {"projects": [], "entries": [], "folders": []}
        )
        self.data.setdefault("hidden_projects", [])
        self.data.setdefault("hidden_files", [])
        self.register_project(project, restore=False)

    def save(self) -> None:
        atomic_write(self.path, json.dumps(self.data, indent=2))

    def organize(self, action: str, key: str, request: dict[str, Any]) -> None:
        updated = FolderOrganizer(self.data).apply(action, key, request)
        atomic_write(self.path, json.dumps(updated, indent=2))
        self.data = updated

    def register_project(self, project: Path, *, restore: bool = True) -> None:
        project = project.resolve()
        if not restore and str(project) in self.data["hidden_projects"]:
            return
        if not project.is_dir():
            raise ValueError("Project folder does not exist.")
        if restore:
            self.data["hidden_projects"] = [
                item for item in self.data["hidden_projects"] if item != str(project)
            ]
        if str(project) not in self.data["projects"]:
            self.data["projects"].append(str(project))
        for file in sorted([*project.glob("*.yaml"), *project.glob("*.yml")]):
            self.register(file, validate=False, restore=restore)
        self.save()

    def register(
        self,
        file: Path,
        validate: bool = True,
        *,
        restore: bool = True,
        _visited: set[Path] | None = None,
    ) -> dict[str, Any]:
        file = file.resolve()
        visited = _visited if _visited is not None else set()
        if not restore and str(file) in self.data["hidden_files"]:
            return {}
        if validate:
            validate_document_schema(DocumentStore(file).read()["workflow"])
        if restore:
            self.data["hidden_files"] = [
                item for item in self.data["hidden_files"] if item != str(file)
            ]
        key = digest(str(file).encode())[:20]
        entry = next((item for item in self.data["entries"] if item["path"] == str(file)), None)
        if entry is None:
            entry = {"id": key, "path": str(file), "folder": ""}
            self.data["entries"].append(entry)
        if file not in visited:
            visited.add(file)
            self._register_dependencies(file, restore=restore, visited=visited)
        self.save()
        return entry

    def _register_dependencies(self, file: Path, *, restore: bool, visited: set[Path]) -> None:
        """Discover available child definitions using execution's folder rules."""
        try:
            raw = DocumentStore(file).read()["workflow"]
            validate_document_schema(raw)
        except (ValueError, OSError, YAMLError):
            return
        metadata = raw.get("library", {})
        folder = metadata.get("folder", "")
        parts = folder.split("/") if folder else []
        if parts and all(part.strip() and part not in {".", "..", "*"} for part in parts):
            for index in range(1, len(parts) + 1):
                ancestor = "/".join(parts[:index])
                if ancestor not in self.data["folders"]:
                    self.data["folders"].append(ancestor)
            entry = next(item for item in self.data["entries"] if item["path"] == str(file))
            if not entry["folder"]:
                entry["folder"] = folder
        workspace = (file.parent / raw.get("workspace", ".")).resolve()
        paths = list(metadata.get("imports", []))
        for graph in raw["graphs"].values():
            for card in graph["cards"]:
                if card["kind"] != "workspace":
                    continue
                path = card.get("config", {}).get("path")
                if not isinstance(path, str) or not path.strip():
                    continue
                paths.append(path)
        for path in paths:
            child = (workspace / path).resolve()
            if child in visited or not child.is_file():
                continue
            try:
                self.register(child, restore=restore, _visited=visited)
            except (ValueError, OSError, YAMLError):
                # An unavailable child must not prevent importing its parent.
                continue

    def removal_keys(self, *, key: str = "", project: str = "") -> set[str]:
        """Resolve registered targets without accepting arbitrary filesystem deletion."""
        if project:
            path = str(Path(project).expanduser().resolve())
            if path not in self.data["projects"]:
                raise ValueError("Project is not registered.")
            return {
                entry["id"]
                for entry in self.data["entries"]
                if Path(entry["path"]).is_relative_to(Path(path))
            }
        self.file(key)
        return {key}

    def remove(self, *, key: str = "", project: str = "") -> None:
        """Forget Home entries, preserving files, drafts and historical evidence."""
        keys = self.removal_keys(key=key, project=project)
        paths = {entry["path"] for entry in self.data["entries"] if entry["id"] in keys}
        self.data["hidden_files"] = sorted(set(self.data["hidden_files"]) | paths)
        self.data["entries"] = [entry for entry in self.data["entries"] if entry["id"] not in keys]
        if project:
            path = str(Path(project).expanduser().resolve())
            self.data["projects"].remove(path)
            self.data["hidden_projects"] = sorted(set(self.data["hidden_projects"]) | {path})
        self.save()

    def file(self, key: str) -> Path:
        entry = next((item for item in self.data["entries"] if item["id"] == key), None)
        if not entry:
            raise ValueError("Workflow is not registered in this library.")
        return Path(entry["path"])

    def listing(self) -> dict[str, Any]:
        entries = []
        for item in self.data["entries"]:
            try:
                record = DocumentStore(Path(item["path"])).read()
                raw = record["workflow"]
                supported = raw.get("version") == 3
                entries.append(
                    {
                        **item,
                        "name": raw.get("name", Path(item["path"]).stem),
                        "supported": supported,
                        "error": None
                        if supported
                        else "Unsupported version; Workbench requires schema v3.",
                    }
                )
            except Exception as error:
                entries.append(
                    {
                        **item,
                        "name": Path(item["path"]).stem,
                        "supported": False,
                        "error": str(error),
                    }
                )
        return {**self.data, "entries": entries}

    def create(self, project: Path, filename: str, name: str, template: str) -> dict[str, Any]:
        project = project.resolve()
        if str(project) not in self.data["projects"]:
            self.register_project(project)
        if Path(filename).name != filename or not filename.endswith((".yaml", ".yml")):
            raise ValueError("Use a YAML filename without directory components.")
        file = project / filename
        value = starter(name, template)
        compile_document(value)
        with file.open("x", encoding="utf-8") as stream:
            stream.write(render_document(value))
        return self.register(file)
