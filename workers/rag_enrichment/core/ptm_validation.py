"""
PTM Validation — validates PTM sites against external databases.

Ported from ptm-rag-backend/src/ptmValidation.ts (v4.0).

Features:
  - iPTMnet-based novelty assessment (known vs novel PTM sites)
  - Cross-site PTM search (context-aware, not tissue-specific)
  - Multi-database validation (UniProt, PhosphoSitePlus via iPTMnet)
  - Confidence scoring with evidence grading
  - Homonym filtering for gene names
  - **v4.0**: Context-aware search (cell type, treatment, biological question)
  - **v4.0**: Relevance filtering based on experimental context
  - **v4.0**: Improved query generation with context keywords
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from common.mcp_client import MCPClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Homonym filter — gene names that are also common non-biological terms
# ---------------------------------------------------------------------------

KNOWN_HOMONYMS = {
    "SMAP", "IMPACT", "CAMP", "REST", "SET", "BAD", "BAG", "BAP",
    "CAT", "CAN", "CAP", "CARD", "CAST", "CHIP", "CLOCK", "COBRA",
    "COPE", "DAB", "DAM", "DAMP", "DOCK", "DOME", "DOOR", "FAST",
    "FAT", "FIT", "FLAG", "FLAP", "FLIP", "FLOW", "GAP", "GAS",
    "GRIP", "HAND", "HIT", "HOOK", "HUNT", "JAM", "LAMP", "LARD",
    "LEAD", "LIME", "LINK", "LOCK", "MALT", "MAP", "MARK", "MASK",
    "MINT", "MIST", "NAIL", "NET", "PALM", "PARK", "PATCH", "PEAK",
    "PICK", "PIN", "PINK", "PIPE", "PLAN", "POLE", "POLL", "POOL",
    "PORE", "PRIME", "RING", "ROCK", "SALT", "SAND", "SCAR", "SEAL",
    "SHARP", "SHIP", "SHOT", "SIGN", "SILK", "SLIM", "SLIP", "SLOT",
    "SNAP", "SORT", "SPAN", "SPARK", "SPIN", "SPOT", "SPRING", "STAR",
    "STEM", "STING", "STOP", "STORM", "STRAP", "STRIP", "STUB", "SWAP",
    "TANK", "TAPE", "TEAR", "TIDE", "TOLL", "TRAP", "TRIM", "TRIP",
    "TUBE", "TWIST", "WASP", "WAVE", "WRAP",
}

# ---------------------------------------------------------------------------
# Context-Aware Keyword Expansion Maps (v4.0)
# ---------------------------------------------------------------------------

CELL_TYPE_EXPANSIONS: Dict[str, List[str]] = {
    "muscle": ["muscle", "skeletal muscle", "myocyte", "myofiber", "myotube"],
    "cardiac": ["cardiac", "heart", "cardiomyocyte"],
    "heart": ["cardiac", "heart", "cardiomyocyte"],
    "neuron": ["neuron", "brain", "neural", "neuronal"],
    "brain": ["neuron", "brain", "neural", "neuronal", "cerebral"],
    "liver": ["liver", "hepatocyte", "hepatic"],
    "hepat": ["liver", "hepatocyte", "hepatic"],
    "kidney": ["kidney", "renal", "nephron"],
    "renal": ["kidney", "renal", "nephron"],
    "lung": ["lung", "pulmonary", "alveolar"],
    "adipose": ["adipose", "adipocyte", "fat tissue"],
    "bone": ["bone", "osteocyte", "osteoblast", "osteoclast"],
    "osteocyte": ["osteocyte", "bone", "osteoblast", "mechanosensing"],
    "macrophage": ["macrophage", "monocyte", "innate immunity"],
    "t cell": ["T cell", "lymphocyte", "adaptive immunity"],
    "stem": ["stem cell", "progenitor", "differentiation"],
    "endotheli": ["endothelial", "vascular", "angiogenesis"],
    "epitheli": ["epithelial", "barrier", "tight junction"],
    "fibroblast": ["fibroblast", "connective tissue", "extracellular matrix"],
    "platelet": ["platelet", "thrombocyte", "coagulation"],
    "pancrea": ["pancreas", "beta cell", "islet", "insulin secretion"],
}

TREATMENT_EXPANSIONS: Dict[str, List[str]] = {
    "exercise": ["exercise", "contraction", "physical activity", "training", "endurance"],
    "contraction": ["exercise", "contraction", "physical activity", "muscle contraction"],
    "insulin": ["insulin", "glucose", "metabolic", "insulin signaling"],
    "stress": ["stress", "oxidative stress", "stress response"],
    "hypoxia": ["hypoxia", "oxygen", "HIF", "ischemia"],
    "irisin": ["irisin", "FNDC5", "myokine", "exercise"],
    "egf": ["EGF", "epidermal growth factor", "EGFR", "growth factor"],
    "igf": ["IGF", "insulin-like growth factor", "growth factor"],
    "tgf": ["TGF", "transforming growth factor", "SMAD"],
    "tnf": ["TNF", "tumor necrosis factor", "inflammation", "NF-kB"],
    "lps": ["LPS", "lipopolysaccharide", "inflammation", "innate immunity"],
    "rapamycin": ["rapamycin", "mTOR", "mTORC1", "autophagy"],
    "starvation": ["starvation", "nutrient deprivation", "autophagy", "AMPK"],
    "fasting": ["fasting", "nutrient deprivation", "metabolic adaptation"],
    "radiation": ["radiation", "DNA damage", "ATM", "ATR"],
    "chemotherapy": ["chemotherapy", "drug resistance", "apoptosis"],
    "heat shock": ["heat shock", "HSP", "protein folding", "stress response"],
    "cold": ["cold exposure", "thermogenesis", "UCP1", "brown adipose"],
    "wnt": ["Wnt", "beta-catenin", "Wnt signaling"],
    "notch": ["Notch", "Notch signaling", "differentiation"],
}

QUESTION_EXPANSIONS: Dict[str, List[str]] = {
    "adaptation": ["adaptation", "adaptive", "remodeling"],
    "metabolism": ["metabolism", "metabolic", "energy"],
    "signaling": ["signaling", "signal transduction", "pathway"],
    "apoptosis": ["apoptosis", "cell death", "caspase"],
    "proliferation": ["proliferation", "cell cycle", "mitosis"],
    "differentiation": ["differentiation", "lineage", "commitment"],
    "migration": ["migration", "motility", "invasion"],
    "inflammation": ["inflammation", "inflammatory", "cytokine"],
    "autophagy": ["autophagy", "lysosome", "mTOR"],
    "mechanotransduction": ["mechanotransduction", "mechanical stress", "mechanosensing"],
}


@dataclass
class PTMValidationResult:
    gene: str = ""
    position: str = ""
    ptm_type: str = ""

    # Novelty assessment
    is_known: bool = False
    novelty: str = ""  # "known" | "novel" | "uncertain"
    novelty_confidence: str = ""  # "high" | "medium" | "low"

    # Database evidence
    iptmnet_hits: List[dict] = field(default_factory=list)
    uniprot_ptm_sites: List[dict] = field(default_factory=list)

    # Cross-site PTM search results
    cross_site_results: List[dict] = field(default_factory=list)

    # PubMed context-aware search results (v4.0)
    pubmed_context_articles: List[dict] = field(default_factory=list)
    context_relevance_score: float = 0.0

    # Validation summary
    evidence_count: int = 0
    evidence_sources: List[str] = field(default_factory=list)
    validation_summary: str = ""

    # Homonym check
    is_homonym_risk: bool = False
    homonym_note: str = ""


@dataclass
class CrossSitePTMResult:
    gene: str = ""
    position: str = ""
    ptm_type: str = ""
    known_sites: List[dict] = field(default_factory=list)
    related_sites: List[dict] = field(default_factory=list)
    functional_info: List[dict] = field(default_factory=list)
    context_matches: List[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Context-Aware Keyword Generation (v4.0)
# ---------------------------------------------------------------------------

def generate_context_keywords(context: Optional[dict]) -> List[str]:
    """
    Generate context-aware search keywords from experimental context.
    Ported from ptmValidation.ts v4.0 generateContextKeywords().

    Expands cell type, treatment, and biological question into
    domain-specific synonym sets for more precise PubMed queries.
    """
    if not context:
        return []

    keywords: List[str] = []

    # --- Cell type expansion ---
    cell_type = (context.get("cell_type") or context.get("tissue") or "").lower()
    if cell_type:
        matched = False
        for trigger, expansions in CELL_TYPE_EXPANSIONS.items():
            if trigger in cell_type:
                keywords.extend(expansions)
                matched = True
        if not matched:
            # Use raw cell type as keyword
            keywords.append(cell_type)

    # --- Treatment expansion ---
    treatment = (context.get("treatment") or "").lower()
    if treatment:
        matched = False
        for trigger, expansions in TREATMENT_EXPANSIONS.items():
            if trigger in treatment:
                keywords.extend(expansions)
                matched = True
        if not matched:
            keywords.append(treatment)

    # --- Biological question expansion ---
    question = (context.get("biological_question") or "").lower()
    if question:
        for trigger, expansions in QUESTION_EXPANSIONS.items():
            if trigger in question:
                keywords.extend(expansions)

    # --- Special conditions ---
    special = (context.get("special_conditions") or context.get("condition") or "").lower()
    if special:
        # Extract meaningful words (>3 chars, not stopwords)
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "which",
            "were", "been", "have", "will", "would", "could", "should",
            "cell", "cells", "type", "types", "using", "used", "after",
        }
        words = re.findall(r"[A-Za-z0-9]+", special)
        meaningful = [w for w in words if len(w) > 3 and w.lower() not in stopwords]
        keywords.extend(meaningful[:5])

    # --- Extra keywords from context ---
    extra = context.get("keywords", [])
    if isinstance(extra, list):
        keywords.extend(extra)
    elif isinstance(extra, str):
        keywords.extend([k.strip() for k in extra.split(",") if k.strip()])

    # Deduplicate while preserving order
    seen = set()
    unique: List[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique.append(kw)

    return unique[:15]  # Cap at 15 keywords


def build_context_aware_query(
    gene: str,
    base_query: str,
    context: Optional[dict],
) -> str:
    """
    Build a context-aware PubMed query by appending context keywords.
    Ported from ptmValidation.ts v4.0 buildContextAwareQuery().
    """
    context_keywords = generate_context_keywords(context)
    if not context_keywords:
        return base_query

    # Build OR clause for context keywords
    context_clause = " OR ".join(
        f'"{kw}"[Title/Abstract]' for kw in context_keywords
    )
    return f"{base_query} AND ({context_clause})"


def filter_by_context_relevance(
    articles: List[dict],
    context: Optional[dict],
) -> List[dict]:
    """
    Filter and re-rank articles by relevance to experimental context.
    Ported from ptmValidation.ts v4.0 filterByContextRelevance().

    Returns articles sorted by context relevance score (descending).
    Falls back to returning all articles if none match.
    """
    if not context or not articles:
        return articles

    context_keywords = generate_context_keywords(context)
    if not context_keywords:
        return articles

    scored: List[Tuple[dict, int]] = []
    for article in articles:
        text = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
        score = sum(1 for kw in context_keywords if kw.lower() in text)
        scored.append((article, score))

    # Sort by relevance score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Return articles with score > 0 (at least one context keyword match)
    relevant = [a for a, s in scored if s > 0]
    if relevant:
        logger.info(
            f"Context filtering: {len(relevant)}/{len(articles)} articles relevant"
        )
        return relevant

    # Fallback: return all articles
    logger.info("Context filtering: No relevant articles found, returning all")
    return articles


class PTMValidator:
    """Validates PTM sites against external databases via MCP."""

    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client

    def validate(
        self,
        gene: str,
        position: str = "",
        ptm_type: str = "Phosphorylation",
        experimental_context: Optional[dict] = None,
        # Legacy parameter name support
        site: str = "",
    ) -> PTMValidationResult:
        """
        Validate a PTM site against iPTMnet and UniProt.
        v4.0: Now uses experimental_context for context-aware PubMed queries.

        Args:
            gene: Gene name
            position: PTM position (e.g., "S79")
            ptm_type: PTM type
            experimental_context: Optional context for context-aware search
                Keys: cell_type, tissue, treatment, biological_question,
                      special_conditions, organism, keywords
            site: Legacy alias for position

        Returns:
            PTMValidationResult with novelty assessment and evidence.
        """
        # Support legacy 'site' parameter
        if not position and site:
            position = site

        result = PTMValidationResult(gene=gene, position=position, ptm_type=ptm_type)

        # 1. Homonym check
        if gene.upper() in KNOWN_HOMONYMS:
            result.is_homonym_risk = True
            result.homonym_note = (
                f"'{gene}' is a known homonym — search results may include "
                f"non-biological entities. Results have been filtered for biological context."
            )

        # 2. iPTMnet query — uses MCPClient.query_iptmnet()
        try:
            iptmnet_data = self.mcp.query_iptmnet(
                gene=gene, position=position,
            )
            sites_found = iptmnet_data.get("sites_found", 0)
            novelty_info = iptmnet_data.get("novelty") or {}

            if sites_found > 0:
                result.iptmnet_hits = [{"position": position, "source": "iPTMnet"}]
                iptmnet_status = novelty_info.get("status", "")

                if iptmnet_status and iptmnet_status != "NOVEL":
                    result.is_known = True
                    result.evidence_sources.append("iPTMnet")

                if novelty_info.get("pmids"):
                    for pmid in novelty_info["pmids"][:5]:
                        result.iptmnet_hits.append({
                            "position": position,
                            "source": "iPTMnet",
                            "pmid": pmid,
                        })

        except Exception as e:
            logger.warning(f"iPTMnet query failed for {gene} {position}: {e}")

        # 3. UniProt PTM sites — uses MCPClient.query_uniprot()
        try:
            uniprot_data = self.mcp.query_uniprot(gene)

            go_bp = uniprot_data.get("go_terms_bp", [])
            go_mf = uniprot_data.get("go_terms_mf", [])
            function_summary = uniprot_data.get("function_summary", "")

            ptm_keywords = ["phosphorylat", "kinase", "acetylat", "ubiquitin", "methylat"]
            ptm_related = any(
                kw in (function_summary or "").lower()
                for kw in ptm_keywords
            )

            if ptm_related:
                result.uniprot_ptm_sites.append({
                    "gene": gene,
                    "source": "UniProt",
                    "function_summary": function_summary[:200] if function_summary else "",
                })
                if "UniProt" not in result.evidence_sources:
                    result.evidence_sources.append("UniProt")

        except Exception as e:
            logger.warning(f"UniProt query failed for {gene}: {e}")

        # 4. Cross-site PTM search (context-aware)
        try:
            cross_result = self._cross_site_search(gene, position, ptm_type, experimental_context)
            result.cross_site_results = cross_result.known_sites

            if cross_result.known_sites and not result.is_known:
                result.novelty = "novel"
                result.novelty_confidence = "medium"
            elif not cross_result.known_sites and not result.is_known:
                result.novelty = "novel"
                result.novelty_confidence = "high"

        except Exception as e:
            logger.warning(f"Cross-site search failed for {gene} {position}: {e}")

        # 5. **v4.0** Context-aware PubMed search for additional evidence
        if experimental_context:
            try:
                ctx_articles, ctx_score = self._context_aware_pubmed_search(
                    gene, position, ptm_type, experimental_context,
                )
                result.pubmed_context_articles = ctx_articles
                result.context_relevance_score = ctx_score

                if ctx_articles:
                    if "PubMed(context)" not in result.evidence_sources:
                        result.evidence_sources.append("PubMed(context)")

                    # If context-aware search found strong evidence, upgrade confidence
                    if ctx_score >= 3.0 and result.novelty == "novel":
                        result.novelty = "likely_known"
                        result.novelty_confidence = "medium"
                        logger.info(
                            f"{gene} {position}: Context-aware search found strong evidence "
                            f"(score={ctx_score:.1f}), upgrading to 'likely_known'"
                        )

            except Exception as e:
                logger.warning(f"Context-aware PubMed search failed for {gene}: {e}")

        # 6. Determine novelty
        if result.is_known:
            result.novelty = "known"
            result.novelty_confidence = "high"
            result.evidence_count = len(result.iptmnet_hits) + len(result.uniprot_ptm_sites)
        elif not result.iptmnet_hits and not result.uniprot_ptm_sites:
            if not result.novelty:  # Don't override context-aware upgrade
                result.novelty = "novel"
                result.novelty_confidence = "high"
            result.evidence_count = len(result.pubmed_context_articles)
        else:
            if not result.novelty:
                result.novelty = "uncertain"
                result.novelty_confidence = "low"
            result.evidence_count = (
                len(result.iptmnet_hits)
                + len(result.uniprot_ptm_sites)
                + len(result.pubmed_context_articles)
            )

        # 7. Build summary
        result.validation_summary = self._build_summary(result)

        return result

    # ------------------------------------------------------------------
    # v4.0: Context-Aware PubMed Search
    # ------------------------------------------------------------------

    def _context_aware_pubmed_search(
        self,
        gene: str,
        position: str,
        ptm_type: str,
        context: dict,
    ) -> Tuple[List[dict], float]:
        """
        Perform context-aware PubMed search using experimental context keywords.
        Ported from ptmValidation.ts v4.0 searchGeneralProteinInfo().

        Returns:
            Tuple of (filtered_articles, aggregate_relevance_score)
        """
        context_keywords = generate_context_keywords(context)
        if not context_keywords:
            return [], 0.0

        logger.info(
            f"Context-aware search for {gene} {position}: "
            f"context_keywords={context_keywords[:5]}"
        )

        all_articles: List[dict] = []
        seen_pmids: set = set()

        # Strategy 1: Gene + PTM type + context keywords
        try:
            articles = self.mcp.search_pubmed(
                gene=gene,
                position=position,
                ptm_type=ptm_type,
                context_keywords=context_keywords[:5],
                max_results=10,
            )
            for a in articles.get("articles", []):
                pmid = a.get("pmid", "")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    all_articles.append(a)
        except Exception as e:
            logger.debug(f"Context search strategy 1 failed: {e}")

        # Strategy 2: Gene + kinase/phosphatase + context keywords
        try:
            articles = self.mcp.search_pubmed(
                gene=gene,
                position="",
                ptm_type="kinase OR phosphatase",
                context_keywords=context_keywords[:3],
                max_results=5,
            )
            for a in articles.get("articles", []):
                pmid = a.get("pmid", "")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    all_articles.append(a)
        except Exception as e:
            logger.debug(f"Context search strategy 2 failed: {e}")

        # Strategy 3: Gene + regulation/signaling + context keywords
        try:
            articles = self.mcp.search_pubmed(
                gene=gene,
                position="",
                ptm_type="regulation OR signaling OR pathway",
                context_keywords=context_keywords[:3],
                max_results=5,
            )
            for a in articles.get("articles", []):
                pmid = a.get("pmid", "")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    all_articles.append(a)
        except Exception as e:
            logger.debug(f"Context search strategy 3 failed: {e}")

        # Filter by context relevance
        filtered = filter_by_context_relevance(all_articles, context)

        # Calculate aggregate relevance score
        if not filtered:
            return [], 0.0

        total_score = 0.0
        for article in filtered:
            text = f"{article.get('title', '')} {article.get('abstract', '')}".lower()
            score = sum(1 for kw in context_keywords if kw.lower() in text)
            total_score += score

        avg_score = total_score / len(filtered) if filtered else 0.0

        logger.info(
            f"Context-aware search for {gene}: "
            f"{len(filtered)} relevant articles (avg_score={avg_score:.1f})"
        )

        return filtered[:10], avg_score

    # ------------------------------------------------------------------
    # Cross-Site PTM Search
    # ------------------------------------------------------------------

    def _cross_site_search(
        self,
        gene: str,
        position: str,
        ptm_type: str,
        context: Optional[dict],
    ) -> CrossSitePTMResult:
        """
        Context-aware cross-site PTM search.
        Searches for other known PTM sites on the same protein,
        even if the exact position doesn't match.
        """
        result = CrossSitePTMResult(gene=gene, position=position, ptm_type=ptm_type)

        # Query iPTMnet for all known sites on this gene (empty position = all sites)
        try:
            all_sites_data = self.mcp.query_iptmnet(
                gene=gene, position="",
            )
            sites_found = all_sites_data.get("sites_found", 0)
            if sites_found > 0:
                novelty_info = all_sites_data.get("novelty") or {}
                site_info = {
                    "position": "all",
                    "ptm_type": ptm_type,
                    "source": "iPTMnet",
                    "sites_found": sites_found,
                    "status": novelty_info.get("status", ""),
                }
                result.known_sites.append(site_info)

                if position:
                    result.related_sites.append(site_info)

        except Exception as e:
            logger.warning(f"Cross-site search failed: {e}")

        # Context-aware filtering
        if context:
            tissue = (context.get("tissue") or context.get("cell_type") or "").lower()
            treatment = (context.get("treatment") or "").lower()

            for site in result.known_sites:
                func = (site.get("function") or "").lower()
                if tissue and tissue in func:
                    result.context_matches.append({
                        **site,
                        "context_match": "tissue",
                    })
                if treatment and treatment in func:
                    result.context_matches.append({
                        **site,
                        "context_match": "treatment",
                    })

        return result

    # ------------------------------------------------------------------
    # Summary Builder
    # ------------------------------------------------------------------

    def _build_summary(self, result: PTMValidationResult) -> str:
        """Build human-readable validation summary."""
        gene = result.gene
        pos = result.position

        if result.novelty == "known":
            sources = ", ".join(result.evidence_sources) or "database"
            return (
                f"{gene} {pos} is a **known** {result.ptm_type} site "
                f"(confirmed in {sources}, {result.evidence_count} evidence records)."
            )
        elif result.novelty == "likely_known":
            return (
                f"{gene} {pos} is **likely known** — not found in iPTMnet/UniProt directly, "
                f"but context-aware literature search found supporting evidence "
                f"(relevance score: {result.context_relevance_score:.1f}). "
                f"Sources: {', '.join(result.evidence_sources)}."
            )
        elif result.novelty == "novel":
            related_count = len(result.cross_site_results)
            ctx_count = len(result.pubmed_context_articles)
            parts = []
            parts.append(
                f"{gene} {pos} appears to be a **novel** {result.ptm_type} site "
                f"(not found in iPTMnet/UniProt)."
            )
            if related_count > 0:
                parts.append(
                    f"However, {related_count} other {result.ptm_type} sites are known on "
                    f"{gene}, suggesting the protein is a validated {result.ptm_type} target."
                )
            if ctx_count > 0:
                parts.append(
                    f"Context-aware search found {ctx_count} related articles in the "
                    f"experimental context."
                )
            return " ".join(parts)
        else:
            return (
                f"{gene} {pos} validation is **uncertain** — partial matches found "
                f"but exact site confirmation is inconclusive."
            )
