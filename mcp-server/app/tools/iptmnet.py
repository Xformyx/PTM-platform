"""
iPTMnet Client — PTM novelty assessment via iPTMnet web scraping.

Ported from ptm-rag-backend/src/iptmnetClient.ts (v3.5.2).

Novelty criteria (v3.5.2):
  - Any site with ≥1 source → KNOWN
  - 0 sources → NOVEL
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Organism → UniProt AC mapping for known proteins
KNOWN_UNIPROT_AC: Dict[str, Dict[str, str]] = {
    "Mouse": {
        "Thrap3": "Q569Z6", "Vcan": "Q62059", "A2m": "Q61838",
        "Tns1": "Q8BYW7", "Bin1": "O08539", "Gorasp2": "Q9CWW6",
        "Rbm39": "Q8VH51",
    },
    "Human": {
        "THRAP3": "Q9Y2W1", "VCAN": "P13611", "A2M": "P01023",
    },
}

IPTMNET_BASE = "https://research.bioinformatics.udel.edu/iptmnet"

# Amino acid name mapping
AA_MAP: Dict[str, List[str]] = {
    "S": ["Ser", "serine"], "T": ["Thr", "threonine"], "Y": ["Tyr", "tyrosine"],
    "K": ["Lys", "lysine"], "R": ["Arg", "arginine"],
    "D": ["Asp", "aspartate"], "E": ["Glu", "glutamate"],
    "N": ["Asn", "asparagine"], "Q": ["Gln", "glutamine"],
    "H": ["His", "histidine"], "C": ["Cys", "cysteine"],
    "M": ["Met", "methionine"], "A": ["Ala", "alanine"],
    "V": ["Val", "valine"], "L": ["Leu", "leucine"],
    "I": ["Ile", "isoleucine"], "F": ["Phe", "phenylalanine"],
    "W": ["Trp", "tryptophan"], "P": ["Pro", "proline"],
    "G": ["Gly", "glycine"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class IPTMnetSite:
    __slots__ = ("site", "ptm_type", "sources", "pmids", "enzyme_id", "enzyme_name")

    def __init__(self, site: str, ptm_type: str, sources: List[str],
                 pmids: List[str], enzyme_id: str = "", enzyme_name: str = ""):
        self.site = site
        self.ptm_type = ptm_type
        self.sources = sources
        self.pmids = pmids
        self.enzyme_id = enzyme_id
        self.enzyme_name = enzyme_name


class PTMNoveltyResult:
    def __init__(self, status: str, score: int, source_count: int,
                 sources: List[str], pmid_count: int, pmids: List[str],
                 enzyme_id: str = "", enzyme_name: str = "",
                 site_contexts: Optional[List[str]] = None):
        self.status = status
        self.score = score
        self.source_count = source_count
        self.sources = sources
        self.pmid_count = pmid_count
        self.pmids = pmids
        self.enzyme_id = enzyme_id
        self.enzyme_name = enzyme_name
        self.site_contexts = site_contexts or []

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "score": self.score,
            "source_count": self.source_count,
            "sources": self.sources,
            "pmid_count": self.pmid_count,
            "pmids": self.pmids,
            "enzyme": {"id": self.enzyme_id, "name": self.enzyme_name}
            if self.enzyme_id else None,
            "site_contexts": self.site_contexts,
        }


# ---------------------------------------------------------------------------
# Position variant generation (v3.7.2)
# ---------------------------------------------------------------------------

def _generate_position_variants(position: str) -> List[str]:
    """Generate comprehensive position variants for site matching."""
    variants = [position]
    m = re.match(r"^([A-Z])(\d+)$", position, re.IGNORECASE)
    if not m:
        return variants

    aa, num = m.group(1).upper(), m.group(2)
    names = AA_MAP.get(aa, [])

    for name in names:
        for fmt in (
            f"{name}{num}", f"{name}-{num}", f"{name} {num}",
            f"{name.lower()}{num}", f"{name.lower()}-{num}",
            f"phospho-{name}{num}", f"phospho{name}{num}",
            f"p{name}{num}", f"p-{name}{num}",
            f"at {name}{num}", f"at {name} {num}",
        ):
            variants.append(fmt)

    variants.extend([
        f"{aa}{num}", f"{aa}-{num}", f"p{aa}{num}",
        f"residue {num}", f"position {num}", f"site {num}",
    ])
    return variants


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

async def _fetch_iptmnet_page(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Fetch a page from iPTMnet with timeout and retry."""
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
        except Exception:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
    return None


def _parse_sites_from_html(html: str, target_position: str) -> List[IPTMnetSite]:
    """Parse iPTMnet HTML table to find matching PTM sites."""
    soup = BeautifulSoup(html, "html.parser")
    sites: List[IPTMnetSite] = []

    tables = soup.find_all("table")
    if not tables:
        return sites

    target_num = re.search(r"\d+", target_position)
    if not target_num:
        return sites
    target_num_str = target_num.group()

    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cols = row.find_all("td")
            if len(cols) < 4:
                continue

            site_text = cols[0].get_text(strip=True)
            if target_num_str not in site_text:
                continue

            ptm_type = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            source_text = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            sources = [s.strip() for s in source_text.split(",") if s.strip()]

            pmid_links = cols[3].find_all("a") if len(cols) > 3 else []
            pmids = [a.get_text(strip=True) for a in pmid_links if a.get_text(strip=True).isdigit()]

            enzyme_id, enzyme_name = "", ""
            if len(cols) > 4:
                enzyme_link = cols[4].find("a")
                if enzyme_link:
                    enzyme_id = enzyme_link.get("href", "").split("/")[-1]
                    enzyme_name = enzyme_link.get_text(strip=True)

            sites.append(IPTMnetSite(
                site=site_text, ptm_type=ptm_type, sources=sources,
                pmids=pmids, enzyme_id=enzyme_id, enzyme_name=enzyme_name,
            ))

    return sites


def _assess_novelty(sites: List[IPTMnetSite]) -> PTMNoveltyResult:
    """Assess PTM novelty based on iPTMnet data (v3.5.2 criteria)."""
    if not sites:
        return PTMNoveltyResult(
            status="NOVEL", score=0, source_count=0,
            sources=[], pmid_count=0, pmids=[],
        )

    all_sources: List[str] = []
    all_pmids: List[str] = []
    enzyme_id, enzyme_name = "", ""

    for site in sites:
        all_sources.extend(site.sources)
        all_pmids.extend(site.pmids)
        if site.enzyme_id and not enzyme_id:
            enzyme_id = site.enzyme_id
            enzyme_name = site.enzyme_name

    unique_sources = list(set(all_sources))
    unique_pmids = list(set(all_pmids))
    source_count = len(unique_sources)
    pmid_count = len(unique_pmids)

    # v3.5.2: ≥1 source = KNOWN
    if source_count >= 5:
        status, score = "EXTENSIVELY-STUDIED", 100
    elif source_count >= 3:
        status, score = "WELL-CHARACTERIZED", 80
    elif source_count >= 2:
        status, score = "MODERATE", 60
    elif source_count >= 1:
        status, score = "LOW", 40
    else:
        status, score = "NOVEL", 0

    return PTMNoveltyResult(
        status=status, score=score, source_count=source_count,
        sources=unique_sources, pmid_count=pmid_count, pmids=unique_pmids,
        enzyme_id=enzyme_id, enzyme_name=enzyme_name,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def query_iptmnet(
    gene: str,
    position: str,
    organism: str = "Mouse",
    redis=None,
) -> dict:
    """
    Query iPTMnet for PTM novelty assessment.

    Returns dict with keys: gene, position, novelty, sites_found, error.
    """
    cache_key = f"iptmnet:{gene}:{position}:{organism}"
    if redis:
        try:
            import json as _json
            cached = await redis.get(cache_key)
            if cached:
                return _json.loads(cached)
        except Exception:
            pass

    # Resolve UniProt AC
    uniprot_ac = (KNOWN_UNIPROT_AC.get(organism, {}).get(gene) or
                  KNOWN_UNIPROT_AC.get(organism, {}).get(gene.capitalize()))

    result: dict = {
        "gene": gene,
        "position": position,
        "organism": organism,
        "novelty": None,
        "sites_found": 0,
        "error": None,
    }

    async with aiohttp.ClientSession() as session:
        # Strategy 1: Direct UniProt AC lookup
        if uniprot_ac:
            url = f"{IPTMNET_BASE}/entry/{uniprot_ac}"
            html = await _fetch_iptmnet_page(session, url)
            if html:
                sites = _parse_sites_from_html(html, position)
                if sites:
                    novelty = _assess_novelty(sites)
                    result["novelty"] = novelty.to_dict()
                    result["sites_found"] = len(sites)

                    if redis:
                        try:
                            import json as _json
                            await redis.set(cache_key, _json.dumps(result), ex=86400)
                        except Exception:
                            pass
                    return result

        # Strategy 2: Search by gene name
        search_url = f"{IPTMNET_BASE}/search?search_term={gene}&organism={organism}"
        html = await _fetch_iptmnet_page(session, search_url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            entry_links = soup.find_all("a", href=re.compile(r"/entry/"))
            for link in entry_links[:3]:
                entry_url = f"{IPTMNET_BASE}{link['href']}"
                entry_html = await _fetch_iptmnet_page(session, entry_url)
                if entry_html:
                    sites = _parse_sites_from_html(entry_html, position)
                    if sites:
                        novelty = _assess_novelty(sites)
                        result["novelty"] = novelty.to_dict()
                        result["sites_found"] = len(sites)
                        break

        if result["novelty"] is None:
            result["novelty"] = PTMNoveltyResult(
                status="NOVEL", score=0, source_count=0,
                sources=[], pmid_count=0, pmids=[],
            ).to_dict()

    if redis:
        try:
            import json as _json
            await redis.set(cache_key, _json.dumps(result), ex=86400)
        except Exception:
            pass

    return result
