"""InterPro API Tool — protein domain annotations."""

import asyncio
import logging
import urllib.parse

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
    cache_key = f"interpro:full_source.v2:{clean_id}:pages20"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_interpro_info(clean_id, timeout, max_retries)

    from ptm_shared.evidence_contracts import source_query_record
    result["source_record"] = source_query_record("interpro", result["query_status"],
        query={"protein_id": clean_id, "max_pages": 20}, payload=result,
        snapshot="interpro_full_source.v2")
    if redis and result["query_status"] in {"hit", "no_hit"} and result.get("retrieval_complete"):
        import json
        await redis.set(cache_key, json.dumps(result), ex=604800 if result["query_status"] == "hit" else 3600)
    return result


def _clean_protein_id(protein_id: str) -> str:
    """Clean protein ID from FASTA-style headers, preserving isoform suffixes.

    UniProt isoform IDs (e.g. P12345-2, Q9WTQ5-3) are valid accessions
    supported by the InterPro API and must NOT be stripped.
    """
    import re as _re
    if "|" in protein_id:
        parts = protein_id.split("|")
        if len(parts) >= 2:
            return parts[1]
    # Preserve UniProt isoform suffixes (e.g. P12345-2, Q9WTQ5-3)
    # Pattern: 1 uppercase letter + 5 alphanumeric + dash + digits
    if "-" in protein_id:
        if _re.match(r'^[A-Z][0-9A-Z]{5,9}-\d+$', protein_id.strip()):
            return protein_id.strip()  # valid isoform accession — keep as-is
        return protein_id.split("-")[0]
    return protein_id.strip()


async def _fetch_interpro_info(
    protein_id: str, timeout: float, max_retries: int
) -> dict:
    import json
    empty = {"protein_id": protein_id, "domains": [], "full_domains": [], "source_pages": [],
             "retrieval_complete": False, "query_status": "unavailable"}
    encoded_id = urllib.parse.quote(protein_id, safe="")
    url = f"{BASE_URL}/{encoded_id}"
    pages, domains, seen, visited = [], [], set(), set()
    async with httpx.AsyncClient(timeout=timeout) as client:
        for page_index in range(20):
            if url in visited:
                return {**empty, "query_status": "parse_failure", "source_pages": pages}
            visited.add(url)
            response = None
            for attempt in range(max_retries):
                try:
                    response = await client.get(url)
                    if response.status_code == 429 and attempt + 1 < max_retries:
                        await asyncio.sleep(min(8, 2 ** (attempt + 1)))
                        continue
                    break
                except httpx.TimeoutException:
                    if attempt + 1 == max_retries:
                        return {**empty, "query_status": "timeout", "source_pages": pages}
                except httpx.HTTPError:
                    return {**empty, "query_status": "api_error", "source_pages": pages}
            if response is None:
                return empty
            if response.status_code == 404 and not pages:
                return {**empty, "query_status": "no_hit", "retrieval_complete": True}
            if response.status_code == 429:
                return {**empty, "query_status": "rate_limited", "source_pages": pages}
            if response.status_code >= 400:
                return {**empty, "query_status": "api_error", "source_pages": pages}
            try:
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                    raise ValueError("unexpected_interpro_schema")
                pages.append(data)
                for record in data["results"]:
                    metadata = record.get("metadata") or {}
                    entry_type = str(metadata.get("type", "")).lower()
                    if entry_type not in {"domain", "family", "repeat", "homologous_superfamily"}:
                        continue
                    key = (metadata.get("accession"), entry_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    domains.append({"name": metadata.get("name", ""), "accession": key[0],
                                    "type": entry_type, "source_record": record})
                next_url = data.get("next")
                if not next_url:
                    return {"protein_id": protein_id, "domains": domains[:5], "full_domains": domains,
                            "source_pages": pages, "retrieval_complete": True,
                            "query_status": "hit" if data["results"] or domains else "no_hit",
                            "display_policy": "top5_domains.v1", "parser_version": "interpro_full_source.v2"}
                parsed = urllib.parse.urlparse(str(next_url))
                if parsed.scheme != "https" or parsed.netloc != "www.ebi.ac.uk":
                    raise ValueError("invalid_interpro_pagination")
                url = str(next_url)
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
                return {**empty, "query_status": "parse_failure", "source_pages": pages}
    return {**empty, "domains": domains[:5], "full_domains": domains, "source_pages": pages,
            "query_status": "unknown", "reason": "pagination_budget_exhausted"}
