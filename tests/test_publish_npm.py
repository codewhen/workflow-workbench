"""Publishing orchestration is platform-neutral and stops before unsafe follow-up."""

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import publish_npm


class NpmReleaseTests(unittest.TestCase):
    def fixture(self, root):
        package = root / "npm/workbench/package.json"
        package.parent.mkdir(parents=True)
        package.write_text(
            json.dumps({"name": "@codewhen/workbench", "version": "1.2.3"}), encoding="utf-8"
        )
        (root / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
        module = root / "src/release_workbench/__init__.py"
        module.parent.mkdir(parents=True)
        module.write_text('__version__ = "1.2.3"\n', encoding="utf-8")
        (root / "dist").mkdir()
        for name in (
            "release_workbench-1.2.3-py3-none-any.whl",
            "release_workbench-1.2.3.tar.gz",
            "codewhen-workbench-1.2.3.tgz",
        ):
            (root / "dist" / name).write_bytes(b"synthetic artifact")

    def test_version_mismatch_fails_before_running_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "pyproject.toml").write_text('[project]\nversion = "1.2.4"\n', encoding="utf-8")
            with (
                patch.object(publish_npm.subprocess, "run") as run,
                self.assertRaisesRegex(ValueError, "Align"),
            ):
                publish_npm.release(
                    argparse.Namespace(pack_only=True, dry_run=False, tag="latest"), root
                )
            run.assert_not_called()

    def test_npm_resolution_for_both_platforms(self):
        for windows, name in ((True, "npm.cmd"), (False, "npm")):
            with (
                self.subTest(windows=windows),
                patch.object(publish_npm.shutil, "which", return_value=name) as which,
            ):
                self.assertEqual(publish_npm.npm_program(windows), name)
                which.assert_called_once_with(name)

    def test_pack_only_and_dry_run_publish_only_the_exact_verified_archive(self):
        for pack_only in (True, False):
            with (
                self.subTest(pack_only=pack_only),
                tempfile.TemporaryDirectory(prefix="release with spaces ") as directory,
            ):
                root = Path(directory)
                self.fixture(root)
                with (
                    patch.object(publish_npm, "npm_program", return_value="npm.cmd"),
                    patch.object(publish_npm.shutil, "which", return_value="node"),
                    patch.object(publish_npm.subprocess, "check_output", return_value="22\n"),
                    patch.object(publish_npm.subprocess, "run") as run,
                    patch("builtins.print"),
                ):
                    publish_npm.release(
                        argparse.Namespace(pack_only=pack_only, dry_run=not pack_only, tag="next"),
                        root,
                    )
                calls = run.call_args_list
                commands = [call.args[0] for call in calls]
                self.assertNotIn(["npm.cmd", "whoami"], commands)
                publish = [command for command in commands if command[1] == "publish"]
                self.assertEqual(len(publish), 0 if pack_only else 1)
                if publish:
                    self.assertEqual(
                        publish[0],
                        [
                            "npm.cmd",
                            "publish",
                            str(root / "dist/codewhen-workbench-1.2.3.tgz"),
                            "--access",
                            "public",
                            "--tag",
                            "next",
                            "--dry-run",
                        ],
                    )
                pack = next(call for call in calls if call.args[0][1] == "pack")
                self.assertEqual(pack.kwargs["cwd"], root / "npm/workbench")
                self.assertTrue(all(call.kwargs["check"] for call in calls))
                self.assertTrue((root / "dist/SHA256SUMS-1.2.3").is_file())

    def test_authentication_failure_stops_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with (
                patch.object(publish_npm, "npm_program", return_value="npm"),
                patch.object(publish_npm.shutil, "which", return_value="node"),
                patch.object(publish_npm.subprocess, "check_output", return_value="22\n"),
                patch.object(
                    publish_npm.subprocess,
                    "run",
                    side_effect=subprocess.CalledProcessError(1, "npm whoami"),
                ) as run,
                patch("builtins.print"),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                publish_npm.release(
                    argparse.Namespace(pack_only=False, dry_run=False, tag="latest"), root
                )
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], ["npm", "whoami"])


if __name__ == "__main__":
    unittest.main()
