"""Checks that provincial records keep their city and source boundaries."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from .shaanxi_source_ingest import import_jsonl as import_source_cards
from .xiaohongshu_ingest import import_jsonl as import_xhs_notes


class ShaanxiIngestTests(unittest.TestCase):
    def test_huashan_note_is_assigned_to_weinan_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "notes.jsonl"
            database = root / "notes.sqlite3"
            item = {
                "source_url": "https://www.xiaohongshu.com/explore/huashan123",
                "city": "渭南", "attraction_name": "华山",
                "title": "华山徒步", "content": "西岳华山徒步见闻。",
            }
            source.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, import_xhs_notes(source, database)["imported"])
            with closing(sqlite3.connect(database)) as connection:
                row = connection.execute("SELECT city, attraction_id FROM xhs_notes").fetchone()
            self.assertEqual(("渭南", "huashan"), row)
            item["city"] = "西安"
            source.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown 陕西省/西安"):
                import_xhs_notes(source, database)

    def test_source_card_keeps_provenance_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cards.jsonl"
            database = root / "cards.sqlite3"
            card = {
                "city": "渭南", "attraction_name": "华山",
                "source_url": "https://www.chinahuashan.com/front/example",
                "source_title": "华山景区介绍", "source_type": "scenic_official",
                "reviewed_at": "2026-10-24", "content": "华山有东南西北中五峰。",
            }
            source.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, import_source_cards(source, database)["chunks"])
            self.assertEqual(1, import_source_cards(source, database)["unchanged"])
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute("SELECT city, metadata_json FROM attraction_chunks").fetchall()
            self.assertEqual(1, len(rows))
            self.assertEqual("渭南", rows[0][0])
            metadata = json.loads(rows[0][1])
            self.assertEqual("scenic_official", metadata["source_type"])
            self.assertEqual("source_reviewed", metadata["verification_status"])
            self.assertEqual(card["source_url"], metadata["source"])


if __name__ == "__main__":
    unittest.main()
