"""External PTM-CoScientist Discussion Evidence Packet integration.

This node deliberately keeps PTM-platform observations separate from external
interpretive candidates.  It only consumes the versioned, read-only
``discussion_evidence_packet`` contract exposed by PTM-CoScientist.

Safety rules:
* Disabled by default through COSCIENTIST_ENABLED=false.
* A remote error, timeout, malformed packet, or empty packet never fails report generation.
* Only quality-gated candidates with observed PTM sites and re-resolved supporting
  literature are passed to the report writer.
* No ELO or tournament mechanics are retained in writer-facing data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from report_generation.core.rag_retriever import RAGRetriever

logger = logging.getLogger(__name__)

_SUPPORTED_SCHEMA = "1.0"
_PACKET_TYPE = "discussion_evidence_packet"
_DEFAULT_TIMEOUT_SECONDS = 20
_DEFAULT_MAX_HYPOTHESES = 2


def run_external_coscientist_context(state: dict) -> dict:
    """Load, validate, and snapshot a selected external Discussion Evidence Packet.

    The selected session is deliberately opt-in.  This node does not start a new
    remote research run; the scientist first runs Co-Scientist from the Order tab
    and explicitly selects a completed session for this report.
    """
    integration = state.get("co_scientist_integration") or {}
    if not _is_feature_enabled() or not integration.get("enabled"):
        return {
            "co_scientist_status": "disabled",
            "co_scientist_warning": None,
            "co_scientist_discussion_packet": None,
        }

    session_id = str(integration.get("session_id") or "").strip()
    mode = str(integration.get("mode") or "addendum").strip()
    if mode not in {"addendum", "enhanced_discussion"}:
        return _skipped("Unsupported Co-Scientist integration mode")
    if not session_id:
        return _skipped("No completed Co-Scientist session was selected")

    try:
        base_url = os.getenv(
            "COSCIENTIST_BASE_URL",
            os.getenv("COSCIENTIST_API_URL", "http://ptm-coscientist-api:8080"),
        ).rstrip("/")
        timeout = _read_int_env("COSCIENTIST_REQUEST_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
        max_hypotheses = min(
            2,
            max(1, int(integration.get("max_hypotheses") or _read_int_env("COSCIENTIST_MAX_HYPOTHESES", _DEFAULT_MAX_HYPOTHESES))),
        )

        session = _get_json(f"{base_url}/session/{urllib.parse.quote(session_id)}", timeout)
        terminal_status = str(session.get("status") or "").lower()
        if terminal_status != "completed":
            return _skipped(f"Selected Co-Scientist session status is '{terminal_status or 'unknown'}'", session_id)

        packet_url = (
            f"{base_url}/session/{urllib.parse.quote(session_id)}/discussion-packet?"
            f"max_hypotheses={max_hypotheses}"
        )
        packet = _get_json(packet_url, timeout)
        # Soft-skip non-ready packets (e.g. no_eligible_hypotheses) without failing the report.
        packet_status = str(packet.get("status") or "").lower()
        if packet_status and packet_status != "ready":
            return _skipped(f"Packet status is not ready: {packet.get('status')!r}", session_id, packet=packet)
        _validate_packet_contract(packet, session_id)

        verified_packet, verification = _verify_packet_against_platform_data(packet, state, max_hypotheses)
        if not verified_packet.get("selected_hypotheses"):
            reason = verification.get("reason") or "No eligible external candidates remained after PTM and literature verification"
            return _skipped(reason, session_id, packet=verified_packet)

        snapshot_path = _snapshot_packet(verified_packet, state.get("output_dir", ""), session_id)
        logger.info(
            "[CoScientist] Discussion packet ready: session=%s, candidates=%d, mode=%s, snapshot=%s",
            session_id,
            len(verified_packet["selected_hypotheses"]),
            mode,
            snapshot_path or "not-written",
        )
        return {
            "co_scientist_session_id": session_id,
            "co_scientist_discussion_packet": verified_packet,
            "co_scientist_status": "ready",
            "co_scientist_warning": None,
            "co_scientist_integration_mode": mode,
            "co_scientist_packet_snapshot": snapshot_path,
        }
    except Exception as exc:  # External integration is always isolated from the core report.
        status = "timed_out" if _is_timeout_error(exc) else "failed"
        logger.warning(
            "[CoScientist] External packet skipped without blocking report generation (%s): %s",
            status,
            exc,
        )
        return {
            "co_scientist_session_id": session_id,
            "co_scientist_discussion_packet": None,
            "co_scientist_status": status,
            "co_scientist_warning": _safe_error_message(exc),
            "co_scientist_integration_mode": mode,
        }


def build_external_coscientist_writer_context(state: dict) -> str:
    """Build a strict writer-only context block from a validated packet."""
    packet = state.get("co_scientist_discussion_packet") or {}
    if state.get("co_scientist_status") != "ready" or not packet.get("selected_hypotheses"):
        return ""

    lines = [
        "=== EXTERNAL CO-SCIENTIST DISCUSSION CANDIDATES ===",
        "These are evidence-gated, falsifiable interpretive candidates from a separate Co-Scientist session.",
        "They are NOT measured findings or validated causal conclusions.",
        "Use at most two candidates only where they directly align with measured PTM data.",
        "For every candidate used, explicitly state its limitation or counter-evidence in the same or adjacent paragraph.",
        "Use cautious language such as 'suggests', 'may', 'is consistent with', or 'warrants experimental testing'.",
        "Do NOT expose ELO ratings, tournament mechanics, or unsupported claims.",
        f"Session provenance: {packet.get('session_id', 'unknown')} | Goal: {packet.get('research_goal', 'not provided')}",
        "",
    ]

    for index, hypothesis in enumerate(packet.get("selected_hypotheses", [])[:2], 1):
        lines.extend(
            [
                f"Candidate CS-{index} (external id: {hypothesis.get('id', 'unknown')}; tier: {hypothesis.get('priority_tier', 'unspecified')}):",
                f"- Interpretive claim: {hypothesis.get('claim', '')}",
                f"- Linked observed PTM sites: {', '.join(hypothesis.get('supporting_ptm_sites', [])) or 'none'}",
                f"- Proposed signaling chain: {hypothesis.get('signaling_chain', 'not specified')}",
                f"- Re-verified data support: {_format_data_support(hypothesis.get('data_support', []))}",
                f"- Re-verified supporting literature: {_format_resolved_literature(hypothesis.get('resolved_literature', []))}",
                f"- Counter-evidence / limitations: {_format_limitations(hypothesis)}",
                f"- Testable prediction (Future Directions only): {hypothesis.get('testable_prediction', 'not specified')}",
                "",
            ]
        )

    lines.append("=== END EXTERNAL CO-SCIENTIST DISCUSSION CANDIDATES ===")
    return "\n".join(lines)


def build_external_coscientist_addendum(
    packet: dict,
    citation_map: Dict[str, int] | None = None,
) -> str:
    """Create a provenance-preserving, non-causal report addendum from a ready packet.

    When ``citation_map`` is provided (PMID/DOI/normalised-title → reference number),
    re-resolved literature lines include stable inline citations such as ``[3][7]``
    that match the final ``## References`` numbering.
    """
    if not packet or not packet.get("selected_hypotheses"):
        return ""

    lines = [
        "## Hypothesis & Validation Addendum: External Co-Scientist",
        "",
        "> **Interpretation boundary.** This addendum contains evidence-gated, falsifiable "
        "interpretive candidates generated by the external PTM-CoScientist service. It does not "
        "replace measured PTM observations, statistical results, or causal conclusions of this report.",
        "",
        f"**Session provenance:** `{packet.get('session_id', 'unknown')}`  ",
        f"**Research goal:** {packet.get('research_goal', 'not provided')}  ",
        f"**Packet schema:** {packet.get('schema_version', 'unknown')}  ",
        f"**Generated:** {packet.get('generated_at', 'unknown')}",
        "",
    ]

    for index, hypothesis in enumerate(packet.get("selected_hypotheses", [])[:2], 1):
        lit_items = hypothesis.get("resolved_literature", [])
        lit_text = _format_resolved_literature(lit_items)
        cite_suffix = _format_citation_markers(lit_items, citation_map)
        if cite_suffix:
            lit_text = f"{lit_text} {cite_suffix}".strip()
        lines.extend(
            [
                f"### Candidate {index}: {hypothesis.get('id', 'External hypothesis')}",
                "",
                f"**Interpretive candidate.** {hypothesis.get('claim', '')}",
                "",
                f"- **Priority tier:** {hypothesis.get('priority_tier', 'unspecified')}",
                f"- **Category:** {hypothesis.get('category', 'unspecified')}",
                f"- **Linked observed PTM sites:** {', '.join(hypothesis.get('supporting_ptm_sites', [])) or 'none'}",
                f"- **Candidate signaling chain:** {hypothesis.get('signaling_chain', 'not specified')}",
                f"- **Platform-reverified data support:** {_format_data_support(hypothesis.get('data_support', []))}",
                f"- **Platform-reresolved supporting literature:** {lit_text}",
                f"- **Counter-evidence / limitations:** {_format_limitations(hypothesis)}",
                f"- **Testable prediction:** {hypothesis.get('testable_prediction', 'not specified')}",
                "",
            ]
        )

    priorities = packet.get("experiment_priorities") or []
    if priorities:
        lines.extend(["### Limitations and Future Directions", ""])
        for item in priorities[:5]:
            if isinstance(item, dict):
                text = item.get("description") or item.get("title") or item.get("objective") or json.dumps(item, ensure_ascii=False)
            else:
                text = str(item)
            lines.append(f"- **Proposed validation experiment:** {text}")
        lines.append("")

    lines.extend(
        [
            "**Audit note.** Original Co-Scientist hypothesis lineage and debate mechanics are intentionally "
            "not reproduced here. Only quality-gated candidates whose PTM sites and supporting literature were "
            "rechecked by PTM-platform are included.",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_packet_against_platform_data(packet: dict, state: dict, max_hypotheses: int) -> Tuple[dict, dict]:
    """Filter packet candidates by quality gate, observed PTM sites, and re-resolved literature."""
    observed_sites = _observed_ptm_site_ids(state)
    retriever = RAGRetriever(collection_names=state.get("chromadb_collections") or [])
    verified_hypotheses = []
    excluded = []

    for hypothesis in packet.get("selected_hypotheses", []):
        if len(verified_hypotheses) >= max_hypotheses:
            break
        if not isinstance(hypothesis, dict):
            excluded.append("malformed hypothesis")
            continue
        gate = hypothesis.get("quality_gate") or {}
        if not isinstance(gate, dict) or gate.get("passed") is not True:
            excluded.append(f"{hypothesis.get('id', 'unknown')}: quality gate not passed")
            continue
        sites = [str(site) for site in hypothesis.get("supporting_ptm_sites", []) if str(site).strip()]
        matched_sites = [site for site in sites if _site_is_observed(site, observed_sites)]
        if not matched_sites:
            excluded.append(f"{hypothesis.get('id', 'unknown')}: no linked observed PTM site")
            continue

        resolved_literature = _resolve_supporting_literature(
            hypothesis.get("literature_evidence") or [], retriever
        )
        if not resolved_literature:
            excluded.append(f"{hypothesis.get('id', 'unknown')}: no supporting literature re-resolved")
            continue

        cleaned = {
            "id": str(hypothesis.get("id") or "unknown"),
            "priority_tier": str(hypothesis.get("priority_tier") or "exploratory"),
            "claim": str(hypothesis.get("claim") or ""),
            "category": str(hypothesis.get("category") or "integrative"),
            "supporting_ptm_sites": matched_sites,
            "signaling_chain": str(hypothesis.get("signaling_chain") or ""),
            "data_support": _validated_data_support(hypothesis.get("data_support") or [], matched_sites),
            "resolved_literature": resolved_literature,
            "counter_evidence": _identifier_backed_evidence(hypothesis.get("counter_evidence") or []),
            "limitations": [str(v) for v in hypothesis.get("limitations") or [] if str(v).strip()],
            "testable_prediction": str(hypothesis.get("testable_prediction") or ""),
            "lineage": hypothesis.get("lineage") or {},
            "quality_gate": {"passed": True},
        }
        if not cleaned["claim"] or not (cleaned["counter_evidence"] or cleaned["limitations"]):
            excluded.append(f"{cleaned['id']}: claim or limitation missing")
            continue
        verified_hypotheses.append(cleaned)

    verified_packet = {
        "schema_version": packet.get("schema_version"),
        "packet_type": packet.get("packet_type"),
        "session_id": packet.get("session_id"),
        "generated_at": packet.get("generated_at"),
        "source_orders": packet.get("source_orders") or [],
        "research_goal": packet.get("research_goal") or "",
        "ptm_type": packet.get("ptm_type") or "",
        "rag_collections": packet.get("rag_collections") or [],
        "status": "ready" if verified_hypotheses else "no_eligible_hypotheses",
        "usage_notice": packet.get("usage_notice") or "",
        "selected_hypotheses": verified_hypotheses,
        "experiment_priorities": packet.get("experiment_priorities") or [],
        "quality_summary": {
            **(packet.get("quality_summary") or {}),
            "platform_eligible_hypotheses": len(verified_hypotheses),
            "platform_excluded_candidates": excluded,
        },
    }
    return verified_packet, {
        "reason": "; ".join(excluded[:3]) if not verified_hypotheses else "",
        "excluded": excluded,
    }


def _resolve_supporting_literature(evidence_items: Iterable[Any], retriever: RAGRetriever) -> List[dict]:
    """Re-resolve external literature identifiers against PTM-platform ChromaDB.

    A title/PMID/DOI/evidence_id from the external packet is a retrieval hint, not
    a report citation.  This function only returns references that have a matching
    PTM-platform RAG result.
    """
    resolved = []
    seen = set()
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            continue
        title = str(evidence.get("title") or "").strip()
        pmid = str(evidence.get("pmid") or "").strip()
        doi = str(evidence.get("doi") or "").strip()
        evidence_id = str(evidence.get("evidence_id") or "").strip()
        collection = str(evidence.get("collection") or "").strip()
        if not title or not (pmid or doi or (evidence_id and collection)):
            continue
        try:
            candidates = retriever.query(title, n_results=5, relevance_threshold=0.15)
        except Exception as exc:
            logger.warning("[CoScientist] Literature re-resolution skipped for '%s': %s", title[:80], exc)
            continue
        match = next((candidate for candidate in candidates if _literature_matches(evidence, candidate)), None)
        if not match:
            continue
        metadata = match.get("metadata") or {}
        key = str(metadata.get("pmid") or pmid or metadata.get("doi") or doi or title).lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(
            {
                "title": match.get("title") or title,
                "pmid": str(metadata.get("pmid") or pmid),
                "doi": str(metadata.get("doi") or doi),
                "authors": str(metadata.get("authors") or evidence.get("authors") or ""),
                "year": str(metadata.get("year") or evidence.get("year") or ""),
                "journal": str(metadata.get("journal") or evidence.get("journal") or ""),
                "collection": match.get("collection") or collection,
                "relevance": match.get("relevance"),
            }
        )
    return resolved


def _literature_matches(evidence: dict, candidate: dict) -> bool:
    metadata = candidate.get("metadata") or {}
    evidence_pmid = str(evidence.get("pmid") or "").strip()
    evidence_doi = str(evidence.get("doi") or "").strip().lower()
    if evidence_pmid and str(metadata.get("pmid") or "").strip() == evidence_pmid:
        return True
    if evidence_doi and evidence_doi == str(metadata.get("doi") or "").strip().lower():
        return True
    return _normalise_title(evidence.get("title", "")) == _normalise_title(candidate.get("title", ""))


def _observed_ptm_site_ids(state: dict) -> set[str]:
    observed = set()
    rows = list(state.get("parsed_ptms") or []) + list(state.get("vector_plot_raw_data") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        gene = row.get("gene") or row.get("Gene") or row.get("Gene_Name") or row.get("Protein") or ""
        position = row.get("position") or row.get("Position") or row.get("PTM_Position") or row.get("site") or ""
        if gene:
            observed.add(_normalise_site(f"{gene}-{position}" if position else str(gene)))
    return observed


def _site_is_observed(site: str, observed: set[str]) -> bool:
    """Exact PTM-site match after normalisation.

    Accepts separator variants (``SRC-Y416``, ``SRC_Y416``, ``SRC:Y416``,
    ``SRC Y416``) but does *not* accept a different residue on the same gene
    (``SRC-Y999`` must not match when only ``SRC-Y416`` was observed).
    """
    normalised = _normalise_site(site)
    if not normalised:
        return False
    if normalised in observed:
        return True
    # Gene-only candidate may match gene-only observed rows
    if "-" not in normalised:
        return normalised in observed
    return False


def _validated_data_support(data_support: Iterable[Any], matched_sites: List[str]) -> List[dict]:
    validated = []
    for item in data_support:
        if isinstance(item, dict):
            site = str(item.get("site") or item.get("ptm_site") or item.get("gene") or "")
            if not site or any(_normalise_site(site) == _normalise_site(match) for match in matched_sites):
                validated.append({k: v for k, v in item.items() if k in {"site", "ptm_site", "condition", "fc", "log2fc", "pathway", "gene"}})
    return validated[:10]


def _identifier_backed_evidence(items: Iterable[Any]) -> List[dict]:
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("pmid") or item.get("doi") or (item.get("evidence_id") and item.get("collection")):
            result.append({k: v for k, v in item.items() if k in {"title", "pmid", "doi", "excerpt", "collection"}})
    return result[:5]


def _validate_packet_contract(packet: dict, expected_session_id: str) -> None:
    if not isinstance(packet, dict):
        raise ValueError("Malformed Co-Scientist Discussion Evidence Packet")
    if str(packet.get("schema_version")) != _SUPPORTED_SCHEMA:
        raise ValueError(f"Unsupported packet schema: {packet.get('schema_version')!r}")
    if packet.get("packet_type") != _PACKET_TYPE:
        raise ValueError(f"Unsupported packet type: {packet.get('packet_type')!r}")
    if packet.get("status") != "ready":
        raise ValueError(f"Packet status is not ready: {packet.get('status')!r}")
    if str(packet.get("session_id") or expected_session_id) != expected_session_id:
        raise ValueError("Packet session ID does not match selected session")
    if not isinstance(packet.get("selected_hypotheses"), list):
        raise ValueError("Packet selected_hypotheses must be a list")


def _get_json(url: str, timeout_seconds: int) -> dict:
    import socket

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
            data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from Co-Scientist API") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError("Co-Scientist API request timed out") from exc
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc) or exc)
        if _is_timeout_error(exc) or "timed out" in reason.lower():
            raise TimeoutError("Co-Scientist API request timed out") from exc
        raise RuntimeError(f"Co-Scientist API unavailable: {reason}") from exc


def _snapshot_packet(packet: dict, output_dir: str, session_id: str) -> str:
    if not output_dir:
        return ""
    try:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id)
        path = directory / f"coscientist_discussion_packet_{safe_id}.json"
        path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)
    except Exception as exc:
        logger.warning("[CoScientist] Could not save packet snapshot: %s", exc)
        return ""


def _skipped(reason: str, session_id: str = "", packet: dict | None = None) -> dict:
    logger.info("[CoScientist] Integration skipped: %s", reason)
    return {
        "co_scientist_session_id": session_id or None,
        "co_scientist_discussion_packet": packet,
        "co_scientist_status": "skipped",
        "co_scientist_warning": reason,
    }


def _is_feature_enabled() -> bool:
    return os.getenv("COSCIENTIST_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalise_site(value: Any) -> str:
    """Normalise PTM site identifiers to ``GENE-RESIDUE`` form.

    Handles common external/platform variants:
    ``SRC-Y416``, ``SRC_Y416``, ``SRC:Y416``, ``SRC Y416``, ``src/y416``.
    """
    text = str(value or "").strip().upper()
    if not text:
        return ""
    # Unify separators first (keep a single hyphen between gene and residue)
    text = re.sub(r"[\s_:/]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    # Compact form without separator: SRCY416 / AKT1S473
    if "-" not in text:
        m = re.match(r"^([A-Z0-9]+)([STYC]\d+[A-Z]?)$", text)
        if m:
            text = f"{m.group(1)}-{m.group(2)}"
    return text


def _normalise_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    try:
        import socket

        if isinstance(exc, socket.timeout):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    reason = str(getattr(exc, "reason", "") or "").lower()
    return "timed out" in msg or "timeout" in msg or "timed out" in reason or "timeout" in reason


def _safe_error_message(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc))[:300]


def _format_data_support(items: Iterable[Any]) -> str:
    parts = []
    for item in list(items)[:5]:
        if not isinstance(item, dict):
            continue
        site = item.get("site") or item.get("ptm_site") or item.get("gene") or "PTM"
        condition = item.get("condition") or ""
        fc = item.get("fc", item.get("log2fc", ""))
        parts.append(f"{site}{f' at {condition}' if condition else ''}{f' (FC={fc})' if fc != '' else ''}")
    return "; ".join(parts) or "No packet data-support detail retained"


def _format_resolved_literature(items: Iterable[Any]) -> str:
    parts = []
    for item in list(items)[:3]:
        if not isinstance(item, dict):
            continue
        identifier = item.get("pmid") or item.get("doi") or "PTM-platform RAG match"
        parts.append(f"{item.get('title', 'Untitled')} ({identifier})")
    return "; ".join(parts) or "No literature was re-resolved by PTM-platform"


def build_citation_map(collected_refs: Iterable[Any]) -> Dict[str, int]:
    """Map PMID / DOI / normalised title → 1-based reference index."""
    citation_map: Dict[str, int] = {}
    for idx, ref in enumerate(list(collected_refs or []), 1):
        if not isinstance(ref, dict):
            continue
        for raw in (ref.get("pmid"), ref.get("doi"), _normalise_title(ref.get("title"))):
            key = str(raw or "").strip().lower()
            if key and key not in citation_map:
                citation_map[key] = idx
    return citation_map


def _format_citation_markers(items: Iterable[Any], citation_map: Dict[str, int] | None) -> str:
    if not citation_map:
        return ""
    numbers: list[int] = []
    for item in list(items or [])[:5]:
        if not isinstance(item, dict):
            continue
        for raw in (item.get("pmid"), item.get("doi"), _normalise_title(item.get("title"))):
            key = str(raw or "").strip().lower()
            if key and key in citation_map:
                numbers.append(citation_map[key])
                break
    return "".join(f"[{n}]" for n in sorted(set(numbers)))


def build_integration_telemetry(state: dict) -> dict:
    """Compact status payload for Order UI / result_files / worker logs."""
    packet = state.get("co_scientist_discussion_packet") or {}
    quality = packet.get("quality_summary") or {}
    return {
        "status": state.get("co_scientist_status") or "disabled",
        "warning": state.get("co_scientist_warning"),
        "session_id": state.get("co_scientist_session_id"),
        "mode": state.get("co_scientist_integration_mode")
        or ((state.get("co_scientist_integration") or {}).get("mode")),
        "snapshot": state.get("co_scientist_packet_snapshot"),
        "eligible_hypotheses": len(packet.get("selected_hypotheses") or []),
        "excluded_candidates": quality.get("platform_excluded_candidates")
        or quality.get("excluded_candidates")
        or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_integration_telemetry(state: dict) -> str:
    """Persist telemetry JSON next to the report for operator debugging."""
    output_dir = state.get("output_dir") or ""
    if not output_dir:
        return ""
    payload = build_integration_telemetry(state)
    try:
        path = Path(output_dir) / "coscientist_integration_status.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)
    except Exception as exc:
        logger.warning("[CoScientist] Could not write integration telemetry: %s", exc)
        return ""


def _format_limitations(hypothesis: dict) -> str:
    limitations = [str(item) for item in hypothesis.get("limitations") or [] if str(item).strip()]
    counter = hypothesis.get("counter_evidence") or []
    if counter:
        limitations.append("Counter-evidence available from external evidence packet")
    return "; ".join(limitations) or "No limitation retained (candidate should not be used as a conclusion)"
