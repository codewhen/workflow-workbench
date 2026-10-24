"""Native Windows launch regressions, plus unchanged POSIX command semantics."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from release_workbench.infrastructure import host
from release_workbench.infrastructure.processes import ProcessAdapter


class HostPreparation(unittest.TestCase):
    def test_windows_environment_merges_case_insensitive_overrides(self):
        with patch.object(host, "os", SimpleNamespace(name="nt")):
            result = host.process_environment({"PATH": "old", "Path": "new"})
        self.assertEqual(result["PATH"], "new")
        self.assertNotIn("Path", result)

    def test_explicit_python_settings_are_preserved(self):
        result = host.process_environment({"PYTHONIOENCODING": "ascii", "PYTHONUNBUFFERED": "0"})
        self.assertEqual(result["PYTHONIOENCODING"], "ascii")
        self.assertEqual(result["PYTHONUNBUFFERED"], "0")

    def test_posix_arguments_are_not_reinterpreted(self):
        args = ["bash", "some script.sh", "value & other"]
        with patch.object(host, "os", SimpleNamespace(name="posix")):
            self.assertEqual(host.program_arguments(args, Path.cwd(), {}), args)

    def test_windows_resolves_against_the_child_path(self):
        with (
            patch.object(host, "os", SimpleNamespace(name="nt", defpath="")),
            patch.object(host.shutil, "which", return_value="C:/tools/flutter.bat") as resolve,
        ):
            result = host.program_arguments(
                ["flutter", "test"], Path.cwd(), {"PATH": "child-tools"}
            )
        resolve.assert_called_once_with("flutter", path="child-tools")
        self.assertEqual(result, ["C:/tools/flutter.bat", "test"])

    def test_bash_script_path_is_converted_without_mutating_arguments(self):
        with (
            patch.object(host, "os", SimpleNamespace(name="nt")),
            patch.object(host, "_bash", return_value="C:/Git/bin/bash.exe"),
        ):
            result = host.program_arguments(
                ["bash", r"C:\Project space\script.sh", r"literal\value"], Path.cwd(), {}
            )
        self.assertEqual(
            result, ["C:/Git/bin/bash.exe", "C:/Project space/script.sh", r"literal\value"]
        )

    def test_explicit_bash_executable_is_preserved(self):
        args = [str(Path(sys.executable)), "-V"]
        with patch.object(host, "os", SimpleNamespace(name="nt")):
            self.assertEqual(host.program_arguments(args, Path.cwd(), {}), args)


class NativeProcesses(unittest.IsolatedAsyncioTestCase):
    async def run_process(self, argv, cwd, environment):
        return await ProcessAdapter().run(
            argv, cwd, environment, None, lambda _: None, lambda: None, 15
        )

    async def test_python_unicode_and_environment_are_preserved(self):
        env = dict(os.environ, WORKBENCH_HOST_MARKER="inherited-value")
        result = await self.run_process(
            [
                sys.executable,
                "-c",
                "import json,os,sys; print(json.dumps([os.environ['WORKBENCH_HOST_MARKER'],sys.stdout.encoding],ensure_ascii=False)); print('héllo 世界')",
            ],
            Path.cwd(),
            env,
        )
        marker, encoding = json.loads(result["stdout"].splitlines()[0])
        self.assertEqual(marker, "inherited-value")
        self.assertEqual(encoding.lower().replace("-", ""), "utf8")
        self.assertIn("héllo 世界", result["stdout"])

    @unittest.skipUnless(os.name == "nt", "Native Windows executable lookup")
    async def test_program_resolves_from_workflow_path_without_parent_path(self):
        with tempfile.TemporaryDirectory(prefix="workbench tools ") as directory:
            root = Path(directory)
            shim = root / "workbench-probe.cmd"
            shim.write_bytes(b"@echo off\r\necho child-path-resolved\r\n")
            env = dict(os.environ)
            env["PATH"] = str(root)
            result = await self.run_process(["workbench-probe"], root, env)
            self.assertIn("child-path-resolved", result["stdout"])

    @unittest.skipUnless(os.name == "nt", "Native Git Bash invocation")
    async def test_bash_handles_native_script_paths_and_spaces(self):
        env = host.process_environment(dict(os.environ))
        bash = host._bash(env)
        if not Path(bash).is_file():
            self.skipTest("Git Bash is not installed")
        with tempfile.TemporaryDirectory(prefix="workbench script ") as directory:
            script = Path(directory) / "hello space.sh"
            script.write_text("printf '%s\\n' \"$1\"\n", encoding="utf-8", newline="\n")
            result = await self.run_process(["bash", str(script), "a & b"], Path(directory), env)
            self.assertEqual(result["stdout"].strip(), "a & b")


if __name__ == "__main__":
    unittest.main()
