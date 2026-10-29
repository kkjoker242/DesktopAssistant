"""Load attraction records and turn them into traceable LangChain documents."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class DataPreparationModule:
    def __init__(self, data_path: str | Path | None = None) -> None:
        self.data_path = Path(data_path or Path(__file__).with_name("sample_data"))
        self.documents: list[Document] = []
        self.chunks: list[Document] = []
        self.catalogs: dict[str, dict] = {}

    def load_documents(self) -> list[Document]:
        paths = sorted(self.data_path.glob("*.json")) if self.data_path.is_dir() else [self.data_path]
        if not paths:
            raise FileNotFoundError(f"No attraction data found at {self.data_path}")

        documents: list[Document] = []
        catalogs: dict[str, dict] = {}
        for path in paths:
            catalog = json.loads(path.read_text(encoding="utf-8"))
            city = catalog["city"]
            if city in catalogs:
                raise ValueError(f"Duplicate city catalog: {city}")
            catalogs[city] = catalog
            for attraction in catalog["attractions"]:
                attraction_id = attraction["id"]
                for section in attraction["sections"]:
                    content = f"{attraction['name']} - {section['title']}\n{section['text']}"
                    source = str(path.resolve())
                    document_id = hashlib.sha256(
                        f"{source}:{attraction_id}:{section['title']}".encode("utf-8")
                    ).hexdigest()
                    documents.append(
                        Document(
                            page_content=content,
                            metadata={
                                "document_id": document_id,
                                "city": city,
                                "attraction_id": attraction_id,
                                "attraction_name": attraction["name"],
                                "section": section["title"],
                                "source": source,
                                "source_type": catalog.get("source_type", "sample"),
                                "updated_at": catalog.get("updated_at", "unknown"),
                            },
                        )
                    )
        self.catalogs = catalogs
        self.documents = documents
        return documents

    def chunk_documents(self, chunk_size: int = 450, chunk_overlap: int = 50) -> list[Document]:
        if not self.documents:
            self.load_documents()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunks = splitter.split_documents(self.documents)
        for chunk in chunks:
            chunk.metadata["chunk_id"] = hashlib.sha256(
                (chunk.metadata["document_id"] + ":" + chunk.page_content).encode("utf-8")
            ).hexdigest()
        self.chunks = chunks
        return chunks

    def get_catalog(self, city: str) -> dict:
        if not self.catalogs:
            self.load_documents()
        try:
            return self.catalogs[city]
        except KeyError as exc:
            raise ValueError(f"No catalog for city: {city}") from exc

    def save_chunks_to_sqlite(self, connection: sqlite3.Connection) -> None:
        if not self.chunks:
            self.chunk_documents()
        connection.execute(
            """CREATE TABLE IF NOT EXISTS attraction_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                city TEXT NOT NULL,
                attraction_id TEXT NOT NULL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                position INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )"""
        )
        connection.executemany(
            """INSERT OR REPLACE INTO attraction_chunks
               (chunk_id, document_id, city, attraction_id, source,
                updated_at, position, content, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    chunk.metadata["chunk_id"],
                    chunk.metadata["document_id"],
                    chunk.metadata["city"],
                    chunk.metadata["attraction_id"],
                    chunk.metadata["source"],
                    chunk.metadata["updated_at"],
                    position,
                    chunk.page_content,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                )
                for position, chunk in enumerate(self.chunks)
            ],
        )
        connection.commit()

    @staticmethod
    def load_chunks_from_sqlite(connection: sqlite3.Connection) -> list[Document]:
        rows = connection.execute(
            "SELECT content, metadata_json FROM attraction_chunks ORDER BY position"
        ).fetchall()
        return [
            Document(page_content=content, metadata=json.loads(metadata_json))
            for content, metadata_json in rows
        ]
