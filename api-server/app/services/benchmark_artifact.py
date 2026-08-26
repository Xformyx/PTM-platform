"""Build truth-free canonical Wave observations from a blind child Order.

This module consumes only normalized vector output and the child FASTA.  It
does not load a manifest, anchor, benchmark workbook, RAG collection, or LLM.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from Bio import SeqIO
from ptm_shared.temporal_wave_engine import analyze_temporal_waves


def build_temporal_request(
    *, output_dir: Path,
    ptm_type: str,
    wave_config: Mapping[str, Any] | None = None,
    site_aggregation: str = "legacy_last",
) -> dict[str, Any]:
    rows = _read_vector_rows(output_dir, ptm_type)
    grouped = _group_rows(rows, site_aggregation=site_aggregation)
    timepoints = _sorted_timepoints(grouped.values())
    site_time_series = {
        key: {timepoint: site["values"].get(timepoint, 0.0) for timepoint in timepoints}
        for key, site in grouped.items()
    }
    metadata = {
        key: {
            "gene": item["gene"],
            "site": item["site"],
            "q_value": item["min_q_value"],
            "candidate_kinases": [],
        }
        for key, item in grouped.items()
    }
    effective_wave_config = dict(wave_config or {})
    effective_wave_config.setdefault(
        "threshold_source",
        "benchmark_tmm_full_temporal.v1",
    )
    wave_contract = analyze_temporal_waves(
        site_time_series,
        timepoints,
        metadata=metadata,
        config=effective_wave_config,
    )
    cowave_modules = [
        {
            "id": wave["wave_id"],
            "label": f"Wave {wave['wave_id']} (peak: {wave['peak_timepoint']})",
            "ptm_keys": list(wave["members"]),
        }
        for wave in wave_contract.get("waves", [])
    ]
    return {
        "ptms": [{"gene": item["gene"], "position": item["site"]} for item in grouped.values()],
        "cowave_modules": cowave_modules,
        "wave_contract": wave_contract,
        "site_rows": grouped,
        "timepoints": timepoints,
        "site_aggregation": site_aggregation,
    }


def build_score_artifact(
    *,
    output_dir: Path,
    fasta_path: Path,
    ptm_type: str,
    production_contract: Mapping[str, Any],
    tmm_result: Mapping[str, Any],
    wave_config: Mapping[str, Any] | None = None,
    site_aggregation: str = "legacy_last",
) -> dict[str, Any]:
    temporal = build_temporal_request(
        output_dir=output_dir,
        ptm_type=ptm_type,
        wave_config=wave_config,
        site_aggregation=site_aggregation,
    )
    fasta_index = _fasta_index(fasta_path)
    availability: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for site in temporal["site_rows"].values():
        evidence = _mapping_evidence(site, fasta_index)
        base = {
            "gene": site["gene"],
            "site": site["site"],
            "mapping_evidence": evidence,
        }
        availability.append({**base, "is_measurable": evidence["method"] == "sequence_isoform_species"})
        values = site["values"]
        peak_timepoint = max(values, key=lambda name: abs(values[name]))
        peak_value = values[peak_timepoint]
        threshold = 1.0 if site["has_q_values"] else 0.8
        regulated = abs(peak_value) >= threshold and (
            not site["has_q_values"] or (site["min_q_value"] is not None and site["min_q_value"] < 0.05)
        )
        observations.append(
            {
                **base,
                "detected": True,
                "regulated": regulated,
                "phosphorylation_direction": "up" if peak_value > 0 else "down" if peak_value < 0 else "neutral",
                "peak_minutes": _minutes(peak_timepoint),
                "peak_timepoint": peak_timepoint,
                "peak_log2fc": peak_value,
                "regulation_rule": "q_lt_0.05_and_abs_log2fc_ge_1.0" if site["has_q_values"] else "abs_log2fc_ge_0.8_no_q_value",
            }
        )
    return {
        "schema_version": "ptm_blind_analysis_artifact.v1",
        "site_availability": availability,
        "site_observations": observations,
        "branch_evidence": [],
        "temporal_wave_contract": temporal["wave_contract"],
        "tmm_full_temporal": dict(tmm_result),
        "provenance": {
            "production_contract": dict(production_contract),
            "source": "normalized_vector_data",
            "rag_used": False,
            "llm_used": False,
            "timepoints": temporal["timepoints"],
            "mapping_policy": "sequence_isoform_species_or_exclude",
        },
    }


def _read_vector_rows(output_dir: Path, ptm_type: str) -> list[dict[str, str]]:
    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    candidates = [
        output_dir / f"ptm_vector_data_normalized{suffix}.tsv",
        output_dir / f"ptm_vector_data_with_motifs{suffix}.tsv",
    ]
    vector_path = next((path for path in candidates if path.is_file()), None)
    if not vector_path:
        raise ValueError("normalized PTM vector output is not available")
    with vector_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _group_rows(
    rows: Iterable[Mapping[str, str]],
    *,
    site_aggregation: str = "legacy_last",
) -> dict[str, dict[str, Any]]:
    if site_aggregation not in {"legacy_last", "mean", "median"}:
        raise ValueError(f"unsupported site aggregation: {site_aggregation}")
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        gene = str(row.get("Gene.Name") or row.get("gene") or "").strip().upper()
        site = str(row.get("PTM_Position") or row.get("position") or "").strip().upper()
        condition = str(row.get("Condition") or row.get("condition") or "").strip()
        if not gene or not site or not condition:
            continue
        key = f"{gene}_{site}"
        entry = grouped.setdefault(
            key,
            {
                "gene": gene,
                "site": site,
                "values": {},
                "values_by_condition": defaultdict(list),
                "q_values": [],
                "protein_group": str(row.get("Protein.Group") or ""),
                "modified_sequence": str(row.get("Modified.Sequence") or ""),
                "fasta_taxonomy_id": str(row.get("FASTA_Taxonomy_ID") or ""),
            },
        )
        entry["values_by_condition"][condition].append(
            _float(row.get("PTM_Relative_Log2FC") or row.get("ptm_relative_log2fc"))
        )
        q_value = _optional_float(row.get("q_value"))
        if q_value is not None:
            entry["q_values"].append(q_value)
    for entry in grouped.values():
        for condition, values in entry.pop("values_by_condition").items():
            if site_aggregation == "mean":
                aggregated = sum(values) / len(values)
            elif site_aggregation == "median":
                aggregated = statistics.median(values)
            else:
                aggregated = values[-1]
            entry["values"][condition] = float(aggregated)
        entry["has_q_values"] = bool(entry["q_values"])
        entry["min_q_value"] = min(entry["q_values"]) if entry["q_values"] else None
    return grouped


def _sorted_timepoints(sites: Iterable[Mapping[str, Any]]) -> list[str]:
    labels = {label for site in sites for label in site["values"]}
    return sorted(labels, key=lambda label: (_minutes(label), label))


def _fasta_index(path: Path) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for record in SeqIO.parse(str(path), "fasta"):
        accession = _accession(record.id)
        taxon_match = re.search(r"\bOX=(\d+)", record.description)
        index[accession] = {"sequence": str(record.seq).upper(), "taxonomy_id": taxon_match.group(1) if taxon_match else ""}
    return index


def _mapping_evidence(site: Mapping[str, Any], fasta_index: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    accession = _accession(str(site.get("protein_group") or ""))
    record = fasta_index.get(accession)
    residue, position = _site_residue_position(str(site.get("site") or ""))
    peptide = _clean_peptide(str(site.get("modified_sequence") or ""))
    explicit_taxa = {taxon.strip() for taxon in str(site.get("fasta_taxonomy_id") or "").split(";") if taxon.strip()}
    # The normalized production vector predates FASTA_Taxonomy_ID.  The supplied
    # FASTA is nevertheless the trusted mapping authority: when a row has no
    # explicit taxonomy field, bind its expected taxon to the matched accession's
    # FASTA record.  This preserves per-record provenance for mixed-species
    # databases (for example, a host proteome plus one transgene) rather than
    # treating every otherwise exact sequence mapping as species-unresolved.
    expected_taxa = explicit_taxa or ({record["taxonomy_id"]} if record and record.get("taxonomy_id") else set())
    sequence_match = bool(record and residue and position and len(record["sequence"]) >= position and record["sequence"][position - 1] == residue and (not peptide or peptide in record["sequence"]))
    isoform_match = bool(record and accession)
    species_match = bool(record and record["taxonomy_id"] and record["taxonomy_id"] in expected_taxa)
    return {
        "method": "sequence_isoform_species" if sequence_match and isoform_match and species_match else "unresolved",
        "sequence_match": sequence_match,
        "isoform_match": isoform_match,
        "species_match": species_match,
        "accession": accession or None,
        "taxonomy_id": record["taxonomy_id"] if record else None,
        "species_provenance": "vector_taxonomy" if explicit_taxa else "trusted_fasta_record",
    }


def _accession(value: str) -> str:
    first = value.split(";")[0].strip()
    if "|" in first:
        parts = first.split("|")
        return parts[1].strip() if len(parts) >= 2 else first
    return first


def _site_residue_position(site: str) -> tuple[str, int]:
    match = re.fullmatch(r"([STY])(\d+)", site.replace(" ", ""))
    return (match.group(1), int(match.group(2))) if match else ("", 0)


def _clean_peptide(value: str) -> str:
    # DIA formats commonly encode a modified residue as ``S(Phospho)`` or
    # ``S[Phospho]``.  Some exports wrap the entire modified residue as
    # ``(S[Phospho])``; normalize that nested form first.
    cleaned = re.sub(r"\(([A-Z])(?:\[[^]]*\])?\)", r"\1", value.upper())
    cleaned = re.sub(r"([A-Z])\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"([A-Z])\[[^]]*\]", r"\1", cleaned)
    cleaned = re.sub(r"\([^)]*\)|\[[^]]*\]", "", cleaned)
    cleaned = re.sub(r"[^A-Z]", "", cleaned)
    return cleaned


def _minutes(label: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(sec|s|min|m|hr|h|hour|day|d)s?", str(label).strip(), re.I)
    if not match:
        return math.inf
    value, unit = float(match.group(1)), match.group(2).lower()
    return value / 60 if unit in {"sec", "s"} else value * 60 if unit in {"hr", "h", "hour"} else value * 1440 if unit in {"day", "d"} else value


def _float(value: Any) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else 0.0


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None
