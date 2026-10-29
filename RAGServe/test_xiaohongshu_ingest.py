"""Checks for the Xi'an note ingestion boundary and chunk lifecycle."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from .data_preparation import DataPreparationModule
from .index_construction import IndexConstructionModule
from .xiaohongshu_ingest import check_crawl_permission, import_jsonl


class XiaohongshuIngestTests(unittest.TestCase):
    def test_import_is_idempotent_and_replaces_changed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "notes.jsonl"
            database = root / "notes.sqlite3"
            note = {
                "source_url": "https://www.xiaohongshu.com/explore/a123456",
                "region": "陕西省",
                "city": "西安",
                "attraction_name": "大雁塔",
                "title": "大雁塔游览",
                "content": "围绕大雁塔步行，记录沿途见闻。",
            }
            source.write_text(json.dumps(note, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, import_jsonl(source, database)["chunks"])
            self.assertEqual(1, import_jsonl(source, database)["unchanged"])
            with closing(sqlite3.connect(database)) as connection:
                first = DataPreparationModule.load_chunks_from_sqlite(connection)
            self.assertEqual("big_wild_goose_pagoda", first[0].metadata["attraction_id"])
            self.assertEqual("unverified", first[0].metadata["verification_status"])

            note["content"] = "修改后的大雁塔游览记录。"
            source.write_text(json.dumps(note, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, import_jsonl(source, database)["imported"])
            with closing(sqlite3.connect(database)) as connection:
                updated = DataPreparationModule.load_chunks_from_sqlite(connection)
                note_count = connection.execute("SELECT COUNT(*) FROM xhs_notes").fetchone()[0]
            self.assertEqual(1, note_count)
            self.assertEqual(1, len(updated))
            self.assertNotEqual(first[0].metadata["chunk_id"], updated[0].metadata["chunk_id"])
            store = IndexConstructionModule().build_vector_index(updated)
            self.assertEqual(1, store.index.ntotal)

    def test_multi_attraction_note_is_kept_out_of_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "notes.jsonl"
            database = root / "notes.sqlite3"
            source.write_text(json.dumps({
                "source_url": "https://www.xiaohongshu.com/explore/b123456",
                "city": "西安",
                "title": "西安一日游",
                "content": "上午去了大雁塔，下午去了西安城墙。",
            }, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, import_jsonl(source, database)["unassigned"])
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual([], DataPreparationModule.load_chunks_from_sqlite(connection))

    def test_robots_gate_disallows_explore(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self):
                return b"User-agent: *\nDisallow: /\n"

        with patch("RAGServe.xiaohongshu_ingest.urlopen", return_value=Response()):
            self.assertFalse(check_crawl_permission())


if __name__ == "__main__":
    unittest.main()
