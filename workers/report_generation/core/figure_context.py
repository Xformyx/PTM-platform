"""
Figure Context Generator — provides figure context for LLM report writing.
Ported from ptm_nonptm_network_command.py FigureInformationGenerator.

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
    """

    def __init__(self, network_analysis: dict, parsed_ptms: list = None):
        self.network_analysis = network_analysis
        self.network_images = network_analysis.get("network_images", {})
        self.network_data = network_analysis.get("network_data", {})
        self.legends = network_analysis.get("legends", {})
        self.parsed_ptms = parsed_ptms or []
        self.figure_map = self._build_figure_map()

    def _build_figure_map(self) -> Dict[str, dict]:
        """Build mapping of figure labels to their descriptions."""
        fig_map = {}
        fig_num = 1

        for label in sorted(self.network_images.keys()):
            if label == "main":
                display = "Combined PTM Signaling Network"
                description = self._describe_main_network()
            else:
                display = f"PTM Network — {label}"
                description = self._describe_condition_network(label)

            fig_map[label] = {
                "figure_number": fig_num,
                "figure_label": f"Figure {fig_num}",
                "display_name": display,
                "description": description,
            }
            fig_num += 1

        return fig_map

    def _describe_main_network(self) -> str:
        """Generate description for the main combined network."""
        nodes = self.network_data.get("nodes", [])
        edges = self.network_data.get("edges", [])

        active = [n for n in nodes if n.get("state") in ("activated", "moderate_active")]
        inhibited = [n for n in nodes if n.get("state") == "inhibited"]

        edge_types = defaultdict(int)
        for e in edges:
            edge_types[e.get("evidence_type", "Unknown")] += 1

        desc = (
            f"The combined PTM signaling network contains {len(nodes)} PTM nodes "
            f"and {len(edges)} interaction edges. "
            f"{len(active)} PTMs show activation (red/orange), "
            f"while {len(inhibited)} show inhibition (blue). "
        )

        if active:
            top = sorted(active, key=lambda x: -x.get("value", 0))[:3]
            top_str = ", ".join(f"{n['gene']}-{n['site']} (Log2FC={n['value']:.2f})" for n in top)
            desc += f"The most strongly activated PTMs are {top_str}. "

        if edge_types:
            et_str = ", ".join(f"{cnt} {et}" for et, cnt in sorted(edge_types.items(), key=lambda x: -x[1])[:3])
            desc += f"Edge types include {et_str}. "

        desc += (
            "Node colors represent activation state (red=high activation, orange=moderate, "
            "yellow=baseline, blue=inhibited). Node size is proportional to |Log2FC| magnitude. "
            "Edge colors indicate evidence type (green=STRING-DB, orange=shared pathway, "
            "purple=kinase-substrate)."
        )

        return desc

    def _describe_condition_network(self, condition: str) -> str:
        """Generate description for a condition-specific sub-network."""
        nodes = self.network_data.get("nodes", [])

        # Filter PTMs for this condition
        cond_genes = set()
        for ptm in self.parsed_ptms:
            cond = ptm.get("condition") or ptm.get("Condition", "")
            if cond == condition:
                cond_genes.add(ptm.get("gene", ""))

        cond_nodes = [n for n in nodes if n.get("gene") in cond_genes]
        active = [n for n in cond_nodes if n.get("state") in ("activated", "moderate_active")]
        inhibited = [n for n in cond_nodes if n.get("state") == "inhibited"]

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

        if section_type == "results":
            lines.append(
                "INSTRUCTION: In the Results section, describe the network analysis findings "
                "and reference the figures. Mention specific PTM nodes, their activation states, "
                "and key interaction edges visible in the network."
            )
        elif section_type == "discussion":
            lines.append(
                "INSTRUCTION: In the Discussion section, interpret the network topology "
                "and discuss the biological significance of the observed interaction patterns. "
                "Reference the figures when discussing network-level findings."
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
