"""
Figure Context Generator — provides figure context for LLM report writing.
Ported from ptm_nonptm_network_command.py FigureInformationGenerator.

v8.0 — Temporal Co-movement Analysis:
  - Co-movement heatmap and cluster line plots added to figure map
  - LLM context includes structured cluster descriptions for writing

v7.0 — Content-driven cascade diagram pipeline:
  - Figure 1: Canonical Pathway Distribution Bar Graph
  - Figure 2+: Signaling Cascade Diagrams (generated AFTER writing by mediator)
  - Figure N+: Cytoscape Network Images (per-timepoint panels)
  
  v7.0: Cascade diagrams are now generated AFTER LLM writes sections, by the
  cascade_mediator_node. The LLM is no longer forced to discuss specific pathways.
  Instead, the LLM freely chooses which pathways to discuss based on the data,
  and the mediator generates diagrams matching the LLM's text.
  
  Pathway candidates (scored list from network_node) are provided as context
  so the LLM can make informed choices, but without MUST-discuss directives.

v2.0 — Aligned with cytoscape_network_pipeline_guide.md:
  GAP 3: Enhanced with timepoint-based figure context
  GAP 4: Multi-type legend integration (full, individual, comparison)
  GAP 6: Updated activation state names to match guide palette
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from ptm_shared.de_novo_representation import is_de_novo_representation

logger = logging.getLogger(__name__)


class FigureInformationGenerator:
    """Generate figure context for LLM prompts.
    
    Provides structured descriptions of ALL report figures so that
    LLM-written sections can reference figures naturally with correct numbering.
    
    v3.0: Includes pathway distribution graph, cascade diagrams, AND Cytoscape
    network images — matching the exact figure numbering in the final report.
    """

    # GAP 6: Updated activation state names to match guide palette
    ACTIVE_STATES = ("high_active", "moderate_active", "activated", "low_active")
    INHIBITED_STATES = ("inhibited", "low_inhibited")

    def __init__(self, network_analysis: dict, parsed_ptms: list = None,
                 comovement_analysis: dict = None, comovement_figures: list = None,
                 comovement_llm_context: str = ""):
        self.network_analysis = network_analysis
        self.network_images = network_analysis.get("network_images", {})
        self.network_data = network_analysis.get("network_data", {})
        self.legends = network_analysis.get("legends", {})
        self.parsed_ptms = parsed_ptms or []
        # GAP 1/3: Timepoint-based results from network_node.py
        self.timepoint_results = network_analysis.get("timepoint_results", {})
        self.timepoints = network_analysis.get("timepoints", [])
        # v3.0: Cascade diagram info
        self.pathway_graph_path = network_analysis.get("pathway_graph_path")
        self.cascade_diagram_path = network_analysis.get("cascade_diagram_path")
        self.cascade_diagram_paths = network_analysis.get("cascade_diagram_paths", {})
        self.cascade_pathway_names = network_analysis.get("cascade_pathway_names", {})
        # v8.9.1: Fig 1 pathway names for LLM-text consistency
        self.fig1_pathway_names = network_analysis.get("fig1_pathway_names", [])
        # v8.0: Temporal co-movement analysis
        self.comovement_analysis = comovement_analysis or {}
        self.comovement_figures = comovement_figures or []
        self.comovement_llm_context = comovement_llm_context
        self.figure_map = self._build_figure_map()

    def _build_figure_map(self) -> Dict[str, dict]:
        """Build mapping of figure labels to their descriptions.
        
        v8.9.3: Fixed to match the ACTUAL figure numbering in
        generate_network_figure_section (network_node.py):
          Figure 1 = Pathway Distribution Graph (main figure)
          Supplementary Figure 1+ = Compartmentalized Signaling Context Diagrams (per-condition or combined)
          Supplementary Figure N{A-Z} = Cytoscape Network Images (per-timepoint panels)
        
        IMPORTANT: Only Figure 1 is a main figure. All context diagrams and
        Cytoscape network images are Supplementary Figures in the final report.
        The LLM must reference them as "Supplementary Figure X" to match.
        """
        fig_map = {}
        main_fig_num = 1
        supp_num = 1  # Supplementary figure counter (matches network_node.py)
        panel_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        # ── Figure 1: Canonical Pathway Distribution Bar Graph (MAIN FIGURE) ──
        if self.pathway_graph_path:
            fig_map["pathway_graph"] = {
                "figure_number": main_fig_num,
                "figure_label": f"Figure {main_fig_num}",
                "display_name": "PTM Pathway-Membership Distribution with Protein and Network Context",
                "description": self._describe_pathway_graph(),
                "panel_index": 0,
                "figure_type": "pathway_graph",
            }
            main_fig_num += 1

        # ── Supplementary Figure 1+: Compartmentalized Signaling Context Diagrams ──
        if self.cascade_diagram_paths:
            # Per-condition cascade diagrams
            cascade_timepoints = self.timepoints if self.timepoints else sorted(self.cascade_diagram_paths.keys())
            for tp in cascade_timepoints:
                if tp not in self.cascade_diagram_paths:
                    continue
                fig_map[f"cascade_{tp}"] = {
                    "figure_number": supp_num,
                    "figure_label": f"Supplementary Figure {supp_num}",
                    "display_name": f"Compartmentalized Signaling Context Diagram — {tp}",
                    "description": self._describe_cascade_diagram(condition=tp),
                    "panel_index": 0,
                    "figure_type": "cascade_diagram",
                    "condition": tp,
                }
                supp_num += 1
        elif self.cascade_diagram_path:
            # Single combined cascade diagram
            fig_map["cascade_combined"] = {
                "figure_number": supp_num,
                "figure_label": f"Supplementary Figure {supp_num}",
                "display_name": "Compartmentalized Signaling Context Diagram",
                "description": self._describe_cascade_diagram(),
                "panel_index": 0,
                "figure_type": "cascade_diagram",
            }
            supp_num += 1

        # ── Co-movement Figures (v8.0) — these remain as main figures ──
        for cf in self.comovement_figures:
            cf_type = cf.get("type", "unknown")
            cf_caption = cf.get("caption", "Temporal Coordination Analysis")
            if cf_type in ("heatmap", "supplementary_heatmap"):
                fig_map["comovement_heatmap"] = {
                    "figure_number": main_fig_num,
                    "figure_label": f"Figure {main_fig_num}",
                    "display_name": "Temporal PTM Coordination Cluster Heatmap",
                    "description": (
                        "Hierarchical clustering heatmap of PTM temporal profiles. "
                        "Rows represent individual PTM sites, columns represent time points. "
                        "Color intensity reflects Log2FC magnitude. Dendrogram and cluster "
                        "color bars group temporally coordinated PTMs that share similar temporal dynamics. "
                        "Clusters reveal coordinated phosphorylation waves."
                    ),
                    "panel_index": 0,
                    "figure_type": "comovement_heatmap",
                }
                main_fig_num += 1
            elif cf_type == "transient_burst_composite":
                fig_map["comovement_burst"] = {
                    "figure_number": main_fig_num,
                    "figure_label": f"Figure {main_fig_num}",
                    "display_name": f"Transient Phosphorylation Burst Dynamics",
                    "description": (
                        f"{cf_caption} "
                        "Panel (a) shows individual PTM time-series profiles colored by cluster membership "
                        "with cluster mean (bold). Panel (b) shows peak amplitude profiles. "
                        "Panel (c) shows cluster mean temporal envelope showing activation-recovery kinetics."
                    ),
                    "panel_index": 0,
                    "figure_type": "comovement_burst",
                }
                main_fig_num += 1
            elif cf_type in ("cluster_lineplot", "cluster_detail", "supplementary_cluster"):
                cluster_id = cf.get("cluster_id", "")
                fig_map[f"comovement_cluster_{cluster_id}"] = {
                    "figure_number": main_fig_num,
                    "figure_label": f"Figure {main_fig_num}",
                    "display_name": f"Temporal Profile \u2014 {cf_caption}",
                    "description": (
                        f"Line plot showing the temporal Log2FC profiles of PTM sites in {cf_caption}. "
                        "Solid lines represent PTM proteins; dashed lines represent linked Non-PTM interactors. "
                        "Shaded area indicates the cluster envelope. Temporally coordinated PTMs share similar "
                        "temporal dynamics, suggesting coordinated regulation."
                    ),
                    "panel_index": 0,
                    "figure_type": "comovement_lineplot",
                }
                main_fig_num += 1

        # ── Supplementary Figure N{A-Z}: Cytoscape Network Images (per-timepoint panels) ──
        # v5.0: "main" is excluded — replaced by pathway distribution graph
        sorted_labels = []
        for label in sorted(
            [k for k in self.network_images.keys() if k != "main"],
            key=self._tp_sort_key
        ):
            sorted_labels.append(label)

        for idx, label in enumerate(sorted_labels):
            phase = self._tp_to_phase(label)
            display = f"PTM-NonPTM Integrated Network at {label} ({phase})"
            description = self._describe_timepoint_network(label)
            panel = panel_labels[idx] if idx < len(panel_labels) else str(idx + 1)
            fig_label = f"Supplementary Figure {supp_num}{panel}"

            fig_map[label] = {
                "figure_number": supp_num,
                "figure_label": fig_label,
                "display_name": display,
                "description": description,
                "panel_index": idx,
                "figure_type": "cytoscape_network",
            }

        return fig_map

    # ── Description generators ──

    def _describe_pathway_graph(self) -> str:
        """Generate description for the Canonical Pathway Distribution Bar Graph (Figure 1).
        
        v8.9.1: Now includes the actual pathway names shown in the figure.
        """
        desc = (
            "This bar graph shows the cumulative |Protein_Log2FC| score of activated PTM proteins "
            "(red), inhibited PTM proteins (blue), and Non-PTM interactor proteins (green) across "
            "canonical signaling pathways identified via 3-Layer Pathway Enrichment: "
            "(1) KEGG + Reactome per-gene pathway mapping, "
            "(2) STRING interaction partner-based indirect pathway inference for genes with "
            "limited direct pathway annotations. "
            "Disease-related pathways (KEGG 05xxx) are excluded. "
            "Pathways are ranked by total cumulative score, highlighting pathways with the "
            "strongest combined expression changes. "
            "Bar labels show the score followed by protein count in parentheses."
        )
        if self.fig1_pathway_names:
            top_names = self.fig1_pathway_names[:10]
            desc += (
                f" The top pathways shown in this figure (ranked by score) are: "
                f"{', '.join(top_names)}"
            )
            if len(self.fig1_pathway_names) > 10:
                desc += f" (and {len(self.fig1_pathway_names) - 10} more)"
            desc += "."
        return desc

    def _describe_cascade_diagram(self, condition: str = None) -> str:
        """Generate description for Signaling Cascade Diagram(s).
        
        v7.0: Cascade diagrams are generated AFTER writing by the mediator.
        At write-time, we describe what the cascade diagram WILL show (a placeholder)
        so the LLM knows the figure exists but isn't forced to discuss specific pathways.
        After the mediator generates the actual diagrams, the figure context is updated.
        """
        cond_str = f" for the {condition} condition" if condition else ""
        
        # v7.0: At write-time, cascade_pathway_names may be empty (mediator hasn't run yet).
        # If populated (e.g., after mediator), include the actual pathway names.
        pw_key = condition if condition else "combined"
        pathway_names = self.cascade_pathway_names.get(pw_key, [])
        
        if pathway_names:
            pw_list_str = ", ".join(pathway_names)
            pw_sentence = (
                f"The diagram shows the following signaling pathways: {pw_list_str}. "
            )
        else:
            pw_sentence = (
                "The diagram will place the pathways discussed in the text into a compartmentalized "
                "literature-context map. "
            )
        
        desc = (
            f"This compartmentalized pathway-context diagram{cond_str} organizes measured PTM and protein observations "
            "across cellular compartments (Extracellular Space, Plasma Membrane, "
            "Cytoplasm, Nucleus). "
            f"{pw_sentence}"
            "Each horizontal lane represents a distinct signaling pathway, with proteins positioned "
            "in their annotated subcellular compartment (based on UniProt and GO annotations). "
            "Protein nodes are color-coded: red = higher measured PTM abundance (Log2FC > 0), "
            "blue = lower measured PTM abundance (Log2FC < 0), green = higher Non-PTM abundance, "
            "purple = lower Non-PTM abundance, orange diamond = kinase annotation. "
            "For conventionally quantified sites, node size is proportional to |PTM Log2FC| magnitude; "
            "de novo sites use detection/LOD context rather than a fold-change scale. "
            "Gray arrows indicate literature/pathway context only and do not establish Order-specific direction or direct regulation."
        )

        # Add condition-specific protein summary if available
        if condition and self.parsed_ptms:
            cond_ptms = [p for p in self.parsed_ptms
                         if (p.get("condition") or p.get("Condition", "")) == condition]
            if cond_ptms:
                quantified = [p for p in cond_ptms if not is_de_novo_representation(p)]
                denovo_count = len(cond_ptms) - len(quantified)
                higher = [p for p in quantified if (p.get("ptm_relative_log2fc") or 0) > 0]
                lower = [p for p in quantified if (p.get("ptm_relative_log2fc") or 0) < 0]
                desc += (
                    f" In the {condition} condition, {len(higher)} conventionally quantified PTMs have higher measured abundance "
                    f"and {len(lower)} have lower measured abundance; {denovo_count} de novo rows are represented by detection/LOD context."
                )
                top_act = sorted(higher, key=lambda x: -(x.get("ptm_relative_log2fc") or 0))[:5]
                if top_act:
                    top_str = ", ".join(
                        f"{p.get('gene', '?')}({p.get('position', '')})"
                        for p in top_act
                    )
                    desc += f" Largest conventionally quantified PTM contrasts: {top_str}. Numerical contrast magnitude is descriptive and is not a biological-priority ranking."

        return desc

    def _describe_main_network(self) -> str:
        """Generate description for the main combined network.
        
        GAP 2/3: Now includes Non-PTM node counts and types.
        """
        nodes = self.network_data.get("nodes", {})
        edges = self.network_data.get("edges", [])

        # Handle nodes as dict or list
        if isinstance(nodes, dict):
            node_list = list(nodes.values()) if nodes else []
        else:
            node_list = nodes or []

        ptm_nodes = [n for n in node_list if isinstance(n, dict) and n.get("type") == "PTM"]
        non_ptm_nodes = [n for n in node_list if isinstance(n, dict) and n.get("type") == "Non-PTM"]
        active = [n for n in ptm_nodes if n.get("state") in self.ACTIVE_STATES]
        inhibited = [n for n in ptm_nodes if n.get("state") in self.INHIBITED_STATES]

        edge_types = defaultdict(int)
        for e in edges:
            if isinstance(e, dict):
                edge_types[e.get("evidence_type", "Unknown")] += 1

        desc = (
            f"The combined PTM-NonPTM context map contains "
            f"{len(ptm_nodes)} PTM nodes (circles), "
            f"{len(non_ptm_nodes)} Non-PTM protein nodes (diamonds), "
            f"and {len(edges)} interaction edges. "
            f"{len(active)} PTMs have higher measured abundance (red/orange), "
            f"while {len(inhibited)} have lower measured abundance (blue). "
            f"Non-PTM proteins are shown in green diamonds. "
        )

        if edge_types:
            et_str = ", ".join(
                f"{cnt} {et}" for et, cnt in sorted(edge_types.items(), key=lambda x: -x[1])[:4]
            )
            desc += f"Edge types include {et_str}. "

        # GAP 6: Updated color descriptions to match guide palette
        desc += (
            "Node colors represent measured abundance context: red=higher measured PTM abundance, "
            "dark orange=modestly higher measured PTM abundance, "
            "royal blue=lower measured PTM abundance, light blue=modestly lower measured abundance, "
            "light green=Non-PTM protein. "
            "Node size is a display aid and is not biological priority or direct regulatory strength. "
            "Edges are literature/database context and do not establish Order-specific direction, activity, or causality."
        )

        return desc

    def _describe_timepoint_network(self, timepoint: str) -> str:
        """Generate description for a timepoint-specific sub-network.
        
        GAP 1/3: New method for timepoint-based figure descriptions.
        Uses timepoint_results from network_node.py when available.
        """
        # Try timepoint_results first (GAP 1)
        if timepoint in self.timepoint_results:
            tp_data = self.timepoint_results[timepoint]
            stats = tp_data.get("stats", {})
            active_count = stats.get("active_ptm_count", 0)
            inhibited_count = stats.get("inhibited_ptm_count", 0)
            non_ptm_count = stats.get("non_ptm_count", 0)
            edge_count = stats.get("active_edge_count", 0)
            phase = self._tp_to_phase(timepoint)

            desc = (
                f"The {timepoint} ({phase}) network display contains "
                f"{active_count} PTMs with higher measured abundance, {inhibited_count} with lower measured abundance, "
                f"{non_ptm_count} Non-PTM proteins, and {edge_count} context edges. "
            )

            # Key pathways
            pw_summary = tp_data.get("pathway_summary", {})
            if pw_summary:
                top_pw = sorted(pw_summary.keys(), key=lambda k: -len(pw_summary[k]))[:3]
                desc += f"Descriptive pathway-membership context: {', '.join(top_pw)}. "

            return desc

        # Fallback: condition-based description (backward compatible)
        return self._describe_condition_network(timepoint)

    def _describe_condition_network(self, condition: str) -> str:
        """Generate description for a condition-specific sub-network (backward compatible)."""
        nodes = self.network_data.get("nodes", {})

        # Handle nodes as dict or list
        if isinstance(nodes, dict):
            node_list = list(nodes.values()) if nodes else []
        else:
            node_list = nodes or []

        # Filter PTMs for this condition
        cond_genes = set()
        for ptm in self.parsed_ptms:
            cond = ptm.get("condition") or ptm.get("Condition", "")
            if cond == condition:
                cond_genes.add(ptm.get("gene", ""))

        cond_nodes = [n for n in node_list if isinstance(n, dict) and n.get("gene") in cond_genes]
        active = [n for n in cond_nodes if n.get("state") in self.ACTIVE_STATES]
        inhibited = [n for n in cond_nodes if n.get("state") in self.INHIBITED_STATES]

        desc = (
            f"The {condition} condition sub-network contains {len(cond_nodes)} PTM nodes, "
            f"with {len(active)} higher and {len(inhibited)} lower measured-abundance observations. "
        )

        return desc

    # ── LLM context generation ──

    def generate_figure_context_for_llm(self, section_type: str = "results") -> str:
        """Generate figure context text to inject into LLM prompts.
        
        v3.0: Now includes ALL figures (pathway graph, cascade diagrams, Cytoscape)
        with correct numbering matching the final report.
        
        Returns a structured text block that tells the LLM which figures
        are available and how to reference them.
        """
        if not self.figure_map:
            return ""

        lines = [
            "\n--- FIGURE CONTEXT (ALL REPORT FIGURES) ---",
            "The following figures are included in this report.",
            "You MUST reference these figures naturally in your writing using their EXACT labels.",
            "CRITICAL: Main figures use 'Figure N' (e.g., Figure 1). "
            "Supplementary figures use 'Supplementary Figure N' (e.g., Supplementary Figure 1).",
            "For example: 'Figure 1 summarizes descriptive pathway-membership context at sampled timepoints.'",
            "or 'Figure 3 places literature/pathway annotations and measured observations in a common non-directional context.'",
            "or 'Supplementary Figure N provides a condition-specific observation map.'",
            "NEVER use 'Figure 2' to refer to a Supplementary Figure. Always include the word 'Supplementary'.",
            "",
        ]

        for label, info in self.figure_map.items():
            fig_type = info.get("figure_type", "unknown")
            lines.append(f"**{info['figure_label']}: {info['display_name']}**")
            lines.append(f"  Type: {fig_type}")
            lines.append(f"  {info['description']}")
            lines.append("")

        # GAP 3: Add temporal comparison context when multiple timepoints exist
        if len(self.timepoints) > 1 and self.timepoint_results:
            lines.append("**Temporal Dynamics Summary:**")
            for tp in self.timepoints:
                if tp in self.timepoint_results:
                    stats = self.timepoint_results[tp].get("stats", {})
                    phase = self._tp_to_phase(tp)
                    lines.append(
                        f"- {tp} ({phase}): {stats.get('active_ptm_count', 0)} higher-abundance PTMs, "
                        f"{stats.get('inhibited_ptm_count', 0)} lower-abundance PTMs, "
                        f"{stats.get('non_ptm_count', 0)} Non-PTM proteins"
                    )
            lines.append("")

            # Temporal comparison legend from network_node.py
            comparison_legend = self.legends.get("comparison_legend", "")
            if comparison_legend:
                lines.append(comparison_legend)
                lines.append("")

        # Panel-by-panel summary
        individual_legends = self.legends.get("individual_legends", {})
        if individual_legends:
            lines.append("**Panel-by-Panel Summary:**")
            for tp, legend_text in individual_legends.items():
                lines.append(legend_text)
            lines.append("")

        # v8.0: Add co-movement analysis context
        if self.comovement_llm_context:
            lines.append("**Temporal PTM Coordination Analysis:**")
            lines.append(self.comovement_llm_context)
            lines.append("")

        # v8.9.1: Fig 1 Pathway Consistency Directive
        # Provide the exact pathway names shown in Figure 1 so LLM can maintain
        # consistency between text and figure.
        if self.fig1_pathway_names:
            lines.append("**FIGURE 1 PATHWAY LIST (Direct NES):**")
            lines.append(
                "The following pathways are shown in Figure 1 "
                "(Time-resolved Direct PTM Pathway Enrichment), "
                "ranked by signed Direct NES. Protein and network support are annotations, "
                "not rank:"
            )
            for i, pw_name in enumerate(self.fig1_pathway_names, 1):
                lines.append(f"  {i}. {pw_name}")
            lines.append("")
            lines.append(
                "**PATHWAY CONSISTENCY RULE (CRITICAL):**\n"
                "- When discussing signaling pathways in the text, primarily reference "
                "the pathways listed above (Figure 1 Direct NES).\n"
                "- If you mention a pathway that IS in Figure 1, cite it as Direct NES "
                "context and apply its recorded q-value; never call it pathway activation.\n"
                "- If you mention a pathway that is NOT in Figure 1, say it is from literature.\n"
                "- Do NOT describe a pathway as 'enriched in our analysis' if it is not "
                "in Figure 1. STRING support is not discovery.\n"
                "- Do not privilege PI3K-Akt or MAPK because they are canonical."
            )
            lines.append("")

        # v7.0: Provide pathway candidates as informational context (not forced)
        # The LLM can use this to make informed pathway choices in its writing.
        # The cascade_mediator will later extract which pathways were actually discussed.
        pathway_candidates = self.network_analysis.get("pathway_candidates_summary", "")

        # Section-specific instructions (v7.0: no forced pathway discussion)
        if section_type == "results":
            candidate_hint = ""
            if pathway_candidates:
                candidate_hint = (
                    f" Available signaling pathway data from the analysis includes: {pathway_candidates}. "
                    "You may discuss the pathways most relevant to your analysis findings."
                )
            lines.append(
                "INSTRUCTION: In the Results section, you MUST reference the figures by their "
                "exact labels (Figure N for main figures, Supplementary Figure N for supplementary). "
                "Use the exact figure labels. Figure 1 supplies pathway-membership context; Figure 2 "
                "summarizes substrate-derived candidate context; Figure 3 is a non-directional context map. "
                "Supplementary figures are observation maps, not proof of pathway order. Mention only "
                "measured PTM/Non-PTM contrasts and the evidence boundary stated in each caption. "
                "For q>=0.05 use 'descriptive pathway trend' or 'pathway context', never enriched, active, "
                "or functionally engaged. For multiple conditions, describe sampled-timepoint differences "
                f"without imposing an ordered mechanism.{candidate_hint}"
            )
        elif section_type == "discussion":
            candidate_hint = ""
            if pathway_candidates:
                candidate_hint = (
                    f" Key signaling pathway candidates from the analysis: {pathway_candidates}. "
                    "Focus on the pathways most relevant to your biological interpretation."
                )
            lines.append(
                "INSTRUCTION: In the Discussion section, distinguish observed contrasts and local profiles "
                "from traceable literature context and prospective hypotheses. Reference figures by their "
                "EXACT labels. Figure 1 and context diagrams organize annotation context; they do not demonstrate "
                "activity, direct edges, pathway function, or causal ordering. If temporal data are available, "
                "discuss only sampled-timepoint profiles and aggregate robustness. Do not call a co-wave a functional "
                "module, assign a common regulator, or infer signaling propagation from membership alone."
            )

        lines.append("--- END FIGURE CONTEXT ---\n")

        return "\n".join(lines)

    def get_figure_reference(self, label: str = "main") -> str:
        """Get a figure reference string for a specific network."""
        info = self.figure_map.get(label)
        if info:
            return info["figure_label"]
        return ""

    def has_figures(self) -> bool:
        """Check if any figures are available."""
        return len(self.figure_map) > 0

    def get_temporal_summary(self) -> str:
        """Get a summary of temporal network changes.
        
        GAP 3: New method for temporal analysis context.
        """
        if not self.timepoint_results or len(self.timepoints) < 2:
            return ""

        lines = ["Temporal Network Evolution:"]
        prev_active = 0
        for tp in self.timepoints:
            if tp in self.timepoint_results:
                stats = self.timepoint_results[tp].get("stats", {})
                curr_active = stats.get("active_ptm_count", 0)
                change = curr_active - prev_active
                direction = "↑" if change > 0 else ("↓" if change < 0 else "→")
                lines.append(
                    f"  {tp}: {curr_active} active PTMs "
                    f"({direction}{abs(change)} from previous)"
                )
                prev_active = curr_active

        return "\n".join(lines)

    # --- Helper methods ---

    @staticmethod
    def _tp_sort_key(tp: str) -> float:
        """Sort key for timepoint strings."""
        import re
        tp_lower = tp.lower().strip()
        m = re.match(r'^(\d+(?:\.\d+)?)\s*min', tp_lower)
        if m:
            return float(m.group(1))
        m = re.match(r'^(\d+(?:\.\d+)?)\s*h', tp_lower)
        if m:
            return float(m.group(1)) * 60
        m = re.match(r'^(\d+(?:\.\d+)?)\s*s(?:ec)?', tp_lower)
        if m:
            return float(m.group(1)) / 60
        return -1.0

    @staticmethod
    def _tp_to_phase(tp: str) -> str:
        """Classify timepoint into phase label."""
        import re
        tp_lower = tp.lower().strip()
        minutes = -1.0
        m = re.match(r'^(\d+(?:\.\d+)?)\s*min', tp_lower)
        if m:
            minutes = float(m.group(1))
        m2 = re.match(r'^(\d+(?:\.\d+)?)\s*h', tp_lower)
        if m2:
            minutes = float(m2.group(1)) * 60
        m3 = re.match(r'^(\d+(?:\.\d+)?)\s*s(?:ec)?', tp_lower)
        if m3:
            minutes = float(m3.group(1)) / 60

        if minutes < 0:
            return "Condition"
        if minutes < 10:
            return "Early Phase"
        if minutes <= 40:
            return "Mid Phase"
        return "Late Phase"
