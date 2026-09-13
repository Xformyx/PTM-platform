"""Evidence-tiered figure inventory, eligibility, and reader caption policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ptm_shared.de_novo_representation import conventional_quantitation_eligibility, is_de_novo_representation
from report_generation.core.measured_feature_cards import (
    build_quantitation_comparison_cards,
    reader_feature_id,
)
from .quantitative_claims import quantitative_records


FIGURE_MANIFEST_VERSION = "report_figure_manifest.v5"
HEATMAP_MAIN_MIN_FEATURES = 12
HEATMAP_MAIN_MAX_FEATURES = 16
"""Main heatmap row range.

docs/official_temporal_terminology_contract.md § Reader-facing selected-feature
heatmap encoding, declared 2026-09-14. Selection maximum and eligibility are
the same 12–16 window. Not a biological priority threshold.
"""
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
        return str(path) if path.is_file() and path.stat().st_size > 1000 else ""
    except OSError:
        return ""


def _figure_readability_audit(
    image_path: str,
    *,
    label_count: int,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Estimate label legibility from the rendered image and label density."""
    width = height = 0
    error = None
    try:
        from PIL import Image

        with Image.open(str(image_path)) as image:
            width, height = image.size
    except Exception as exc:
        error = type(exc).__name__
    cleaned_labels = [str(value).strip() for value in labels or [] if str(value).strip()]
    longest = max((len(value) for value in cleaned_labels), default=0)
    pixels_per_label = (height / max(label_count, 1)) if height else 0.0
    readable = bool(
        width >= 300
        and height >= 180
        and label_count > 0
        and pixels_per_label >= 16.0
        and (not longest or longest * 6.0 <= width * 0.78)
    )
    return {
        "contract_version": "figure_readability_audit.v1",
        "status": "readable" if readable else "review_required",
        "labels_readable": readable,
        "image_width_px": width or None,
        "image_height_px": height or None,
        "label_count": int(label_count),
        "pixels_per_label": round(pixels_per_label, 2),
        "longest_label_characters": longest,
        "dimension_read_error": error,
    }


def _feature_binding_audit(selected_features: list[Mapping[str, Any]]) -> dict[str, Any]:
    bindings: list[tuple[str, str]] = []
    for item in selected_features:
        if not isinstance(item, Mapping):
            continue
        feature_id = str(
            item.get("reader_feature_id")
            or _mapping(item.get("feature_identity")).get("reader_feature_id")
            or ""
        ).strip()
        condition = str(item.get("condition") or "").strip()
        bindings.append((feature_id, condition))
    nonempty = [feature_id for feature_id, _ in bindings if feature_id]
    record_ids = [f"{feature_id}|{condition}" for feature_id, condition in bindings if feature_id]
    duplicates = sorted({value for value in record_ids if record_ids.count(value) > 1})
    valid = bool(selected_features) and len(nonempty) == len(selected_features) and not duplicates
    return {
        "contract_version": "figure_feature_binding_audit.v1",
        "status": "validated" if valid else "incompatible",
        "binding_valid": valid,
        "selected_feature_count": len(selected_features),
        "bound_reader_feature_id_count": len(nonempty),
        "duplicate_feature_condition_bindings": duplicates,
        "selected_reader_feature_ids": sorted(set(nonempty)),
        "feature_condition_binding_count": len(record_ids),
    }


class FigureEligibilityPolicy:
    """Fail-closed policy for researcher-facing Report figure placement."""

    def classify(self, figure: Mapping[str, Any], *, citation_complete: bool) -> tuple[str, str | None]:
        kind = str(figure.get("kind") or "")
        path = str(figure.get("image_path") or "")
        if kind not in {"reader_heatmap", "reader_temporal_profile", "reader_protein_context", "literature_comparison"} and not path:
            return "suppressed", "image_missing"
        if kind in {"dense_network", "kinase_diagnostic", "technical_atlas"}:
            return "technical_audit", "dense_or_diagnostic_visualization"
        if kind == "reader_joint_trajectory":
            binding = _mapping(figure.get("feature_binding_audit"))
            if (path and figure.get("labels_readable") and binding.get("binding_valid")
                    and binding.get("contract_version") == "joint_trajectory_binding.v1"
                    and figure.get("quantitative_bindings") and figure.get("prepared_from_finding_selection")):
                return "main", None
            return "suppressed", "joint_trajectory_measurement_binding_or_render_unavailable"
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
            binding_valid = bool(_mapping(figure.get("feature_binding_audit")).get("binding_valid"))
            if HEATMAP_MAIN_MIN_FEATURES <= count <= HEATMAP_MAIN_MAX_FEATURES and labels and conventional_only and binding_valid:
                return "main", None
            return "suppressed", "requires_12_to_16_readable_bound_conventional_feature_cards"
        if kind == "reader_temporal_profile":
            if not figure.get("quantitative_bindings"):
                return "technical_audit", "legacy_cluster_image_measurements_unbound"
            profile_count = int(figure.get("selected_profile_count") or 0)
            cluster_count = int(figure.get("selected_cluster_count") or 0)
            if 3 <= profile_count <= 5 and 3 <= cluster_count <= 5 and bool(figure.get("labels_readable")):
                return "main", None
            return "supplementary", "requires_preselected_profile_and_cluster_cards"
        if kind == "reader_concordance":
            if figure.get("quantitative_bindings") and figure.get("labels_readable"):
                return "supplementary", "descriptive_pair_transition_context"
            return "suppressed", "observed_counts_or_readability_unavailable"
        if kind == "reader_protein_context":
            matched_count = int(figure.get("matched_feature_count") or 0)
            binding_valid = bool(_mapping(figure.get("feature_binding_audit")).get("binding_valid"))
            if matched_count >= 2 and bool(figure.get("matched_protein_context")) and bool(figure.get("labels_readable")) and binding_valid:
                return "main", None
            if matched_count == 1 and bool(figure.get("matched_protein_context")) and bool(figure.get("labels_readable")) and binding_valid:
                return "supplementary", "single_complete_comparison_retained_as_supplementary_context"
            return "suppressed", "matched_protein_context_readable_labels_or_feature_binding_unavailable"
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


def select_reader_heatmap_features(vector_rows, conditions, *, minimum=HEATMAP_MAIN_MIN_FEATURES, maximum=HEATMAP_MAIN_MAX_FEATURES, selected_reader_feature_ids=()):
    """Finding-first display with partial observations; clustering stays separate."""
    from .measured_feature_cards import build_feature_observation_cards
    cards = build_feature_observation_cards({"vector_plot_raw_data": vector_rows}, maximum=max(len(vector_rows), maximum), minimum_points=1)
    candidates = []
    for card in cards:
        identity = card["feature_identity"]
        records = [r for r in quantitative_records(card) if r["axis"] == "adjusted" and r["condition"] in conditions]
        if not any(r["value"] is not None for r in records):
            continue
        values = {r["condition"]: r["value"] for r in records}
        candidates.append({**identity, "source_feature_id": identity.get("source_feature_id") or identity.get("precursor_id"),
            "position": identity.get("candidate_residue_annotation") or identity.get("position"),
            "reader_feature_id": identity["reader_feature_id"],
            "display_label": identity["gene"] + " " + str(identity.get("candidate_residue_annotation") or identity.get("position") or "") + " · " + identity["reader_feature_id"][-4:],
            "conditions": list(conditions), "values": values, "quantitative_bindings": records,
            "render_axis": "protein_adjusted_relative_ptm_contrast", "render_eligible": True,
            "partial_observation_display": True, "clustering_eligible": card.get("clustering_eligible"),
            "pattern_class": "".join("?" if values.get(c) is None else "+" if values[c] > SIGNED_PATTERN_THRESHOLD else "-" if values[c] < -SIGNED_PATTERN_THRESHOLD else "0" for c in conditions),
            "selection_reason": "selected finding first, then observed shape diversity; missingness is displayed"})
    candidates.sort(key=lambda c: (c["reader_feature_id"] not in selected_reader_feature_ids, c["pattern_class"], c["reader_feature_id"]))
    selected = [c for c in candidates if c["reader_feature_id"] in selected_reader_feature_ids][:maximum]
    seen = {c["pattern_class"] for c in selected}
    for card in candidates:
        if len(selected) >= maximum: break
        if card not in selected and card["pattern_class"] not in seen:
            selected.append(card); seen.add(card["pattern_class"])
    for card in candidates:
        if len(selected) >= maximum: break
        if card not in selected: selected.append(card)
    return selected if len(selected) >= minimum else []


def order_reader_conditions(conditions, rows):
    """Order by measured elapsed time; unknown/conflicting times remain labels."""
    from .temporal_analysis import observed_time_minutes
    times = {}
    for row in rows:
        condition = str(row.get("condition") or "")
        value = observed_time_minutes(row)
        if value is not None:
            times.setdefault(condition, set()).add(value)
    def key(condition):
        values = times.get(condition, set())
        value = next(iter(values)) if len(values) == 1 else observed_time_minutes({"condition": condition}) if not values else None
        return (value is None, value if value is not None else 0, condition)
    return sorted(dict.fromkeys(conditions), key=key)


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
    conditions = order_reader_conditions(conditions, vector_rows)
    selected_features = select_reader_heatmap_features(vector_rows, conditions, selected_reader_feature_ids=state.get("_selected_finding_ids") or [])
    if selected_features or vector_rows:
        initial_binding = _feature_binding_audit(selected_features)
        entries.append(_entry(
            "reader_quantitative_heatmap", "reader_heatmap", "",
            question="Which selected quantitative phosphorylation features show distinct measured profiles across sampled timepoints?",
            evidence_tier="O1", source_evidence_ids=["quantitative.landscape", "temporal.profile_summary"],
            caption_facts={
                "data_scope": "protein-adjusted phosphorylation-feature contrasts with independent conventional eligibility at every displayed condition",
                "data_unit_scope": "phosphorylation feature aggregate",
                "visual_encoding": "diverging protein-adjusted relative PTM Log2FC color scale",
                "interpretation_boundary": "measured contrast is not activation, directness, or biological-priority score; de novo rows are excluded from the numeric color scale",
            },
            selection_rule="selected findings first, then observed shape diversity; partial observations retain gaps",
            selected_feature_count=len(selected_features), labels_readable=True,
            feature_binding_audit=initial_binding,
            selected_reader_feature_ids=initial_binding["selected_reader_feature_ids"],
            conventional_only=bool(selected_features) and all(item.get("render_eligible") for item in selected_features),
            render_axis="protein_adjusted_relative_ptm_contrast",
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
        from PIL import Image, ImageDraw, ImageFont
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
        cell_height = max(image.height for _, image in opened) + 112
        canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(canvas)
        try:
            title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
            member_font = ImageFont.truetype("DejaVuSans.ttf", 14)
        except OSError:
            title_font = member_font = None
        for index, (item, image) in enumerate(opened):
            row, column = divmod(index, columns)
            x = column * cell_width + 18
            y = row * cell_height + 82
            pattern = str(item.get("pattern") or "unclassified").replace("_", " ")
            draw.text(
                (x, 10 + row * cell_height),
                f"{chr(65 + index)}  Temporal Profile Cluster {index + 1} · {pattern}",
                fill="black",
                font=title_font,
            )
            member_text = ", ".join(str(value) for value in item.get("representative_members") or [])
            if member_text:
                if len(member_text) > 82:
                    member_text = member_text[:79].rstrip() + "…"
                draw.text(
                    (x, 42 + row * cell_height),
                    f"Representative measured members (lexical): {member_text}",
                    fill="#4B5563",
                    font=member_font,
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


def concordance_bindings(state, selected_cluster_ids=()):
    """Preserve observed integer counts, never reconstruct them from rates."""
    import re
    records = []
    for row in _dynamic_transition_rows(state):
        cluster = str(row.get("static_wave_id") or row.get("cluster_id") or "")
        if selected_cluster_ids and cluster not in selected_cluster_ids:
            continue
        counts = row.get("pair_transition_type_counts")
        denominator = row.get("evaluable_pair_window_comparison_count")
        if (not isinstance(counts, Mapping) or not isinstance(denominator, int)
                or denominator <= 0 or any(not isinstance(n, int) or n < 0 for n in counts.values())):
            continue
        retained = counts.get("persistence", 0)
        gain = counts.get("recruitment", 0) + counts.get("merge", 0)
        loss = counts.get("split", 0)
        if retained + gain + loss > denominator:
            continue
        records.append({"cluster_id": cluster, "from_window": row.get("from_window"),
                        "to_window": row.get("to_window"), "denominator": denominator,
                        "counts": dict(counts), "retained": retained, "gain": gain, "loss": loss,
                        "other_or_no_transition": denominator - retained - gain - loss,
                        "source": "temporal_ptm_protein_analysis.dynamic_transition_per_wave"})
    def interval_key(label):
        return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(label)))
    return sorted(records, key=lambda r: (r["cluster_id"], interval_key(r["from_window"]), interval_key(r["to_window"])))


def _generate_concordance_summary(state, output_dir, selected_cluster_ids):
    """All supplied adjacent comparisons; separate rates are not a 100% stack."""
    rows = concordance_bindings(state, selected_cluster_ids)
    if not rows or not output_dir:
        return "", []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        labels = [f"{r['cluster_id']} · {r['from_window']} → {r['to_window']}" for r in rows]
        rates = np.array([[r[k] / r["denominator"] for k in ("retained", "gain", "loss")] for r in rows])
        fig, ax = plt.subplots(figsize=(6.5, max(2.5, 1.2 + .34 * len(rows))))
        ax.imshow(rates, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        ax.set_xticks(range(3), ["Retained", "Gain", "Loss"], fontsize=10)
        ax.set_yticks(range(len(rows)), labels, fontsize=8)
        for i, r in enumerate(rows):
            for j, key in enumerate(("retained", "gain", "loss")):
                ax.text(j, i, f"{r[key]}/{r['denominator']}", ha="center", va="center", fontsize=8,
                        color="white" if rates[i, j] > .55 else "black")
        ax.set_title("Within-cluster pair transitions", fontsize=11)
        fig.tight_layout()
        path = Path(output_dir) / "reader_interval_concordance_change_summary.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=300)
        plt.close(fig)
        return _available_path(path), sorted({r["cluster_id"] for r in rows})
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
    from .reader_authoring import finding_observation_conditions
    cards = build_quantitation_comparison_cards(state, maximum=max(12, len(state.get("vector_plot_raw_data") or [])))
    choices = {(c["feature_identity"]["reader_feature_id"], condition) for c in state.get("_selected_finding_cards") or [] for condition in finding_observation_conditions(c)}
    if choices:
        cards = [c for c in cards if (c["feature_identity"]["reader_feature_id"], c.get("condition")) in choices]
    cards = cards[:12]
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
                f"{gene}"
                f"{' ' + residue if residue else ''} · {feature_id[-4:]} · {condition}"
            )
            unadjusted.append(float(card["ptm_unadjusted_log2fc"]))
            adjusted.append(float(card["ptm_protein_adjusted_log2fc"]))
            protein.append(float(card["protein_log2fc"]))

        y = np.arange(len(cards))
        fig_height = max(5.2, 1.9 + 0.56 * len(cards))
        fig, ax = plt.subplots(figsize=(6.5, max(4.0, .37 * len(cards) + 1.8)))
        for index in range(len(cards)):
            ax.plot(
                [unadjusted[index], adjusted[index]],
                [y[index], y[index]],
                color="#B8B8B8",
                linewidth=1.5,
                zorder=1,
            )
        ax.scatter(unadjusted, y, s=105, facecolors="none", edgecolors="#2F5597", linewidths=1.2, label="Independent unadjusted PTM", zorder=5)
        ax.scatter(adjusted, y, s=62, marker="D", color="#D97706", label="Protein-adjusted PTM", zorder=4)
        ax.scatter(protein, y, s=48, marker="s", color="#6B7280", label="Linked protein", zorder=3)
        ax.axvline(0.0, color="#222222", linewidth=0.9, alpha=0.55)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Conventional log2 contrast", labelpad=10)
        ax.set_title(
            "Matched PTM contrasts",
            loc="left",
            weight="bold",
            pad=34,
        )
        ax.text(
            0.0,
            1.01,
            "",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9,
            color="#4B5563",
        )
        fig.legend(*ax.get_legend_handles_labels(), frameon=False, ncol=1,
                   loc="upper center", bbox_to_anchor=(.64, .99), fontsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.grid(axis="x", alpha=0.18)
        fig.subplots_adjust(left=0.40, bottom=0.14, top=0.72, right=0.98)
        path = Path(output_dir) / "reader_protein_adjustment_comparison.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        return _available_path(path), cards
    except Exception:
        return "", []


def _generate_joint_trajectory_entry(state, output_dir):
    """Plot the frozen finding features, preserving actual minutes and NA gaps."""
    from .reader_authoring import build_authoring_packet, finding_observation_conditions
    from .measured_feature_cards import select_finding_cards
    packet = build_authoring_packet(state)
    cards, selection = select_finding_cards(packet["reader_cards"])
    cards = state.get("_selected_finding_cards") or cards
    if not cards:
        return None
    bindings = [r for card in cards for r in quantitative_records(card) if r["time_minutes"] is not None]
    ids = sorted({r["feature_id"] for r in bindings})
    keys = [(r["feature_id"], r["condition"], r["axis"]) for r in bindings]
    time_keys = [(r["feature_id"], r["time_minutes"], r["axis"]) for r in bindings]
    valid = (len(keys) == len(set(keys)) and bool(bindings)
             and all(any(r["feature_id"] == fid and r["value"] is not None for r in bindings) for fid in ids))
    entry = _entry("reader_joint_trajectories", "reader_joint_trajectory", "",
        question="How do independent PTM, linked protein and protein-adjusted PTM measurements differ over the observed time window?",
        evidence_tier="O1", source_evidence_ids=sorted({e for c in cards for e in c["evidence_ids"]}),
        caption_facts={"data_scope": "selected precursor/form contrasts at recorded elapsed times; candidate residue labels do not independently establish localization",
                       "visual_encoding": "U: independent unadjusted PTM; P: linked protein; A: protein-adjusted relative PTM log2 contrast; separate columns with shared relative scale. Points are observations, dashed segments are visual guides, gaps are unavailable values",
                       "interpretation_boundary": "the sampled contrasts do not establish absolute concentrations, occupancy, biological peaks or direct kinase activity. Different features are not on a common absolute MS intensity scale; sample counts and axis-specific q values are recorded separately"},
        selection_rule="observation quality followed by parent and joint-pattern diversity, with stable feature identity as the tie-breaker", selected_reader_feature_ids=ids,
        quantitative_bindings=bindings, prepared_from_finding_selection=selection,
        table_conditions={c["feature_identity"]["reader_feature_id"]: finding_observation_conditions(c) for c in cards},
        feature_binding_audit={"contract_version": "joint_trajectory_binding.v1", "binding_valid": valid,
                               "selected_reader_feature_ids": ids, "unknown_time_conditions": sorted({p["condition"] for c in cards for p in c["trajectory"] if p.get("time_minutes") is None})},
        title="Selected PTM–protein time responses", labels_readable=False)
    if valid and output_dir:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
            from PIL import Image
            visible = sorted([c for c in cards if c["feature_identity"]["reader_feature_id"] in ids],
                             key=lambda c: (c.get("parent_protein_ids") or [c["feature_identity"]["gene"]], c["feature_identity"]["reader_feature_id"]))
            times = sorted({r["time_minutes"] for r in bindings})
            values = [abs(r["value"]) for r in bindings if r["value"] is not None]
            extent = max(values + [.2]) * 1.15
            separate = (state.get("report_options") or {}).get("joint_trajectory_layout") == "separate_axes"
            columns = 3 if separate else 2
            rows = len(visible) if separate else (len(visible) + 1) // 2
            fig, axes = plt.subplots(rows, columns, figsize=(6.5, 1.0 + 2.8 * rows), squeeze=False)
            styles = (("unadjusted", "U · PTM", "#1764ab", "o"),
                      ("protein", "P · Protein", "#706573", "s"),
                      ("adjusted", "A · Adjusted PTM", "#b64518", "D"))
            early = [t for t in times if 0 < t <= 30]
            early_zoom = len(early) >= 3 and max(times) > 60
            mixed_range = any(
                min([r["value"] for r in bindings if r["feature_id"] == c["feature_identity"]["reader_feature_id"] and r["value"] is not None], default=0) < -extent * .25
                and max([r["value"] for r in bindings if r["feature_id"] == c["feature_identity"]["reader_feature_id"] and r["value"] is not None], default=0) > extent * .25
                for c in visible)
            log_time = early_zoom and mixed_range and min(times) > 0
            early_zoom = early_zoom and not log_time
            tick_axes = []
            def plot_axis(ax, fid, styles_to_plot, *, zoom=False):
                for axis, label, color, marker in styles_to_plot:
                    data = sorted([r for r in bindings if r["feature_id"] == fid and r["axis"] == axis],
                                  key=lambda r: (r["time_minutes"], r["condition"]))
                    xs = [r["time_minutes"] for r in data]
                    ys = [r["value"] if r["value"] is not None else np.nan for r in data]
                    ax.plot(xs, ys, marker=marker, linestyle="None" if len(set(xs)) != len(xs) else "--",
                            color=color, lw=.9, ms=5 if axis == "unadjusted" else 3,
                            markerfacecolor="none" if axis == "unadjusted" else color, label=label)
                ax.axhline(0, color="#888888", lw=.6)
                ax.set_ylim(-extent, extent)
                ax.tick_params(labelsize=7)
                if zoom:
                    ax.set_xlim(min(early) - .7, max(early) + 1)
                    ax.set_xticks(early)
                    ax.set_title("Early observations (min)", fontsize=7)
                else:
                    ax.set_xlim(min(times) * .85 if log_time else min(times) - 1, max(times) * 1.05)
                    # Actual elapsed times, selected ticks; inset resolves the
                    # early measurements without forcing crowded tick labels.
                    ticks = [min(times)] + [t for t in times if t >= 60] if early_zoom else times
                    ax.set_xticks(ticks)
                    if log_time:
                        from matplotlib.ticker import ScalarFormatter, NullLocator
                        ax.set_xscale("log")
                        ax.set_xticks(times)
                        ax.xaxis.set_major_formatter(ScalarFormatter())
                        ax.xaxis.set_minor_locator(NullLocator())
                        ax.tick_params(axis="x", labelrotation=35)
                    ax.set_xlabel("Elapsed time (min, log scale)" if log_time else "Elapsed time (min)", fontsize=8)
                tick_axes.append(ax)
            for i, card in enumerate(visible):
                fid = card["feature_identity"]["reader_feature_id"]
                identity = card["feature_identity"]
                selected_axes = list(axes[i]) if separate else [axes.flat[i]]
                for j, ax in enumerate(selected_axes):
                    plot_axis(ax, fid, [styles[j]] if separate else styles)
                    ax.set_title(f"{identity['gene']} {identity.get('candidate_residue_annotation') or ''} · {fid[-4:]}" + (f" / {styles[j][1]}" if separate else ""), fontsize=9, loc="left")
                    ax.set_ylabel("Relative log2 contrast", fontsize=8)
                    if early_zoom:
                        values_for_feature = [r["value"] for r in bindings if r["feature_id"] == fid and r["value"] is not None]
                        inset_y = .10 if sum(values_for_feature) >= 0 else .62
                        inset = ax.inset_axes([.26, inset_y, .68, .24])
                        plot_axis(inset, fid, [styles[j]] if separate else styles, zoom=True)
            if not separate:
                for ax in axes.flat[len(visible):]:
                    ax.set_visible(False)
            fig.legend(*axes.flat[0].get_legend_handles_labels(), loc="upper center", ncol=3, frameon=False, fontsize=8)
            fig.tight_layout(rect=(0, 0, 1, .93), pad=1.2)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            overlaps = []
            for ax_index, ax in enumerate(tick_axes):
                boxes = [t.get_window_extent(renderer) for t in ax.get_xticklabels() if t.get_visible() and t.get_text()]
                for left, right in zip(boxes, boxes[1:]):
                    if left.overlaps(right):
                        overlaps.append(ax_index)
            path = Path(output_dir) / "reader_joint_trajectories.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, dpi=300)
            plt.close(fig)
            with Image.open(path) as img:
                img.verify()
            entry.update(image_path=str(path), labels_readable=not overlaps, render_status="rendered",
                         readability_audit={"contract_version": "figure_text_bounds.v1", "tick_overlap_axes": overlaps,
                                            "intended_width_inches": 6.5, "page_visual_review": "required"},
                         layout="separate_axes" if separate else "overlaid_axes_log_time" if log_time else "overlaid_axes_with_early_inset" if early_zoom else "overlaid_axes",
                         displayed_feature_labels={c["feature_identity"]["reader_feature_id"]: c["feature_identity"]["gene"] + " · " + c["feature_identity"]["reader_feature_id"][-4:] for c in visible})
            entry["caption_facts"]["visual_encoding"] = "U: independent PTM; P: linked protein; A: protein-adjusted PTM, all in relative log2 contrast. Actual elapsed minutes; dashed segments join observations and gaps remain unavailable." + (" Insets enlarge early observations." if early_zoom else " Time is shown on an explicitly logarithmic scale." if log_time else "")
        except Exception as exc:
            entry.update(render_status="renderer_failed", render_error=type(exc).__name__)
    entry["placement"], entry["suppression_reason"] = FigureEligibilityPolicy().classify(entry, citation_complete=False)
    return entry


def joint_trajectory_evidence_table(figure):
    """Show the selected observation times; complete statistics stay bound."""
    if figure.get("kind") != "reader_joint_trajectory":
        return ""
    grouped = {}
    bindings = figure.get("quantitative_bindings") or []
    protein = [r for r in bindings if r["axis"] == "protein"]
    hide_protein_q = bool(protein) and all(r.get("q") is None for r in protein)
    protein_test_absent = bool(protein) and all((r.get("support") or {}).get("test_status") == "not_computed" for r in protein)
    for row in bindings:
        chosen = (figure.get("table_conditions") or {}).get(row["feature_id"])
        if chosen is not None and row["condition"] not in chosen:
            continue
        grouped.setdefault((row["feature_id"], row["condition"]), {})[row["axis"]] = row
    lines = ["| Feature / condition | U: value; n; q | P: value; n" + ("" if hide_protein_q else "; q") + " | A: value; n; q |",
             "|---|---|---|---|"]
    def cell(record, axis):
        value = record.get("value")
        support = record.get("support") or {}
        n = "/".join(f"{record[f'{g}_n']:g}" if record.get(f"{g}_n") is not None else "unrecorded" for g in ("control", "treatment"))
        if n == "unrecorded/unrecorded":
            n = "n unrecorded"
        if value is None:
            return "Unavailable: " + str(support.get("missing_reason") or "quantitation unavailable").replace("_", " ")
        text = f"{value:+.3f}; {n}"
        if axis != "protein" or not hide_protein_q:
            q = record.get("q")
            text += f"; {q:.3g}" if q is not None else "; not tested" if support.get("test_status") == "not_computed" else "; test unavailable"
        return text
    for (fid, condition), records in grouped.items():
        label = (figure.get("displayed_feature_labels") or {}).get(fid, fid)
        lines.append("| " + label + " / " + condition + " | " + " | ".join(cell(records.get(axis, {}), axis) for axis in ("unadjusted", "protein", "adjusted")) + " |")
    note = "Values and statistics refer to the selected first response, sampled extremum and late observation; all times and full feature identifiers remain in the evidence table. Counts are contributing sample observations (control/treatment); biological design is not inferred from injection counts. Point q-values do not test the trajectory or adjustment effect."
    if hide_protein_q:
        note += " Protein q-values are omitted because " + ("a separate protein test was not computed." if protein_test_absent else "protein statistical support was not supplied; this does not imply missing protein measurements.")
    return "\n".join(lines) + "\n\n" + note + "\n"


def render_verified_reader_figures(manifest, *, placement="main"):
    figures = [f for f in manifest.get("figures") or [] if f.get("placement") == placement
               and f.get("insertion_verified") and _available_path(f.get("image_path"))]
    blocks = []
    for figure in sorted(figures, key=lambda f: int(str(f.get("display_label") or "Figure 0").split()[-1])):
        title = figure.get("title") or figure.get("research_question") or "Reader Figure"
        blocks.append(f"### {figure['display_label']}. {title}\n\n![{title}]({figure['image_path']})\n\n"
                      f"**Figure legend.** {compile_reader_caption(figure)}\n\n" + joint_trajectory_evidence_table(figure))
    return "\n\n".join(blocks)


def _assign_reader_figure_labels(manifest: Mapping[str, Any]) -> dict:
    preferred = {
        "reader_quantitative_heatmap": 0,
        "reader_temporal_profiles": 1,
        "reader_interval_concordance": 2,
        "reader_protein_context": 3,
        "reader_joint_trajectories": 4,
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
        item["insertion_verified"] = bool(_available_path(item.get("image_path")))
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
    from .reader_authoring import build_authoring_packet
    from .measured_feature_cards import select_finding_cards
    state = dict(state)
    selected_cards, _ = select_finding_cards(build_authoring_packet(state)["reader_cards"])
    state["_selected_finding_cards"] = selected_cards
    state["_selected_finding_ids"] = [c["feature_identity"]["reader_feature_id"] for c in selected_cards]
    output_dir = str(state.get("output_dir") or "")
    manifest = build_figure_manifest(state, citation_complete=citation_complete)
    vector_rows = [row for row in state.get("vector_plot_raw_data") or [] if isinstance(row, Mapping)]
    network = _mapping(state.get("network_analysis"))
    heatmap = _mapping(state.get("kinase_activity_heatmap"))
    conditions = [str(value) for value in heatmap.get("conditions") or network.get("timepoints") or [] if str(value).strip()]
    if not conditions:
        conditions = sorted({str(row.get("condition") or "") for row in vector_rows if str(row.get("condition") or "")})
    conditions = order_reader_conditions(conditions, vector_rows)
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
        profile_labels = [f"Temporal Profile Cluster {index}" for index in range(1, len(selected_clusters) + 1)]
        profile_readability = _figure_readability_audit(
            profile_path,
            label_count=len(profile_labels),
            labels=profile_labels,
        )
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
            labels_readable=profile_readability["labels_readable"],
            readability_audit=profile_readability,
            title="Selected Temporal Profile Clusters",
        )
        placement, reason = FigureEligibilityPolicy().classify(profile_entry, citation_complete=citation_complete)
        profile_entry["placement"] = placement
        profile_entry["suppression_reason"] = reason
        manifest["figures"].append(profile_entry)

    selected_ids = [str(item.get("cluster_id")) for item in selected_clusters]
    concordance_path, concordance_ids = _generate_concordance_summary(state, output_dir, selected_ids)
    if concordance_path:
        concordance_labels = [f"Temporal Profile Cluster {value}" for value in concordance_ids]
        concordance_readability = _figure_readability_audit(
            concordance_path,
            label_count=max(len(concordance_ids), 1),
            labels=concordance_labels,
        )
        concordance_entry = _entry(
            "reader_interval_concordance", "reader_concordance", concordance_path,
            question="How did within-cluster activity-state concordance change across adjacent sampled intervals?",
            evidence_tier="O2", source_evidence_ids=["temporal.concordance_summary"],
            caption_facts={
                "data_scope": "observed within-cluster pair transitions normalized by evaluable pair-window comparisons in each adjacent sampled interval",
                "data_unit_scope": "eligible within-cluster feature pairs",
                "visual_encoding": "separate retained, gain and loss rates with observed integer numerator/denominator; the remainder comprises other or no recorded transitions",
                "interpretation_boundary": "Concordance Change is descriptive; persistence is distinct from change, and rates do not establish common regulation, causal order, kinase switching, or pathway rewiring",
            },
            selection_rule="all supplied intervals for selected clusters, sorted by elapsed time",
            quantitative_bindings=concordance_bindings(state, selected_ids),
            selected_cluster_count=len(concordance_ids),
            selected_cluster_ids=concordance_ids,
            labels_readable=concordance_readability["labels_readable"],
            readability_audit=concordance_readability,
            title="Interval-wise Concordance Change Summary",
        )
        placement, reason = FigureEligibilityPolicy().classify(concordance_entry, citation_complete=citation_complete)
        concordance_entry["placement"] = placement
        concordance_entry["suppression_reason"] = reason
        manifest["figures"].append(concordance_entry)

    comparison_path, comparison_cards = _generate_protein_adjustment_comparison(state, output_dir)
    if comparison_path:
        comparison_labels = [str(card.get("feature_label") or "") for card in comparison_cards]
        comparison_readability = _figure_readability_audit(
            comparison_path,
            label_count=max(len(comparison_cards), 1),
            labels=comparison_labels,
        )
        comparison_binding = _feature_binding_audit(comparison_cards)
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
                "interpretation_boundary": "axis-specific point tests do not test the adjustment effect; de-novo and reconstructed values are excluded",
            },
            selection_rule="selected finding features at first response, sampled extremum and final observed time; independent matched axes",
            matched_feature_count=len(comparison_cards),
            matched_protein_context=True,
            labels_readable=comparison_readability["labels_readable"],
            readability_audit=comparison_readability,
            feature_binding_audit=comparison_binding,
            quantitative_bindings=[r for card in comparison_cards for r in quantitative_records(card)],
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

    joint = _generate_joint_trajectory_entry(state, output_dir)
    if joint:
        manifest["figures"].append(joint)
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
        "data_scope": "protein-adjusted phosphorylation-feature contrasts with independent conventional eligibility at every displayed condition",
        "data_unit_scope": "phosphorylation feature aggregate",
        "visual_encoding": "protein-adjusted relative PTM log2 contrast; grey denotes unavailable values, white the reference level; equally spaced columns are condition labels ordered by elapsed time, not a proportional time axis",
        "interpretation_boundary": "measured contrast is not activation, directness, or biological-priority score; de novo rows are excluded from the numeric color scale",
    }
    labels = [str(item.get("display_label") or "") for item in selected_features]
    readability = _figure_readability_audit(
        image_path,
        label_count=max(len(selected_features), 1),
        labels=labels,
    )
    binding = _feature_binding_audit(selected_features)
    entry = _entry(
        "reader_quantitative_heatmap", "reader_heatmap", image_path,
        question="Which selected quantitative phosphorylation features show distinct measured profiles across sampled timepoints?",
        evidence_tier="O1", source_evidence_ids=["quantitative.landscape", "temporal.profile_summary"],
        caption_facts=facts,
        selection_rule="selected findings first, then observed shape diversity; partial observations retain gaps",
        selected_feature_count=len(selected_features),
        labels_readable=readability["labels_readable"],
        readability_audit=readability,
        feature_binding_audit=binding,
        conventional_only=bool(selected_features) and all(item.get("render_eligible") for item in selected_features),
        render_axis="protein_adjusted_relative_ptm_contrast",
        selected_reader_feature_ids=binding["selected_reader_feature_ids"],
        selected_features=[dict(item) for item in selected_features],
        quantitative_bindings=[r for item in selected_features for r in item.get("quantitative_bindings") or []],
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
            "quantitative_bindings": list(figure.get("quantitative_bindings") or []),
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
    scope = str(facts.get("data_scope") or facts.get("data_unit_scope") or "recorded evidence").strip()
    encoding = str(facts.get("visual_encoding") or "display encoding").strip()
    boundary = str(facts.get("interpretation_boundary") or "interpretation is bounded by the stated evidence tier").strip()
    return f"{scope[:1].upper() + scope[1:]}. {encoding[:1].upper() + encoding[1:]}. {boundary[:1].upper() + boundary[1:]}."
