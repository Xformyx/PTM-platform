"""STRING-DB API Tool — protein-protein interaction data."""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("mcp-server.stringdb")

BASE_URL = "https://string-db.org/api/json"
STRINGDB_API_KEY = os.getenv("STRINGDB_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")


async def query_stringdb(
    gene_name: str,
    species: str = "10090",
    redis=None,
    timeout: float = 15.0,
) -> dict:
    cache_key = f"stringdb:query_status.v2:{gene_name}:{species}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_string_info(gene_name, species, timeout)

    result.setdefault("query_status", "hit" if result.get("interactions") else "unknown")
    from ptm_shared.evidence_contracts import source_query_record
    result["source_record"] = source_query_record("stringdb", result["query_status"],
        query={"gene": gene_name, "scope": species}, payload=result,
        snapshot="live_query_status.v2")
    if redis and result["query_status"] in {"hit", "no_hit"}:
        import json
        await redis.set(cache_key, json.dumps(result), ex=604800 if result["query_status"] == "hit" else 3600)  # permanent cache

    return result


async def _fetch_string_info(
    gene_name: str, species: str, timeout: float
) -> dict:
    empty = {
        "gene_name": gene_name,
        "species": species,
        "interactions": [],
        "interaction_count": 0,
        "avg_score": 0.0,
    }

    params = {
        "identifiers": gene_name,
        "species": species,
    }
    caller = STRINGDB_API_KEY or NCBI_EMAIL or "PTM-Platform"
    if caller:
        params["caller_identity"] = caller

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{BASE_URL}/interaction_partners",
                params=params,
            )
            if resp.status_code != 200:
                return {**empty, "query_status": "rate_limited" if resp.status_code == 429 else "api_error", "http_status": resp.status_code}

            data = resp.json()
            if not data:
                return {**empty, "query_status": "no_hit"}

            interactions = []
            total_score = 0.0
            for item in data:
                partner = item.get("preferredName_B", item.get("stringId_B", ""))
                score = item.get("score", 0)
                interactions.append({"partner": partner, "score": round(score, 3)})
                total_score += score

            return {
                "gene_name": gene_name,
                "species": species,
                "interactions": interactions,
                "interaction_count": len(interactions),
                "avg_score": round(total_score / len(interactions), 3) if interactions else 0.0,
            }

    except Exception as e:
        logger.warning(f"STRING-DB fetch failed for {gene_name}: {e}")
        status = "timeout" if isinstance(e, httpx.TimeoutException) else "parse_failure" if isinstance(e, (ValueError, TypeError, AttributeError)) else "api_error"
        return {**empty, "query_status": status}
