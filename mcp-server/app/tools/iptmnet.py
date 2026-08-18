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
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Organism → UniProt AC mapping for known proteins
KNOWN_UNIPROT_AC: Dict[str, Dict[str, str]] = {
    "Mouse": {
        "Thrap3": "Q569Z6", "Vcan": "Q62059", "A2m": "Q61838",
        "Tns1": "Q8BYW7", "Bin1": "O08539", "Gorasp2": "Q9CWW6",
        "Rbm39": "Q8VH51",
        "Egfr": "Q01279", "Mapk1": "P63085", "Mapk3": "Q63844",
        "Akt1": "P31750", "Src": "P05480", "Stat3": "P42227",
        "Tp53": "P02340", "Myc": "P09416", "Jun": "P05627",
        "Fos": "P01101", "Rb1": "P13405",
    },
    "Human": {
        "THRAP3": "Q9Y2W1", "VCAN": "P13611", "A2M": "P01023",
        "EGFR": "P00533", "MAPK1": "P28482", "MAPK3": "P27361",
        "AKT1": "P31749", "SRC": "P12931", "STAT3": "P40763",
        "TP53": "P04637", "MYC": "P01106", "JUN": "P05412",
        "FOS": "P01100", "RB1": "P06400",
    },
    "Rat": {
        # Common proteins with curated UniProt ACs to skip slow API search
        "THRAP3": "Q5XIF4", "VCAN": "Q9ERB4", "A2M": "P06238",
        "TNS1": "D3ZYM7", "BIN1": "O08838",
        # Kinases / signalling proteins frequently studied in rat
        "Egfr": "P06803", "EGFR": "P06803",
        "Mapk1": "P63086", "MAPK1": "P63086",  # ERK2
        "Mapk3": "Q63844", "MAPK3": "Q63844",  # ERK1
        "Akt1": "P47196", "AKT1": "P47196",
        "Src": "P00523", "SRC": "P00523",
        "Stat3": "P52631", "STAT3": "P52631",
        "Tp53": "P10361", "TP53": "P10361",
        "Myc": "P09416", "MYC": "P09416",
        "Jun": "P17325", "JUN": "P17325",
        "Fos": "P13325", "FOS": "P13325",
        "Rb1": "Q9Z1N4", "RB1": "Q9Z1N4",
        # Cardiac / metabolic
        "Tnnt2": "P23693", "TNNT2": "P23693",
        "Prkaa1": "Q9Z1M7", "PRKAA1": "Q9Z1M7",   # AMPK α1
        "Prkaa2": "Q9Z1M6", "PRKAA2": "Q9Z1M6",   # AMPK α2
        "Mtor": "P42346", "MTOR": "P42346",
        "Pik3ca": "Q9Z1U3", "PIK3CA": "Q9Z1U3",
        "Pten": "O54724", "PTEN": "O54724",
        "Gsk3b": "P18265", "GSK3B": "P18265",
        "Cdkn1a": "Q63318", "CDKN1A": "Q63318",   # p21
        "Cdkn2a": "Q9Z1B9", "CDKN2A": "Q9Z1B9",   # p16
        "Hif1a": "Q9Z2A9", "HIF1A": "Q9Z2A9",
        "Nfkb1": "Q63100", "NFKB1": "Q63100",
        "Rela": "Q63318", "RELA": "Q63318",
        "Mapk14": "Q9Z1B5", "MAPK14": "Q9Z1B5",   # p38 MAPK
        "Mapk8": "Q9WTU6", "MAPK8": "Q9WTU6",     # JNK1
    },
}

IPTMNET_BASE = "https://research.bioinformatics.udel.edu/iptmnet"
ENSEMBL_REST_BASE = "https://rest.ensembl.org"
IPTMNET_HTTP_TIMEOUT_SECONDS = 20
IPTMNET_MAX_RETRIES = 3
IPTMNET_SUCCESS_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
IPTMNET_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _canonical_iptmnet_organism(organism: str) -> str:
    """Normalize FASTA/pipeline species labels to iPTMnet's organism keys."""
    value = str(organism or "").strip()
    lower = value.lower()
    if "rat" in lower or "rattus" in lower:
        return "Rat"
    if "human" in lower or "homo" in lower:
        return "Human"
    if "mouse" in lower or "mus musculus" in lower:
        return "Mouse"
    return value or "Mouse"


def _ensembl_native_species(organism: str) -> str:
    """Return the Ensembl source-species alias eligible for human fallback."""
    canonical = _canonical_iptmnet_organism(organism)
    return {
        "Rat": "rattus_norvegicus",
        "Mouse": "mus_musculus",
    }.get(canonical, "")

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


def _split_site(position: str) -> tuple[str, int] | None:
    """Return normalized residue and one-based coordinate for a PTM site label."""
    match = re.fullmatch(r"\s*([A-Za-z])(\d+)\s*", str(position or ""))
    if not match:
        return None
    return match.group(1).upper(), int(match.group(2))


def map_conserved_human_site(homology_payload: dict, rat_position: str) -> dict:
    """Map a rat site to a human one-to-one ortholog only when the residue aligns.

    Ensembl Compara returns aligned source and target protein strings.  This helper
    intentionally rejects non-one-to-one orthology, gaps, changed residues, and
    malformed alignment data instead of guessing from shared gene symbols.
    """
    parsed_site = _split_site(rat_position)
    if not parsed_site:
        return {"status": "unavailable_or_unaligned", "reason_code": "invalid_rat_site"}
    rat_residue, rat_index = parsed_site
    homologies = []
    for record in homology_payload.get("data", []) if isinstance(homology_payload, dict) else []:
        if isinstance(record, dict):
            homologies.extend(record.get("homologies") or [])

    candidates = [
        item for item in homologies
        if isinstance(item, dict)
        and str(item.get("type") or "").lower() == "ortholog_one2one"
        and str((item.get("target") or {}).get("species") or "").lower() == "homo_sapiens"
    ]
    if len(candidates) != 1:
        return {
            "status": "unavailable_or_unaligned",
            "reason_code": "human_one_to_one_ortholog_unresolved",
            "candidate_count": len(candidates),
        }

    target = candidates[0].get("target") or {}
    source = candidates[0].get("source") or {}
    rat_alignment = str(source.get("align_seq") or "")
    human_alignment = str(target.get("align_seq") or "")
    if not rat_alignment or len(rat_alignment) != len(human_alignment):
        return {"status": "unavailable_or_unaligned", "reason_code": "protein_alignment_unavailable"}

    rat_seen = 0
    human_seen = 0
    for rat_aa, human_aa in zip(rat_alignment, human_alignment):
        if rat_aa != "-":
            rat_seen += 1
        if human_aa != "-":
            human_seen += 1
        if rat_seen != rat_index:
            continue
        if rat_aa.upper() != rat_residue:
            return {"status": "unavailable_or_unaligned", "reason_code": "rat_reference_residue_mismatch"}
        if human_aa == "-":
            return {"status": "unavailable_or_unaligned", "reason_code": "human_alignment_gap"}
        if human_aa.upper() != rat_residue:
            return {
                "status": "unavailable_or_unaligned",
                "reason_code": "residue_not_conserved",
                "human_residue": human_aa.upper(),
                "human_position": human_seen,
            }
        return {
            "status": "aligned_conserved",
            "reason_code": "one_to_one_aligned_residue",
            "human_position": human_seen,
            "human_site": f"{human_aa.upper()}{human_seen}",
            "human_gene_id": str(target.get("id") or ""),
            "human_protein_id": str(target.get("protein_id") or ""),
            "orthology_type": str(candidates[0].get("type") or ""),
            "alignment_source": "Ensembl Compara",
        }
    return {"status": "unavailable_or_unaligned", "reason_code": "rat_site_outside_alignment"}


async def _fetch_ensembl_json(
    session: aiohttp.ClientSession, path: str, params: Optional[dict] = None,
) -> Optional[dict]:
    """Fetch one bounded JSON response from Ensembl without blocking direct evidence."""
    try:
        async with session.get(
            f"{ENSEMBL_REST_BASE}{path}",
            params=params or {},
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=12),
        ) as response:
            if response.status != 200:
                return None
            payload = await response.json(content_type=None)
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

async def _fetch_iptmnet_page(
    session: aiohttp.ClientSession, url: str,
) -> tuple[Optional[str], Optional[str]]:
    """Fetch one iPTMnet page with bounded retries and a machine-readable reason.

    A direct PTM record is never inferred from a failed public-web request.  The
    caller receives both the response body and an explicit failure category so
    it can distinguish a real empty lookup from an unavailable source.
    """
    failure_reason: Optional[str] = None
    for attempt in range(IPTMNET_MAX_RETRIES):
        try:
            async with session.get(
                url,
                headers={"User-Agent": "PTM-Platform/1.0 (+structured-PTM-evidence)"},
                timeout=aiohttp.ClientTimeout(total=IPTMNET_HTTP_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status == 200:
                    return await resp.text(), None
                failure_reason = f"http_{resp.status}"
                if resp.status not in IPTMNET_RETRYABLE_HTTP_STATUS:
                    return None, failure_reason
        except asyncio.TimeoutError:
            failure_reason = "timeout"
        except aiohttp.ClientError:
            failure_reason = "network_error"
        except Exception:
            failure_reason = "unexpected_client_error"

        if attempt < IPTMNET_MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
    return None, failure_reason or "response_unavailable"


def _extract_iptmnet_entry_urls(html: str) -> List[str]:
    """Return unique absolute entry URLs from a current iPTMnet search page."""
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    for link in soup.find_all("a", href=re.compile(r"/entry/")):
        href = str(link.get("href") or "")
        absolute_url = urljoin(f"{IPTMNET_BASE}/", href)
        if absolute_url not in urls:
            urls.append(absolute_url)
    return urls


async def _search_iptmnet_by_gene(
    session: aiohttp.ClientSession, gene: str,
) -> tuple[Optional[str], Optional[str]]:
    """Submit iPTMnet's CSRF-protected current gene-search form.

    The prior GET `/search?...` endpoint is no longer served by iPTMnet.  The
    public site now requires a bootstrap GET for the CSRF token followed by a
    form POST to `/handle/`; aiohttp retains the response cookies in session.
    """
    landing_html, landing_failure = await _fetch_iptmnet_page(
        session, f"{IPTMNET_BASE}/"
    )
    if not landing_html:
        return None, f"search_form_{landing_failure or 'unavailable'}"

    landing_soup = BeautifulSoup(landing_html, "html.parser")
    csrf_input = landing_soup.find("input", attrs={"name": "csrfmiddlewaretoken"})
    csrf_token = str(csrf_input.get("value") or "") if csrf_input else ""
    if not csrf_token:
        return None, "search_form_csrf_missing"

    failure_reason: Optional[str] = None
    for attempt in range(IPTMNET_MAX_RETRIES):
        try:
            async with session.post(
                f"{IPTMNET_BASE}/handle/",
                data={
                    "csrfmiddlewaretoken": csrf_token,
                    "searchCriteria": "name",
                    "searchQuery": gene,
                },
                headers={
                    "Referer": f"{IPTMNET_BASE}/",
                    "User-Agent": "PTM-Platform/1.0 (+structured-PTM-evidence)",
                },
                timeout=aiohttp.ClientTimeout(total=IPTMNET_HTTP_TIMEOUT_SECONDS),
            ) as response:
                if response.status == 200:
                    return await response.text(), None
                failure_reason = f"search_post_http_{response.status}"
                if response.status not in IPTMNET_RETRYABLE_HTTP_STATUS:
                    return None, failure_reason
        except asyncio.TimeoutError:
            failure_reason = "search_post_timeout"
        except aiohttp.ClientError:
            failure_reason = "search_post_network_error"
        except Exception:
            failure_reason = "search_post_unexpected_client_error"

        if attempt < IPTMNET_MAX_RETRIES - 1:
            await asyncio.sleep(2 ** attempt)
    return None, failure_reason or "search_post_unavailable"


def _parse_sites_from_html(html: str, target_position: str) -> List[IPTMnetSite]:
    """Parse iPTMnet PTM entry tables to find matching PTM sites.

    iPTMnet's live entry pages prefix each row with a checkbox column.  Column
    positions must therefore be resolved from table headers rather than assumed
    from an older site-first table layout.
    """
    soup = BeautifulSoup(html, "html.parser")
    sites: List[IPTMnetSite] = []

    tables = soup.find_all("table")
    if not tables:
        return sites

    target_site = _split_site(target_position)
    if not target_site:
        return sites
    target_aa, target_num = target_site
    aa_names = "|".join(re.escape(name) for name in AA_MAP.get(target_aa, []))
    residue_pattern = rf"(?:{target_aa}|{aa_names})\s*-?\s*{target_num}(?!\d)"
    site_pattern = re.compile(residue_pattern, re.IGNORECASE)

    def header_index(headers: List[str], *aliases: str) -> Optional[int]:
        aliases_lower = {alias.lower() for alias in aliases}
        for index, header in enumerate(headers):
            normalized = " ".join(header.lower().split())
            if normalized in aliases_lower:
                return index
        return None

    for table in tables:
        header_cells = table.select("thead tr th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all("th", recursive=False) if first_row else []
        headers = [cell.get_text(" ", strip=True) for cell in header_cells]
        site_index = header_index(headers, "site", "sites")
        ptm_type_index = header_index(headers, "ptm type", "type")
        source_index = header_index(headers, "source", "sources")
        pmid_index = header_index(headers, "pmid", "pmids")
        enzyme_index = header_index(headers, "ptm enzyme", "enzyme")
        if site_index is None or ptm_type_index is None or source_index is None:
            continue

        rows = table.select("tbody tr") or table.find_all("tr")
        for row in rows:
            cols = row.find_all("td", recursive=False)
            if len(cols) <= max(site_index, ptm_type_index, source_index):
                continue

            site_text = cols[site_index].get_text(" ", strip=True)
            if not site_pattern.search(site_text):
                continue

            ptm_type = cols[ptm_type_index].get_text(" ", strip=True)
            source_cell = cols[source_index]
            sources = list(dict.fromkeys(
                link.get_text(" ", strip=True)
                for link in source_cell.find_all("a")
                if link.get_text(" ", strip=True)
            ))
            if not sources:
                source_text = source_cell.get_text(" ", strip=True)
                sources = [source_text] if source_text else []

            pmid_links = (
                cols[pmid_index].find_all("a")
                if pmid_index is not None and len(cols) > pmid_index
                else []
            )
            pmids = [a.get_text(strip=True) for a in pmid_links if a.get_text(strip=True).isdigit()]

            enzyme_id, enzyme_name = "", ""
            if enzyme_index is not None and len(cols) > enzyme_index:
                enzyme_link = cols[enzyme_index].find("a")
                if enzyme_link:
                    enzyme_id = enzyme_link.get("href", "").split("/")[-1]
                    enzyme_name = enzyme_link.get_text(" ", strip=True)

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
    organism = _canonical_iptmnet_organism(organism)
    cache_key = f"iptmnet:{gene}:{position}:{organism}"
    if redis:
        try:
            import json as _json
            cached = await redis.get(cache_key)
            if cached:
                cached_payload = _json.loads(cached)
                if cached_payload.get("query_status") in {"hit", "empty"}:
                    cached_payload["cache_status"] = "success_cache_hit"
                    return cached_payload
                # Older worker versions could store source failures permanently.
                # Delete them so a transient outage never becomes a false site gap.
                await redis.delete(cache_key)
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
        "query_status": "",
        "error": None,
        "failure_reasons": [],
        "cache_status": "live_query",
    }
    fetched_any_page = False
    parse_failures: List[str] = []
    request_failures: List[str] = []

    async with aiohttp.ClientSession() as session:
        # Strategy 1: Direct UniProt AC lookup
        if uniprot_ac:
            url = f"{IPTMNET_BASE}/entry/{uniprot_ac}"
            html, failure_reason = await _fetch_iptmnet_page(session, url)
            if html:
                fetched_any_page = True
                if not BeautifulSoup(html, "html.parser").find_all("table"):
                    parse_failures.append("entry_schema_missing")
                sites = _parse_sites_from_html(html, position)
                if sites:
                    novelty = _assess_novelty(sites)
                    result["novelty"] = novelty.to_dict()
                    result["sites_found"] = len(sites)
                    result["query_status"] = "hit"

                    if redis:
                        try:
                            import json as _json
                            await redis.set(
                                cache_key, _json.dumps(result),
                                ex=IPTMNET_SUCCESS_CACHE_TTL_SECONDS,
                            )
                        except Exception:
                            pass
                    return result
            elif failure_reason:
                request_failures.append(f"direct_entry_{failure_reason}")

        # Strategy 2: Current iPTMnet CSRF-protected gene search.
        html, failure_reason = await _search_iptmnet_by_gene(session, gene)
        if html:
            fetched_any_page = True
            for entry_url in _extract_iptmnet_entry_urls(html)[:3]:
                entry_html, entry_failure_reason = await _fetch_iptmnet_page(session, entry_url)
                if entry_html:
                    fetched_any_page = True
                    if not BeautifulSoup(entry_html, "html.parser").find_all("table"):
                        parse_failures.append("entry_schema_missing")
                    sites = _parse_sites_from_html(entry_html, position)
                    if sites:
                        novelty = _assess_novelty(sites)
                        result["novelty"] = novelty.to_dict()
                        result["sites_found"] = len(sites)
                        result["query_status"] = "hit"
                        break
                elif entry_failure_reason:
                    request_failures.append(f"search_entry_{entry_failure_reason}")
        elif failure_reason:
            request_failures.append(f"gene_search_{failure_reason}")

        if result["novelty"] is None:
            failure_reasons = list(dict.fromkeys(request_failures + parse_failures))
            result["failure_reasons"] = failure_reasons
            if fetched_any_page and not parse_failures:
                result["novelty"] = PTMNoveltyResult(
                    status="NOVEL", score=0, source_count=0,
                    sources=[], pmid_count=0, pmids=[],
                ).to_dict()
                result["query_status"] = "empty"
            else:
                result["novelty"] = PTMNoveltyResult(
                    status="UNKNOWN", score=0, source_count=0,
                    sources=[], pmid_count=0, pmids=[],
                ).to_dict()
                result["query_status"] = "error"
                result["error"] = "iPTMnet response unavailable or unparseable"

    if redis and result["query_status"] in {"hit", "empty"}:
        try:
            import json as _json
            await redis.set(
                cache_key, _json.dumps(result),
                ex=IPTMNET_SUCCESS_CACHE_TTL_SECONDS,
            )
        except Exception:
            pass

    return result


async def query_human_ortholog_iptmnet(
    gene: str,
    position: str,
    organism: str = "Rat",
    redis=None,
) -> dict:
    """Return human support only for an aligned conserved native rodent residue.

    This endpoint is deliberately additive.  It does not query or replace the
    direct rat record, and a result with no human hit remains an evidence gap.
    """
    result: dict = {
        "provenance": "unavailable_or_unaligned",
        "query_status": "not_attempted",
        "source_species": organism,
        "target_species": "Human",
        "native_gene": gene,
        "native_site": position,
        "human_gene": "",
        "human_site": "",
        "residue_conserved": False,
        "orthology_type": "",
        "alignment_source": "Ensembl Compara",
        "human_iptmnet": None,
        "reason_code": "native_species_not_supported_for_fallback",
        "error": None,
    }
    native_ensembl_species = _ensembl_native_species(organism)
    if not native_ensembl_species:
        return result

    cache_key = f"iptmnet:human_ortholog:{native_ensembl_species}:{gene}:{position}"
    if redis:
        try:
            import json as _json
            cached = await redis.get(cache_key)
            if cached:
                return _json.loads(cached)
        except Exception:
            pass

    async with aiohttp.ClientSession() as session:
        homology = await _fetch_ensembl_json(
            session,
            f"/homology/symbol/{native_ensembl_species}/{gene}",
            {
                "target_species": "homo_sapiens",
                "type": "orthologues",
                "sequence": "protein",
                "aligned": "1",
            },
        )
        if homology is None:
            result.update({"provenance": "source_error", "query_status": "error", "reason_code": "ensembl_unavailable", "error": "Ensembl homology response unavailable"})
            return result

        mapping = map_conserved_human_site(homology, position)
        if mapping.get("status") != "aligned_conserved":
            result.update(mapping)
            return result

        human_gene_id = str(mapping.get("human_gene_id") or "")
        lookup = await _fetch_ensembl_json(session, f"/lookup/id/{human_gene_id}") if human_gene_id else None
        human_gene = str((lookup or {}).get("display_name") or "")
        if not human_gene:
            result.update({"reason_code": "human_gene_symbol_unresolved", "human_site": mapping.get("human_site") or ""})
            return result

    human_site = str(mapping["human_site"])
    human_result = await query_iptmnet(human_gene, human_site, organism="Human", redis=redis)
    if human_result.get("query_status") == "error" or human_result.get("error"):
        result.update({
            **mapping,
            "provenance": "source_error",
            "query_status": "error",
            "human_gene": human_gene,
            "human_site": human_site,
            "residue_conserved": True,
            "human_iptmnet": human_result,
            "reason_code": "human_iptmnet_unavailable",
            "error": human_result.get("error") or "human iPTMnet response unavailable",
        })
        return result
    if int(human_result.get("sites_found") or 0) <= 0:
        result.update({
            **mapping,
            "query_status": "empty",
            "human_gene": human_gene,
            "human_site": human_site,
            "residue_conserved": True,
            "human_iptmnet": human_result,
            "reason_code": "human_conserved_site_not_curated",
        })
        return result

    result.update({
        **mapping,
        "provenance": "inferred_cross_species",
        "query_status": "hit",
        "human_gene": human_gene,
        "human_site": human_site,
        "residue_conserved": True,
        "human_iptmnet": human_result,
        "reason_code": "human_curated_at_aligned_conserved_site",
    })
    if redis:
        try:
            import json as _json
            await redis.set(cache_key, _json.dumps(result))
        except Exception:
            pass
    return result
