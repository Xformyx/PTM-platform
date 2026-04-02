"""
Signal Flow Figure — Publication-quality Receptor → Kinase → Substrate diagram.

v1.0 — Server-side matplotlib figure generation for report insertion.
  - Mirrors the frontend SignalFlowView (KinaseModuleAnalysis.tsx)
  - Receptor → Kinase → Substrate hierarchy with activity classification
  - Color-coded: de_novo (orange), regulated (blue), minor (gray)
  - Receptor source: Treatment (sky), Reactome (rose), Literature (violet)
  - Kinase nodes in amber
  - Outputs PNG file for DOCX/Markdown report insertion

Called from kinase_annotation_node → output saved as signal_flow_diagram.png
"""

import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def generate_signal_flow_figure(
    inferred_receptors: List[dict],
    global_kinase_modules: dict,
    enriched_ptm_data: List[dict],
    output_dir: str,
    ptm_type: str = "phosphorylation",
    max_receptors: int = 8,
    max_substrates_per_kinase: int = 15,
) -> Optional[str]:
    """Generate a publication-quality Signal Flow diagram.

    Args:
        inferred_receptors: List of receptor dicts from DB
            [{name, receptor_class, downstream_ptm_count, via_kinases, source, ...}]
        global_kinase_modules: Kinase module analysis result
            {kinase_modules: [{kinase, canonical, members: [{gene, position, membership}]}]}
        enriched_ptm_data: Full enriched PTM data for activity classification
        output_dir: Directory to save the figure
        ptm_type: 'phosphorylation' or 'ubiquitylation'
        max_receptors: Maximum number of receptors to show
        max_substrates_per_kinase: Maximum substrates per kinase node

    Returns:
        Path to the generated PNG file, or None if generation fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    except ImportError:
        logger.warning("[SIGNAL-FLOW-FIG] matplotlib not available — skipping")
        return None

    if not inferred_receptors:
        logger.info("[SIGNAL-FLOW-FIG] No inferred receptors — skipping figure generation")
        return None

    # ── Build activity classification map ──
    activity_map = _build_activity_classification(enriched_ptm_data)

    # ── Build kinase → PTM substrate mapping ──
    kinase_to_ptms = _build_kinase_to_ptms(global_kinase_modules)

    # ── Select top receptors ──
    receptors = sorted(
        inferred_receptors,
        key=lambda r: r.get("downstream_ptm_count", 0),
        reverse=True,
    )[:max_receptors]

    if not receptors:
        logger.info("[SIGNAL-FLOW-FIG] No receptors after filtering — skipping")
        return None

    # ── Calculate layout dimensions ──
    total_kinases = sum(len(r.get("via_kinases", [])) for r in receptors)
    total_kinases = max(total_kinases, 1)

    fig_width = max(16, min(28, 4 + total_kinases * 2.5))
    fig_height = max(10, min(24, 3 + len(receptors) * 2.8))

    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.axis("off")
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#0f1117")

    # ── Color definitions ──
    SOURCE_COLORS = {
        "treatment_context": "#38bdf8",
        "treatment_context_uniprot": "#38bdf8",
        "reactome": "#fb7185",
        "literature": "#a78bfa",
    }
    KINASE_COLOR = "#f59e0b"
    KINASE_BG = "#451a0320"
    ACTIVITY_COLORS = {
        "de_novo": {"border": "#f97316", "bg": "#431407", "text": "#fdba74"},
        "regulated": {"border": "#3b82f6", "bg": "#1e1b4b", "text": "#93c5fd"},
        "minor": {"border": "#6b7280", "bg": "#1f2937", "text": "#9ca3af"},
    }

    # ── Title ──
    entity_label = "E3 Ligases" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinases"
    ax.text(
        fig_width / 2, fig_height - 0.5,
        f"Signal Flow: Upstream Receptor → {entity_label} → PTM Substrates",
        fontsize=14, fontweight="bold", color="white",
        ha="center", va="top",
    )
    ax.text(
        fig_width / 2, fig_height - 1.0,
        f"Top {len(receptors)} inferred receptors with downstream {ptm_type} signaling cascade",
        fontsize=9, color="#9ca3af",
        ha="center", va="top",
    )

    # ── Draw each receptor chain ──
    y_cursor = fig_height - 1.8
    row_height = max(2.0, (fig_height - 3.0) / len(receptors))

    for rec_idx, rec in enumerate(receptors):
        rec_name = rec.get("name", "Unknown")
        rec_class = rec.get("receptor_class", "")
        rec_source = rec.get("source", "literature")
        via_kinases = rec.get("via_kinases", [])
        ptm_count = rec.get("downstream_ptm_count", 0)
        color = SOURCE_COLORS.get(rec_source, "#a78bfa")

        y_center = y_cursor - row_height / 2

        # ── Receptor node ──
        rec_x = 0.5
        rec_box = FancyBboxPatch(
            (rec_x, y_center - 0.35), 3.0, 0.7,
            boxstyle="round,pad=0.1",
            facecolor=color + "20",
            edgecolor=color,
            linewidth=2,
        )
        ax.add_patch(rec_box)

        # Receptor icon + name
        ax.text(
            rec_x + 0.15, y_center,
            "↑",
            fontsize=10, color=color, fontweight="bold",
            ha="left", va="center",
        )
        display_name = rec_name if len(rec_name) <= 25 else rec_name[:22] + "…"
        ax.text(
            rec_x + 0.45, y_center,
            display_name,
            fontsize=9, fontweight="bold", color=color,
            ha="left", va="center",
        )

        # Receptor metadata
        source_label = {"treatment_context": "T", "treatment_context_uniprot": "T",
                        "reactome": "R", "literature": "L"}.get(rec_source, "L")
        ax.text(
            rec_x + 3.2, y_center,
            f"{rec_class} · {ptm_count} PTMs · {source_label}",
            fontsize=7, color="#9ca3af",
            ha="left", va="center",
        )

        # ── Kinase layer ──
        if via_kinases:
            kinase_start_x = 5.5
            kinase_spacing = max(2.0, min(4.0, (fig_width - kinase_start_x - 1) / max(len(via_kinases), 1)))

            # Arrow from receptor to kinase area
            ax.annotate(
                "", xy=(kinase_start_x - 0.3, y_center),
                xytext=(rec_x + 3.0, y_center),
                arrowprops=dict(
                    arrowstyle="->",
                    color="#4b5563",
                    lw=1.5,
                    connectionstyle="arc3,rad=0",
                ),
            )
            ax.text(
                kinase_start_x - 0.8, y_center + 0.25,
                f"via {entity_label.lower()}:",
                fontsize=7, color="#6b7280",
                ha="center", va="bottom",
            )

            for k_idx, kinase_name in enumerate(via_kinases[:6]):  # max 6 kinases per receptor
                k_x = kinase_start_x + k_idx * kinase_spacing
                kinase_key = kinase_name.upper()

                # Kinase node
                k_box = FancyBboxPatch(
                    (k_x, y_center - 0.25), 1.8, 0.5,
                    boxstyle="round,pad=0.08",
                    facecolor="#451a0330",
                    edgecolor=KINASE_COLOR,
                    linewidth=1.5,
                )
                ax.add_patch(k_box)
                ax.text(
                    k_x + 0.15, y_center,
                    "⚡",
                    fontsize=7, color=KINASE_COLOR,
                    ha="left", va="center",
                )
                ax.text(
                    k_x + 0.4, y_center,
                    kinase_name if len(kinase_name) <= 12 else kinase_name[:10] + "…",
                    fontsize=8, fontweight="medium", color="#fbbf24",
                    ha="left", va="center",
                )

                # ── Substrate PTMs ──
                ptms = kinase_to_ptms.get(kinase_key, [])
                if ptms:
                    ptms_to_show = ptms[:max_substrates_per_kinase]
                    sub_y = y_center - 0.5
                    ax.text(
                        k_x + 0.2, sub_y,
                        f"→ {len(ptms)} substrates:",
                        fontsize=6, color="#6b7280",
                        ha="left", va="top",
                    )

                    # Draw substrate chips
                    chip_x = k_x + 0.2
                    chip_y = sub_y - 0.25
                    chips_per_row = max(1, int(kinase_spacing / 0.85))

                    for p_idx, ptm in enumerate(ptms_to_show):
                        ptm_key = f"{ptm['gene']}_{ptm['position']}"
                        act_class = activity_map.get(ptm_key, "minor")
                        act_colors = ACTIVITY_COLORS[act_class]

                        row = p_idx // chips_per_row
                        col = p_idx % chips_per_row

                        cx = chip_x + col * 0.82
                        cy = chip_y - row * 0.22

                        # Activity indicator
                        prefix = "★" if act_class == "de_novo" else ("●" if act_class == "regulated" else "")
                        label = f"{prefix}{ptm['gene']} {ptm['position']}"
                        if len(label) > 12:
                            label = label[:10] + "…"

                        ax.text(
                            cx, cy,
                            label,
                            fontsize=5.5,
                            color=act_colors["text"],
                            ha="left", va="top",
                            bbox=dict(
                                boxstyle="round,pad=0.08",
                                facecolor=act_colors["bg"],
                                edgecolor=act_colors["border"],
                                linewidth=0.5,
                                alpha=0.8,
                            ),
                        )

        y_cursor -= row_height

    # ── Legend ──
    legend_y = 0.8
    legend_x = 0.5

    # Receptor source legend
    ax.text(legend_x, legend_y, "Receptor source:", fontsize=7, color="#6b7280",
            fontweight="bold", ha="left", va="center")
    for i, (label, clr) in enumerate([
        ("Treatment context (T)", "#38bdf8"),
        ("Reactome (R)", "#fb7185"),
        ("Literature (L)", "#a78bfa"),
    ]):
        ax.plot(legend_x + 2.5 + i * 3.0, legend_y, "o", color=clr, markersize=5)
        ax.text(legend_x + 2.7 + i * 3.0, legend_y, label, fontsize=6, color="#9ca3af",
                ha="left", va="center")

    # Activity legend
    ax.text(legend_x, legend_y - 0.35, "Substrate activity:", fontsize=7, color="#6b7280",
            fontweight="bold", ha="left", va="center")
    for i, (label, act) in enumerate([
        ("★ De novo (control imputed)", "de_novo"),
        ("● Regulated (|Log2FC|≥1, q<0.05)", "regulated"),
        ("Minor change", "minor"),
    ]):
        clrs = ACTIVITY_COLORS[act]
        ax.text(
            legend_x + 2.5 + i * 4.5, legend_y - 0.35,
            label,
            fontsize=6, color=clrs["text"],
            ha="left", va="center",
            bbox=dict(
                boxstyle="round,pad=0.06",
                facecolor=clrs["bg"],
                edgecolor=clrs["border"],
                linewidth=0.5,
            ),
        )

    # ── Save ──
    output_path = Path(output_dir) / "signal_flow_diagram.png"
    fig.tight_layout(pad=0.5)
    fig.savefig(
        str(output_path),
        dpi=200,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)

    logger.info(
        f"[SIGNAL-FLOW-FIG] Generated signal flow diagram: {output_path} "
        f"({len(receptors)} receptors, {total_kinases} kinases)"
    )
    return str(output_path)


def generate_kinase_temporal_heatmap(
    global_kinase_modules: dict,
    output_dir: str,
    ptm_type: str = "phosphorylation",
    max_kinases: int = 20,
) -> Optional[str]:
    """Generate a kinase temporal activity heatmap.

    Shows which kinases are active at each timepoint with PTM count intensity.

    Returns:
        Path to the generated PNG file, or None if generation fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        logger.warning("[KINASE-HEATMAP] matplotlib/numpy not available — skipping")
        return None

    temporal_cascade = global_kinase_modules.get("temporal_cascade", {})
    timepoints = temporal_cascade.get("timepoints", [])
    kinase_activity = temporal_cascade.get("kinase_activity", [])

    if not timepoints or not kinase_activity:
        logger.info("[KINASE-HEATMAP] No temporal data — skipping heatmap generation")
        return None

    # ── Build heatmap matrix ──
    tp_labels = [tp["timepoint"] for tp in timepoints]
    kinases = kinase_activity[:max_kinases]
    kinase_labels = [k["canonical"] for k in kinases]

    matrix = np.zeros((len(kinases), len(tp_labels)))
    for k_idx, kinase in enumerate(kinases):
        for tp_data in kinase.get("timepoints", []):
            tp_name = tp_data["timepoint"]
            if tp_name in tp_labels:
                tp_idx = tp_labels.index(tp_name)
                matrix[k_idx, tp_idx] = tp_data.get("ptm_count", 0)

    # ── Plot ──
    fig_width = max(8, min(16, 3 + len(tp_labels) * 1.2))
    fig_height = max(6, min(14, 2 + len(kinases) * 0.5))
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#0f1117")

    # Custom colormap: dark → amber → orange
    from matplotlib.colors import LinearSegmentedColormap
    colors_list = ["#1a1a2e", "#451a03", "#b45309", "#f59e0b", "#fbbf24"]
    cmap = LinearSegmentedColormap.from_list("kinase_heat", colors_list)

    im = ax.imshow(matrix, cmap=cmap, aspect="auto", interpolation="nearest")

    # Labels
    ax.set_xticks(range(len(tp_labels)))
    ax.set_xticklabels(tp_labels, fontsize=8, color="#d1d5db", rotation=45, ha="right")
    ax.set_yticks(range(len(kinase_labels)))
    ax.set_yticklabels(kinase_labels, fontsize=8, color="#d1d5db")

    # Annotate cells
    for i in range(len(kinases)):
        for j in range(len(tp_labels)):
            val = int(matrix[i, j])
            if val > 0:
                ax.text(j, i, str(val), ha="center", va="center",
                        fontsize=7, color="white" if val > matrix.max() * 0.5 else "#fbbf24",
                        fontweight="bold")

    entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
    ax.set_title(
        f"Temporal {entity_label} Activity Heatmap (PTM substrate count per timepoint)",
        fontsize=11, fontweight="bold", color="white", pad=12,
    )
    ax.set_xlabel("Timepoint", fontsize=9, color="#9ca3af")
    ax.set_ylabel(entity_label, fontsize=9, color="#9ca3af")

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("PTM substrate count", fontsize=8, color="#9ca3af")
    cbar.ax.yaxis.set_tick_params(color="#9ca3af")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="#9ca3af", fontsize=7)

    # Cascade flow arrows
    cascade_flow = temporal_cascade.get("cascade_flow", [])
    if cascade_flow:
        flow_text_parts = []
        for flow in cascade_flow:
            new_k = flow.get("new_kinases", [])
            lost_k = flow.get("lost_kinases", [])
            persist_k = flow.get("persistent_kinases", [])
            from_tp = flow.get("from_timepoint", "")
            to_tp = flow.get("to_timepoint", "")
            if new_k or lost_k:
                parts = [f"{from_tp}→{to_tp}:"]
                if new_k:
                    parts.append(f"+{','.join(new_k[:3])}")
                if lost_k:
                    parts.append(f"-{','.join(lost_k[:3])}")
                flow_text_parts.append(" ".join(parts))

        if flow_text_parts:
            flow_summary = "  |  ".join(flow_text_parts[:4])
            fig.text(
                0.5, 0.01, f"Cascade transitions: {flow_summary}",
                fontsize=7, color="#6b7280", ha="center", va="bottom",
            )

    # ── Save ──
    output_path = Path(output_dir) / "kinase_temporal_heatmap.png"
    fig.tight_layout(pad=1.0)
    fig.savefig(
        str(output_path),
        dpi=200,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)

    logger.info(
        f"[KINASE-HEATMAP] Generated temporal heatmap: {output_path} "
        f"({len(kinases)} kinases × {len(tp_labels)} timepoints)"
    )
    return str(output_path)


# ── Helper functions ──────────────────────────────────────────────────────────

def _build_activity_classification(enriched_ptm_data: List[dict]) -> Dict[str, str]:
    """Build PTM activity classification map from enriched data.

    Returns: {gene_position: "de_novo" | "regulated" | "minor"}
    """
    activity_map = {}
    for ptm in enriched_ptm_data:
        gene = ptm.get("gene_name", ptm.get("gene", ""))
        position = ptm.get("position", ptm.get("site", ""))
        key = f"{gene}_{position}"

        # Check de_novo flag
        if ptm.get("de_novo", False) or ptm.get("control_pseudocount_used", False):
            activity_map[key] = "de_novo"
            continue

        # Check regulated: |Log2FC| >= 1.0 AND q_value < 0.05
        log2fc_values = []
        q_values = []

        # Try timepoint_data
        for tp_data in ptm.get("timepoint_data", []):
            fc = tp_data.get("log2fc", tp_data.get("Log2FC"))
            if fc is not None:
                try:
                    log2fc_values.append(abs(float(fc)))
                except (ValueError, TypeError):
                    pass
            qv = tp_data.get("q_value")
            if qv is not None:
                try:
                    q_values.append(float(qv))
                except (ValueError, TypeError):
                    pass

        # Try direct fields
        if not log2fc_values:
            fc = ptm.get("log2fc", ptm.get("Log2FC", ptm.get("max_abs_log2fc")))
            if fc is not None:
                try:
                    log2fc_values.append(abs(float(fc)))
                except (ValueError, TypeError):
                    pass

        max_abs_fc = max(log2fc_values) if log2fc_values else 0
        min_q = min(q_values) if q_values else 1.0

        if max_abs_fc >= 1.0 and min_q < 0.05:
            activity_map[key] = "regulated"
        elif max_abs_fc >= 1.0:
            activity_map[key] = "regulated"  # fallback: FC-based only
        else:
            activity_map[key] = "minor"

    return activity_map


def _build_kinase_to_ptms(global_kinase_modules: dict) -> Dict[str, List[dict]]:
    """Build kinase → PTM substrate mapping from global kinase modules.

    Returns: {KINASE_KEY: [{gene, position, membership}]}
    """
    kinase_to_ptms = {}
    if not global_kinase_modules:
        return kinase_to_ptms

    for mod in global_kinase_modules.get("kinase_modules", []):
        key = (mod.get("canonical") or mod.get("kinase", "")).upper()
        if not key:
            continue
        members = []
        for member in mod.get("members", []):
            members.append({
                "gene": member.get("gene", ""),
                "position": member.get("position", ""),
                "membership": member.get("membership", "inferred"),
            })
        kinase_to_ptms[key] = members

    return kinase_to_ptms
