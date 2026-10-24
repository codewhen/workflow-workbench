"""Opening a child definition never executes it or saves the parent draft."""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from release_workbench.application.starters import starter
from release_workbench.infrastructure.documents import render_document
from release_workbench.interfaces.server import WorkbenchApplication


class WorkspaceNavigation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        folder = self.root / "workflows" / "test"
        folder.mkdir(parents=True)
        self.parent = folder / "parent.yaml"
        self.child = self.root / "child.yaml"
        self.child.write_text(render_document(starter("Child definition")))
        self.raw = starter("Parent")
        self.raw["workspace"] = "../.."
        self.raw["graphs"]["main"]["cards"].insert(
            1,
            {
                "id": "call",
                "kind": "workspace",
                "name": "Child call",
                "config": {"path": "child.yaml", "inputs": {}},
            },
        )
        self.parent.write_text(render_document(self.raw), encoding="utf-8", newline="\n")
        self.app = WorkbenchApplication(self.root, self.root / "storage")
        self.key = self.app.library.register(self.parent)["id"]

    def open(self, **extra):
        return self.app.mutation(
            "open-workspace", self.key, {"graph": "main", "card": "call", **extra}
        )

    def test_relative_path_uses_declared_execution_root_and_reuses_registration(self):
        before = self.parent.read_bytes()
        edit = self.open(view="edit")
        run = self.open(view="run")
        self.assertEqual(edit["id"], run["id"])
        self.assertEqual(self.app.library.file(edit["id"]), self.child)
        self.assertEqual(edit["url"], f"/workflows/{edit['id']}/edit")
        self.assertTrue(run["url"].endswith("/run"))
        self.assertEqual(self.parent.read_bytes(), before)
        self.assertFalse(self.app.runs)

    def test_current_unsaved_child_path_is_used_without_saving_parent(self):
        other = self.root / "other.yaml"
        other.write_text(render_document(starter("Other child")))
        draft = copy.deepcopy(self.raw)
        draft["graphs"]["main"]["cards"][1]["config"]["path"] = "other.yaml"
        result = self.open(workflow=draft)
        self.assertEqual(self.app.library.file(result["id"]), other)
        self.assertEqual(self.parent.read_bytes(), render_document(self.raw).encode())

    def test_resolved_execution_path_wins_for_dynamic_child_calls(self):
        raw = copy.deepcopy(self.raw)
        raw["graphs"]["main"]["cards"][1]["config"]["path"] = {"$ref": "input:child"}
        self.app.runs[self.key] = SimpleNamespace(
            evidence=SimpleNamespace(
                state={
                    "executions": {
                        "root/main/call": {
                            "card": "call",
                            "graph": "main",
                            "child_source": str(self.child),
                        }
                    }
                }
            )
        )
        result = self.open(workflow=raw, execution="root/main/call")
        self.assertEqual(self.app.library.file(result["id"]), self.child)
        automatic = self.open(workflow=raw, view="run")
        self.assertEqual(automatic["id"], result["id"])
        self.app.runs[self.key].evidence.state["executions"]["root/main/call"]["card"] = "different"
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.open(execution="root/main/call")

    def test_missing_invalid_and_unresolved_children_produce_useful_errors(self):
        draft = copy.deepcopy(self.raw)
        draft["graphs"]["main"]["cards"][1]["config"]["path"] = "missing.yaml"
        with self.assertRaises((OSError, ValueError)):
            self.open(workflow=draft)
        draft["graphs"]["main"]["cards"][1]["config"]["path"] = {"$ref": "input:child"}
        with self.assertRaisesRegex(ValueError, "Dynamic paths"):
            self.open(workflow=draft)

    def test_live_child_context_tracks_exact_invocation_and_snapshot(self):
        import time
        from urllib.parse import parse_qs, urlsplit

        from release_workbench.application.starters import card, edge
        from release_workbench.infrastructure.documents import DocumentStore

        child = starter("Live child")
        child["graphs"]["main"] = {
            "cards": [
                card("start", "start"),
                card("review", "manual", {"mode": "decision", "instructions": "Synthetic review"}),
                card("finish", "finish", {"returns": "boolean", "value": {"$ref": "card:review"}}),
            ],
            "edges": [edge("start", "review"), edge("review", "finish")],
        }
        self.child.write_text(render_document(child))
        self.raw["graphs"]["main"]["edges"] = [edge("start", "call"), edge("call", "finish")]
        self.parent.write_text(render_document(self.raw), encoding="utf-8", newline="\n")
        record = DocumentStore(self.parent).read()
        self.app.mutation("run", self.key, {"revision": record["revision"]})
        parent = self.app.runs[self.key]
        self.addCleanup(lambda: parent.stop())
        deadline = time.monotonic() + 10
        while (
            not parent.children or not parent.children[0][1].evidence.state["manual"]
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(parent.children)
        result = self.open(view="run", execution="root/main/call")
        context = parse_qs(urlsplit(result["url"]).query)["run"][0]
        selected = parent.children[0][1]
        self.assertEqual(context, selected.evidence.state["run_id"])
        self.assertTrue(self.app.state(result["id"], context)["busy"])
        self.assertTrue(selected.busy)  # children have no dedicated thread
        # Never substitute a standalone run of the same saved workflow.
        self.app.runs[result["id"]] = parent
        self.assertIs(self.app.selected_run(result["id"], context), selected)
        self.assertEqual(
            self.app.configuration(result["id"], context)["workflow"]["name"], "Live child"
        )
        self.child.write_text(render_document(starter("Edited after launch")))
        self.assertEqual(
            self.app.configuration(result["id"], context)["workflow"]["name"], "Live child"
        )
        with self.assertRaisesRegex(ValueError, "different workflow"):
            self.app.state(self.key, context)
        with self.assertRaisesRegex(ValueError, "no longer available"):
            self.app.state(result["id"], "missing-run")
        with self.assertRaisesRegex(ValueError, "existing execution"):
            self.app.mutation("run", result["id"], {}, context)
        path = next(iter(selected.evidence.state["manual"]))
        self.app.mutation(
            "record",
            result["id"],
            {"execution": path, "note": "Reviewed", "decision": False},
            context,
        )
        parent.thread.join(10)
        self.assertFalse(parent.busy)
        self.assertFalse(selected.busy)
        self.assertEqual(self.app.state(result["id"], context)["status"], "passed")
        self.assertEqual(selected.evidence.state["result"]["value"], False)
        self.assertTrue(self.app.state(result["id"], context)["can_run_from_here"])
        fresh = self.app.mutation(
            "run",
            result["id"],
            {
                "revision": self.app.configuration(result["id"], context)["revision"],
                "selection": {"graph": "main", "card": "finish"},
            },
            context,
        )
        fresh_run = self.app.runs[result["id"]]
        fresh_run.thread.join(10)
        self.assertNotEqual(fresh["run_id"], context)
        self.assertEqual(fresh_run.workflow.name, "Live child")
        self.assertEqual(list(fresh_run.evidence.state["executions"]), ["root/main/finish"])
        self.assertEqual(self.app.state(result["id"], context)["result"]["value"], False)
        # Context remains inspectable after the parent's latest-run slot is replaced.
        self.app.runs.pop(self.key)
        self.assertIs(self.app.selected_run(result["id"], context), selected)

    def test_parallel_calls_have_distinct_contexts_and_targeted_cancellation(self):
        import time
        from urllib.parse import parse_qs, urlsplit

        from release_workbench.infrastructure.documents import DocumentStore

        child = starter("Waiting child", "manual")
        self.child.write_text(render_document(child))
        raw = starter("Parallel callers", "parallel")
        for item in raw["graphs"]["main"]["cards"]:
            if item["id"] in {"first", "second"}:
                item.update(kind="workspace", config={"path": "child.yaml", "inputs": {}})
        self.parent.write_text(render_document(raw))
        # The parent lives below workflows/test, so declare its project root.
        raw["workspace"] = "../.."
        self.parent.write_text(render_document(raw))
        record = DocumentStore(self.parent).read()
        self.app.mutation("run", self.key, {"revision": record["revision"]})
        parent = self.app.runs[self.key]
        self.addCleanup(parent.stop)
        deadline = time.monotonic() + 10
        while (
            len(parent.children) < 2
            or not all(child.evidence.state["manual"] for _, child in parent.children)
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(parent.children), 2)
        contexts = []
        for path, child in parent.children:
            caller = parent.evidence.state["executions"][path]
            result = self.app.mutation(
                "open-workspace",
                self.key,
                {
                    "view": "run",
                    "graph": caller["graph"],
                    "card": caller["card"],
                    "execution": path,
                },
            )
            context = parse_qs(urlsplit(result["url"]).query)["run"][0]
            contexts.append(context)
            self.assertIs(self.app.selected_run(result["id"], context), child)
        self.assertNotEqual(*contexts)
        self.app.mutation("stop", result["id"], {}, contexts[0])
        deadline = time.monotonic() + 5
        while parent.children[0][1].busy and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.app.state(result["id"], contexts[0])["status"], "cancelled")
        self.assertTrue(self.app.state(result["id"], contexts[1])["busy"])
        parent.stop()
        parent.thread.join(10)
        self.assertFalse(parent.busy)
        self.assertTrue(all(not child.busy for _, child in parent.children))
