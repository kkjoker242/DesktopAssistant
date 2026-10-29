"""Import authorized Xiaohongshu travel note exports into the local travel RAG.

The ``crawl`` command checks the site's robots policy before any page request.
The current public policy disallows generic crawlers, so use ``import-jsonl``
with data that you are authorized to retain and process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .data_preparation import DataPreparationModule
from .index_construction import IndexConstructionModule
from .shaanxi_catalog import ATTRACTIONS, CITIES, REGION, resolve_attraction


USER_AGENT = "MCP_MOD-TravelRAG/0.1"
EXPLORE_URL = "https://www.xiaohongshu.com/explore"
ROBOTS_URL = "https://www.xiaohongshu.com/robots.txt"

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _note_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.xiaohongshu.com", "xiaohongshu.com"}:
        raise ValueError("source_url must be an HTTPS xiaohongshu.com URL")
    match = re.fullmatch(r"/(?:explore|discovery/item)/([a-zA-Z0-9]+)/*", parsed.path)
    if not match:
        raise ValueError("source_url must link to a Xiaohongshu note")
    return match.group(1)


def _attribution(item: dict) -> tuple[str, str] | None:
    city = item["city"]
    explicit = _clean(item.get("attraction_name", ""))
    if explicit:
        return resolve_attraction(city, explicit)
    text = _clean(item.get("title", "") + " " + item.get("content", ""))
    matches = [
        (key, name) for key, (place, name, aliases) in ATTRACTIONS.items()
        if place == city and any(alias in text for alias in aliases)
    ]
    return matches[0] if len(matches) == 1 else None


def _chunks(item: dict, note_id: str, attraction_id: str, attraction_name: str) -> list[Document]:
    title = _clean(item["title"])
    body = item["content"].strip()
    # Short social posts remain one unit. Longer posts split at paragraph and
    # sentence boundaries; overlap keeps a sentence near a boundary in context.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=420,
        chunk_overlap=40,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
    )
    pieces = splitter.split_text(body)
    source_url = item["source_url"]
    document_id = _hash("xiaohongshu:" + note_id)
    result = []
    for position, piece in enumerate(pieces):
        content = f"{attraction_name}｜{title}\n{piece.strip()}"
        metadata = {
            "chunk_id": _hash(f"{document_id}:{attraction_id}:{position}:{_clean(piece)}"),
            "document_id": document_id,
            "city": item["city"],
            "region": REGION,
            "attraction_id": attraction_id,
            "attraction_name": attraction_name,
            "section": "游客笔记",
            "source": source_url,
            "source_type": "user_generated_note",
            "source_note_id": note_id,
            "published_at": item.get("published_at") or "unknown",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "verification_status": "unverified",
            "fact_type": "visitor_experience",
        }
        result.append(Document(page_content=content, metadata=metadata))
    return result


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS xhs_notes (
            note_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE,
            region TEXT NOT NULL,
            city TEXT NOT NULL,
            attraction_id TEXT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            published_at TEXT,
            imported_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('assigned', 'unassigned'))
        );
        CREATE INDEX IF NOT EXISTS idx_xhs_notes_place
            ON xhs_notes(city, attraction_id);
        CREATE TABLE IF NOT EXISTS attraction_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            city TEXT NOT NULL,
            attraction_id TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            position INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attraction_chunks_place
            ON attraction_chunks(city, attraction_id);
    """)


def import_jsonl(input_path: Path, database_path: Path) -> dict[str, int]:
    """Upsert note records and replace changed note chunks atomically."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"imported": 0, "unchanged": 0, "unassigned": 0, "chunks": 0}
    with closing(sqlite3.connect(database_path)) as connection:
        _create_schema(connection)
        for line_number, line in enumerate(input_path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if item.get("city") not in CITIES or item.get("region", REGION) != REGION:
                    raise ValueError("Only catalogued 陕西省 localities are accepted")
                note_id = _note_id(item["source_url"])
                title, content = _clean(item["title"]), item["content"].strip()
                if not title or not content:
                    raise ValueError("title and content are required")
                item["title"], item["content"] = title, content
                attribution = _attribution(item)
                content_hash = _hash(json.dumps(
                    [REGION, item["city"], title, content, item.get("published_at"), attribution],
                    ensure_ascii=False,
                ))
                old = connection.execute(
                    "SELECT content_hash FROM xhs_notes WHERE note_id = ?", (note_id,)
                ).fetchone()
                if old and old[0] == content_hash:
                    counts["unchanged"] += 1
                    continue
                chunks = _chunks(item, note_id, *attribution) if attribution else []
                imported_at = datetime.now(timezone.utc).isoformat()
                with connection:
                    connection.execute(
                        "DELETE FROM attraction_chunks WHERE document_id = ?",
                        (_hash("xiaohongshu:" + note_id),),
                    )
                    connection.execute("""
                        INSERT INTO xhs_notes
                        (note_id, source_url, region, city, attraction_id, title, content,
                         published_at, imported_at, content_hash, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(note_id) DO UPDATE SET
                            source_url=excluded.source_url, region=excluded.region,
                            city=excluded.city, attraction_id=excluded.attraction_id,
                            title=excluded.title, content=excluded.content,
                            published_at=excluded.published_at, imported_at=excluded.imported_at,
                            content_hash=excluded.content_hash, status=excluded.status
                    """, (note_id, item["source_url"], REGION, item["city"],
                           attribution[0] if attribution else None, title, content,
                           item.get("published_at"), imported_at, content_hash,
                           "assigned" if attribution else "unassigned"))
                    connection.executemany("""
                        INSERT INTO attraction_chunks
                        (chunk_id, document_id, city, attraction_id, source, updated_at,
                         position, content, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [(
                        doc.metadata["chunk_id"], doc.metadata["document_id"], item["city"],
                        doc.metadata["attraction_id"], doc.metadata["source"],
                        doc.metadata["updated_at"], position, doc.page_content,
                        json.dumps(doc.metadata, ensure_ascii=False),
                    ) for position, doc in enumerate(chunks)])
                counts["imported"] += 1
                counts["unassigned"] += not bool(attribution)
                counts["chunks"] += len(chunks)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Line {line_number}: {exc}") from exc
    return counts


def check_crawl_permission() -> bool:
    """Fail closed when robots is unavailable or does not permit /explore."""
    request = Request(ROBOTS_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=15) as response:
        robots = response.read().decode("utf-8")
    parser = RobotFileParser()
    parser.parse(robots.splitlines())
    return parser.can_fetch(USER_AGENT, EXPLORE_URL)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("crawl", help="Check whether /explore permits this crawler")
    importer = subcommands.add_parser("import-jsonl", help="Import an authorized JSONL export")
    importer.add_argument("input", type=Path)
    importer.add_argument("--database", type=Path, default=Path("RAGServe/data/shaanxi.sqlite3"))
    indexer = subcommands.add_parser("build-index", help="Build a local demonstration FAISS index")
    indexer.add_argument("--database", type=Path, default=Path("RAGServe/data/shaanxi.sqlite3"))
    indexer.add_argument("--output", type=Path, default=Path("RAGServe/data/shaanxi_faiss"))
    args = parser.parse_args()
    if args.command == "crawl":
        try:
            allowed = check_crawl_permission()
        except Exception as exc:
            parser.exit(2, f"Cannot verify robots.txt; no pages fetched: {exc}\n")
        if not allowed:
            parser.exit(2, "robots.txt disallows this crawler at /explore; no pages fetched.\n")
        parser.exit(2, "Robots now permits /explore; page extraction still needs a verified adapter.\n")
    if args.command == "import-jsonl":
        print(json.dumps(import_jsonl(args.input, args.database), ensure_ascii=False))
        return
    with closing(sqlite3.connect(args.database)) as connection:
        chunks = DataPreparationModule.load_chunks_from_sqlite(connection)
    if not chunks:
        parser.error("No assigned attraction chunks in the database")
    builder = IndexConstructionModule(index_save_path=args.output)
    builder.build_vector_index(chunks)
    builder.save_index()
    print(f"Built demonstration index: {len(chunks)} chunks -> {args.output}")


if __name__ == "__main__":
    main()
