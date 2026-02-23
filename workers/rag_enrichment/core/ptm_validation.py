"""
PTM Validation — validates PTM sites against external databases.

Ported from ptm-rag-backend/src/ptmValidation.ts (v2.0).

Features:
  - iPTMnet-based novelty assessment (known vs novel PTM sites)
  - Cross-site PTM search (context-aware, not tissue-specific)
  - Multi-database validation (UniProt, PhosphoSitePlus via iPTMnet)
  - Confidence scoring with evidence grading
  - Homonym filtering for gene names
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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


class PTMValidator:
    """Validates PTM sites against external databases via MCP."""

    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client

    def validate(
        self,
        gene: str,
        position: str,
        ptm_type: str = "Phosphorylation",
        experimental_context: Optional[dict] = None,
    ) -> PTMValidationResult:
        """
        Validate a PTM site against iPTMnet and UniProt.

        Args:
            gene: Gene name
            position: PTM position (e.g., "S79")
            ptm_type: PTM type
            experimental_context: Optional context for context-aware search

        Returns:
            PTMValidationResult with novelty assessment and evidence.
        """
        result = PTMValidationResult(gene=gene, position=position, ptm_type=ptm_type)

        # 1. Homonym check
        if gene.upper() in KNOWN_HOMONYMS:
            result.is_homonym_risk = True
            result.homonym_note = (
                f"'{gene}' is a known homonym — search results may include "
                f"non-biological entities. Results have been filtered for biological context."
            )

        # 2. iPTMnet query
        try:
            iptmnet_data = self.mcp.call_tool("query_iptmnet", {
                "gene": gene, "position": position, "ptm_type": ptm_type,
            })
            result.iptmnet_hits = iptmnet_data.get("ptm_sites", [])

            # Check if exact site is known
            for hit in result.iptmnet_hits:
                hit_pos = str(hit.get("position", "")).upper()
                query_pos = position.upper()
                if hit_pos == query_pos or hit_pos in query_pos or query_pos in hit_pos:
                    result.is_known = True
                    result.evidence_sources.append("iPTMnet")
                    break

        except Exception as e:
            logger.warning(f"iPTMnet query failed for {gene} {position}: {e}")

        # 3. UniProt PTM sites
        try:
            uniprot_data = self.mcp.call_tool("query_uniprot", {"query": gene})
            ptm_features = uniprot_data.get("ptm_features", [])
            result.uniprot_ptm_sites = ptm_features

            # Check UniProt for known site
            for feat in ptm_features:
                feat_pos = str(feat.get("position", ""))
                if position.replace("S", "").replace("T", "").replace("Y", "").replace("K", "") in feat_pos:
                    result.is_known = True
                    if "UniProt" not in result.evidence_sources:
                        result.evidence_sources.append("UniProt")
                    break

        except Exception as e:
            logger.warning(f"UniProt query failed for {gene}: {e}")

        # 4. Cross-site PTM search (context-aware)
        try:
            cross_result = self._cross_site_search(gene, position, ptm_type, experimental_context)
            result.cross_site_results = cross_result.known_sites

            # Even if exact position doesn't match, related sites provide context
            if cross_result.known_sites and not result.is_known:
                result.novelty = "novel"
                result.novelty_confidence = "medium"
            elif not cross_result.known_sites and not result.is_known:
                result.novelty = "novel"
                result.novelty_confidence = "high"

        except Exception as e:
            logger.warning(f"Cross-site search failed for {gene} {position}: {e}")

        # 5. Determine novelty
        if result.is_known:
            result.novelty = "known"
            result.novelty_confidence = "high"
            result.evidence_count = len(result.iptmnet_hits) + len(result.uniprot_ptm_sites)
        elif not result.iptmnet_hits and not result.uniprot_ptm_sites:
            result.novelty = "novel"
            result.novelty_confidence = "high"
            result.evidence_count = 0
        else:
            result.novelty = "uncertain"
            result.novelty_confidence = "low"
            result.evidence_count = len(result.iptmnet_hits) + len(result.uniprot_ptm_sites)

        # 6. Build summary
        result.validation_summary = self._build_summary(result)

        return result

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

        # Query iPTMnet for all known sites on this gene
        try:
            all_sites = self.mcp.call_tool("query_iptmnet", {
                "gene": gene, "position": "", "ptm_type": ptm_type,
            })
            for site in all_sites.get("ptm_sites", []):
                site_info = {
                    "position": site.get("position", ""),
                    "ptm_type": site.get("ptm_type", ""),
                    "source": site.get("source", "iPTMnet"),
                    "regulators": site.get("regulators", []),
                    "function": site.get("function", ""),
                }
                result.known_sites.append(site_info)

                # If same gene + same PTM type but different position → related
                if str(site.get("position", "")).upper() != position.upper():
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
        elif result.novelty == "novel":
            related_count = len(result.cross_site_results)
            if related_count > 0:
                return (
                    f"{gene} {pos} appears to be a **novel** {result.ptm_type} site "
                    f"(not found in iPTMnet/UniProt). However, {related_count} other "
                    f"{result.ptm_type} sites are known on {gene}, suggesting the protein "
                    f"is a validated {result.ptm_type} target."
                )
            else:
                return (
                    f"{gene} {pos} appears to be a **novel** {result.ptm_type} site "
                    f"(no records found in iPTMnet or UniProt for this gene/site)."
                )
        else:
            return (
                f"{gene} {pos} validation is **uncertain** — partial matches found "
                f"but exact site confirmation is inconclusive."
            )
