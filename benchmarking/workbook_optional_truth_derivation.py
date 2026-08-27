"""Derive runner-only optional benchmark truth from explicit workbook fields.

Only curated values already present in the analyst-provided workbook may be
copied.  This module never reads an analysis artifact and deliberately leaves
PTM→protein cross-layer and counterexample references empty when the workbook
does not state them explicitly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import sha256_file


def _tokenize_outputs(value: Any) -> list[str]:
    """Extract explicit protein-like targets, not prose or PTM-position fragments.

    The workbook output field is free text.  This intentionally conservative
    parser only copies token-shaped targets that are already written there; it
    never uses an analysis artifact to rescue, expand, or rank a token.
    """

    normalized = str(value or "").upper()
    normalized = re.sub(r"\b[A-Z0-9-]+-(?:MEDIATED|DEPENDENT)\b", " ", normalized)
    normalized = re.sub(r"\bP-([A-Z][A-Z0-9-]+)\b", r"\1", normalized)
    tokens = re.findall(r"\b[A-Z0-9][A-Z0-9-]{1,15}\b", normalized)
    excluded = {
        "NO", "AND", "OR", "OF", "TO", "USE", "HIGH", "MEDIUM", "LOW", "PIP3", "PY",
        "PST", "PS", "PT", "ACTIVATION", "INACTIVATION", "INHIBITION",
        "PHOSPHORYLATION", "DEPHOSPHORYLATION", "DIRECT", "PREFERRED",
        "OUTPUT", "OUTPUTS", "DOWNSTREAM", "UPSTREAM", "ANCHOR", "ANCHORS",
        "RECRUITMENT", "DEPENDENT", "MEDIATED", "SIGNALING", "PATHWAY",
        "SER", "THR", "TYR", "SITE", "SITES", "UNKNOWN",
    }
    protein_like = {
        token
        for token in tokens
        if token not in excluded
        and re.search(r"[A-Z]", token)
        and not re.fullmatch(r"P?[STY]\d+", token)
        and not re.fullmatch(r"P?[STY]", token)
    }
    return sorted(protein_like)


def _canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_workbook_mechanism_chains(
    kinase_reference: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Copy only explicit kinase-output tokens already curated in the workbook."""

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kinase_row in kinase_reference:
        kinase_id = str(kinase_row.get("Kinase_ID") or "").strip()
        kinase_label = str(kinase_row.get("Kinase_or_complex") or "").strip()
        source_ids = kinase_row.get("Source_IDs")
        for target in _tokenize_outputs(kinase_row.get("Direct_or_preferred_outputs")):
            identity = (kinase_id or kinase_label, target)
            if not identity[0] or identity in seen:
                continue
            seen.add(identity)
            digest = hashlib.sha256((identity[0] + "|" + target).encode("utf-8")).hexdigest()[:12]
            rows.append(
                {
                    "Chain_ID": f"WORKBOOK_KINASE_OUTPUT_{digest}",
                    "Kinase_ID": kinase_id or None,
                    "Kinase_or_complex": kinase_label,
                    "Target_gene": target,
                    "Required_output_tokens": target,
                    "Expected_direction": kinase_row.get("Expected_activity_direction"),
                    "Expected_time": kinase_row.get("Expected_time"),
                    "Evidence_tier": "workbook_curated_kinase_output",
                    "Reference": source_ids,
                    "Notes": "Derived only from Kinase_Reference.Direct_or_preferred_outputs; not an asserted PTM-to-protein cross-layer relation.",
                    "Reference_origin": "workbook_kinase_reference_direct_or_preferred_outputs",
                }
            )
    return rows


def derive_optional_truth_from_workbook(
    base_truth: Mapping[str, Any],
    *,
    workbook_path: str | Path,
) -> dict[str, Any]:
    """Return a child truth payload with workbook-evidence-only optional records."""

    workbook = Path(workbook_path).resolve()
    workbook_sha = sha256_file(workbook)
    parent_sha = str(base_truth.get("source_workbook_sha256") or "")
    if parent_sha and parent_sha != workbook_sha:
        raise ValueError("workbook SHA-256 does not match the locked parent truth")
    existing_optional = dict(base_truth.get("additive_v2_reference") or {})
    if any(existing_optional.get(key) for key in ("protein_effectors", "cross_layer_relations", "mechanism_chains", "counterexamples")):
        raise ValueError("base truth already has optional biological reference rows; refusing to overwrite")
    payload = copy.deepcopy(dict(base_truth))
    derived_chains = derive_workbook_mechanism_chains(
        [row for row in (base_truth.get("kinase_reference") or []) if isinstance(row, Mapping)]
    )
    payload["additive_v2_reference"] = {
        "protein_effectors": [],
        "cross_layer_relations": [],
        "mechanism_chains": derived_chains,
        "counterexamples": [],
        "source_sheets_present": [],
        "derivation_provenance": {
            "source": "analyst_provided_workbook.Kinase_Reference.Direct_or_preferred_outputs",
            "workbook_sha256": workbook_sha,
            "algorithm_artifact_read": False,
            "protein_effectors_derived": False,
            "cross_layer_relations_derived": False,
            "counterexamples_derived": False,
            "mechanism_chain_count": len(derived_chains),
            "claim_boundary": "Curated kinase-output pairs only; this is not curated PTM-to-protein cross-layer truth.",
        },
    }
    payload["workbook_optional_truth_derivation"] = {
        "parent_truth_sha256": _canonical_payload_hash(base_truth),
        "workbook_sha256": workbook_sha,
        "source_field": "Kinase_Reference.Direct_or_preferred_outputs",
        "forbidden_inputs": ["analysis_artifact", "prediction", "RAG", "LLM"],
        "empty_reference_types": ["protein_effectors", "cross_layer_relations", "counterexamples"],
    }
    payload["derived_truth_sha256"] = _canonical_payload_hash(payload)
    return payload


def provenance_summary(derived_truth: Mapping[str, Any]) -> dict[str, Any]:
    rows = list((derived_truth.get("additive_v2_reference") or {}).get("mechanism_chains") or [])
    origins = Counter(str(row.get("Reference_origin") or "unknown") for row in rows if isinstance(row, Mapping))
    return {
        "mechanism_chain_count": len(rows),
        "reference_origin_counts": dict(sorted(origins.items())),
        "protein_effector_reference_count": 0,
        "cross_layer_reference_count": 0,
        "counterexample_reference_count": 0,
        "claim_boundary": "Only workbook-curated kinase-output pairs were derived; no algorithm output was used as truth.",
    }
