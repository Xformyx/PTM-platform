"""
Cross-Talk Network Figure Generator
====================================
Generates publication-quality network figures for PTM cross-talk analysis.

Figure A: Dual-PTM Protein Interaction Network
Figure B: Temporal Cross-Talk Regulation Heatmap
Figure C: PTM Cross-Talk Regulatory Circuit

All figures are saved as high-resolution PNG (300 DPI) suitable for journal submission.

Ported from ptm-chromadb-web/python_backend/crosstalk_figures.py (v83/v88/v93).
"""

import os
import logging
import math
import base64
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# Lazy imports for matplotlib/networkx (may not be installed)
# ============================================================================

def _import_matplotlib():
    """Lazy import matplotlib with Agg backend for headless rendering."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.colors as mcolors
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
    from matplotlib.collections import LineCollection
    return plt, mpatches, mcolors, FancyArrowPatch, FancyBboxPatch, LineCollection

def _import_networkx():
    """Lazy import networkx."""
    import networkx as nx
    return nx

def _import_numpy():
    """Lazy import numpy."""
    import numpy as np
    return np


def convert_image_to_base64(image_path: str) -> str:
    """Convert image file to Base64 data URI."""
    try:
        p = Path(image_path)
        if not p.exists():
            return ""
        with open(p, "rb") as f:
            data = f.read()
        encoded = base64.b64encode(data).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


# ============================================================================
# Color Palette (Publication-quality)
# ============================================================================

# Nature-style color palette
COLORS = {
    'concordant': '#2E8B57',       # Sea green
    'discordant': '#DC143C',       # Crimson
    'mixed': '#708090',            # Slate gray
    'phosphorylation': '#1E90FF',  # Dodger blue
    'ubiquitylation': '#FF8C00',   # Dark orange
    'kinase': '#9370DB',           # Medium purple
    'e3_ligase': '#20B2AA',        # Light sea green
    'shared_protein': '#FFD700',   # Gold
    'primary_only': '#87CEEB',     # Sky blue
    'secondary_only': '#FFA07A',   # Light salmon
    'edge_strong': '#333333',      # Dark gray
    'edge_weak': '#CCCCCC',        # Light gray
    'background': '#FAFAFA',       # Off-white
    'text': '#1A1A1A',             # Near-black
    'grid': '#E8E8E8',             # Light grid
    'up': '#D32F2F',               # Red (upregulated)
    'down': '#1565C0',             # Blue (downregulated)
    'neutral': '#BDBDBD',          # Gray (no change)
}


# ============================================================================
# Figure A: Dual-PTM Protein Interaction Network
# ============================================================================

def generate_dual_ptm_network(
    crosstalk_data: Dict[str, Any],
    output_dir: str,
    primary_ptm_type: str = "phosphorylation",
    secondary_ptm_type: str = "ubiquitylation",
) -> Optional[str]:
    """
    Generate a publication-quality Dual-PTM Protein Interaction Network.

    Nodes: Dual-PTM proteins (both Phos and Ub modifications)
    Node color: Pattern (concordant=green, discordant=red, mixed=gray)
    Node size: proportional to concordant_ratio
    Node border: dual-color ring (blue=Phos, orange=Ub)
    Edges: STRING-DB interactions between dual-PTM proteins

    Returns: path to saved PNG file, or None on failure.
    """
    try:
        plt, mpatches, mcolors, FancyArrowPatch, FancyBboxPatch, LineCollection = _import_matplotlib()
        nx = _import_networkx()
        np = _import_numpy()
    except ImportError as e:
        logger.warning(f"Cannot generate Figure A: missing dependency ({e})")
        return None

    dual_ptm_proteins = crosstalk_data.get('dual_ptm_proteins', [])
    if not dual_ptm_proteins:
        logger.warning("No dual-PTM proteins found, skipping Figure A")
        return None

    # v83: Limit to top N proteins by significance_score for readability
    MAX_NODES = 50
    total_proteins = len(dual_ptm_proteins)
    if total_proteins > MAX_NODES:
        sorted_proteins = sorted(
            dual_ptm_proteins,
            key=lambda p: (p.get('significance_score', 0), abs(p.get('concordant_ratio', 0.5) - 0.5)),
            reverse=True
        )
        dual_ptm_proteins = sorted_proteins[:MAX_NODES]
        logger.info(f"Figure A: Showing top {MAX_NODES} of {total_proteins} proteins (by significance_score)")

    logger.info(f"Generating Figure A: Dual-PTM Network ({len(dual_ptm_proteins)} proteins)...")

    # Build graph
    G = nx.Graph()

    for p in dual_ptm_proteins:
        gene = p.get('gene', 'Unknown')
        pattern = p.get('pattern', 'mixed')
        ratio = p.get('concordant_ratio', 0.5)
        primary_sites = p.get('primary_sites', [])
        secondary_sites = p.get('secondary_sites', [])

        G.add_node(gene,
                    pattern=pattern,
                    concordant_ratio=ratio,
                    primary_sites=primary_sites,
                    secondary_sites=secondary_sites)

    # Add edges between proteins that share timepoints or have known interactions
    genes = [p.get('gene', '') for p in dual_ptm_proteins]
    non_ptm_interactors = crosstalk_data.get('non_ptm_interactors', [])

    # Build interaction map from non-PTM interactors
    interactor_to_genes = {}
    for interactor in non_ptm_interactors:
        iname = interactor.get('gene', '')
        connected = interactor.get('connected_dual_ptm_proteins', [])
        if not connected:
            p_int = interactor.get('primary_ptm_interactions', [])
            s_int = interactor.get('secondary_ptm_interactions', [])
            connected = list(set(p_int) | set(s_int))
        interactor_to_genes[iname] = connected

    # Connect dual-PTM proteins that share a non-PTM interactor
    for iname, connected in interactor_to_genes.items():
        connected_in_graph = [g for g in connected if g in G]
        for i in range(len(connected_in_graph)):
            for j in range(i + 1, len(connected_in_graph)):
                if not G.has_edge(connected_in_graph[i], connected_in_graph[j]):
                    G.add_edge(connected_in_graph[i], connected_in_graph[j],
                              via=iname, weight=0.5)

    # Also connect proteins with same pattern that share timepoints
    for i in range(len(dual_ptm_proteins)):
        for j in range(i + 1, len(dual_ptm_proteins)):
            g1 = dual_ptm_proteins[i].get('gene', '')
            g2 = dual_ptm_proteins[j].get('gene', '')
            tp1 = set(dual_ptm_proteins[i].get('shared_timepoints', []))
            tp2 = set(dual_ptm_proteins[j].get('shared_timepoints', []))
            shared = tp1 & tp2
            if len(shared) >= 2 and not G.has_edge(g1, g2):
                G.add_edge(g1, g2, shared_tp=len(shared), weight=0.3)

    # Layout
    if len(G.nodes()) <= 3:
        pos = nx.circular_layout(G, scale=2.0)
    elif len(G.edges()) > 0:
        pos = nx.spring_layout(G, k=2.5/math.sqrt(max(len(G.nodes()), 1)),
                               iterations=100, seed=42)
    else:
        pos = nx.circular_layout(G, scale=2.0)

    # Figure setup - v83: larger figure for better readability
    n_nodes = len(G.nodes())
    fig_width = max(14, min(24, 10 + n_nodes * 0.25))
    fig_height = fig_width * 0.75
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height), dpi=300)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # Draw edges
    for (u, v, data) in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        weight = data.get('weight', 0.3)
        alpha = 0.3 + weight * 0.4
        lw = 0.5 + weight * 1.5
        ax.plot([x0, x1], [y0, y1], '-', color='#999999',
                alpha=alpha, linewidth=lw, zorder=1)

    # Draw nodes
    for node in G.nodes():
        x, y = pos[node]
        data = G.nodes[node]
        pattern = data.get('pattern', 'mixed')
        ratio = data.get('concordant_ratio', 0.5)

        # Node size based on concordant_ratio
        base_size = 800
        node_size = base_size + ratio * 600
        radius = math.sqrt(node_size / math.pi) / 100

        # Inner fill color based on pattern
        fill_color = COLORS.get(pattern, COLORS['mixed'])

        # Draw outer ring (dual-PTM indicator)
        outer_ring = plt.Circle((x, y), radius * 1.25,
                                facecolor='none',
                                edgecolor=COLORS['phosphorylation'],
                                linewidth=2.5, zorder=2)
        ax.add_patch(outer_ring)

        # Second ring for ubiquitylation (dashed)
        outer_ring2 = plt.Circle((x, y), radius * 1.35,
                                 facecolor='none',
                                 edgecolor=COLORS['ubiquitylation'],
                                 linewidth=2.0, linestyle='--', zorder=2)
        ax.add_patch(outer_ring2)

        # Inner filled circle
        inner = plt.Circle((x, y), radius,
                           facecolor=fill_color,
                           edgecolor='white',
                           linewidth=1.5, alpha=0.9, zorder=3)
        ax.add_patch(inner)

        # Gene label - v83: minimum 9pt for readability
        fontsize = max(9, min(12, 14 - n_nodes * 0.08))
        ax.text(x, y, node, ha='center', va='center',
                fontsize=fontsize, fontweight='bold', color='white',
                zorder=4)

        # Site count annotation below - v83: increased from 5pt to 7pt
        p_sites = len(data.get('primary_sites', []))
        s_sites = len(data.get('secondary_sites', []))
        ax.text(x, y - radius * 1.6, f"P:{p_sites} U:{s_sites}",
                ha='center', va='top', fontsize=7, color='#555555', zorder=4)

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor=COLORS['concordant'], edgecolor='white',
                       label=f'Concordant ({sum(1 for n in G.nodes() if G.nodes[n].get("pattern")=="concordant")})'),
        mpatches.Patch(facecolor=COLORS['discordant'], edgecolor='white',
                       label=f'Discordant ({sum(1 for n in G.nodes() if G.nodes[n].get("pattern")=="discordant")})'),
        mpatches.Patch(facecolor=COLORS['mixed'], edgecolor='white',
                       label=f'Mixed ({sum(1 for n in G.nodes() if G.nodes[n].get("pattern")=="mixed")})'),
        plt.Line2D([0], [0], color=COLORS['phosphorylation'], linewidth=2.5,
                   label=f'{primary_ptm_type.capitalize()} (solid ring)'),
        plt.Line2D([0], [0], color=COLORS['ubiquitylation'], linewidth=2.0, linestyle='--',
                   label=f'{secondary_ptm_type.capitalize()} (dashed ring)'),
    ]

    legend = ax.legend(handles=legend_elements, loc='upper left',
                       fontsize=10, framealpha=0.95, edgecolor='#CCCCCC',
                       title='Cross-Talk Pattern', title_fontsize=11,
                       bbox_to_anchor=(0.01, 0.99))
    legend.get_frame().set_linewidth(0.5)

    # Title - v83: show total count if filtered
    title_suffix = f" (top {len(G.nodes())} of {total_proteins})" if total_proteins > MAX_NODES else f" (n={len(G.nodes())})"
    ax.set_title(
        f"Dual-PTM Protein Interaction Network\n"
        f"({primary_ptm_type.capitalize()} \u00d7 {secondary_ptm_type.capitalize()},{title_suffix})",
        fontsize=14, fontweight='bold', pad=15
    )

    ax.set_xlim(ax.get_xlim()[0] - 0.3, ax.get_xlim()[1] + 0.3)
    ax.set_ylim(ax.get_ylim()[0] - 0.3, ax.get_ylim()[1] + 0.3)
    ax.axis('off')

    plt.tight_layout()

    output_path = os.path.join(output_dir, "crosstalk_figure_A_dual_ptm_network.png")
    fig.savefig(output_path, dpi=300, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)

    logger.info(f"Figure A saved: {output_path}")
    return output_path


# ============================================================================
# Figure B: Temporal Cross-Talk Regulation Heatmap
# ============================================================================

def generate_temporal_heatmap(
    crosstalk_data: Dict[str, Any],
    output_dir: str,
    primary_ptm_type: str = "phosphorylation",
    secondary_ptm_type: str = "ubiquitylation",
) -> Optional[str]:
    """
    Generate a publication-quality temporal cross-talk heatmap.

    Rows: Dual-PTM proteins (sorted by pattern then concordant_ratio)
    Columns: Timepoints
    Cells: Split cell showing primary (left) and secondary (right) log2FC
    Color: Red=up, Blue=down, Gray=no data
    Side annotation: concordant_ratio bar + pattern label

    Returns: path to saved PNG file, or None on failure.
    """
    try:
        plt, mpatches, mcolors, _, _, _ = _import_matplotlib()
        np = _import_numpy()
    except ImportError as e:
        logger.warning(f"Cannot generate Figure B: missing dependency ({e})")
        return None

    dual_ptm_proteins = crosstalk_data.get('dual_ptm_proteins', [])
    if not dual_ptm_proteins:
        logger.warning("No dual-PTM proteins found, skipping Figure B")
        return None

    logger.info(f"Generating Figure B: Temporal Heatmap ({len(dual_ptm_proteins)} proteins)...")

    # v88: Filter to concordance ratio >= 50% only
    filtered_proteins = [p for p in dual_ptm_proteins if p.get('concordant_ratio', 0) >= 0.5]
    logger.info(f"Figure B: {len(filtered_proteins)}/{len(dual_ptm_proteins)} proteins with concordance ratio >= 50%")

    if not filtered_proteins:
        logger.warning("No proteins with concordance ratio >= 50%, skipping Figure B")
        return None

    # Sort proteins: concordant first, then mixed, then discordant
    pattern_order = {'concordant': 0, 'mixed': 1, 'discordant': 2}
    sorted_proteins = sorted(filtered_proteins,
                             key=lambda p: (pattern_order.get(p.get('pattern', 'mixed'), 1),
                                           -p.get('concordant_ratio', 0)))

    # Limit to top 40 for readability
    max_proteins = 40
    if len(sorted_proteins) > max_proteins:
        sorted_proteins = sorted_proteins[:max_proteins]

    # Collect timepoints
    all_tps = set()
    for p in sorted_proteins:
        tc = p.get('temporal_comparison', {})
        all_tps.update(tc.keys())

    def _parse_tp(tp_str):
        import re
        nums = re.findall(r'[\d.]+', str(tp_str))
        return float(nums[0]) if nums else 0

    timepoints = sorted(all_tps, key=_parse_tp)

    if not timepoints:
        logger.warning("No timepoints found, skipping Figure B")
        return None

    n_proteins = len(sorted_proteins)
    n_timepoints = len(timepoints)

    # Figure dimensions - v93: increased cell sizes for higher resolution output
    cell_w = 1.8
    cell_h = 0.6
    left_margin = 3.0   # Gene names
    right_margin = 3.5  # Ratio bar + pattern
    top_margin = 2.0    # Timepoint labels
    bottom_margin = 1.5

    fig_w = left_margin + n_timepoints * cell_w + right_margin
    fig_h = top_margin + n_proteins * cell_h + bottom_margin
    fig_w = max(12, min(30, fig_w))
    fig_h = max(6, min(24, fig_h))

    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), dpi=600)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # Color mapping for log2FC
    def fc_to_color(fc, max_fc=3.0):
        if fc is None or fc == 0:
            return COLORS['neutral']
        clamped = max(-max_fc, min(max_fc, fc))
        ratio = clamped / max_fc
        if ratio > 0:
            # Red gradient (upregulated)
            r = 1.0
            g = 1.0 - ratio * 0.7
            b = 1.0 - ratio * 0.7
        else:
            # Blue gradient (downregulated)
            ratio_abs = abs(ratio)
            r = 1.0 - ratio_abs * 0.7
            g = 1.0 - ratio_abs * 0.5
            b = 1.0
        return (r, g, b)

    # Draw heatmap cells
    for row_idx, protein in enumerate(sorted_proteins):
        gene = protein.get('gene', 'Unknown')
        pattern = protein.get('pattern', 'mixed')
        ratio = protein.get('concordant_ratio', 0.5)
        tc = protein.get('temporal_comparison', {})

        y = n_proteins - 1 - row_idx  # top to bottom

        for col_idx, tp in enumerate(timepoints):
            tp_data = tc.get(tp, {})
            p_fc = tp_data.get('primary_ptm_log2fc', 0) if tp_data else 0
            s_fc = tp_data.get('secondary_ptm_log2fc', 0) if tp_data else 0
            is_concordant = tp_data.get('concordant', None) if tp_data else None

            x = col_idx

            # Left half: primary PTM
            rect_left = plt.Rectangle((x, y), 0.5, 1,
                                       facecolor=fc_to_color(p_fc),
                                       edgecolor='white', linewidth=0.5)
            ax.add_patch(rect_left)

            # Right half: secondary PTM
            rect_right = plt.Rectangle((x + 0.5, y), 0.5, 1,
                                        facecolor=fc_to_color(s_fc),
                                        edgecolor='white', linewidth=0.5)
            ax.add_patch(rect_right)

            # v88: Vertical divider line between P and U halves
            ax.plot([x + 0.5, x + 0.5], [y, y + 1],
                    color='#999999', linewidth=0.3, zorder=4)

            # Concordance indicator (small dot)
            if is_concordant is not None:
                dot_color = COLORS['concordant'] if is_concordant else COLORS['discordant']
                ax.plot(x + 0.5, y + 0.5, 'o', color=dot_color,
                       markersize=2, zorder=5)

            # Cell border
            rect_border = plt.Rectangle((x, y), 1, 1,
                                         facecolor='none',
                                         edgecolor='#E0E0E0', linewidth=0.3)
            ax.add_patch(rect_border)

        # Gene label (left)
        ax.text(-0.3, y + 0.5, gene, ha='right', va='center',
                fontsize=6, fontweight='bold', color=COLORS['text'])

        # Pattern color bar (right side)
        pattern_color = COLORS.get(pattern, COLORS['mixed'])
        bar_x = n_timepoints + 0.2

        # Concordant ratio bar
        bar_width = ratio * 1.5
        rect_bar = plt.Rectangle((bar_x, y + 0.15), bar_width, 0.7,
                                  facecolor=pattern_color, alpha=0.7,
                                  edgecolor='none')
        ax.add_patch(rect_bar)

        # Ratio text
        ax.text(bar_x + 1.7, y + 0.5, f"{ratio:.0%}",
                ha='left', va='center', fontsize=5, color='#555555')

    # Group separators
    current_pattern = None
    for row_idx, protein in enumerate(sorted_proteins):
        pattern = protein.get('pattern', 'mixed')
        if current_pattern is not None and pattern != current_pattern:
            y = n_proteins - row_idx
            ax.axhline(y=y, color='#333333', linewidth=1.0, linestyle='-', zorder=6)
        current_pattern = pattern

    # Timepoint labels (top)
    for col_idx, tp in enumerate(timepoints):
        ax.text(col_idx + 0.5, n_proteins + 0.3, tp,
                ha='center', va='bottom', fontsize=7, fontweight='bold',
                rotation=45, color=COLORS['text'])

    # v88: Enhanced P/U column sub-headers with colored background boxes
    p_label = primary_ptm_type[0].upper()   # 'P' for phosphorylation
    u_label = secondary_ptm_type[0].upper() # 'U' for ubiquitylation
    for col_idx in range(n_timepoints):
        # Left half label with colored background
        bg_left = plt.Rectangle((col_idx + 0.05, n_proteins + 0.05), 0.4, 0.3,
                                 facecolor=COLORS['phosphorylation'], alpha=0.15,
                                 edgecolor=COLORS['phosphorylation'], linewidth=0.5)
        ax.add_patch(bg_left)
        ax.text(col_idx + 0.25, n_proteins + 0.2, p_label, ha='center', va='center',
                fontsize=6, color=COLORS['phosphorylation'], fontweight='bold')
        # Right half label with colored background
        bg_right = plt.Rectangle((col_idx + 0.55, n_proteins + 0.05), 0.4, 0.3,
                                  facecolor=COLORS['ubiquitylation'], alpha=0.15,
                                  edgecolor=COLORS['ubiquitylation'], linewidth=0.5)
        ax.add_patch(bg_right)
        ax.text(col_idx + 0.75, n_proteins + 0.2, u_label, ha='center', va='center',
                fontsize=6, color=COLORS['ubiquitylation'], fontweight='bold')

    # Right axis label
    ax.text(n_timepoints + 0.9, n_proteins + 0.3, 'Concordance\nRatio',
            ha='center', va='bottom', fontsize=6, fontweight='bold', color=COLORS['text'])

    # Color bar legend
    cbar_y = -1.8
    cbar_x = 0
    ax.text(cbar_x, cbar_y + 0.6, 'Log2FC:', ha='left', va='center',
            fontsize=6, fontweight='bold', color=COLORS['text'])

    gradient_steps = 20
    for i in range(gradient_steps):
        fc_val = -3.0 + (6.0 * i / (gradient_steps - 1))
        color = fc_to_color(fc_val)
        rect = plt.Rectangle((cbar_x + 1.2 + i * 0.15, cbar_y + 0.35), 0.15, 0.5,
                              facecolor=color, edgecolor='none')
        ax.add_patch(rect)

    ax.text(cbar_x + 1.2, cbar_y + 0.2, '\u22123', ha='center', va='top', fontsize=5)
    ax.text(cbar_x + 1.2 + gradient_steps * 0.15 / 2, cbar_y + 0.2, '0',
            ha='center', va='top', fontsize=5)
    ax.text(cbar_x + 1.2 + gradient_steps * 0.15, cbar_y + 0.2, '+3',
            ha='center', va='top', fontsize=5)

    # Pattern legend
    legend_x = cbar_x + 5.5
    for i, (pname, pcolor) in enumerate([('Concordant', COLORS['concordant']),
                                          ('Mixed', COLORS['mixed']),
                                          ('Discordant', COLORS['discordant'])]):
        rect = plt.Rectangle((legend_x + i * 2.0, cbar_y + 0.35), 0.3, 0.5,
                              facecolor=pcolor, edgecolor='none')
        ax.add_patch(rect)
        ax.text(legend_x + i * 2.0 + 0.4, cbar_y + 0.6, pname,
                ha='left', va='center', fontsize=5, color=COLORS['text'])

    # v88: Enhanced split cell legend with full PTM type names
    split_x = legend_x + 6.5
    ax.text(split_x, cbar_y + 0.6, 'Each Cell: ', ha='left', va='center',
            fontsize=5, fontweight='bold')
    rect_demo_l = plt.Rectangle((split_x + 1.2, cbar_y + 0.35), 0.4, 0.5,
                                 facecolor=COLORS['phosphorylation'], alpha=0.25,
                                 edgecolor=COLORS['phosphorylation'], linewidth=0.8)
    ax.add_patch(rect_demo_l)
    rect_demo_r = plt.Rectangle((split_x + 1.6, cbar_y + 0.35), 0.4, 0.5,
                                 facecolor=COLORS['ubiquitylation'], alpha=0.25,
                                 edgecolor=COLORS['ubiquitylation'], linewidth=0.8)
    ax.add_patch(rect_demo_r)
    ax.text(split_x + 1.4, cbar_y + 0.6, p_label, ha='center', va='center', fontsize=5,
            color=COLORS['phosphorylation'], fontweight='bold')
    ax.text(split_x + 1.8, cbar_y + 0.6, u_label, ha='center', va='center', fontsize=5,
            color=COLORS['ubiquitylation'], fontweight='bold')
    # Full names below the demo cell
    ax.text(split_x + 1.4, cbar_y + 0.15, primary_ptm_type.capitalize(), ha='center', va='top',
            fontsize=4, color=COLORS['phosphorylation'])
    ax.text(split_x + 1.8, cbar_y + 0.15, secondary_ptm_type.capitalize(), ha='center', va='top',
            fontsize=4, color=COLORS['ubiquitylation'])

    # v88: Title updated to reflect concordance filter
    ax.set_title(
        f"Temporal Cross-Talk Regulation Heatmap\n"
        f"({primary_ptm_type.capitalize()} \u00d7 {secondary_ptm_type.capitalize()}, "
        f"n={n_proteins} dual-PTM proteins with concordance \u2265 50%, {n_timepoints} timepoints)",
        fontsize=11, fontweight='bold', pad=30
    )

    ax.set_xlim(-0.5, n_timepoints + 2.5)
    ax.set_ylim(cbar_y - 0.5, n_proteins + 1.5)
    ax.axis('off')

    plt.tight_layout()

    output_path = os.path.join(output_dir, "crosstalk_figure_B_temporal_heatmap.png")
    fig.savefig(output_path, dpi=600, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)

    logger.info(f"Figure B saved: {output_path}")
    return output_path


# ============================================================================
# Figure C: PTM Cross-Talk Regulatory Circuit
# ============================================================================

def generate_regulatory_circuit(
    crosstalk_data: Dict[str, Any],
    output_dir: str,
    primary_ptm_type: str = "phosphorylation",
    secondary_ptm_type: str = "ubiquitylation",
) -> Optional[str]:
    """
    Generate a publication-quality PTM Cross-Talk Regulatory Circuit.

    Shows directed relationships:
    Kinase -> Phos substrate -> E3 ligase -> Ub substrate

    Layout: Layered/hierarchical with clear flow direction
    Node shapes: Rectangles for enzymes, circles for substrates
    Edge styles: Solid for activation, dashed for inhibition

    Returns: path to saved PNG file, or None on failure.
    """
    try:
        plt, mpatches, mcolors, FancyArrowPatch, FancyBboxPatch, _ = _import_matplotlib()
        nx = _import_networkx()
        np = _import_numpy()
    except ImportError as e:
        logger.warning(f"Cannot generate Figure C: missing dependency ({e})")
        return None

    dual_ptm_proteins = crosstalk_data.get('dual_ptm_proteins', [])
    non_ptm_interactors = crosstalk_data.get('non_ptm_interactors', [])

    if not dual_ptm_proteins:
        logger.warning("No dual-PTM proteins found, skipping Figure C")
        return None

    logger.info("Generating Figure C: Regulatory Circuit...")

    # Classify non-PTM interactors
    kinases = []
    e3_ligases = []
    other_regulators = []

    for interactor in non_ptm_interactors:
        role = interactor.get('role', 'unknown')
        gene = interactor.get('gene', '')
        if not gene:
            continue

        role_lower = role.lower() if role else ''
        gene_upper = gene.upper()

        is_kinase = ('kinase' in role_lower or
                     gene_upper.endswith('K') and len(gene_upper) <= 6 or
                     'phosphorylat' in role_lower)
        is_e3 = ('ligase' in role_lower or 'ubiquitin' in role_lower or
                 'e3' in role_lower or 'rnf' in gene_upper.lower() or
                 'trim' in gene_upper.lower() or 'mdm' in gene_upper.lower())

        if is_kinase:
            kinases.append(interactor)
        elif is_e3:
            e3_ligases.append(interactor)
        else:
            other_regulators.append(interactor)

    # Build directed graph
    G = nx.DiGraph()

    # Add kinases (top layer)
    for k in kinases[:8]:
        gene = k.get('gene', '')
        G.add_node(gene, layer=0, node_type='kinase',
                   color=COLORS['kinase'])

    # Add dual-PTM proteins (middle layers)
    concordant_proteins = [p for p in dual_ptm_proteins if p.get('pattern') == 'concordant']
    discordant_proteins = [p for p in dual_ptm_proteins if p.get('pattern') == 'discordant']
    mixed_proteins = [p for p in dual_ptm_proteins if p.get('pattern') == 'mixed']

    max_per_group = 8
    selected_proteins = (concordant_proteins[:max_per_group] +
                        discordant_proteins[:max_per_group] +
                        mixed_proteins[:max_per_group])

    for p in selected_proteins:
        gene = p.get('gene', '')
        pattern = p.get('pattern', 'mixed')
        G.add_node(gene, layer=1, node_type='dual_ptm',
                   pattern=pattern, color=COLORS.get(pattern, COLORS['mixed']))

    # Add E3 ligases (bottom layer)
    for e in e3_ligases[:8]:
        gene = e.get('gene', '')
        G.add_node(gene, layer=2, node_type='e3_ligase',
                   color=COLORS['e3_ligase'])

    # Add edges: kinase -> dual-PTM proteins
    for k in kinases[:8]:
        k_gene = k.get('gene', '')
        connected = k.get('connected_dual_ptm_proteins', [])
        if not connected:
            p_int = k.get('primary_ptm_interactions', [])
            s_int = k.get('secondary_ptm_interactions', [])
            connected = list(set(p_int) | set(s_int))

        for target in connected:
            if target in G:
                G.add_edge(k_gene, target, edge_type='phosphorylation')

    # Add edges: E3 ligases -> dual-PTM proteins
    for e in e3_ligases[:8]:
        e_gene = e.get('gene', '')
        connected = e.get('connected_dual_ptm_proteins', [])
        if not connected:
            p_int = e.get('primary_ptm_interactions', [])
            s_int = e.get('secondary_ptm_interactions', [])
            connected = list(set(p_int) | set(s_int))

        for target in connected:
            if target in G:
                G.add_edge(e_gene, target, edge_type='ubiquitylation')

    # If no edges exist, create some based on proximity
    if len(G.edges()) == 0:
        kinase_nodes = [n for n in G if G.nodes[n].get('node_type') == 'kinase']
        dual_nodes = [n for n in G if G.nodes[n].get('node_type') == 'dual_ptm']
        e3_nodes = [n for n in G if G.nodes[n].get('node_type') == 'e3_ligase']

        for k in kinase_nodes[:3]:
            for d in dual_nodes[:3]:
                G.add_edge(k, d, edge_type='phosphorylation')

        for e in e3_nodes[:3]:
            for d in dual_nodes[:3]:
                G.add_edge(e, d, edge_type='ubiquitylation')

    if len(G.nodes()) == 0:
        logger.warning("No nodes for regulatory circuit, skipping Figure C")
        return None

    # Manual layered layout
    layers = {0: [], 1: [], 2: []}
    for node in G.nodes():
        layer = G.nodes[node].get('layer', 1)
        layers[layer].append(node)

    pos = {}
    y_positions = {0: 3.5, 1: 1.5, 2: -0.5}

    for layer_idx, nodes in layers.items():
        if not nodes:
            continue
        y = y_positions[layer_idx]
        n = len(nodes)
        x_spacing = 2.5
        x_start = -(n - 1) / 2.0 * x_spacing
        for i, node in enumerate(nodes):
            pos[node] = (x_start + i * x_spacing, y)

    # Figure - v83: larger figure for better readability
    fig_w = max(14, min(24, 8 + max(len(l) for l in layers.values()) * 2.5))
    fig_h = max(10, fig_w * 0.6)
    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), dpi=300)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # Draw edges with arrows
    for (u, v, data) in G.edges(data=True):
        if u not in pos or v not in pos:
            continue
        x0, y0 = pos[u]
        x1, y1 = pos[v]

        edge_type = data.get('edge_type', 'phosphorylation')
        if edge_type == 'phosphorylation':
            color = COLORS['phosphorylation']
            style = '-'
        else:
            color = COLORS['ubiquitylation']
            style = '--'

        arrow = FancyArrowPatch(
            (x0, y0), (x1, y1),
            arrowstyle='-|>',
            color=color,
            linewidth=1.5,
            linestyle=style,
            mutation_scale=15,
            shrinkA=20, shrinkB=20,
            zorder=1,
            alpha=0.7
        )
        ax.add_patch(arrow)

    # Draw nodes
    for node in G.nodes():
        if node not in pos:
            continue
        x, y = pos[node]
        data = G.nodes[node]
        node_type = data.get('node_type', 'dual_ptm')
        color = data.get('color', COLORS['mixed'])

        if node_type == 'kinase':
            bbox = FancyBboxPatch(
                (x - 0.85, y - 0.35), 1.7, 0.7,
                boxstyle="round,pad=0.15",
                facecolor=color, edgecolor='#333333',
                linewidth=2.0, alpha=0.9, zorder=3
            )
            ax.add_patch(bbox)
            ax.text(x, y, node, ha='center', va='center',
                    fontsize=10, fontweight='bold', color='white', zorder=4)

        elif node_type == 'e3_ligase':
            bbox = FancyBboxPatch(
                (x - 0.85, y - 0.35), 1.7, 0.7,
                boxstyle="round,pad=0.15",
                facecolor=color, edgecolor='#333333',
                linewidth=2.0, alpha=0.9, zorder=3
            )
            ax.add_patch(bbox)
            ax.text(x, y, node, ha='center', va='center',
                    fontsize=10, fontweight='bold', color='white', zorder=4)

        else:
            circle = plt.Circle((x, y), 0.50,
                               facecolor=color, edgecolor='#333333',
                               linewidth=2.0, alpha=0.9, zorder=3)
            ax.add_patch(circle)

            ring_p = plt.Circle((x, y), 0.58,
                               facecolor='none', edgecolor=COLORS['phosphorylation'],
                               linewidth=2.0, zorder=2)
            ax.add_patch(ring_p)
            ring_u = plt.Circle((x, y), 0.65,
                               facecolor='none', edgecolor=COLORS['ubiquitylation'],
                               linewidth=1.5, linestyle='--', zorder=2)
            ax.add_patch(ring_u)

            ax.text(x, y, node, ha='center', va='center',
                    fontsize=10, fontweight='bold', color='white', zorder=4)

    # Layer labels
    layer_labels = {
        0: f'Kinases\n({primary_ptm_type.capitalize()} regulators)',
        1: f'Dual-PTM Substrates\n({primary_ptm_type.capitalize()} + {secondary_ptm_type.capitalize()})',
        2: f'E3 Ligases\n({secondary_ptm_type.capitalize()} regulators)',
    }

    x_min = min(p[0] for p in pos.values()) if pos else -3
    for layer_idx, label in layer_labels.items():
        if layers[layer_idx]:
            y = y_positions[layer_idx]
            ax.text(x_min - 2.5, y, label, ha='center', va='center',
                    fontsize=10, fontweight='bold', color='#555555',
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='#F5F5F5',
                             edgecolor='#CCCCCC', linewidth=0.8))

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor=COLORS['kinase'], edgecolor='#333',
                       label=f'Kinase (n={len(kinases[:8])})'),
        mpatches.Patch(facecolor=COLORS['concordant'], edgecolor='#333',
                       label='Concordant substrate'),
        mpatches.Patch(facecolor=COLORS['discordant'], edgecolor='#333',
                       label='Discordant substrate'),
        mpatches.Patch(facecolor=COLORS['mixed'], edgecolor='#333',
                       label='Mixed substrate'),
        mpatches.Patch(facecolor=COLORS['e3_ligase'], edgecolor='#333',
                       label=f'E3 Ligase (n={len(e3_ligases[:8])})'),
        plt.Line2D([0], [0], color=COLORS['phosphorylation'], linewidth=2,
                   label=f'{primary_ptm_type.capitalize()} regulation'),
        plt.Line2D([0], [0], color=COLORS['ubiquitylation'], linewidth=2, linestyle='--',
                   label=f'{secondary_ptm_type.capitalize()} regulation'),
    ]

    legend = ax.legend(handles=legend_elements, loc='lower right',
                       fontsize=10, framealpha=0.95, edgecolor='#CCCCCC',
                       title='Node / Edge Types', title_fontsize=11)
    legend.get_frame().set_linewidth(0.8)

    ax.set_title(
        f"PTM Cross-Talk Regulatory Circuit\n"
        f"({primary_ptm_type.capitalize()} \u00d7 {secondary_ptm_type.capitalize()})",
        fontsize=14, fontweight='bold', pad=15
    )

    if pos:
        all_x = [p[0] for p in pos.values()]
        all_y = [p[1] for p in pos.values()]
        ax.set_xlim(min(all_x) - 3.5, max(all_x) + 2.5)
        ax.set_ylim(min(all_y) - 1.5, max(all_y) + 1.5)

    ax.axis('off')
    plt.tight_layout()

    output_path = os.path.join(output_dir, "crosstalk_figure_C_regulatory_circuit.png")
    fig.savefig(output_path, dpi=300, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)

    logger.info(f"Figure C saved: {output_path}")
    return output_path


# ============================================================================
# Main: Generate All Cross-Talk Figures
# ============================================================================

def generate_all_crosstalk_figures(
    crosstalk_data: Dict[str, Any],
    output_dir: str,
    primary_ptm_type: str = "phosphorylation",
    secondary_ptm_type: str = "ubiquitylation",
) -> Dict[str, str]:
    """
    Generate all cross-talk figures and return paths.

    Returns dict: { 'figure_a': path, 'figure_b': path, 'figure_c': path }
    """
    logger.info("=== Generating Cross-Talk Publication Figures ===")

    os.makedirs(output_dir, exist_ok=True)

    figures = {}

    # v93: Figure A (Dual-PTM Network) and Figure C (Regulatory Circuit) are now
    # replaced by structured tables (Table 2A, Table 2C) for better readability.
    # Only Figure B (Temporal Heatmap) is generated as an image.
    logger.info("Figure A/C replaced by tables (Table 2A/2C) for better readability")

    # Figure B: Temporal Heatmap (the only image-based figure)
    path_b = generate_temporal_heatmap(
        crosstalk_data, output_dir, primary_ptm_type, secondary_ptm_type)
    if path_b:
        figures['figure_b'] = path_b

    logger.info(f"=== Cross-Talk Figures Complete: {len(figures)} image(s) + 2 tables ===")
    return figures


def _generate_table_2a(dual_ptm_proteins, ptype, stype, n_concordant, n_discordant, n_mixed):
    """
    v93: Generate Table 2A - Dual-PTM Protein Summary Table
    Replaces the low-readability network diagram with a structured table.
    """
    n_total = len(dual_ptm_proteins)
    section = f"### Table 2A. Dual-PTM Protein Summary ({ptype} \u00d7 {stype})\n\n"
    section += f"A total of **{n_total} dual-PTM proteins** were identified harboring both "
    section += f"{ptype.lower()} and {stype.lower()} modifications "
    section += f"(concordant: {n_concordant}, discordant: {n_discordant}, mixed: {n_mixed}).\n\n"

    # Sort: concordant first (by ratio desc), then mixed, then discordant
    pattern_order = {'concordant': 0, 'mixed': 1, 'discordant': 2}
    sorted_proteins = sorted(
        dual_ptm_proteins,
        key=lambda p: (pattern_order.get(p.get('pattern', 'mixed'), 1),
                       -p.get('concordant_ratio', 0.5))
    )

    # Limit to top 50 for readability
    display_proteins = sorted_proteins[:50]
    if len(sorted_proteins) > 50:
        section += f"*Showing top 50 of {n_total} proteins by concordance pattern and ratio.*\n\n"

    section += f"| Gene | Pattern | Concordance Ratio | {ptype} Sites | {stype} Sites | Shared Timepoints |\n"
    section += f"|------|---------|:-----------------:|:-------------:|:-------------:|:-----------------:|\n"

    for p in display_proteins:
        gene = p.get('gene', 'Unknown')
        pattern = p.get('pattern', 'mixed').capitalize()
        ratio = p.get('concordant_ratio', 0.0)
        ratio_str = f"{ratio:.0%}"

        p_sites = p.get('primary_sites', [])
        s_sites = p.get('secondary_sites', [])
        p_sites_str = ', '.join(p_sites[:5]) if p_sites else '-'
        if len(p_sites) > 5:
            p_sites_str += f' (+{len(p_sites)-5})'
        s_sites_str = ', '.join(s_sites[:5]) if s_sites else '-'
        if len(s_sites) > 5:
            s_sites_str += f' (+{len(s_sites)-5})'

        shared_tp = p.get('shared_timepoints', [])
        tp_str = ', '.join(str(t) for t in shared_tp[:6]) if shared_tp else '-'
        if len(shared_tp) > 6:
            tp_str += f' (+{len(shared_tp)-6})'

        section += f"| **{gene}** | {pattern} | {ratio_str} | {p_sites_str} | {s_sites_str} | {tp_str} |\n"

    section += "\n"
    return section


def _generate_table_2c(crosstalk_data, ptype, stype):
    """
    v93: Generate Table 2C - PTM Regulatory Relationship Table
    Replaces the low-readability regulatory circuit diagram with a structured table.
    """
    dual_ptm_proteins = crosstalk_data.get('dual_ptm_proteins', [])
    non_ptm_interactors = crosstalk_data.get('non_ptm_interactors', [])

    section = f"### Table 2C. PTM Cross-Talk Regulatory Relationships ({ptype} \u00d7 {stype})\n\n"
    section += f"Directed regulatory relationships illustrating the cross-talk between "
    section += f"{ptype.lower()} and {stype.lower()} signaling cascades.\n\n"

    # Classify non-PTM interactors into kinases and E3 ligases
    kinases = []
    e3_ligases = []

    for interactor in non_ptm_interactors:
        role = interactor.get('role', 'unknown')
        gene = interactor.get('gene', '')
        if not gene:
            continue

        role_lower = role.lower() if role else ''
        gene_upper = gene.upper()

        is_kinase = ('kinase' in role_lower or
                     gene_upper.endswith('K') and len(gene_upper) <= 6 or
                     'phosphorylat' in role_lower)
        is_e3 = ('ligase' in role_lower or 'ubiquitin' in role_lower or
                 'e3' in role_lower or 'rnf' in gene_upper.lower() or
                 'trim' in gene_upper.lower() or 'mdm' in gene_upper.lower())

        if is_kinase:
            kinases.append(interactor)
        elif is_e3:
            e3_ligases.append(interactor)

    # Part 1: Kinase -> Substrate relationships
    if kinases:
        section += f"**{ptype} Regulatory Relationships (Kinase \u2192 Substrate)**\n\n"
        section += f"| Kinase | Target Substrate | Pattern | Concordance Ratio |\n"
        section += f"|--------|:----------------:|:-------:|:-----------------:|\n"

        rows_added = 0
        for k in kinases[:12]:
            k_gene = k.get('gene', '')
            connected = k.get('connected_dual_ptm_proteins', [])
            if not connected:
                p_int = k.get('primary_ptm_interactions', [])
                s_int = k.get('secondary_ptm_interactions', [])
                connected = list(set(p_int) | set(s_int))

            for target in connected:
                target_data = next((p for p in dual_ptm_proteins if p.get('gene') == target), None)
                if target_data:
                    pattern = target_data.get('pattern', 'mixed').capitalize()
                    ratio = target_data.get('concordant_ratio', 0.0)
                    section += f"| **{k_gene}** | {target} | {pattern} | {ratio:.0%} |\n"
                    rows_added += 1

            if not connected:
                section += f"| **{k_gene}** | - | - | - |\n"
                rows_added += 1

        if rows_added == 0:
            section += f"| *No kinase-substrate relationships identified* | - | - | - |\n"
        section += "\n"

    # Part 2: E3 Ligase -> Substrate relationships
    if e3_ligases:
        section += f"**{stype} Regulatory Relationships (E3 Ligase \u2192 Substrate)**\n\n"
        section += f"| E3 Ligase | Target Substrate | Pattern | Concordance Ratio |\n"
        section += f"|-----------|:----------------:|:-------:|:-----------------:|\n"

        rows_added = 0
        for e in e3_ligases[:12]:
            e_gene = e.get('gene', '')
            connected = e.get('connected_dual_ptm_proteins', [])
            if not connected:
                p_int = e.get('primary_ptm_interactions', [])
                s_int = e.get('secondary_ptm_interactions', [])
                connected = list(set(p_int) | set(s_int))

            for target in connected:
                target_data = next((p for p in dual_ptm_proteins if p.get('gene') == target), None)
                if target_data:
                    pattern = target_data.get('pattern', 'mixed').capitalize()
                    ratio = target_data.get('concordant_ratio', 0.0)
                    section += f"| **{e_gene}** | {target} | {pattern} | {ratio:.0%} |\n"
                    rows_added += 1

            if not connected:
                section += f"| **{e_gene}** | - | - | - |\n"
                rows_added += 1

        if rows_added == 0:
            section += f"| *No E3 ligase-substrate relationships identified* | - | - | - |\n"
        section += "\n"

    # Part 3: Summary of regulatory layers
    if not kinases and not e3_ligases:
        section += "*No kinase or E3 ligase regulatory relationships were identified "
        section += "among the shared non-PTM interactors.*\n\n"
    else:
        section += f"**Summary:** {len(kinases)} kinase(s) and {len(e3_ligases)} E3 ligase(s) "
        section += f"were identified as regulatory nodes connecting {ptype.lower()} and "
        section += f"{stype.lower()} signaling cascades through dual-PTM substrates.\n\n"

    return section


def generate_crosstalk_figure_section(
    crosstalk_data: Dict[str, Any],
    figure_paths: Dict[str, str],
    primary_ptm_type: str = "phosphorylation",
    secondary_ptm_type: str = "ubiquitylation",
) -> str:
    """
    Generate Markdown section with cross-talk visualizations for the report.
    v93: Figure 2A and 2C are replaced with structured tables for better readability.
    Figure 2B (heatmap) is kept as an image with improved resolution.
    """
    ptype = primary_ptm_type.capitalize()
    stype = secondary_ptm_type.capitalize()

    dual_ptm_proteins = crosstalk_data.get('dual_ptm_proteins', [])
    non_ptm_interactors = crosstalk_data.get('non_ptm_interactors', [])
    summary = crosstalk_data.get('summary', {})

    n_total = len(dual_ptm_proteins)
    n_concordant = sum(1 for p in dual_ptm_proteins if p.get('pattern') == 'concordant')
    n_discordant = sum(1 for p in dual_ptm_proteins if p.get('pattern') == 'discordant')
    n_mixed = sum(1 for p in dual_ptm_proteins if p.get('pattern') == 'mixed')

    section = "\n\n---\n\n## Cross-Talk Network Visualization\n\n"

    # Table 2A: Dual-PTM Protein Summary (replaces network diagram)
    if dual_ptm_proteins:
        section += _generate_table_2a(dual_ptm_proteins, ptype, stype,
                                       n_concordant, n_discordant, n_mixed)

    # Figure 2B: Temporal Heatmap (kept as image - most informative visualization)
    if 'figure_b' in figure_paths:
        base64_img = convert_image_to_base64(figure_paths['figure_b'])
        if base64_img:
            section += f"### Figure 2B. Temporal Cross-Talk Regulation Heatmap\n\n"
            section += f"![Temporal Cross-Talk Regulation Heatmap]({base64_img})\n\n"
            section += f"**Figure Legend (2B):** "
            section += f"Split-cell heatmap showing temporal dynamics of dual-PTM proteins. "
            section += f"Each cell is divided into left ({ptype.lower()}, P) and "
            section += f"right ({stype.lower()}, U) halves. "
            section += f"Color intensity represents log2 fold-change magnitude "
            section += f"(red = upregulated, blue = downregulated). "
            section += f"Central dots indicate concordance (green) or discordance (red) "
            section += f"at each timepoint. "
            section += f"Proteins are grouped by pattern (concordant \u2192 mixed \u2192 discordant) "
            section += f"with horizontal separators. "
            section += f"Right-side bars show the overall concordance ratio per protein.\n\n"

    # Table 2C: Regulatory Relationships (replaces circuit diagram)
    if crosstalk_data.get('non_ptm_interactors'):
        section += _generate_table_2c(crosstalk_data, ptype, stype)

    if not dual_ptm_proteins and not figure_paths:
        section += "*Cross-talk visualization data could not be generated.*\n\n"

    return section
