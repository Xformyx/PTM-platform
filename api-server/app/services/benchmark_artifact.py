"""Build truth-free canonical Wave observations from a blind child Order.

This module consumes only normalized vector output and the child FASTA.  It
does not load a manifest, anchor, benchmark workbook, RAG collection, or LLM.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from Bio import SeqIO
from ptm_shared.enrichment_free_temporal_sidecar import build_v2_sidecar
from ptm_shared.temporal_optimization_config import (
    ADDITIVE_V2_CONFIG_SHA256,
    ADDITIVE_V2_CONTRACT_VERSION,
    CROSS_LAYER_CONFIG,
    DYNAMIC_COWAVE_CONFIG,
)
from ptm_shared.temporal_wave_engine import analyze_temporal_waves


def attach_v2_extensions(
    artifact: Mapping[str, Any],
    *,
    output_dir: Path,
    ptm_type: str,
    cross_layer_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an additive v2 artifact while preserving every v1 top-level value."""

    augmented = dict(artifact)
    augmented["extension_schema_versions"] = {
        "enrichment_free_temporal_mechanism": "v2.sidecar"
    }
    effective_cross_layer = dict(CROSS_LAYER_CONFIG if cross_layer_config is None else cross_layer_config)
    sidecar = build_v2_sidecar(
        output_dir=output_dir,
        ptm_type=ptm_type,
        site_observations=artifact.get("site_observations") or [],
        wave_contract=artifact.get("temporal_wave_contract") or {},
        tmm_result=artifact.get("tmm_full_temporal") or {},
        cross_layer_config=effective_cross_layer,
    )
    effective_sha256 = hashlib.sha256(
        json.dumps(effective_cross_layer, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    sidecar.setdefault("provenance", {})["frozen_config"] = {
        "contract_version": ADDITIVE_V2_CONTRACT_VERSION,
        "selected_config_applied": effective_cross_layer == CROSS_LAYER_CONFIG,
        "config_sha256": ADDITIVE_V2_CONFIG_SHA256 if effective_cross_layer == CROSS_LAYER_CONFIG else effective_sha256,
        "cross_layer": effective_cross_layer,
        "dynamic_cowave": dict(DYNAMIC_COWAVE_CONFIG),
        "dynamic_cowave_config_sha256": (
            (sidecar.get("dynamic_co_wave_transition") or {}).get("provenance") or {}
        ).get("config_sha256"),
        "selection_boundary": "Numeric time-course evidence only; locked workbook truth and identities were unavailable during selection.",
    }
    augmented["v2_extensions"] = sidecar
    augmented["compatibility"] = {
        "v1_top_level_fields_preserved": True,
        "v1_primary_score_contract_unchanged": True,
        "v2_scored_separately": True,
    }
    return augmented


def build_temporal_request(
    *, output_dir: Path,
    ptm_type: str,
    wave_config: Mapping[str, Any] | None = None,
    site_aggregation: str = "legacy_last",
    fasta_path: Path | None = None,
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
    replicate_time_series, replicate_wave_provenance = _load_replicate_wave_series(
        output_dir,
        ptm_type,
        grouped,
    )
    wave_contract = analyze_temporal_waves(
        site_time_series,
        timepoints,
        metadata=metadata,
        config=effective_wave_config,
        replicate_time_series=replicate_time_series,
    )
    wave_contract["replicate_input_provenance"] = replicate_wave_provenance
    cowave_modules = [
        {
            "id": wave["wave_id"],
            "label": f"Wave {wave['wave_id']} (peak: {wave['peak_timepoint']})",
            "ptm_keys": list(wave["members"]),
        }
        for wave in wave_contract.get("waves", [])
    ]
    fasta_index = _fasta_index(fasta_path) if fasta_path else {}
    ptms = []
    for item in grouped.values():
        mapping = _mapping_evidence(item, fasta_index) if fasta_index else {}
        ptms.append(
            {
                "gene": item["gene"],
                "position": item["site"],
                "accession": mapping.get("accession") or _accession(str(item.get("protein_group") or "")) or None,
                "taxonomy_id": mapping.get("taxonomy_id") or None,
                "mapping_method": mapping.get("method") or "not_evaluated",
                "sequence_match": mapping.get("sequence_match"),
                "isoform_match": mapping.get("isoform_match"),
                "species_match": mapping.get("species_match"),
            }
        )
    return {
        "ptms": ptms,
        "cowave_modules": cowave_modules,
        "wave_contract": wave_contract,
        "site_rows": grouped,
        "timepoints": timepoints,
        "site_aggregation": site_aggregation,
        "replicate_wave_provenance": replicate_wave_provenance,
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
    include_v2_extensions: bool = False,
    cross_layer_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    temporal = build_temporal_request(
        output_dir=output_dir,
        ptm_type=ptm_type,
        wave_config=wave_config,
        site_aggregation=site_aggregation,
        fasta_path=fasta_path,
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
    artifact = {
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
    if include_v2_extensions:
        artifact = attach_v2_extensions(
            artifact,
            output_dir=output_dir,
            ptm_type=ptm_type,
            cross_layer_config=cross_layer_config,
        )
    return artifact


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


def _load_replicate_wave_series(
    output_dir: Path,
    ptm_type: str,
    grouped_sites: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, list[float]]], dict[str, Any]]:
    """Build paired control-normalized replicate log2FC for consensus Wave.

    Duplicate precursor rows for the same site/sample are median aggregated.
    Replicates are paired by deterministic within-condition sample order, which
    matches the grouped-replicate optimization contract.
    """

    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    path = output_dir / f"site_level_relative_quantification_normalized{suffix}.tsv"
    if not path.is_file():
        return {}, {
            "contract": "temporal_wave_replicate_input.v1",
            "status": "unavailable",
            "reason": "site_level_relative_quantification_not_found",
        }
    protein_to_gene = {
        str(site.get("protein_group") or "").strip(): str(site.get("gene") or "").strip().upper()
        for site in grouped_sites.values()
        if site.get("protein_group") and site.get("gene")
    }
    raw: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    samples_by_condition: dict[str, set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            protein = str(row.get("Protein.Group") or "").strip()
            gene = protein_to_gene.get(protein, "")
            site = str(row.get("PTM_Position") or "").strip().upper()
            condition = str(row.get("Condition") or "").strip()
            sample = str(row.get("Sample") or "").strip()
            abundance = _optional_float(row.get("PTM_Relative_Abundance"))
            if not gene or not site or not condition or not sample or abundance is None or abundance <= 0:
                continue
            key = f"{gene}_{site}"
            if key not in grouped_sites:
                continue
            raw[(key, condition, sample)].append(abundance)
            samples_by_condition[condition].add(sample)
    aggregated = {
        key: statistics.median(values)
        for key, values in raw.items()
        if values
    }
    control_label = next(
        (condition for condition in samples_by_condition if condition.strip().lower() == "control"),
        None,
    )
    if not control_label:
        return {}, {
            "contract": "temporal_wave_replicate_input.v1",
            "status": "unavailable",
            "reason": "control_condition_not_found",
        }
    control_samples = sorted(samples_by_condition[control_label])
    replicate_series: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for site_key in grouped_sites:
        controls = [
            aggregated.get((site_key, control_label, sample))
            for sample in control_samples
        ]
        for condition, condition_samples_set in samples_by_condition.items():
            if condition == control_label:
                continue
            condition_samples = sorted(condition_samples_set)
            values = []
            for index, sample in enumerate(condition_samples):
                if index >= len(controls):
                    break
                control = controls[index]
                observed = aggregated.get((site_key, condition, sample))
                if control and observed and control > 0 and observed > 0:
                    values.append(math.log2(observed / control))
            if values:
                replicate_series[site_key][condition] = values
    replicate_counts = [
        len(values)
        for by_condition in replicate_series.values()
        for values in by_condition.values()
    ]
    return dict(replicate_series), {
        "contract": "temporal_wave_replicate_input.v1",
        "status": "available" if replicate_series else "unavailable",
        "source": path.name,
        "normalization": "paired_condition_to_control_log2_ratio",
        "duplicate_aggregation": "median_within_site_condition_sample",
        "site_count": len(replicate_series),
        "minimum_replicates": min(replicate_counts) if replicate_counts else 0,
        "maximum_replicates": max(replicate_counts) if replicate_counts else 0,
    }


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
