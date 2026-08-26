"""Truth-free accession-first audit of external direct kinase evidence.

The audit consumes only an already-frozen strict-blind artifact.  It never
loads benchmark manifests, workbook truth, RAG context, stimulus labels, or
LLMs.  Exact observed residue positions are required before an external
annotation can be classified as direct evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from ptm_shared.direct_kinase_evidence import annotation_queries, extract_direct_kinase_names


AUDIT_SCHEMA_VERSION = "direct_kinase_evidence_audit.v1"
IPTMNET_BASE = "https://research.bioinformatics.udel.edu/iptmnet/api"
UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb"
USER_AGENT = "PTM-platform-strict-blind-direct-evidence-audit/1.0"

_BY_PATTERN = re.compile(r"by\s+(.+)", re.IGNORECASE)
_PTM_COMMENT_PATTERN = re.compile(
    r"(?:phosphorylated|ubiquitinated)\s+(?:at\s+)?(?:Ser|Thr|Tyr|Lys)-?(\d+)\s+by\s+([^.;]+)",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def queries_from_artifact(artifact: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    ptms: list[dict[str, Any]] = []
    for row in artifact.get("site_observations") or []:
        mapping = dict(row.get("mapping_evidence") or {})
        ptms.append(
            {
                "gene": row.get("gene"),
                "position": row.get("site"),
                "accession": mapping.get("accession"),
                "taxonomy_id": mapping.get("taxonomy_id"),
                "mapping_method": mapping.get("method"),
            }
        )
    return annotation_queries(ptms), len(ptms)


def parse_uniprot_exact_hits(
    entry: Mapping[str, Any],
    query: Mapping[str, Any],
    *,
    ptm_type: str = "phosphorylation",
) -> list[dict[str, Any]]:
    observed_positions = {str(value).upper() for value in (query.get("positions") or [])}
    numeric_to_observed: dict[int, list[str]] = {}
    for observed in observed_positions:
        digits = "".join(char for char in observed if char.isdigit())
        if digits:
            numeric_to_observed.setdefault(int(digits), []).append(observed)

    hits: list[dict[str, Any]] = []
    for feature in entry.get("features") or []:
        if feature.get("type") != "Modified residue":
            continue
        description = str(feature.get("description") or "")
        position = feature.get("location", {}).get("start", {}).get("value")
        try:
            position = int(position)
        except (TypeError, ValueError):
            continue
        description_lower = description.lower()
        if ptm_type == "phosphorylation" and "phosph" not in description_lower:
            continue
        if ptm_type == "ubiquitylation" and "ubiquit" not in description_lower:
            continue
        by_match = _BY_PATTERN.search(description)
        if position not in numeric_to_observed or not by_match:
            continue
        for observed_site in numeric_to_observed[position]:
            for kinase in extract_direct_kinase_names(
                by_match.group(1), substrate_gene=str(query.get("gene") or "")
            ):
                hits.append(
                    _hit_row(
                        query,
                        source="UniProt",
                        observed_site=observed_site,
                        kinase=kinase,
                        alignment="exact_numeric_position",
                        source_detail=description,
                    )
                )

    for comment in entry.get("comments") or []:
        if comment.get("commentType") != "PTM":
            continue
        for text_object in comment.get("texts") or []:
            text = str(text_object.get("value") or "")
            for match in _PTM_COMMENT_PATTERN.finditer(text):
                position = int(match.group(1))
                if position not in numeric_to_observed:
                    continue
                for observed_site in numeric_to_observed[position]:
                    for kinase in extract_direct_kinase_names(
                        match.group(2), substrate_gene=str(query.get("gene") or "")
                    ):
                        hits.append(
                            _hit_row(
                                query,
                                source="UniProt",
                                observed_site=observed_site,
                                kinase=kinase,
                                alignment="exact_numeric_position_ptm_comment",
                                source_detail=match.group(0),
                            )
                        )
    return _deduplicate_hits(hits)


def parse_iptmnet_exact_hits(
    sites: Iterable[Mapping[str, Any]],
    query: Mapping[str, Any],
    *,
    ptm_type: str = "phosphorylation",
) -> list[dict[str, Any]]:
    observed_positions = {str(value).upper() for value in (query.get("positions") or [])}
    expected_type = "phosphorylation" if ptm_type == "phosphorylation" else "ubiquitination"
    hits: list[dict[str, Any]] = []
    for site_entry in sites:
        source_site = str(site_entry.get("site") or "").upper()
        if source_site not in observed_positions:
            continue
        if expected_type not in str(site_entry.get("ptm_type") or "").lower():
            continue
        source_names = [
            str(source.get("name") or "")
            for source in (site_entry.get("sources") or [])
            if isinstance(source, Mapping)
        ]
        pmids = [str(value) for value in (site_entry.get("pmids") or [])][:5]
        for enzyme in site_entry.get("enzymes") or []:
            if not isinstance(enzyme, Mapping) or not enzyme.get("name"):
                continue
            hits.append(
                {
                    **_hit_row(
                        query,
                        source="iPTMnet_direct",
                        observed_site=source_site,
                        kinase=str(enzyme.get("name")),
                        alignment="exact_residue_position",
                        source_detail=", ".join(source_names),
                    ),
                    "enzyme_id": enzyme.get("id"),
                    "pmids": pmids,
                }
            )
    return _deduplicate_hits(hits)


def _hit_row(
    query: Mapping[str, Any],
    *,
    source: str,
    observed_site: str,
    kinase: str,
    alignment: str,
    source_detail: str,
) -> dict[str, Any]:
    return {
        "gene": query.get("gene"),
        "accession": query.get("accession"),
        "taxonomy_id": query.get("taxonomy_id"),
        "lookup_mode": query.get("lookup_mode"),
        "mapping_methods": list(query.get("mapping_methods") or []),
        "observed_site": observed_site,
        "kinase": kinase,
        "source": source,
        "direct_evidence": True,
        "site_alignment": alignment,
        "source_detail": source_detail,
    }


def _deduplicate_hits(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    retained: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("source") or ""),
            str(row.get("accession") or ""),
            str(row.get("observed_site") or ""),
            str(row.get("kinase") or "").upper(),
        )
        retained.setdefault(key, dict(row))
    return [retained[key] for key in sorted(retained)]


def link_exact_evidence_to_tmm(
    artifact: Mapping[str, Any],
    exact_site_evidence: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Require exact kinase identity and positive site contribution for timing use."""

    tmm = dict(artifact.get("tmm_full_temporal") or {})
    contribution_matrix = dict(
        tmm.get("relative_site_contribution_matrix")
        or tmm.get("tmm_site_contribution_matrix")
        or {}
    )
    profile_kinases = {
        str(score.get("kinase") or "").upper()
        for score in (tmm.get("kinase_scores") or [])
        if score.get("tmm_profile_values")
    }
    rows: list[dict[str, Any]] = []
    for hit in exact_site_evidence:
        kinase = str(hit.get("kinase") or "").upper()
        site_key = f"{hit.get('gene')}_{hit.get('observed_site')}"
        contributions = {
            str(candidate).upper(): float(value or 0.0)
            for candidate, value in dict(contribution_matrix.get(site_key) or {}).items()
        }
        profile_identity_match = kinase in profile_kinases
        positive_site_contribution = contributions.get(kinase, 0.0) > 0.0
        timing_anchor_eligible = profile_identity_match and positive_site_contribution
        rows.append(
            {
                "gene": hit.get("gene"),
                "observed_site": hit.get("observed_site"),
                "kinase": hit.get("kinase"),
                "source": hit.get("source"),
                "profile_identity_match": profile_identity_match,
                "positive_site_contribution": positive_site_contribution,
                "timing_anchor_eligible": timing_anchor_eligible,
                "site_contributions": contributions,
            }
        )
    return {
        "contract": "direct_evidence_to_tmm_linkage.v1",
        "exact_evidence_row_count": len(rows),
        "profile_identity_match_row_count": sum(row["profile_identity_match"] for row in rows),
        "positive_same_kinase_site_contribution_row_count": sum(
            row["positive_site_contribution"] for row in rows
        ),
        "timing_anchor_eligible_row_count": sum(row["timing_anchor_eligible"] for row in rows),
        "timing_status": "evaluable" if any(row["timing_anchor_eligible"] for row in rows) else "not_evaluable",
        "not_evaluable_reason": (
            None
            if any(row["timing_anchor_eligible"] for row in rows)
            else "no_exact_site_direct_evidence_linked_to_positive_same_kinase_tmm_contribution"
        ),
        "rows": rows,
    }


async def _request_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    retries: int = 2,
) -> tuple[int | None, Any]:
    for attempt in range(retries + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return 200, response.json()
            status = response.status_code
        except (httpx.HTTPError, ValueError):
            status = None
        if attempt < retries:
            await asyncio.sleep(0.5 * (2**attempt))
    return status, None


async def _probe_iptmnet(client: httpx.AsyncClient, queries: list[dict[str, Any]]) -> dict[str, Any]:
    accession = next((str(query.get("accession")) for query in queries if query.get("accession")), "P06213")
    status, _ = await _request_json(client, f"{IPTMNET_BASE}/{accession}/substrate", retries=2)
    return {
        "available": status == 200,
        "probe_accession": accession,
        "http_status": status,
        "status": "available" if status == 200 else f"unavailable_http_{status or 'error'}",
    }


async def _lookup_iptmnet(
    client: httpx.AsyncClient,
    query: Mapping[str, Any],
    *,
    ptm_type: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accession = str(query.get("accession") or "")
    status_codes: list[int | None] = []
    if not accession:
        params = {
            "search_term": query.get("gene"),
            "term_type": "All",
            "ptm_type": "Phosphorylation" if ptm_type == "phosphorylation" else "Ubiquitination",
            "role": "Substrate",
        }
        if query.get("taxonomy_id"):
            params["organism"] = query.get("taxonomy_id")
        status, search_data = await _request_json(client, f"{IPTMNET_BASE}/search", params=params)
        status_codes.append(status)
        if status != 200 or not isinstance(search_data, list) or not search_data:
            return [], {"statuses": status_codes, "resolved_accession": None}
        accession = str(
            next(
                (
                    entry.get("iptm_id")
                    for entry in search_data
                    if str(entry.get("gene_name") or "").upper() == str(query.get("gene") or "").upper()
                ),
                search_data[0].get("iptm_id"),
            )
            or ""
        )
    if not accession:
        return [], {"statuses": status_codes, "resolved_accession": None}
    await asyncio.sleep(0.3)
    status, payload = await _request_json(client, f"{IPTMNET_BASE}/{accession}/substrate")
    status_codes.append(status)
    sites = payload.get(accession, []) if status == 200 and isinstance(payload, Mapping) else []
    return parse_iptmnet_exact_hits(sites, query, ptm_type=ptm_type), {
        "statuses": status_codes,
        "resolved_accession": accession,
    }


async def _lookup_uniprot(
    client: httpx.AsyncClient,
    query: Mapping[str, Any],
    *,
    ptm_type: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accession = str(query.get("accession") or "")
    if accession:
        status, payload = await _request_json(
            client,
            f"{UNIPROT_BASE}/{accession}",
            params={"fields": "ft_mod_res,cc_ptm", "format": "json"},
        )
        resolved_accession = accession
    else:
        search_query = f"gene_exact:{query.get('gene')}"
        if query.get("taxonomy_id"):
            search_query += f" AND organism_id:{query.get('taxonomy_id')}"
        search_query += " AND reviewed:true"
        status, payload = await _request_json(
            client,
            f"{UNIPROT_BASE}/search",
            params={
                "query": search_query,
                "fields": "accession,ft_mod_res,cc_ptm",
                "format": "json",
                "size": "1",
            },
        )
        entries = payload.get("results", []) if status == 200 and isinstance(payload, Mapping) else []
        payload = entries[0] if entries else {}
        resolved_accession = str(payload.get("primaryAccession") or "")
    hits = parse_uniprot_exact_hits(payload or {}, query, ptm_type=ptm_type) if status == 200 else []
    return hits, {"status": status, "resolved_accession": resolved_accession or None}


async def run_audit(
    *,
    artifact_path: Path,
    ptm_type: str = "phosphorylation",
    batch_size: int = 5,
    batch_delay_seconds: float = 0.3,
) -> dict[str, Any]:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    queries, observed_site_count = queries_from_artifact(artifact)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    timeout = httpx.Timeout(30.0)
    hits: list[dict[str, Any]] = []
    source_status: dict[str, Any] = {}
    lookup_records: list[dict[str, Any]] = []

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        source_status["iPTMnet_direct"] = await _probe_iptmnet(client, queries)
        for offset in range(0, len(queries), batch_size):
            batch = queries[offset : offset + batch_size]
            uniprot_results = await asyncio.gather(
                *[_lookup_uniprot(client, query, ptm_type=ptm_type) for query in batch]
            )
            if source_status["iPTMnet_direct"]["available"]:
                iptmnet_results = await asyncio.gather(
                    *[_lookup_iptmnet(client, query, ptm_type=ptm_type) for query in batch]
                )
            else:
                iptmnet_results = [([], {"statuses": [], "resolved_accession": None}) for _ in batch]
            for query, (uniprot_hits, uniprot_meta), (iptmnet_hits, iptmnet_meta) in zip(
                batch, uniprot_results, iptmnet_results
            ):
                hits.extend(uniprot_hits)
                hits.extend(iptmnet_hits)
                lookup_records.append(
                    {
                        "gene": query.get("gene"),
                        "accession": query.get("accession"),
                        "taxonomy_id": query.get("taxonomy_id"),
                        "lookup_mode": query.get("lookup_mode"),
                        "positions": list(query.get("positions") or []),
                        "uniprot": uniprot_meta,
                        "iptmnet": iptmnet_meta,
                        "exact_hit_count": len(uniprot_hits) + len(iptmnet_hits),
                    }
                )
            if offset + batch_size < len(queries):
                await asyncio.sleep(batch_delay_seconds)

    hits = _deduplicate_hits(hits)
    uniprot_statuses = Counter(str(row["uniprot"].get("status")) for row in lookup_records)
    source_status["UniProt"] = {
        "status": "completed",
        "request_status_counts": dict(sorted(uniprot_statuses.items())),
    }
    matched_sites = {(row.get("gene"), row.get("observed_site")) for row in hits}
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "selection_boundary": {
            "benchmark_truth_used": False,
            "stimulus_identity_used": False,
            "rag_used": False,
            "llm_used": False,
            "input_scope": "Frozen strict-blind site observations and FASTA-derived accession/OX provenance only.",
        },
        "input": {
            "artifact": str(artifact_path),
            "artifact_sha256": sha256_file(artifact_path),
            "observed_site_count": observed_site_count,
        },
        "query_summary": {
            "query_count": len(queries),
            "accession_first_count": sum(query.get("lookup_mode") == "accession_first" for query in queries),
            "gene_fallback_count": sum(query.get("lookup_mode") == "gene_fallback" for query in queries),
            "taxonomy_counts": dict(sorted(Counter(str(query.get("taxonomy_id") or "unknown") for query in queries).items())),
        },
        "source_status": source_status,
        "evidence_summary": {
            "exact_direct_evidence_row_count": len(hits),
            "observed_site_with_exact_direct_evidence_count": len(matched_sites),
            "observed_site_with_exact_direct_evidence_fraction": len(matched_sites) / observed_site_count if observed_site_count else None,
            "source_counts": dict(sorted(Counter(str(row.get("source")) for row in hits).items())),
            "lookup_mode_counts": dict(sorted(Counter(str(row.get("lookup_mode")) for row in hits).items())),
            "taxonomy_counts": dict(sorted(Counter(str(row.get("taxonomy_id") or "unknown") for row in hits).items())),
        },
        "exact_site_evidence": hits,
        "lookup_records": lookup_records,
        "interpretation_boundary": (
            "Exact-site database evidence can anchor kinase-substrate annotation, but does not itself provide an observed kinase activity trajectory. "
            "Timing remains non-evaluable unless that direct kinase candidate is linked to an empirical or otherwise valid profile under the frozen TMM contract."
        ),
    }
