"""Tests for workspace file operations and path restrictions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_herness_build.tools import files


class WorkspaceFileTests(unittest.TestCase):
    """Verify workspace files work from a clean directory."""

    def setUp(self) -> None:
        """Give each test an isolated temporary workspace."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.patch_workspace = patch.object(files, "WORKSPACE", self.workspace)
        self.patch_workspace.start()
        self.addCleanup(self.patch_workspace.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_listing_creates_a_missing_workspace(self) -> None:
        """A first list operation creates the configured workspace."""
        self.assertEqual(files.list_files(), "(empty)")
        self.assertTrue(self.workspace.is_dir())

    def test_write_and_read_file(self) -> None:
        """Written content can be read back from the workspace."""
        self.assertEqual(files.write_file("notes/today.txt", "hello"), "wrote notes/today.txt")
        self.assertEqual(files.read_file("notes/today.txt"), "hello")
        self.assertIn("notes", files.list_files())

    def test_overwriting_existing_file_requires_confirmation(self) -> None:
        files.write_file("notes.txt", "original")
        with patch("builtins.input", return_value="n") as prompt:
            result = files.write_file("notes.txt", "replacement")
        prompt.assert_called_once()
        self.assertIn("cancelled", result)
        self.assertEqual(files.read_file("notes.txt"), "original")

    def test_confirmed_overwrite_replaces_file(self) -> None:
        files.write_file("notes.txt", "original")
        with patch("builtins.input", return_value="yes"):
            result = files.write_file("notes.txt", "replacement")
        self.assertEqual(result, "wrote notes.txt")
        self.assertEqual(files.read_file("notes.txt"), "replacement")

    def test_paths_outside_workspace_are_rejected(self) -> None:
        """Read and write tools refuse parent-directory traversal."""
        self.assertTrue(files.read_file("../outside.txt").startswith("error:"))
        self.assertTrue(files.write_file("../outside.txt", "no").startswith("error:"))
        self.assertFalse((self.workspace.parent / "outside.txt").exists())

    def test_missing_file_returns_an_error(self) -> None:
        """Reading a nonexistent workspace file returns a clear error."""
        self.assertEqual(files.read_file("missing.txt"), "error: no file named missing.txt")


if __name__ == "__main__":
    unittest.main()
