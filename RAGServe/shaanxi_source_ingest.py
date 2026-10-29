"""Import reviewed Shaanxi attraction source cards into the travel RAG."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .shaanxi_catalog import CITIES, REGION, resolve_attraction
from .xiaohongshu_ingest import _create_schema

SOURCE_TYPES = {"government_page", "scenic_official", "museum_official"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def import_jsonl(input_path: Path, database_path: Path) -> dict[str, int]:
    """Upsert short paraphrased cards and their traceable retrieval chunks."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"imported": 0, "unchanged": 0, "chunks": 0}
    with closing(sqlite3.connect(database_path)) as connection:
        _create_schema(connection)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS attraction_source_cards (
                card_id TEXT PRIMARY KEY,
                region TEXT NOT NULL,
                city TEXT NOT NULL,
                attraction_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                content TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                content_hash TEXT NOT NULL
            )
        """)
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=450, chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        )
        for line_number, line in enumerate(input_path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                city = item["city"].strip()
                if city not in CITIES or item.get("region", REGION) != REGION:
                    raise ValueError("Only catalogued 陕西省 localities are accepted")
                attraction_id, attraction_name = resolve_attraction(city, item["attraction_name"].strip())
                source_url = item["source_url"].strip()
                parsed = urlparse(source_url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("source_url must be a public HTTPS page")
                source_type = item["source_type"]
                if source_type not in SOURCE_TYPES:
                    raise ValueError(f"Unsupported source_type: {source_type}")
                title = item["source_title"].strip()
                content = item["content"].strip()
                reviewed_at = item["reviewed_at"].strip()
                if not title or not content or not reviewed_at:
                    raise ValueError("source_title, content and reviewed_at are required")
                datetime.fromisoformat(reviewed_at)
                card_id = _hash(f"{source_url}:{attraction_id}")
                content_hash = _hash(json.dumps(
                    [city, attraction_id, source_url, title, source_type, content, reviewed_at],
                    ensure_ascii=False,
                ))
                old = connection.execute(
                    "SELECT content_hash FROM attraction_source_cards WHERE card_id = ?", (card_id,)
                ).fetchone()
                if old and old[0] == content_hash:
                    counts["unchanged"] += 1
                    continue
                document_id = _hash("source_card:" + card_id)
                updated_at = datetime.now(timezone.utc).isoformat()
                chunks = []
                for position, piece in enumerate(splitter.split_text(content)):
                    chunk_content = f"{attraction_name}｜{title}\n{piece.strip()}"
                    metadata = {
                        "chunk_id": _hash(f"{document_id}:{position}:{piece}"),
                        "document_id": document_id,
                        "region": REGION,
                        "city": city,
                        "attraction_id": attraction_id,
                        "attraction_name": attraction_name,
                        "section": "景点介绍",
                        "source": source_url,
                        "source_title": title,
                        "source_type": source_type,
                        "source_card_id": card_id,
                        "reviewed_at": reviewed_at,
                        "updated_at": updated_at,
                        "verification_status": "source_reviewed",
                        "fact_type": "static_description",
                    }
                    chunks.append((metadata["chunk_id"], document_id, city, attraction_id,
                                   source_url, updated_at, position, chunk_content,
                                   json.dumps(metadata, ensure_ascii=False)))
                with connection:
                    connection.execute("DELETE FROM attraction_chunks WHERE document_id = ?", (document_id,))
                    connection.execute("""
                        INSERT INTO attraction_source_cards
                        (card_id, region, city, attraction_id, source_url, source_title,
                         source_type, content, reviewed_at, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(card_id) DO UPDATE SET
                            region=excluded.region, city=excluded.city,
                            attraction_id=excluded.attraction_id, source_url=excluded.source_url,
                            source_title=excluded.source_title, source_type=excluded.source_type,
                            content=excluded.content, reviewed_at=excluded.reviewed_at,
                            content_hash=excluded.content_hash
                    """, (card_id, REGION, city, attraction_id, source_url, title,
                           source_type, content, reviewed_at, content_hash))
                    connection.executemany("""
                        INSERT INTO attraction_chunks
                        (chunk_id, document_id, city, attraction_id, source, updated_at,
                         position, content, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, chunks)
                counts["imported"] += 1
                counts["chunks"] += len(chunks)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Line {line_number}: {exc}") from exc
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--database", type=Path, default=Path("RAGServe/data/shaanxi.sqlite3"))
    args = parser.parse_args()
    print(json.dumps(import_jsonl(args.input, args.database), ensure_ascii=False))


if __name__ == "__main__":
    main()
