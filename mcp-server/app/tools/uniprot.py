"""UniProt REST API Tool — protein information, GO terms, subcellular localization."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger("mcp-server.uniprot")

BASE_URL = "https://rest.uniprot.org/uniprotkb"


async def query_uniprot(
    protein_id: str,
    redis=None,
    timeout: float = 15.0,
) -> dict:
    clean_id = _clean_protein_id(protein_id)
    cache_key = f"uniprot:{clean_id}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _fetch_uniprot_info(clean_id, timeout)

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


async def _fetch_uniprot_info(protein_id: str, timeout: float) -> dict:
    empty = _empty_result(protein_id)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{BASE_URL}/{protein_id}.json")
            if resp.status_code == 404:
                return empty
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"UniProt fetch failed for {protein_id}: {e}")
        return empty

    result = {
        "protein_id": protein_id,
        "subcellular_location": [],
        "function_summary": "",
        "go_terms_bp": [],
        "go_terms_mf": [],
        "go_terms_cc": [],
    }

    for comment in data.get("comments", []):
        ctype = comment.get("commentType", "")
        if ctype == "SUBCELLULAR LOCATION":
            for sub in comment.get("subcellularLocations", []):
                loc = sub.get("location", {}).get("value", "")
                if loc and loc not in result["subcellular_location"]:
                    result["subcellular_location"].append(loc)
        elif ctype == "FUNCTION":
            texts = comment.get("texts", [])
            if texts:
                result["function_summary"] = texts[0].get("value", "")[:500]

    for xref in data.get("uniProtKBCrossReferences", []):
        if xref.get("database") == "GO":
            go_id = xref.get("id", "")
            props = {p["key"]: p["value"] for p in xref.get("properties", [])}
            term = props.get("GoTerm", "")
            category = term[:2] if term else ""
            label = term[2:].strip(":").strip() if len(term) > 2 else term
            entry = f"{go_id}:{label}" if label else go_id

            if category == "P:" or category == "P:":
                result["go_terms_bp"].append(entry)
            elif category == "F:":
                result["go_terms_mf"].append(entry)
            elif category == "C:":
                result["go_terms_cc"].append(entry)

    for key in ("go_terms_bp", "go_terms_mf", "go_terms_cc"):
        result[key] = result[key][:5]

    return result


def _empty_result(protein_id: str) -> dict:
    return {
        "protein_id": protein_id,
        "subcellular_location": [],
        "function_summary": "",
        "go_terms_bp": [],
        "go_terms_mf": [],
        "go_terms_cc": [],
    }
