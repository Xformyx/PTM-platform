"""
Reactome Kinase → Receptor reverse-lookup with Redis caching.

Flow:
  1. gene_name → Reactome search → entity stId
  2. stId → low-level pathways
  3. pathway → ancestor hierarchy → extract receptor names from "Signaling by {RECEPTOR}" pattern
  4. Cache results in Redis (TTL 90 days)
"""

import asyncio
import json
import logging
import re
from datetime import timedelta
from typing import Optional

import httpx

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REACTOME_BASE = "https://reactome.org/ContentService"
CACHE_PREFIX = "reactome:kinase_receptors"
CACHE_TTL = timedelta(days=90)

# Species mapping: NCBI taxonomy ID and Reactome species name
_SPECIES_MAP: dict[str, dict] = {
    "human": {"tax_id": 9606, "name": "Homo sapiens"},
    "homo": {"tax_id": 9606, "name": "Homo sapiens"},
    "mouse": {"tax_id": 10090, "name": "Mus musculus"},
    "mus": {"tax_id": 10090, "name": "Mus musculus"},
    "rat": {"tax_id": 10116, "name": "Rattus norvegicus"},
    "rattus": {"tax_id": 10116, "name": "Rattus norvegicus"},
}


def _resolve_species(species: str) -> tuple[int, str]:
    """Resolve species string to (tax_id, reactome_species_name).

    Defaults to Homo sapiens (9606) if species is empty or unrecognized.
    """
    if not species:
        return 9606, "Homo sapiens"
    sp_lower = species.lower()
    for key, info in _SPECIES_MAP.items():
        if key in sp_lower:
            return info["tax_id"], info["name"]
    # Default: Homo sapiens
    return 9606, "Homo sapiens"


# Patterns to extract receptor names from pathway hierarchy
# e.g. "Signaling by EGFR", "Signaling by NTRK2 (TRKB)"
_SIGNALING_BY_RE = re.compile(
    r"^Signaling by (.+)$", re.IGNORECASE
)

# Generic top-level categories to skip (not specific receptors)
_SKIP_NAMES = {
    "receptor tyrosine kinases",
    "nuclear receptors",
    "interleukins",
    "wnt",
    "notch",
    "hedgehog",
    "gpcrs, class a rhodopsin-like",
    "gpcrs, class b secretin-like",
    "gpcrs, class c metabotropic glutamate",
}

# Receptor class inference from pathway name keywords
_RECEPTOR_CLASS_RULES = [
    (re.compile(r"EGFR|ERBB|HER\d", re.I), "RTK"),
    (re.compile(r"FGFR\d?", re.I), "RTK"),
    (re.compile(r"VEGFR|KDR|FLT", re.I), "RTK"),
    (re.compile(r"PDGFR", re.I), "RTK"),
    (re.compile(r"INSR|IGF1R|Insulin", re.I), "RTK"),
    (re.compile(r"NTRK\d|TRK[A-C]|NGF|BDNF", re.I), "RTK"),
    (re.compile(r"MET|HGFR", re.I), "RTK"),
    (re.compile(r"ALK", re.I), "RTK"),
    (re.compile(r"RET", re.I), "RTK"),
    (re.compile(r"KIT|SCF", re.I), "RTK"),
    (re.compile(r"Integrin|ITGA|ITGB", re.I), "Integrin"),
    (re.compile(r"TGF.?[Bb]|TGFBR|BMP|BMPR|Activin", re.I), "TGFβ"),
    (re.compile(r"Notch", re.I), "Developmental"),
    (re.compile(r"Wnt|Frizzled|FZD", re.I), "Developmental"),
    (re.compile(r"Hedgehog|SMO|PTCH", re.I), "Developmental"),
    (re.compile(r"TLR\d|Toll", re.I), "Immune"),
    (re.compile(r"TNF|TNFR|TRAIL", re.I), "Immune"),
    (re.compile(r"IL\d|Interleukin", re.I), "Cytokine"),
    (re.compile(r"IFN|Interferon|IFNAR|IFNGR", re.I), "Cytokine"),
    (re.compile(r"GPCR|Adrenergic|Muscarinic|Serotonin|Dopamine|Opioid", re.I), "GPCR"),
    (re.compile(r"Estrogen|ESR|Androgen|Progesterone", re.I), "Nuclear Receptor"),
    (re.compile(r"EPH|Ephrin", re.I), "RTK"),
    (re.compile(r"NMDA|Glutamate|GABA", re.I), "Ion Channel"),
]


def _classify_receptor(receptor_name: str) -> str:
    """Classify receptor into a category based on name."""
    for pattern, cls in _RECEPTOR_CLASS_RULES:
        if pattern.search(receptor_name):
            return cls
    return "Receptor"


def _extract_receptor_from_name(name: str) -> Optional[str]:
    """Extract receptor name from a pathway display name like 'Signaling by EGFR'."""
    m = _SIGNALING_BY_RE.match(name)
    if not m:
        return None
    candidate = m.group(1).strip()
    if candidate.lower() in _SKIP_NAMES:
        return None
    return candidate


# ---------------------------------------------------------------------------
# Reactome API calls (with httpx)
# ---------------------------------------------------------------------------
async def _search_entity(
    client: httpx.AsyncClient, gene_name: str, species_name: str = "Homo sapiens"
) -> Optional[str]:
    """Search Reactome for a protein entity and return its stId."""
    url = f"{REACTOME_BASE}/search/query"
    params = {
        "query": gene_name,
        "species": species_name,
        "types": "Protein",
    }
    try:
        resp = await client.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        entries = results[0].get("entries", [])
        if not entries:
            return None
        return entries[0].get("stId")
    except Exception as e:
        logger.warning(f"Reactome search failed for {gene_name}: {e}")
        return None


async def _get_pathways(
    client: httpx.AsyncClient, entity_stid: str, species_id: int = 9606
) -> list[dict]:
    """Get low-level pathways containing all forms of the entity."""
    url = f"{REACTOME_BASE}/data/pathways/low/entity/{entity_stid}/allForms"
    params = {"species": species_id}
    try:
        resp = await client.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception as e:
        logger.warning(f"Reactome pathways failed for {entity_stid}: {e}")
        return []


async def _get_ancestors(client: httpx.AsyncClient, pathway_stid: str) -> list[list[dict]]:
    """Get ancestor hierarchy for a pathway event."""
    url = f"{REACTOME_BASE}/data/event/{pathway_stid}/ancestors"
    try:
        resp = await client.get(url, timeout=10)
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception as e:
        logger.warning(f"Reactome ancestors failed for {pathway_stid}: {e}")
        return []


# ---------------------------------------------------------------------------
# Core logic: kinase → receptor mapping
# ---------------------------------------------------------------------------
async def _lookup_receptors_for_kinase(
    client: httpx.AsyncClient, gene_name: str,
    species_id: int = 9606, species_name: str = "Homo sapiens",
) -> list[dict]:
    """
    Given a kinase gene name, find upstream receptors via Reactome pathway hierarchy.
    Returns list of:
      {"receptor": str, "receptor_class": str, "pathway": str, "pathway_id": str}
    """
    # Step 1: search entity
    stid = await _search_entity(client, gene_name, species_name=species_name)
    if not stid:
        return []

    # Step 2: get pathways
    pathways = await _get_pathways(client, stid, species_id=species_id)
    if not pathways:
        return []

    # Step 3: for each pathway, get ancestors and extract receptors
    # Limit to 15 pathways to avoid excessive API calls
    receptor_map: dict[str, dict] = {}  # receptor_name -> info

    # Gather ancestors in parallel (batched)
    pathway_subset = pathways[:15]
    ancestor_tasks = [
        _get_ancestors(client, p.get("stId", "")) for p in pathway_subset
    ]
    ancestor_results = await asyncio.gather(*ancestor_tasks, return_exceptions=True)

    for pw, ancestors in zip(pathway_subset, ancestor_results):
        if isinstance(ancestors, Exception) or not ancestors:
            continue
        pw_name = pw.get("displayName", "")
        pw_stid = pw.get("stId", "")

        for branch in ancestors:
            for node in branch:
                name = node.get("displayName", "")
                receptor = _extract_receptor_from_name(name)
                if receptor and receptor not in receptor_map:
                    receptor_map[receptor] = {
                        "receptor": receptor,
                        "receptor_class": _classify_receptor(receptor),
                        "pathway": pw_name,
                        "pathway_id": pw_stid,
                        "signaling_pathway": name,
                    }

    return list(receptor_map.values())


# ---------------------------------------------------------------------------
# Public API with Redis caching
# ---------------------------------------------------------------------------
async def get_receptors_for_kinase(gene_name: str, species: str = "") -> list[dict]:
    """
    Get upstream receptors for a kinase, with Redis caching.
    Cache key: reactome:kinase_receptors:{species_id}:{gene_name}
    Cache TTL: 90 days

    Args:
        gene_name: Kinase gene symbol (e.g. "MAPK1")
        species: Species string (e.g. "Rattus norvegicus", "human", "mouse").
                 Defaults to Homo sapiens if empty.
    """
    species_id, species_name = _resolve_species(species)
    redis = await get_redis()
    cache_key = f"{CACHE_PREFIX}:{species_id}:{gene_name.upper()}"

    # Check cache
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis cache read failed: {e}")

    # Cache miss — call Reactome API
    async with httpx.AsyncClient(verify=False) as client:
        receptors = await _lookup_receptors_for_kinase(
            client, gene_name, species_id=species_id, species_name=species_name
        )

    # Store in cache (even empty results to avoid repeated lookups)
    try:
        await redis.set(
            cache_key,
            json.dumps(receptors),
            ex=int(CACHE_TTL.total_seconds()),
        )
    except Exception as e:
        logger.warning(f"Redis cache write failed: {e}")

    return receptors


async def get_receptors_for_kinases(
    kinase_names: list[str], species: str = ""
) -> dict[str, list[dict]]:
    """
    Batch lookup: get upstream receptors for multiple kinases.
    Returns {kinase_name: [receptor_info, ...]}

    Args:
        kinase_names: List of kinase gene symbols.
        species: Species string (e.g. "Rattus norvegicus", "human", "mouse").
                 Defaults to Homo sapiens if empty.
    """
    tasks = [get_receptors_for_kinase(name, species=species) for name in kinase_names]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = {}
    for name, result in zip(kinase_names, results):
        if isinstance(result, Exception):
            logger.warning(f"Receptor lookup failed for {name}: {result}")
            output[name] = []
        else:
            output[name] = result

    return output
