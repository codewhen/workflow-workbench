"""Host-specific process preparation without application toolchain assumptions."""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PureWindowsPath

from release_workbench.domain.values import ContractError


def process_environment(environment: dict[str, str]) -> dict[str, str]:
    # Windows environment names are case insensitive. Workflow/card overrides
    # such as Path must replace inherited PATH rather than create two entries.
    result = {key.upper() if os.name == "nt" else key: value for key, value in environment.items()}
    # ProcessAdapter decodes UTF-8 and streams output while the card is running.
    # Explicit workflow values remain authoritative.
    result.setdefault("PYTHONUTF8", "1")
    result.setdefault("PYTHONIOENCODING", "utf-8")
    result.setdefault("PYTHONUNBUFFERED", "1")
    return result


def _bash(environment: dict[str, str]) -> str:
    configured = shutil.which("bash", path=environment.get("PATH", os.defpath))
    if configured and not any(
        part.lower() in {"windowsapps", "system32", "sysnative"} for part in Path(configured).parts
    ):
        return configured
    candidates = []
    git = shutil.which("git", path=environment.get("PATH", os.defpath))
    if git:
        candidates.append(Path(git).resolve().parent.parent / "bin/bash.exe")
    for variable, suffix in (
        ("PROGRAMFILES", "Git"),
        ("PROGRAMFILES(X86)", "Git"),
        ("LOCALAPPDATA", "Programs/Git"),
    ):
        if directory := environment.get(variable):
            candidates.append(Path(directory) / suffix / "bin/bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    # Leave an unresolved name for the adapter to report as a launch error.
    # Never silently launch WSL for a native Windows workspace.
    raise ContractError(
        "Native Bash was not found. Install Git for Windows and add Git Bash to PATH; WSL bash cannot execute native Windows workspace scripts."
    )


def program_arguments(argv: list[str], cwd: Path, environment: dict[str, str]) -> list[str]:
    if os.name != "nt":
        return list(argv)
    result = list(argv)
    name = PureWindowsPath(result[0]).name.lower()
    if result[0].lower() in {"bash", "bash.exe"}:
        result[0] = _bash(environment)
    else:
        local = cwd / result[0]
        if PureWindowsPath(result[0]).is_absolute() or Path(result[0]).is_absolute():
            pass  # Preserve explicitly selected interpreters, including venv symlinks.
        elif local.is_file():
            result[0] = str(local.resolve())
        else:
            result[0] = (
                shutil.which(result[0], path=environment.get("PATH", os.defpath)) or result[0]
            )
    if name in {"bash", "bash.exe"}:
        # Script paths use native-drive forward slashes in Git Bash. Do not
        # rewrite shell code or user arguments passed after the script path.
        if len(result) > 1 and not result[1].startswith("-"):
            result[1] = result[1].replace("\\", "/")
    return result
