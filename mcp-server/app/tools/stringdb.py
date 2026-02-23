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
    limit: int = 10,
    redis=None,
    timeout: float = 15.0,
) -> dict:
    cache_key = f"stringdb:{gene_name}:{species}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_string_info(gene_name, species, limit, timeout)

    if redis:
        import json
        await redis.set(cache_key, json.dumps(result))  # permanent cache

    return result


async def _fetch_string_info(
    gene_name: str, species: str, limit: int, timeout: float
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
        "limit": limit,
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
                return empty

            data = resp.json()
            if not data:
                return empty

            interactions = []
            total_score = 0.0
            for item in data[:10]:
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
        return empty
