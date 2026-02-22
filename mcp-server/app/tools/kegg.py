"""KEGG REST API Tool — pathway information for genes."""

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger("mcp-server.kegg")

BASE_URL = "https://rest.kegg.jp"


async def query_kegg(
    gene_name: str,
    organism: str = "mmu",
    redis=None,
    timeout: float = 15.0,
) -> dict:
    cache_key = f"kegg:{gene_name}:{organism}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_kegg_info(gene_name, organism, timeout)

    if redis:
        import json
        await redis.set(cache_key, json.dumps(result), ex=7 * 86400)

    return result


async def _fetch_kegg_info(
    gene_name: str, organism: str, timeout: float
) -> dict:
    empty = {"gene_name": gene_name, "organism": organism, "pathways": []}
    gene_lower = gene_name.lower().strip()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: Find KEGG gene ID
            resp = await client.get(f"{BASE_URL}/find/{organism}/{gene_lower}")
            if resp.status_code != 200 or not resp.text.strip():
                return empty

            kegg_id = None
            for line in resp.text.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    candidate = parts[0].strip()
                    desc = parts[1].lower()
                    if gene_lower in desc or gene_lower == candidate.split(":")[-1].lower():
                        kegg_id = candidate
                        break
            if not kegg_id:
                first_line = resp.text.strip().split("\n")[0]
                kegg_id = first_line.split("\t")[0].strip()

            if not kegg_id:
                return empty

            # Step 2: Get pathway links
            resp2 = await client.get(f"{BASE_URL}/link/pathway/{kegg_id}")
            if resp2.status_code != 200 or not resp2.text.strip():
                return empty

            pathway_ids = []
            for line in resp2.text.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    pid = parts[1].strip()
                    if pid.startswith("path:"):
                        pathway_ids.append(pid.replace("path:", ""))

            if not pathway_ids:
                return empty

            # Step 3: Get pathway names (top 5)
            pathways = []
            for pid in pathway_ids[:5]:
                resp3 = await client.get(f"{BASE_URL}/get/{pid}")
                if resp3.status_code == 200:
                    for line in resp3.text.split("\n"):
                        if line.startswith("NAME"):
                            name = line.replace("NAME", "").strip()
                            name = name.split(" - ")[0].strip()
                            pathways.append({"id": pid, "name": name})
                            break
                await asyncio.sleep(0.05)

            return {
                "gene_name": gene_name,
                "organism": organism,
                "kegg_id": kegg_id,
                "pathways": pathways,
            }

    except Exception as e:
        logger.warning(f"KEGG fetch failed for {gene_name}: {e}")
        return empty
