import copy
import tempfile
import unittest
from pathlib import Path

from release_workbench.application.compiler import CompilationError
from release_workbench.application.skip_plan import plan_skips
from release_workbench.application.starters import card, ref, starter
from release_workbench.infrastructure.documents import (
    DocumentStore,
    compile_document,
    render_document,
)
from release_workbench.interfaces.server import WorkbenchApplication
from tests.support import RunCase, by_id, sequence


def marked(raw, *ids):
    raw = copy.deepcopy(raw)
    raw["skip_cards"] = [{"graph": "main", "card": c} for c in ids]
    return raw


class Planner(unittest.TestCase):
    def test_invalid_identifiers_and_control_cards(self):
        for name in ["absent", "start", "finish"]:
            with self.subTest(name=name), self.assertRaises(CompilationError):
                compile_document(marked(sequence(), name))

    def test_dependencies_are_transitive_but_flow_is_not(self):
        raw = sequence(
            card("a", "python", {"code": "return 1", "returns": "number"}),
            {
                **card("b", "python", {"code": "return 2", "returns": "number"}),
                "inputs": {"nested": {"items": [ref("a")]}},
            },
            card("c", "wait", {"seconds": ref("b")}),
            card("independent", "wait", {"seconds": 0}),
        )
        plan = plan_skips(compile_document(raw), [{"graph": "main", "card": "a"}])
        self.assertEqual({x["card"] for x in plan["affected"]}, {"a", "b", "c"})
        self.assertFalse(plan["blockers"])

    def test_missing_terminal_output_blocks(self):
        raw = sequence(card("a", "python", {"code": "return 1", "returns": "number"}))
        by_id(raw, "finish")["config"] = {"value": ref("a")}
        plan = plan_skips(compile_document(raw), [{"graph": "main", "card": "a"}])
        self.assertIn("required finish loses its result", plan["blockers"][0])

    def test_parent_closure_join_and_independent_descendant_mark(self):
        raw = starter("Parallel", "parallel")
        workflow = compile_document(raw)
        roots = [{"graph": "main", "card": c} for c in ["parallel", "first"]]
        plan = plan_skips(workflow, roots)
        self.assertTrue(
            {"parallel", "first", "second", "join"} <= {x["card"] for x in plan["affected"]}
        )
        unmarked = plan_skips(workflow, roots[1:])
        self.assertEqual({x["card"] for x in unmarked["affected"]}, {"first"})

    def test_if_common_continuation_and_condition_children(self):
        plan = plan_skips(
            compile_document(starter("If", "manual")), [{"graph": "main", "card": "decision"}]
        )
        self.assertFalse(plan["blockers"])
        self.assertEqual(
            plan["continuations"], [{"graph": "main", "card": "decision", "next": "finish"}]
        )
        self.assertEqual({x["card"] for x in plan["affected"]}, {"decision", "work"})
        self.assertIn("ask", {x["card"] for x in plan["children"]})

    def test_if_without_common_continuation_rejected(self):
        raw = starter("If", "manual")
        raw["graphs"]["main"]["cards"].append(card("other_finish", "finish"))
        for e in raw["graphs"]["main"]["edges"]:
            if e["source"] == "work":
                e["target"] = "other_finish"
        plan = plan_skips(compile_document(raw), [{"graph": "main", "card": "decision"}])
        self.assertTrue(plan["blockers"])


class Persistence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / "test.yaml"
        self.file.write_text(render_document(sequence(card("hold", "wait", {"seconds": 0}))))
        self.app = WorkbenchApplication(self.root, self.root / "storage")
        self.key = self.app.library.register(self.file)["id"]

    def preview(self, **extra):
        return self.app.mutation(
            "skip-preview", self.key, {"graph": "main", "card": "hold", **extra}
        )

    def test_preview_does_not_write_confirm_persists_reopen_unmark(self):
        original = self.file.read_text()
        preview = self.preview()
        self.assertEqual(original, self.file.read_text())
        result = self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        self.assertEqual(
            result["document"]["workflow"]["skip_cards"], [{"graph": "main", "card": "hold"}]
        )
        reopened = WorkbenchApplication(self.root, self.root / "other-storage")
        plan = reopened.mutation("skip-plan", reopened.library.register(self.file)["id"], {})
        self.assertEqual(plan["marks"], result["plan"]["marks"])
        preview = self.preview(unmark=True)
        self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        self.assertNotIn("skip_cards", DocumentStore(self.file).read()["workflow"])

    def test_stale_file_and_reused_tokens_do_not_write(self):
        preview = self.preview()
        self.file.write_text(self.file.read_text() + "\n# external edit\n")
        changed = self.file.read_text()
        with self.assertRaises(ValueError):
            self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        self.assertEqual(self.file.read_text(), changed)
        with self.assertRaises(ValueError):
            self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        with self.assertRaises(ValueError):
            self.app.mutation("skip", self.key, {"graph": "main", "card": "hold"})


class Startup(RunCase):
    async def test_saved_marks_apply_to_fresh_run(self):
        raw = marked(
            sequence(card("hold", "wait", {"seconds": 20}), card("next", "wait", {"seconds": 0})),
            "hold",
        )
        run = await self.passed(raw)
        self.assertEqual(run.evidence.state["executions"]["root/main/hold"]["status"], "skipped")
        self.assertEqual(run.evidence.state["executions"]["root/main/next"]["status"], "passed")

    async def test_saved_if_bypasses_condition_and_both_branches(self):
        run = await self.passed(marked(starter("If", "manual"), "decision"))
        self.assertNotIn("ask", {x["card"] for x in run.evidence.state["executions"].values()})
        self.assertEqual(
            run.evidence.state["executions"]["root/main/decision"]["status"], "skipped"
        )
        self.assertEqual(run.evidence.state["executions"]["root/main/work"]["status"], "skipped")

    async def test_saved_parent_bypasses_owned_work(self):
        for template, parent in [
            ("parallel", "parallel"),
            ("recovery", "recover"),
            ("while", "repeat"),
        ]:
            raw = starter("Parent", template)
            if parent not in {c["id"] for c in raw["graphs"]["main"]["cards"]}:
                continue
            run = await self.passed(marked(raw, parent))
            self.assertEqual(
                run.evidence.state["executions"]["root/main/" + parent]["status"], "skipped"
            )


class LivePersistence(Persistence):
    def start(self):
        import time

        raw = sequence(
            card("hold", "wait", {"seconds": 20}), card("pending", "wait", {"seconds": 20})
        )
        self.file.write_text(render_document(raw))
        self.app.mutation(
            "run", self.key, {"revision": DocumentStore(self.file).read()["revision"], "inputs": {}}
        )
        run = self.app.runs[self.key]
        self.addCleanup(lambda: run.thread.join(3))
        self.addCleanup(run.stop)
        for _ in range(200):
            if (
                run.evidence.state["executions"].get("root/main/hold", {}).get("status")
                == "running"
            ):
                return run
            time.sleep(0.005)
        self.fail("Run did not start")

    def test_confirm_updates_live_plan_but_not_configuration_snapshot(self):
        run = self.start()
        snapshot = copy.deepcopy(run.workflow.raw)
        preview = self.preview()
        result = self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        self.assertEqual(run.workflow.raw, snapshot)
        self.assertIn("skip_cards", result["document"]["workflow"])
        self.assertTrue(run.evidence.state["skip_plan_changed"])
        self.assertEqual(run.evidence.state["events"][-1]["kind"], "skip_plan_changed")
        from release_workbench.application.start_context import compatible

        self.assertFalse(compatible(run.evidence.state, run.base_fingerprint))

    def test_affected_execution_change_rejects_without_saving(self):
        run = self.start()
        preview = self.preview()
        original = self.file.read_text()
        with run.control_lock:
            entry = run.evidence.state["executions"]["root/main/hold"]
            entry["status"] = "passed"
        with self.assertRaisesRegex(ValueError, "Execution changed"):
            self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        self.assertEqual(self.file.read_text(), original)
        self.assertNotIn(("main", "hold"), run.skipped_cards)

    def test_failed_persistence_does_not_change_execution_plan(self):
        from unittest.mock import patch

        run = self.start()
        preview = self.preview()
        with patch.object(DocumentStore, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.app.mutation("skip-confirm", self.key, {"token": preview["token"]})
        self.assertNotIn(("main", "hold"), run.skipped_cards)
        self.assertNotIn("skip_cards", DocumentStore(self.file).read()["workflow"])

    def test_unmark_retains_consumed_execution_and_independent_mark(self):
        run = self.start()
        for name in ["pending", "hold"]:
            p = self.app.mutation("skip-preview", self.key, {"graph": "main", "card": name})
            self.app.mutation("skip-confirm", self.key, {"token": p["token"]})
        run.thread.join(3)
        self.assertFalse(run.busy)
        self.assertEqual(run.evidence.state["status"], "passed")
        p = self.preview(unmark=True)
        self.app.mutation("skip-confirm", self.key, {"token": p["token"]})
        self.assertEqual(
            DocumentStore(self.file).read()["workflow"]["skip_cards"],
            [{"graph": "main", "card": "pending"}],
        )
        self.assertEqual(run.evidence.state["executions"]["root/main/hold"]["status"], "skipped")


class InvocationSkips(RunCase):
    async def test_call_skip_is_scoped_and_shared_function_still_runs(self):
        raw = sequence(
            card("one", "call", {"function": "shared"}), card("two", "call", {"function": "shared"})
        )
        raw["functions"] = {
            "shared": {"name": "Shared", "graph": "shared", "inputs": {}, "returns": "void"}
        }
        raw["graphs"]["shared"] = sequence(card("work", "wait", {"seconds": 0}))["graphs"]["main"]
        by_id(raw, "finish", "shared")["kind"] = "return"
        by_id(raw, "finish", "shared")["config"] = {"returns": "void"}
        raw = marked(raw, "one")
        before = copy.deepcopy(raw)
        run = await self.passed(raw)
        self.assertEqual(run.workflow.raw, before)
        calls = [x for x in run.evidence.state["executions"].values() if x["graph"] == "shared"]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("/two/" in x["path"] for x in calls))

    async def test_workspace_saved_skip_does_not_edit_child(self):
        child = self.root / "child.yaml"
        child.write_text(render_document(sequence(card("hold", "wait", {"seconds": 20}))))
        original = child.read_text()
        run = await self.passed(
            marked(
                sequence(card("child", "workspace", {"path": "child.yaml", "inputs": {}})), "child"
            )
        )
        self.assertFalse(run.children)
        self.assertEqual(child.read_text(), original)

    async def test_dependency_skips_do_not_run_and_value_wire_is_followed(self):
        raw = sequence(
            card("a", "python", {"code": "return 1", "returns": "number"}),
            card("b", "wait", {"seconds": 0}),
            card("independent", "wait", {"seconds": 0}),
        )
        raw["graphs"]["main"]["edges"].append(
            {
                "id": "value-a-b",
                "kind": "value",
                "source": "a",
                "target": "b",
                "source_port": "value",
                "target_port": "config:seconds",
                "path": "",
            }
        )
        run = await self.passed(marked(raw, "a"))
        self.assertEqual(run.evidence.state["executions"]["root/main/b"]["status"], "skipped")
        self.assertEqual(
            run.evidence.state["executions"]["root/main/independent"]["status"], "passed"
        )
