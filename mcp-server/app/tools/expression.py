"""
Expression & Localization Clients — HPA, GTEx, BioGRID.

Ported from ptm-rag-backend/src/hpaClient.ts, gtexParser.ts.

Provides:
  - Human Protein Atlas (HPA) subcellular localization
  - GTEx tissue expression / isoform ratios
  - BioGRID protein-protein interactions
"""

import asyncio
import logging
import os
import re
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


# ===========================================================================
# HPA — Human Protein Atlas Subcellular Localization
# ===========================================================================

HPA_API_BASE = "https://www.proteinatlas.org"


async def query_hpa(gene_name: str, redis=None) -> dict:
    """
    Query Human Protein Atlas for subcellular localization.

    Returns dict with keys: gene, locations, reliability, go_terms, error.
    """
    cache_key = f"hpa:{gene_name.upper()}"
    if redis:
        try:
            import json
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    result: dict = {
        "gene": gene_name,
        "locations": [],
        "reliability": None,
        "go_terms": [],
        "cell_cycle_dependency": [],
        "error": None,
    }

    url = f"{HPA_API_BASE}/{gene_name.upper()}.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    result["error"] = f"HPA returned {resp.status}"
                    return result

                import json
                data = await resp.json(content_type=None)

                # Extract subcellular location data
                if isinstance(data, list) and len(data) > 0:
                    entry = data[0] if isinstance(data, list) else data
                elif isinstance(data, dict):
                    entry = data
                else:
                    result["error"] = "Unexpected HPA response format"
                    return result

                # Try to find subcellular location info
                sub_loc = entry.get("Subcellular location", {})
                if isinstance(sub_loc, list) and len(sub_loc) > 0:
                    sub_loc = sub_loc[0]

                if isinstance(sub_loc, dict):
                    result["locations"] = sub_loc.get("location", [])
                    result["reliability"] = sub_loc.get("reliability", None)

                # Fallback: check for protein_atlas_subcellular_location
                if not result["locations"]:
                    for key in ("SubcellularLocation", "subcellular_location"):
                        if key in entry:
                            loc_data = entry[key]
                            if isinstance(loc_data, list):
                                result["locations"] = loc_data
                            elif isinstance(loc_data, str):
                                result["locations"] = [s.strip() for s in loc_data.split(";")]
                            break

    except Exception as e:
        logger.warning(f"HPA query failed for {gene_name}: {e}")
        result["error"] = str(e)

    if redis and not result["error"]:
        try:
            import json
            await redis.set(cache_key, json.dumps(result))  # permanent cache
        except Exception:
            pass

    return result


# ===========================================================================
# GTEx — Tissue Expression
# ===========================================================================

GTEX_API_BASE = "https://gtexportal.org/api/v2"


async def query_gtex(gene_name: str, redis=None) -> dict:
    """
    Query GTEx for tissue expression data.

    Returns dict with keys: gene, expressions (list of {tissue, median_tpm}), error.
    """
    cache_key = f"gtex:{gene_name.upper()}"
    if redis:
        try:
            import json
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    result: dict = {
        "gene": gene_name,
        "expressions": [],
        "top_tissues": [],
        "error": None,
    }

    url = f"{GTEX_API_BASE}/expression/medianGeneExpression"
    params = {"gencodeId": gene_name, "datasetId": "gtex_v8"}

    try:
        async with aiohttp.ClientSession() as session:
            # First try with gene symbol via search
            search_url = f"{GTEX_API_BASE}/reference/gene?geneId={gene_name}&gencodeVersion=v26&genomeBuild=GRCh38%2Fhg38"
            async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    import json
                    search_data = await resp.json(content_type=None)
                    genes = search_data.get("data", [])
                    if genes:
                        gencode_id = genes[0].get("gencodeId", "")
                        if gencode_id:
                            expr_url = f"{GTEX_API_BASE}/expression/medianGeneExpression?gencodeId={gencode_id}&datasetId=gtex_v8"
                            async with session.get(expr_url, timeout=aiohttp.ClientTimeout(total=15)) as expr_resp:
                                if expr_resp.status == 200:
                                    expr_data = await expr_resp.json(content_type=None)
                                    expressions = expr_data.get("data", [])
                                    result["expressions"] = [
                                        {"tissue": e.get("tissueSiteDetailId", ""),
                                         "median_tpm": e.get("median", 0)}
                                        for e in expressions
                                    ]
                                    # Top 5 tissues
                                    sorted_expr = sorted(result["expressions"],
                                                         key=lambda x: x["median_tpm"], reverse=True)
                                    result["top_tissues"] = sorted_expr[:5]

    except Exception as e:
        logger.warning(f"GTEx query failed for {gene_name}: {e}")
        result["error"] = str(e)

    if redis and not result["error"]:
        try:
            import json
            await redis.set(cache_key, json.dumps(result))  # permanent cache
        except Exception:
            pass

    return result


# ===========================================================================
# BioGRID — Protein-Protein Interactions
# ===========================================================================

BIOGRID_API_BASE = "https://webservice.thebiogrid.org/interactions"
BIOGRID_API_KEY = os.getenv("BIOGRID_API_KEY", "")


async def query_biogrid(
    gene_name: str,
    organism: int = 10090,  # 10090=mouse, 9606=human
    redis=None,
) -> dict:
    """
    Query BioGRID for protein-protein interactions.

    Returns dict with keys: gene, interactions, interaction_count, error.
    """
    cache_key = f"biogrid:{gene_name}:{organism}"
    if redis:
        try:
            import json
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    result: dict = {
        "gene": gene_name,
        "organism": organism,
        "interactions": [],
        "interaction_count": 0,
        "error": None,
    }

    if not BIOGRID_API_KEY:
        result["error"] = "BIOGRID_API_KEY not configured"
        return result

    params = {
        "accesskey": BIOGRID_API_KEY,
        "format": "json",
        "searchNames": "true",
        "geneList": gene_name,
        "taxId": str(organism),
        "max": "100",
        "includeInteractors": "true",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BIOGRID_API_BASE, params=params,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    result["error"] = f"BioGRID returned {resp.status}"
                    return result

                import json
                data = await resp.json(content_type=None)

                if isinstance(data, dict):
                    interactions = []
                    for _id, interaction in data.items():
                        if not isinstance(interaction, dict):
                            continue
                        interactions.append({
                            "interactor_a": interaction.get("OFFICIAL_SYMBOL_A", ""),
                            "interactor_b": interaction.get("OFFICIAL_SYMBOL_B", ""),
                            "experimental_system": interaction.get("EXPERIMENTAL_SYSTEM", ""),
                            "throughput": interaction.get("THROUGHPUT", ""),
                            "pubmed_id": interaction.get("PUBMED_ID", ""),
                        })

                    result["interactions"] = interactions[:50]  # limit
                    result["interaction_count"] = len(interactions)

    except Exception as e:
        logger.warning(f"BioGRID query failed for {gene_name}: {e}")
        result["error"] = str(e)

    if redis and not result["error"]:
        try:
            import json
            await redis.set(cache_key, json.dumps(result))  # permanent cache
        except Exception:
            pass

    return result
