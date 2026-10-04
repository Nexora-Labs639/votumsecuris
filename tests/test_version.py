import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.version import (
    init_version_table, snapshot, list_versions,
    diff, rollback, get_version
)


class TestVersion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_version_table()

    def test_snapshot_creates_version(self):
        r = snapshot(note="单元测试用")
        self.assertIn("ok", r)
        if r["ok"]:
            self.assertTrue(r["version"].startswith("v0."))

    def test_list_versions(self):
        result = list_versions()
        self.assertIsInstance(result, list)

    def test_get_nonexistent_version(self):
        r = get_version("v99.99")
        self.assertIn("error", r)

    def test_diff_nonexistent(self):
        r = diff("v99.1", "v99.2")
        self.assertIn("error", r)

    def test_rollback_nonexistent(self):
        r = rollback("v99.99")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()