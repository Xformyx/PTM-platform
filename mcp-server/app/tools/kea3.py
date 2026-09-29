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
    taxonomy_id: Optional[str] = None,
    orthology_mapping=None,
) -> dict:
    """
    Submit a gene list to KEA3 for kinase enrichment analysis.

    Parameters:
        gene_list: List of substrate gene symbols (e.g., ["ACC1", "AMPK", "mTOR"])
                   Human symbols retain their identity. Nonhuman genes require explicit
                   verified human orthology mapping; uppercase is not mapping.
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

    from ptm_shared.kea3_evidence import mapped_human_genes, parse_kea3
    try:
        normalized_genes = mapped_human_genes(gene_list, taxonomy_id, orthology_mapping)
    except ValueError as error:
        return {"gene_count": len(gene_list), "top_kinases": [], "query_status": "not_supported", "error": str(error)}

    # Cache key
    sorted_genes = sorted(normalized_genes)
    from ptm_shared.evidence_contracts import source_cache_key
    top_n = max(0, int(top_n))
    cache_key = source_cache_key("kea3", genes=sorted_genes, top_n=top_n,
                                 parser="kea3_typed_response.v3", taxon=taxonomy_id, mapping=orthology_mapping, endpoint=KEA3_API_URL)
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
        "gene_set": normalized_genes,
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
                    result['query_status'] = 'rate_limited' if resp.status == 429 else 'api_error'
                    result["error"] = f"KEA3 returned {resp.status}"
                    return result

                import json
                data = await resp.json(content_type=None)
                result['full_source_response'] = data
                result['available_libraries'] = sorted(data) if isinstance(data, dict) else []
                result['species_scope'] = 'human_native_or_explicit_verified_mapping'
                rows = parse_kea3(data)
                result['all_source_rows'] = rows
                result['integrated_ranking'] = [r for r in rows if r['library'] == 'Integrated--meanRank']
                result['top_kinases'] = result['integrated_ranking'][:top_n]
                result['library_rankings'] = {lib: [r for r in rows if r['library'] == lib]
                    for lib in sorted(data) if not lib.startswith('Integrated')}

    except Exception as e:
        logger.warning(f"KEA3 query failed: {e}")
        import asyncio
        result['query_status'] = 'timeout' if isinstance(e, asyncio.TimeoutError) else 'parse_failure' if isinstance(e, (ValueError, TypeError, AttributeError)) else 'api_error'
        result["error"] = str(e)

    result.setdefault('query_status', 'hit' if result['top_kinases'] else 'no_hit')
    from ptm_shared.evidence_contracts import source_query_record
    result['source_record'] = source_query_record('kea3', result['query_status'],
        query={'genes': sorted_genes, 'top_n': top_n}, payload=result)
    if redis and not result["error"]:
        try:
            import json
            await redis.set(cache_key, json.dumps(result), ex=7 * 24 * 60 * 60)
        except Exception:
            pass

    return result
