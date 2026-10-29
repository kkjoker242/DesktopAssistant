"""FAISS index for local attraction evidence."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


class DemoHashEmbeddings(Embeddings):
    """Deterministic offline vectors for the example only, not production semantics."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        normalized = text.lower()
        chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
        words = re.findall(r"[a-z0-9]+", normalized)
        tokens = chinese + [
            "".join(chinese[index:index + 2])
            for index in range(len(chinese) - 1)
        ] + words
        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class IndexConstructionModule:
    def __init__(
        self,
        embeddings: Embeddings | None = None,
        index_save_path: str | Path = "RAGServe/vector_index",
    ) -> None:
        self.embeddings = embeddings or DemoHashEmbeddings()
        self.index_save_path = Path(index_save_path)
        self.vectorstore: FAISS | None = None

    def build_vector_index(self, chunks: list[Document]) -> FAISS:
        if not chunks:
            raise ValueError("At least one attraction chunk is required")
            raise ValueError("At least one attraction chunk is required")
        ids = [chunk.metadata["chunk_id"] for chunk in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("Chunk IDs must be unique")
        self.vectorstore = FAISS.from_documents(chunks, self.embeddings, ids=ids)
        return self.vectorstore

    def save_index(self) -> None:
        if self.vectorstore is None:
            raise ValueError("Build the index before saving")
        self.index_save_path.mkdir(parents=True, exist_ok=True)
        self.vectorstore.save_local(str(self.index_save_path))

    def load_index(self, *, trusted_local: bool = False) -> FAISS:
        if not trusted_local:
            raise ValueError("FAISS docstore uses pickle; load only a trusted local index")
        if not self.index_save_path.is_dir():
            raise FileNotFoundError(self.index_save_path)
        self.vectorstore = FAISS.load_local(
            str(self.index_save_path),
            self.embeddings,
            allow_dangerous_deserialization=True,
        )
        return self.vectorstore
