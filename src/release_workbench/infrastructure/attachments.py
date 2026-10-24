"""Workspace-confined, explicitly declared run report attachments."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode


def report_files(root: Path, patterns: list[str], started: float = 0) -> dict[str, Path]:
    root = root.resolve()
    files: dict[str, Path] = {}
    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("Report patterns must stay inside the workspace.")
        for candidate in root.glob(pattern):
            file = candidate.resolve()
            if file.is_relative_to(root) and file.is_file() and file.stat().st_mtime >= started:
                files[file.relative_to(root).as_posix()] = file
                if len(files) >= 1000:
                    return files
    return files


def attachments(root: Path, raw: dict[str, Any], key: str, started: float) -> list[dict[str, str]]:
    return [
        {"path": path, "url": "/api/attachment?" + urlencode({"workflow": key, "path": path})}
        for path in sorted(report_files(root, raw.get("report_paths", []), started))
    ]


def snapshot_reports(directory: Path, state: dict[str, Any], masker: Any) -> list[dict[str, str]]:
    """Snapshot small text reports; retain original references for oversized artifacts."""
    config = state.get("report_sources", {})
    if not config.get("patterns"):
        return []
    root = Path(config["workspace"])
    total = 0
    result = []
    for name, file in sorted(
        report_files(root, config["patterns"], state.get("started", 0)).items()
    ):
        entry = {"path": name}
        size = file.stat().st_size
        if (
            file.suffix.lower() in {".json", ".html", ".log", ".txt", ".csv"}
            and size <= 16 * 1024 * 1024
            and total + size <= 64 * 1024 * 1024
        ):
            destination = directory / "attachments" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                masker.text(file.read_text(encoding="utf-8", errors="replace")), encoding="utf-8"
            )
            entry["snapshot"] = destination.relative_to(directory).as_posix()
            total += size
        else:
            entry["note"] = "Original workspace artifact; not copied into run storage."
        result.append(entry)
    return result
