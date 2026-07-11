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
    """Clean protein ID from FASTA-style headers, preserving isoform suffixes.

    UniProt isoform IDs (e.g. P12345-2, Q9WTQ5-3) are valid accessions
    supported by the UniProt REST API and must NOT be stripped.
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
        "gene_synonyms": [],
        "isoforms": [],
        "keywords": [],          # v9.17: UniProt keyword IDs + names for protein class prediction
        "protein_families": [],  # v9.17: protein family annotations (from SIMILARITY comments)
    }

    # Extract gene synonyms
    genes = data.get("genes", [])
    for gene_entry in genes:
        for syn in gene_entry.get("synonyms", []):
            val = syn.get("value", "")
            if val and val not in result["gene_synonyms"]:
                result["gene_synonyms"].append(val)

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
        elif ctype == "ALTERNATIVE PRODUCTS":
            # Extract isoform information
            for iso_event in comment.get("isoforms", []):
                iso_name = ""
                iso_names = iso_event.get("name", {}).get("value", "")
                if not iso_names:
                    iso_names_list = iso_event.get("isoformIds", [])
                    iso_name = iso_names_list[0] if iso_names_list else ""
                else:
                    iso_name = iso_names
                iso_ids = iso_event.get("isoformIds", [])
                iso_seq = iso_event.get("isoformSequenceStatus", "")
                note_texts = iso_event.get("texts", [])
                note = note_texts[0].get("value", "") if note_texts else ""
                if iso_name or iso_ids:
                    result["isoforms"].append({
                        "name": iso_name,
                        "isoform_id": iso_ids[0] if iso_ids else "",
                        "sequence_status": iso_seq,
                        "note": note[:200] if note else "",
                    })
        elif ctype == "SIMILARITY":
            # v9.17: protein family information
            texts = comment.get("texts", [])
            if texts:
                family_text = texts[0].get("value", "")[:200]
                if family_text:
                    result["protein_families"].append(family_text)

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

    # v9.17: Extract UniProt keywords for protein class prediction
    # Key keywords: KW-0675 Receptor, KW-0418 Kinase, KW-0823 Transcription factor,
    # KW-0472 Membrane, KW-1003 Cell membrane, KW-0597 Phosphoprotein,
    # KW-0832 Ubl conjugation, KW-0656 Proto-oncogene, KW-0807 Transducer
    for kw in data.get("keywords", []):
        kw_id = kw.get("id", "")
        kw_name = kw.get("name", "")
        if kw_id and kw_name:
            result["keywords"].append({"id": kw_id, "name": kw_name})

    # No limit on GO terms — return all available for comprehensive analysis
    return result


def _empty_result(protein_id: str) -> dict:
    return {
        "protein_id": protein_id,
        "subcellular_location": [],
        "function_summary": "",
        "go_terms_bp": [],
        "go_terms_mf": [],
        "go_terms_cc": [],
        "gene_synonyms": [],
        "isoforms": [],
        "keywords": [],
        "protein_families": [],
    }
