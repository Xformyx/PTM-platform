"""Enrichr API Tool — gene-set enrichment analysis across multiple libraries."""

import asyncio
import logging
from typing import List, Optional

import httpx

logger = logging.getLogger("mcp-server.enrichr")

BASE_URL = "https://maayanlab.cloud/Enrichr"

# Default libraries for PTM/signaling analysis
DEFAULT_LIBRARIES = [
    "KEGG_2021_Human",
    "Reactome_2022",
    "WikiPathway_2023_Human",
    "BioPlanet_2019",
    "MSigDB_Hallmark_2020",
]


async def query_enrichr(
    gene_list: List[str],
    libraries: Optional[List[str]] = None,
    description: str = "",
    top_n: int = 15,
    redis=None,
    timeout: float = 30.0,
) -> dict:
    """
    Submit a gene list to Enrichr and retrieve enrichment results
    from multiple pathway libraries.

    Args:
        gene_list: List of gene symbols (human, uppercase recommended)
        libraries: Pathway libraries to query (defaults to 5 key libraries)
        description: Optional description for the gene list
        top_n: Number of top terms to return per library
        redis: Optional Redis connection for caching
        timeout: HTTP timeout in seconds

    Returns:
        Dict with enrichment results per library, including term name,
        p-value, FDR, and overlapping genes.
    """
    if not gene_list:
        return {"gene_list": [], "results": {}, "error": "Empty gene list"}

    # Normalize gene names to uppercase (Enrichr expects human gene symbols)
    gene_list_upper = [g.upper() for g in gene_list]
    libs = libraries or DEFAULT_LIBRARIES

    # Cache key based on sorted gene list + libraries
    cache_key = f"enrichr:{','.join(sorted(gene_list_upper))}:{','.join(sorted(libs))}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _run_enrichr(gene_list_upper, libs, description, top_n, timeout)

    if redis and "error" not in result:
        import json
        # Cache for 24 hours (enrichment results are relatively stable)
        await redis.set(cache_key, json.dumps(result), ex=86400)

    return result


async def _run_enrichr(
    gene_list: List[str],
    libraries: List[str],
    description: str,
    top_n: int,
    timeout: float,
) -> dict:
    empty = {"gene_list": gene_list, "results": {}}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: Submit gene list
            gene_str = "\n".join(gene_list)
            resp = await client.post(
                f"{BASE_URL}/addList",
                data={"list": gene_str, "description": description or "PTM_cluster"},
            )
            if resp.status_code != 200:
                logger.warning(f"Enrichr addList failed: {resp.status_code}")
                return {**empty, "error": f"addList failed: {resp.status_code}"}

            list_data = resp.json()
            user_list_id = list_data.get("userListId")
            if not user_list_id:
                return {**empty, "error": "No userListId returned"}

            # Brief pause to let Enrichr process the list
            await asyncio.sleep(0.5)

            # Step 2: Query each library
            results = {}
            for lib in libraries:
                try:
                    url = f"{BASE_URL}/enrich"
                    params = {
                        "userListId": user_list_id,
                        "backgroundType": lib,
                    }
                    resp2 = await client.get(url, params=params, timeout=timeout)

                    if resp2.status_code != 200:
                        logger.debug(f"Enrichr {lib} returned {resp2.status_code}")
                        results[lib] = {"terms": [], "error": f"HTTP {resp2.status_code}"}
                        continue

                    data = resp2.json()
                    terms_raw = data.get(lib, [])

                    # Parse Enrichr response format:
                    # [rank, term_name, p_value, z_score, combined_score,
                    #  overlapping_genes, adj_p_value, ...]
                    terms = []
                    for t in terms_raw[:top_n]:
                        if len(t) < 7:
                            continue
                        term = {
                            "rank": t[0],
                            "name": t[1],
                            "p_value": t[2],
                            "z_score": t[3],
                            "combined_score": t[4],
                            "genes": t[5] if isinstance(t[5], list) else [],
                            "adj_p_value": t[6],
                        }
                        terms.append(term)

                    results[lib] = {
                        "terms": terms,
                        "total_terms": len(terms_raw),
                    }

                    # Rate limit between library queries
                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.warning(f"Enrichr query failed for {lib}: {e}")
                    results[lib] = {"terms": [], "error": str(e)}

            return {
                "gene_list": gene_list,
                "user_list_id": user_list_id,
                "results": results,
            }

    except Exception as e:
        logger.warning(f"Enrichr analysis failed: {e}")
        return {**empty, "error": str(e)}


async def query_enrichr_string_enrichment(
    gene_list: List[str],
    species: int = 10090,
    redis=None,
    timeout: float = 20.0,
) -> dict:
    """
    Use STRING-DB's functional enrichment API for a gene set.
    This provides KEGG pathway enrichment with statistical significance
    based on the STRING network background.

    Args:
        gene_list: List of gene symbols
        species: NCBI taxonomy ID (10090=mouse, 9606=human)
        redis: Optional Redis connection
        timeout: HTTP timeout

    Returns:
        Dict with KEGG enrichment terms, FDR values, and gene memberships.
    """
    if not gene_list:
        return {"gene_list": [], "kegg_terms": [], "all_terms": []}

    cache_key = f"string_enrich:{','.join(sorted(gene_list))}:{species}"
    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _run_string_enrichment(gene_list, species, timeout)

    if redis and "error" not in result:
        import json
        await redis.set(cache_key, json.dumps(result), ex=86400)

    return result


async def _run_string_enrichment(
    gene_list: List[str], species: int, timeout: float
) -> dict:
    empty = {"gene_list": gene_list, "kegg_terms": [], "all_terms": []}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            params = {
                "identifiers": "%0d".join(gene_list),
                "species": species,
                "caller_identity": "PTM-Platform",
            }
            resp = await client.get(
                "https://string-db.org/api/json/enrichment",
                params=params,
            )
            if resp.status_code != 200:
                return {**empty, "error": f"STRING enrichment HTTP {resp.status_code}"}

            data = resp.json()
            if not isinstance(data, list):
                return empty

            kegg_terms = []
            all_terms = []

            # Signaling keywords for relevance tagging
            SIG_KW = [
                "signal", "pi3k", "akt", "mapk", "mtor", "ras", "wnt",
                "notch", "jak", "stat", "nfkb", "tgf", "vegf", "erbb",
                "insulin", "integrin", "focal", "adhesion", "autophagy",
                "apoptosis", "kinase", "phosphat", "calcium", "camp",
                "cell cycle", "chemokine", "cytokine",
            ]

            for item in data:
                category = item.get("category", "")
                term = {
                    "category": category,
                    "term": item.get("term", ""),
                    "description": item.get("description", ""),
                    "fdr": item.get("fdr", 1.0),
                    "p_value": item.get("p_value", 1.0),
                    "gene_count": item.get("number_of_genes", 0),
                    "input_genes": item.get("inputGenes", ""),
                    "is_signaling": any(
                        kw in item.get("description", "").lower()
                        for kw in SIG_KW
                    ),
                }
                all_terms.append(term)
                if category == "KEGG":
                    kegg_terms.append(term)

            # Sort by FDR
            kegg_terms.sort(key=lambda x: x["fdr"])
            all_terms.sort(key=lambda x: x["fdr"])

            return {
                "gene_list": gene_list,
                "kegg_terms": kegg_terms,
                "all_terms": all_terms[:50],  # Limit total terms
                "kegg_count": len(kegg_terms),
                "total_count": len(all_terms),
            }

    except Exception as e:
        logger.warning(f"STRING enrichment failed: {e}")
        return {**empty, "error": str(e)}
