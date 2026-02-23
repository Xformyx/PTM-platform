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
"""

import logging
import math
import re
from typing import Callable, Dict, List, Optional

import pandas as pd

from common.mcp_client import MCPClient
from common.llm_client import LLMClient
from common.local_data_loader import HPALocalLoader, GTExLocalLoader
from .regulation_extractor import RegulationExtractor
from .abstract_analyzer import AbstractAnalyzer
from .llm_kinase_predictor import LLMKinasePredictor
from .llm_functional_impact import LLMFunctionalImpact
from .fulltext_analyzer import FullTextAnalyzer
from .ptm_validation import PTMValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 8-Category Cell-Signaling Classification Thresholds
# ---------------------------------------------------------------------------
PTM_HIGH = 2.0       # Strong PTM change threshold (|Log2FC| > 2.0 = 4x fold change)
PTM_LOW = 0.5        # Minimal PTM change threshold (|Log2FC| <= 0.5 = <1.4x fold change)
PROTEIN_CHANGE = 0.5  # Protein change threshold (|Log2FC| > 0.5 = >1.4x fold change)


class RAGEnrichmentPipeline:
    """Enriches PTM vector data with literature search and pattern-based analysis."""

    def __init__(
        self,
        mcp_client: MCPClient,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        enable_llm_analysis: bool = True,
        enable_fulltext: bool = True,
        enable_ptm_validation: bool = True,
    ):
        self.mcp = mcp_client
        self.reg_extractor = RegulationExtractor()
        self._progress = progress_callback or (lambda p, m: None)

        # LLM-based analysis modules (restored from original)
        self.enable_llm = enable_llm_analysis
        self.enable_fulltext = enable_fulltext
        self.enable_ptm_validation = enable_ptm_validation

        if enable_llm_analysis:
            llm = LLMClient()  # auto-detects: Ollama → OpenAI → Gemini
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
            self.ptm_validator = PTMValidator(mcp_client=mcp_client)

        # Log local data availability
        if HPALocalLoader.is_available():
            logger.info("HPA local data available — will use local-first strategy")
        else:
            logger.info("HPA local data not available — will use MCP API only")

        if GTExLocalLoader.is_available():
            logger.info("GTEx local data available — will use local-first strategy")
        else:
            logger.info("GTEx local data not available — will use MCP API only")

    def enrich_ptm_data(
        self,
        ptm_data: List[dict],
        experimental_context: Optional[dict] = None,
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
        logger.info(f"RAG enrichment: processing {total} PTM entries")
        context_keywords = self._extract_context_keywords(experimental_context)

        enriched = []
        for i, ptm in enumerate(ptm_data):
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")
            self._progress(i / total, f"Enriching {gene} {pos}")

            try:
                result = self._enrich_single_ptm(ptm, context_keywords, experimental_context)
                enriched.append(result)
            except Exception as e:
                logger.warning(f"Enrichment failed for {ptm.get('gene')}/{ptm.get('position')}: {e}")
                ptm["rag_enrichment"] = self._empty_enrichment()
                enriched.append(ptm)

        self._progress(1.0, f"Enrichment complete: {len(enriched)} PTMs")
        return enriched

    def _enrich_single_ptm(
        self, ptm: dict, context_keywords: List[str], context: Optional[dict]
    ) -> dict:
        gene = ptm.get("gene") or ptm.get("Gene.Name", "Unknown")
        position = ptm.get("position") or ptm.get("PTM_Position", "Unknown")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        species = (context or {}).get("organism") or (context or {}).get("species", "")

        # 1. PubMed search via MCP
        search_result = self.mcp.search_pubmed(
            gene=gene, position=position, ptm_type=ptm_type,
            context_keywords=context_keywords, max_results=15,
        )
        articles = search_result.get("articles", [])

        # 2. Pattern-based regulation extraction
        regulation = self.reg_extractor.extract_from_articles(articles, gene, position)

        # 3. KEGG pathway info via MCP
        kegg_info = self.mcp.query_kegg(gene)
        kegg_pathways = kegg_info.get("pathways", [])

        # 4. STRING-DB interactions via MCP
        string_info = self.mcp.query_stringdb(gene, species=species)
        interactions = string_info.get("interactions", [])

        # 5. UniProt info via MCP
        protein_id = ptm.get("protein_id") or ptm.get("Protein.Group", "")
        uniprot_info = self.mcp.query_uniprot(protein_id, species=species) if protein_id else {}

        # 6. HPA (Human Protein Atlas) — LOCAL-FIRST with API fallback
        hpa_data = self._query_hpa_local_first(gene)

        # 7. GTEx tissue expression — LOCAL-FIRST with API fallback
        gtex_data = self._query_gtex_local_first(gene)

        # 8. BioGRID interactions via MCP
        biogrid_data = {}
        try:
            biogrid_data = self.mcp.query_biogrid(gene, species=species)
        except Exception as e:
            logger.warning(f"BioGRID query failed for {gene}: {e}")

        # 9. LLM-based abstract analysis (RESTORED)
        abstract_analysis = {}
        if self.enable_llm and articles:
            try:
                abstract_analysis = self.abstract_analyzer.analyze(
                    articles=articles, gene=gene, position=position, ptm_type=ptm_type,
                )
            except Exception as e:
                logger.warning(f"Abstract analysis failed for {gene}: {e}")

        # 10. LLM-based kinase prediction (RESTORED)
        kinase_prediction = {}
        if self.enable_llm:
            try:
                kinase_prediction = self.kinase_predictor.predict(
                    gene=gene, site=position, ptm_type=ptm_type,
                    context=context, articles=articles,
                )
            except Exception as e:
                logger.warning(f"Kinase prediction failed for {gene}: {e}")

        # 11. LLM-based functional impact analysis (RESTORED)
        functional_impact = {}
        if self.enable_llm:
            try:
                pathway_names = [p.get("name", p) if isinstance(p, dict) else p for p in kegg_pathways]
                functional_impact = self.functional_impact.analyze(
                    gene=gene, site=position, ptm_type=ptm_type,
                    articles=articles, pathways=pathway_names,
                )
            except Exception as e:
                logger.warning(f"Functional impact analysis failed for {gene}: {e}")

        # 12. Full-text analysis via PMC (RESTORED)
        fulltext_results = {}
        if self.enable_fulltext:
            try:
                fulltext_results = self._run_fulltext_analysis(
                    gene=gene, position=position, ptm_type=ptm_type,
                    articles=articles,
                )
            except Exception as e:
                logger.warning(f"Full-text analysis failed for {gene}: {e}")

        # 13. PTM validation / novelty check (RESTORED)
        validation_result = {}
        if self.enable_ptm_validation:
            try:
                validation_result = self.ptm_validator.validate(
                    gene=gene, site=position, ptm_type=ptm_type,
                )
            except Exception as e:
                logger.warning(f"PTM validation failed for {gene}: {e}")

        # 14. Merge regulation (KEGG + PubMed patterns)
        upstream = regulation["upstream_regulators"]
        downstream = regulation["downstream_targets"]

        # 15. Classify PTM significance (8-category cell-signaling system)
        ptm_log2fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
        protein_log2fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
        classification = self._classify_ptm_8cat(ptm_log2fc, protein_log2fc)

        # 16. Extract trajectory data (time-course)
        trajectory = self._extract_trajectory(ptm)

        # 17. Extract isoform information from UniProt
        isoform_info = self._extract_isoform_info(uniprot_info)

        # 18. Build enrichment result
        interaction_partners = [
            {"partner": i.get("partner", ""), "score": i.get("score", 0), "evidence": i.get("evidence", [])}
            for i in interactions[:10]
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
                "kinase_substrate": regulation["kinase_substrate"],
                "evidence_count": len(regulation["regulation_evidence"]),
                "regulation_evidence": regulation["regulation_evidence"],
            },
            "pathways": kegg_pathways,
            "string_db": {
                "interactions": interaction_partners,
            },
            "string_interactions": [
                f"{i.get('partner', '')}({i.get('score', 0)})" for i in interactions[:5]
            ],
            "diseases": regulation["diseases"],
            "localization": uniprot_info.get("subcellular_location", []),
            "function_summary": uniprot_info.get("function_summary", ""),
            "aliases": uniprot_info.get("gene_synonyms", []),
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
            "isoform_info": isoform_info,
            # Trajectory (time-course)
            "trajectory": trajectory,
            # --- RESTORED LLM analysis results ---
            "abstract_analysis": abstract_analysis,
            "kinase_prediction": kinase_prediction,
            "functional_impact": functional_impact,
            "fulltext_analysis": fulltext_results,
            "ptm_validation": validation_result,
        }

        ptm["rag_enrichment"] = enrichment
        return ptm

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
            if local_result and (local_result.get("locations") or local_result.get("tissue_expression")):
                logger.debug(f"HPA local data found for {gene}")
                return local_result

        # Fallback to MCP API
        try:
            hpa_data = self.mcp.query_hpa(gene)
            if hpa_data:
                hpa_data["source"] = "mcp_api"
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
                logger.debug(f"GTEx local data found for {gene}")
                return local_result

        # Fallback to MCP API
        try:
            gtex_data = self.mcp.query_gtex(gene)
            if gtex_data:
                gtex_data["source"] = "mcp_api"
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
    def _empty_enrichment() -> dict:
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
            "classification": {
                "level": "Baseline / low-change state",
                "short_label": "Baseline",
                "significance": "Low",
                "protein_context": None,
            },
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
            ptm_fc = float(ptm_log2fc or 0)
            prot_fc = float(protein_log2fc or 0)
        except (ValueError, TypeError):
            return {
                "level": "Baseline / low-change state",
                "short_label": "Baseline",
                "significance": "Low",
                "protein_context": None,
            }

        # Determine protein context
        protein_context = None
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
        elif ptm_up and protein_up:
            level = "Coupled activation"
            short_label = "Coupled ↑"
            significance = "Moderate"
        elif ptm_down and protein_down:
            level = "Coupled shutdown"
            short_label = "Coupled ↓"
            significance = "Moderate"
        elif ptm_high and ptm_fc > 0 and protein_down:
            level = "Compensatory PTM hyperactivation"
            short_label = "Compensatory ↑↑"
            significance = "High"
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
