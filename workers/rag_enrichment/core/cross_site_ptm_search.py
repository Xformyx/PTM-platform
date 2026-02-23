"""
Cross-Site PTM Search — searches for PTM evidence across multiple databases.

Ported from ptm-rag-backend/src/crossSitePTMSearch.ts.

Features:
  - PubMed abstract search for PTM + protein + site
  - PMC full-text search for detailed evidence
  - iPTMnet cross-reference for known PTM sites
  - UniProt PTM annotation lookup
  - Aggregated confidence scoring across sources
  - Antibody validation information extraction
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MCP_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")


@dataclass
class PTMEvidence:
    """Evidence for a PTM from a single source."""
    source: str  # "pubmed", "pmc", "iptmnet", "uniprot"
    protein: str
    site: str
    ptm_type: str
    pmid: str = ""
    title: str = ""
    snippet: str = ""
    confidence: float = 0.0
    antibody_info: Optional[str] = None  # Antibody validation info
    year: str = ""


@dataclass
class CrossSiteResult:
    """Aggregated cross-site search result for a PTM."""
    protein: str
    site: str
    ptm_type: str
    is_known: bool = False
    novelty_score: float = 1.0  # 1.0 = completely novel, 0.0 = well-known
    evidence_count: int = 0
    evidence: List[PTMEvidence] = field(default_factory=list)
    databases_found: List[str] = field(default_factory=list)
    antibody_validated: bool = False
    summary: str = ""


# ---------------------------------------------------------------------------
# Antibody Info Extraction Patterns
# ---------------------------------------------------------------------------

ANTIBODY_PATTERNS = [
    re.compile(
        r"(?:anti-?)?(?:phospho-?)?" + gene + r".*?(?:antibod(?:y|ies)).*?(?:\(([^)]+)\))",
        re.IGNORECASE,
    )
    for gene in [r"[A-Z][A-Z0-9]{1,6}"]
]

WESTERN_BLOT_PATTERN = re.compile(
    r"(?:western\s*blot|immunoblot).*?(?:anti-?)?(?:phospho-?)?\s*([A-Z][A-Z0-9]{1,6})",
    re.IGNORECASE,
)

ANTIBODY_VENDOR_PATTERN = re.compile(
    r"(?:Cell\s*Signaling|Abcam|Santa\s*Cruz|Sigma|Millipore|BD\s*Biosciences|"
    r"Thermo\s*Fisher|Invitrogen|R&D\s*Systems|Proteintech)\s*(?:#?\s*\d+)?",
    re.IGNORECASE,
)


def extract_antibody_info(text: str, protein: str) -> Optional[str]:
    """Extract antibody validation information from text."""
    protein_upper = protein.upper()
    info_parts = []

    # Search for western blot mentions
    for match in WESTERN_BLOT_PATTERN.finditer(text):
        if protein_upper in match.group(0).upper():
            info_parts.append(f"Western blot confirmed: {match.group(0).strip()[:100]}")

    # Search for antibody vendor info
    # Look in context around protein name
    protein_pattern = re.compile(
        rf"(?:anti-?)?(?:phospho-?)?\s*{re.escape(protein)}.*?(?:\n|$)",
        re.IGNORECASE,
    )
    for match in protein_pattern.finditer(text):
        context = match.group(0)
        vendor_match = ANTIBODY_VENDOR_PATTERN.search(context)
        if vendor_match:
            info_parts.append(f"Antibody: {vendor_match.group(0).strip()}")

    return "; ".join(info_parts) if info_parts else None


# ---------------------------------------------------------------------------
# Cross-Site PTM Searcher
# ---------------------------------------------------------------------------

class CrossSitePTMSearcher:
    """Searches for PTM evidence across multiple databases via MCP."""

    def __init__(self, mcp_base_url: str = MCP_URL):
        self.mcp_url = mcp_base_url

    async def search(
        self,
        protein: str,
        site: str,
        ptm_type: str = "phosphorylation",
        include_fulltext: bool = True,
    ) -> CrossSiteResult:
        """
        Search for PTM evidence across multiple databases.

        Args:
            protein: Protein/gene name (e.g., "AKT1")
            site: PTM site (e.g., "S473")
            ptm_type: Type of PTM
            include_fulltext: Whether to search PMC full-text

        Returns:
            CrossSiteResult with aggregated evidence
        """
        result = CrossSiteResult(
            protein=protein,
            site=site,
            ptm_type=ptm_type,
        )

        # 1. PubMed search
        pubmed_evidence = await self._search_pubmed(protein, site, ptm_type)
        result.evidence.extend(pubmed_evidence)
        if pubmed_evidence:
            result.databases_found.append("pubmed")

        # 2. PMC full-text search (if enabled)
        if include_fulltext:
            pmc_evidence = await self._search_pmc(protein, site, ptm_type)
            result.evidence.extend(pmc_evidence)
            if pmc_evidence:
                result.databases_found.append("pmc")

        # 3. iPTMnet lookup
        iptmnet_evidence = await self._search_iptmnet(protein, site, ptm_type)
        result.evidence.extend(iptmnet_evidence)
        if iptmnet_evidence:
            result.databases_found.append("iptmnet")

        # 4. Aggregate results
        result.evidence_count = len(result.evidence)
        result.is_known = result.evidence_count > 0
        result.novelty_score = self._calculate_novelty(result)

        # 5. Check antibody validation
        for ev in result.evidence:
            if ev.antibody_info:
                result.antibody_validated = True
                break

        # 6. Generate summary
        result.summary = self._generate_summary(result)

        return result

    async def search_batch(
        self,
        ptm_list: List[Dict[str, str]],
        include_fulltext: bool = True,
    ) -> List[CrossSiteResult]:
        """
        Search for multiple PTMs.

        Args:
            ptm_list: List of dicts with keys: protein, site, ptm_type
            include_fulltext: Whether to search PMC full-text

        Returns:
            List of CrossSiteResult
        """
        import asyncio

        tasks = [
            self.search(
                protein=ptm.get("protein", ""),
                site=ptm.get("site", ""),
                ptm_type=ptm.get("ptm_type", "phosphorylation"),
                include_fulltext=include_fulltext,
            )
            for ptm in ptm_list
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for r in results:
            if isinstance(r, CrossSiteResult):
                valid_results.append(r)
            else:
                logger.error(f"Cross-site search error: {r}")

        return valid_results

    # -----------------------------------------------------------------------
    # Database-specific search methods
    # -----------------------------------------------------------------------

    async def _search_pubmed(
        self, protein: str, site: str, ptm_type: str,
    ) -> List[PTMEvidence]:
        """Search PubMed for PTM evidence."""
        try:
            import httpx

            query = f"{protein} {site} {ptm_type}"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.mcp_url}/tools/pubmed_search",
                    json={"query": query, "max_results": 10},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                articles = data.get("result", {}).get("articles", [])

                evidence = []
                for art in articles:
                    abstract = art.get("abstract", "")
                    # Check if the specific site is mentioned
                    site_mentioned = (
                        site.lower() in abstract.lower()
                        or protein.lower() in abstract.lower()
                    )

                    if site_mentioned:
                        ab_info = extract_antibody_info(abstract, protein)
                        ev = PTMEvidence(
                            source="pubmed",
                            protein=protein,
                            site=site,
                            ptm_type=ptm_type,
                            pmid=art.get("pmid", ""),
                            title=art.get("title", ""),
                            snippet=abstract[:300],
                            confidence=0.7 if site.lower() in abstract.lower() else 0.4,
                            antibody_info=ab_info,
                            year=art.get("year", ""),
                        )
                        evidence.append(ev)

                return evidence

        except Exception as e:
            logger.warning(f"PubMed search failed for {protein} {site}: {e}")
            return []

    async def _search_pmc(
        self, protein: str, site: str, ptm_type: str,
    ) -> List[PTMEvidence]:
        """Search PMC full-text for detailed PTM evidence."""
        try:
            import httpx

            query = f"{protein} {site} {ptm_type}"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.mcp_url}/tools/pmc_fulltext_search",
                    json={"query": query, "max_results": 5},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                articles = data.get("result", {}).get("articles", [])

                evidence = []
                for art in articles:
                    fulltext = art.get("body", art.get("abstract", ""))
                    if not fulltext:
                        continue

                    # More precise matching in full text
                    site_pattern = re.compile(
                        rf"\b{re.escape(protein)}.*?{re.escape(site)}\b",
                        re.IGNORECASE,
                    )
                    matches = site_pattern.findall(fulltext)

                    if matches:
                        ab_info = extract_antibody_info(fulltext, protein)
                        snippet = matches[0][:200] if matches else ""

                        ev = PTMEvidence(
                            source="pmc",
                            protein=protein,
                            site=site,
                            ptm_type=ptm_type,
                            pmid=art.get("pmid", ""),
                            title=art.get("title", ""),
                            snippet=snippet,
                            confidence=0.9,  # Full-text match is high confidence
                            antibody_info=ab_info,
                            year=art.get("year", ""),
                        )
                        evidence.append(ev)

                return evidence

        except Exception as e:
            logger.warning(f"PMC search failed for {protein} {site}: {e}")
            return []

    async def _search_iptmnet(
        self, protein: str, site: str, ptm_type: str,
    ) -> List[PTMEvidence]:
        """Search iPTMnet for known PTM annotations."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.mcp_url}/tools/iptmnet_search",
                    json={"query": protein, "ptm_type": ptm_type},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                entries = data.get("result", {}).get("entries", [])

                evidence = []
                for entry in entries:
                    entry_site = entry.get("site", "")
                    # Check for exact or nearby site match
                    if self._sites_match(site, entry_site):
                        ev = PTMEvidence(
                            source="iptmnet",
                            protein=protein,
                            site=site,
                            ptm_type=ptm_type,
                            title=f"iPTMnet: {entry.get('substrate', protein)} {entry_site}",
                            snippet=(
                                f"Enzyme: {entry.get('enzyme', 'N/A')}, "
                                f"Score: {entry.get('score', 'N/A')}"
                            ),
                            confidence=0.95,  # Database annotation is high confidence
                        )
                        evidence.append(ev)

                return evidence

        except Exception as e:
            logger.warning(f"iPTMnet search failed for {protein} {site}: {e}")
            return []

    # -----------------------------------------------------------------------
    # Helper methods
    # -----------------------------------------------------------------------

    @staticmethod
    def _sites_match(query_site: str, db_site: str) -> bool:
        """
        Check if two PTM sites match.
        Handles formats: S473, Ser473, pS473, phospho-Ser473
        Also allows nearby positions (within ±2 residues) for fuzzy matching.
        """
        def _parse_site(s: str):
            m = re.match(r"(?:p(?:hospho)?-?)?\s*([STY](?:er|hr|yr)?)\s*(\d+)", s, re.IGNORECASE)
            if m:
                aa = m.group(1)[0].upper()
                pos = int(m.group(2))
                return aa, pos
            return None, None

        q_aa, q_pos = _parse_site(query_site)
        d_aa, d_pos = _parse_site(db_site)

        if q_aa is None or d_aa is None:
            return query_site.lower() == db_site.lower()

        # Exact match
        if q_aa == d_aa and q_pos == d_pos:
            return True

        # Fuzzy match: same amino acid, position within ±2
        if q_aa == d_aa and abs(q_pos - d_pos) <= 2:
            return True

        return False

    @staticmethod
    def _calculate_novelty(result: CrossSiteResult) -> float:
        """
        Calculate novelty score (1.0 = novel, 0.0 = well-known).

        Based on:
          - Number of evidence sources
          - Database types (iPTMnet > PubMed > PMC)
          - Confidence of evidence
        """
        if not result.evidence:
            return 1.0  # No evidence = novel

        # Weight by source reliability
        source_weights = {
            "iptmnet": 0.3,
            "pubmed": 0.2,
            "pmc": 0.15,
            "uniprot": 0.3,
        }

        known_score = 0.0
        for ev in result.evidence:
            weight = source_weights.get(ev.source, 0.1)
            known_score += weight * ev.confidence

        # Cap at 1.0
        known_score = min(known_score, 1.0)

        return round(1.0 - known_score, 3)

    @staticmethod
    def _generate_summary(result: CrossSiteResult) -> str:
        """Generate a human-readable summary of cross-site search results."""
        if not result.evidence:
            return (
                f"**Novel PTM**: {result.protein} {result.site} ({result.ptm_type}) — "
                f"No prior reports found in PubMed, PMC, or iPTMnet databases."
            )

        sources = ", ".join(result.databases_found)
        summary = (
            f"**Known PTM**: {result.protein} {result.site} ({result.ptm_type}) — "
            f"Found in {result.evidence_count} source(s) ({sources}). "
            f"Novelty score: {result.novelty_score:.2f}."
        )

        if result.antibody_validated:
            summary += " Antibody validation evidence available."

        # Top evidence
        top = sorted(result.evidence, key=lambda e: e.confidence, reverse=True)[:3]
        for ev in top:
            if ev.title:
                summary += f"\n  - [{ev.source}] {ev.title[:80]}"

        return summary
