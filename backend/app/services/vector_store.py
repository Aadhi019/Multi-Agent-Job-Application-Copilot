from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


def _tokenize(text: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9+#.-]{2,}", (text or "").lower()))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStoreService:
    """Optional ChromaDB-backed embedding store with deterministic TF cosine fallback."""

    def __init__(self, persist_dir: str | None = None, collection_name: str = "copilot_profile") -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._memory_docs: dict[str, dict[str, Any]] = {}
        self._chroma_collection = None

        if persist_dir:
            try:
                import chromadb  # type: ignore

                client = chromadb.PersistentClient(path=persist_dir)
                self._chroma_collection = client.get_or_create_collection(name=collection_name)
            except Exception:
                self._chroma_collection = None

    def upsert_chunks(self, user_id: str, chunks: list[dict[str, Any]]) -> int:
        """Index profile experience, project, or resume chunks for semantic retrieval."""
        if not chunks:
            return 0

        if self._chroma_collection is not None:
            try:
                self._chroma_collection.upsert(
                    ids=[f"{user_id}:{c['id']}" for c in chunks],
                    documents=[c["text"] for c in chunks],
                    metadatas=[{"user_id": user_id, **c.get("metadata", {})} for c in chunks],
                )
                return len(chunks)
            except Exception:
                pass

        for c in chunks:
            key = f"{user_id}:{c['id']}"
            self._memory_docs[key] = {
                "id": key,
                "user_id": user_id,
                "text": c["text"],
                "metadata": c.get("metadata", {}),
                "vec": _tokenize(c["text"]),
            }
        return len(chunks)

    def query(self, user_id: str, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve top_k relevant profile chunks for a given job description or query."""
        if self._chroma_collection is not None:
            try:
                res = self._chroma_collection.query(
                    query_texts=[query_text],
                    n_results=top_k,
                    where={"user_id": user_id},
                )
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                dists = (res.get("distances") or [[]])[0]
                return [
                    {"text": d, "metadata": m, "score": round(max(0.0, 1.0 - float(dist)), 4)}
                    for d, m, dist in zip(docs, metas, dists)
                ]
            except Exception:
                pass

        q_vec = _tokenize(query_text)
        candidates = [d for d in self._memory_docs.values() if d["user_id"] == user_id]
        scored = [
            {"text": d["text"], "metadata": d["metadata"], "score": round(_cosine(q_vec, d["vec"]), 4)}
            for d in candidates
        ]
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]
