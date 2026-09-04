"""
Signal Flow Figure — Publication-quality Receptor → Kinase → Substrate → Non-PTM Effector diagram.

v2.0 — 4-layer Signal Flow with Non-PTM Effector integration.
  - Mirrors the frontend SignalFlowView (KinaseModuleAnalysis.tsx)
  - Receptor → Kinase → Substrate → Non-PTM Effector hierarchy
  - Color-coded: de_novo (orange), regulated (blue), minor (gray)
  - Receptor source: Treatment (sky), Reactome (rose), Literature (violet)
  - Kinase nodes in amber
  - Non-PTM Effector nodes in teal/emerald
  - Outputs PNG file for DOCX/Markdown report insertion

Called from kinase_annotation_node → output saved as signal_flow_diagram.png
"""

import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ptm_shared.de_novo_representation import is_de_novo_representation

logger = logging.getLogger(__name__)


def generate_signal_flow_figure(
    inferred_receptors: List[dict],
    global_kinase_modules: dict,
    enriched_ptm_data: List[dict],
    output_dir: str,
    ptm_type: str = "phosphorylation",
    max_receptors: int = 8,
    max_substrates_per_kinase: int = 15,
    effector_proteins: Optional[List[dict]] = None,
    context_only: bool = True,
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
        effector_proteins: Optional list of Non-PTM effector proteins
            [{gene, connected_substrates, temporal_profile, max_abs_fc, peak_condition, sources}]

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

    # ── Build substrate → effector mapping ──
    substrate_to_effectors = _build_substrate_to_effectors(effector_proteins or [])
    has_effectors = len(substrate_to_effectors) > 0

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

    # Wider figure if we have effectors (4th layer)
    base_width = max(16, min(28, 4 + total_kinases * 2.5))
    fig_width = base_width + (4 if has_effectors else 0)
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
    EFFECTOR_COLORS = {
        "up": {"border": "#10b981", "bg": "#064e3b", "text": "#6ee7b7"},
        "down": {"border": "#f43e5e", "bg": "#4c0519", "text": "#fda4af"},
        "neutral": {"border": "#6b7280", "bg": "#1f2937", "text": "#9ca3af"},
    }

    # ── Title ──
    entity_label = "E3 Ligases" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinases"
    layers_label = "Non-PTM Effectors" if has_effectors else "PTM Substrates"
    ax.text(
        fig_width / 2, fig_height - 0.5,
        f"Signaling Context: Receptor · {entity_label} · PTM Substrates" + (" · Non-PTM Effectors" if has_effectors else ""),
        fontsize=14, fontweight="bold", color="white",
        ha="center", va="top",
    )
    ax.text(
        fig_width / 2, fig_height - 1.0,
        f"Top {len(receptors)} pathway/literature-linked receptors with measured {ptm_type} context"
        + (f" + {len(substrate_to_effectors)} effector context links" if has_effectors else ""),
        fontsize=9, color="#9ca3af",
        ha="center", va="top",
    )

    # ── Layer column headers ──
    header_y = fig_height - 1.5
    layer_positions = {
        "receptor": 2.0,
        "kinase": 6.5,
        "substrate": 11.0 if has_effectors else 10.0,
    }
    if has_effectors:
        layer_positions["effector"] = fig_width - 4.0

    for layer_name, lx in layer_positions.items():
        label = {
            "receptor": "Receptors",
            "kinase": entity_label,
            "substrate": "PTM Substrates",
            "effector": "Non-PTM Effectors",
        }[layer_name]
        color = {
            "receptor": "#38bdf8",
            "kinase": "#f59e0b",
            "substrate": "#93c5fd",
            "effector": "#6ee7b7",
        }[layer_name]
        ax.text(
            lx, header_y, f"▎{label}",
            fontsize=8, fontweight="bold", color=color,
            ha="left", va="center", alpha=0.7,
        )

    # ── Draw each receptor chain ──
    y_cursor = fig_height - 2.2
    row_height = max(2.0, (fig_height - 3.5) / len(receptors))

    # Track substrate positions for effector connections
    _substrate_positions: Dict[str, Tuple[float, float]] = {}  # gene_upper -> (x, y)

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
            if has_effectors:
                kinase_spacing = max(1.8, min(3.0, (fig_width - kinase_start_x - 6) / max(len(via_kinases), 1)))

            # Context-only by default. Receptor-to-kinase visual adjacency is
            # not an Order-specific directed relationship.
            if context_only:
                ax.plot([rec_x + 3.0, kinase_start_x - 0.3], [y_center, y_center],
                        color="#6b7280", lw=1.2, ls=(0, (3, 2)))
            else:
                ax.annotate("", xy=(kinase_start_x - 0.3, y_center), xytext=(rec_x + 3.0, y_center),
                            arrowprops=dict(arrowstyle="->", color="#4b5563", lw=1.5, connectionstyle="arc3,rad=0"))
            ax.text(
                kinase_start_x - 0.8, y_center + 0.25,
                f"{entity_label.lower()} context:",
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
                        f"• {len(ptms)} PTM context:",
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

                        # Track substrate position for effector connections
                        gene_upper = ptm["gene"].upper()
                        if gene_upper not in _substrate_positions:
                            _substrate_positions[gene_upper] = (cx + 0.4, cy)

        y_cursor -= row_height

    # ── 4th Layer: Non-PTM Effector nodes ──
    if has_effectors and effector_proteins:
        effector_x = layer_positions.get("effector", fig_width - 4.0)
        # Select top effectors by max_abs_fc
        top_effectors = sorted(
            effector_proteins,
            key=lambda e: e.get("max_abs_fc", 0),
            reverse=True,
        )[:12]  # max 12 effectors

        if top_effectors:
            eff_y_start = fig_height - 2.5
            eff_spacing = min(1.2, (fig_height - 3.5) / max(len(top_effectors), 1))

            for eff_idx, eff in enumerate(top_effectors):
                eff_gene = eff.get("gene", "Unknown")
                eff_fc = eff.get("peak_fc", 0)
                eff_cond = eff.get("peak_condition", "")
                eff_sources = eff.get("sources", [])
                eff_subs = eff.get("connected_substrates", [])

                ey = eff_y_start - eff_idx * eff_spacing

                # Determine color by direction
                if eff_fc > 0.3:
                    eff_clr = EFFECTOR_COLORS["up"]
                elif eff_fc < -0.3:
                    eff_clr = EFFECTOR_COLORS["down"]
                else:
                    eff_clr = EFFECTOR_COLORS["neutral"]

                # Effector node box
                eff_box = FancyBboxPatch(
                    (effector_x, ey - 0.2), 3.5, 0.4,
                    boxstyle="round,pad=0.08",
                    facecolor=eff_clr["bg"],
                    edgecolor=eff_clr["border"],
                    linewidth=1.2,
                )
                ax.add_patch(eff_box)

                # Effector gene name
                direction_icon = "▲" if eff_fc > 0 else "▼" if eff_fc < 0 else "●"
                ax.text(
                    effector_x + 0.1, ey,
                    direction_icon,
                    fontsize=6, color=eff_clr["text"],
                    ha="left", va="center",
                )
                ax.text(
                    effector_x + 0.35, ey,
                    eff_gene if len(eff_gene) <= 10 else eff_gene[:8] + "…",
                    fontsize=7, fontweight="bold", color=eff_clr["text"],
                    ha="left", va="center",
                )

                # FC and peak info
                fc_str = f"{eff_fc:+.2f}" if eff_fc != 0 else "0.00"
                source_str = "/".join(eff_sources[:2])
                ax.text(
                    effector_x + 1.8, ey,
                    f"FC:{fc_str} @{eff_cond}",
                    fontsize=5, color="#9ca3af",
                    ha="left", va="center",
                )

                # Draw connection lines from substrates to effector
                for sub in eff_subs[:3]:  # max 3 connections per effector
                    sub_gene_upper = sub.get("gene", "").upper()
                    if sub_gene_upper in _substrate_positions:
                        sx, sy = _substrate_positions[sub_gene_upper]
                        if context_only:
                            ax.plot([sx + 0.3, effector_x], [sy, ey], color=eff_clr["border"] + "80",
                                    lw=0.8, ls=(0, (3, 2)))
                        else:
                            ax.annotate("", xy=(effector_x, ey), xytext=(sx + 0.3, sy),
                                        arrowprops=dict(arrowstyle="->", color=eff_clr["border"] + "60",
                                                        lw=0.8, connectionstyle="arc3,rad=0.15"))

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

    # Effector legend (if applicable)
    if has_effectors:
        ax.text(legend_x, legend_y - 0.7, "Non-PTM Effector:", fontsize=7, color="#6b7280",
                fontweight="bold", ha="left", va="center")
        for i, (label, eff_type) in enumerate([
            ("▲ Upregulated (Protein FC>0)", "up"),
            ("▼ Downregulated (Protein FC<0)", "down"),
        ]):
            clrs = EFFECTOR_COLORS[eff_type]
            ax.text(
                legend_x + 2.5 + i * 4.5, legend_y - 0.7,
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

    effector_count = len(substrate_to_effectors) if has_effectors else 0
    logger.info(
        f"[SIGNAL-FLOW-FIG] Generated signal flow diagram: {output_path} "
        f"({len(receptors)} receptors, {total_kinases} kinases, {effector_count} effector connections)"
    )
    return str(output_path)


def generate_kinase_temporal_heatmap(
    global_kinase_modules: dict,
    output_dir: str,
    ptm_type: str = "phosphorylation",
    max_kinases: int = 30,
    kinase_activity_heatmap: Optional[dict] = None,
) -> Optional[str]:
    """Generate a kinase temporal activity heatmap showing activation/inhibition direction.

    Uses kinase_activity_heatmap data (substrate-derived signed scores) instead
    of simple PTM counts. Colors distinguish higher versus lower aggregate
    substrate signals; this is candidate context, not direct kinase activity.

    Args:
        global_kinase_modules: Kinase module analysis result
        output_dir: Directory to save the figure
        ptm_type: 'phosphorylation' or 'ubiquitylation'
        max_kinases: Maximum number of kinases to show
        kinase_activity_heatmap: Optional heatmap data with per-condition scores
            {kinase_scores, conditions, peak_sync, cowave_groups, all_patterns}

    Returns:
        Path to the generated PNG file, or None if generation fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
        from matplotlib.patches import Rectangle
    except ImportError:
        logger.warning("[KINASE-HEATMAP] matplotlib/numpy not available — skipping")
        return None

    entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"

    # ── Prefer kinase_activity_heatmap (has direction info) ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("kinase_scores"):
        return _generate_directional_heatmap(
            kinase_activity_heatmap, output_dir, ptm_type, entity_label, max_kinases
        )

    # ── Fallback: original PTM count heatmap ──
    temporal_cascade = global_kinase_modules.get("temporal_cascade", {})
    timepoints = temporal_cascade.get("timepoints", [])
    kinase_activity = temporal_cascade.get("kinase_activity", [])

    if not timepoints or not kinase_activity:
        logger.info("[KINASE-HEATMAP] No temporal data — skipping heatmap generation")
        return None

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

    fig_width = max(8, min(16, 3 + len(tp_labels) * 1.2))
    fig_height = max(6, min(14, 2 + len(kinases) * 0.5))
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#0f1117")

    colors_list = ["#1a1a2e", "#451a03", "#b45309", "#f59e0b", "#fbbf24"]
    cmap = LinearSegmentedColormap.from_list("kinase_heat", colors_list)
    im = ax.imshow(matrix, cmap=cmap, aspect="auto", interpolation="nearest")

    ax.set_xticks(range(len(tp_labels)))
    ax.set_xticklabels(tp_labels, fontsize=8, color="#d1d5db", rotation=45, ha="right")
    ax.set_yticks(range(len(kinase_labels)))
    ax.set_yticklabels(kinase_labels, fontsize=8, color="#d1d5db")

    for i in range(len(kinases)):
        for j in range(len(tp_labels)):
            val = int(matrix[i, j])
            if val > 0:
                ax.text(j, i, str(val), ha="center", va="center",
                        fontsize=7, color="white" if val > matrix.max() * 0.5 else "#fbbf24",
                        fontweight="bold")

    ax.set_title(
        f"Temporal {entity_label} Activity Heatmap (PTM substrate count per timepoint)",
        fontsize=11, fontweight="bold", color="white", pad=12,
    )
    ax.set_xlabel("Timepoint", fontsize=9, color="#9ca3af")
    ax.set_ylabel(entity_label, fontsize=9, color="#9ca3af")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("PTM substrate count", fontsize=8, color="#9ca3af")
    cbar.ax.yaxis.set_tick_params(color="#9ca3af")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="#9ca3af", fontsize=7)

    output_path = Path(output_dir) / "kinase_temporal_heatmap.png"
    fig.tight_layout(pad=1.0)
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"[KINASE-HEATMAP] Generated fallback heatmap: {output_path}")
    return str(output_path)


def _generate_directional_heatmap(
    kinase_activity_heatmap: dict,
    output_dir: str,
    ptm_type: str,
    entity_label: str,
    max_kinases: int = 30,
) -> Optional[str]:
    """Generate publication-quality directional kinase activity heatmap.

    Red = higher aggregate substrate score
    Blue = lower aggregate substrate score
    Intensity = signal strength (dominant direction sum)
    Rows grouped by temporal pattern with annotation sidebar.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    from matplotlib.patches import Rectangle

    kinase_scores = kinase_activity_heatmap.get("kinase_scores", [])
    conditions = kinase_activity_heatmap.get("conditions", [])
    all_patterns = kinase_activity_heatmap.get("all_patterns", {})

    if not kinase_scores or not conditions:
        logger.info("[KINASE-HEATMAP] No kinase_scores or conditions — skipping")
        return None

    # ── Pattern ordering (group kinases by temporal pattern) ──
    pattern_order = [
        "sustained_activation", "sustained_inactivation",
        "progressive_amplification", "progressive_decay",
        "early_only", "late_onset",
    ]
    # Dynamic patterns (emergence_at_X, spike_at_X, etc.) sorted alphabetically
    dynamic_patterns = sorted(set(
        ks.get("temporal_pattern", "mixed") for ks in kinase_scores
    ) - set(pattern_order) - {"mixed", "inactive"})
    pattern_order.extend(dynamic_patterns)
    pattern_order.extend(["mixed", "inactive"])

    def pattern_sort_key(ks):
        pat = ks.get("temporal_pattern", "mixed")
        try:
            idx = pattern_order.index(pat)
        except ValueError:
            idx = len(pattern_order)
        # Secondary sort: by peak_score descending
        return (idx, -abs(ks.get("peak_score", 0)))

    # Sort and limit
    sorted_scores = sorted(kinase_scores, key=pattern_sort_key)
    # Filter out inactive
    sorted_scores = [ks for ks in sorted_scores if ks.get("temporal_pattern") != "inactive"]
    sorted_scores = sorted_scores[:max_kinases]

    if not sorted_scores:
        logger.info("[KINASE-HEATMAP] No active kinases after filtering")
        return None

    n_kinases = len(sorted_scores)
    n_conds = len(conditions)

    # ── Build matrix (scores = dominant direction sum) ──
    matrix = np.zeros((n_kinases, n_conds))
    kinase_labels = []
    pattern_labels = []

    for i, ks in enumerate(sorted_scores):
        k_name = ks.get("kinase", "Unknown")
        kinase_labels.append(k_name)
        pattern_labels.append(ks.get("temporal_pattern", "mixed"))
        scores = ks.get("scores", {})
        for j, c in enumerate(conditions):
            matrix[i, j] = scores.get(c, 0)

    # ── Figure layout: main heatmap + pattern sidebar ──
    fig_width = max(10, min(18, 4 + n_conds * 1.5 + 3))  # +3 for pattern column
    fig_height = max(7, min(20, 2.5 + n_kinases * 0.45))

    fig = plt.figure(figsize=(fig_width, fig_height))
    fig.patch.set_facecolor("white")

    # GridSpec: [pattern_sidebar | main_heatmap | colorbar]
    gs = fig.add_gridspec(1, 3, width_ratios=[0.8, n_conds, 0.3], wspace=0.05)
    ax_pattern = fig.add_subplot(gs[0, 0])
    ax_main = fig.add_subplot(gs[0, 1])
    ax_cbar = fig.add_subplot(gs[0, 2])

    # ── Diverging colormap: lower score → White → higher score ──
    colors_div = ["#1e3a5f", "#3b82f6", "#93c5fd", "#ffffff", "#fca5a5", "#ef4444", "#7f1d1d"]
    cmap_div = LinearSegmentedColormap.from_list("candidate_context_score", colors_div)

    # Symmetric normalization
    max_abs = max(abs(matrix.min()), abs(matrix.max()), 0.1)
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0, vmax=max_abs)

    # ── Main heatmap ──
    im = ax_main.imshow(matrix, cmap=cmap_div, norm=norm, aspect="auto", interpolation="nearest")

    # Cell annotations (score values)
    for i in range(n_kinases):
        for j in range(n_conds):
            val = matrix[i, j]
            if abs(val) >= 0.1:
                text_color = "white" if abs(val) > max_abs * 0.6 else "#333333"
                ax_main.text(j, i, f"{val:+.1f}", ha="center", va="center",
                            fontsize=6.5, color=text_color, fontweight="bold")

    # Condition labels (x-axis)
    ax_main.set_xticks(range(n_conds))
    ax_main.set_xticklabels(conditions, fontsize=9, rotation=45, ha="right", color="#333333")
    ax_main.set_yticks(range(n_kinases))
    ax_main.set_yticklabels(kinase_labels, fontsize=8, color="#333333")

    # Grid lines
    for i in range(n_kinases + 1):
        ax_main.axhline(i - 0.5, color="#e5e7eb", linewidth=0.5)
    for j in range(n_conds + 1):
        ax_main.axvline(j - 0.5, color="#e5e7eb", linewidth=0.5)

    ax_main.set_title(
        f"Temporal {entity_label} Candidate Context Score (Substrate-Derived)",
        fontsize=11, fontweight="bold", color="#1f2937", pad=12,
    )
    ax_main.set_xlabel("Condition / Timepoint", fontsize=9, color="#4b5563")

    # ── Pattern sidebar ──
    pattern_colors = {
        "sustained_activation": "#dc2626",
        "sustained_inactivation": "#2563eb",
        "progressive_amplification": "#ea580c",
        "progressive_decay": "#7c3aed",
        "early_only": "#f59e0b",
        "late_onset": "#059669",
        "mixed": "#6b7280",
        "inactive": "#d1d5db",
    }
    # Default color for dynamic patterns
    dynamic_color_pool = ["#0891b2", "#db2777", "#65a30d", "#c026d3", "#0d9488"]

    ax_pattern.set_xlim(0, 1)
    ax_pattern.set_ylim(-0.5, n_kinases - 0.5)
    ax_pattern.invert_yaxis()
    ax_pattern.axis("off")

    # Draw pattern color blocks
    prev_pattern = None
    group_start = 0
    for i, pat in enumerate(pattern_labels + [None]):
        if pat != prev_pattern and prev_pattern is not None:
            # Draw block for previous group
            color = pattern_colors.get(prev_pattern, "")
            if not color:
                # Dynamic pattern - assign from pool
                dyn_idx = dynamic_patterns.index(prev_pattern) if prev_pattern in dynamic_patterns else 0
                color = dynamic_color_pool[dyn_idx % len(dynamic_color_pool)]

            block_height = i - group_start
            rect = Rectangle((0, group_start - 0.5), 0.3, block_height,
                           facecolor=color, edgecolor="white", linewidth=0.5, alpha=0.8)
            ax_pattern.add_patch(rect)

            # Pattern label (abbreviated)
            label = _abbreviate_pattern(prev_pattern)
            mid_y = group_start + block_height / 2 - 0.5
            ax_pattern.text(0.4, mid_y, label, fontsize=6.5, color="#374151",
                          va="center", ha="left", style="italic")

            group_start = i
        prev_pattern = pat

    ax_pattern.set_title("Pattern", fontsize=8, color="#4b5563", pad=5)

    # ── Colorbar ──
    cb = fig.colorbar(im, cax=ax_cbar)
    cb.set_label(f"{entity_label} Candidate Context Score\n(Weighted Substrate Log2FC)", fontsize=8, color="#4b5563")
    cb.ax.yaxis.set_tick_params(color="#4b5563", labelsize=7)
    plt.setp(cb.ax.yaxis.get_ticklabels(), color="#4b5563")

    # Candidate-context labels, not direct activity labels.
    ax_cbar.text(0.5, 1.02, "Higher score", transform=ax_cbar.transAxes,
                fontsize=7, color="#dc2626", ha="center", fontweight="bold")
    ax_cbar.text(0.5, -0.02, "Lower score", transform=ax_cbar.transAxes,
                fontsize=7, color="#2563eb", ha="center", fontweight="bold", va="top")

    # ── Footer: data source note ──
    fig.text(
        0.5, 0.01,
        f"Score = weighted sum of substrate Log2FC per condition. "
        f"Positive (red) = higher aggregate substrate score; negative (blue) = lower aggregate substrate score. "
        f"Rows grouped by detected temporal pattern. This figure provides candidate context only, not direct {entity_label.lower()} activity or kinase–site attribution.",
        fontsize=7, color="#6b7280", ha="center", va="bottom", style="italic",
    )

    # ── Save ──
    output_path = Path(output_dir) / "kinase_temporal_heatmap.png"
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info(
        f"[KINASE-HEATMAP] Generated directional heatmap: {output_path} "
        f"({n_kinases} kinases × {n_conds} conditions, patterns={len(set(pattern_labels))})"
    )
    return str(output_path)


def _abbreviate_pattern(pattern: str) -> str:
    """Abbreviate temporal pattern name for sidebar display."""
    abbrevs = {
        "sustained_activation": "Sustained Up",
        "sustained_inactivation": "Sustained Down",
        "progressive_amplification": "Amplifying",
        "progressive_decay": "Decaying",
        "early_only": "Early Only",
        "late_onset": "Late Onset",
        "mixed": "Mixed",
        "inactive": "Inactive",
    }
    if pattern in abbrevs:
        return abbrevs[pattern]
    # Dynamic patterns: emergence_at_6h → Emerge@6h
    if pattern.startswith("emergence_at_"):
        return f"Emerge@{pattern[13:]}"
    if pattern.startswith("disappearance_at_"):
        return f"Disappear@{pattern[17:]}"
    if pattern.startswith("spike_at_"):
        return f"Spike@{pattern[9:]}"
    if pattern.startswith("reversal_at_"):
        return f"Reversal@{pattern[12:]}"
    return pattern[:15]


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
        if is_de_novo_representation(ptm):
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


def _build_substrate_to_effectors(effector_proteins: List[dict]) -> Dict[str, List[dict]]:
    """Build substrate → effector mapping from effector proteins list.

    Returns: {SUBSTRATE_GENE_UPPER: [{gene, peak_fc, peak_condition, sources}]}
    """
    substrate_to_effectors: Dict[str, List[dict]] = {}
    if not effector_proteins:
        return substrate_to_effectors

    for eff in effector_proteins:
        for sub in eff.get("connected_substrates", []):
            sub_gene = sub.get("gene", "").upper()
            if not sub_gene:
                continue
            if sub_gene not in substrate_to_effectors:
                substrate_to_effectors[sub_gene] = []
            substrate_to_effectors[sub_gene].append({
                "gene": eff.get("gene", ""),
                "peak_fc": eff.get("peak_fc", 0),
                "peak_condition": eff.get("peak_condition", ""),
                "sources": eff.get("sources", []),
            })

    return substrate_to_effectors


# ── Fig 3: Context-Aware PTM Heatmap (v10.2) ──────────────────────────────────

def generate_context_aware_ptm_heatmap(
    sections: Dict[str, str],
    vector_plot_raw_data: List[dict],
    conditions: List[str],
    output_dir: str,
    ptm_type: str = "phosphorylation",
    max_sites: int = 40,
) -> Optional[str]:
    """Generate a PTM heatmap showing only sites discussed in the report text.

    Post-writing figure: extracts protein/site mentions from LLM-written sections,
    matches them against vector_plot_raw_data, and generates a clustered heatmap.

    Args:
        sections: Dict of section_type → text (from write_sections)
        vector_plot_raw_data: Full PTM data [{gene, position, condition, ptm_relative_log2fc, ...}]
        conditions: List of condition/timepoint labels in order
        output_dir: Directory to save the figure
        ptm_type: 'phosphorylation' or 'ubiquitylation'
        max_sites: Maximum number of PTM sites to display

    Returns:
        Path to the generated PNG file, or None if generation fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
        import re
    except ImportError:
        logger.warning("[CTX-HEATMAP] matplotlib/numpy not available — skipping")
        return None

    if not vector_plot_raw_data or not conditions:
        logger.info("[CTX-HEATMAP] No vector_plot_raw_data or conditions — skipping")
        return None

    # ── Step 1: Extract mentioned proteins/sites from report text ──
    combined_text = " ".join(sections.get(k, "") for k in ["results", "discussion", "abstract", "conclusion"])
    if not combined_text.strip():
        logger.info("[CTX-HEATMAP] No text in results/discussion — skipping")
        return None

    # Build lookup of available PTM sites
    # Key: (GENE_UPPER, position_str) → {condition: log2fc}
    site_data: Dict[tuple, Dict[str, float]] = {}
    all_genes = set()
    for row in vector_plot_raw_data:
        gene = (row.get("gene") or row.get("gene_name") or "").strip()
        position = str(row.get("position") or row.get("site") or "").strip()
        condition = (row.get("condition") or "").strip()
        fc = row.get("ptm_relative_log2fc") or row.get("log2fc") or row.get("Log2FC")
        if not gene or not condition:
            continue
        is_denovo = is_de_novo_representation(row)
        lod_rel = row.get("lod_relative_log2") or row.get("LOD_Relative_Log2")
        try:
            fc_val = float(fc) if fc is not None else 0.0
        except (ValueError, TypeError):
            fc_val = 0.0
        try:
            lod_val = float(lod_rel) if lod_rel not in (None, "", "nan") else None
        except (TypeError, ValueError):
            lod_val = None
        plot_val = lod_val if is_denovo and lod_val is not None else (0.0 if is_denovo else fc_val)

        key = (gene.upper(), position)
        if key not in site_data:
            site_data[key] = {}
        site_data[key][condition] = plot_val
        if is_denovo:
            site_data[key]["_denovo"] = True
        all_genes.add(gene.upper())

    if not site_data:
        logger.info("[CTX-HEATMAP] No site_data built from vector_plot_raw_data — skipping")
        return None

    # Extract gene names mentioned in text (case-insensitive match against known genes)
    mentioned_genes = set()
    text_upper = combined_text.upper()
    for gene in all_genes:
        # Match whole word (avoid partial matches like "AKT" in "RAKTL")
        if re.search(r'\b' + re.escape(gene) + r'\b', text_upper):
            mentioned_genes.add(gene)

    # Also try to extract specific site mentions (e.g., "Ser473", "T308", "Y416")
    site_pattern = re.compile(r'\b([A-Z][a-z]*\d+[A-Z]?\d*)\b')  # e.g., Ser473, T308
    mentioned_sites_raw = set(site_pattern.findall(combined_text))

    # Match mentioned genes to available sites
    matched_sites = []
    for (gene, pos), fc_dict in site_data.items():
        if gene in mentioned_genes:
            # Check if any condition has non-zero FC
            if any(abs(v) > 0.01 for k, v in fc_dict.items() if k != "_denovo" and isinstance(v, (int, float))):
                matched_sites.append((gene, pos, fc_dict))

    if not matched_sites:
        logger.info(f"[CTX-HEATMAP] No PTM sites matched from {len(mentioned_genes)} mentioned genes — skipping")
        return None

    # Sort by max absolute display value. De novo already uses LOD-relative, not pseudo-FC.
    def _site_sort_value(item):
        values = [v for k, v in item[2].items() if k != "_denovo" and isinstance(v, (int, float))]
        return max((abs(v) for v in values), default=0.0)

    matched_sites.sort(key=_site_sort_value, reverse=True)
    matched_sites = matched_sites[:max_sites]

    logger.info(f"[CTX-HEATMAP] Matched {len(matched_sites)} PTM sites from {len(mentioned_genes)} mentioned genes")

    # ── Step 2: Build matrix ──
    n_sites = len(matched_sites)
    n_conds = len(conditions)
    matrix = np.zeros((n_sites, n_conds))
    site_labels = []

    denovo_rows = []
    for i, (gene, pos, fc_dict) in enumerate(matched_sites):
        is_denovo = bool(fc_dict.get("_denovo"))
        label = f"{gene} {pos}" if pos else gene
        if is_denovo:
            label = f"★ {label}"
        site_labels.append(label)
        denovo_rows.append(is_denovo)
        for j, c in enumerate(conditions):
            matrix[i, j] = float(fc_dict.get(c, 0.0) or 0.0)

    # ── Step 3: Simple hierarchical clustering of rows ──
    try:
        from scipy.cluster.hierarchy import linkage, leaves_list
        from scipy.spatial.distance import pdist
        if n_sites > 2:
            dist = pdist(matrix, metric="euclidean")
            Z = linkage(dist, method="ward")
            order = leaves_list(Z)
            matrix = matrix[order]
            site_labels = [site_labels[i] for i in order]
    except ImportError:
        pass  # Skip clustering if scipy not available

    # ── Step 4: Plot ──
    fig_width = max(9, min(16, 3.5 + n_conds * 1.3))
    fig_height = max(6, min(22, 2 + n_sites * 0.4))

    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Diverging colormap: Blue → White → Red
    colors_div = ["#1e3a5f", "#3b82f6", "#93c5fd", "#ffffff", "#fca5a5", "#ef4444", "#7f1d1d"]
    cmap_div = LinearSegmentedColormap.from_list("ptm_fc", colors_div)

    quantified = matrix.copy()
    for i, is_denovo in enumerate(denovo_rows):
        if is_denovo:
            quantified[i, :] = np.nan
    finite = quantified[np.isfinite(quantified)]
    max_abs = max(abs(float(finite.min())) if finite.size else 0.5,
                  abs(float(finite.max())) if finite.size else 0.5,
                  0.5)
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0, vmax=max_abs)

    im = ax.imshow(matrix, cmap=cmap_div, norm=norm, aspect="auto", interpolation="nearest")

    # Cell annotations. De novo uses ≥ LOD-relative, not conventional Log2FC.
    for i in range(n_sites):
        for j in range(n_conds):
            val = matrix[i, j]
            if denovo_rows[i]:
                if abs(val) >= 0.3:
                    ax.text(j, i, f"≥{val:.1f}", ha="center", va="center",
                            fontsize=6, color="#7c2d12", fontweight="bold")
                continue
            if abs(val) >= 0.3:
                text_color = "white" if abs(val) > max_abs * 0.55 else "#333333"
                ax.text(j, i, f"{val:+.1f}", ha="center", va="center",
                        fontsize=6, color=text_color, fontweight="bold")

    # Labels
    ax.set_xticks(range(n_conds))
    ax.set_xticklabels(conditions, fontsize=9, rotation=45, ha="right", color="#333333")
    ax.set_yticks(range(n_sites))
    ax.set_yticklabels(site_labels, fontsize=7, color="#333333")

    # Grid
    for i in range(n_sites + 1):
        ax.axhline(i - 0.5, color="#e5e7eb", linewidth=0.3)
    for j in range(n_conds + 1):
        ax.axvline(j - 0.5, color="#e5e7eb", linewidth=0.3)

    mod_label = "Ubiquitylation" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Phosphorylation"
    ax.set_title(
        f"Key {mod_label} Sites Discussed in This Report "
        f"(Log₂FC; ★ de novo = LOD-relative ≥)",
        fontsize=11, fontweight="bold", color="#1f2937", pad=12,
    )
    ax.set_xlabel("Condition / Timepoint", fontsize=9, color="#4b5563")

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("Log₂FC (PTM-level)", fontsize=8, color="#4b5563")
    cbar.ax.yaxis.set_tick_params(color="#4b5563", labelsize=7)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="#4b5563")

    # Footer
    fig.text(
        0.5, 0.005,
        f"Heatmap of {n_sites} PTM sites referenced in the report text. "
        f"Red/blue = quantified Log₂FC. ★ de novo cells are LOD-relative lower bounds, not fold-change. "
        f"Colormap scale excludes de novo.",
        fontsize=7, color="#6b7280", ha="center", va="bottom", style="italic",
    )

    # ── Save ──
    output_path = Path(output_dir) / "context_ptm_heatmap.png"
    fig.tight_layout(rect=[0, 0.025, 1, 0.97])
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info(
        f"[CTX-HEATMAP] Generated context-aware PTM heatmap: {output_path} "
        f"({n_sites} sites × {n_conds} conditions from {len(mentioned_genes)} mentioned genes)"
    )
    return str(output_path)


# ── Fig 4: Pathway Diagram (v10.2) ──────────────────────────────────────────────

def generate_pathway_diagram(
    inferred_receptors: List[dict],
    global_kinase_modules: dict,
    enriched_ptm_data: List[dict],
    output_dir: str,
    ptm_type: str = "phosphorylation",
    experimental_context: Optional[dict] = None,
    kinase_activity_heatmap: Optional[dict] = None,
    effector_proteins: Optional[List[dict]] = None,
    max_receptors: int = 5,
    max_kinases: int = 8,
    max_substrates: int = 10,
    max_effectors: int = 6,
    context_only: bool = True,
) -> Optional[str]:
    """Generate a publication-quality pathway diagram in cascade arrow format.

    Standard journal-style signaling pathway: vertical flow with horizontal layers.
    Stimulus → Receptor → Kinase → Substrate → Effector

    Args:
        inferred_receptors: List of receptor dicts (sorted by confidence_score)
        global_kinase_modules: Kinase module analysis result
        enriched_ptm_data: Full enriched PTM data
        output_dir: Directory to save the figure
        ptm_type: 'phosphorylation' or 'ubiquitylation'
        experimental_context: Optional context with treatment info
        kinase_activity_heatmap: Optional heatmap data for kinase direction
        effector_proteins: Optional list of Non-PTM effector proteins
        max_receptors: Maximum receptors to show
        max_kinases: Maximum kinases to show
        max_substrates: Maximum substrates to show
        max_effectors: Maximum effectors to show

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
        logger.warning("[PATHWAY-DIAGRAM] matplotlib not available — skipping")
        return None

    if not inferred_receptors:
        logger.info("[PATHWAY-DIAGRAM] No inferred receptors — skipping")
        return None

    entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"

    # ── Gather data for each layer ──

    # Layer 1: Stimulus/Treatment
    treatment_name = ""
    if experimental_context:
        treatment_name = (
            experimental_context.get("treatment", "") or
            experimental_context.get("stimulus", "") or
            experimental_context.get("condition", "") or
            ""
        )

    # Layer 2: Receptors (top by confidence_score)
    receptors = sorted(
        inferred_receptors,
        key=lambda r: r.get("confidence_score", r.get("downstream_ptm_count", 0)),
        reverse=True,
    )[:max_receptors]

    # Layer 3: Kinases (from receptor via_kinases + heatmap data for direction)
    kinase_direction = {}  # kinase_name → "up" | "down" | "mixed"
    if kinase_activity_heatmap:
        for ks in kinase_activity_heatmap.get("kinase_scores", []):
            k_name = ks.get("kinase", "")
            pattern = ks.get("temporal_pattern", "mixed")
            peak = ks.get("peak_score", 0)
            if "activation" in pattern or "amplif" in pattern or peak > 0:
                kinase_direction[k_name.upper()] = "up"
            elif "inactivation" in pattern or "decay" in pattern or peak < 0:
                kinase_direction[k_name.upper()] = "down"
            else:
                kinase_direction[k_name.upper()] = "mixed"

    # Collect unique kinases from receptors
    all_kinases = []
    seen_kinases = set()
    for rec in receptors:
        for k in rec.get("via_kinases", []):
            k_upper = k.upper()
            if k_upper not in seen_kinases:
                seen_kinases.add(k_upper)
                all_kinases.append(k)
    all_kinases = all_kinases[:max_kinases]

    # Layer 4: Substrates (top regulated PTMs)
    activity_map = _build_activity_classification(enriched_ptm_data)
    kinase_to_ptms = _build_kinase_to_ptms(global_kinase_modules)

    # Get substrates connected to displayed kinases
    substrate_list = []
    seen_subs = set()
    for k in all_kinases:
        for ptm in kinase_to_ptms.get(k.upper(), []):
            key = f"{ptm['gene']}_{ptm['position']}"
            if key not in seen_subs:
                seen_subs.add(key)
                act = activity_map.get(key, "minor")
                if act in ("de_novo", "regulated"):
                    substrate_list.append({"gene": ptm["gene"], "position": ptm["position"], "activity": act, "kinase": k})
    substrate_list = substrate_list[:max_substrates]

    # Layer 5: Effectors
    eff_list = []
    if effector_proteins:
        eff_list = sorted(effector_proteins, key=lambda e: abs(e.get("max_abs_fc", 0)), reverse=True)[:max_effectors]

    has_effectors = len(eff_list) > 0

    # ── Layout calculation ──
    n_layers = 4 + (1 if treatment_name else 0) + (1 if has_effectors else 0)
    fig_width = max(10, min(16, 2 + max(len(receptors), len(all_kinases), len(substrate_list)) * 2.0))
    fig_height = max(8, min(14, n_layers * 2.2 + 2))

    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # ── Color scheme (publication standard) ──
    COLORS = {
        "stimulus": {"bg": "#fef3c7", "border": "#d97706", "text": "#92400e"},
        "receptor": {"bg": "#dbeafe", "border": "#2563eb", "text": "#1e40af"},
        "kinase_up": {"bg": "#fee2e2", "border": "#dc2626", "text": "#991b1b"},
        "kinase_down": {"bg": "#dbeafe", "border": "#2563eb", "text": "#1e40af"},
        "kinase_mixed": {"bg": "#f3f4f6", "border": "#6b7280", "text": "#374151"},
        "substrate_denovo": {"bg": "#ffedd5", "border": "#ea580c", "text": "#9a3412"},
        "substrate_regulated": {"bg": "#e0e7ff", "border": "#4f46e5", "text": "#3730a3"},
        "effector_up": {"bg": "#d1fae5", "border": "#059669", "text": "#065f46"},
        "effector_down": {"bg": "#fce7f3", "border": "#db2777", "text": "#9d174d"},
        "arrow_activate": "#374151",
        "arrow_inhibit": "#dc2626",
    }

    # ── Draw layers from top to bottom ──
    layer_y_positions = []
    current_y = fig_height - 1.2

    def _draw_node(x, y, width, height, label, sublabel, colors):
        """Draw a rounded box node."""
        box = FancyBboxPatch(
            (x - width / 2, y - height / 2), width, height,
            boxstyle="round,pad=0.15",
            facecolor=colors["bg"],
            edgecolor=colors["border"],
            linewidth=1.5,
        )
        ax.add_patch(box)
        ax.text(x, y + 0.05, label, fontsize=8, fontweight="bold",
                color=colors["text"], ha="center", va="center")
        if sublabel:
            ax.text(x, y - 0.25, sublabel, fontsize=6, color="#6b7280",
                    ha="center", va="center")
        return (x, y)

    def _draw_arrow(start_xy, end_xy, style="activate"):
        """Draw a context connector or an explicit arrow when evidence permits."""
        if context_only:
            ax.plot([start_xy[0], end_xy[0]], [start_xy[1], end_xy[1]],
                    color="#64748b", lw=1.1, linestyle=(0, (3, 2)), zorder=1)
            return
        color = COLORS["arrow_activate"] if style == "activate" else COLORS["arrow_inhibit"]
        linestyle = "-" if style == "activate" else "--"
        ax.annotate(
            "", xy=end_xy, xytext=start_xy,
            arrowprops=dict(
                arrowstyle="-|>",
                color=color,
                lw=1.2,
                linestyle=linestyle,
                connectionstyle="arc3,rad=0",
            ),
        )

    # ── Layer 0: Stimulus (if available) ──
    stimulus_positions = []
    if treatment_name:
        layer_label_y = current_y + 0.3
        ax.text(0.3, layer_label_y, "Stimulus", fontsize=7, color="#6b7280",
                fontweight="bold", ha="left", va="center", style="italic")
        pos = _draw_node(fig_width / 2, current_y, 3.0, 0.7, treatment_name, "", COLORS["stimulus"])
        stimulus_positions.append(pos)
        layer_y_positions.append(current_y)
        current_y -= 2.0

    # ── Layer 1: Receptors ──
    receptor_positions = []
    layer_label_y = current_y + 0.3
    ax.text(0.3, layer_label_y, "Receptors", fontsize=7, color="#6b7280",
            fontweight="bold", ha="left", va="center", style="italic")
    if receptors:
        spacing = min(2.5, (fig_width - 2) / max(len(receptors), 1))
        start_x = (fig_width - spacing * (len(receptors) - 1)) / 2
        for i, rec in enumerate(receptors):
            x = start_x + i * spacing
            name = rec.get("name", "Unknown")
            if len(name) > 12:
                name = name[:10] + "…"
            conf = rec.get("confidence_score", 0)
            sublabel = f"{rec.get('receptor_class', '')}" if rec.get("receptor_class") else ""
            pos = _draw_node(x, current_y, 2.2, 0.7, name, sublabel, COLORS["receptor"])
            receptor_positions.append(pos)
    layer_y_positions.append(current_y)
    current_y -= 2.0

    # Arrows: Stimulus → Receptors
    if stimulus_positions and receptor_positions:
        for rp in receptor_positions:
            _draw_arrow(
                (stimulus_positions[0][0], stimulus_positions[0][1] - 0.35),
                (rp[0], rp[1] + 0.35),
                "activate"
            )

    # ── Layer 2: Kinases ──
    kinase_positions = []
    layer_label_y = current_y + 0.3
    ax.text(0.3, layer_label_y, f"{entity_label}s", fontsize=7, color="#6b7280",
            fontweight="bold", ha="left", va="center", style="italic")
    if all_kinases:
        spacing = min(2.2, (fig_width - 2) / max(len(all_kinases), 1))
        start_x = (fig_width - spacing * (len(all_kinases) - 1)) / 2
        for i, k in enumerate(all_kinases):
            x = start_x + i * spacing
            direction = kinase_direction.get(k.upper(), "mixed")
            color_key = f"kinase_{direction}"
            name = k if len(k) <= 10 else k[:8] + "…"
            direction_symbol = "↑" if direction == "up" else ("↓" if direction == "down" else "")
            pos = _draw_node(x, current_y, 1.8, 0.6, f"{name}{direction_symbol}", "", COLORS[color_key])
            kinase_positions.append((pos, direction))
    layer_y_positions.append(current_y)
    current_y -= 2.0

    # Arrows: Receptors → Kinases (connect based on via_kinases)
    if receptor_positions and kinase_positions:
        for rec_idx, rec in enumerate(receptors):
            if rec_idx >= len(receptor_positions):
                break
            for k_name in rec.get("via_kinases", []):
                # Find kinase position
                for k_idx, k in enumerate(all_kinases):
                    if k.upper() == k_name.upper() and k_idx < len(kinase_positions):
                        _draw_arrow(
                            (receptor_positions[rec_idx][0], receptor_positions[rec_idx][1] - 0.35),
                            (kinase_positions[k_idx][0][0], kinase_positions[k_idx][0][1] + 0.3),
                            "activate"
                        )
                        break

    # ── Layer 3: Substrates ──
    substrate_positions = []
    layer_label_y = current_y + 0.3
    ax.text(0.3, layer_label_y, "PTM Substrates", fontsize=7, color="#6b7280",
            fontweight="bold", ha="left", va="center", style="italic")
    if substrate_list:
        spacing = min(2.0, (fig_width - 2) / max(len(substrate_list), 1))
        start_x = (fig_width - spacing * (len(substrate_list) - 1)) / 2
        for i, sub in enumerate(substrate_list):
            x = start_x + i * spacing
            act = sub["activity"]
            color_key = f"substrate_{act}" if f"substrate_{act}" in COLORS else "substrate_regulated"
            name = f"{sub['gene']}"
            sublabel = sub["position"]
            pos = _draw_node(x, current_y, 1.8, 0.6, name, sublabel, COLORS[color_key])
            substrate_positions.append((pos, sub))
    layer_y_positions.append(current_y)
    current_y -= 2.0

    # Arrows: Kinases → Substrates (connect based on kinase_to_ptms)
    if kinase_positions and substrate_positions:
        for k_idx, k in enumerate(all_kinases):
            if k_idx >= len(kinase_positions):
                break
            for s_idx, (s_pos, sub) in enumerate(substrate_positions):
                if sub.get("kinase", "").upper() == k.upper():
                    _draw_arrow(
                        (kinase_positions[k_idx][0][0], kinase_positions[k_idx][0][1] - 0.3),
                        (s_pos[0], s_pos[1] + 0.3),
                        "activate"
                    )

    # ── Layer 4: Effectors (if available) ──
    effector_positions = []
    if has_effectors:
        layer_label_y = current_y + 0.3
        ax.text(0.3, layer_label_y, "Non-PTM Effectors", fontsize=7, color="#6b7280",
                fontweight="bold", ha="left", va="center", style="italic")
        spacing = min(2.2, (fig_width - 2) / max(len(eff_list), 1))
        start_x = (fig_width - spacing * (len(eff_list) - 1)) / 2
        for i, eff in enumerate(eff_list):
            x = start_x + i * spacing
            fc = eff.get("peak_fc", eff.get("max_abs_fc", 0))
            color_key = "effector_up" if fc > 0 else "effector_down"
            name = eff.get("gene", "Unknown")
            if len(name) > 10:
                name = name[:8] + "…"
            direction_symbol = "▲" if fc > 0 else "▼"
            pos = _draw_node(x, current_y, 1.8, 0.6, f"{name}{direction_symbol}", f"FC:{fc:+.1f}", COLORS[color_key])
            effector_positions.append(pos)
        layer_y_positions.append(current_y)

        # Arrows: Substrates → Effectors (simplified: connect nearby)
        if substrate_positions and effector_positions:
            # Connect effectors to their connected substrates
            for eff_idx, eff in enumerate(eff_list):
                if eff_idx >= len(effector_positions):
                    break
                for conn_sub in eff.get("connected_substrates", [])[:2]:
                    conn_gene = conn_sub.get("gene", "").upper()
                    for s_idx, (s_pos, sub) in enumerate(substrate_positions):
                        if sub["gene"].upper() == conn_gene:
                            _draw_arrow(
                                (s_pos[0], s_pos[1] - 0.3),
                                (effector_positions[eff_idx][0], effector_positions[eff_idx][1] + 0.3),
                                "activate"
                            )
                            break

    # ── Title ──
    ax.text(
        fig_width / 2, fig_height - 0.3,
        "Contextual Signaling Map" if context_only else "Inferred Signaling Pathway",
        fontsize=12, fontweight="bold", color="#1f2937",
        ha="center", va="top",
    )

    # ── Legend ──
    legend_y = 0.6
    legend_items = [
        (("Context association (dashed)" if context_only else "Activation (→)"), COLORS["arrow_activate"], "--" if context_only else "-"),
        ("De novo substrate", COLORS["substrate_denovo"]["border"], "-"),
        ("Regulated substrate", COLORS["substrate_regulated"]["border"], "-"),
    ]
    if not context_only:
        legend_items.insert(1, ("Inhibition (⊣)", COLORS["arrow_inhibit"], "--"))
    if has_effectors:
        legend_items.append(("Effector ▲ up / ▼ down", COLORS["effector_up"]["border"], "-"))

    for i, (label, color, ls) in enumerate(legend_items):
        x_pos = 0.5 + i * (fig_width / len(legend_items))
        ax.plot([x_pos, x_pos + 0.4], [legend_y, legend_y], color=color,
                linewidth=2, linestyle=ls)
        ax.text(x_pos + 0.5, legend_y, label, fontsize=6.5, color="#4b5563",
                ha="left", va="center")
    if context_only:
        ax.text(
            fig_width / 2, 0.25,
            "Connectors show shared pathway/literature context, not direct regulation, direction, or causality.",
            fontsize=6.2, color="#64748b", ha="center", va="center",
        )

    # ── Save ──
    output_path = Path(output_dir) / "pathway_diagram.png"
    fig.tight_layout(pad=0.5)
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info(
        f"[PATHWAY-DIAGRAM] Generated pathway diagram: {output_path} "
        f"({len(receptors)} receptors, {len(all_kinases)} kinases, "
        f"{len(substrate_list)} substrates, {len(eff_list)} effectors)"
    )
    return str(output_path)
