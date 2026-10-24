import tempfile
import unittest
from pathlib import Path

from release_workbench.application.starters import card, starter
from release_workbench.infrastructure.documents import render_document
from release_workbench.infrastructure.library import Library
from release_workbench.interfaces.server import WorkbenchApplication
from tests.support import sequence


class LibraryDependencies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.storage = self.root / "storage"

    def write(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(raw))

    def parent(self, path, workspace="."):
        raw = sequence(card("child", "workspace", {"path": path, "inputs": {}}))
        raw["workspace"] = workspace
        return raw

    def test_project_discovers_nested_dependencies_and_cycles_without_duplicates(self):
        parent = self.project / "parent.yaml"
        child = self.project / "work" / "nested" / "child.yaml"
        leaf = child.parent / "leaf.yaml"
        self.write(parent, self.parent("nested/child.yaml", "work"))
        self.write(child, self.parent("leaf.yaml"))
        self.write(leaf, self.parent("../../parent.yaml"))
        library = Library(self.storage, self.project)
        library.register(parent)
        self.assertCountEqual(
            [entry["path"] for entry in library.data["entries"]],
            [str(parent), str(child), str(leaf)],
        )
        restored = Library(self.storage, self.project)
        self.assertEqual(len(restored.data["entries"]), 3)

    def test_yaml_import_discovers_children_after_writing_parent(self):
        app = WorkbenchApplication(self.project, self.storage)
        child = self.project / "nested" / "child.yaml"
        self.write(child, starter("Child"))
        entry = app.mutation(
            "import",
            "",
            {
                "filename": "parent.yaml",
                "project": str(self.project),
                "yaml": render_document(self.parent("nested/child.yaml")),
            },
        )
        self.assertEqual(app.library.file(entry["id"]), self.project / "parent.yaml")
        self.assertIn(str(child), [item["path"] for item in app.library.data["entries"]])

    def test_missing_and_invalid_children_do_not_block_parent(self):
        parent = self.project / "parent.yaml"
        self.write(parent, self.parent("missing.yaml"))
        library = Library(self.storage, self.project)
        library.register(parent)
        self.write(self.project / "invalid.yaml", {"name": "invalid"})
        self.write(parent, self.parent("invalid.yaml"))
        library.register(parent)
        self.assertEqual(len(library.data["entries"]), 1)

    def test_import_manifest_assigns_folders_without_changing_execution(self):
        parent = self.project / "parent.yaml"
        child = self.project / "workflows" / "test" / "child.yaml"
        raw = starter("Parent")
        raw["library"] = {"folder": "Example", "imports": ["workflows/test/child.yaml"]}
        child_raw = starter("Child")
        child_raw["library"] = {"folder": "Example/Test"}
        self.write(parent, raw)
        self.write(child, child_raw)
        library = Library(self.storage, self.project)
        self.assertCountEqual(library.data["folders"], ["Example", "Example/Test"])
        entries = {Path(item["path"]): item for item in library.data["entries"]}
        self.assertEqual(entries[parent]["folder"], "Example")
        self.assertEqual(entries[child]["folder"], "Example/Test")
        self.assertEqual(len(raw["graphs"]["main"]["cards"]), 2)
        library.organize("new_folder", "", {"name": "Custom"})
        library.organize("move", entries[child]["id"], {"folder": "Custom"})
        library.register(parent)
        self.assertEqual(entries[child]["id"], library.register(child)["id"])
        self.assertEqual(library.register(child)["folder"], "Custom")

    def test_open_original_workspace_imports_manifest_and_nested_dependencies(self):
        from unittest.mock import patch

        from release_workbench.infrastructure.documents import DocumentStore

        parent = self.project / "release-workbench.yaml"
        child = self.project / "workflows" / "build" / "all.yaml"
        leaf = self.project / "workflows" / "build" / "android.yaml"
        raw = starter("AirDeck root")
        raw["library"] = {"folder": "AirDeck", "imports": ["workflows/build/all.yaml"]}
        nested = self.parent("workflows/build/android.yaml", "../..")
        nested["library"] = {"folder": "AirDeck/Build"}
        leaf_raw = starter("Android")
        leaf_raw["workspace"] = "../.."
        leaf_raw["library"] = {"folder": "AirDeck/Build/Android"}
        self.write(parent, raw)
        self.write(child, nested)
        self.write(leaf, leaf_raw)
        original = {file: file.read_text() for file in [parent, child, leaf]}
        other_project = self.root / "unrelated"
        other_project.mkdir()
        app = WorkbenchApplication(other_project, self.storage)
        with patch.object(app.workflow_picker, "choose", return_value=str(parent)):
            selection = app.mutation("pick-file", "", {})
        entry = app.mutation("register", "", selection)
        self.assertEqual(app.library.file(entry["id"]), parent)
        self.assertCountEqual(
            [
                item["path"]
                for item in app.library.data["entries"]
                if Path(item["path"]).is_relative_to(self.project)
            ],
            [str(f) for f in original],
        )
        self.assertIn("AirDeck/Build/Android", app.library.data["folders"])
        self.assertFalse(app.runs)
        self.assertEqual(DocumentStore(parent).read()["workflow"], raw)
        for file, text in original.items():
            self.assertEqual(file.read_text(), text)
