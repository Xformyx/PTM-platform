"""Reactome API Tool — pathway information for proteins via Reactome."""

import asyncio
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger("mcp-server.reactome")

BASE_URL = "https://reactome.org/ContentService"

# ── Gene-name → UniProt mapping (mouse gene → human ortholog) ──────────
# Reactome primarily uses human UniProt IDs.  We use UniProt's ID-mapping
# service to resolve mouse gene names to human orthologs.

UNIPROT_ID_MAP_URL = "https://rest.uniprot.org"


async def query_reactome(
    gene_name: str,
    organism: str = "Mus musculus",
    redis=None,
    timeout: float = 20.0,
) -> dict:
    """
    Query Reactome pathways for a gene.

    Strategy:
      1. Map mouse gene name → human UniProt ID via UniProt ID-mapping
      2. Query Reactome /data/mapping/UniProt/{id}/pathways
      3. Return pathway list with signaling relevance tags
    """
    cache_key = f"reactome:{gene_name}:{organism}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_reactome_pathways(gene_name, organism, timeout)

    if redis:
        import json
        await redis.set(cache_key, json.dumps(result))

    return result


async def _fetch_reactome_pathways(
    gene_name: str, organism: str, timeout: float
) -> dict:
    empty = {
        "gene_name": gene_name,
        "organism": organism,
        "pathways": [],
        "signaling_pathways": [],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: Resolve gene name → UniProt ID
            # Use UniProt search to find human ortholog
            uniprot_id = await _resolve_uniprot_id(client, gene_name, timeout)
            if not uniprot_id:
                logger.debug(f"No UniProt ID found for {gene_name}")
                return empty

            # Step 2: Query Reactome pathways
            url = f"{BASE_URL}/data/mapping/UniProt/{uniprot_id}/pathways"
            resp = await client.get(
                url, headers={"Accept": "application/json"}
            )
            if resp.status_code != 200:
                logger.debug(f"Reactome returned {resp.status_code} for {uniprot_id}")
                return empty

            raw_pathways = resp.json()
            if not isinstance(raw_pathways, list):
                return empty

            # Step 3: Parse and classify pathways
            pathways = []
            signaling_pathways = []

            # Keywords indicating signaling-related pathways
            SIGNALING_KEYWORDS = [
                "signal", "pi3k", "akt", "mapk", "mtor", "ras", "wnt",
                "notch", "jak", "stat", "nfkb", "tgf", "vegf", "erbb",
                "insulin", "integrin", "focal", "adhesion", "autophagy",
                "apoptosis", "kinase", "phosphat", "calcium", "camp",
                "raf", "mek", "erk", "hedgehog", "hippo", "receptor",
                "tyrosine", "serine", "threonine", "gpcr", "rtk",
                "chemokine", "cytokine", "growth factor", "cell cycle",
                "dna damage", "immune", "inflamm", "toll",
            ]

            for pw in raw_pathways:
                name = pw.get("displayName", "")
                stable_id = pw.get("stId", "")
                species = pw.get("speciesName", "")

                # Only include Homo sapiens pathways (Reactome is human-centric)
                if species and "homo" not in species.lower():
                    continue

                entry = {
                    "id": stable_id,
                    "name": name,
                    "source": "Reactome",
                }

                # Classify as signaling or other
                name_lower = name.lower()
                is_signaling = any(kw in name_lower for kw in SIGNALING_KEYWORDS)
                entry["is_signaling"] = is_signaling

                pathways.append(entry)
                if is_signaling:
                    signaling_pathways.append(entry)

            return {
                "gene_name": gene_name,
                "organism": organism,
                "uniprot_id": uniprot_id,
                "pathways": pathways,
                "signaling_pathways": signaling_pathways,
                "total_count": len(pathways),
                "signaling_count": len(signaling_pathways),
            }

    except Exception as e:
        logger.warning(f"Reactome fetch failed for {gene_name}: {e}")
        return empty


async def _resolve_uniprot_id(
    client: httpx.AsyncClient, gene_name: str, timeout: float
) -> Optional[str]:
    """Resolve a gene name to a human UniProt ID (reviewed/Swiss-Prot preferred)."""
    try:
        # Search UniProt for human protein with this gene name
        params = {
            "query": f"gene_exact:{gene_name} AND organism_id:9606 AND reviewed:true",
            "format": "json",
            "size": "1",
            "fields": "accession",
        }
        resp = await client.get(
            f"{UNIPROT_ID_MAP_URL}/uniprotkb/search",
            params=params,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                return results[0].get("primaryAccession", "")

        # Fallback: try without reviewed filter
        params["query"] = f"gene_exact:{gene_name} AND organism_id:9606"
        resp = await client.get(
            f"{UNIPROT_ID_MAP_URL}/uniprotkb/search",
            params=params,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                return results[0].get("primaryAccession", "")

    except Exception as e:
        logger.debug(f"UniProt ID resolution failed for {gene_name}: {e}")

    return None
