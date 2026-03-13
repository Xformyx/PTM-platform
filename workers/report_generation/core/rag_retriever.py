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
    """ChromaDB-based retrieval with optional BM25 reranking.

    v84: Includes source-type inference (textbook / review / research_article),
    relevance boosting for textbooks and reviews, and guaranteed minimum slots
    for high-authority sources.
    """

    # v84 constants
    TEXTBOOK_COLLECTIONS = {"textbooks", "textbook", "books", "book"}
    REVIEW_COLLECTIONS = {"reviews", "review", "review_papers"}
    TEXTBOOK_BOOST = 0.15
    REVIEW_BOOST = 0.10
    MIN_TEXTBOOK_REVIEW_SLOTS = 5

    def __init__(self, collection_names: Optional[List[str]] = None):
        self.collection_names = collection_names or []
        self._client = None
        self._collections: Dict[str, object] = {}
        self._cache: Dict[str, list] = {}
        self._resolved_names: Optional[List[str]] = None  # Filtered to existing only

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

    def _resolve_existing_collections(self) -> List[str]:
        """Filter collection_names to only those that exist in ChromaDB. Reduces 404 log noise."""
        if self._resolved_names is not None:
            return self._resolved_names
        if not self.is_available() or not self.collection_names:
            self._resolved_names = []
            return self._resolved_names
        try:
            existing = {c.name for c in self.client.list_collections()}
            self._resolved_names = [n for n in self.collection_names if n in existing]
            missing = set(self.collection_names) - existing
            if missing:
                logger.info(
                    "[ChromaDB] Using %d/%d collections (%d not found in ChromaDB)",
                    len(self._resolved_names),
                    len(self.collection_names),
                    len(missing),
                )
        except Exception as e:
            logger.warning(f"[ChromaDB] Could not list collections: {e}")
            self._resolved_names = self.collection_names
        return self._resolved_names

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

        coll_names = self._resolve_existing_collections()
        all_results = []
        for coll_name in coll_names:
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

        # v84: Infer source_type from collection name and metadata
        for r in all_results:
            col = r.get("collection", "").lower()
            doc_type = r.get("metadata", {}).get("doc_type", "").lower()

            if doc_type == "textbook" or col in self.TEXTBOOK_COLLECTIONS:
                r["source_type"] = "textbook"
            elif doc_type == "review" or col in self.REVIEW_COLLECTIONS:
                r["source_type"] = "review"
            else:
                r["source_type"] = "research_article"

        # v84: Apply relevance boost for textbooks and reviews
        for r in all_results:
            original_score = r["relevance"]
            if r["source_type"] == "textbook":
                r["relevance"] = min(1.0, original_score + self.TEXTBOOK_BOOST)
                r["boosted"] = True
            elif r["source_type"] == "review":
                r["relevance"] = min(1.0, original_score + self.REVIEW_BOOST)
                r["boosted"] = True
            else:
                r["boosted"] = False

        # Deduplicate by content
        seen = set()
        unique = []
        for r in sorted(all_results, key=lambda x: x["relevance"], reverse=True):
            h = hash(r["document"][:200])
            if h not in seen:
                seen.add(h)
                unique.append(r)

        # v84: Guaranteed minimum slots for textbooks/reviews
        textbook_review_results = [
            r for r in unique if r["source_type"] in ("textbook", "review")
        ]
        top_n = unique[:n_results]
        tr_in_top = sum(
            1 for r in top_n if r["source_type"] in ("textbook", "review")
        )

        if (
            tr_in_top < self.MIN_TEXTBOOK_REVIEW_SLOTS
            and len(textbook_review_results) > tr_in_top
        ):
            needed = min(self.MIN_TEXTBOOK_REVIEW_SLOTS, len(textbook_review_results))
            research_slots = n_results - needed
            final_research = [
                r for r in unique if r["source_type"] == "research_article"
            ][:research_slots]
            final_tr = textbook_review_results[:needed]
            result = final_research + final_tr
            result.sort(key=lambda x: x["relevance"], reverse=True)
            logger.info(
                "[ChromaDB] v84: Guaranteed %d textbook/review slots (was %d in top %d)",
                needed, tr_in_top, n_results,
            )
        else:
            result = unique[:n_results]

        # Log source type distribution
        type_counts: dict = {}
        for r in result:
            st = r.get("source_type", "unknown")
            type_counts[st] = type_counts.get(st, 0) + 1
        type_summary = ", ".join(f"{k}: {v}" for k, v in sorted(type_counts.items()))
        logger.info(
            "[ChromaDB] Search complete: %d total -> %d final [%s]",
            len(all_results), len(result), type_summary,
        )

        # Log top 5 results
        for i, r in enumerate(result[:5], 1):
            source = r.get("metadata", {}).get(
                "source", r.get("metadata", {}).get("title", "Unknown")
            )
            st = r.get("source_type", "?")
            boosted = " BOOSTED" if r.get("boosted") else ""
            logger.info(
                "  Top %d: [%.2f] %s (%s%s, from: %s)",
                i, r["relevance"], source, st, boosted, r.get("collection", "?"),
            )

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

    def search_for_section(self, section_type: str, keywords: List[str], n_results: int = 10) -> List[dict]:
        """Search for literature relevant to a specific report section."""
        query_text = f"{section_type}: {' '.join(keywords[:5])}"
        return self.query_with_reranking(query_text, n_results=n_results)

    def _get_collection(self, name: str):
        if name not in self._collections:
            try:
                self._collections[name] = self.client.get_collection(name)
            except Exception:
                logger.warning(f"Collection '{name}' not found")
                self._collections[name] = None
        return self._collections[name]
