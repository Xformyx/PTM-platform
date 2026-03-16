"""
Dynamic Prompt Generator v2 — generates data-driven prompts for report sections.

Ported from ptm-chromadb-web/python_backend/dynamic_prompt_generator_v2.py.

Features:
  - Statistical analysis of PTM data (enrichment, correlation, distribution)
  - Pathway classification with extensible pathway database
  - Few-shot examples for quantitative data extraction
  - Visualization data generation (volcano, scatter, heatmap)
  - MD file experimental context integration
  - Time-unit auto-detection (hour, min)
"""

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pathway Database
# ---------------------------------------------------------------------------

DEFAULT_PATHWAYS = {
    "Cell-ECM Adhesion": {
        "keywords": ["ctnnd", "lamb", "vcan", "cdh", "jup", "ctnnb", "vcl", "itg", "fn1", "col"],
        "description": "Cell adhesion to extracellular matrix",
    },
    "Cytoskeleton": {
        "keywords": ["mtss", "svil", "actn", "vim", "tuba", "tubb", "map", "arpc", "wasp"],
        "description": "Actin cytoskeleton organization",
    },
    "Metabolism": {
        "keywords": ["pdk", "ldh", "hk", "pfk", "pkm", "eno", "gapdh", "idh", "mdh", "sdh"],
        "description": "Metabolic processes",
    },
    "Signaling": {
        "keywords": ["mapk", "akt", "erk", "jnk", "src", "fak", "pka", "pkc", "camk", "rock"],
        "description": "Signal transduction",
    },
    "Transcription": {
        "keywords": ["myod", "myog", "mef2", "nfat", "nfkb", "stat", "creb", "sp1", "ap1"],
        "description": "Transcription regulation",
    },
    "Translation": {
        "keywords": ["eif", "eef", "rps", "rpl", "mtor", "4ebp", "s6k"],
        "description": "Protein translation",
    },
    "Autophagy": {
        "keywords": ["atg", "lc3", "sqstm", "becn", "ulk", "vps"],
        "description": "Autophagy and protein degradation",
    },
    "Calcium Signaling": {
        "keywords": ["calm", "camk", "atp2a", "ryr", "cacn", "pln"],
        "description": "Calcium-mediated signaling",
    },
}


def classify_gene_pathway(gene_name: str, pathways: Optional[Dict] = None) -> List[str]:
    """Classify a gene into pathways based on name matching."""
    pathways = pathways or DEFAULT_PATHWAYS
    gene_lower = gene_name.lower()
    matched = []
    for pathway_name, info in pathways.items():
        for kw in info["keywords"]:
            if kw in gene_lower:
                matched.append(pathway_name)
                break
    return matched or ["Other"]


# ---------------------------------------------------------------------------
# Statistical Analysis
# ---------------------------------------------------------------------------

@dataclass
class DistributionStats:
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    iqr: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    count: int = 0


def calculate_distribution(values: List[float]) -> DistributionStats:
    """Calculate distribution statistics for a list of values."""
    if not values:
        return DistributionStats()

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean = sum(sorted_vals) / n
    median = sorted_vals[n // 2] if n % 2 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
    variance = sum((x - mean) ** 2 for x in sorted_vals) / max(n - 1, 1)
    std = math.sqrt(variance)
    q1 = sorted_vals[n // 4] if n >= 4 else sorted_vals[0]
    q3 = sorted_vals[3 * n // 4] if n >= 4 else sorted_vals[-1]

    return DistributionStats(
        mean=mean, median=median, std=std, iqr=q3 - q1,
        min_val=sorted_vals[0], max_val=sorted_vals[-1], count=n,
    )


def calculate_correlation(x_vals: List[float], y_vals: List[float]) -> Dict:
    """Calculate Pearson correlation between two value lists."""
    if len(x_vals) < 3 or len(y_vals) < 3 or len(x_vals) != len(y_vals):
        return {"r": 0.0, "p_value": 1.0, "n": 0}

    n = len(x_vals)
    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals)) / (n - 1)
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_vals) / (n - 1))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_vals) / (n - 1))

    if std_x == 0 or std_y == 0:
        return {"r": 0.0, "p_value": 1.0, "n": n}

    r = cov / (std_x * std_y)
    # Approximate p-value using t-distribution
    t_stat = r * math.sqrt((n - 2) / max(1 - r ** 2, 1e-10))
    # Simplified p-value approximation
    p_value = 2 * math.exp(-0.717 * abs(t_stat) - 0.416 * t_stat ** 2) if abs(t_stat) < 10 else 0.0

    return {"r": r, "p_value": max(p_value, 1e-300), "n": n}


def calculate_enrichment(
    pathway_ptms: Dict[str, List], total_ptms: int, total_genes: int = 20000,
) -> Dict[str, Dict]:
    """Calculate pathway enrichment statistics."""
    results = {}
    for pathway, ptms in pathway_ptms.items():
        count = len(ptms)
        if count == 0:
            continue
        percentage = (count / total_ptms * 100) if total_ptms > 0 else 0
        expected = total_ptms * (len(DEFAULT_PATHWAYS.get(pathway, {}).get("keywords", [])) / total_genes)
        fold_enrichment = (count / expected) if expected > 0 else 0

        results[pathway] = {
            "count": count,
            "percentage": percentage,
            "fold_enrichment": fold_enrichment,
            "genes": [p.get("gene", "") for p in ptms[:10]],
        }

    return results


# ---------------------------------------------------------------------------
# PTM Pattern Classification (6-pattern system)
# ---------------------------------------------------------------------------

def classify_ptm_patterns(ptms: List[dict], threshold: float = 0.5) -> Dict[str, List[dict]]:
    """
    Classify PTMs into 6 patterns based on Protein Log2FC vs PTM Log2FC.

    Patterns:
      1A: PTM up, Protein stable/up → Kinase activation
      1B: PTM down, Protein stable/down → Phosphatase activation
      2A: PTM up, Protein down → Compensatory hyperactivation
      2B: PTM down, Protein up → Desensitization
      3A: PTM stable, Protein up → Expression-driven
      3B: PTM stable, Protein down → Degradation-driven
    """
    patterns = {"1A": [], "1B": [], "2A": [], "2B": [], "3A": [], "3B": []}

    for ptm in ptms:
        ptm_fc = float(ptm.get("ptm_relative_log2fc", 0))
        prot_fc = float(ptm.get("protein_log2fc", 0))

        ptm_sig = abs(ptm_fc) >= threshold
        prot_sig = abs(prot_fc) >= threshold

        if ptm_fc > 0 and ptm_sig:
            if prot_fc < -threshold:
                patterns["2A"].append(ptm)
            else:
                patterns["1A"].append(ptm)
        elif ptm_fc < 0 and ptm_sig:
            if prot_fc > threshold:
                patterns["2B"].append(ptm)
            else:
                patterns["1B"].append(ptm)
        elif not ptm_sig:
            if prot_fc > threshold:
                patterns["3A"].append(ptm)
            elif prot_fc < -threshold:
                patterns["3B"].append(ptm)

    return patterns


# ---------------------------------------------------------------------------
# Few-Shot Examples
# ---------------------------------------------------------------------------

FEW_SHOT_QUANTITATIVE = """
**Example of good quantitative data integration:**

"The phosphorylation of ACC1 at Ser79 showed a dramatic 18.5-fold increase (PTM Log2FC = 4.21)
without significant change in protein abundance (Protein Log2FC = 0.03), indicating specific
kinase-mediated activation. This is consistent with AMPK-dependent phosphorylation of ACC1 at
Ser79, which inhibits fatty acid synthesis and promotes fatty acid oxidation [1]. The magnitude
of this change (4.21 log2 units) suggests near-complete phosphorylation of the available ACC1
pool, implying sustained AMPK activation under the experimental conditions."

Note how the example:
1. Includes specific fold-change values with units
2. Compares PTM vs protein changes to infer mechanism
3. Cites literature with reference numbers
4. Interprets the magnitude of change biologically
"""


# ---------------------------------------------------------------------------
# Dynamic Prompt Builder
# ---------------------------------------------------------------------------

class DynamicPromptGenerator:
    """Generates data-driven prompts for report sections using PTM statistics."""

    def __init__(self, ptms: List[dict], experimental_context: Optional[dict] = None):
        self.ptms = ptms
        self.context = experimental_context or {}

        # Classify patterns
        self.patterns = classify_ptm_patterns(ptms)

        # Group by pathway
        self.pathway_ptms: Dict[str, List] = defaultdict(list)
        for ptm in ptms:
            gene = ptm.get("gene", "")
            pathways = classify_gene_pathway(gene)
            for pw in pathways:
                self.pathway_ptms[pw].append(ptm)

        # Statistics
        ptm_fcs = [float(p.get("ptm_relative_log2fc", 0)) for p in ptms]
        prot_fcs = [float(p.get("protein_log2fc", 0)) for p in ptms]

        self.ptm_dist = calculate_distribution(ptm_fcs)
        self.prot_dist = calculate_distribution(prot_fcs)
        self.correlation = calculate_correlation(prot_fcs, ptm_fcs)
        self.enrichment = calculate_enrichment(self.pathway_ptms, len(ptms))

    def get_statistics_context(self) -> str:
        """Generate statistics context string for prompts."""
        lines = [
            "**Statistical Summary:**",
            f"- Total PTMs: {len(self.ptms)}",
            f"- Pattern 1A (Kinase activation): {len(self.patterns['1A'])} PTMs",
            f"- Pattern 1B (Phosphatase activation): {len(self.patterns['1B'])} PTMs",
            f"- Pattern 2A (Compensatory): {len(self.patterns['2A'])} PTMs",
            f"- Pattern 2B (Desensitization): {len(self.patterns['2B'])} PTMs",
            f"- Protein-PTM correlation: r={self.correlation['r']:.3f} (p={self.correlation['p_value']:.2e})",
            f"- PTM Log2FC: median={self.ptm_dist.median:.2f}, IQR={self.ptm_dist.iqr:.2f}",
            f"- Protein Log2FC: median={self.prot_dist.median:.2f}, IQR={self.prot_dist.iqr:.2f}",
        ]

        # Top enriched pathways
        sorted_enrichment = sorted(
            self.enrichment.items(), key=lambda x: x[1]["fold_enrichment"], reverse=True,
        )
        if sorted_enrichment:
            lines.append("\n**Pathway Enrichment:**")
            for pw, stats in sorted_enrichment[:5]:
                lines.append(
                    f"- {pw}: {stats['count']} PTMs "
                    f"({stats['fold_enrichment']:.1f}x enriched, {stats['percentage']:.1f}%)"
                )

        return "\n".join(lines)

    def get_top_ptms_context(self, n: int = 20) -> str:
        """Generate top PTMs context for prompts."""
        # Top activated
        top_activated = sorted(
            self.patterns["1A"],
            key=lambda x: float(x.get("ptm_relative_log2fc", 0)),
            reverse=True,
        )[:n]

        # Top inhibited
        top_inhibited = sorted(
            self.patterns["1B"],
            key=lambda x: float(x.get("ptm_relative_log2fc", 0)),
        )[:n]

        lines = ["**Top Activated PTMs (Pattern 1A):**"]
        for ptm in top_activated[:10]:
            fc = float(ptm.get("ptm_relative_log2fc", 0))
            fold = 2 ** fc
            lines.append(
                f"- {ptm.get('gene', '?')} {ptm.get('position', '?')}: "
                f"PTM Log2FC={fc:.2f} ({fold:,.0f}x), "
                f"Protein Log2FC={float(ptm.get('protein_log2fc', 0)):.3f}"
            )

        lines.append("\n**Top Inhibited PTMs (Pattern 1B):**")
        for ptm in top_inhibited[:10]:
            fc = float(ptm.get("ptm_relative_log2fc", 0))
            fold = 2 ** fc
            lines.append(
                f"- {ptm.get('gene', '?')} {ptm.get('position', '?')}: "
                f"PTM Log2FC={fc:.2f} ({fold:.2f}x), "
                f"Protein Log2FC={float(ptm.get('protein_log2fc', 0)):.3f}"
            )

        return "\n".join(lines)

    def get_few_shot_context(self) -> str:
        """Return few-shot examples for quantitative data integration."""
        return FEW_SHOT_QUANTITATIVE

    def enhance_section_prompt(self, section_type: str, base_prompt: str) -> str:
        """
        Enhance a section prompt with statistical context and few-shot examples.

        Args:
            section_type: Section type (introduction, results, discussion, etc.)
            base_prompt: The base prompt to enhance

        Returns:
            Enhanced prompt with statistics, top PTMs, and few-shot examples.
        """
        enhancements = []

        # Add statistics for all sections
        enhancements.append(self.get_statistics_context())

        # Section-specific enhancements
        if section_type in ("results", "discussion"):
            enhancements.append(self.get_top_ptms_context())
            enhancements.append(self.get_few_shot_context())

        if section_type == "results":
            # Add visualization data summary
            enhancements.append(self._get_visualization_summary())

        enhancement_text = "\n\n".join(enhancements)

        return f"{base_prompt}\n\n{enhancement_text}"

    def _get_visualization_summary(self) -> str:
        """Generate visualization data summary."""
        # Scatter plot quadrant counts
        q1 = len(self.patterns["1A"])
        q2 = len(self.patterns["2A"])
        q3 = len(self.patterns["1B"])
        q4 = len(self.patterns["2B"])

        return (
            f"**Visualization Data:**\n"
            f"- Scatter plot quadrants: Q1(up/up)={q1}, Q2(up/down)={q2}, "
            f"Q3(down/down)={q3}, Q4(down/up)={q4}\n"
            f"- Total PTMs in volcano plot: {len(self.ptms)}"
        )


# ---------------------------------------------------------------------------
# PTM Regulatory Context (ported from ptm_nonptm_network_command v32)
# ---------------------------------------------------------------------------

PTM_REGULATORY_CONTEXTS = {
    "phosphorylation": {
        "regulator_type": "Kinase/Phosphatase",
        "activator": "Kinase",
        "inhibitor": "Phosphatase",
        "pathway_description": "Kinase -> Substrate -> Downstream effector",
        "biological_role": "Signal transduction, enzyme activation/inhibition, protein-protein interactions",
        "temporal_interpretation": "Rapid activation followed by feedback inhibition",
        "network_focus": "Kinase-substrate relationships and signaling cascades",
    },
    "ubiquitylation": {
        "regulator_type": "E3 Ligase/DUB",
        "activator": "E3 Ligase",
        "inhibitor": "DUB (Deubiquitinase)",
        "pathway_description": "E3 Ligase -> Substrate -> Proteasome/Signaling",
        "biological_role": "Protein degradation, signaling regulation, cellular localization, DNA repair",
        "temporal_interpretation": "Protein turnover dynamics and stability regulation",
        "network_focus": "E3 Ligase-substrate relationships and ubiquitin chain type-specific outcomes",
        "chain_types": {
            "K48": "Proteasomal degradation",
            "K63": "Non-proteolytic signaling (NF-kB, DNA damage)",
            "K11": "Cell cycle regulation (APC/C)",
            "mono": "Endocytosis, localization, histone regulation",
        },
    },
    "acetylation": {
        "regulator_type": "HAT/HDAC",
        "activator": "HAT (Histone Acetyltransferase)",
        "inhibitor": "HDAC (Histone Deacetylase)",
        "pathway_description": "HAT -> Substrate -> Chromatin/Metabolic regulation",
        "biological_role": "Chromatin remodeling, transcription regulation, metabolic enzyme regulation",
        "temporal_interpretation": "Epigenetic changes and metabolic adaptation",
        "network_focus": "Acetyltransferase-substrate relationships",
    },
    "methylation": {
        "regulator_type": "Methyltransferase/Demethylase",
        "activator": "Methyltransferase",
        "inhibitor": "Demethylase",
        "pathway_description": "Methyltransferase -> Substrate -> Chromatin/Signaling",
        "biological_role": "Chromatin regulation, protein-protein interactions, signaling modulation",
        "temporal_interpretation": "Epigenetic regulation and signaling fine-tuning",
        "network_focus": "Methyltransferase-substrate relationships",
    },
}


def get_ptm_regulatory_context(ptm_type: str) -> Dict:
    """Return PTM-specific regulatory context for LLM prompts."""
    return PTM_REGULATORY_CONTEXTS.get(ptm_type, PTM_REGULATORY_CONTEXTS["phosphorylation"])


# ---------------------------------------------------------------------------
# v98: Anti-Hallucination Directive Builder
# ---------------------------------------------------------------------------

def build_anti_hallucination_directive(
    protein_names: List[str],
    section_name: str = "this section",
) -> str:
    """
    v98: Build a strong anti-hallucination directive block for LLM prompts.

    This block is inserted at the TOP of every LLM prompt to establish
    data fidelity as the primary constraint before any writing instructions.

    Args:
        protein_names: List of verified protein/gene names from experimental data
        section_name: Name of the section being generated

    Returns:
        Formatted directive string
    """
    if not protein_names:
        return ""

    unique_names = sorted(set(protein_names))
    names_str = ", ".join(unique_names[:50])

    directive = f"""## MANDATORY DATA FIDELITY DIRECTIVE (v98)

**THIS IS THE MOST IMPORTANT INSTRUCTION IN THIS ENTIRE PROMPT.**

You are writing {section_name} based on REAL experimental data. Every protein name,
gene name, modification site, and Log2FC value you mention MUST come from the
VERIFIED DATA sections provided below.

### VERIFIED PROTEIN REGISTRY
The following {len(unique_names)} proteins are confirmed present in the experimental data:
{names_str}

### ABSOLUTE RULES (violation = scientific fraud)
1. **NEVER invent protein names** — if a protein is not in the registry above, do NOT mention it
2. **NEVER fabricate Log2FC values** — every numerical value must come from the data tables below
3. **NEVER use example proteins from your training data** (e.g., GSK3B, YWHAZ, HSP90, ACTB, GAPDH, MYC, TP53, EGFR, AKT1, ERK1/2, JNK, p38) UNLESS they appear in the verified registry above
4. **NEVER write hypothetical examples** like "proteins such as X" or "for example, Y" with invented names
5. **When in doubt, OMIT** — it is better to write fewer proteins correctly than to hallucinate
6. **Cross-check every protein name** you write against the registry before including it

### SELF-CHECK BEFORE SUBMITTING
Before finalizing your response, verify:
- [ ] Every protein name I mentioned appears in the VERIFIED PROTEIN REGISTRY
- [ ] Every Log2FC value I cited comes from the data tables provided
- [ ] I did not use any "well-known" proteins from my training data that are not in this dataset
- [ ] I did not fabricate any numerical values or timepoints
"""
    return directive


# ---------------------------------------------------------------------------
# v98b: Dynamic Writing Example Builder
# ---------------------------------------------------------------------------

def build_dynamic_writing_example(
    results: dict,
    timepoints: list,
    ptm_type: str = "phosphorylation",
) -> str:
    """
    v98b: Build a GOOD EXAMPLE block using ACTUAL data from the current dataset.

    Instead of hardcoded protein names that cause hallucination, this function
    extracts the top proteins from the real data and constructs a writing example
    using those actual proteins.

    Returns:
        Formatted example string using real data, or empty string if no data.
    """
    networks = results.get("networks", {})
    if not networks or not timepoints:
        return ""

    regulatory_context = get_ptm_regulatory_context(ptm_type)

    # Find the first timepoint with data
    first_tp = None
    first_panel = "A"
    top_activated = []
    top_inhibited = []

    for i, tp in enumerate(timepoints):
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue

        active = net.get("active_nodes", [])
        inhibited = net.get("inhibited_nodes", [])

        if active or inhibited:
            first_tp = tp
            first_panel = chr(65 + i)

            active_sorted = sorted(
                [n for n in active if isinstance(n, dict)],
                key=lambda x: abs(x.get("value", x.get("ptm_log2fc", x.get("log2fc", 0)))),
                reverse=True,
            )
            inhibited_sorted = sorted(
                [n for n in inhibited if isinstance(n, dict)],
                key=lambda x: abs(x.get("value", x.get("ptm_log2fc", x.get("log2fc", 0)))),
                reverse=True,
            )

            top_activated = active_sorted[:3]
            top_inhibited = inhibited_sorted[:2]
            break

    if not first_tp or not top_activated:
        return ""

    net = networks.get(first_tp, {})
    n_active = len(net.get("active_nodes", []))
    n_inhibited = len(net.get("inhibited_nodes", []))
    n_nonptm = len(net.get("non_ptm_nodes", []))

    # Format top proteins
    protein_examples = []
    for node in top_activated[:3]:
        gene = node.get("gene", node.get("id", "Unknown"))
        site = node.get("site", "")
        val = node.get("value", node.get("ptm_log2fc", node.get("log2fc", 0)))
        if site:
            protein_examples.append(f"{gene}({site}) exhibited a PTM Log2FC of {val:.2f}")
        else:
            protein_examples.append(f"{gene} exhibited a PTM Log2FC of {val:.2f}")

    example_proteins_text = ", ".join(protein_examples[:2])
    if len(protein_examples) > 2:
        example_proteins_text += f", and {protein_examples[2]}"

    # Build temporal example if multiple timepoints
    temporal_example = ""
    if len(timepoints) >= 2 and top_activated:
        first_gene = top_activated[0].get("gene", "Unknown")
        first_site = top_activated[0].get("site", "")
        first_val = top_activated[0].get("value", top_activated[0].get("ptm_log2fc", 0))

        later_tp = timepoints[-1]
        later_net = networks.get(later_tp, {})
        if isinstance(later_net, dict):
            later_panel = chr(65 + len(timepoints) - 1)
            for node_type in ["active_nodes", "inhibited_nodes"]:
                for node in later_net.get(node_type, []):
                    if isinstance(node, dict) and node.get("gene") == first_gene:
                        later_val = node.get("value", node.get("ptm_log2fc", 0))
                        protein_ref = f"{first_gene}({first_site})" if first_site else first_gene
                        if abs(later_val - first_val) > 0.5:
                            if later_val > first_val:
                                temporal_example = (
                                    f"\n> {protein_ref} showed progressive increase from "
                                    f"PTM Log2FC of {first_val:.2f} at {first_tp} to {later_val:.2f} at {later_tp} "
                                    f"(Figure 1{later_panel}), suggesting sustained {ptm_type} signaling."
                                )
                            else:
                                temporal_example = (
                                    f"\n> In contrast, {protein_ref} showed a shift from "
                                    f"PTM Log2FC of {first_val:.2f} at {first_tp} to {later_val:.2f} at {later_tp} "
                                    f"(Figure 1{later_panel}), suggesting a biphasic regulatory mechanism."
                                )
                        break

    example = f"""## CORRECT WRITING EXAMPLE (Follow this style — uses YOUR actual data)

GOOD EXAMPLE:
> The {ptm_type} signaling network at {first_tp} (Figure 1{first_panel}) revealed {n_active} activated PTMs and {n_inhibited} inhibited PTMs,
> with {n_nonptm} non-PTM proteins forming the interaction network. Among the most strongly modified substrates,
> {example_proteins_text},{temporal_example}
> indicating coordinated activation of multiple signaling nodes.

BAD EXAMPLE (NEVER write like this):
> The MAPK pathway demonstrated a clear temporal profile. At 3h, we observed robust phosphorylation of
> several key substrates, including [list specific substrates and Log2FC values from Figure 1A].
> For example, [Specific substrate] exhibited a PTM Log2FC of [value].
"""
    return example


# ---------------------------------------------------------------------------
# v98: Structured Protein Data Builder for LLM Prompts
# ---------------------------------------------------------------------------

def build_structured_protein_data_for_llm(
    results: dict,
    timepoints: list,
    ptm_type: str = "phosphorylation",
    mode: str = "ptm_only",
    top_n: int = 30,
) -> Tuple[str, List[str], List[float]]:
    """
    v98: Build structured protein data in Markdown table + JSON format for LLM prompts.

    Replaces unstructured text data with clear tabular format that makes it
    harder for the LLM to hallucinate by providing an unambiguous data reference.

    Returns:
        Tuple of (structured_data_block, protein_names, log2fc_values)
    """
    import json as _json

    networks = results.get("networks", {})
    protein_names: List[str] = []
    log2fc_values: List[float] = []

    # Collect all PTM proteins across timepoints
    ptm_data: Dict[str, dict] = {}  # {gene(site): {tp: {ptm_log2fc, protein_log2fc}}}

    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes"]:
            for node in net.get(node_type, []):
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", node.get("id", "Unknown"))
                site = node.get("site", "")
                key = f"{gene}({site})" if site else gene
                ptm_log2fc = node.get("value", node.get("ptm_log2fc", node.get("log2fc", 0)))
                protein_log2fc = node.get("protein_log2fc", 0)

                if key not in ptm_data:
                    ptm_data[key] = {"gene": gene, "site": site}
                ptm_data[key][tp] = {
                    "ptm_log2fc": round(ptm_log2fc, 2),
                    "protein_log2fc": round(protein_log2fc, 2),
                }
                protein_names.append(gene)
                log2fc_values.append(round(ptm_log2fc, 2))
                if protein_log2fc != 0:
                    log2fc_values.append(round(protein_log2fc, 2))

    # Collect Non-PTM proteins
    nonptm_data: Dict[str, dict] = {}
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node in net.get("non_ptm_nodes", []):
            if not isinstance(node, dict):
                continue
            gene = node.get("gene", node.get("id", "Unknown"))
            if not gene or gene == "Unknown":
                continue
            plog2fc = node.get("protein_log2fc", node.get("log2fc", 0))
            if gene not in nonptm_data:
                nonptm_data[gene] = {}
            nonptm_data[gene][tp] = round(plog2fc, 2)
            protein_names.append(gene)
            if plog2fc != 0:
                log2fc_values.append(round(plog2fc, 2))

    if not ptm_data:
        return ("", [], [])

    # Sort PTM proteins by max absolute Log2FC
    sorted_ptms = sorted(
        ptm_data.items(),
        key=lambda x: max(abs(x[1].get(tp, {}).get("ptm_log2fc", 0)) for tp in timepoints if tp in x[1]),
        reverse=True,
    )

    lines = []
    lines.append("## " + "=" * 59)
    lines.append("## VERIFIED EXPERIMENTAL DATA -- STRUCTURED FORMAT (v98)")
    lines.append("## " + "=" * 59)
    lines.append("")
    lines.append("**INSTRUCTION**: The tables below contain ALL verified experimental data.")
    lines.append("You MUST cite protein names and Log2FC values EXACTLY as they appear here.")
    lines.append("Any protein or value NOT in these tables is HALLUCINATED.")
    lines.append("")

    # PTM Protein Table
    lines.append(f"### Table A: Verified {ptm_type.capitalize()} Modification Data")
    header = "| # | Protein | Site |"
    for tp in timepoints:
        header += f" {tp} PTM_Log2FC |"
    header += " Max |PTM_Log2FC| |"
    lines.append(header)

    sep = "|---|---|---|"
    for _ in timepoints:
        sep += "---|"
    sep += "---|"
    lines.append(sep)

    for i, (key, data) in enumerate(sorted_ptms[:top_n], 1):
        gene = data.get("gene", "?")
        site = data.get("site", "")
        row = f"| {i} | **{gene}** | {site} |"
        max_abs = 0
        for tp in timepoints:
            if tp in data and isinstance(data[tp], dict):
                val = data[tp]["ptm_log2fc"]
                row += f" {val:.2f} |"
                if abs(val) > max_abs:
                    max_abs = abs(val)
            else:
                row += " -- |"
        row += f" {max_abs:.2f} |"
        lines.append(row)
    lines.append("")

    # Non-PTM Protein Table (top 20)
    if nonptm_data:
        sorted_nonptm = sorted(
            nonptm_data.items(),
            key=lambda x: max(abs(v) for v in x[1].values()) if x[1] else 0,
            reverse=True,
        )
        lines.append("### Table B: Verified Non-PTM Effector Protein Abundance Data")
        header = "| # | Protein |"
        for tp in timepoints:
            header += f" {tp} Protein_Log2FC |"
        header += " Max |Change| |"
        lines.append(header)

        sep = "|---|---|"
        for _ in timepoints:
            sep += "---|"
        sep += "---|"
        lines.append(sep)

        for i, (gene, tp_data) in enumerate(sorted_nonptm[:20], 1):
            row = f"| {i} | **{gene}** |"
            max_abs = 0
            for tp in timepoints:
                val = tp_data.get(tp, 0)
                row += f" {val:.2f} |"
                if abs(val) > max_abs:
                    max_abs = abs(val)
            row += f" {max_abs:.2f} |"
            lines.append(row)
        lines.append("")

    # JSON protein registry
    unique_proteins = sorted(set(protein_names))
    lines.append("### Verified Protein Name Registry (JSON)")
    lines.append("```json")
    lines.append(_json.dumps({
        "verified_proteins": unique_proteins,
        "total_ptm_proteins": len(ptm_data),
        "total_nonptm_proteins": len(nonptm_data),
        "instruction": "ONLY cite proteins from this list. Any other protein name is HALLUCINATED.",
    }, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## " + "=" * 59)
    lines.append("")

    return ("\n".join(lines), unique_proteins, log2fc_values)


# ---------------------------------------------------------------------------
# GAP A: 5 Auxiliary Data Blocks for Results Prompt
# Ported from ptm_nonptm_network_command.py
# ---------------------------------------------------------------------------

def build_ptm_data_summary(parsed_ptms: List[dict], ptm_type: str = "phosphorylation") -> str:
    """
    GAP A-1: Build a concise PTM data summary block.
    Summarizes total counts, up/down regulation, top modified proteins.
    """
    if not parsed_ptms:
        return ""

    total = len(parsed_ptms)
    up = sum(1 for p in parsed_ptms if float(p.get("ptm_relative_log2fc", 0)) > 0)
    down = total - up

    # Top 5 by absolute FC
    sorted_ptms = sorted(parsed_ptms, key=lambda x: abs(float(x.get("ptm_relative_log2fc", 0))), reverse=True)

    lines = [
        "## PTM DATA SUMMARY",
        f"- **Total {ptm_type} sites**: {total}",
        f"- **Upregulated**: {up} ({up/total*100:.1f}%)" if total > 0 else "",
        f"- **Downregulated**: {down} ({down/total*100:.1f}%)" if total > 0 else "",
        "",
        "**Top 5 Most Changed PTMs:**",
    ]
    for i, p in enumerate(sorted_ptms[:5], 1):
        gene = p.get("gene", "?")
        pos = p.get("position", "?")
        ptm_fc = float(p.get("ptm_relative_log2fc", 0))
        prot_fc = float(p.get("protein_log2fc", 0))
        direction = "UP" if ptm_fc > 0 else "DOWN"
        lines.append(
            f"  {i}. **{gene}-{pos}**: PTM Log2FC={ptm_fc:.2f} ({direction}), "
            f"Protein Log2FC={prot_fc:.2f}"
        )
    lines.append("")
    return "\n".join(lines)


def build_nonptm_temporal_analysis(
    network_results: dict, timepoints: list, ptm_type: str = "phosphorylation"
) -> str:
    """
    GAP A-2: Build Non-PTM temporal analysis block.
    Shows how Non-PTM effector proteins change across timepoints.
    """
    # Support both 'networks' (legacy) and 'timepoint_results' (network_node.py output)
    networks = network_results.get("networks", {})
    tp_results = network_results.get("timepoint_results", {})
    source = networks or tp_results
    if not source or not timepoints:
        return ""

    # Collect Non-PTM proteins across timepoints
    nonptm_temporal: Dict[str, Dict[str, float]] = {}
    for tp in timepoints:
        net = source.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node in net.get("non_ptm_nodes", []):
            if not isinstance(node, dict):
                continue
            gene = node.get("gene", node.get("id", ""))
            if not gene:
                continue
            plog2fc = float(node.get("protein_log2fc", node.get("log2fc", 0)))
            if gene not in nonptm_temporal:
                nonptm_temporal[gene] = {}
            nonptm_temporal[gene][tp] = plog2fc

    if not nonptm_temporal:
        return ""

    # Sort by max absolute change
    sorted_nonptm = sorted(
        nonptm_temporal.items(),
        key=lambda x: max(abs(v) for v in x[1].values()),
        reverse=True,
    )

    lines = [
        "## NON-PTM EFFECTOR TEMPORAL ANALYSIS",
        f"Non-PTM proteins are interaction partners that do not carry {ptm_type} "
        "modifications but show significant protein abundance changes.",
        "",
    ]

    # Table header
    header = "| # | Protein |"
    for tp in timepoints:
        header += f" {tp} Prot_Log2FC |"
    header += " Trend |"
    lines.append(header)

    sep = "|---|---|"
    for _ in timepoints:
        sep += "---|"
    sep += "---|"
    lines.append(sep)

    for i, (gene, tp_data) in enumerate(sorted_nonptm[:15], 1):
        row = f"| {i} | **{gene}** |"
        values = []
        for tp in timepoints:
            val = tp_data.get(tp, 0)
            row += f" {val:.2f} |"
            values.append(val)
        # Determine trend
        if len(values) >= 2:
            if values[-1] > values[0] + 0.3:
                trend = "INCREASING"
            elif values[-1] < values[0] - 0.3:
                trend = "DECREASING"
            else:
                trend = "STABLE"
        else:
            trend = "N/A"
        row += f" {trend} |"
        lines.append(row)

    lines.append("")
    return "\n".join(lines)


def build_ptm_protein_timelag_analysis(
    network_results: dict, timepoints: list, ptm_type: str = "phosphorylation"
) -> str:
    """
    GAP A-3: Build PTM vs Protein time-lag analysis.
    Identifies cases where PTM change precedes or follows protein abundance change.
    """
    # Support both 'networks' (legacy) and 'timepoint_results' (network_node.py output)
    networks = network_results.get("networks", {})
    tp_results = network_results.get("timepoint_results", {})
    source = networks or tp_results
    if not source or len(timepoints) < 2:
        return ""

    # Collect PTM proteins across timepoints
    ptm_temporal: Dict[str, Dict[str, dict]] = {}
    for tp in timepoints:
        net = source.get(tp, {})
        if not isinstance(net, dict):
            continue
        # Support both legacy (active_nodes/inhibited_nodes) and network_node.py (ptm_nodes)
        all_ptm_nodes = []
        for node_type in ["active_nodes", "inhibited_nodes"]:
            all_ptm_nodes.extend(net.get(node_type, []))
        if not all_ptm_nodes:
            all_ptm_nodes = net.get("ptm_nodes", [])
        for node in all_ptm_nodes:
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", node.get("id", ""))
                site = node.get("site", node.get("position", ""))
                key = f"{gene}({site})" if site else gene
                ptm_fc = float(node.get("value", node.get("ptm_log2fc", node.get("ptm_relative_log2fc", 0))))
                prot_fc = float(node.get("protein_log2fc", 0))
                if key not in ptm_temporal:
                    ptm_temporal[key] = {"gene": gene, "site": site}
                ptm_temporal[key][tp] = {"ptm": ptm_fc, "prot": prot_fc}

    if not ptm_temporal:
        return ""

    # Analyze time-lag patterns
    timelag_cases = []
    for key, data in ptm_temporal.items():
        gene = data.get("gene", "?")
        site = data.get("site", "")
        tp_values = [(tp, data[tp]) for tp in timepoints if tp in data and isinstance(data[tp], dict)]
        if len(tp_values) < 2:
            continue

        # Check if PTM change precedes protein change
        first_ptm_sig = None
        first_prot_sig = None
        for tp, vals in tp_values:
            if first_ptm_sig is None and abs(vals["ptm"]) > 0.5:
                first_ptm_sig = tp
            if first_prot_sig is None and abs(vals["prot"]) > 0.5:
                first_prot_sig = tp

        if first_ptm_sig and first_prot_sig:
            ptm_idx = timepoints.index(first_ptm_sig) if first_ptm_sig in timepoints else -1
            prot_idx = timepoints.index(first_prot_sig) if first_prot_sig in timepoints else -1
            if ptm_idx >= 0 and prot_idx >= 0 and ptm_idx != prot_idx:
                if ptm_idx < prot_idx:
                    pattern = "PTM-first"
                    explanation = f"{gene} {ptm_type} at {site} detected at {first_ptm_sig}, protein change at {first_prot_sig}"
                else:
                    pattern = "Protein-first"
                    explanation = f"{gene} protein change at {first_prot_sig}, {ptm_type} at {site} detected at {first_ptm_sig}"
                timelag_cases.append({
                    "gene": gene, "site": site, "pattern": pattern,
                    "ptm_tp": first_ptm_sig, "prot_tp": first_prot_sig,
                    "explanation": explanation,
                })

    if not timelag_cases:
        return ""

    lines = [
        "## PTM-PROTEIN TIME-LAG ANALYSIS",
        "The following proteins show a temporal offset between PTM modification "
        "and protein abundance change, suggesting causal regulatory relationships.",
        "",
        "| # | Protein | Site | Pattern | PTM First Detected | Protein First Changed | Interpretation |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, case in enumerate(timelag_cases[:15], 1):
        lines.append(
            f"| {i} | **{case['gene']}** | {case['site']} | {case['pattern']} | "
            f"{case['ptm_tp']} | {case['prot_tp']} | {case['explanation'][:80]} |"
        )
    lines.append("")

    ptm_first = sum(1 for c in timelag_cases if c["pattern"] == "PTM-first")
    prot_first = len(timelag_cases) - ptm_first
    lines.append(
        f"**Summary**: {ptm_first} PTM-first cases, {prot_first} Protein-first cases. "
        f"PTM-first cases suggest kinase/phosphatase-driven regulation; "
        f"Protein-first cases suggest expression-driven or degradation-mediated changes."
    )
    lines.append("")
    return "\n".join(lines)


def build_pathway_context_for_llm(
    parsed_ptms: List[dict], pathways: Optional[Dict] = None
) -> str:
    """
    GAP A-4: Build pathway context block for LLM.
    Groups PTMs by pathway and provides biological context.
    """
    pathways = pathways or DEFAULT_PATHWAYS
    if not parsed_ptms:
        return ""

    pathway_ptms: Dict[str, List[dict]] = defaultdict(list)
    for ptm in parsed_ptms:
        gene = ptm.get("gene", "")
        matched = classify_gene_pathway(gene, pathways)
        for pw in matched:
            pathway_ptms[pw].append(ptm)

    if not pathway_ptms:
        return ""

    # Sort by count
    sorted_pathways = sorted(pathway_ptms.items(), key=lambda x: len(x[1]), reverse=True)

    lines = [
        "## PATHWAY CONTEXT FOR PTM INTERPRETATION",
        "The following pathway groupings provide biological context for interpreting PTM changes.",
        "",
    ]

    for pw_name, ptms in sorted_pathways[:8]:
        desc = pathways.get(pw_name, {}).get("description", "")
        up = sum(1 for p in ptms if float(p.get("ptm_relative_log2fc", 0)) > 0)
        down = len(ptms) - up
        top_genes = sorted(ptms, key=lambda x: abs(float(x.get("ptm_relative_log2fc", 0))), reverse=True)
        gene_list = ", ".join(
            f"{p['gene']}-{p.get('position', '?')}(FC={float(p.get('ptm_relative_log2fc', 0)):.2f})"
            for p in top_genes[:5]
        )
        lines.append(f"### {pw_name} ({len(ptms)} PTMs: {up} up, {down} down)")
        if desc:
            lines.append(f"*{desc}*")
        lines.append(f"Key members: {gene_list}")
        lines.append("")

    return "\n".join(lines)


def build_signal_propagation_json(
    network_results: dict, timepoints: list, ptm_type: str = "phosphorylation"
) -> str:
    """
    GAP A-5: Build signal propagation JSON block.
    Provides a structured timeline of signaling events for LLM interpretation.
    """
    import json as _json

    # Support both 'networks' (legacy) and 'timepoint_results' (network_node.py output)
    networks = network_results.get("networks", {})
    tp_results = network_results.get("timepoint_results", {})
    source = networks or tp_results
    if not source or not timepoints:
        return ""

    propagation = {"ptm_type": ptm_type, "timepoints": [], "propagation_events": []}

    prev_active_genes = set()
    for tp in timepoints:
        net = source.get(tp, {})
        if not isinstance(net, dict):
            continue

        # Support both key formats: active_nodes (legacy) and ptm_nodes (network_node.py)
        active_nodes = net.get("active_nodes", [])
        if not active_nodes:
            # From network_node.py: ptm_nodes with positive FC are active
            for n in net.get("ptm_nodes", []):
                if isinstance(n, dict) and n.get("ptm_relative_log2fc", 0) > 0:
                    active_nodes.append(n)
        inhibited_nodes = net.get("inhibited_nodes", [])
        if not inhibited_nodes:
            for n in net.get("ptm_nodes", []):
                if isinstance(n, dict) and n.get("ptm_relative_log2fc", 0) < 0:
                    inhibited_nodes.append(n)
        nonptm_nodes = net.get("non_ptm_nodes", [])

        active_genes = set()
        for n in active_nodes:
            if isinstance(n, dict):
                active_genes.add(n.get("gene", n.get("id", "")))

        # New activations at this timepoint
        new_activations = active_genes - prev_active_genes
        lost_activations = prev_active_genes - active_genes

        tp_data = {
            "timepoint": tp,
            "n_active": len(active_nodes),
            "n_inhibited": len(inhibited_nodes),
            "n_nonptm": len(nonptm_nodes),
            "new_activations": sorted(new_activations)[:10],
            "lost_activations": sorted(lost_activations)[:10],
        }
        propagation["timepoints"].append(tp_data)

        if prev_active_genes and new_activations:
            propagation["propagation_events"].append({
                "from_tp": timepoints[timepoints.index(tp) - 1] if timepoints.index(tp) > 0 else tp,
                "to_tp": tp,
                "new_signals": sorted(new_activations)[:5],
                "interpretation": f"Signal propagated to {len(new_activations)} new proteins at {tp}",
            })

        prev_active_genes = active_genes

    if not propagation["timepoints"]:
        return ""

    lines = [
        "## SIGNAL PROPAGATION TIMELINE (JSON)",
        "Use this structured timeline to describe how signaling events propagate across timepoints.",
        "",
        "```json",
        _json.dumps(propagation, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GAP G: Condition Display Name Formatting
# ---------------------------------------------------------------------------

def format_condition_display_name(condition: str) -> str:
    """
    GAP G: Convert raw condition strings to human-readable display names.
    Examples:
        'ECM_EPS_2min_vs_Control' -> 'ECM EPS 2 min vs Control'
        'kbsi_af_5min' -> 'KBSI AF 5 min'
        'treatment_6h_vs_ctrl' -> 'Treatment 6 h vs Ctrl'
    """
    if not condition:
        return condition

    import re as _re

    # Replace underscores with spaces
    name = condition.replace("_", " ")

    # Add space between number and unit (e.g., '2min' -> '2 min', '6h' -> '6 h')
    name = _re.sub(r'(\d+)(min|h|sec|hr|hour|s)\b', r'\1 \2', name, flags=_re.IGNORECASE)

    # Capitalize first letter of each word, but keep known abbreviations uppercase
    words = name.split()
    formatted = []
    upper_abbreviations = {"ecm", "eps", "kbsi", "af", "ctrl", "ko", "wt", "het"}
    lower_keep = {"vs", "min", "h", "sec", "hr", "hour", "s"}
    for w in words:
        wl = w.lower()
        if wl in lower_keep:
            formatted.append(wl)
        elif wl in upper_abbreviations:
            formatted.append(w.upper())
        elif _re.match(r'^\d+$', w):
            formatted.append(w)  # keep numbers as-is
        else:
            formatted.append(w.capitalize() if not w[0].isupper() else w)

    return " ".join(formatted)


# ---------------------------------------------------------------------------
# v98: Structured Cross-Talk Data Builder for LLM Prompts
# ---------------------------------------------------------------------------

def build_structured_crosstalk_data_for_llm(
    crosstalk_data: dict,
) -> Tuple[str, List[str], List[float]]:
    """
    v98: Build structured Cross-Talk data in Markdown table + JSON format.

    Converts crosstalk_data dict into clear tabular format for LLM prompts.

    Returns:
        Tuple of (structured_data_block, protein_names, log2fc_values)
    """
    import json as _json

    if not crosstalk_data:
        return ("", [], [])

    p_type = crosstalk_data.get("primary_ptm_type", "phosphorylation").capitalize()
    s_type = crosstalk_data.get("secondary_ptm_type", "ubiquitylation").capitalize()

    protein_names: List[str] = []
    log2fc_values: List[float] = []

    lines = []
    lines.append("## " + "=" * 59)
    lines.append("## VERIFIED CROSS-TALK DATA -- STRUCTURED FORMAT (v98)")
    lines.append("## " + "=" * 59)
    lines.append("")
    lines.append("**INSTRUCTION**: The tables below contain ALL verified dual-PTM protein data.")
    lines.append("You MUST cite protein names and Log2FC values EXACTLY as they appear here.")
    lines.append("Any protein or value NOT in these tables is HALLUCINATED.")
    lines.append("")

    # Dual-PTM Protein Table
    dual_ptms = crosstalk_data.get("dual_ptm_proteins", [])
    if dual_ptms:
        all_tps: set = set()
        for dp in dual_ptms:
            all_tps.update(dp.get("temporal_comparison", {}).keys())
        sorted_tps = sorted(all_tps)

        lines.append(f"### Table C: Verified Dual-PTM Protein Data ({p_type} x {s_type})")
        header = "| # | Protein | Pattern | Concordance |"
        for tp in sorted_tps:
            header += f" {tp} {p_type[:4]}_Log2FC | {tp} {s_type[:4]}_Log2FC | {tp} Status |"
        lines.append(header)

        sep = "|---|---|---|---|"
        for _ in sorted_tps:
            sep += "---|---|---|"
        lines.append(sep)

        for i, dp in enumerate(dual_ptms[:20], 1):
            gene = dp.get("gene", "?")
            protein_names.append(gene)
            pattern = dp.get("pattern", "mixed").upper()
            conc_ratio = dp.get("concordant_ratio", 0)
            row = f"| {i} | **{gene}** | {pattern} | {conc_ratio:.0%} |"

            for tp in sorted_tps:
                comp = dp.get("temporal_comparison", {}).get(tp, {})
                p_val = comp.get("primary_ptm_log2fc", 0)
                s_val = comp.get("secondary_ptm_log2fc", 0)
                log2fc_values.extend([round(p_val, 2), round(s_val, 2)])

                if comp.get("concordant") is True:
                    status = "CONC"
                elif comp.get("concordant") is False:
                    status = "DISC"
                else:
                    status = "NEUT"
                row += f" {p_val:.2f} | {s_val:.2f} | {status} |"
            lines.append(row)
        lines.append("")

    # Shared Non-PTM Interactors
    shared_nonptm = crosstalk_data.get("shared_nonptm", [])
    if shared_nonptm:
        protein_names.extend(shared_nonptm[:30])
        lines.append("### Verified Shared Non-PTM Interactors")
        lines.append(f"| # | Protein | Present in {p_type} | Present in {s_type} |")
        lines.append("|---|---|---|---|")
        for i, gene in enumerate(shared_nonptm[:30], 1):
            lines.append(f"| {i} | **{gene}** | Yes | Yes |")
        lines.append("")

    # Sequential Gating Events
    gating = crosstalk_data.get("sequential_gating", [])
    if gating:
        lines.append("### Verified Sequential Gating Events")
        lines.append("| # | Protein | Leading PTM | Lagging PTM | Time Lag (min) | Mechanism |")
        lines.append("|---|---|---|---|---|---|")
        for i, gate in enumerate(gating[:15], 1):
            gene = gate.get("gene", "?")
            protein_names.append(gene)
            lines.append(
                f"| {i} | **{gene}** | {gate.get('leading_ptm', '?')} at {gate.get('leading_first_tp', '?')} | "
                f"{gate.get('lagging_ptm', '?')} at {gate.get('lagging_first_tp', '?')} | "
                f"{gate.get('time_lag_minutes', 0):.0f} | {gate.get('mechanism_hint', '?')[:50]} |"
            )
        lines.append("")

    # JSON protein registry
    unique_proteins = sorted(set(protein_names))
    lines.append("### Verified Protein Name Registry (JSON)")
    lines.append("```json")
    lines.append(_json.dumps({
        "verified_dual_ptm_proteins": [dp.get("gene", "") for dp in dual_ptms],
        "verified_shared_nonptm": shared_nonptm[:30],
        "verified_gating_proteins": [g.get("gene", "") for g in gating],
        "all_verified_proteins": unique_proteins,
        "instruction": "ONLY cite proteins from this list. Any other protein name is HALLUCINATED.",
    }, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## " + "=" * 59)
    lines.append("")

    return ("\n".join(lines), unique_proteins, log2fc_values)
