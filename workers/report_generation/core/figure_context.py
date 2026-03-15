"""
Figure Context Generator — provides figure context for LLM report writing.
Ported from ptm_nonptm_network_command.py FigureInformationGenerator.

v2.0 — Aligned with cytoscape_network_pipeline_guide.md:
  GAP 3: Enhanced with timepoint-based figure context
  GAP 4: Multi-type legend integration (full, individual, comparison)
  GAP 6: Updated activation state names to match guide palette

Generates structured figure descriptions so that LLM-written Results/Discussion
sections can reference "Figure 1A", "Figure 1B" etc. naturally.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class FigureInformationGenerator:
    """Generate figure context for LLM prompts.
    
    Provides structured descriptions of network figures so that
    LLM-written sections can reference figures naturally.
    
    v2.0: Now supports timepoint-based analysis, Non-PTM nodes,
    and multi-type legends from network_node.py.
    """

    # GAP 6: Updated activation state names to match guide palette
    ACTIVE_STATES = ("high_active", "moderate_active", "activated", "low_active")
    INHIBITED_STATES = ("inhibited", "low_inhibited")

    def __init__(self, network_analysis: dict, parsed_ptms: list = None):
        self.network_analysis = network_analysis
        self.network_images = network_analysis.get("network_images", {})
        self.network_data = network_analysis.get("network_data", {})
        self.legends = network_analysis.get("legends", {})
        self.parsed_ptms = parsed_ptms or []
        # GAP 1/3: Timepoint-based results from network_node.py
        self.timepoint_results = network_analysis.get("timepoint_results", {})
        self.timepoints = network_analysis.get("timepoints", [])
        self.figure_map = self._build_figure_map()

    def _build_figure_map(self) -> Dict[str, dict]:
        """Build mapping of figure labels to their descriptions.
        
        GAP 3: Now creates panel-based figure map when timepoint data is available.
        """
        fig_map = {}
        fig_num = 1
        panel_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        # Sort: "main" first, then timepoints in order
        sorted_labels = []
        if "main" in self.network_images:
            sorted_labels.append("main")
        for label in sorted(
            [k for k in self.network_images.keys() if k != "main"],
            key=self._tp_sort_key
        ):
            sorted_labels.append(label)

        for idx, label in enumerate(sorted_labels):
            if label == "main":
                display = "Combined PTM-NonPTM Signaling Network"
                description = self._describe_main_network()
                fig_label = f"Figure {fig_num}"
            else:
                phase = self._tp_to_phase(label)
                display = f"PTM-NonPTM Integrated Network at {label} ({phase})"
                description = self._describe_timepoint_network(label)
                panel = panel_labels[idx - 1] if idx > 0 and idx <= len(panel_labels) else str(idx)
                fig_label = f"Figure {fig_num}{panel}"

            fig_map[label] = {
                "figure_number": fig_num,
                "figure_label": fig_label,
                "display_name": display,
                "description": description,
                "panel_index": idx,
            }

        return fig_map

    def _describe_main_network(self) -> str:
        """Generate description for the main combined network.
        
        GAP 2/3: Now includes Non-PTM node counts and types.
        """
        nodes = self.network_data.get("nodes", [])
        edges = self.network_data.get("edges", [])

        ptm_nodes = [n for n in nodes if n.get("type") == "PTM"]
        non_ptm_nodes = [n for n in nodes if n.get("type") == "Non-PTM"]
        active = [n for n in ptm_nodes if n.get("state") in self.ACTIVE_STATES]
        inhibited = [n for n in ptm_nodes if n.get("state") in self.INHIBITED_STATES]

        edge_types = defaultdict(int)
        for e in edges:
            edge_types[e.get("evidence_type", "Unknown")] += 1

        desc = (
            f"The combined PTM-NonPTM signaling network contains "
            f"{len(ptm_nodes)} PTM nodes (circles), "
            f"{len(non_ptm_nodes)} Non-PTM protein nodes (diamonds), "
            f"and {len(edges)} interaction edges. "
            f"{len(active)} PTMs show activation (red/orange), "
            f"while {len(inhibited)} show inhibition (blue). "
            f"Non-PTM proteins are shown in green diamonds. "
        )

        if active:
            top = sorted(active, key=lambda x: -x.get("value", 0))[:5]
            top_str = ", ".join(f"{n['gene']}-{n['site']} (Log2FC={n['value']:.2f})" for n in top)
            desc += f"The most strongly activated PTMs are {top_str}. "

        if inhibited:
            top = sorted(inhibited, key=lambda x: x.get("value", 0))[:3]
            top_str = ", ".join(f"{n['gene']}-{n['site']} (Log2FC={n['value']:.2f})" for n in top)
            desc += f"The most strongly inhibited PTMs are {top_str}. "

        if edge_types:
            et_str = ", ".join(
                f"{cnt} {et}" for et, cnt in sorted(edge_types.items(), key=lambda x: -x[1])[:4]
            )
            desc += f"Edge types include {et_str}. "

        # GAP 6: Updated color descriptions to match guide palette
        desc += (
            "Node colors represent activation state: red=high activation (Log2FC>1.0), "
            "dark orange=moderate activation (0<Log2FC≤1.0), "
            "royal blue=inhibited (Log2FC<-1.0), light blue=weak inhibition, "
            "light green=Non-PTM protein. "
            "Node size is proportional to |Log2FC| magnitude (30-100px). "
            "Edge colors indicate evidence type: gray=STRING-DB PPI, "
            "forest green=KEGG pathway, orange-red=KEA3 kinase-substrate."
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
                f"The {timepoint} ({phase}) network shows "
                f"{active_count} activated PTMs, {inhibited_count} inhibited PTMs, "
                f"{non_ptm_count} Non-PTM proteins, and {edge_count} active edges. "
            )

            # Top activated PTMs
            top_active = sorted(
                tp_data.get("active_ptm_nodes", []),
                key=lambda x: -x.get("value", 0)
            )[:5]
            if top_active:
                top_str = ", ".join(
                    f"{n['gene']}({n['site']}): Log2FC={n['value']:.2f}" for n in top_active
                )
                desc += f"Top activated: {top_str}. "

            # Top inhibited PTMs
            top_inhib = sorted(
                tp_data.get("inhibited_ptm_nodes", []),
                key=lambda x: x.get("value", 0)
            )[:3]
            if top_inhib:
                top_str = ", ".join(
                    f"{n['gene']}({n['site']}): Log2FC={n['value']:.2f}" for n in top_inhib
                )
                desc += f"Top inhibited: {top_str}. "

            # Key pathways
            pw_summary = tp_data.get("pathway_summary", {})
            if pw_summary:
                top_pw = sorted(pw_summary.keys(), key=lambda k: -len(pw_summary[k]))[:3]
                desc += f"Key pathways: {', '.join(top_pw)}. "

            return desc

        # Fallback: condition-based description (backward compatible)
        return self._describe_condition_network(timepoint)

    def _describe_condition_network(self, condition: str) -> str:
        """Generate description for a condition-specific sub-network (backward compatible)."""
        nodes = self.network_data.get("nodes", [])

        # Filter PTMs for this condition
        cond_genes = set()
        for ptm in self.parsed_ptms:
            cond = ptm.get("condition") or ptm.get("Condition", "")
            if cond == condition:
                cond_genes.add(ptm.get("gene", ""))

        cond_nodes = [n for n in nodes if n.get("gene") in cond_genes]
        active = [n for n in cond_nodes if n.get("state") in self.ACTIVE_STATES]
        inhibited = [n for n in cond_nodes if n.get("state") in self.INHIBITED_STATES]

        desc = (
            f"The {condition} condition sub-network shows {len(cond_nodes)} PTM nodes, "
            f"with {len(active)} activated and {len(inhibited)} inhibited. "
        )

        if active:
            top = sorted(active, key=lambda x: -x.get("value", 0))[:3]
            top_str = ", ".join(f"{n['gene']}-{n['site']}" for n in top)
            desc += f"Key activated PTMs: {top_str}. "

        return desc

    def generate_figure_context_for_llm(self, section_type: str = "results") -> str:
        """Generate figure context text to inject into LLM prompts.
        
        GAP 3: Enhanced with timepoint-based context and temporal comparison.
        Returns a structured text block that tells the LLM which figures
        are available and how to reference them.
        """
        if not self.figure_map:
            return ""

        lines = [
            "\n--- NETWORK FIGURE CONTEXT ---",
            "The following network visualization figures are included in this report.",
            "Reference them naturally in your writing using their figure numbers.",
            "Example: 'As shown in Figure 1, the PTM signaling network reveals...'",
            "",
        ]

        for label, info in self.figure_map.items():
            lines.append(f"**{info['figure_label']}: {info['display_name']}**")
            lines.append(info["description"])
            lines.append("")

        # GAP 3: Add temporal comparison context when multiple timepoints exist
        if len(self.timepoints) > 1 and self.timepoint_results:
            lines.append("**Temporal Dynamics Summary:**")
            for tp in self.timepoints:
                if tp in self.timepoint_results:
                    stats = self.timepoint_results[tp].get("stats", {})
                    phase = self._tp_to_phase(tp)
                    lines.append(
                        f"- {tp} ({phase}): {stats.get('active_ptm_count', 0)} activated, "
                        f"{stats.get('inhibited_ptm_count', 0)} inhibited, "
                        f"{stats.get('non_ptm_count', 0)} Non-PTM proteins"
                    )
            lines.append("")

            # Temporal comparison legend from network_node.py
            comparison_legend = self.legends.get("comparison_legend", "")
            if comparison_legend:
                lines.append(comparison_legend)
                lines.append("")

        # GAP 4: Include individual panel legends
        individual_legends = self.legends.get("individual_legends", {})
        if individual_legends:
            lines.append("**Panel-by-Panel Summary:**")
            for tp, legend_text in individual_legends.items():
                lines.append(legend_text)
            lines.append("")

        # Section-specific instructions
        if section_type == "results":
            lines.append(
                "INSTRUCTION: In the Results section, describe the network analysis findings "
                "and reference the figures. Mention specific PTM nodes, their activation states, "
                "Non-PTM interactors, and key interaction edges visible in the network. "
                "If multiple timepoints are present, describe the temporal progression of "
                "signaling network changes across early, mid, and late phases."
            )
        elif section_type == "discussion":
            lines.append(
                "INSTRUCTION: In the Discussion section, interpret the network topology "
                "and discuss the biological significance of the observed interaction patterns. "
                "Reference the figures when discussing network-level findings. "
                "If temporal data is available, discuss how the signaling network evolves "
                "over time and the implications for cellular response mechanisms."
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
