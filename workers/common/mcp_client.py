"""
MCP Client — synchronous wrapper for calling MCP Server from Celery workers.

All external bio-database API calls go through the MCP Server, which handles
caching (Redis), rate limiting, and response normalization.
"""

import logging
import os
import threading
from typing import Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MCP_BASE_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")

ProgressCallback = Optional[Callable[[int, int, str], None]]


class MCPClient:
    """Synchronous MCP Client for Celery workers. Thread-safe via per-thread sessions."""

    def __init__(self, base_url: str = None, timeout: float = 120.0):
        self.base_url = (base_url or MCP_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        """Return a per-thread requests.Session (lazy-created)."""
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"Content-Type": "application/json"})
            self._local.session = s
        return s

    def health_check(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Generic tool caller — allows calling any MCP tool by name
    # ------------------------------------------------------------------

    def call_tool(self, tool_name: str, params: dict) -> dict:
        """
        Generic tool caller that routes to the appropriate MCP endpoint.

        Supports both dedicated methods and dynamic endpoint resolution.
        This enables modules like PTMValidator to call tools by name.
        """
        # Route to dedicated methods when available
        _routes = {
            "query_uniprot": lambda p: self.query_uniprot(p.get("query", p.get("protein_id", ""))),
            "query_kegg": lambda p: self.query_kegg(p.get("gene_name", ""), p.get("organism", "mmu")),
            "query_stringdb": lambda p: self.query_stringdb(p.get("gene_name", ""), p.get("species", "10090")),
            "query_interpro": lambda p: self.query_interpro(p.get("protein_id", "")),
            "query_iptmnet": lambda p: self.query_iptmnet(
                p.get("gene", ""), p.get("position", ""), p.get("organism", "Mouse"),
            ),
            "fetch_fulltext": lambda p: self.fetch_fulltext(p.get("pmid", "")),
            "query_hpa": lambda p: self.query_hpa(p.get("gene_name", "")),
            "query_gtex": lambda p: self.query_gtex(p.get("gene_name", "")),
            "query_biogrid": lambda p: self.query_biogrid(
                p.get("gene_name", ""), p.get("organism", 10090),
            ),
            "query_kea3": lambda p: self.query_kea3(
                p.get("gene_list", []), p.get("top_n", 10),
            ),
        }

        handler = _routes.get(tool_name)
        if handler:
            return handler(params)

        # Fallback: try POST to /tools/{tool_name}
        try:
            r = self.session.post(
                f"{self.base_url}/tools/{tool_name}",
                json=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP call_tool({tool_name}) failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # UniProt
    # ------------------------------------------------------------------

    def query_uniprot(self, protein_id: str) -> dict:
        try:
            r = self.session.get(
                f"{self.base_url}/tools/uniprot/{protein_id}",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP UniProt failed for {protein_id}: {e}")
            return {"protein_id": protein_id, "subcellular_location": [],
                    "function_summary": "", "go_terms_bp": [], "go_terms_mf": [], "go_terms_cc": []}

    def query_uniprot_batch(self, protein_ids: List[str]) -> List[dict]:
        # 90s per batch to avoid long hangs; fallback to individual queries on timeout
        batch_timeout = min(self.timeout * 2, 90)
        try:
            r = self.session.post(
                f"{self.base_url}/tools/uniprot/batch",
                json={"protein_ids": protein_ids},
                timeout=batch_timeout,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP UniProt batch failed: {e}")
            return [self.query_uniprot(pid) for pid in protein_ids]

    # ------------------------------------------------------------------
    # KEGG
    # ------------------------------------------------------------------

    def query_kegg(self, gene_name: str, organism: str = "mmu") -> dict:
        try:
            r = self.session.get(
                f"{self.base_url}/tools/kegg/{gene_name}",
                params={"organism": organism},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP KEGG failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "organism": organism, "pathways": []}

    def query_kegg_batch(self, gene_names: List[str], organism: str = "mmu") -> List[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/kegg/batch",
                json={"gene_names": gene_names, "organism": organism},
                timeout=self.timeout * 3,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP KEGG batch failed: {e}")
            return [self.query_kegg(g, organism) for g in gene_names]

    # ------------------------------------------------------------------
    # STRING-DB
    # ------------------------------------------------------------------

    def query_stringdb(self, gene_name: str, species: str = "10090") -> dict:
        try:
            r = self.session.get(
                f"{self.base_url}/tools/stringdb/{gene_name}",
                params={"species": species},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP STRING-DB failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "species": species,
                    "interactions": [], "interaction_count": 0, "avg_score": 0.0}

    def query_stringdb_batch(self, gene_names: List[str], species: str = "10090") -> List[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/stringdb/batch",
                json={"gene_names": gene_names, "species": species},
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP STRING-DB batch failed: {e}")
            return [self.query_stringdb(g, species) for g in gene_names]

    # ------------------------------------------------------------------
    # InterPro
    # ------------------------------------------------------------------

    def query_interpro(self, protein_id: str) -> dict:
        try:
            r = self.session.get(
                f"{self.base_url}/tools/interpro/{protein_id}",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP InterPro failed for {protein_id}: {e}")
            return {"protein_id": protein_id, "domains": []}

    def query_interpro_batch(self, protein_ids: List[str]) -> List[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/interpro/batch",
                json={"protein_ids": protein_ids},
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP InterPro batch failed: {e}")
            return [self.query_interpro(pid) for pid in protein_ids]

    # ------------------------------------------------------------------
    # iPTMnet — PTM novelty assessment
    # ------------------------------------------------------------------

    def query_iptmnet(
        self, gene: str, position: str = "", organism: str = "Mouse",
    ) -> dict:
        """Query iPTMnet for PTM novelty assessment."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/iptmnet/{gene}",
                params={"position": position, "organism": organism},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP iPTMnet failed for {gene} {position}: {e}")
            return {
                "gene": gene, "position": position, "organism": organism,
                "novelty": None, "sites_found": 0, "ptm_sites": [],
                "query_status": "error", "error": str(e),
            }

    def query_iptmnet_human_ortholog(
        self, gene: str, position: str, organism: str = "Rat",
    ) -> dict:
        """Fetch additive human evidence only for an Ensembl-aligned rat residue."""
        try:
            response = self.session.get(
                f"{self.base_url}/tools/iptmnet/ortholog/{gene}",
                params={"position": position, "organism": organism},
                timeout=self.timeout * 2,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"MCP iPTMnet human ortholog failed for {gene} {position}: {e}")
            return {
                "provenance": "source_error", "query_status": "error",
                "rat_gene": gene, "rat_site": position,
                "reason_code": "ortholog_query_unavailable", "error": str(e),
            }

    # ------------------------------------------------------------------
    # PMC Full-Text
    # ------------------------------------------------------------------

    def fetch_fulltext(self, pmid: str) -> dict:
        """Fetch PMC/EuropePMC full-text by PMID."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/pmc/fulltext/{pmid}",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP PMC fulltext failed for {pmid}: {e}")
            return {"pmid": pmid, "fulltext": "", "source": "", "error": str(e)}

    def fetch_fulltext_batch(self, pmids: List[str]) -> List[dict]:
        """Fetch PMC full-text for multiple PMIDs."""
        try:
            r = self.session.post(
                f"{self.base_url}/tools/pmc/fulltext/batch",
                json={"pmids": pmids},
                timeout=self.timeout * 3,
            )
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as e:
            logger.warning(f"MCP PMC fulltext batch failed: {e}")
            return [self.fetch_fulltext(pmid) for pmid in pmids]

    # ------------------------------------------------------------------
    # HPA — Human Protein Atlas
    # ------------------------------------------------------------------

    def query_hpa(self, gene_name: str) -> dict:
        """Query Human Protein Atlas for subcellular localization."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/hpa/{gene_name}",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP HPA failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "subcellular_location": [], "error": str(e)}

    # ------------------------------------------------------------------
    # GTEx — Tissue Expression
    # ------------------------------------------------------------------

    def query_gtex(self, gene_name: str) -> dict:
        """Query GTEx for tissue expression data."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/gtex/{gene_name}",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP GTEx failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "tissues": [], "error": str(e)}

    # ------------------------------------------------------------------
    # BioGRID — Protein-Protein Interactions
    # ------------------------------------------------------------------

    def query_biogrid(self, gene_name: str, organism: int = 10090) -> dict:
        """Query BioGRID for protein-protein interactions."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/biogrid/{gene_name}",
                params={"organism": organism},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP BioGRID failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "interactions": [], "error": str(e)}

    # ------------------------------------------------------------------
    # KEA3 — Kinase Enrichment Analysis
    # ------------------------------------------------------------------

    def query_kea3(self, gene_list: List[str], top_n: int = 10) -> dict:
        """Query KEA3 for kinase enrichment analysis."""
        try:
            r = self.session.post(
                f"{self.base_url}/tools/kea3/enrich",
                json={"gene_list": gene_list, "top_n": top_n},
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP KEA3 failed: {e}")
            return {"gene_list": gene_list, "kinases": [], "error": str(e)}

    # ------------------------------------------------------------------
    # Reactome — Per-gene Pathway Information (Layer 1)
    # ------------------------------------------------------------------

    def query_reactome(self, gene_name: str, organism: str = "Mus musculus") -> dict:
        """Query Reactome pathways for a gene (via human ortholog)."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/reactome/{gene_name}",
                params={"organism": organism},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP Reactome failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "pathways": [], "signaling_pathways": []}

    def query_reactome_batch(self, gene_names: List[str], organism: str = "Mus musculus") -> List[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/reactome/batch",
                json={"gene_names": gene_names, "organism": organism},
                timeout=self.timeout * 3,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP Reactome batch failed: {e}")
            return [self.query_reactome(g, organism) for g in gene_names]

    # ------------------------------------------------------------------
    # Enrichr — Cluster-level Gene-set Enrichment (Layer 2)
    # ------------------------------------------------------------------

    def query_enrichr(self, gene_list: List[str], libraries: List[str] = None,
                      description: str = "", top_n: int = 15) -> dict:
        """Submit gene list to Enrichr for pathway enrichment analysis."""
        try:
            payload = {"gene_list": gene_list, "top_n": top_n, "description": description}
            if libraries:
                payload["libraries"] = libraries
            r = self.session.post(
                f"{self.base_url}/tools/enrichr/enrich",
                json=payload,
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP Enrichr failed: {e}")
            return {"gene_list": gene_list, "results": {}, "error": str(e)}

    def query_string_enrichment(self, gene_list: List[str], species: int = 10090) -> dict:
        """Run STRING functional enrichment on a gene set."""
        try:
            r = self.session.post(
                f"{self.base_url}/tools/enrichr/string",
                json={"gene_list": gene_list, "species": species},
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP STRING enrichment failed: {e}")
            return {"gene_list": gene_list, "kegg_terms": [], "all_terms": []}

    # ------------------------------------------------------------------
    # STRING Indirect Pathway Inference (Layer 3)
    # ------------------------------------------------------------------

    def query_string_indirect(self, gene_name: str, species: int = 10090,
                              top_partners: int = 10) -> dict:
        """Infer signaling pathways via STRING interaction partners."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/string_indirect/{gene_name}",
                params={"species": species, "top_partners": top_partners},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP STRING indirect failed for {gene_name}: {e}")
            return {"gene_name": gene_name, "inferred_pathways": [], "signaling_pathways": []}

    def query_string_indirect_batch(self, gene_names: List[str], species: int = 10090,
                                    top_partners: int = 10) -> List[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/string_indirect/batch",
                json={"gene_names": gene_names, "species": species, "top_partners": top_partners},
                timeout=self.timeout * 3,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP STRING indirect batch failed: {e}")
            return [self.query_string_indirect(g, species, top_partners) for g in gene_names]

    # ------------------------------------------------------------------
    # Parallel helpers with concurrency + progress
    # ------------------------------------------------------------------

    def _run_batches_parallel(
        self,
        items: list,
        batch_fn,
        key_field: str,
        batch_size: int = 20,
        max_workers: int = 4,
        progress_cb: ProgressCallback = None,
        label: str = "",
    ) -> Dict[str, dict]:
        """Generic concurrent batch processor with throttled progress reporting."""
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(items)
        batches = [items[i: i + batch_size] for i in range(0, total, batch_size)]
        results = {}
        completed_count = 0
        last_report_time = 0.0

        if progress_cb:
            progress_cb(0, total, f"{label}: 0/{total}")
            last_report_time = time.monotonic()

        def process_batch(batch):
            return batch_fn(batch)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_batch, b): i for i, b in enumerate(batches)}
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    for r in batch_results:
                        results[r.get(key_field, "")] = r
                except Exception as e:
                    logger.warning(f"{label} batch failed: {e}")

                completed_count += 1
                done_items = min(completed_count * batch_size, total)
                now = time.monotonic()
                is_last = completed_count == len(batches)
                if progress_cb and (is_last or now - last_report_time >= 2.0):
                    progress_cb(done_items, total, f"{label}: {done_items}/{total}")
                    last_report_time = now

        return results

    def fetch_uniprot_parallel(
        self, protein_ids: List[str], batch_size: int = 20,
        max_workers: int = 4, progress_cb: ProgressCallback = None,
    ) -> Dict[str, dict]:
        return self._run_batches_parallel(
            protein_ids, self.query_uniprot_batch, "protein_id",
            batch_size=batch_size, max_workers=max_workers,
            progress_cb=progress_cb, label="UniProt",
        )

    def fetch_interpro_parallel(
        self, protein_ids: List[str], batch_size: int = 20,
        max_workers: int = 4, progress_cb: ProgressCallback = None,
    ) -> Dict[str, dict]:
        return self._run_batches_parallel(
            protein_ids, self.query_interpro_batch, "protein_id",
            batch_size=batch_size, max_workers=max_workers,
            progress_cb=progress_cb, label="InterPro",
        )

    def fetch_kegg_parallel(
        self, gene_names: List[str], organism: str = "mmu", batch_size: int = 10,
        max_workers: int = 4, progress_cb: ProgressCallback = None,
    ) -> Dict[str, dict]:
        def batch_fn(batch):
            return self.query_kegg_batch(batch, organism)
        return self._run_batches_parallel(
            gene_names, batch_fn, "gene_name",
            batch_size=batch_size, max_workers=max_workers,
            progress_cb=progress_cb, label="KEGG",
        )

    def fetch_stringdb_parallel(
        self, gene_names: List[str], species: str = "10090", batch_size: int = 20,
        max_workers: int = 4, progress_cb: ProgressCallback = None,
    ) -> Dict[str, dict]:
        def batch_fn(batch):
            return self.query_stringdb_batch(batch, species)
        return self._run_batches_parallel(
            gene_names, batch_fn, "gene_name",
            batch_size=batch_size, max_workers=max_workers,
            progress_cb=progress_cb, label="STRING-DB",
        )

    def fetch_reactome_parallel(
        self, gene_names: List[str], organism: str = "Mus musculus", batch_size: int = 10,
        max_workers: int = 3, progress_cb: ProgressCallback = None,
    ) -> Dict[str, dict]:
        def batch_fn(batch):
            return self.query_reactome_batch(batch, organism)
        return self._run_batches_parallel(
            gene_names, batch_fn, "gene_name",
            batch_size=batch_size, max_workers=max_workers,
            progress_cb=progress_cb, label="Reactome",
        )

    # ------------------------------------------------------------------
    # PubMed
    # ------------------------------------------------------------------

    def search_pubmed(
        self, gene: str, position: str, ptm_type: str = "Phosphorylation",
        context_keywords: list | None = None, max_results: int = 15,
    ) -> dict:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/pubmed/search",
                json={
                    "gene": gene, "position": position, "ptm_type": ptm_type,
                    "context_keywords": context_keywords or [], "max_results": max_results,
                },
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP PubMed search failed for {gene}/{position}: {e}")
            return {"gene": gene, "position": position, "articles": [], "total_found": 0}

    def search_pubmed_batch(self, queries: list) -> list:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/pubmed/search/batch",
                json={"queries": queries},
                timeout=self.timeout * 5,
            )
            r.raise_for_status()
            return r.json()["results"]
        except Exception as e:
            logger.warning(f"MCP PubMed batch search failed: {e}")
            return [self.search_pubmed(**q) for q in queries]

    def fetch_articles(self, pmids: list) -> list:
        try:
            r = self.session.post(
                f"{self.base_url}/tools/pubmed/fetch",
                json={"pmids": pmids},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("articles", [])
        except Exception as e:
            logger.warning(f"MCP PubMed fetch failed: {e}")
            return []

    def get_gene_aliases(self, gene: str) -> list:
        try:
            r = self.session.get(
                f"{self.base_url}/tools/pubmed/aliases/{gene}",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("aliases", [])
        except Exception as e:
            logger.warning(f"MCP gene aliases failed for {gene}: {e}")
            return []

    # ------------------------------------------------------------------
    # TF Activity Inference (v11.8: DoRothEA + TRRUST)
    # ------------------------------------------------------------------
    def query_tf_targets(self, tf_name: str, species: str = "mouse",
                         min_confidence: str = "medium") -> dict:
        """Get all known target genes for a transcription factor."""
        try:
            r = self.session.get(
                f"{self.base_url}/tools/tf_targets/{tf_name}",
                params={"species": species, "min_confidence": min_confidence},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP TF targets failed for {tf_name}: {e}")
            return {"tf": tf_name, "targets": [], "total_targets": 0}

    def infer_tf_activity(self, gene_list: List[str], species: str = "mouse",
                          min_confidence: str = "medium",
                          min_targets_overlap: int = 3,
                          top_n: int = 20) -> dict:
        """Infer active TFs from a list of changed genes."""
        try:
            r = self.session.post(
                f"{self.base_url}/tools/tf_targets/infer",
                json={
                    "gene_list": gene_list,
                    "species": species,
                    "min_confidence": min_confidence,
                    "min_targets_overlap": min_targets_overlap,
                    "top_n": top_n,
                },
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP TF inference failed: {e}")
            return {"gene_list_size": len(gene_list), "inferred_tfs": []}

    def infer_tf_activity_batch(self, gene_sets: dict, species: str = "mouse",
                                min_confidence: str = "medium",
                                min_targets_overlap: int = 3,
                                top_n: int = 10) -> dict:
        """Infer TF activity for multiple gene sets (per-timepoint)."""
        try:
            r = self.session.post(
                f"{self.base_url}/tools/tf_targets/infer_batch",
                json={
                    "gene_sets": gene_sets,
                    "species": species,
                    "min_confidence": min_confidence,
                    "min_targets_overlap": min_targets_overlap,
                    "top_n": top_n,
                },
                timeout=self.timeout * 3,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"MCP TF inference batch failed: {e}")
            return {"n_sets": len(gene_sets), "results": {}}

    def close(self):
        s = getattr(self._local, "session", None)
        if s is not None:
            s.close()
            self._local.session = None
