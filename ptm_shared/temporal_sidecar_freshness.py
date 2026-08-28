"""Shared freshness checks for production temporal sidecar reuse.

These checks are intentionally limited to versioned, user-data-derived Dynamic
Co-Wave metadata. They never read benchmark truth, workbook, RAG prose, or LLM
output. Keeping API preflight and Report-worker recovery on this same helper
prevents a stale semantic contract from being accepted by one path but rejected
by another.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ptm_shared.dynamic_cowave_transition import dynamic_transition_config_sha256
from ptm_shared.temporal_optimization_config import (
    DYNAMIC_COWAVE_CONFIG,
    DYNAMIC_COWAVE_CONTRACT_VERSION,
)


CURRENT_DYNAMIC_CONTRACT_VERSION = DYNAMIC_COWAVE_CONTRACT_VERSION
CURRENT_DYNAMIC_CONFIG_SHA256 = dynamic_transition_config_sha256(DYNAMIC_COWAVE_CONFIG)


def compact_dynamic_is_current(compact: Mapping[str, Any]) -> bool:
    """Return whether a DB/config compact sidecar uses the current semantics."""
    return (
        compact.get("dynamic_co_wave_transition_contract_version")
        == CURRENT_DYNAMIC_CONTRACT_VERSION
        and compact.get("dynamic_co_wave_transition_config_sha256")
        == CURRENT_DYNAMIC_CONFIG_SHA256
    )


def full_dynamic_is_current(full_sidecar: Mapping[str, Any]) -> bool:
    """Return whether a full sidecar carries the current Dynamic Co-Wave contract."""
    dynamic = full_sidecar.get("dynamic_co_wave_transition") or {}
    provenance = dynamic.get("provenance") or {}
    return (
        dynamic.get("contract_version") == CURRENT_DYNAMIC_CONTRACT_VERSION
        and provenance.get("config_sha256") == CURRENT_DYNAMIC_CONFIG_SHA256
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
