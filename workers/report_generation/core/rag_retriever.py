"""
RAG Retriever — ChromaDB vector search + BM25 reranking for report generation.
Ported from multi_agent_system/agents/hypothesis_validator.py and section_writers.py.

Provides literature evidence retrieval for hypothesis validation and section writing.
"""

import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

from ptm_shared.embedding_registry import collection_embedding_spec, encode_texts

logger = logging.getLogger(__name__)

CHROMADB_URL = os.getenv("CHROMADB_URL", "http://chromadb:8000")
NCBI_EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_MIN_REQUEST_INTERVAL_SECONDS = 0.35
MAX_BIBLIOGRAPHIC_TITLE_LOOKUPS = 12


def _clean_metadata_value(value: object) -> str:
    """Return a normalized scalar metadata value without inventing identity."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _first_metadata_value(metadata: dict, *aliases: str) -> str:
    for alias in aliases:
        value = _clean_metadata_value(metadata.get(alias))
        if value:
            return value
    return ""


def _normalise_title(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _legacy_chunk_bibliographic_hints(result: dict) -> dict:
    """Recover only explicit article identity hints from a legacy collection chunk.

    Some historical collections stored a bundle label in metadata while preserving
    an article heading, PMID or DOI in the chunk text.  This helper never promotes
    arbitrary prose to a paper title and never treats a collection label as one.
    """
    document = str(result.get("document") or "")[:6_000]
    hints: dict[str, str] = {}
    title_match = re.search(
        r"(?mi)^\s*(?:article\s+)?title\s*:\s*(.{20,300})$|^\s*#\s+(.{20,300})$",
        document,
    )
    if title_match:
        hints["title"] = (title_match.group(1) or title_match.group(2) or "").strip()
    pmid_match = re.search(r"\bPMID\s*[:#]?\s*(\d{5,10})\b", document, flags=re.IGNORECASE)
    if pmid_match:
        hints["pmid"] = pmid_match.group(1)
    doi_match = re.search(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", document, flags=re.IGNORECASE)
    if doi_match:
        hints["doi"] = doi_match.group(1).rstrip(".,;)")
    return hints


def traceable_reference_from_rag_result(result: dict) -> dict:
    """Normalize collection-local bibliographic fields into a citable identity.

    A collection name, filename, or free-text source label is never treated as a
    journal.  A result becomes citation eligible only if it contains a title plus
    a persistent identifier, or a minimal author-year publication identity.
    """
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    legacy_hints = _legacy_chunk_bibliographic_hints(result)
    title = _clean_metadata_value(result.get("title")) or _first_metadata_value(
        metadata, "title", "article_title", "paper_title", "source_title"
    )
    collection_label = _first_metadata_value(metadata, "collection", "collection_name", "bundle")
    if legacy_hints.get("title") and (
        not title
        or _normalise_title(title) == _normalise_title(collection_label)
        or _normalise_title(title) in {"allptmarticles", "allarticles", "collection"}
    ):
        title = legacy_hints["title"]
    title = title or legacy_hints.get("title", "")
    authors = _clean_metadata_value(result.get("authors")) or _first_metadata_value(
        metadata, "authors", "author", "author_string", "first_author"
    )
    year = _clean_metadata_value(result.get("year")) or _first_metadata_value(
        metadata, "year", "pub_year", "publication_year", "pub_date", "date"
    )
    year_match = re.search(r"\b(?:19|20)\d{2}\b", year)
    year = year_match.group(0) if year_match else ""
    journal = _first_metadata_value(
        metadata, "journal", "journal_name", "fulljournalname", "venue", "publication"
    )
    pmid = _first_metadata_value(metadata, "pmid", "PMID", "pubmed_id", "pubmed") or legacy_hints.get("pmid", "")
    pmid_match = re.search(r"\b\d{5,10}\b", pmid)
    pmid = pmid_match.group(0) if pmid_match else ""
    doi = _first_metadata_value(metadata, "doi", "DOI", "doi_url") or legacy_hints.get("doi", "")
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE).strip()
    doi_match = re.search(r"10\.\d{4,9}/\S+", doi, flags=re.IGNORECASE)
    doi = doi_match.group(0).rstrip(".,;)])") if doi_match else ""
    persistent_identity = bool(pmid or doi)
    author_year_identity = bool(authors and year and journal)
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "pmid": pmid,
        "doi": doi,
        "citation_eligible": bool(title and (persistent_identity or author_year_identity)),
        "citation_identity_source": "collection_metadata" if title else "missing",
    }


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
        self._cache_lock = threading.Lock()
        self._resolved_names: Optional[List[str]] = None  # Filtered to existing only
        self._bibliography_cache: Dict[str, dict] = {}
        self._bibliography_lock = threading.Lock()
        self._bibliography_lookups = 0
        self._last_bibliography_request = 0.0

    def _eutils_json(self, endpoint: str, params: dict) -> dict:
        """Fetch a small bibliographic response under the public NCBI rate limit."""
        now = time.monotonic()
        last_request = getattr(self, "_last_bibliography_request", 0.0)
        wait_seconds = NCBI_MIN_REQUEST_INTERVAL_SECONDS - (now - last_request)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        response = requests.get(
            f"{NCBI_EUTILS_URL}/{endpoint}",
            params={**params, "tool": "ptm_vector_report"},
            timeout=8,
            headers={"User-Agent": "PTM-Vector/1.0 bibliographic-metadata"},
        )
        self._last_bibliography_request = time.monotonic()
        response.raise_for_status()
        return response.json()

    def _resolve_pubmed_title(self, title: str) -> dict:
        """Resolve an exact PubMed title match; ambiguous matches fail closed."""
        normalized_title = _normalise_title(title)
        if len(normalized_title) < 20:
            return {}
        cache = getattr(self, "_bibliography_cache", None)
        if cache is None:
            self._bibliography_cache = {}
            cache = self._bibliography_cache
        if normalized_title in cache:
            return dict(cache[normalized_title])
        if getattr(self, "_bibliography_lookups", 0) >= MAX_BIBLIOGRAPHIC_TITLE_LOOKUPS:
            cache[normalized_title] = {}
            return {}
        try:
            self._bibliography_lookups = getattr(self, "_bibliography_lookups", 0) + 1
            search = self._eutils_json(
                "esearch.fcgi",
                {"db": "pubmed", "term": f'"{title}"[Title]', "retmax": 3, "retmode": "json"},
            )
            identifiers = list((search.get("esearchresult") or {}).get("idlist") or [])
            if not identifiers:
                cache[normalized_title] = {}
                return {}
            summary = self._eutils_json(
                "esummary.fcgi",
                {"db": "pubmed", "id": ",".join(str(item) for item in identifiers), "retmode": "json"},
            )
            payload = summary.get("result") or {}
            matches = []
            for identifier in identifiers:
                item = payload.get(str(identifier)) or {}
                resolved_title = _clean_metadata_value(item.get("title"))
                if _normalise_title(resolved_title) != normalized_title:
                    continue
                article_ids = item.get("articleids") or []
                doi = ""
                for article_id in article_ids:
                    if str(article_id.get("idtype") or "").lower() == "doi":
                        doi = _clean_metadata_value(article_id.get("value"))
                        break
                matches.append({
                    "title": resolved_title,
                    "authors": _clean_metadata_value(item.get("sortfirstauthor")),
                    "year": _clean_metadata_value(item.get("pubdate")),
                    "journal": _clean_metadata_value(item.get("fulljournalname") or item.get("source")),
                    "pmid": str(identifier),
                    "doi": doi,
                    "citation_eligible": True,
                    "citation_identity_source": "pubmed_exact_title",
                })
            resolved = matches[0] if len(matches) == 1 else {}
        except Exception as exc:
            logger.info("[ChromaDB] PubMed metadata resolution skipped for '%s': %s", title[:80], exc)
            resolved = {}
        cache[normalized_title] = dict(resolved)
        return resolved

    def resolve_traceable_reference(self, result: dict) -> dict:
        """Attach an exact PubMed identity to a selected collection result when needed."""
        normalized = traceable_reference_from_rag_result(result)
        if normalized.get("citation_eligible"):
            return normalized
        title = normalized.get("title") or _clean_metadata_value(result.get("title"))
        resolved = self._resolve_pubmed_title(title) if title else {}
        return resolved or normalized

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
        cache_key = f"{query_text}:{n_results}:{relevance_threshold}"
        with self._cache_lock:
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

                spec = collection_embedding_spec(coll)
                query_embedding = encode_texts([query_text], spec.key)[0]

                results = coll.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )

                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                dists = results.get("distances", [[]])[0]

                for doc, meta, dist in zip(docs, metas, dists):
                    relevance = max(0, 1.0 - dist)
                    if relevance >= relevance_threshold:
                        raw_result = {"metadata": meta or {}, "title": (meta or {}).get("title", "")}
                        bibliography = self.resolve_traceable_reference(raw_result)
                        enriched_meta = {**(meta or {}), **{
                            key: value for key, value in bibliography.items()
                            if key in {"authors", "year", "journal", "pmid", "doi"} and value
                        }}
                        all_results.append({
                            "document": doc[:500],
                            "metadata": enriched_meta,
                            "relevance": round(relevance, 3),
                            "collection": coll_name,
                            "title": bibliography.get("title") or (meta or {}).get("title", ""),
                            "authors": bibliography.get("authors", ""),
                            "year": bibliography.get("year", ""),
                            "journal": bibliography.get("journal", ""),
                            "pmid": bibliography.get("pmid", ""),
                            "doi": bibliography.get("doi", ""),
                            "citation_eligible": bool(bibliography.get("citation_eligible")),
                            "citation_identity_source": bibliography.get("citation_identity_source", "missing"),
                            "source": (meta or {}).get("source", ""),
                        })

            except Exception as e:
                logger.warning(
                    f"ChromaDB query failed for collection '{coll_name}' "
                    f"(embedding contract enforced): {e}"
                )

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

        with self._cache_lock:
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

    def search_for_biological_synthesis(
        self,
        query_plan: List[dict],
        *,
        n_results: int = 10,
    ) -> List[dict]:
        """Retrieve literature for data-derived system, pathway, and candidate anchors.

        ``query_plan`` is deterministic Report input, not a generated hypothesis.
        Results retain the query role/text so the writer can distinguish study
        background from a pathway or candidate-specific literature comparison.
        """
        if not query_plan:
            return []
        per_query = max(1, min(3, int(n_results)))
        unique: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in query_plan:
            if not isinstance(item, dict):
                continue
            query_text = str(item.get("query") or "").strip()
            if not query_text:
                continue
            try:
                retrieved = self.query_with_reranking(query_text, n_results=per_query)
            except Exception as error:
                logger.warning("[ChromaDB] Biological synthesis query failed for '%s': %s", query_text[:80], error)
                continue
            for row in retrieved:
                doc_key = (str(row.get("title") or ""), str(row.get("document") or "")[:160])
                if doc_key in seen:
                    continue
                seen.add(doc_key)
                unique.append({
                    **row,
                    "query_role": str(item.get("role") or "data_anchored"),
                    "query_text": query_text,
                    "query_anchor": str(item.get("anchor") or ""),
                    "selection_bucket": str(item.get("selection_bucket") or ""),
                })
        # Keep the first result for each role/anchor before filling remaining relevance-ranked slots.
        # This prevents high-amplitude canonical anchors from exhausting all candidate-specific
        # literature slots ahead of selected discovery candidates.
        selected: list[dict] = []
        represented: set[tuple[str, str]] = set()
        for row in unique:
            representation_key = (str(row.get("query_role") or "data_anchored"), str(row.get("query_anchor") or ""))
            if representation_key not in represented:
                selected.append(row)
                represented.add(representation_key)
        for row in unique:
            if len(selected) >= n_results:
                break
            if row not in selected:
                selected.append(row)
        selected = selected[:n_results]
        logger.info(
            "[ChromaDB] Biological synthesis retrieval: %d data-anchored queries -> %d references",
            len(query_plan), len(selected),
        )
        return selected

    def search_for_cascade_pathways(
        self,
        temporal_kinase_cascade: dict,
        inferred_receptors: list = None,
        ptm_type: str = "phosphorylation",
        n_results_per_query: int = 3,
        max_queries: int = 5,
    ) -> List[dict]:
        """v9.35: Pathway-specific ChromaDB search using kinase cascade data.
        Extracts top kinase→substrate relationships from temporal_kinase_cascade
        and searches for literature evidence supporting each specific cascade.
        Returns deduplicated results tagged with the cascade they support.
        """
        if not temporal_kinase_cascade:
            return []

        # Build cascade-specific search queries
        cascade_queries = []

        # Source 1: Top kinases from kinase_activity (most timepoints = most important)
        kinase_activity = temporal_kinase_cascade.get("kinase_activity", [])
        for ka in kinase_activity[:max_queries]:
            kinase_name = ka.get("canonical", ka.get("kinase", ""))
            if kinase_name:
                cascade_queries.append({
                    "query": f"{kinase_name} {ptm_type} substrate signaling pathway",
                    "context": f"kinase:{kinase_name}",
                })

        # Source 2: Receptor → Kinase connections (if receptors available)
        if inferred_receptors:
            for rec in inferred_receptors[:3]:
                rec_name = rec.get("name", "")
                # Find kinases connected to this receptor
                connected_kinases = rec.get("connected_kinases", [])
                if connected_kinases:
                    kinase_str = " ".join(str(k) for k in connected_kinases[:3])
                    cascade_queries.append({
                        "query": f"{rec_name} receptor {kinase_str} {ptm_type} signaling",
                        "context": f"receptor:{rec_name}→kinase:{kinase_str}",
                    })
                elif rec_name:
                    cascade_queries.append({
                        "query": f"{rec_name} receptor {ptm_type} downstream signaling",
                        "context": f"receptor:{rec_name}",
                    })

        # Source 3: Cascade flow transitions (new kinases at each timepoint)
        cascade_flow = temporal_kinase_cascade.get("cascade_flow", [])
        for flow in cascade_flow[:3]:
            new_kinases = flow.get("new_kinases", [])
            if new_kinases:
                kinase_str = " ".join(new_kinases[:3])
                from_tp = flow.get("from_timepoint", "")
                to_tp = flow.get("to_timepoint", "")
                cascade_queries.append({
                    "query": f"{kinase_str} {ptm_type} activation signaling cascade",
                    "context": f"cascade_transition:{from_tp}→{to_tp}",
                })

        # Deduplicate and limit queries
        seen_queries = set()
        unique_queries = []
        for cq in cascade_queries:
            q_key = cq["query"].lower().strip()
            if q_key not in seen_queries:
                seen_queries.add(q_key)
                unique_queries.append(cq)
        unique_queries = unique_queries[:max_queries]

        # Execute searches
        all_results = []
        seen_docs = set()
        for cq in unique_queries:
            try:
                results = self.query_with_reranking(
                    cq["query"], n_results=n_results_per_query
                )
                for r in results:
                    doc_key = r.get("document", "")[:100]
                    if doc_key not in seen_docs:
                        seen_docs.add(doc_key)
                        r["cascade_context"] = cq["context"]
                        r["cascade_query"] = cq["query"]
                        all_results.append(r)
            except Exception as e:
                logger.warning(f"[v9.35] Cascade search failed for '{cq['query'][:50]}': {e}")

        logger.info(
            f"[v9.35] Cascade pathway search: {len(unique_queries)} queries → "
            f"{len(all_results)} unique results"
        )
        return all_results

    def _get_collection(self, name: str):
        if name not in self._collections:
            try:
                self._collections[name] = self.client.get_collection(name)
            except Exception:
                logger.warning(f"Collection '{name}' not found")
                self._collections[name] = None
        return self._collections[name]
