"""Tests for workspace file operations and project inspection restrictions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_herness_build.tools import files


class WorkspaceFileTests(unittest.TestCase):
    """Verify generated writes and allowlisted project reads."""

    def setUp(self) -> None:
        """Give each test isolated workspace and project roots."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.project_root = Path(self.temp_dir.name) / "project"
        self.project_root.mkdir()
        self.patch_workspace = patch.object(files, "WORKSPACE", self.workspace)
        self.patch_project_root = patch.object(files, "PROJECT_ROOT", self.project_root)
        self.patch_workspace.start()
        self.patch_project_root.start()
        self.addCleanup(self.patch_workspace.stop)
        self.addCleanup(self.patch_project_root.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_listing_creates_a_missing_workspace(self) -> None:
        self.assertEqual(files.list_files(), "(empty)")
        self.assertTrue(self.workspace.is_dir())

    def test_write_and_read_generated_file(self) -> None:
        self.assertEqual(
            files.write_file("notes/today.txt", "hello"),
            "wrote generated/notes/today.txt",
        )
        self.assertEqual(files.read_file("generated/notes/today.txt"), "hello")
        self.assertIn("generated", files.list_files())

    def test_overwriting_existing_file_requires_confirmation(self) -> None:
        files.write_file("notes.txt", "original")
        with patch("builtins.input", return_value="n") as prompt:
            result = files.write_file("notes.txt", "replacement")
        prompt.assert_called_once()
        self.assertIn("cancelled", result)
        self.assertEqual(files.read_file("generated/notes.txt"), "original")

    def test_confirmed_overwrite_replaces_generated_file(self) -> None:
        files.write_file("notes.txt", "original")
        with patch("builtins.input", return_value="yes"):
            result = files.write_file("notes.txt", "replacement")
        self.assertEqual(result, "wrote generated/notes.txt")
        self.assertEqual(files.read_file("generated/notes.txt"), "replacement")

    def test_workspace_read_and_generated_write_reject_parent_traversal(self) -> None:
        self.assertTrue(files.read_file("../outside.txt").startswith("error:"))
        self.assertTrue(files.write_file("../outside.txt", "no").startswith("error:"))
        self.assertFalse((self.workspace.parent / "outside.txt").exists())

    def test_generated_write_rejects_absolute_paths(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        self.assertTrue(
            files.write_file(str(outside / "bad.txt"), "no").startswith("error:")
        )
        self.assertFalse((outside / "bad.txt").exists())

    def test_generated_write_rejects_symlinked_directory(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        self.workspace.mkdir()
        (self.workspace / "generated").symlink_to(outside, target_is_directory=True)
        self.assertTrue(files.write_file("bad.txt", "no").startswith("error:"))
        self.assertFalse((outside / "bad.txt").exists())

    def test_generated_write_rejects_file_symlink_outside_directory(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.txt"
        outside.write_text("original", encoding="utf-8")
        generated = self.workspace / "generated"
        generated.mkdir(parents=True)
        (generated / "linked.txt").symlink_to(outside)
        self.assertTrue(
            files.write_file("linked.txt", "replacement").startswith("error:")
        )
        self.assertEqual(outside.read_text(encoding="utf-8"), "original")

    def test_project_listing_only_shows_allowlisted_entries(self) -> None:
        (self.project_root / "README.md").write_text("docs", encoding="utf-8")
        (self.project_root / "pyproject.toml").write_text("[project]", encoding="utf-8")
        (self.project_root / ".env").write_text("secret", encoding="utf-8")
        (self.project_root / "credentials.json").write_text("secret", encoding="utf-8")
        source = self.project_root / "src" / "package"
        source.mkdir(parents=True)
        (source / "module.py").write_text("value = 1", encoding="utf-8")
        (source / ".private").write_text("hidden", encoding="utf-8")
        (self.project_root / "tests").mkdir()
        config = self.project_root / "config"
        config.mkdir()
        (config / "mcp_servers.example.json").write_text("{}", encoding="utf-8")
        (config / "mcp_servers.json").write_text("secret", encoding="utf-8")
        (self.project_root / ".git").mkdir()

        self.assertEqual(
            files.list_project_files(),
            "README.md\nconfig\npyproject.toml\nsrc\ntests",
        )
        self.assertEqual(files.list_project_files("src/package"), "module.py")
        self.assertEqual(
            files.list_project_files("config"), "mcp_servers.example.json"
        )

    def test_project_read_allows_selected_files_and_rejects_private_paths(self) -> None:
        (self.project_root / "README.md").write_text("docs", encoding="utf-8")
        (self.project_root / "src").mkdir()
        (self.project_root / "src" / "module.py").write_text(
            "value = 1", encoding="utf-8"
        )
        self.assertEqual(files.read_project_file("README.md"), "docs")
        self.assertEqual(files.read_project_file("src/module.py"), "value = 1")

        for filename in (
            "../outside.txt",
            ".env",
            "credentials.json",
            ".git/config",
            "workspace/private.txt",
            "config/mcp_servers.json",
        ):
            with self.subTest(filename=filename):
                self.assertTrue(
                    files.read_project_file(filename).startswith("error:")
                )

    def test_project_read_excludes_sensitive_names_within_source_tree(self) -> None:
        source = self.project_root / "src"
        source.mkdir()
        for filename in (".env", "credentials.json", "mcp_servers.json"):
            (source / filename).write_text("sensitive", encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertTrue(
                    files.read_project_file(f"src/{filename}").startswith("error:")
                )
        self.assertNotIn(".env", files.list_project_files("src"))
        self.assertNotIn(
            "credentials.json", files.list_project_files("src")
        )
        self.assertNotIn("mcp_servers.json", files.list_project_files("src"))

    def test_project_read_rejects_symlink_escaping_allowlisted_tree(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.py"
        outside.write_text("sensitive", encoding="utf-8")
        source = self.project_root / "src"
        source.mkdir()
        (source / "outside.py").symlink_to(outside)
        self.assertTrue(
            files.read_project_file("src/outside.py").startswith("error:")
        )

    def test_missing_file_returns_an_error(self) -> None:
        self.assertEqual(
            files.read_file("missing.txt"), "error: no file named missing.txt"
        )


if __name__ == "__main__":
    unittest.main()
