import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from executor.policy_bridge import request_delete, check_output


class TestPolicyBridge(unittest.TestCase):

    def test_request_delete_nonexistent_file(self):
        r = request_delete("test-agent", "D:/definitely_not_exist_xyz.txt")
        self.assertIn("status", r)
        self.assertIn(r["status"], ["denied", "error", "deleted", "need_approval"])

    def test_request_delete_empty_path(self):
        r = request_delete("test-agent", "")
        self.assertIn("status", r)

    def test_check_output_normal(self):
        r = check_output("我会尽力完成")
        self.assertIn("ok", r)

    def test_check_output_blocked(self):
        r = check_output("我保证")
        self.assertIn("blocked", r)
        self.assertTrue(r["blocked"])


if __name__ == "__main__":
    unittest.main()