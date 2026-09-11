"""Evidence-tiered figure inventory, eligibility, and reader caption policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ptm_shared.de_novo_representation import is_de_novo_representation
from report_generation.core.measured_feature_cards import (
    build_quantitation_comparison_cards,
    reader_feature_id,
)


FIGURE_MANIFEST_VERSION = "report_figure_manifest.v3"
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
        if kind == "reader_concordance":
            cluster_count = int(figure.get("selected_cluster_count") or 0)
            if 3 <= cluster_count <= 8 and bool(figure.get("labels_readable")):
                return "main", None
            return "suppressed", "requires_3_to_8_readable_cluster_transition_summaries"
        if kind == "reader_protein_context":
            matched_count = int(figure.get("matched_feature_count") or 0)
            if matched_count >= 2 and bool(figure.get("matched_protein_context")) and bool(figure.get("labels_readable")):
                return "main", None
            if matched_count == 1 and bool(figure.get("matched_protein_context")) and bool(figure.get("labels_readable")):
                return "supplementary", "single_complete_comparison_retained_as_supplementary_context"
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
    grouped: dict[tuple[str, str, str, str], dict[str, list[Mapping[str, Any]]]] = {}
    for row in vector_rows or []:
        if not isinstance(row, Mapping) or is_de_novo_representation(row):
            continue
        gene = str(row.get("gene") or row.get("gene_name") or "").strip()
        site = str(row.get("position") or row.get("site") or "").strip()
        precursor = str(row.get("Precursor.Id") or row.get("precursor_id") or row.get("source_feature_id") or "").strip()
        sequence = str(row.get("Modified.Sequence") or row.get("modified_sequence") or "").strip()
        condition = str(row.get("condition") or "").strip()
        if not gene or not site or not (precursor or sequence) or condition not in conditions:
            continue
        grouped.setdefault((gene.upper(), site, precursor, sequence), {}).setdefault(condition, []).append(row)
    candidates: list[dict] = []
    for key, by_condition in grouped.items():
        gene, site, precursor, sequence = key
        if any(condition not in by_condition or len(by_condition[condition]) != 1 for condition in conditions):
            continue
        values: list[float] = []
        valid = True
        for condition in conditions:
            raw = by_condition[condition][0].get("ptm_relative_log2fc")
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
        feature_id = reader_feature_id(key)
        candidates.append({
            "gene": gene,
            "position": site,
            "source_feature_id": precursor or None,
            "modified_sequence": sequence or None,
            "reader_feature_id": feature_id,
            "display_label": f"{feature_id} · {gene} {site}",
            "conditions": list(conditions),
            "pattern_class": pattern,
            "selection_reason": "unique modified-precursor identity; complete conventional temporal coverage; representative signed profile pattern; lexical tie-breaker",
        })
    candidates.sort(key=lambda item: (item["pattern_class"], item["reader_feature_id"]))
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
        selected_keys = {item["reader_feature_id"] for item in selected}
        for candidate in candidates:
            key = candidate["reader_feature_id"]
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


def _select_cluster_figures(state: Mapping[str, Any], *, minimum: int = 3, maximum: int = 5) -> list[dict]:
    """Select readable cluster plots by distinct temporal pattern, never magnitude."""
    analysis = _mapping(state.get("comovement_analysis"))
    clusters = [dict(row) for row in analysis.get("clusters") or [] if isinstance(row, Mapping)]
    metadata: dict[str, dict] = {}
    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or cluster.get("wave_id") or cluster.get("id") or "")
        if cluster_id:
            metadata[cluster_id] = cluster
    candidates: list[dict] = []
    for record in state.get("comovement_figures") or []:
        figure = _mapping(record)
        if str(figure.get("type") or "") not in {"cluster_detail", "supplementary_cluster"}:
            continue
        path = _available_path(figure.get("path"))
        cluster_id = str(figure.get("cluster_id") or "")
        if not path or not cluster_id:
            continue
        cluster = metadata.get(cluster_id, {})
        pattern = str(cluster.get("pattern") or cluster.get("pattern_type") or "unclassified")
        members = []
        for member in cluster.get("member_details") or []:
            if not isinstance(member, Mapping):
                continue
            if str(member.get("activity_class") or "").lower() == "de_novo" or bool(member.get("control_pseudocount_used")):
                continue
            gene = str(member.get("gene") or "").strip()
            site = str(member.get("site") or member.get("position") or "").strip()
            label = " ".join(part for part in (gene, site) if part).strip() or str(member.get("key") or "").strip()
            if label:
                members.append(label)
        candidates.append({
            "path": path,
            "cluster_id": cluster_id,
            "pattern": pattern,
            "caption": str(figure.get("caption") or ""),
            "representative_members": sorted(set(members))[:3],
        })
    candidates.sort(key=lambda item: (item["pattern"], item["cluster_id"]))
    selected: list[dict] = []
    seen_patterns: set[str] = set()
    for candidate in candidates:
        if candidate["pattern"] in seen_patterns:
            continue
        selected.append(candidate)
        seen_patterns.add(candidate["pattern"])
        if len(selected) >= maximum:
            break
    if len(selected) < minimum:
        selected_ids = {item["cluster_id"] for item in selected}
        for candidate in candidates:
            if candidate["cluster_id"] in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate["cluster_id"])
            if len(selected) >= maximum:
                break
    return selected if len(selected) >= minimum else []


def _compose_cluster_panel(selected: list[Mapping[str, Any]], output_dir: str) -> str:
    """Stitch pre-rendered cluster plots into one bounded reader panel."""
    if not selected or not output_dir:
        return ""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""
    opened = []
    try:
        for item in selected:
            image = Image.open(str(item.get("path"))).convert("RGB")
            image.thumbnail((980, 650))
            opened.append((item, image.copy()))
        if not opened:
            return ""
        columns = 2
        rows = (len(opened) + columns - 1) // columns
        cell_width = max(image.width for _, image in opened) + 36
        cell_height = max(image.height for _, image in opened) + 82
        canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(canvas)
        for index, (item, image) in enumerate(opened):
            row, column = divmod(index, columns)
            x = column * cell_width + 18
            y = row * cell_height + 54
            pattern = str(item.get("pattern") or "unclassified").replace("_", " ")
            draw.text(
                (x, 10 + row * cell_height),
                f"{chr(65 + index)}  Temporal Profile Cluster {index + 1} · {pattern}",
                fill="black",
            )
            member_text = ", ".join(str(value) for value in item.get("representative_members") or [])
            if member_text:
                draw.text(
                    (x, 30 + row * cell_height),
                    f"Representative measured members (lexical): {member_text}",
                    fill="#4B5563",
                )
            canvas.paste(image, (x, y))
        path = Path(output_dir) / "reader_temporal_profile_clusters.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(path, format="PNG", optimize=True)
        return _available_path(path)
    except Exception:
        return ""
    finally:
        for _, image in opened:
            try:
                image.close()
            except Exception:
                pass


def _dynamic_transition_rows(state: Mapping[str, Any]) -> list[dict]:
    temporal = _mapping(state.get("temporal_ptm_protein_analysis"))
    dynamic = _mapping(temporal.get("dynamic_co_wave_transition"))
    rows = temporal.get("dynamic_transition_per_wave") or dynamic.get("per_wave_summary") or []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _generate_concordance_summary(
    state: Mapping[str, Any],
    output_dir: str,
    selected_cluster_ids: list[str],
) -> tuple[str, list[str]]:
    """Plot retained/gain/loss rates by cluster and adjacent sampled interval."""
    rows = _dynamic_transition_rows(state)
    if not rows or not output_dir:
        return "", []
    selected_set = {str(value) for value in selected_cluster_ids if str(value)}
    matched = [
        row for row in rows
        if not selected_set or str(row.get("static_wave_id") or row.get("cluster_id") or "") in selected_set
    ]
    if len(matched) < 3:
        matched = sorted(rows, key=lambda row: str(row.get("static_wave_id") or row.get("cluster_id") or ""))[:8]
    cluster_rank = {str(cluster_id): index for index, cluster_id in enumerate(selected_cluster_ids)}
    matched.sort(key=lambda row: (
        cluster_rank.get(str(row.get("static_wave_id") or row.get("cluster_id") or ""), len(cluster_rank)),
        str(row.get("from_window") or ""),
        str(row.get("to_window") or ""),
    ))
    matched = matched[:8]
    labels: list[str] = []
    denominators: list[int] = []
    included_cluster_ids: list[str] = []
    retained: list[float] = []
    gained: list[float] = []
    lost: list[float] = []
    cluster_order = {
        str(cluster_id): index + 1
        for index, cluster_id in enumerate(selected_cluster_ids)
        if str(cluster_id)
    }
    for row in matched:
        rates = _mapping(row.get("concordance_change_rates"))
        denominator = int(row.get("evaluable_pair_window_comparison_count") or 0)
        if denominator <= 0 or not rates:
            continue
        from_window = str(row.get("from_window") or "")
        to_window = str(row.get("to_window") or "")
        cluster_id = str(row.get("static_wave_id") or row.get("cluster_id") or "")
        cluster_number = cluster_order.get(cluster_id)
        if cluster_number is None:
            cluster_number = len(cluster_order) + 1
            cluster_order[cluster_id] = cluster_number
        labels.append(f"Cluster {cluster_number}\n{from_window} | {to_window}")
        denominators.append(denominator)
        if cluster_id and cluster_id not in included_cluster_ids:
            included_cluster_ids.append(cluster_id)
        retained.append(float(rates.get("retained") or 0.0))
        gained.append(float(rates.get("gain") or 0.0))
        lost.append(float(rates.get("loss") or 0.0))
    if len(labels) < 3:
        return "", []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        x = np.arange(len(labels))
        fig, ax = plt.subplots(figsize=(max(8.5, len(labels) * 1.25), 5.4))
        ax.bar(x, retained, label="Retained", color="#4C78A8")
        ax.bar(x, gained, bottom=retained, label="Gain", color="#59A14F")
        stacked = np.array(retained) + np.array(gained)
        ax.bar(x, lost, bottom=stacked, label="Loss", color="#E15759")
        totals = np.array(retained) + np.array(gained) + np.array(lost)
        for index, denominator in enumerate(denominators):
            classified = int(round(float(totals[index]) * denominator))
            ax.text(
                x[index],
                min(float(totals[index]) + 0.025, 0.97),
                f"{classified}/{denominator}",
                ha="center",
                va="bottom",
                fontsize=7,
                color="#374151",
            )
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=35, ha="right")
        ax.set_ylabel("Rate per evaluable within-cluster pair-window")
        ax.set_ylim(0, 1)
        ax.set_title("Interval-wise Concordance Change Rates")
        ax.legend(frameon=False, ncol=3, loc="lower right", bbox_to_anchor=(1.0, 1.015))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.2)
        fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))
        path = Path(output_dir) / "reader_interval_concordance_change_summary.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        return _available_path(path), included_cluster_ids
    except Exception:
        return "", []


def _generate_protein_adjustment_comparison(
    state: Mapping[str, Any],
    output_dir: str,
) -> tuple[str, list[dict]]:
    """Render independent unadjusted, adjusted and protein contrasts.

    Records are preselected by comparison-class diversity and lexical tie-breaker
    in ``build_quantitation_comparison_cards``.  The legacy reconstructed metric
    and de-novo rows never enter this visual axis.
    """
    cards = build_quantitation_comparison_cards(state, maximum=12)
    if not cards or not output_dir:
        return "", []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        labels = []
        unadjusted = []
        adjusted = []
        protein = []
        for card in cards:
            identity = _mapping(card.get("feature_identity"))
            feature_id = str(identity.get("reader_feature_id") or "")
            gene = str(identity.get("gene") or "feature")
            residue = str(identity.get("candidate_residue_annotation") or "").strip()
            condition = str(card.get("condition") or "recorded condition")
            labels.append(
                f"{feature_id + ' · ' if feature_id else ''}{gene}"
                f"{' ' + residue if residue else ''} · {condition}"
            )
            unadjusted.append(float(card["ptm_unadjusted_log2fc"]))
            adjusted.append(float(card["ptm_protein_adjusted_log2fc"]))
            protein.append(float(card["protein_log2fc"]))

        y = np.arange(len(cards))
        fig_height = max(5.2, 1.9 + 0.56 * len(cards))
        fig, ax = plt.subplots(figsize=(10.8, fig_height))
        for index in range(len(cards)):
            ax.plot(
                [unadjusted[index], adjusted[index]],
                [y[index], y[index]],
                color="#B8B8B8",
                linewidth=1.5,
                zorder=1,
            )
        ax.scatter(unadjusted, y, s=58, color="#2F5597", label="Independent unadjusted PTM", zorder=3)
        ax.scatter(adjusted, y, s=62, marker="D", color="#D97706", label="Protein-adjusted PTM", zorder=4)
        ax.scatter(protein, y, s=48, marker="s", color="#6B7280", label="Linked protein", zorder=3)
        ax.axvline(0.0, color="#222222", linewidth=0.9, alpha=0.55)
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
        ax.set_xlabel("Conventional log2 contrast", labelpad=10)
        ax.set_title(
            "How Protein Adjustment Changed Matched PTM Contrasts",
            loc="left",
            weight="bold",
            pad=34,
        )
        ax.text(
            0.0,
            1.01,
            "Lines connect independent unadjusted and protein-adjusted PTM values; squares show linked protein contrasts.",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9,
            color="#4B5563",
        )
        ax.legend(frameon=False, ncol=1, loc="upper right", fontsize=8.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.grid(axis="x", alpha=0.18)
        fig.subplots_adjust(left=0.28, bottom=0.14, top=0.78, right=0.98)
        path = Path(output_dir) / "reader_protein_adjustment_comparison.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        return _available_path(path), cards
    except Exception:
        return "", []


def _assign_reader_figure_labels(manifest: Mapping[str, Any]) -> dict:
    preferred = {
        "reader_quantitative_heatmap": 0,
        "reader_temporal_profiles": 1,
        "reader_interval_concordance": 2,
        "reader_protein_context": 3,
    }
    figures = [dict(item) for item in manifest.get("figures") or [] if isinstance(item, Mapping)]
    main = sorted(
        [item for item in figures if item.get("placement") == "main"],
        key=lambda item: (preferred.get(str(item.get("figure_key")), 100), str(item.get("figure_key"))),
    )
    supplementary = sorted(
        [item for item in figures if item.get("placement") == "supplementary" and item.get("image_path")],
        key=lambda item: str(item.get("figure_key")),
    )
    for index, item in enumerate(main, 1):
        item["display_label"] = f"Figure {index}"
        item["insertion_verified"] = bool(_available_path(item.get("image_path")))
    for index, item in enumerate(supplementary, 1):
        item["display_label"] = f"Supplementary Figure {index}"
    labelled = {str(item.get("figure_key")): item for item in main + supplementary}
    result = []
    for item in figures:
        result.append(labelled.get(str(item.get("figure_key")), item))
    return {
        **dict(manifest),
        "figures": result,
        "main_figure_count": len(main),
        "supplementary_figure_count": len(supplementary),
    }


def prepare_reader_figure_manifest(state: Mapping[str, Any], *, citation_complete: bool) -> dict:
    """Generate and freeze insertable reader figures before scientific writing."""
    output_dir = str(state.get("output_dir") or "")
    manifest = build_figure_manifest(state, citation_complete=citation_complete)
    vector_rows = [row for row in state.get("vector_plot_raw_data") or [] if isinstance(row, Mapping)]
    network = _mapping(state.get("network_analysis"))
    heatmap = _mapping(state.get("kinase_activity_heatmap"))
    conditions = [str(value) for value in heatmap.get("conditions") or network.get("timepoints") or [] if str(value).strip()]
    if not conditions:
        conditions = sorted({str(row.get("condition") or "") for row in vector_rows if str(row.get("condition") or "")})
    selected_features = next((list(item.get("selected_features") or []) for item in manifest.get("figures") or [] if item.get("figure_key") == "reader_quantitative_heatmap"), [])
    if output_dir and selected_features:
        try:
            from report_generation.core.nodes.signal_flow_figure import generate_context_aware_ptm_heatmap

            heatmap_path = generate_context_aware_ptm_heatmap(
                sections={},
                vector_plot_raw_data=vector_rows,
                conditions=conditions,
                output_dir=output_dir,
                ptm_type=str(state.get("ptm_type") or "phosphorylation"),
                selected_features=selected_features,
            )
            if heatmap_path:
                manifest = attach_reader_heatmap(manifest, heatmap_path, selected_features)
        except Exception:
            pass

    # Legacy temporal images remain available to the technical audit but are not
    # exposed to the author once a reader composite is prepared.
    for item in manifest.get("figures") or []:
        if str(item.get("figure_key") or "").startswith("temporal."):
            item["placement"] = "technical_audit"
            item["suppression_reason"] = "replaced_by_reader_temporal_profile_panel"

    selected_clusters = _select_cluster_figures(state)
    profile_path = _compose_cluster_panel(selected_clusters, output_dir)
    if profile_path:
        representative_members = {
            f"Temporal Profile Cluster {index}": list(item.get("representative_members") or [])
            for index, item in enumerate(selected_clusters, 1)
        }
        profile_entry = _entry(
            "reader_temporal_profiles", "reader_temporal_profile", profile_path,
            question="Which selected Temporal Profile Clusters represent distinct measured phosphorylation trajectories?",
            evidence_tier="O2", source_evidence_ids=["temporal.profile_summary"],
            caption_facts={
                "data_scope": "three to five preselected Temporal Profile Clusters with existing cluster-detail plots",
                "data_unit_scope": "conventional quantified phosphorylation-feature profiles",
                "visual_encoding": "cluster-specific sampled-timepoint trajectories and cluster summaries",
                "interpretation_boundary": "descriptive temporal profiles; not common regulation, kinase activity, pathway function, or causal order",
                "representative_members": representative_members,
            },
            selection_rule="distinct temporal pattern class; readable existing cluster plot; lexical cluster-ID tie-breaker",
            selected_profile_count=len(selected_clusters),
            selected_cluster_count=len(selected_clusters),
            selected_cluster_ids=[str(item.get("cluster_id")) for item in selected_clusters],
            representative_member_labels=representative_members,
            labels_readable=True,
            title="Selected Temporal Profile Clusters",
        )
        placement, reason = FigureEligibilityPolicy().classify(profile_entry, citation_complete=citation_complete)
        profile_entry["placement"] = placement
        profile_entry["suppression_reason"] = reason
        manifest["figures"].append(profile_entry)

    selected_ids = [str(item.get("cluster_id")) for item in selected_clusters]
    concordance_path, concordance_ids = _generate_concordance_summary(state, output_dir, selected_ids)
    if concordance_path:
        concordance_entry = _entry(
            "reader_interval_concordance", "reader_concordance", concordance_path,
            question="How did within-cluster activity-state concordance change across adjacent sampled intervals?",
            evidence_tier="O2", source_evidence_ids=["temporal.concordance_summary"],
            caption_facts={
                "data_scope": "observed within-cluster pair transitions normalized by evaluable pair-window comparisons in each adjacent sampled interval",
                "data_unit_scope": "eligible within-cluster feature pairs",
                "visual_encoding": "stacked retained, gain and loss rates per evaluable pair-window by Temporal Profile Cluster and adjacent sampled interval",
                "interpretation_boundary": "Concordance Change is descriptive; persistence is distinct from change, and rates do not establish common regulation, causal order, kinase switching, or pathway rewiring",
            },
            selection_rule="same selected cluster set as the temporal-profile panel when evaluable; otherwise lexical cluster-ID subset",
            selected_cluster_count=len(concordance_ids),
            selected_cluster_ids=concordance_ids,
            labels_readable=True,
            title="Interval-wise Concordance Change Summary",
        )
        placement, reason = FigureEligibilityPolicy().classify(concordance_entry, citation_complete=citation_complete)
        concordance_entry["placement"] = placement
        concordance_entry["suppression_reason"] = reason
        manifest["figures"].append(concordance_entry)

    comparison_path, comparison_cards = _generate_protein_adjustment_comparison(state, output_dir)
    if comparison_path:
        comparison_entry = _entry(
            "reader_protein_context", "reader_protein_context", comparison_path,
            question="For matched current-order features, how did protein adjustment change the independently measured PTM contrast?",
            evidence_tier="O1",
            source_evidence_ids=[
                str(card.get("evidence_ids", [""])[0])
                for card in comparison_cards
                if card.get("evidence_ids")
            ],
            caption_facts={
                "data_scope": "matched conventional current-order feature-condition records with independent unadjusted PTM, protein-adjusted PTM, and linked protein contrasts",
                "data_unit_scope": "modified-precursor feature-condition comparison",
                "visual_encoding": "paired unadjusted and protein-adjusted PTM points connected within each record; linked protein contrast shown as a separate square",
                "interpretation_boundary": "arithmetic change after adjustment does not prove improved biological truth, absolute occupancy, kinase activity, direct regulation, or biological priority; de-novo and reconstructed values are excluded",
            },
            selection_rule="matched conventional axes; comparison-class diversity; lexical tie-breaker; no magnitude ranking",
            matched_feature_count=len(comparison_cards),
            matched_protein_context=True,
            labels_readable=True,
            comparison_classes=sorted({str(card.get("comparison_class") or "") for card in comparison_cards}),
            selected_reader_feature_ids=sorted({
                str(_mapping(card.get("feature_identity")).get("reader_feature_id") or "")
                for card in comparison_cards
                if str(_mapping(card.get("feature_identity")).get("reader_feature_id") or "")
            }),
            reconstructed_metric_excluded=True,
            de_novo_excluded=True,
            title="Independent PTM and Protein-Adjustment Comparison",
        )
        placement, reason = FigureEligibilityPolicy().classify(
            comparison_entry,
            citation_complete=citation_complete,
        )
        comparison_entry["placement"] = placement
        comparison_entry["suppression_reason"] = reason
        manifest["figures"].append(comparison_entry)

    manifest["prepared_before_writer"] = True
    return _assign_reader_figure_labels(manifest)


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
        if (
            not isinstance(figure, Mapping)
            or figure.get("placement") != "main"
            or not bool(figure.get("insertion_verified"))
        ):
            continue
        cards.append({
            "figure_key": figure.get("figure_key"),
            "display_label": figure.get("display_label"),
            "image_path": figure.get("image_path"),
            "title": figure.get("title"),
            "placement": figure.get("placement"),
            "question": figure.get("research_question"),
            "reader_summary": (
                f"{figure.get('kind')} selected under {figure.get('selection_rule')}"
            ),
            "allowed_interpretation": "descriptive temporal pattern or cited external context",
            "forbidden_interpretation": "activation, direct kinase–substrate relation, causal order, isoform-specific activity",
            "citation_ids": list(figure.get("citation_ids") or []),
            "source_evidence_ids": list(figure.get("source_evidence_ids") or []),
            "selected_reader_feature_ids": list(
                figure.get("selected_reader_feature_ids")
                or [
                    str(item.get("reader_feature_id") or "")
                    for item in figure.get("selected_features") or []
                    if str(item.get("reader_feature_id") or "")
                ]
            ),
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
