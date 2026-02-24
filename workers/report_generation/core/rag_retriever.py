"""
RAG Retriever — ChromaDB vector search + BM25 reranking for report generation.
Ported from multi_agent_system/agents/hypothesis_validator.py and section_writers.py.

Provides literature evidence retrieval for hypothesis validation and section writing.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CHROMADB_URL = os.getenv("CHROMADB_URL", "http://chromadb:8000")


class RAGRetriever:
    """ChromaDB-based retrieval with optional BM25 reranking."""

    def __init__(self, collection_names: Optional[List[str]] = None):
        self.collection_names = collection_names or []
        self._client = None
        self._collections: Dict[str, object] = {}
        self._cache: Dict[str, list] = {}

    @property
    def client(self):
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.HttpClient(
                    host=CHROMADB_URL.replace("http://", "").split(":")[0],
                    port=int(CHROMADB_URL.split(":")[-1]),
                )
                logger.info(f"ChromaDB connected at {CHROMADB_URL}")
            except Exception as e:
                logger.warning(f"ChromaDB connection failed: {e}")
                self._client = None
        return self._client

    def is_available(self) -> bool:
        try:
            if self.client:
                self.client.heartbeat()
                return True
        except Exception:
            pass
        return False

    def query(
        self, query_text: str, n_results: int = 5, relevance_threshold: float = 0.5
    ) -> List[dict]:
        """Query all collections and return merged, scored results."""
        cache_key = f"{query_text}:{n_results}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self.is_available():
            logger.warning("ChromaDB not available — returning empty results")
            return []

        all_results = []
        for coll_name in self.collection_names:
            try:
                coll = self._get_collection(coll_name)
                if coll is None:
                    continue

                results = coll.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )

                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                dists = results.get("distances", [[]])[0]

                for doc, meta, dist in zip(docs, metas, dists):
                    relevance = max(0, 1.0 - dist)
                    if relevance >= relevance_threshold:
                        all_results.append({
                            "document": doc[:500],
                            "metadata": meta or {},
                            "relevance": round(relevance, 3),
                            "collection": coll_name,
                            "title": (meta or {}).get("title", ""),
                            "authors": (meta or {}).get("authors", ""),
                            "year": (meta or {}).get("year", ""),
                            "source": (meta or {}).get("source", ""),
                        })

            except Exception as e:
                logger.warning(f"ChromaDB query failed for collection '{coll_name}': {e}")

        all_results.sort(key=lambda r: r["relevance"], reverse=True)
        result = all_results[:n_results]

        self._cache[cache_key] = result
        return result

    def query_with_reranking(
        self, query_text: str, n_results: int = 5,
        initial_fetch: int = 15, relevance_threshold: float = 0.3,
    ) -> List[dict]:
        """Query with BM25 reranking for improved precision."""
        candidates = self.query(query_text, n_results=initial_fetch, relevance_threshold=relevance_threshold)

        if not candidates:
            return candidates

        try:
            from rank_bm25 import BM25Okapi
            corpus = [c["document"].lower().split() for c in candidates]
            bm25 = BM25Okapi(corpus)
            query_tokens = query_text.lower().split()
            scores = bm25.get_scores(query_tokens)

            for cand, score in zip(candidates, scores):
                cand["bm25_score"] = float(score)
                cand["combined_score"] = round(0.6 * cand["relevance"] + 0.4 * min(score / max(scores.max(), 1), 1.0), 3)

            candidates.sort(key=lambda c: c.get("combined_score", c["relevance"]), reverse=True)
        except ImportError:
            logger.warning("rank_bm25 not available, skipping reranking")

        return candidates[:n_results]

    def search_for_hypothesis(self, hypothesis: dict) -> List[dict]:
        """Targeted search for hypothesis validation."""
        queries = [
            hypothesis.get("condition", ""),
            hypothesis.get("prediction", ""),
            hypothesis.get("mechanism", ""),
        ]
        query_text = " ".join(q for q in queries if q)
        return self.query_with_reranking(query_text, n_results=5)

    def search_for_section(self, section_type: str, keywords: List[str]) -> List[dict]:
        """Search for literature relevant to a specific report section."""
        query_text = f"{section_type}: {' '.join(keywords[:5])}"
        return self.query_with_reranking(query_text, n_results=10)

    def _get_collection(self, name: str):
        if name not in self._collections:
            try:
                self._collections[name] = self.client.get_collection(name)
            except Exception:
                logger.warning(f"Collection '{name}' not found")
                self._collections[name] = None
        return self._collections[name]
