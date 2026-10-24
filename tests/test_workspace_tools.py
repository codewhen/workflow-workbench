import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from release_workbench.application.runtime import Run
from release_workbench.application.starters import starter
from release_workbench.infrastructure.attachments import report_files
from release_workbench.infrastructure.discovery import discover
from release_workbench.infrastructure.documents import compile_document
from release_workbench.infrastructure.processes import ProcessAdapter
from release_workbench.infrastructure.services import LocalServices


class WorkspaceTools(unittest.TestCase):
    def test_workspace_is_resolved_once_and_runtime_python_is_a_string(self):
        from release_workbench.application.frame import Frame

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            nested = root / "nested"
            nested.mkdir()
            raw = starter("Nested")
            raw["workspace"] = ".."
            workflow = compile_document(raw)
            run = Run(workflow, nested, root / "evidence", LocalServices())
            self.assertEqual(run.root, root)
            frame = Frame(run, workflow.graphs["main"], {}, "root/main")
            self.assertEqual(frame.reference("runtime:python"), sys.executable)

    def test_long_output_streams_full_log_with_bounded_return(self):
        chunks = []
        result = asyncio.run(
            ProcessAdapter().run(
                [sys.executable, "-c", 'import sys; sys.stdout.write("x" * 2000000)'],
                Path.cwd(),
                {},
                None,
                chunks.append,
                lambda: None,
                10,
            )
        )
        self.assertTrue(result["truncated"])
        self.assertEqual(sum(len(chunk) for chunk in chunks), 2000000)
        self.assertLessEqual(len(result["stdout"]), 524288)

    def test_large_stderr_does_not_invalidate_json_stdout(self):
        from release_workbench.domain.models import Card
        from release_workbench.infrastructure.operations.program import ProgramHandler

        command = [sys.executable, "-c", 'import sys; sys.stderr.write("x"*1100000); print("42")']
        result = asyncio.run(
            ProgramHandler().execute(
                Card("program", "program", "Program", {"argv": command, "capture": "json"}),
                Path.cwd(),
                {},
                {},
                ProcessAdapter(),
                lambda text: None,
                lambda: None,
            )
        )
        self.assertEqual(result["json"], 42)
        self.assertTrue(result["stderr_truncated"])
        self.assertFalse(result["stdout_truncated"])

    def test_discovery_validates_typed_values_and_ambiguous_choices(self):
        raw = starter("Discovery")
        raw["inputs"] = {"serial": {"type": "string"}, "pid": {"type": "number"}}
        data = {
            "serial": [{"value": "one"}, {"value": "two"}],
            "pid": [{"value": "42"}],
            "warnings": ["Choose phone"],
        }
        raw["input_detection"] = {
            "argv": [
                {"$ref": "runtime:python"},
                "-c",
                "import json; print(" + repr(json.dumps(data)) + ")",
            ]
        }
        with tempfile.TemporaryDirectory() as folder:
            result = discover(raw, Path(folder), LocalServices())
        self.assertEqual(len(result["candidates"]["serial"]), 2)
        self.assertEqual(result["candidates"]["pid"][0]["value"], 42)
        raw["inputs"]["serial"]["type"] = "boolean"
        with self.assertRaises(ValueError):
            discover(raw, Path.cwd(), LocalServices())

    def test_attachment_paths_reject_escape_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "report.json").write_text("{}")
            (root / "secret.json").write_text("secret")
            with self.assertRaises(ValueError):
                report_files(workspace, ["../*.json"])
            try:
                (workspace / "escape.json").symlink_to(root / "secret.json")
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege requires Developer Mode or elevation")
                raise
            self.assertEqual(set(report_files(workspace, ["*.json"])), {"report.json"})

    def test_json_capture_rejects_truncated_output(self):
        from release_workbench.domain.models import Card
        from release_workbench.infrastructure.operations.program import ProgramHandler

        class Fake:
            async def run(self, *args):
                return {"stdout": "{}", "truncated": True}

        with self.assertRaisesRegex(ValueError, "truncated"):
            asyncio.run(
                ProgramHandler().execute(
                    Card("p", "program", "Program", {"argv": ["x"], "capture": "json"}),
                    Path.cwd(),
                    {},
                    {},
                    Fake(),
                    Mock(),
                    Mock(),
                )
            )


class ChildEvidence(unittest.IsolatedAsyncioTestCase):
    async def test_parent_receives_live_child_logs_progress_events_and_report(self):
        from release_workbench.application.starters import card
        from release_workbench.infrastructure.documents import render_document
        from tests.support import sequence

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            child = sequence(
                card(
                    "work",
                    "python",
                    {
                        "code": 'import time\nprint("child live marker", flush=True)\nprint(\'::workbench::{"done":1,"total":2,"stage":"probe"}\', flush=True)\ntime.sleep(0.3)\nreturn 42',
                        "returns": "number",
                    },
                )
            )
            (root / "child.yaml").write_text(render_document(child))
            parent = sequence(card("child", "workspace", {"path": "child.yaml", "inputs": {}}))
            run = Run(compile_document(parent), root, root / "evidence", LocalServices())
            task = asyncio.create_task(run.execute())
            observed = False
            for _ in range(200):
                entry = run.evidence.state["executions"].get("root/main/child", {})
                if "child live marker" in entry.get("tail", ""):
                    observed = True
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(observed)
            self.assertEqual(await task, 0)
            entry = run.evidence.state["executions"]["root/main/child"]
            self.assertEqual(entry["child_status"], "passed")
            self.assertEqual(Path(entry["child_source"]), (root / "child.yaml").resolve())
            self.assertEqual(entry["child_progress"]["stage"], "probe")
            self.assertTrue((run.evidence.directory / entry["child_report"]).is_file())
            self.assertTrue(
                any(event["kind"] == "child_progress" for event in run.evidence.state["events"])
            )
