"""Shared freshness checks for production temporal sidecar reuse.

These checks are intentionally limited to versioned, user-data-derived Dynamic
Co-Wave metadata. They never read benchmark truth, workbook, RAG prose, or LLM
output. Keeping API preflight and Report-worker recovery on this same helper
prevents a stale semantic contract from being accepted by one path but rejected
by another.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("ptm_shared.temporal_sidecar_freshness")

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
from ptm_shared.kinase_candidate_allocation import (
    ALLOCATION_CONTRACT_VERSION as CURRENT_ALLOCATION_CONTRACT_VERSION,
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


def api_has_local_reference_bundle_access() -> bool:
    """Return whether this process can safely rebuild P1/P2 evidence locally.

    Production deployments may deliberately mount source bundles only in RAG
    workers.  An API process without every root and manifest must preserve a
    validated worker-built sidecar rather than serializing an M0/R0 fallback
    over it.  This check only validates local path availability; the importers
    remain responsible for manifest/hash/schema verification during a rebuild.
    """

    values = {
        "mapping_root": str(os.getenv("PTM_MAPPING_SNAPSHOT_ROOT") or "").strip(),
        "mapping_manifest": str(os.getenv("PTM_MAPPING_SOURCE_BUNDLE_PATH") or "").strip(),
        "relation_root": str(os.getenv("PTM_RELATION_SNAPSHOT_ROOT") or "").strip(),
        "relation_manifest": str(os.getenv("PTM_RELATION_SOURCE_BUNDLE_PATH") or "").strip(),
    }
    if not all(values.values()):
        return False
    try:
        mapping_root = Path(values["mapping_root"]).resolve()
        mapping_manifest = Path(values["mapping_manifest"]).resolve()
        relation_root = Path(values["relation_root"]).resolve()
        relation_manifest = Path(values["relation_manifest"]).resolve()
    except OSError:
        return False
    return (
        mapping_root.is_dir()
        and mapping_manifest.is_file()
        and mapping_root in mapping_manifest.parents
        and relation_root.is_dir()
        and relation_manifest.is_file()
        and relation_root in relation_manifest.parents
    )


def full_sidecar_has_validated_local_reference_bundles(full_sidecar: Mapping[str, Any]) -> bool:
    """Identify an immutable P1/P2 worker-built artifact eligible for preservation.

    This intentionally does not require P1 M1, P2 R3 or P3 allocation.  A
    M3-dominant/R1-only sidecar can be a valid production result and must not be
    replaced merely because source coverage is sparse.
    """

    ledger = full_sidecar.get("kinase_feature_evidence_ledger") or {}
    mapping = ledger.get("mapping_importer") or {}
    relation = ledger.get("relation_importer") or {}
    return (
        full_dynamic_is_current(full_sidecar)
        and isinstance(ledger, Mapping)
        and mapping.get("mapping_bundle_status") == "validated"
        and relation.get("relation_bundle_status") == "validated"
        and bool(mapping.get("mapping_bundle_sha256"))
        and bool(relation.get("relation_bundle_sha256"))
    )


def load_sidecar_json(path: Path) -> Any:
    """Load the first complete JSON value from a sidecar artifact.

    Concurrent writers can leave a valid document plus a trailing Extra data
    fragment. ``json.loads`` then fails and the API treats a validated P1/P2
    artifact as missing, which triggers an M0/R0 rebuild.
    """
    text = path.read_text(encoding="utf-8")
    obj, end = json.JSONDecoder().raw_decode(text)
    leftover = text[end:].strip()
    if leftover:
        logger.warning(
            "Ignoring trailing Extra data in %s after first JSON value "
            "(end=%s leftover_chars=%s)",
            path.name,
            end,
            len(leftover),
        )
    return obj


def load_preservable_local_reference_sidecar(artifact_path: Path) -> dict[str, Any] | None:
    """Load a validated P1/P2 full artifact without triggering reconstruction."""

    if not artifact_path.is_file():
        return None
    try:
        payload = load_sidecar_json(artifact_path)
    except (OSError, ValueError, TypeError):
        return None
    if isinstance(payload, Mapping) and full_sidecar_has_validated_local_reference_bundles(payload):
        return dict(payload)
    return None


def compact_dynamic_is_current(compact: Mapping[str, Any]) -> bool:
    """Return whether a DB/config compact sidecar uses the current semantics."""
    ledger_summary = compact.get("kinase_feature_evidence_ledger_summary") or {}
    mapping_readiness = ledger_summary.get("mapping_readiness") or {}
    relation_readiness = ledger_summary.get("relation_readiness") or {}
    allocation_readiness = ledger_summary.get("candidate_allocation_readiness") or {}
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
        and allocation_readiness.get("allocation_contract_version") == CURRENT_ALLOCATION_CONTRACT_VERSION
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
    candidate_allocation = ledger.get("candidate_allocation") or {}
    expected_mapping_bundle = _expected_mapping_bundle_sha256()
    expected_relation_bundle = _expected_relation_bundle_sha256()
    return (
        dynamic.get("contract_version") == CURRENT_DYNAMIC_CONTRACT_VERSION
        and provenance.get("config_sha256") == CURRENT_DYNAMIC_CONFIG_SHA256
        and ledger.get("contract_version") == CURRENT_KINASE_LEDGER_CONTRACT_VERSION
        and mapping_importer.get("mapping_importer_contract_version") == CURRENT_MAPPING_IMPORTER_CONTRACT_VERSION
        and relation_importer.get("relation_importer_contract_version") == CURRENT_RELATION_IMPORTER_CONTRACT_VERSION
        and candidate_allocation.get("allocation_contract_version") == CURRENT_ALLOCATION_CONTRACT_VERSION
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
            artifact = load_sidecar_json(artifact_path)
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
