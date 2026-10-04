import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.error_archive import init, record_error, check_before


class TestErrorArchive(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init()
        record_error("test-agent", "测试场景A", "错误A", "教训A")
        record_error("test-agent", "测试场景B", "错误B", "教训B")

    def test_record_and_check(self):
        results = check_before("测试场景")
        self.assertIsInstance(results, list)

    def test_similar_scenario_found(self):
        results = check_before("测试场景A")
        self.assertGreater(len(results), 0)

    def test_unrelated_scenario(self):
        results = check_before("完全不相关的场景XYZ")
        self.assertIsInstance(results, list)

    def test_empty_scenario(self):
        results = check_before("")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()