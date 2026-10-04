import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from policy.engine import evaluate


class TestPolicyEngine(unittest.TestCase):

    def test_junk_file_allow(self):
        r = evaluate("delete_file", {"path": "D:/tmp/a.tmp"}, "medium", None)
        self.assertEqual(r["action"], "allow")

    def test_important_file_require_approval(self):
        r = evaluate("delete_file", {"path": "D:/doc.docx"}, "medium", None)
        self.assertEqual(r["action"], "require_approval")

    def test_system_dir_deny(self):
        r = evaluate("delete_file", {"path": "C:/Windows/x.dll"}, "medium", None)
        self.assertEqual(r["action"], "deny")

    def test_dangerous_shell_deny(self):
        r = evaluate("run_shell", {"command": "rm -rf /"}, "high", None)
        self.assertEqual(r["action"], "deny")

    def test_normal_shell_require_approval(self):
        r = evaluate("run_shell", {"command": "echo hello"}, "high", None)
        self.assertEqual(r["action"], "require_approval")

    def test_empty_path(self):
        r = evaluate("delete_file", {"path": ""}, "medium", None)
        self.assertIn(r["action"], ["allow", "require_approval", "deny"])

    def test_none_path(self):
        r = evaluate("delete_file", {"path": None}, "medium", None)
        self.assertIn(r["action"], ["allow", "require_approval", "deny"])

    def test_result_has_required_fields(self):
        r = evaluate("read_file", {"path": "x.txt"}, "low", None)
        self.assertIn("action", r)
        self.assertIn("reason", r)
        self.assertIn("severity", r)


if __name__ == "__main__":
    unittest.main()