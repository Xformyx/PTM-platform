"""Evidence-tiered figure inventory, eligibility, and reader caption policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ptm_shared.de_novo_representation import is_de_novo_representation


FIGURE_MANIFEST_VERSION = "report_figure_manifest.v1"
SIGNED_PATTERN_THRESHOLD = 0.25
"""Main-figure signed temporal pattern bin.

docs/official_temporal_terminology_contract.md § Reader-facing selected-feature
heatmap encoding, declared 2026-09-07 before reuse as a display constant.
This is a reader-figure encoding, not a primary scientific threshold.
Do not treat the bin as activation, directness, or biological priority.
"""


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _available_path(value: Any) -> str:
    path = Path(str(value or ""))
    try:
        return str(path) if path.exists() and path.stat().st_size > 1000 else ""
    except OSError:
        return ""


class FigureEligibilityPolicy:
    """Fail-closed policy for researcher-facing Report figure placement."""

    def classify(self, figure: Mapping[str, Any], *, citation_complete: bool) -> tuple[str, str | None]:
        kind = str(figure.get("kind") or "")
        path = str(figure.get("image_path") or "")
        if kind not in {"reader_heatmap", "reader_temporal_profile", "reader_protein_context", "literature_comparison"} and not path:
            return "suppressed", "image_missing"
        if kind in {"dense_network", "kinase_diagnostic", "technical_atlas"}:
            return "technical_audit", "dense_or_diagnostic_visualization"
        if kind in {"context_map", "cascade_context"}:
            if not citation_complete:
                return "suppressed", "traceable_citations_unavailable"
            return "supplementary", "contextual_association_not_current_order_mechanism"
        if kind in {"pathway_membership", "full_temporal_atlas", "ranked_contrast_panel"}:
            return "supplementary", "not_a_narrow_current_order_result_figure"
        if kind == "reader_heatmap":
            count = int(figure.get("selected_feature_count") or 0)
            labels = bool(figure.get("labels_readable"))
            conventional_only = bool(figure.get("conventional_only"))
            if 12 <= count <= 20 and labels and conventional_only:
                return "main", None
            return "suppressed", "requires_12_to_20_readable_conventional_feature_cards"
        if kind == "reader_temporal_profile":
            profile_count = int(figure.get("selected_profile_count") or 0)
            cluster_count = int(figure.get("selected_cluster_count") or 0)
            if 3 <= profile_count <= 5 and 3 <= cluster_count <= 5 and bool(figure.get("labels_readable")):
                return "main", None
            return "supplementary", "requires_preselected_profile_and_cluster_cards"
        if kind == "reader_protein_context":
            if bool(figure.get("matched_protein_context")) and bool(figure.get("labels_readable")):
                return "main", None
            return "suppressed", "matched_protein_context_or_readable_labels_unavailable"
        if kind == "literature_comparison":
            return ("main", None) if citation_complete else ("suppressed", "traceable_citations_unavailable")
        return "supplementary", "unclassified_legacy_figure"


def _entry(
    figure_key: str,
    kind: str,
    image_path: str,
    *,
    question: str,
    evidence_tier: str,
    source_evidence_ids: list[str],
    caption_facts: Mapping[str, Any],
    selection_rule: str,
    **extra: Any,
) -> dict:
    return {
        "figure_key": figure_key,
        "kind": kind,
        "image_path": image_path,
        "evidence_tier": evidence_tier,
        "research_question": question,
        "data_scope": str(caption_facts.get("data_scope") or "recorded_current_order_evidence"),
        "selection_rule": selection_rule,
        "source_evidence_ids": source_evidence_ids,
        "citation_ids": list(caption_facts.get("citation_ids") or []),
        "caption_facts": dict(caption_facts),
        "required_caption_facts": ["question", "data_unit_scope", "visual_encoding", "selection_evidence_rule", "interpretation_boundary"],
        "forbidden_claims": ["activation", "direct_kinase_substrate", "causal_order", "isoform_specific_activity"],
        **extra,
    }


def select_reader_heatmap_features(vector_rows: list[Mapping[str, Any]], conditions: list[str], *, minimum: int = 12, maximum: int = 20) -> list[dict]:
    """Select complete conventional features by temporal shape, not effect magnitude.

    구현 대상: docs/official_temporal_terminology_contract.md § Reader-facing
    selected-feature heatmap encoding.
    사전등록: 2026-09-07 표시 계약. 결과 기반 primary 승격 아님.
    해석 한계: 선택된 행은 가독성 있는 관측 카드이며 우선순위 또는 직접성 순위가 아니다.
    주장 금지: 이 선택으로 kinase 예측이나 생물학적 중요도 향상을 주장하지 않는다.

    One lexical representative is retained per distinct signed time-course pattern,
    followed by lexical completion. This avoids a sole |Log2FC| ranking while
    supplying a reproducible, readable 12–20 feature display candidate set.
    """
    grouped: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for row in vector_rows or []:
        if not isinstance(row, Mapping) or is_de_novo_representation(row):
            continue
        gene = str(row.get("gene") or row.get("gene_name") or "").strip()
        site = str(row.get("position") or row.get("site") or "").strip()
        condition = str(row.get("condition") or "").strip()
        if not gene or not site or condition not in conditions:
            continue
        grouped.setdefault((gene.upper(), site), {})[condition] = row
    candidates: list[dict] = []
    for (gene, site), by_condition in grouped.items():
        if any(condition not in by_condition for condition in conditions):
            continue
        values: list[float] = []
        valid = True
        for condition in conditions:
            raw = by_condition[condition].get("ptm_relative_log2fc")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                valid = False
                break
            if value != value or abs(value) == float("inf"):
                valid = False
                break
            values.append(value)
        if not valid:
            continue
        pattern = "".join(
            "+" if value > SIGNED_PATTERN_THRESHOLD
            else "-" if value < -SIGNED_PATTERN_THRESHOLD
            else "0"
            for value in values
        )
        candidates.append({
            "gene": gene,
            "position": site,
            "conditions": list(conditions),
            "pattern_class": pattern,
            "selection_reason": "complete conventional temporal coverage; representative signed profile pattern; lexical tie-breaker",
        })
    candidates.sort(key=lambda item: (item["pattern_class"], item["gene"], item["position"]))
    selected: list[dict] = []
    seen_patterns: set[str] = set()
    for candidate in candidates:
        if candidate["pattern_class"] in seen_patterns:
            continue
        seen_patterns.add(candidate["pattern_class"])
        selected.append(candidate)
        if len(selected) >= maximum:
            break
    if len(selected) < minimum:
        selected_keys = {(item["gene"], item["position"]) for item in selected}
        for candidate in candidates:
            key = (candidate["gene"], candidate["position"])
            if key in selected_keys:
                continue
            selected.append(candidate)
            selected_keys.add(key)
            if len(selected) >= maximum:
                break
    return selected if len(selected) >= minimum else []


def build_figure_manifest(state: Mapping[str, Any], *, citation_complete: bool) -> dict:
    """Inventory current figure outputs and apply figure eligibility policy.

    구현 대상: docs/official_temporal_terminology_contract.md reader-facing
    figure wording; 2026-09-07 implementation_log figure-manifest contract.
    사전등록: 2026-09-07 표시 계약.
    해석 한계: placement는 본문 삽입 자격이며 경로 활성화나 인과를 보이지 않는다.
    주장 금지: manifest 항목 수를 kinase 활성 또는 네트워크 증명으로 해석하지 않는다.
    """
    policy = FigureEligibilityPolicy()
    network = _mapping(state.get("network_analysis"))
    entries: list[dict] = []
    vector_rows = [row for row in state.get("vector_plot_raw_data") or [] if isinstance(row, Mapping)]
    heatmap = _mapping(state.get("kinase_activity_heatmap"))
    conditions = [str(value) for value in heatmap.get("conditions") or network.get("timepoints") or [] if str(value).strip()]
    if not conditions:
        conditions = sorted({str(row.get("condition") or "") for row in vector_rows if str(row.get("condition") or "")})
    selected_features = select_reader_heatmap_features(vector_rows, conditions)
    if selected_features or vector_rows:
        entries.append(_entry(
            "reader_quantitative_heatmap", "reader_heatmap", "",
            question="Which selected quantitative phosphorylation features show distinct measured profiles across sampled timepoints?",
            evidence_tier="O1", source_evidence_ids=["quantitative.landscape", "temporal.profile_summary"],
            caption_facts={
                "data_scope": "conventional quantified phosphorylation features with complete selected time-course coverage",
                "data_unit_scope": "phosphorylation feature aggregate",
                "visual_encoding": "diverging conventional Log2FC color scale",
                "interpretation_boundary": "measured contrast is not activation, directness, or biological-priority score; de novo rows are excluded from the numeric color scale",
            },
            selection_rule="complete conventional temporal coverage; representative signed profile pattern; lexical tie-breaker",
            selected_feature_count=len(selected_features), labels_readable=True, conventional_only=True,
            selected_features=selected_features,
        ))
    pathway = _available_path(network.get("pathway_graph_path"))
    if pathway:
        entries.append(_entry(
            "pathway_membership", "pathway_membership", pathway,
            question="Which pathway-membership categories provide descriptive context for observed features?",
            evidence_tier="O1", source_evidence_ids=["quantitative.landscape"],
            caption_facts={"data_unit_scope": "pathway-member feature set", "visual_encoding": "descriptive membership enrichment", "interpretation_boundary": "not pathway activation or kinase activity"},
            selection_rule="current pathway-membership renderer",
        ))
    for index, figure in enumerate(state.get("comovement_figures") or [], 1):
        record = _mapping(figure)
        figure_type = str(record.get("type") or "")
        kind = "full_temporal_atlas" if "heatmap" in figure_type else "reader_temporal_profile"
        entries.append(_entry(
            f"temporal.{index}", kind, _available_path(record.get("path")),
            question="How do measured phosphorylation-feature profiles differ across sampled timepoints?",
            evidence_tier="O2", source_evidence_ids=["temporal.profile_summary"],
            caption_facts={"data_unit_scope": "conventional quantified phosphorylation features", "visual_encoding": "temporal profile display", "interpretation_boundary": "descriptive pattern, not common regulation or causal order"},
            selection_rule="legacy temporal renderer; reader-card eligibility not yet confirmed",
            selected_profile_count=0, selected_cluster_count=0, labels_readable=False,
        ))
    for index, figure in enumerate(state.get("signal_flow_figures") or [], 1):
        record = _mapping(figure)
        figure_type = str(record.get("type") or "")
        if figure_type == "kinase_heatmap":
            kind = "kinase_diagnostic"
        elif figure_type in {"pathway_diagram", "signal_flow", "signal_flow_supplementary"}:
            kind = "context_map"
        else:
            kind = "technical_atlas"
        entries.append(_entry(
            f"signal_flow.{index}", kind, _available_path(record.get("path")),
            question="What visual context is available for observed PTM and protein patterns?",
            evidence_tier="C1" if kind == "kinase_diagnostic" else "L1",
            source_evidence_ids=["kinase.context" if kind == "kinase_diagnostic" else "literature.context"],
            caption_facts={"data_unit_scope": "candidate or literature-context visualization", "visual_encoding": "contextual annotations", "interpretation_boundary": "not direct regulation, activation, or causal flow"},
            selection_rule="legacy signaling renderer",
        ))
    for index, (_, path) in enumerate(sorted(_mapping(network.get("network_images")).items()), 1):
        entries.append(_entry(
            f"network.{index}", "dense_network", _available_path(path),
            question="Which complete network topology is retained for technical review?",
            evidence_tier="technical", source_evidence_ids=["network.topology"],
            caption_facts={"data_unit_scope": "full network topology", "visual_encoding": "dense graph", "interpretation_boundary": "technical atlas, not a causal model"},
            selection_rule="complete network renderer",
        ))
    for entry in entries:
        placement, reason = policy.classify(entry, citation_complete=citation_complete)
        entry["placement"] = placement
        entry["suppression_reason"] = reason
    return {"contract_version": FIGURE_MANIFEST_VERSION, "figures": entries}


def attach_reader_heatmap(manifest: Mapping[str, Any], image_path: str, selected_features: list[Mapping[str, Any]]) -> dict:
    """Add the narrow conventional selected-feature heatmap and classify it."""
    result = {
        **dict(manifest),
        "figures": [
            dict(item) for item in manifest.get("figures") or []
            if str(item.get("figure_key") or "") != "reader_quantitative_heatmap"
        ],
    }
    facts = {
        "data_scope": "conventional quantified phosphorylation features with complete selected time-course coverage",
        "data_unit_scope": "phosphorylation feature aggregate",
        "visual_encoding": "diverging conventional Log2FC color scale; missingness notation in source renderer",
        "interpretation_boundary": "measured contrast is not activation, directness, or biological-priority score; de novo rows are excluded from the numeric color scale",
    }
    entry = _entry(
        "reader_quantitative_heatmap", "reader_heatmap", image_path,
        question="Which selected quantitative phosphorylation features show distinct measured profiles across sampled timepoints?",
        evidence_tier="O1", source_evidence_ids=["quantitative.landscape", "temporal.profile_summary"],
        caption_facts=facts,
        selection_rule="complete conventional temporal coverage; representative signed profile pattern; lexical tie-breaker",
        selected_feature_count=len(selected_features), labels_readable=True, conventional_only=True,
        selected_features=[dict(item) for item in selected_features],
    )
    placement, reason = FigureEligibilityPolicy().classify(entry, citation_complete=False)
    entry["placement"] = placement
    entry["suppression_reason"] = reason
    result["figures"].append(entry)
    return result


def figure_cards_from_manifest(manifest: Mapping[str, Any]) -> list[dict]:
    """Return only eligible reader-facing figure cards for the scientific author."""
    cards: list[dict] = []
    for figure in manifest.get("figures") or []:
        if not isinstance(figure, Mapping) or figure.get("placement") not in {"main", "supplementary"}:
            continue
        cards.append({
            "figure_key": figure.get("figure_key"),
            "placement": figure.get("placement"),
            "question": figure.get("research_question"),
            "reader_summary": (
                f"{figure.get('kind')} selected under {figure.get('selection_rule')}"
            ),
            "allowed_interpretation": "descriptive temporal pattern or cited external context",
            "forbidden_interpretation": "activation, direct kinase–substrate relation, causal order, isoform-specific activity",
            "citation_ids": list(figure.get("citation_ids") or []),
            "source_evidence_ids": list(figure.get("source_evidence_ids") or []),
        })
    return cards


def compile_reader_caption(figure: Mapping[str, Any]) -> str:
    """Compile mandatory factual caption clauses for a reader-facing figure."""
    facts = _mapping(figure.get("caption_facts"))
    question = str(figure.get("research_question") or "").strip()
    scope = str(facts.get("data_scope") or facts.get("data_unit_scope") or "recorded evidence").strip()
    encoding = str(facts.get("visual_encoding") or "display encoding").strip()
    rule = str(figure.get("selection_rule") or "pre-specified manifest selection").strip()
    boundary = str(facts.get("interpretation_boundary") or "interpretation is bounded by the stated evidence tier").strip()
    return f"Question: {question} Data unit and scope: {scope}. Visual encoding: {encoding}. Selection rule: {rule}. Interpretation boundary: {boundary}."
