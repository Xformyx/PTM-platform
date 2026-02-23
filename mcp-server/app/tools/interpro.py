"""InterPro API Tool — protein domain annotations."""

import asyncio
import logging
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger("mcp-server.interpro")

BASE_URL = "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot"


async def query_interpro(
    protein_id: str,
    redis=None,
    timeout: float = 20.0,
    max_retries: int = 3,
) -> dict:
    clean_id = _clean_protein_id(protein_id)
    cache_key = f"interpro:{clean_id}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_interpro_info(clean_id, timeout, max_retries)

    if redis:
        import json
        await redis.set(cache_key, json.dumps(result))  # permanent cache

    return result


def _clean_protein_id(protein_id: str) -> str:
    if "|" in protein_id:
        parts = protein_id.split("|")
        if len(parts) >= 2:
            return parts[1]
    if "-" in protein_id:
        return protein_id.split("-")[0]
    return protein_id.strip()


async def _fetch_interpro_info(
    protein_id: str, timeout: float, max_retries: int
) -> dict:
    empty = {"protein_id": protein_id, "domains": []}
    encoded_id = urllib.parse.quote(protein_id, safe="")

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{BASE_URL}/{encoded_id}")

                if resp.status_code == 404:
                    return empty
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"InterPro rate limit for {protein_id}, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

            target_types = {"domain", "family", "repeat", "homologous_superfamily"}
            domains = []
            seen = set()

            for result in data.get("results", []):
                metadata = result.get("metadata", {})
                entry_type = metadata.get("type", "").lower()
                if entry_type not in target_types:
                    continue
                name = metadata.get("name", "")
                accession = metadata.get("accession", "")
                if name and name not in seen:
                    seen.add(name)
                    domains.append({
                        "name": name,
                        "accession": accession,
                        "type": entry_type,
                    })

            return {
                "protein_id": protein_id,
                "domains": domains[:5],
            }

        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            logger.warning(f"InterPro timeout for {protein_id}")
            return empty
        except Exception as e:
            logger.warning(f"InterPro fetch failed for {protein_id}: {e}")
            return empty

    return empty
