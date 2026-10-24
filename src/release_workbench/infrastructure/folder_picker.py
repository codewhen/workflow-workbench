"""Native directory selection on the local Workbench host."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path


class FolderPicker:
    kind = "folder"

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def choose(self) -> str | None:
        if not self._lock.acquire(blocking=False):
            raise ValueError(
                f"A {self.kind} picker is already open. Choose a {self.kind} or cancel it."
            )
        try:
            command = self._command()
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, encoding="utf-8", timeout=180
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError(
                    f"The {self.kind} picker could not finish. Enter the {self.kind} path instead."
                ) from error
            if result.returncode == 1 and sys.platform not in ("darwin", "win32"):
                return None
            if result.returncode != 0:
                raise ValueError(
                    f"The {self.kind} picker could not open. Enter the {self.kind} path instead."
                )
            selected = result.stdout.rstrip("\r\n")
            if not selected:
                return None
            path = Path(selected)
            if not path.is_absolute() or not self._available(path):
                raise ValueError(f"The selected {self.kind} is no longer available.")
            return str(path.resolve())
        finally:
            self._lock.release()

    def _available(self, path: Path) -> bool:
        return path.is_dir()

    @staticmethod
    def _command() -> list[str]:
        if sys.platform == "darwin":
            return [
                "/usr/bin/osascript",
                "-e",
                "activate\ntry\n"
                'return POSIX path of (choose folder with prompt "Choose a Workbench project folder")\n'
                'on error number -128\nreturn ""\nend try',
            ]
        if sys.platform == "win32":
            return [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-Command",
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$picker = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$picker.Description = 'Choose a Workbench project folder'; "
                "try { if ($picker.ShowDialog() -eq 'OK') { "
                "[Console]::WriteLine($picker.SelectedPath) } } finally { $picker.Dispose() }",
            ]
        if shutil.which("zenity"):
            return ["zenity", "--file-selection", "--directory", "--title=Choose a project folder"]
        if shutil.which("kdialog"):
            return ["kdialog", "--getexistingdirectory", str(Path.home())]
        raise ValueError("No native folder picker is available. Enter the folder path instead.")


class WorkflowPicker(FolderPicker):
    """Open the original definition so relative imports retain their source root."""

    kind = "YAML file"

    def _available(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in {".yaml", ".yml"}

    @staticmethod
    def _command() -> list[str]:
        if sys.platform == "darwin":
            return [
                "/usr/bin/osascript",
                "-e",
                'activate\ntry\nreturn POSIX path of (choose file with prompt "Open a workflow YAML file")\non error number -128\nreturn ""\nend try',
            ]
        if sys.platform == "win32":
            return [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-Command",
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$picker = New-Object System.Windows.Forms.OpenFileDialog; "
                "$picker.Title = 'Open a workflow YAML file'; "
                "$picker.Filter = 'Workflow YAML (*.yaml;*.yml)|*.yaml;*.yml'; "
                "try { if ($picker.ShowDialog() -eq 'OK') { "
                "[Console]::WriteLine($picker.FileName) } } finally { $picker.Dispose() }",
            ]
        if shutil.which("zenity"):
            return [
                "zenity",
                "--file-selection",
                "--title=Open a workflow YAML file",
                "--file-filter=Workflow YAML | *.yaml *.yml",
            ]
        if shutil.which("kdialog"):
            return ["kdialog", "--getopenfilename", str(Path.home()), "*.yaml *.yml|Workflow YAML"]
        raise ValueError(
            "No native file picker is available. Use Add project or file to enter the original YAML path, or Import a copy."
        )
