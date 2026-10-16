"""Tests for safe discovery and loading of behavioral skills."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_herness_build import skills


class SkillLoadingTests(unittest.TestCase):
    def test_list_skills_returns_markdown_skill_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "systematic-debugging.md").write_text("debug", encoding="utf-8")
            (root / "not a skill.md").write_text("ignored", encoding="utf-8")
            (root / "notes.txt").write_text("ignored", encoding="utf-8")
            with patch.object(skills, "SKILLS_DIR", root):
                self.assertEqual(skills.list_skills(), ["systematic-debugging"])

    def test_load_skill_reads_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path = root / "env-doctor.md"
            skill_path.write_text("# Environment Doctor\nCheck versions.", encoding="utf-8")
            with patch.object(skills, "SKILLS_DIR", root):
                self.assertEqual(
                    skills.load_skill("env-doctor"),
                    "# Environment Doctor\nCheck versions.",
                )

    def test_load_skill_rejects_traversal_and_unknown_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "skills"
            root.mkdir()
            with patch.object(skills, "SKILLS_DIR", root):
                with self.assertRaisesRegex(ValueError, "skill name"):
                    skills.load_skill("../secret")
                with self.assertRaisesRegex(ValueError, "no skill named"):
                    skills.load_skill("missing")

    def test_load_skill_rejects_symlink_outside_skills_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "skills"
            root.mkdir()
            (base / "outside.md").write_text("outside", encoding="utf-8")
            (root / "external.md").symlink_to(base / "outside.md")
            with patch.object(skills, "SKILLS_DIR", root):
                with self.assertRaisesRegex(ValueError, "stay inside"):
                    skills.load_skill("external")


if __name__ == "__main__":
    unittest.main()
