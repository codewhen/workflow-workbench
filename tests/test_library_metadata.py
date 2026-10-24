"""Generic library discovery is organization only and remains cycle-safe."""

import tempfile
import unittest
from pathlib import Path

from release_workbench.application.starters import starter
from release_workbench.infrastructure.documents import compile_document, render_document
from release_workbench.infrastructure.library import Library


class LibraryMetadata(unittest.TestCase):
    def write(self, path, metadata):
        raw = starter(path.stem)
        raw["library"] = metadata
        path.write_text(render_document(raw), encoding="utf-8", newline="\n")
        return raw

    def test_metadata_imports_children_and_folder_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            library = Library(root / "storage", project)
            self.write(project / "child.yaml", {"folder": "Demo/Tests/Native"})
            parent = project / "parent.yaml"
            self.write(parent, {"folder": "Demo", "imports": ["child.yaml", "missing.yaml"]})
            library.register(parent)
            self.assertEqual(len(library.data["entries"]), 2)
            self.assertTrue(
                {"Demo", "Demo/Tests", "Demo/Tests/Native"} <= set(library.data["folders"])
            )

    def test_cycles_and_repeated_imports_do_not_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = Library(root / "storage", root)
            self.write(root / "a.yaml", {"imports": ["b.yaml"]})
            self.write(root / "b.yaml", {"imports": ["a.yaml"]})
            library.register(root / "a.yaml")
            library.register(root / "a.yaml")
            self.assertEqual(len(library.data["entries"]), 2)

    def test_automatic_discovery_does_not_restore_hidden_children(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            self.write(project / "a.yaml", {"imports": ["b.yaml"]})
            self.write(project / "b.yaml", {})
            library = Library(root / "storage", project)
            child = next(
                entry for entry in library.data["entries"] if Path(entry["path"]).name == "b.yaml"
            )
            library.remove(key=child["id"])
            restored = Library(root / "storage", project)
            self.assertEqual(
                [Path(entry["path"]).name for entry in restored.data["entries"]], ["a.yaml"]
            )

    def test_invalid_library_folder_is_rejected(self):
        raw = starter("Invalid folder")
        raw["library"] = {"folder": "Demo\\Tests"}
        with self.assertRaises(ValueError):
            compile_document(raw)
