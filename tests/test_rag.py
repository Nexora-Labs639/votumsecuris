import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.rag import (
    init_rag_table, chunk_text, list_knowledge_files,
    scan_knowledge_dir, search, _cosine
)


class TestRAG(unittest.TestCase):

    def test_chunk_text_empty(self):
        self.assertEqual(chunk_text(""), [])

    def test_chunk_text_none(self):
        self.assertEqual(chunk_text(None), [])

    def test_chunk_text_small(self):
        result = chunk_text("hello world")
        self.assertGreater(len(result), 0)

    def test_cosine_identical(self):
        v = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(_cosine(v, v), 1.0, places=4)

    def test_cosine_zero_vector(self):
        self.assertEqual(_cosine([0, 0, 0], [1, 2, 3]), 0.0)

    def test_cosine_dim_mismatch(self):
        self.assertEqual(_cosine([1, 2], [1, 2, 3]), 0.0)

    def test_list_knowledge_files_returns_list(self):
        self.assertIsInstance(list_knowledge_files(), list)

    def test_scan_knowledge_dir_returns_dict(self):
        r = scan_knowledge_dir()
        self.assertIn("indexed", r)
        self.assertIn("total_chunks", r)

    def test_search_empty_query(self):
        self.assertEqual(search(""), [])


if __name__ == "__main__":
    unittest.main()