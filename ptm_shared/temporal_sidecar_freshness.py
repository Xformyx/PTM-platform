"""Shared freshness checks for production temporal sidecar reuse.

These checks are intentionally limited to versioned, user-data-derived Dynamic
Co-Wave metadata. They never read benchmark truth, workbook, RAG prose, or LLM
output. Keeping API preflight and Report-worker recovery on this same helper
prevents a stale semantic contract from being accepted by one path but rejected
by another.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ptm_shared.dynamic_cowave_transition import dynamic_transition_config_sha256
from ptm_shared.temporal_optimization_config import (
    DYNAMIC_COWAVE_CONFIG,
    DYNAMIC_COWAVE_CONTRACT_VERSION,
)
from ptm_shared.kinase_evidence_ledger import CONTRACT_VERSION as CURRENT_KINASE_LEDGER_CONTRACT_VERSION
from ptm_shared.species_site_mapping import (
    MAPPING_IMPORTER_CONTRACT_VERSION as CURRENT_MAPPING_IMPORTER_CONTRACT_VERSION,
)
from ptm_shared.kinase_relation_evidence import (
    RELATION_IMPORTER_CONTRACT_VERSION as CURRENT_RELATION_IMPORTER_CONTRACT_VERSION,
)


CURRENT_DYNAMIC_CONTRACT_VERSION = DYNAMIC_COWAVE_CONTRACT_VERSION
CURRENT_DYNAMIC_CONFIG_SHA256 = dynamic_transition_config_sha256(DYNAMIC_COWAVE_CONFIG)


def _expected_mapping_bundle_sha256() -> str | None:
    """Return an explicitly deployment-configured expected manifest hash, if any.

    This helper intentionally does not access the network or resolve a source
    bundle. Operators set ``PTM_MAPPING_BUNDLE_SHA256`` only after a local
    snapshot manifest has been acquired and verified. An absent value preserves
    explicit M0/no-bundle sidecars as reusable; a configured mismatch forces the
    normal canonical analysis path to rebuild the local mapping projection.
    """

    value = str(os.getenv("PTM_MAPPING_BUNDLE_SHA256") or "").strip().lower()
    return value if len(value) == 64 and all(char in "0123456789abcdef" for char in value) else None


def _expected_relation_bundle_sha256() -> str | None:
    """Return an optional operator-configured immutable P2 bundle manifest SHA-256."""

    value = str(os.getenv("PTM_RELATION_BUNDLE_SHA256") or "").strip().lower()
    return value if len(value) == 64 and all(char in "0123456789abcdef" for char in value) else None


def compact_dynamic_is_current(compact: Mapping[str, Any]) -> bool:
    """Return whether a DB/config compact sidecar uses the current semantics."""
    ledger_summary = compact.get("kinase_feature_evidence_ledger_summary") or {}
    mapping_readiness = ledger_summary.get("mapping_readiness") or {}
    relation_readiness = ledger_summary.get("relation_readiness") or {}
    expected_mapping_bundle = _expected_mapping_bundle_sha256()
    expected_relation_bundle = _expected_relation_bundle_sha256()
    return (
        compact.get("dynamic_co_wave_transition_contract_version")
        == CURRENT_DYNAMIC_CONTRACT_VERSION
        and compact.get("dynamic_co_wave_transition_config_sha256")
        == CURRENT_DYNAMIC_CONFIG_SHA256
        and ledger_summary.get("contract_version") == CURRENT_KINASE_LEDGER_CONTRACT_VERSION
        and mapping_readiness.get("mapping_importer_contract_version") == CURRENT_MAPPING_IMPORTER_CONTRACT_VERSION
        and relation_readiness.get("relation_importer_contract_version") == CURRENT_RELATION_IMPORTER_CONTRACT_VERSION
        and (expected_mapping_bundle is None or mapping_readiness.get("mapping_bundle_sha256") == expected_mapping_bundle)
        and (expected_relation_bundle is None or relation_readiness.get("relation_bundle_sha256") == expected_relation_bundle)
    )


def full_dynamic_is_current(full_sidecar: Mapping[str, Any]) -> bool:
    """Return whether a full sidecar carries the current Dynamic Co-Wave contract."""
    dynamic = full_sidecar.get("dynamic_co_wave_transition") or {}
    provenance = dynamic.get("provenance") or {}
    ledger = full_sidecar.get("kinase_feature_evidence_ledger") or {}
    mapping_importer = ledger.get("mapping_importer") or {}
    relation_importer = ledger.get("relation_importer") or {}
    expected_mapping_bundle = _expected_mapping_bundle_sha256()
    expected_relation_bundle = _expected_relation_bundle_sha256()
    return (
        dynamic.get("contract_version") == CURRENT_DYNAMIC_CONTRACT_VERSION
        and provenance.get("config_sha256") == CURRENT_DYNAMIC_CONFIG_SHA256
        and ledger.get("contract_version") == CURRENT_KINASE_LEDGER_CONTRACT_VERSION
        and mapping_importer.get("mapping_importer_contract_version") == CURRENT_MAPPING_IMPORTER_CONTRACT_VERSION
        and relation_importer.get("relation_importer_contract_version") == CURRENT_RELATION_IMPORTER_CONTRACT_VERSION
        and (expected_mapping_bundle is None or mapping_importer.get("mapping_bundle_sha256") == expected_mapping_bundle)
        and (expected_relation_bundle is None or relation_importer.get("relation_bundle_sha256") == expected_relation_bundle)
    )


def evaluate_temporal_evidence_readiness(
    *,
    compact_sources: tuple[tuple[str, Mapping[str, Any] | None], ...],
    artifact_path: Path,
) -> dict[str, Any]:
    """Evaluate whether an Order may reuse temporal evidence for a Report rerun.

    This pure helper is shared by API preflight tests and production dispatch.
    Any stale v1/config-mismatched sidecar deliberately becomes ``missing`` so
    canonical RAG preparation, rather than Report-local reconstruction, runs.
    """
    stale_sources: list[str] = []
    for source, container in compact_sources:
        if not isinstance(container, Mapping):
            continue
        sidecar = container.get("temporal_ptm_protein_analysis")
        if not isinstance(sidecar, Mapping) or not sidecar or sidecar.get("status") == "unavailable":
            continue
        if not compact_dynamic_is_current(sidecar):
            stale_sources.append(source)
            continue
        if sidecar.get("full_artifact_available"):
            return {
                "status": "ready",
                "source": source,
                "artifact": sidecar.get("artifact_path") or artifact_path.name,
                "dynamic_transition_status": sidecar.get("dynamic_co_wave_transition_status"),
                "dynamic_transition_contract_version": sidecar.get("dynamic_co_wave_transition_contract_version"),
                "message": "Canonical temporal evidence is ready for Report generation.",
                "stale_sources": stale_sources,
            }

    unreadable_error: str | None = None
    if artifact_path.is_file():
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            if isinstance(artifact, Mapping) and full_dynamic_is_current(artifact):
                dynamic = artifact.get("dynamic_co_wave_transition") or {}
                return {
                    "status": "ready",
                    "source": "production_artifact",
                    "artifact": artifact_path.name,
                    "dynamic_transition_status": dynamic.get("status"),
                    "dynamic_transition_contract_version": dynamic.get("contract_version"),
                    "message": "Canonical temporal evidence is ready for Report generation.",
                    "stale_sources": stale_sources,
                }
            if isinstance(artifact, Mapping):
                stale_sources.append("production_artifact")
        except (OSError, ValueError, TypeError) as error:
            unreadable_error = str(error)

    return {
        "status": "missing",
        "source": None,
        "artifact": None,
        "dynamic_transition_status": None,
        "dynamic_transition_contract_version": None,
        "required_dynamic_contract_version": CURRENT_DYNAMIC_CONTRACT_VERSION,
        "message": (
            "Temporal evidence uses an outdated Dynamic Co-Wave contract and will be rebuilt before Report generation."
            if stale_sources
            else "Temporal evidence is missing; canonical heatmap, TMM, and PTM–protein analysis will run before Report generation."
        ),
        "stale_sources": stale_sources,
        "unreadable_artifact_error": unreadable_error,
    }
