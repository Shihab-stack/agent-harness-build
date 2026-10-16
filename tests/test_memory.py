"""Tests for persistent assistant memory."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_herness_build.tools import memory


class MemoryTests(unittest.TestCase):
    """Verify the memory tool creates and reads its file safely."""

    def test_save_and_load_memory(self) -> None:
        """Memory facts persist as readable lines."""
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_file = Path(temp_dir) / "workspace" / "memory.md"
            with patch.object(memory, "MEMORY_FILE", memory_file):
                self.assertEqual(memory.load_memory(), "(nothing saved yet)")
                self.assertEqual(memory.save_memory("prefers concise answers"), "saved: prefers concise answers")
                self.assertIn("prefers concise answers", memory.load_memory())


if __name__ == "__main__":
    unittest.main()
