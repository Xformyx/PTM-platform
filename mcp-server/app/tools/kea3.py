"""
KEA3 Client — Kinase Enrichment Analysis via KEA3 API.

Ported from ptm-rag-backend/src/kea3Client.ts.

Provides kinase enrichment analysis for a list of substrate genes,
returning ranked kinases with scores and p-values.
"""

import asyncio
import logging
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

KEA3_API_URL = "https://maayanlab.cloud/kea3/api/enrich/"


class KEA3Result:
    __slots__ = ("kinase", "rank", "score", "p_value", "overlapping_genes", "library")

    def __init__(self, kinase: str, rank: int, score: float,
                 p_value: float, overlapping_genes: List[str], library: str):
        self.kinase = kinase
        self.rank = rank
        self.score = score
        self.p_value = p_value
        self.overlapping_genes = overlapping_genes
        self.library = library

    def to_dict(self) -> dict:
        return {
            "kinase": self.kinase,
            "rank": self.rank,
            "score": self.score,
            "p_value": self.p_value,
            "overlapping_genes": self.overlapping_genes,
            "library": self.library,
        }


async def query_kea3(
    gene_list: List[str],
    top_n: int = 10,
    redis=None,
) -> dict:
    """
    Submit a gene list to KEA3 for kinase enrichment analysis.

    Parameters:
        gene_list: List of substrate gene symbols (e.g., ["ACC1", "AMPK", "mTOR"])
        top_n: Number of top kinases to return
        redis: Optional Redis client for caching

    Returns dict with keys:
        gene_count, top_kinases, integrated_ranking, library_rankings, error.
    """
    if not gene_list or len(gene_list) < 2:
        return {
            "gene_count": len(gene_list),
            "top_kinases": [],
            "error": "At least 2 genes required for KEA3 analysis",
        }

    # Cache key
    sorted_genes = sorted(set(g.upper() for g in gene_list))
    cache_key = f"kea3:{':'.join(sorted_genes[:20])}"
    if redis:
        try:
            import json
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    result: dict = {
        "gene_count": len(gene_list),
        "top_kinases": [],
        "integrated_ranking": [],
        "library_rankings": {},
        "error": None,
    }

    payload = {
        "gene_set": gene_list,
        "query_name": "PTM-Platform Query",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                KEA3_API_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    result["error"] = f"KEA3 returned {resp.status}"
                    return result

                import json
                data = await resp.json(content_type=None)

                # Parse integrated ranking (MeanRank)
                integrated = data.get("Integrated--meanRank", [])
                if isinstance(integrated, list):
                    for i, entry in enumerate(integrated[:top_n]):
                        if isinstance(entry, dict):
                            overlapping = entry.get("Overlapping_Genes", "")
                            if isinstance(overlapping, str):
                                overlapping = [g.strip() for g in overlapping.split(",") if g.strip()]

                            result["integrated_ranking"].append({
                                "kinase": entry.get("TF", entry.get("Kinase", "")),
                                "rank": i + 1,
                                "score": float(entry.get("Score", 0)),
                                "p_value": float(entry.get("FDR", entry.get("P-value", 1.0))),
                                "overlapping_genes": overlapping,
                                "library": "Integrated",
                            })

                result["top_kinases"] = result["integrated_ranking"][:top_n]

                # Parse individual library rankings
                for lib_key, lib_data in data.items():
                    if lib_key.startswith("Integrated"):
                        continue
                    if isinstance(lib_data, list) and len(lib_data) > 0:
                        lib_results = []
                        for i, entry in enumerate(lib_data[:5]):
                            if isinstance(entry, dict):
                                lib_results.append({
                                    "kinase": entry.get("TF", entry.get("Kinase", "")),
                                    "rank": i + 1,
                                    "score": float(entry.get("Score", 0)),
                                })
                        result["library_rankings"][lib_key] = lib_results

    except Exception as e:
        logger.warning(f"KEA3 query failed: {e}")
        result["error"] = str(e)

    if redis and not result["error"]:
        try:
            import json
            await redis.set(cache_key, json.dumps(result))  # permanent cache
        except Exception:
            pass

    return result
