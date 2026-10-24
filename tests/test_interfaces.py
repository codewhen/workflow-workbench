import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from release_workbench.application.starters import starter
from release_workbench.infrastructure.documents import render_document
from release_workbench.interfaces.server import WorkbenchApplication, create_server


class Interfaces(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "test.yaml").write_text(render_document(starter("Test")))
        self.server, self.app = create_server(self.root, self.root / "storage")
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, body=None, headers=None):
        req = Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers or {},
        )
        with urlopen(req) as response:
            return response.status, response.read()

    def test_application_paths_serve_the_shell_and_unknown_routes_stay_404(self):
        for path in (
            "/workspace",
            "/folders/Automation/Checks",
            "/folders/Phone%20tests",
            "/workflows",
            "/workflows/example",
            "/workflows/example/edit/list",
            "/workflows/example/run/canvas/functions/check/cards/result/settings",
        ):
            with self.subTest(path=path):
                status, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(self.app.token.encode(), body)
                self.assertNotIn(b"__TOKEN__", body)
        for path in (
            "/workspace/extra",
            "/workflows/example/unknown",
            "/folders/../schema.json",
            "/folders/%2e%2e/schema.json",
            "/workflows/example/edit/unknown",
            "/missing-page",
        ):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()

    def test_mutation_token_and_origin_protection(self):
        for headers in (
            {},
            {"X-Workbench-Token": "wrong-token"},
            {"X-Workbench-Token": self.app.token, "Origin": "https://other.example"},
        ):
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/create", {"filename": "x.yaml", "name": "x"}, headers)
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        status, _ = self.request(
            "/api/create",
            {"project": str(self.root), "filename": "new.yaml", "name": "New"},
            {"X-Workbench-Token": self.app.token},
        )
        self.assertEqual(status, 200)

    def test_restart_keeps_existing_browser_session(self):
        restarted = WorkbenchApplication(self.root, self.root / "storage")
        self.assertEqual(restarted.token, self.app.token)
        self.assertTrue(restarted.sessions.accepts(self.app.token))
        self.assertFalse(restarted.sessions.accepts("wrong-token"))
        self.assertFalse(restarted.sessions.accepts(None))
        token_file = self.root / "storage" / "browser-sessions.json"
        if os.name != "nt":
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)

    def test_report_escape_unknown_and_host_rejected(self):
        for path in ("/reports/%2e%2e/%2e%2e/test.yaml", "/api/missing", "/not-a-page"):
            with self.assertRaises(HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/library", headers={"Host": "outside.example"})
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_folder_picker_is_protected_and_does_not_register_on_selection(self):
        with patch.object(self.app.folder_picker, "choose", return_value=str(self.root)) as choose:
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/pick-folder", {})
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
            choose.assert_not_called()
            before = self.app.library.listing()
            _, body = self.request("/api/pick-folder", {}, {"X-Workbench-Token": self.app.token})
            self.assertEqual(json.loads(body), {"path": str(self.root)})
            self.assertEqual(before, self.app.library.listing())

    def test_cli_reuses_matching_dashboard_and_rejects_other_storage(self):
        from release_workbench.interfaces.dashboard import reuse_dashboard

        other = self.root / "another-project"
        other.mkdir()
        self.assertTrue(reuse_dashboard(other, self.root / "storage", self.server.server_port))
        self.assertIn(str(other.resolve()), self.app.library.listing()["projects"])
        with self.assertRaisesRegex(ValueError, "another Workbench library"):
            reuse_dashboard(other, self.root / "different-storage", self.server.server_port)

    def test_old_workflow_stays_unchanged(self):
        text = "version: 2\nname: Old\nsteps: []\n"
        old = self.root / "old.yaml"
        old.write_text(text)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.app.library.register(old)
        self.assertEqual(old.read_text(), text)

    def test_save_never_starts_commands_and_revision_is_checked(self):
        entry = self.app.library.listing()["entries"][0]
        key = entry["id"]
        record = json.loads(self.request("/api/config?workflow=" + key)[1])
        value = record["workflow"]
        value["name"] = "Changed"
        self.app.mutation("save", key, {"workflow": value, "revision": record["revision"]})
        self.assertFalse(self.app.runs)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.app.mutation("save", key, {"workflow": value, "revision": record["revision"]})

    def test_incomplete_draft_saves_but_never_starts_execution(self):
        from release_workbench.application.starters import card, edge
        from release_workbench.infrastructure.documents import DocumentStore

        key = self.app.library.listing()["entries"][0]["id"]
        file = self.app.library.file(key)
        record = DocumentStore(file).read()
        raw = record["workflow"]
        raw["graphs"]["main"]["cards"].append(
            card(
                "unfinished",
                "python",
                {
                    "code": "from pathlib import Path\nPath('must-not-run').write_text('bad')\nreturn True"
                },
            )
        )
        raw["graphs"]["main"]["edges"] = [edge("start", "unfinished")]
        saved = self.app.mutation("save", key, {"workflow": raw, "revision": record["revision"]})
        self.assertFalse(saved["runnable"])
        self.assertIn("Unfinished", saved["validation_errors"][0])
        self.assertNotIn("use Parallel", saved["validation_errors"][0])
        self.assertEqual(DocumentStore(file).read()["workflow"], raw)
        with self.assertRaisesRegex(ValueError, "no execution connection"):
            self.app.mutation("run", key, {"revision": saved["revision"]})
        self.assertFalse(self.app.runs)
        self.assertFalse((file.parent / "must-not-run").exists())

    def test_failed_validation_backs_up_draft_for_existing_browser(self):
        from release_workbench.application.starters import card
        from release_workbench.infrastructure.documents import DocumentStore

        key = self.app.library.listing()["entries"][0]["id"]
        file = self.app.library.file(key)
        original = DocumentStore(file).read()
        raw = original["workflow"]
        raw["graphs"]["main"]["cards"].append(card("unfinished", "manual"))
        with self.assertRaisesRegex(ValueError, "Draft backed up"):
            self.app.mutation("validate", key, {"workflow": raw})
        self.assertEqual(DocumentStore(file).read()["yaml"], original["yaml"])
        reloaded = json.loads(self.request("/api/config?workflow=" + key)[1])
        self.assertEqual(reloaded["recovery"]["workflow"], raw)
        self.app.mutation("save", key, {"workflow": raw, "revision": original["revision"]})
        self.assertIsNone(self.app.drafts.matching(key, original["revision"]))

    def test_schema_invalid_draft_is_not_saved(self):
        from release_workbench.infrastructure.documents import DocumentStore

        key = self.app.library.listing()["entries"][0]["id"]
        file = self.app.library.file(key)
        record = DocumentStore(file).read()
        raw = record["workflow"]
        raw["version"] = 2
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.app.mutation("save", key, {"workflow": raw, "revision": record["revision"]})
        self.assertEqual(DocumentStore(file).read()["revision"], record["revision"])

    def test_recovery_never_overwrites_an_external_revision(self):
        from release_workbench.infrastructure.documents import DocumentStore

        key = self.app.library.listing()["entries"][0]["id"]
        file = self.app.library.file(key)
        record = DocumentStore(file).read()
        self.app.drafts.save(key, record["workflow"], record)
        file.write_text(record["yaml"] + "\n# changed externally\n")
        reloaded = json.loads(self.request("/api/config?workflow=" + key)[1])
        self.assertIsNone(reloaded["recovery"])

    def test_draft_serialization_and_import_accept_unfinished_workflows(self):
        from release_workbench.application.starters import card
        from release_workbench.infrastructure.documents import DocumentStore

        key = self.app.library.listing()["entries"][0]["id"]
        raw = DocumentStore(self.app.library.file(key)).read()["workflow"]
        raw["graphs"]["main"]["cards"].append(card("unfinished", "manual"))
        result = self.app.mutation("draft", key, {"workflow": raw})
        self.assertFalse(result["runnable"])
        self.assertIn("unfinished", result["yaml"])
        self.assertFalse(self.app.runs)
        entry = self.app.mutation(
            "import",
            "",
            {"project": str(self.root), "filename": "draft.yaml", "yaml": result["yaml"]},
        )
        self.assertTrue(entry["id"])
        self.assertEqual(self.app.library.register(self.root / "draft.yaml")["id"], entry["id"])

    def test_diagnostics_refresh_without_saving_or_backing_up_draft(self):
        from release_workbench.infrastructure.documents import DocumentStore
        from tests.support import by_id

        entry = self.app.library.listing()["entries"][0]
        key = entry["id"]
        original = DocumentStore(self.app.library.file(key)).read()
        raw = original["workflow"]
        by_id(raw, "finish")["config"] = {"returns": "boolean", "value": None}
        invalid = self.app.mutation("diagnostics", key, {"workflow": raw})
        self.assertFalse(invalid["runnable"])
        self.assertEqual(len(invalid["issues"]), 1)
        by_id(raw, "finish")["config"]["value"] = False
        fixed = self.app.mutation("diagnostics", key, {"workflow": raw})
        self.assertTrue(fixed["runnable"])
        self.assertEqual(fixed["issues"], [])
        self.assertEqual(
            DocumentStore(self.app.library.file(key)).read()["revision"], original["revision"]
        )
        self.assertIsNone(self.app.drafts.matching(key, original["revision"]))
