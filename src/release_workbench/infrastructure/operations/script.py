"""ScriptHandler external effect adapter."""

from __future__ import annotations

import sys
from pathlib import Path

from release_workbench.domain.models import Card
from release_workbench.domain.values import ContractError

from .base import workspace_path
from .program import ProgramHandler


class ScriptHandler(ProgramHandler):
    kind = "script"

    def arguments(self, card: Card, root: Path) -> list[str]:
        language = card.config["language"]
        executable = {"python": sys.executable, "bash": "bash"}.get(language)
        if not executable:
            raise ContractError("Choose Python or Bash.")
        return [
            executable,
            workspace_path(root, card.config["path"]).as_posix(),
            *card.config.get("arguments", []),
        ]
