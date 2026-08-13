"""
RAG Enrichment Pipeline — enriches PTM data with PubMed literature and biological context.
Ported from ptm-rag-backend/src/ragEnrichmentV2.ts.

Changes from original:
  - All API calls → MCP Client
  - LLM calls (abstractAnalyzer, llmKinasePredictor, llmFunctionalImpact) RESTORED
  - Pattern-based regulation extraction retained
  - Cross-site PTM search and validation integrated
  - Full-text analysis via PMC integrated
  - HPA, GTEx, BioGRID, Isoform data collection RESTORED
  - 8-category cell-signaling classification system RESTORED
  - LOCAL-FIRST data loading: HPA/GTEx from local files with API fallback
  - TypeScript → Python

v9.29.0 — Parallel Enrichment:
  - Level 1: PTM-internal parallelization (ThreadPoolExecutor for independent MCP calls)
  - Level 2: Gene-level result caching + PTM-level concurrent processing
  - 3-phase dependency-aware execution within each PTM
  - Thread-safe progress tracking
"""

import logging
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from common.phase_b_cache import get_cached, get_cached_best_match, set_cached


from common.llm_client import LLMClient
from common.mcp_client import MCPClient
from common.local_data_loader import HPALocalLoader, GTExLocalLoader
from common.temporal_utils import condition_sort_key
from .regulation_extractor import RegulationExtractor
from .abstract_analyzer import AbstractAnalyzer
from .llm_kinase_predictor import LLMKinasePredictor
from .llm_functional_impact import LLMFunctionalImpact
from .fulltext_analyzer import FullTextAnalyzer
from dataclasses import asdict as _asdict
from .ptm_validation import PTMValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 8-Category Cell-Signaling Classification Thresholds
# ---------------------------------------------------------------------------
PTM_HIGH = 2.0       # Strong PTM change threshold (|Log2FC| > 2.0 = 4x fold change)
PTM_LOW = 0.5        # Minimal PTM change threshold (|Log2FC| <= 0.5 = <1.4x fold change)
PROTEIN_CHANGE = 0.5  # Protein change threshold (|Log2FC| > 0.5 = >1.4x fold change)

# ---------------------------------------------------------------------------
# Parallelization Config
# ---------------------------------------------------------------------------
import os as _os
# Level 1: Max concurrent MCP calls within a single PTM enrichment
MCP_WORKERS = int(_os.getenv("RAG_MCP_WORKERS", "6"))
# Level 2: Max concurrent PTM enrichments.
# Default 2: each PTM runs abstract+kinase+functional in parallel inside Phase B,
# so 4 workers → up to 12 simultaneous Ollama requests which causes queue buildup.
# Set RAG_PTM_WORKERS env var in docker-compose to tune for your hardware.
PTM_WORKERS = int(_os.getenv("RAG_PTM_WORKERS", "2"))
# Abstract batch mode: analyze all articles in a single LLM call instead of one-by-one.
# Reduces PTM-level LLM calls from N to 1 for abstract analysis.
# Falls back to per-article mode automatically if batch parsing fails.
def _env_bool(name: str, default: bool = True) -> bool:
    return _os.getenv(name, "true" if default else "false").lower() not in ("false", "0", "no")
def _get_rag_settings() -> dict:
    """Read RAG tuning settings from DB (with env var + hardcoded fallback).

    Called at task start so Settings page changes take effect without restart.
    Uses common.system_settings which caches DB values for 60s.
    """
    try:
        from common.system_settings import get_int, get_bool, get_setting
        return {
            "max_articles":          get_int("RAG_MAX_ARTICLES", 3),
            "enable_llm":            get_bool("RAG_ENABLE_LLM",            default=True),
            "enable_kinase":         get_bool("RAG_ENABLE_KINASE",          default=True),
            "enable_functional":     get_bool("RAG_ENABLE_FUNCTIONAL",      default=True),
            "abstract_batch_mode":   get_bool("RAG_ABSTRACT_BATCH_MODE",    default=True),
            "abstract_max_tokens":   get_int("RAG_ABSTRACT_MAX_TOKENS",    4096),
            "kinase_max_tokens":     get_int("RAG_KINASE_MAX_TOKENS",      2000),
            "functional_max_tokens": get_int("RAG_FUNCTIONAL_MAX_TOKENS",  3000),
            "phase_a_timeout":       get_int("RAG_PHASE_A_TIMEOUT",        60),
            "phase_b_timeout":       get_int("RAG_PHASE_B_TIMEOUT",        120),
        }
    except Exception:
        return {
            "max_articles":          int(_os.getenv("RAG_MAX_ARTICLES", "3")),
            "enable_llm":            _env_bool("RAG_ENABLE_LLM",         True),
            "enable_kinase":         _env_bool("RAG_ENABLE_KINASE",       True),
            "enable_functional":     _env_bool("RAG_ENABLE_FUNCTIONAL",   True),
            "abstract_batch_mode":   _env_bool("RAG_ABSTRACT_BATCH_MODE", True),
            "abstract_max_tokens":   int(_os.getenv("RAG_ABSTRACT_MAX_TOKENS",    "4096")),
            "kinase_max_tokens":     int(_os.getenv("RAG_KINASE_MAX_TOKENS",      "2000")),
            "functional_max_tokens": int(_os.getenv("RAG_FUNCTIONAL_MAX_TOKENS",  "3000")),
            "phase_a_timeout":       int(_os.getenv("RAG_PHASE_A_TIMEOUT",        "60")),
            "phase_b_timeout":       int(_os.getenv("RAG_PHASE_B_TIMEOUT",        "120")),
        }


ABSTRACT_BATCH_MODE = _env_bool("RAG_ABSTRACT_BATCH_MODE", default=True)
# Rate limiting: small delay between batches to avoid overwhelming MCP servers
BATCH_DELAY_SEC = 0.1


def _format_phase_b_exc(e: BaseException, max_len: int = 220) -> str:
    """Phase B pool uses future.result(timeout=120); TimeoutError often has empty str(e)."""
    msg = (str(e) or "").strip()
    if msg:
        return msg[:max_len]
    name = type(e).__name__
    if "Timeout" in name:
        return (
            f"{name}: 120s per sub-task — Ollama slow or prompt too large "
            f"(lighter model, or increase timeout in enrichment_pipeline)"
        )[:max_len]
    return name[:max_len]


class _GeneCache:
    """Thread-safe cache for gene-level MCP results.

    Many PTMs share the same gene (e.g. MAPK1 S189, MAPK1 T185).
    Gene-level queries (KEGG, STRING-DB, UniProt, HPA, GTEx, BioGRID, Reactome)
    return identical results regardless of the specific PTM site.
    This cache stores those results so they are fetched only once per gene.
    """

    def __init__(self):
        self._store: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            return self._store.get(key)

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            self._store[key] = value

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._store


class RAGEnrichmentPipeline:
    """Enriches PTM vector data with literature search and pattern-based analysis."""
    def __init__(
        self,
        mcp_client: MCPClient,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        analysis_log: Optional[Callable[[str], None]] = None,
        enable_llm_analysis: bool = True,
        enable_fulltext: bool = True,
        enable_ptm_validation: bool = True,
        rag_enrichment_llm_model: Optional[str] = None,
        rag_enrichment_llm_provider: Optional[str] = None,
        rag_llm_model: Optional[str] = None,
        rag_llm_provider: Optional[str] = None,
        llm_provider: str = "ollama",
        llm_model: Optional[str] = None,
        species: str = "mouse",
    ):
        self.mcp = mcp_client
        self.reg_extractor = RegulationExtractor()
        self._progress_cb = progress_callback or (lambda p, m: None)
        self._analysis_log = analysis_log
        self._phase_b_genes_seen: set = set()
        self._abstract_warned_genes: set = set()
        self._sets_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        # Read RAG tuning settings from DB at pipeline init (Settings page changes apply immediately)
        _rag_cfg = _get_rag_settings()
        self.max_articles: int        = _rag_cfg["max_articles"]
        self.enable_kinase: bool      = _rag_cfg["enable_kinase"]
        self.enable_functional: bool  = _rag_cfg["enable_functional"]
        self.abstract_batch_mode: bool   = _rag_cfg["abstract_batch_mode"]
        self.abstract_max_tokens: int    = _rag_cfg["abstract_max_tokens"]
        self.kinase_max_tokens: int      = _rag_cfg["kinase_max_tokens"]
        self.functional_max_tokens: int  = _rag_cfg["functional_max_tokens"]
        self.phase_a_timeout: int        = _rag_cfg["phase_a_timeout"]
        self.phase_b_timeout: int        = _rag_cfg["phase_b_timeout"]
        # LLM-based analysis modules (restored from original)
        self.enable_llm = enable_llm_analysis and _rag_cfg["enable_llm"]
        self.enable_fulltext = enable_fulltext
        self.enable_ptm_validation = enable_ptm_validation
        if enable_llm_analysis:
            # Model priority: explicit param → env RAG_ENRICHMENT_LLM_MODEL → fallback to report model
            _env_rag_model = os.getenv("RAG_ENRICHMENT_LLM_MODEL", "").strip() or None
            effective_model = (
                rag_enrichment_llm_model or _env_rag_model or rag_llm_model or llm_model
            )
            # v12.0: Minimum model size enforcement for RAG Enrichment
            # Models smaller than 14B produce unreliable JSON and high hallucination rates
            _MIN_RAG_MODEL_SIZE_B = int(os.getenv("RAG_MIN_MODEL_SIZE_B", "14"))
            _FALLBACK_RAG_MODEL = os.getenv("RAG_ENRICHMENT_LLM_MODEL", "qwen2.5:14b").strip()
            if effective_model:
                _detected_size = self._get_model_size_b(effective_model)
                if 0 < _detected_size < _MIN_RAG_MODEL_SIZE_B:
                    logger.warning(
                        f"[v12.0] RAG Enrichment model '{effective_model}' is {_detected_size}B, "
                        f"below minimum ({_MIN_RAG_MODEL_SIZE_B}B). Replacing with '{_FALLBACK_RAG_MODEL}' "
                        f"to ensure analysis quality."
                    )
                    effective_model = _FALLBACK_RAG_MODEL
            if rag_enrichment_llm_model:
                eff_provider = (
                    rag_enrichment_llm_provider
                    or rag_llm_provider
                    or llm_provider
                )
            elif rag_llm_model:
                eff_provider = rag_llm_provider or llm_provider
            else:
                eff_provider = llm_provider
            eff_provider = eff_provider or "ollama"
            llm = (
                LLMClient(provider=eff_provider, model=effective_model)
                if effective_model
                else LLMClient(provider=eff_provider)
            )
            if not llm.is_available():
                logger.warning("No LLM provider available — disabling LLM analysis")
                self.enable_llm = False
            else:
                logger.info(f"LLM initialized: provider={llm.provider}, model={llm.model}")
                self.abstract_analyzer = AbstractAnalyzer(llm_client=llm)
                self.kinase_predictor = LLMKinasePredictor(llm_client=llm)
                self.functional_impact = LLMFunctionalImpact(llm_client=llm)
        if enable_fulltext:
            self.fulltext_analyzer = FullTextAnalyzer()
        if enable_ptm_validation:
            self.ptm_validator = PTMValidator(mcp_client=mcp_client, species=species)
        # Log local data availability
        if HPALocalLoader.is_available():
            logger.info("HPA local data available — will use local-first strategy")
        else:
            logger.info("HPA local data not available — will use MCP API only")
        if GTExLocalLoader.is_available():
            logger.info("GTEx local data available — will use local-first strategy")
        else:
            logger.info("GTEx local data not available — will use MCP API only")

        # Level 2: Gene-level result cache
        self._gene_cache = _GeneCache()

    # ------------------------------------------------------------------
    # Model size detection
    # ------------------------------------------------------------------

    @staticmethod
    def _get_model_size_b(model_name: str) -> int:
        """Extract model size in billions from model name string.

        Examples:
            'gemma3:4b' -> 4
            'qwen2.5:14b' -> 14
            'qwen3.5:27b' -> 27
            'gemma3:27b-it-qat' -> 27
            'llama3.1:8b' -> 8
            'phi3:3.8b' -> 3
            'gpt-4.1-mini' -> 0 (cloud model, no size restriction)
            'gemini-2.5-flash' -> 0 (cloud model, no size restriction)
        Returns:
            Size in billions, or 0 if not detectable (cloud models are unrestricted).
        """
        if not model_name:
            return 0
        # Cloud providers are unrestricted (return 0 to skip size check)
        cloud_prefixes = ("gpt-", "gemini-", "claude-", "o1-", "o3-", "o4-")
        if any(model_name.lower().startswith(p) for p in cloud_prefixes):
            return 0
        lower = model_name.lower()
        # Priority: parse size tag after colon (Ollama format: 'name:sizeb')
        if ":" in lower:
            tag = lower.split(":", 1)[1]
            match = re.match(r"(\d+(?:\.\d+)?)b", tag)
            if match:
                return int(float(match.group(1)))
        # Fallback: find NNb pattern preceded by delimiter
        match = re.search(r"(?:^|[:\-_])(\d+(?:\.\d+)?)b", lower)
        if match:
            return int(float(match.group(1)))
        return 0

    # ------------------------------------------------------------------
    # Thread-safe progress reporting
    # ------------------------------------------------------------------

    def _alog(self, msg: str, metadata: dict | None = None, *, persist: bool = False) -> None:
        if not self._analysis_log:
            return
        try:
            self._analysis_log(msg, metadata, persist=persist)
        except Exception:
            pass

    def _phase_event(self, gene: str, position: str, phase: str, status: str, detail: str = "") -> None:
        """Emit a structured PTM-phase progress event consumed by the frontend phase-status modal."""
        self._alog(
            f"[phase:{phase}] {gene} {position} → {status}",
            metadata={
                "type": "ptm_phase",
                "gene": gene,
                "position": position,
                "phase": phase,
                "status": status,  # running | done | skip | error
                "detail": detail,
            },
            persist=True,
        )

    def _progress(self, pct: float, msg: str) -> None:
        with self._progress_lock:
            self._progress_cb(pct, msg)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def enrich_ptm_data(
        self,
        ptm_data: List[dict],
        experimental_context: Optional[dict] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> List[dict]:
        """
        Enrich a list of PTM entries with PubMed literature and biological context.

        Args:
            ptm_data: List of PTM dicts with keys:
                gene, position, ptm_type, protein_log2fc, ptm_relative_log2fc, etc.
            experimental_context: Optional context dict with keys:
                tissue, treatment, organism, keywords, etc.

        Returns:
            Enriched PTM list with added rag_enrichment field.
        """
        total = len(ptm_data)
        logger.info(f"RAG enrichment: processing {total} PTM entries (parallel mode: MCP_WORKERS={MCP_WORKERS}, PTM_WORKERS={PTM_WORKERS})")

        # MCP health check
        try:
            mcp_healthy = self.mcp.health_check()
            if mcp_healthy:
                logger.info(f"MCP server is healthy at {self.mcp.base_url}")
            else:
                logger.error(f"MCP server is NOT reachable at {self.mcp.base_url} — enrichment will have limited data")
        except Exception as e:
            logger.error(f"MCP health check exception: {e}")

        # Local data availability check with details
        from common.local_data_loader import DATA_ROOT, LOCAL_DATA_DIR, CONFIG_DIR, PatternLoader
        logger.info(f"DATA_ROOT = {DATA_ROOT}")
        logger.info(f"LOCAL_DATA_DIR = {LOCAL_DATA_DIR} (exists={LOCAL_DATA_DIR.exists() if LOCAL_DATA_DIR else 'N/A'})")
        logger.info(f"CONFIG_DIR = {CONFIG_DIR} (exists={CONFIG_DIR.exists() if CONFIG_DIR else 'N/A'})")
        logger.info(f"HPA local data available: {HPALocalLoader.is_available()}")
        logger.info(f"GTEx local data available: {GTExLocalLoader.is_available()}")
        logger.info(f"Pattern config available: {PatternLoader.is_available()}")

        # Log first PTM keys for debugging field name issues
        if ptm_data:
            sample = ptm_data[0]
            logger.info(f"Sample PTM keys: {list(sample.keys())[:20]}")
            logger.info(
                f"Sample PTM values: gene={sample.get('gene') or sample.get('Gene.Name', '?')}, "
                f"PTM_Relative_Log2FC={sample.get('PTM_Relative_Log2FC', 'MISSING')}, "
                f"Protein_Log2FC={sample.get('Protein_Log2FC', 'MISSING')}"
            )

        context_keywords = self._extract_context_keywords(experimental_context)
        logger.info(f"Context keywords: {context_keywords}")

        # ── Gene deduplication analysis ──
        gene_counts: Dict[str, int] = {}
        for ptm in ptm_data:
            g = ptm.get("gene") or ptm.get("Gene.Name", "?")
            gene_counts[g] = gene_counts.get(g, 0) + 1
        unique_genes = len(gene_counts)
        multi_site_genes = sum(1 for c in gene_counts.values() if c > 1)
        logger.info(
            f"Gene dedup analysis: {total} PTMs → {unique_genes} unique genes "
            f"({multi_site_genes} genes with multiple sites, "
            f"cache will save ~{total - unique_genes} redundant gene-level queries)"
        )
        self._alog(
            f"RAG: {total} PTM rows, {unique_genes} unique genes — "
            f"Phase A(MCP) + Phase B(LLM: abstract/kinase/functional/…) per row in parallel; "
            f"first Phase B per gene is logged below."
        )

        # ── Level 2: Parallel PTM enrichment ──
        enriched = [None] * total  # Pre-allocate to maintain order
        stats = {"success": 0, "failed": 0, "total_articles": 0, "total_pathways": 0}
        stats_lock = threading.Lock()
        completed_count = [0]  # mutable counter for thread-safe increment

        t_start = time.time()

        def _enrich_worker(idx: int, ptm: dict) -> None:
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")

            # Skip this PTM if the order was cancelled while we were waiting in the queue.
            if cancel_event and cancel_event.is_set():
                logger.info(f"[cancel] Skipping {gene} {pos} — order cancelled")
                ptm_log2fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
                protein_log2fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
                ptm["rag_enrichment"] = self._empty_enrichment(ptm_log2fc, protein_log2fc)
                enriched[idx] = ptm
                with stats_lock:
                    stats["failed"] += 1
                    completed_count[0] += 1
                return

            try:
                result = self._enrich_single_ptm_parallel(ptm, context_keywords, experimental_context, cancel_event=cancel_event)
                enriched[idx] = result

                enr = result.get("rag_enrichment", {})
                with stats_lock:
                    stats["success"] += 1
                    stats["total_articles"] += enr.get("search_summary", {}).get("total_articles", 0)
                    stats["total_pathways"] += len(enr.get("pathways", []))
                    completed_count[0] += 1
                    done = completed_count[0]

                # Progress callback with 3-Layer pathway detail
                kc = len(enr.get("pathways", []))
                rc = enr.get("reactome", {})
                rc_sig = rc.get("signaling_count", 0) if rc else 0
                rc_tot = rc.get("total_count", 0) if rc else 0
                si = enr.get("string_indirect", {})
                si_c = len(si.get("signaling_pathways", [])) if si else 0
                pw_total = kc + rc_tot + si_c
                pw_parts = []
                if kc > 0:
                    pw_parts.append(f"KEGG:{kc}")
                if rc_tot > 0:
                    pw_parts.append(f"Reactome:{rc_tot}({rc_sig}sig)")
                if si_c > 0:
                    pw_parts.append(f"STR-Indir:{si_c}")
                pw_summary = ", ".join(pw_parts) if pw_parts else "no pathways"
                art_count = enr.get("search_summary", {}).get("total_articles", 0)
                cached = " [gene-cached]" if self._gene_cache.has(f"{gene}__kegg") else ""
                self._progress(
                    done / total,
                    f"{gene} {pos}: {art_count} articles, {pw_total} pathways ({done}/{total})"
                )
            except Exception as e:
                logger.error(f"Enrichment FAILED for {gene}/{pos}: {e}", exc_info=True)
                ptm_log2fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
                protein_log2fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
                ptm["rag_enrichment"] = self._empty_enrichment(ptm_log2fc, protein_log2fc)
                enriched[idx] = ptm
                with stats_lock:
                    stats["failed"] += 1
                    completed_count[0] += 1

        # Execute with ThreadPoolExecutor (Level 2)
        self._progress(0.0, f"Starting parallel enrichment: {total} PTMs, {unique_genes} unique genes")

        # Emit pending events for ALL PTMs upfront so the frontend table shows the full list immediately
        self._alog(
            f"[ptm_list] total={total}",
            metadata={"type": "ptm_list", "total": total},
            persist=True,
        )
        for ptm in ptm_data:
            _g = ptm.get("gene") or ptm.get("Gene.Name", "?")
            _p = ptm.get("position") or ptm.get("PTM_Position", "?")
            self._alog(
                f"[phase:queued] {_g} {_p}",
                metadata={"type": "ptm_phase", "gene": _g, "position": _p,
                          "phase": "A", "status": "pending", "detail": ""},
                persist=True,
            )

        with ThreadPoolExecutor(max_workers=PTM_WORKERS, thread_name_prefix="ptm_enrich") as executor:
            futures = {}
            for i, ptm in enumerate(ptm_data):
                gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
                pos = ptm.get("position") or ptm.get("PTM_Position", "?")
                future = executor.submit(_enrich_worker, i, ptm)
                futures[future] = (i, gene, pos)

            self._progress(0.0, f"All {total} PTMs queued — processing (0/{total})")
            self._alog(
                f"All {total} jobs submitted (max {PTM_WORKERS} concurrent). "
                f"Waiting for completions..."
            )

            # Wait for all futures to complete
            for future in as_completed(futures):
                idx, gene, pos = futures[future]
                try:
                    future.result()  # Re-raise any unhandled exceptions
                except Exception as e:
                    logger.error(f"Unhandled exception in PTM worker {gene}/{pos}: {e}", exc_info=True)

        t_elapsed = time.time() - t_start
        logger.info(f"Parallel enrichment completed in {t_elapsed:.1f}s ({t_elapsed/total:.1f}s per PTM avg)")

        # Filter out any None entries (shouldn't happen, but safety)
        enriched = [e for e in enriched if e is not None]

        # ── 3-Layer Pathway Enrichment Summary Table ──
        layer_stats = {"kegg": 0, "kegg_genes": 0, "reactome": 0, "reactome_genes": 0,
                       "reactome_signaling": 0, "string_indirect": 0, "string_indirect_genes": 0}
        for item in enriched:
            enr = item.get("rag_enrichment", {})
            kp = len(enr.get("pathways", []))
            if kp > 0:
                layer_stats["kegg"] += kp
                layer_stats["kegg_genes"] += 1
            rc = enr.get("reactome", {})
            if rc:
                rt = rc.get("total_count", 0)
                rs = rc.get("signaling_count", 0)
                if rt > 0:
                    layer_stats["reactome"] += rt
                    layer_stats["reactome_signaling"] += rs
                    layer_stats["reactome_genes"] += 1
            si = enr.get("string_indirect", {})
            if si:
                sp = len(si.get("signaling_pathways", []))
                if sp > 0:
                    layer_stats["string_indirect"] += sp
                    layer_stats["string_indirect_genes"] += 1

        logger.info("")
        logger.info("═" * 70)
        logger.info("  3-LAYER PATHWAY ENRICHMENT SUMMARY")
        logger.info("═" * 70)
        logger.info(
            f"  Layer 1 - KEGG:             {layer_stats['kegg']:>4} pathways "
            f"from {layer_stats['kegg_genes']:>3}/{len(enriched)} genes"
        )
        logger.info(
            f"  Layer 1 - Reactome:         {layer_stats['reactome']:>4} pathways "
            f"({layer_stats['reactome_signaling']} signaling) "
            f"from {layer_stats['reactome_genes']:>3}/{len(enriched)} genes"
        )
        logger.info(
            f"  Layer 3 - STRING Indirect:   {layer_stats['string_indirect']:>4} inferred pathways "
            f"from {layer_stats['string_indirect_genes']:>3}/{len(enriched)} genes"
        )
        logger.info(
            f"  Combined coverage: "
            f"{layer_stats['kegg_genes'] + layer_stats['reactome_genes'] + layer_stats['string_indirect_genes']} "
            f"gene-pathway mappings (some genes counted in multiple layers)"
        )
        logger.info("─" * 70)

        # Per-gene pathway coverage detail
        logger.info("  Per-Gene Pathway Coverage:")
        logger.info(f"  {'Gene':<15} {'KEGG':>6} {'Reactome':>10} {'React-Sig':>10} {'STR-Indir':>10} {'Total':>7}")
        logger.info(f"  {'-'*15} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*7}")
        for item in enriched:
            enr = item.get("rag_enrichment", {})
            g = item.get("gene") or item.get("Gene.Name", "?")
            kc = len(enr.get("pathways", []))
            rc_data = enr.get("reactome", {})
            rc_total = rc_data.get("total_count", 0) if rc_data else 0
            rc_sig = rc_data.get("signaling_count", 0) if rc_data else 0
            si_data = enr.get("string_indirect", {})
            si_count = len(si_data.get("signaling_pathways", [])) if si_data else 0
            total_pw = kc + rc_total + si_count
            marker = " ⚠" if total_pw == 0 else ""
            logger.info(f"  {g:<15} {kc:>6} {rc_total:>10} {rc_sig:>10} {si_count:>10} {total_pw:>7}{marker}")
        logger.info("═" * 70)
        logger.info("")

        # Gene cache stats
        logger.info(f"Gene cache entries: {len(self._gene_cache._store)} (saved redundant MCP calls for multi-site genes)")

        logger.info(
            f"Enrichment complete: {stats['success']} OK, {stats['failed']} failed, "
            f"total articles={stats['total_articles']}, total pathways={stats['total_pathways']}, "
            f"elapsed={t_elapsed:.1f}s"
        )
        # --- Final 3-Layer summary via progress callback (visible in web UI) ---
        self._progress(0.98,
            f"3-Layer Summary: KEGG={layer_stats['kegg']}pw/{layer_stats['kegg_genes']}genes, "
            f"Reactome={layer_stats['reactome']}pw({layer_stats['reactome_signaling']}sig)/{layer_stats['reactome_genes']}genes, "
            f"STRING-Indirect={layer_stats['string_indirect']}pw/{layer_stats['string_indirect_genes']}genes"
        )
        self._progress(1.0,
            f"Enrichment complete: {len(enriched)} PTMs, {stats['total_articles']} articles, "
            f"{stats['total_pathways']} KEGG pathways ({t_elapsed:.0f}s, {t_elapsed/max(total,1):.1f}s/PTM)"
        )
        return enriched

    # ------------------------------------------------------------------
    # Level 1 + Level 2: Parallel single-PTM enrichment
    # ------------------------------------------------------------------

    def _enrich_single_ptm_parallel(
        self, ptm: dict, context_keywords: List[str], context: Optional[dict],
        cancel_event: Optional[threading.Event] = None,
    ) -> dict:
        """Enrich a single PTM with parallelized MCP calls and gene-level caching.

        Execution is split into 3 dependency-aware phases:

        Phase A (parallel, no dependencies):
            PubMed, KEGG, STRING-DB, UniProt, HPA, GTEx, BioGRID, Reactome
            → Gene-level results (KEGG, STRING, UniProt, HPA, GTEx, BioGRID, Reactome)
              are cached so multi-site genes only query once.

        Phase B (parallel, depends on PubMed articles from Phase A):
            Regulation extraction, Abstract analysis, Kinase prediction, Fulltext analysis, PTM validation
            → Also depends on KEGG for functional_impact (pathway names)

        Phase C (conditional, depends on KEGG from Phase A):
            STRING indirect (only when KEGG pathways < 3)
        """
        gene = ptm.get("gene") or ptm.get("Gene.Name", "Unknown")
        position = ptm.get("position") or ptm.get("PTM_Position", "Unknown")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        species = (context or {}).get("organism") or (context or {}).get("species", "")
        # A single order may intentionally use a mixed FASTA, for example a
        # human receptor transgene in rat cells. FASTA-native provenance takes
        # priority for this PTM's external annotations but never changes the
        # order-level discovery species.
        _fasta_taxon = str(ptm.get("FASTA_Taxonomy_ID") or "").split(";")[0].strip()
        _fasta_organism = str(ptm.get("FASTA_Organism") or "").split(";")[0].strip()
        if _fasta_taxon == "9606":
            species = "human"
        elif _fasta_taxon == "10116":
            species = "rat"
        elif _fasta_taxon == "10090":
            species = "mouse"
        elif _fasta_organism and _fasta_organism.lower() != "unknown":
            species = _fasta_organism
        # Derive KEGG organism code and NCBI tax_id from species string
        _sp_lower = species.lower() if species else ""
        _kegg_org = (
            "rno" if "rat" in _sp_lower or "rattus" in _sp_lower
            else "hsa" if "human" in _sp_lower or "homo" in _sp_lower
            else "mmu"  # default mouse
        )
        _tax_id = (
            10116 if "rat" in _sp_lower or "rattus" in _sp_lower
            else 9606 if "human" in _sp_lower or "homo" in _sp_lower
            else 10090
        )
        _is_human = ("human" in _sp_lower or "homo" in _sp_lower)
        protein_id = ptm.get("protein_id") or ptm.get("Protein.Group", "")

        # ══════════════════════════════════════════════════════════════
        # PHASE A: Independent MCP calls (parallel)
        # ══════════════════════════════════════════════════════════════
        phase_a_results = {}

        def _pubmed():
            try:
                result = self.mcp.search_pubmed(
                    gene=gene, position=position, ptm_type=ptm_type,
                    context_keywords=context_keywords, max_results=self.max_articles,
                )
                articles = result.get("articles", [])
                logger.info(f"PubMed search for {gene} {position}: {len(articles)} articles found")
                return {"search_result": result, "articles": articles}
            except Exception as e:
                logger.warning(f"PubMed search failed for {gene} {position}: {e}")
                return {"search_result": {}, "articles": []}

        def _kegg():
            cache_key = f"{gene}__kegg__{_kegg_org}"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] KEGG for {gene}")
                return cached
            try:
                kegg_info = self.mcp.query_kegg(gene, organism=_kegg_org)
                kegg_pathways = kegg_info.get("pathways", [])
                kegg_pw_names = [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in kegg_pathways[:5]]
                logger.info(f"[Layer1-KEGG] {gene}: {len(kegg_pathways)} pathways → {kegg_pw_names}")
                result = {"kegg_info": kegg_info, "kegg_pathways": kegg_pathways}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"KEGG query failed for {gene}: {e}")
                result = {"kegg_info": {}, "kegg_pathways": []}
                self._gene_cache.set(cache_key, result)
                return result

        def _stringdb():
            cache_key = f"{gene}__stringdb__{species}"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] STRING-DB for {gene}")
                return cached
            try:
                string_info = self.mcp.query_stringdb(gene, species=species)
                interactions = string_info.get("interactions", [])
                top_partners = [i.get("partner", "?") for i in interactions[:5]]
                logger.info(f"[STRING-DB] {gene}: {len(interactions)} interactions → {top_partners}")
                result = {"string_info": string_info, "interactions": interactions}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"STRING-DB query failed for {gene}: {e}")
                result = {"string_info": {}, "interactions": []}
                self._gene_cache.set(cache_key, result)
                return result

        def _uniprot():
            if not protein_id:
                return {"uniprot_info": {}}
            cache_key = f"{protein_id}__uniprot"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] UniProt for {protein_id}")
                return cached
            try:
                uniprot_info = self.mcp.query_uniprot(protein_id)
                logger.info(f"[UniProt] {gene} ({protein_id}): {'found' if uniprot_info else 'empty'}")
                result = {"uniprot_info": uniprot_info}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"UniProt query failed for {protein_id}: {e}")
                result = {"uniprot_info": {}}
                self._gene_cache.set(cache_key, result)
                return result

        def _hpa():
            # HPA (Human Protein Atlas) is human-only; skip for non-human species
            if not _is_human:
                logger.debug(f"[SKIP] HPA for {gene}: non-human species ({species})")
                return {"hpa_data": {}}
            cache_key = f"{gene}__hpa"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] HPA for {gene}")
                return cached
            try:
                hpa_data = self._query_hpa_local_first(gene)
                result = {"hpa_data": hpa_data}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"HPA query failed for {gene}: {e}")
                result = {"hpa_data": {}}
                self._gene_cache.set(cache_key, result)
                return result

        def _gtex():
            # GTEx is human-only; skip for non-human species
            if not _is_human:
                logger.debug(f"[SKIP] GTEx for {gene}: non-human species ({species})")
                return {"gtex_data": {}}
            cache_key = f"{gene}__gtex"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] GTEx for {gene}")
                return cached
            try:
                gtex_data = self._query_gtex_local_first(gene)
                result = {"gtex_data": gtex_data}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"GTEx query failed for {gene}: {e}")
                result = {"gtex_data": {}}
                self._gene_cache.set(cache_key, result)
                return result

        def _biogrid():
            cache_key = f"{gene}__biogrid__{_tax_id}"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] BioGRID for {gene}")
                return cached
            try:
                biogrid_data = self.mcp.query_biogrid(gene, organism=_tax_id)
                result = {"biogrid_data": biogrid_data}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"BioGRID query failed for {gene}: {e}")
                result = {"biogrid_data": {}}
                self._gene_cache.set(cache_key, result)
                return result

        def _reactome():
            cache_key = f"{gene}__reactome"
            cached = self._gene_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[CACHE HIT] Reactome for {gene}")
                return cached
            try:
                reactome_data = self.mcp.query_reactome(gene)
                reactome_count = reactome_data.get("total_count", 0)
                signaling_count = reactome_data.get("signaling_count", 0)
                reactome_pw_names = [p.get("name", "?") for p in reactome_data.get("signaling_pathways", [])[:5]]
                logger.info(f"[Layer1-Reactome] {gene}: {reactome_count} total, {signaling_count} signaling → {reactome_pw_names}")
                result = {"reactome_data": reactome_data}
                self._gene_cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning(f"Reactome query failed for {gene}: {e}")
                result = {"reactome_data": {}}
                self._gene_cache.set(cache_key, result)
                return result

        # Execute Phase A in parallel
        phase_a_tasks = {
            "pubmed": _pubmed,
            "kegg": _kegg,
            "stringdb": _stringdb,
            "uniprot": _uniprot,
            "hpa": _hpa,
            "gtex": _gtex,
            "biogrid": _biogrid,
            "reactome": _reactome,
        }

        self._phase_event(gene, position, "A", "running", "PubMed/KEGG/STRING/UniProt/HPA/GTEx/BioGRID/Reactome")
        _phase_a_errors = []
        with ThreadPoolExecutor(max_workers=MCP_WORKERS, thread_name_prefix=f"mcp_{gene[:8]}") as pool:
            futures_a = {name: pool.submit(fn) for name, fn in phase_a_tasks.items()}
            for name, future in futures_a.items():
                try:
                    phase_a_results[name] = future.result(timeout=self.phase_a_timeout)
                except Exception as e:
                    logger.error(f"Phase A task '{name}' failed for {gene}: {e}")
                    phase_a_results[name] = {}
                    _phase_a_errors.append(name)
        self._phase_event(
            gene, position, "A",
            "error" if _phase_a_errors else "done",
            f"failed: {','.join(_phase_a_errors)}" if _phase_a_errors else "",
        )

        # Unpack Phase A results
        pubmed_r = phase_a_results.get("pubmed", {})
        search_result = pubmed_r.get("search_result", {})
        articles = pubmed_r.get("articles", [])

        kegg_r = phase_a_results.get("kegg", {})
        kegg_info = kegg_r.get("kegg_info", {})
        kegg_pathways = kegg_r.get("kegg_pathways", [])

        stringdb_r = phase_a_results.get("stringdb", {})
        string_info = stringdb_r.get("string_info", {})
        interactions = stringdb_r.get("interactions", [])

        uniprot_r = phase_a_results.get("uniprot", {})
        uniprot_info = uniprot_r.get("uniprot_info", {})

        hpa_r = phase_a_results.get("hpa", {})
        hpa_data = hpa_r.get("hpa_data", {})

        gtex_r = phase_a_results.get("gtex", {})
        gtex_data = gtex_r.get("gtex_data", {})

        biogrid_r = phase_a_results.get("biogrid", {})
        biogrid_data = biogrid_r.get("biogrid_data", {})

        reactome_r = phase_a_results.get("reactome", {})
        reactome_data = reactome_r.get("reactome_data", {})

        # ══════════════════════════════════════════════════════════════
        # PHASE B: PubMed-dependent tasks (parallel)
        # ══════════════════════════════════════════════════════════════
        regulation = {"upstream_regulators": [], "downstream_targets": [], "kinase_substrate": [], "regulation_evidence": [], "diseases": []}
        abstract_analysis = {}
        kinase_prediction = {}
        functional_impact = {}
        fulltext_results = {}
        validation_result = {}

        phase_b_tasks = {}

        # Regulation extraction (depends on articles)
        def _regulation():
            try:
                return self.reg_extractor.extract_from_articles(articles, gene, position)
            except Exception as e:
                logger.warning(f"Regulation extraction failed for {gene}: {e}")
                return {"upstream_regulators": [], "downstream_targets": [], "kinase_substrate": [], "regulation_evidence": [], "diseases": []}
        phase_b_tasks["regulation"] = _regulation

        # LLM-based abstract analysis
        if self.enable_llm and articles:
            def _abstract():
                try:
                    def _on_article(done: int, total: int):
                        self._alog(
                            f"[phase:B:art] {gene} {position} {done}/{total}",
                            metadata={"type": "ptm_phase", "gene": gene, "position": position,
                                      "phase": "B", "status": "running",
                                      "detail": f"{done}/{total} articles"},
                        )
                    raw = self.abstract_analyzer.analyze(
                        articles=articles, gene=gene, position=position, ptm_type=ptm_type,
                        on_article_done=_on_article,
                        batch_mode=self.abstract_batch_mode,
                        batch_max_tokens=self.abstract_max_tokens,
                    )
                    out = _asdict(raw) if hasattr(raw, '__dataclass_fields__') else (raw if isinstance(raw, dict) else {})
                    with self._sets_lock:
                        already_warned = gene in self._abstract_warned_genes
                    if self._analysis_log and not already_warned and articles:
                        score = out.get("relevance_score", 0) if isinstance(out, dict) else 0
                        kf = out.get("key_findings") if isinstance(out, dict) else None
                        n_kf = len(kf) if isinstance(kf, list) else 0
                        if score == 0 and n_kf == 0:
                            with self._sets_lock:
                                self._abstract_warned_genes.add(gene)
                            self._alog(
                                f"[LLM·abstract] {gene}: no scored findings "
                                f"(JSON parse fail, Ollama timeout, or short abstracts — see worker logs)"
                            )
                    return out
                except Exception as e:
                    logger.warning(f"Abstract analysis failed for {gene}: {e}")
                    with self._sets_lock:
                        already_warned = gene in self._abstract_warned_genes
                    if self._analysis_log and not already_warned:
                        with self._sets_lock:
                            self._abstract_warned_genes.add(gene)
                        self._alog(f"[LLM·abstract] {gene}: exception — {str(e)[:160]}")
                    return {}
            phase_b_tasks["abstract"] = _abstract

        # LLM-based kinase prediction
        if self.enable_llm and self.enable_kinase:
            def _kinase():
                try:
                    return self.kinase_predictor.predict(
                        gene=gene,
                        position=position,
                        ptm_type=ptm_type,
                        experimental_context=context,
                        pubmed_articles=articles,
                        max_tokens=self.kinase_max_tokens,
                    )
                except Exception as e:
                    logger.warning(f"Kinase prediction failed for {gene}: {e}")
                    return {}
            phase_b_tasks["kinase"] = _kinase

        # LLM-based functional impact (depends on KEGG pathways from Phase A)
        if self.enable_llm and self.enable_functional:
            def _functional():
                try:
                    pathway_names = [p.get("name", p) if isinstance(p, dict) else p for p in kegg_pathways]
                    ptm_l = float(ptm.get("PTM_Relative_Log2FC") or ptm.get("ptm_relative_log2fc") or 0)
                    prot_l = float(ptm.get("Protein_Log2FC") or ptm.get("protein_log2fc") or 0)
                    return self.functional_impact.analyze(
                        gene=gene,
                        position=position,
                        ptm_type=ptm_type,
                        ptm_log2fc=ptm_l,
                        protein_log2fc=prot_l,
                        pubmed_articles=articles,
                        kegg_pathways=pathway_names,
                        experimental_context=context,
                        max_tokens=self.functional_max_tokens,
                    )
                except Exception as e:
                    logger.warning(f"Functional impact analysis failed for {gene}: {e}")
                    return {}
            phase_b_tasks["functional"] = _functional

        # Full-text analysis via PMC
        if self.enable_fulltext:
            def _fulltext():
                try:
                    return self._run_fulltext_analysis(
                        gene=gene, position=position, ptm_type=ptm_type,
                        articles=articles,
                    )
                except Exception as e:
                    logger.warning(f"Full-text analysis failed for {gene}: {e}")
                    return {}
            phase_b_tasks["fulltext"] = _fulltext

        # PTM validation / novelty check
        if self.enable_ptm_validation:
            def _validation():
                try:
                    raw_result = self.ptm_validator.validate(
                        gene=gene, position=position, ptm_type=ptm_type,
                        experimental_context=context,
                    )
                    return _asdict(raw_result) if hasattr(raw_result, '__dataclass_fields__') else raw_result
                except Exception as e:
                    logger.warning(f"PTM validation failed for {gene}: {e}")
                    return {}
            phase_b_tasks["validation"] = _validation

        # Execute Phase B in parallel (LLM calls are I/O-bound, safe to parallelize)
        # Early-exit if the order was cancelled while Phase A was running.
        if cancel_event and cancel_event.is_set():
            logger.info(f"[cancel] {gene} {position} — skipping Phase B/C/D (order cancelled)")
            self._phase_event(gene, position, "B", "skip", "cancelled")
            self._phase_event(gene, position, "C", "skip", "cancelled")
            self._phase_event(gene, position, "D", "skip", "cancelled")
            ptm_log2fc_raw = ptm.get("PTM_Relative_Log2FC", ptm.get("ptm_relative_log2fc", 0))
            protein_log2fc_raw = ptm.get("Protein_Log2FC", ptm.get("protein_log2fc", 0))
            ptm["rag_enrichment"] = self._empty_enrichment(ptm_log2fc_raw or 0, protein_log2fc_raw or 0)
            return ptm

        # ① 영구 캐시 확인: 정확한 PMID 조합 → 없으면 subset 폴백 (논문 수 변경 시 재활용)
        self._phase_event(gene, position, "B", "running", f"{len(articles)} articles")
        phase_b_results = {}
        pmids = [a.get("pmid", "") for a in articles]
        tasks_to_run: dict = {}
        cache_hit_count = 0
        for name, fn in phase_b_tasks.items():
            cached = get_cached(gene, position, ptm_type, name, pmids)
            if cached is None:
                # 정확한 매치 없음 → subset 매칭 시도 (논문 수가 바뀐 경우 재활용)
                cached = get_cached_best_match(gene, position, ptm_type, name, pmids)
            if cached is not None and isinstance(cached, dict):
                phase_b_results[name] = cached
                cache_hit_count += 1
                logger.debug(f"Phase B '{name}' for {gene} served from persistent cache")
            else:
                if cached is not None:
                    logger.warning(f"Phase B cache for {gene}/{name} has non-dict type ({type(cached).__name__}), discarding")
                tasks_to_run[name] = fn

        _phase_b_errors: list = []
        if tasks_to_run:
            with self._sets_lock:
                first_seen = gene not in self._phase_b_genes_seen
                self._phase_b_genes_seen.add(gene)
            if first_seen:
                keys = ",".join(sorted(tasks_to_run.keys()))
                self._alog(
                    f"[LLM·Phase B] {gene}: articles={len(articles)}, parallel=[{keys}]"
                )
            # ② 병렬 실행
            def _to_dict(obj):
                """Ensure Phase B results are plain dicts before caching/storing."""
                if hasattr(obj, '__dataclass_fields__'):
                    return _asdict(obj)
                return obj

            failed_tasks: dict = {}
            with ThreadPoolExecutor(max_workers=min(len(tasks_to_run), MCP_WORKERS), thread_name_prefix=f"llm_{gene[:8]}") as pool:
                futures_b = {name: pool.submit(fn) for name, fn in tasks_to_run.items()}
                for name, future in futures_b.items():
                    try:
                        result = _to_dict(future.result(timeout=self.phase_b_timeout))
                        phase_b_results[name] = result
                        set_cached(gene, position, ptm_type, name, pmids, result)
                    except Exception as e:
                        logger.error(f"Phase B task '{name}' failed for {gene}: {e}")
                        failed_tasks[name] = tasks_to_run[name]

            # ③ 실패한 태스크 직렬 재시도 (LLM 부하 감소 후 재시도)
            if failed_tasks:
                retry_names = ", ".join(sorted(failed_tasks.keys()))
                self._alog(
                    f"[LLM·Phase B] {gene} {position} — retrying [{retry_names}] (serial, timeout={self.phase_b_timeout})"
                )
            for name, fn in failed_tasks.items():
                try:
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"retry_{gene[:8]}") as retry_pool:
                        result = _to_dict(retry_pool.submit(fn).result(timeout=self.phase_b_timeout))
                    phase_b_results[name] = result
                    set_cached(gene, position, ptm_type, name, pmids, result)
                    self._alog(f"[LLM·Phase B] {gene} {position} — {name}: retry OK")
                except Exception as e:
                    logger.error(f"Phase B task '{name}' retry failed for {gene}: {e}")
                    self._alog(
                        f"[LLM·Phase B] ⚠ {gene} {position} — {name}: {_format_phase_b_exc(e)}"
                    )
                    phase_b_results[name] = {}
                    _phase_b_errors.append(name)

        _b_detail = (
            f"timeout: {','.join(_phase_b_errors)}" if _phase_b_errors else ""
        )
        if not _phase_b_errors:
            n_art = len(articles)
            all_cached = cache_hit_count > 0 and not tasks_to_run
            cache_suffix = f", {n_art} cached" if all_cached else ""
            _b_detail = f"{n_art}/{n_art} articles{cache_suffix}"

        self._phase_event(
            gene, position, "B",
            "error" if _phase_b_errors else "done",
            _b_detail,
        )

        regulation = phase_b_results.get("regulation", regulation)
        abstract_analysis = phase_b_results.get("abstract", {})
        kinase_prediction = phase_b_results.get("kinase", {})
        functional_impact = phase_b_results.get("functional", {})
        fulltext_results = phase_b_results.get("fulltext", {})
        validation_result = phase_b_results.get("validation", {})

        # ══════════════════════════════════════════════════════════════
        # PHASE C: Conditional STRING indirect (depends on KEGG count)
        # ══════════════════════════════════════════════════════════════
        string_indirect_data = {}
        if len(kegg_pathways) < 3:
            self._phase_event(gene, position, "C", "running", "STRING indirect (KEGG < 3)")
            cache_key = f"{gene}__string_indirect"
            cached = self._gene_cache.get(cache_key)
            _phase_c_err = False
            if cached is not None:
                string_indirect_data = cached.get("string_indirect_data", {})
                logger.debug(f"[CACHE HIT] STRING indirect for {gene}")
            else:
                try:
                    string_indirect_data = self.mcp.query_string_indirect(gene)
                    inferred_pws = string_indirect_data.get("signaling_pathways", [])
                    inferred_names = [p.get("pathway_name", p) if isinstance(p, dict) else str(p) for p in inferred_pws[:5]]
                    logger.info(
                        f"[Layer3-STRING-Indirect] {gene}: {len(inferred_pws)} inferred pathways "
                        f"(from {string_indirect_data.get('partners_used', '?')} partners) → {inferred_names}"
                    )
                except Exception as e:
                    logger.warning(f"STRING indirect query failed for {gene}: {e}")
                    _phase_c_err = True
                self._gene_cache.set(cache_key, {"string_indirect_data": string_indirect_data})
            self._phase_event(gene, position, "C", "error" if _phase_c_err else "done")
        else:
            self._phase_event(gene, position, "C", "skip", f"KEGG={len(kegg_pathways)} ≥ 3")

        # ══════════════════════════════════════════════════════════════
        # PHASE D: Assembly (same as original)
        # ══════════════════════════════════════════════════════════════
        self._phase_event(gene, position, "D", "running", "assembling result")

        # 14. Merge regulation (KEGG + PubMed patterns)
        upstream = regulation.get("upstream_regulators", [])
        downstream = regulation.get("downstream_targets", [])

        # 15. Classify PTM significance (8-category cell-signaling system)
        ptm_log2fc_raw = ptm.get("PTM_Relative_Log2FC", ptm.get("ptm_relative_log2fc"))
        protein_log2fc_raw = ptm.get("Protein_Log2FC", ptm.get("protein_log2fc"))
        ptm_log2fc = ptm_log2fc_raw if ptm_log2fc_raw is not None else 0
        protein_log2fc = protein_log2fc_raw if protein_log2fc_raw is not None else 0
        classification = self._classify_ptm_8cat(ptm_log2fc, protein_log2fc)
        logger.debug(
            f"Classification for {gene} {position}: ptm_fc={ptm_log2fc}, prot_fc={protein_log2fc} "
            f"→ {classification.get('level')} ({classification.get('significance')})"
        )

        # 16. Extract trajectory data (time-course)
        trajectory = self._extract_trajectory(ptm)

        # 17. Extract isoform information from UniProt
        isoform_info = self._extract_isoform_info(uniprot_info)

        # 18. Build enrichment result
        interaction_partners = [
            {"partner": i.get("partner", ""), "score": i.get("score", 0), "evidence": i.get("evidence", [])}
            for i in interactions  # No limit — store all available interactions
        ]

        enrichment = {
            "search_summary": {
                "total_articles": search_result.get("total_found", 0),
                "tiers_used": search_result.get("search_tiers_used", {}),
            },
            "articles": articles,  # Full article data for report generation
            "recent_findings": [
                {
                    "pmid": a.get("pmid", ""),
                    "title": a.get("title", ""),
                    "journal": a.get("journal", ""),
                    "pub_date": a.get("pub_date", ""),
                    "relevance_score": a.get("relevance_score", 0),
                    "abstract_excerpt": (a.get("abstract") or "")[:300],
                    "abstract": a.get("abstract", ""),
                    "authors": a.get("authors", []),
                    "doi": a.get("doi", ""),
                }
                for a in articles[:10]
            ],
            "regulation": {
                "upstream_regulators": upstream,
                "downstream_targets": downstream,
                "kinase_substrate": regulation.get("kinase_substrate", []),
                "e3_substrate": regulation.get("e3_substrate", []),       # v9.14: E3 ligase-substrate pairs
                "dub_substrate": regulation.get("dub_substrate", []),     # v9.14: DUB-substrate pairs
                "chain_types": regulation.get("chain_types", []),         # v9.14: Detected ubiquitin chain types
                "evidence_count": len(regulation.get("regulation_evidence", [])),
                "regulation_evidence": regulation.get("regulation_evidence", []),
            },
            "pathways": kegg_pathways,
            "string_db": {
                "interactions": interaction_partners,
            },
            "string_interactions": interaction_partners,  # v101: dict format (same as string_db.interactions), no limit
            "diseases": regulation.get("diseases", []),
            "localization": uniprot_info.get("subcellular_location", []),
            "function_summary": uniprot_info.get("function_summary", ""),
            "aliases": uniprot_info.get("gene_synonyms", []),
            "keywords": uniprot_info.get("keywords", []),           # v9.17: UniProt keywords for protein class
            "protein_families": uniprot_info.get("protein_families", []),  # v9.17: family annotations
            "go_terms": {
                "biological_process": uniprot_info.get("go_terms_bp", []),
                "molecular_function": uniprot_info.get("go_terms_mf", []),
                "cellular_component": uniprot_info.get("go_terms_cc", []),
            },
            "classification": classification,
            # Expression data
            "hpa": hpa_data,
            "gtex": gtex_data,
            "biogrid": biogrid_data,
            # v8.10: 3-Layer Pathway Enrichment
            "reactome": reactome_data,
            "string_indirect": string_indirect_data,
            "isoform_info": isoform_info,
            # Trajectory (time-course)
            "trajectory": trajectory,
            # --- RESTORED LLM analysis results ---
            "abstract_analysis": abstract_analysis,
            "kinase_prediction": _asdict(kinase_prediction) if hasattr(kinase_prediction, '__dataclass_fields__') else kinase_prediction,
            "functional_impact": _asdict(functional_impact) if hasattr(functional_impact, '__dataclass_fields__') else functional_impact,
            "fulltext_analysis": fulltext_results,
            "ptm_validation": validation_result,
        }

        ptm["rag_enrichment"] = enrichment
        self._phase_event(gene, position, "D", "done")

        # Log enrichment summary for debugging
        hpa_ok = bool(hpa_data and (hpa_data.get("tissue_expression") or hpa_data.get("locations")))
        gtex_ok = bool(gtex_data and gtex_data.get("expressions"))
        logger.info(
            f"Enrichment for {gene} {position}: "
            f"articles={len(articles)}, "
            f"pathways={len(kegg_pathways)}, "
            f"interactions={len(interactions)}, "
            f"hpa={'yes' if hpa_ok else 'no'} (source={hpa_data.get('source', 'none') if hpa_data else 'none'}), "
            f"gtex={'yes' if gtex_ok else 'no'} (source={gtex_data.get('source', 'none') if gtex_data else 'none'}), "
            f"biogrid={len(biogrid_data.get('interactions', [])) if biogrid_data else 0}, "
            f"reactome={reactome_data.get('total_count', 0) if reactome_data else 0} "
            f"(signaling={reactome_data.get('signaling_count', 0) if reactome_data else 0}), "
            f"string_indirect={len(string_indirect_data.get('signaling_pathways', [])) if string_indirect_data else 0}, "
            f"llm_abstract={'yes' if abstract_analysis else 'no'}, "
            f"classification={classification.get('level', '?')} ({classification.get('significance', '?')})"
        )
        return ptm

    # ------------------------------------------------------------------
    # LEGACY: Sequential single-PTM enrichment (kept for fallback)
    # ------------------------------------------------------------------

    def _enrich_single_ptm(
        self, ptm: dict, context_keywords: List[str], context: Optional[dict]
    ) -> dict:
        """Original sequential enrichment — kept as fallback.
        Use _enrich_single_ptm_parallel for production."""
        return self._enrich_single_ptm_parallel(ptm, context_keywords, context)

    # ------------------------------------------------------------------
    # LOCAL-FIRST Data Access: HPA
    # ------------------------------------------------------------------

    def _query_hpa_local_first(self, gene: str) -> dict:
        """
        Query HPA data using local-first strategy:
        1. Try local TSV files (rna_tissue_hpa.tsv, subcellular_locations.tsv)
        2. Fall back to MCP API if local data unavailable
        """
        # Try local first
        if HPALocalLoader.is_available():
            local_result = HPALocalLoader.query(gene)
            if local_result:
                has_locations = bool(local_result.get("locations"))
                has_tissue = bool(local_result.get("tissue_expression"))
                logger.info(f"HPA local for {gene}: locations={has_locations}, tissue={has_tissue}")
                if has_locations or has_tissue:
                    local_result["source"] = "local_hpa"
                    return local_result
            else:
                logger.debug(f"HPA local: no data for {gene}")
        else:
            logger.debug(f"HPA local data not available, falling back to MCP")

        # Fallback to MCP API
        try:
            hpa_data = self.mcp.query_hpa(gene)
            if hpa_data:
                hpa_data["source"] = "mcp_api"
                logger.debug(f"HPA MCP for {gene}: {list(hpa_data.keys())[:5]}")
            return hpa_data
        except Exception as e:
            logger.warning(f"HPA query failed for {gene}: {e}")
            return {"gene": gene, "locations": [], "error": str(e)}

    # ------------------------------------------------------------------
    # LOCAL-FIRST Data Access: GTEx
    # ------------------------------------------------------------------

    def _query_gtex_local_first(self, gene: str) -> dict:
        """
        Query GTEx data using local-first strategy:
        1. Try local GCT file (3.5GB expression matrix)
        2. Fall back to MCP API if local data unavailable
        """
        # Try local first
        if GTExLocalLoader.is_available():
            local_result = GTExLocalLoader.query_expression(gene)
            if local_result and local_result.get("expressions"):
                logger.info(f"GTEx local for {gene}: {len(local_result['expressions'])} tissues")
                return local_result
            else:
                logger.debug(f"GTEx local: no expression data for {gene}")
        else:
            logger.debug(f"GTEx local data not available, falling back to MCP")

        # Fallback to MCP API
        try:
            gtex_data = self.mcp.query_gtex(gene)
            if gtex_data:
                gtex_data["source"] = "mcp_api"
                logger.debug(f"GTEx MCP for {gene}: {list(gtex_data.keys())[:5]}")
            return gtex_data
        except Exception as e:
            logger.warning(f"GTEx query failed for {gene}: {e}")
            return {"gene": gene, "expressions": [], "error": str(e)}

    # ------------------------------------------------------------------
    # Full-Text Analysis (corrected interface)
    # ------------------------------------------------------------------

    def _run_fulltext_analysis(
        self, gene: str, position: str, ptm_type: str, articles: List[dict],
    ) -> dict:
        """
        Run full-text analysis on articles for a PTM site.
        Fetches full-text from PMC when available, then applies pattern matching.
        """
        all_results = []

        for article in articles[:5]:  # Limit to top 5 articles
            pmid = article.get("pmid", "")
            abstract = article.get("abstract", "")
            pmc_id = article.get("pmc_id") or article.get("pmcid", "")

            # Try to get full-text from PMC via MCP
            fulltext = None
            if pmc_id and hasattr(self.mcp, "fetch_pmc_fulltext"):
                try:
                    pmc_result = self.mcp.fetch_pmc_fulltext(pmc_id)
                    fulltext = pmc_result.get("text") or pmc_result.get("fulltext")
                except Exception as e:
                    logger.debug(f"PMC full-text fetch failed for {pmc_id}: {e}")

            if abstract or fulltext:
                try:
                    analysis = self.fulltext_analyzer.analyze(
                        pmid=pmid,
                        gene=gene,
                        position=position,
                        abstract=abstract,
                        fulltext=fulltext,
                    )
                    all_results.append({
                        "pmid": pmid,
                        "has_fulltext": bool(fulltext),
                        "total_matches": analysis.total_matches,
                        "high_confidence_matches": analysis.high_confidence_matches,
                        "key_findings": analysis.key_findings,
                        "mechanisms": analysis.mechanisms,
                        "antibody_info": [
                            {
                                "target": ab.target,
                                "company": ab.company,
                                "catalog": ab.catalog,
                                "western_blot_validated": ab.western_blot_validated,
                                "confidence": ab.confidence,
                            }
                            for ab in analysis.antibody_info
                        ],
                        "quantitative_data": analysis.quantitative_data,
                        "pattern_summary": {
                            cat: len(matches)
                            for cat, matches in analysis.pattern_matches.items()
                            if matches
                        },
                    })
                except Exception as e:
                    logger.warning(f"Full-text analysis failed for PMID {pmid}: {e}")

        # Aggregate results
        total_matches = sum(r.get("total_matches", 0) for r in all_results)
        all_findings = []
        all_antibodies = []
        for r in all_results:
            all_findings.extend(r.get("key_findings", []))
            all_antibodies.extend(r.get("antibody_info", []))

        return {
            "articles_analyzed": len(all_results),
            "total_pattern_matches": total_matches,
            "key_findings": all_findings[:15],
            "antibody_info": all_antibodies,
            "per_article": all_results,
        }

    @staticmethod
    def _empty_enrichment(ptm_log2fc=0, protein_log2fc=0) -> dict:
        """Return empty enrichment with proper classification based on Log2FC values."""
        logger.debug(f"_empty_enrichment called with ptm_log2fc={ptm_log2fc!r}, protein_log2fc={protein_log2fc!r}")
        classification = RAGEnrichmentPipeline._classify_ptm_8cat(ptm_log2fc, protein_log2fc)
        return {
            "search_summary": {"total_articles": 0},
            "articles": [],
            "recent_findings": [],
            "regulation": {
                "upstream_regulators": [], "downstream_targets": [],
                "kinase_substrate": [], "evidence_count": 0,
                "regulation_evidence": [],
            },
            "pathways": [],
            "string_db": {"interactions": []},
            "string_interactions": [],
            "diseases": [],
            "localization": [],
            "function_summary": "",
            "aliases": [],
            "go_terms": {"biological_process": [], "molecular_function": [], "cellular_component": []},
            "classification": classification,
            "hpa": {},
            "gtex": {},
            "biogrid": {},
            "isoform_info": [],
            "trajectory": {"timepoints": [], "trend": "unknown"},
            "abstract_analysis": {},
            "kinase_prediction": {},
            "functional_impact": {},
            "fulltext_analysis": {},
            "ptm_validation": {},
        }

    # ------------------------------------------------------------------
    # 8-Category Cell-Signaling Classification (v7.7.4)
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_ptm_8cat(ptm_log2fc, protein_log2fc) -> dict:
        """Classify PTM based on Log2FC values using 8-category cell-signaling system."""
        try:
            ptm_fc = float(ptm_log2fc) if ptm_log2fc is not None else 0.0
            prot_fc = float(protein_log2fc) if protein_log2fc is not None else 0.0
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Classification float conversion failed: ptm_log2fc={ptm_log2fc!r} "
                f"(type={type(ptm_log2fc).__name__}), protein_log2fc={protein_log2fc!r} "
                f"(type={type(protein_log2fc).__name__}), error={e}"
            )
            return {
                "level": "Baseline / low-change state",
                "short_label": "Baseline",
                "significance": "Low",
                "protein_context": None,
            }

        # Handle NaN values
        if math.isnan(ptm_fc):
            logger.warning(f"Classification: ptm_log2fc is NaN (original={ptm_log2fc!r})")
            ptm_fc = 0.0
        if math.isnan(prot_fc):
            logger.warning(f"Classification: protein_log2fc is NaN (original={protein_log2fc!r})")
            prot_fc = 0.0

        # Determine protein context
        if prot_fc > PROTEIN_CHANGE:
            protein_context = "Up-regulated"
        elif prot_fc < -PROTEIN_CHANGE:
            protein_context = "Down-regulated"
        else:
            protein_context = "Unchanged"

        ptm_abs = abs(ptm_fc)
        protein_stable = -PROTEIN_CHANGE <= prot_fc <= PROTEIN_CHANGE
        protein_up = prot_fc > PROTEIN_CHANGE
        protein_down = prot_fc < -PROTEIN_CHANGE
        ptm_up = ptm_fc > PTM_LOW
        ptm_down = ptm_fc < -PTM_LOW
        ptm_high = ptm_abs > PTM_HIGH
        ptm_minimal = ptm_abs <= PTM_LOW

        if ptm_high and ptm_fc > 0 and protein_stable:
            level = "PTM-driven hyperactivation"
            short_label = "PTM-driven ↑↑"
            significance = "High"
        elif ptm_high and ptm_fc < 0 and protein_stable:
            level = "PTM-driven inactivation"
            short_label = "PTM-driven ↓↓"
            significance = "High"
        elif ptm_high and ptm_fc > 0 and protein_down:
            level = "Compensatory PTM hyperactivation"
            short_label = "Compensatory ↑↑"
            significance = "High"
        elif ptm_up and protein_up:
            level = "Coupled activation"
            short_label = "Coupled ↑"
            significance = "Moderate"
        elif ptm_down and protein_down:
            level = "Coupled shutdown"
            short_label = "Coupled ↓"
            significance = "Moderate"
        elif ptm_down and protein_up:
            level = "Desensitization-like pattern"
            short_label = "Desensitization"
            significance = "Moderate"
        elif ptm_minimal and (protein_up or protein_down):
            level = "Expression-driven change"
            short_label = "Expression-driven"
            significance = "Low"
        else:
            level = "Baseline / low-change state"
            short_label = "Baseline"
            significance = "Low"

        return {
            "level": level,
            "short_label": short_label,
            "significance": significance,
            "protein_context": protein_context,
        }

    # ------------------------------------------------------------------
    # Trajectory (Time-Course) Data Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_trajectory(ptm: dict) -> dict:
        """Extract time-course trajectory data from PTM entry if available."""
        trajectory = {"timepoints": [], "trend": "unknown"}

        # Check for pre-existing trajectory data
        existing = ptm.get("trajectory")
        if existing and isinstance(existing, dict):
            return existing

        # Check for multi-timepoint data in the PTM entry
        timepoints_raw = ptm.get("timepoints") or ptm.get("time_course", [])
        if isinstance(timepoints_raw, list) and len(timepoints_raw) >= 2:
            timepoints = []
            for tp in timepoints_raw:
                timepoints.append({
                    "timeLabel": tp.get("time_label") or tp.get("timeLabel", ""),
                    "ptmLog2FC": float(tp.get("ptm_log2fc") or tp.get("ptmLog2FC", 0)),
                    "proteinLog2FC": float(tp.get("protein_log2fc") or tp.get("proteinLog2FC", 0)),
                    "classification": tp.get("classification", ""),
                })

            # Determine trend
            if len(timepoints) >= 2:
                first_fc = timepoints[0]["ptmLog2FC"]
                last_fc = timepoints[-1]["ptmLog2FC"]
                peak_fc = max(tp["ptmLog2FC"] for tp in timepoints)
                trough_fc = min(tp["ptmLog2FC"] for tp in timepoints)

                if last_fc > first_fc + 0.5:
                    trend = "increasing"
                elif last_fc < first_fc - 0.5:
                    trend = "decreasing"
                elif peak_fc > first_fc + 1.0 and last_fc < peak_fc - 0.5:
                    trend = "transient_peak"
                elif trough_fc < first_fc - 1.0 and last_fc > trough_fc + 0.5:
                    trend = "transient_dip"
                else:
                    trend = "stable"

                trajectory = {"timepoints": timepoints, "trend": trend}

        return trajectory

    # ------------------------------------------------------------------
    # Isoform Information Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_isoform_info(uniprot_info: dict) -> List[dict]:
        """Extract protein isoform information from UniProt data."""
        isoforms = uniprot_info.get("isoforms", [])
        if not isoforms:
            # Try alternative keys
            alt_products = uniprot_info.get("alternative_products", [])
            if alt_products:
                return alt_products
        return isoforms

    # ------------------------------------------------------------------
    # Context Keywords Extraction
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Public: Classification-Based PTM Selection (ported from ptm-vector-ai)
    # ------------------------------------------------------------------

    @staticmethod
    def select_ptms_by_classification(
        ptm_data: List[dict],
        conditions: Optional[List[str]] = None,
        include_high: bool = True,
        include_moderate: bool = True,
        include_low: bool = False,
        top_n: Optional[int] = None,
    ) -> List[dict]:
        """
        Select PTMs based on 8-category cell-signaling classification.
        Ported from ptm-vector-ai/ragEnrichmentService.ts selectPTMsByClassification().

        This method provides classification-aware PTM selection as an alternative
        to the simple |FC| ranking used in tasks.py.  When *top_n* is set, PTMs
        are ranked by |PTM_Relative_Log2FC| and the top N are returned regardless
        of significance level (matching the original TypeScript behaviour).

        Args:
            ptm_data: List of PTM dicts (must contain ptm_relative_log2fc / PTM_Relative_Log2FC)
            conditions: Optional list of conditions to filter by
            include_high: Include High significance (PTM-driven, Compensatory)
            include_moderate: Include Moderate significance (Coupled, Desensitization)
            include_low: Include Low significance (Expression-driven, Baseline)
            top_n: If set, select top N PTMs per condition by |PTM_Relative_Log2FC|

        Returns:
            List of selected PTM dicts with added 'classification' field.
        """
        selected: List[dict] = []
        added_keys: set = set()

        # Determine conditions
        if conditions is None:
            conditions_set = set()
            for ptm in ptm_data:
                cond = ptm.get("Condition") or ptm.get("condition", "")
                if cond:
                    conditions_set.add(cond)
            conditions = sorted(conditions_set, key=condition_sort_key) if conditions_set else [""]

        for condition in conditions:
            # Filter vectors for this condition
            if condition:
                cond_vectors = [
                    p for p in ptm_data
                    if (p.get("Condition") or p.get("condition", "")) == condition
                ]
            else:
                cond_vectors = list(ptm_data)

            # Sort by |PTM_Relative_Log2FC| descending
            def _get_fc(p):
                val = p.get("PTM_Relative_Log2FC") or p.get("ptm_relative_log2fc")
                try:
                    return abs(float(val)) if val is not None else 0.0
                except (ValueError, TypeError):
                    return 0.0

            cond_vectors.sort(key=_get_fc, reverse=True)

            # Apply top_n if set
            if top_n and top_n > 0:
                cond_vectors = cond_vectors[:top_n]

            for ptm in cond_vectors:
                gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
                pos = ptm.get("position") or ptm.get("PTM_Position", "?")
                key = f"{gene}_{pos}"

                if key in added_keys:
                    continue

                ptm_fc = ptm.get("PTM_Relative_Log2FC") or ptm.get("ptm_relative_log2fc")
                prot_fc = ptm.get("Protein_Log2FC") or ptm.get("protein_log2fc")

                try:
                    ptm_fc_f = float(ptm_fc) if ptm_fc is not None else 0.0
                except (ValueError, TypeError):
                    continue

                classification = RAGEnrichmentPipeline._classify_ptm_8cat(ptm_fc_f, prot_fc)
                sig = classification.get("significance", "Low")

                # When top_n is set, include ALL PTMs (already filtered by ranking)
                include = False
                if top_n and top_n > 0:
                    include = True
                elif include_high and sig == "High":
                    include = True
                elif include_moderate and sig == "Moderate":
                    include = True
                elif include_low and sig == "Low":
                    include = True

                if include:
                    ptm["classification"] = classification
                    selected.append(ptm)
                    added_keys.add(key)

        # Summary logging
        high_count = sum(1 for p in selected if p.get("classification", {}).get("significance") == "High")
        mod_count = sum(1 for p in selected if p.get("classification", {}).get("significance") == "Moderate")
        low_count = sum(1 for p in selected if p.get("classification", {}).get("significance") == "Low")
        logger.info(
            f"PTM classification selection: {len(selected)} PTMs from {len(conditions)} conditions "
            f"(High={high_count}, Moderate={mod_count}, Low={low_count})"
        )

        return selected

    def _extract_context_keywords(self, context: Optional[dict]) -> List[str]:
        if not context:
            return []

        keywords = []
        for key in ("tissue", "treatment", "condition", "disease", "cell_type", "organism"):
            val = context.get(key)
            if val and isinstance(val, str):
                keywords.append(val.strip())

        biological_question = (context.get("biological_question") or "").strip()
        special_conditions = (context.get("special_conditions") or context.get("condition") or "").strip()
        if biological_question:
            keywords.extend(_extract_meaningful_words(biological_question))
        if special_conditions:
            keywords.extend(_extract_meaningful_words(special_conditions))

        extra = context.get("keywords", [])
        if isinstance(extra, list):
            keywords.extend(extra)
        elif isinstance(extra, str):
            keywords.extend(extra.split(","))

        return [k.strip() for k in keywords if k.strip()][:10]


def _extract_meaningful_words(text: str) -> List[str]:
    """Extract keywords from long text (biological_question, special_conditions)."""
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "should", "could", "may", "might", "must", "can", "cell",
        "cells", "tissue", "tissues", "type", "types", "what", "which", "how",
    }
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return [w for w in words if len(w) > 3 and w not in stopwords and not w.isdigit()]
