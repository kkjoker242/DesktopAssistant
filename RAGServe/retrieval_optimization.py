"""Hybrid search over attraction chunks with source-preserving results."""

from __future__ import annotations

import re
from collections import defaultdict

from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document


def tokenize_chinese(text: str) -> list[str]:
    text = text.lower()
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    return chinese + [
        "".join(chinese[index:index + 2])
        for index in range(len(chinese) - 1)
    ] + re.findall(r"[a-z0-9]+", text)


class RetrievalOptimizationModule:
    def __init__(self, vectorstore: FAISS, chunks: list[Document]) -> None:
        if not chunks:
            raise ValueError("At least one attraction chunk is required")
        self.vectorstore = vectorstore
        self.chunks = chunks
        self.keyword_retriever = BM25Retriever.from_documents(
            chunks,
            preprocess_func=tokenize_chinese,
            k=len(chunks),
        )

    def hybrid_search(
        self,
        query: str,
        *,
        city: str,
        attraction_ids: set[str] | None = None,
        top_k: int = 5,
    ) -> list[Document]:
        if top_k < 1:
            return []

        def matches(doc: Document) -> bool:
            return doc.metadata.get("city") == city and (
                attraction_ids is None
                or doc.metadata.get("attraction_id") in attraction_ids
            )

        vector_docs = [
            doc for doc in self.vectorstore.similarity_search(query, k=len(self.chunks))
            if matches(doc)
        ]
        keyword_docs = [
            doc for doc in self.keyword_retriever.invoke(query)
            if matches(doc)
        ]
        scores: dict[str, float] = defaultdict(float)
        docs: dict[str, Document] = {}
        for ranked in (vector_docs, keyword_docs):
            for rank, doc in enumerate(ranked, start=1):
                chunk_id = doc.metadata["chunk_id"]
                docs[chunk_id] = doc
                scores[chunk_id] += 1.0 / (60 + rank)
        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        return [docs[chunk_id] for chunk_id in ordered[:top_k]]
