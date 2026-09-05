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
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
      1A: PTM up, Protein stable/up → PTM-increase dominant
      1B: PTM down, Protein stable/down → PTM-decrease dominant
      2A: PTM up, Protein down → PTM/protein divergence (increase/decrease)
      2B: PTM down, Protein up → PTM/protein divergence (decrease/increase)
      3A: PTM stable, Protein up → protein-abundance dominant increase
      3B: PTM stable, Protein down → protein-abundance dominant decrease
    """
    patterns = {"1A": [], "1B": [], "2A": [], "2B": [], "3A": [], "3B": []}

    for ptm in ptms:
        if ptm.get("conventional_log2fc_na") or ptm.get("control_pseudocount_used") or ptm.get("activity_class") == "de_novo":
            continue
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


def _is_denovo_representation(row: Mapping[str, Any]) -> bool:
    """Return whether a row uses the non-conventional de novo representation.

    Conventional/pseudocount PTM log2FC is not quantitative fold-change data and
    must not enter legacy ranking, distribution, or fold-multiple prompt blocks.
    De novo detection evidence is supplied separately by the P5 packet.
    """
    return bool(
        row.get("conventional_log2fc_na")
        or row.get("Conventional_Log2FC_NA")
        or row.get("control_pseudocount_used")
        or row.get("Control_Pseudocount_Used")
        or str(row.get("activity_class") or row.get("Activity_Class") or "").strip().lower().startswith("de_novo")
    )


# ---------------------------------------------------------------------------
# Few-Shot Examples
# ---------------------------------------------------------------------------

FEW_SHOT_QUANTITATIVE = """
**Example of good quantitative data integration (STYLE ONLY — do NOT use these proteins/sites):**

"The protein-abundance-adjusted PTM signal at [Gene]-[Site] changed by PTM Log2FC = Y,
whereas protein abundance changed by Protein Log2FC = Z. This measured PTM–protein contrast
prioritizes a site-level regulatory hypothesis, but does not establish occupancy, stoichiometry,
an exact upstream kinase, or a causal mechanism. The observed pattern can be compared with
the cited literature model and followed by a discriminating measurement."

CRITICAL: The above is a STYLE template. You MUST use ONLY proteins and PTM sites from the
actual data provided in this prompt. Never mention ACC1, Ser79, AMPK, MAPK, or any other
example proteins from prompt templates — they are placeholders for illustration only.

Note how the style:
1. Includes specific measured log2FC values with units when the feature is conventionally quantified
2. Compares PTM vs protein changes to prioritize a hypothesis, not to infer mechanism
3. Cites literature with reference numbers
4. Interprets the magnitude of change biologically
"""


# ---------------------------------------------------------------------------
# Dynamic Prompt Builder
# ---------------------------------------------------------------------------

class DynamicPromptGenerator:
    """Generates data-driven prompts for report sections using PTM statistics."""

    def __init__(self, ptms: List[dict], experimental_context: Optional[dict] = None):
        self.denovo_count = sum(1 for ptm in ptms if _is_denovo_representation(ptm))
        self.ptms = [ptm for ptm in ptms if not _is_denovo_representation(ptm)]
        self.context = experimental_context or {}

        # Classify patterns
        self.patterns = classify_ptm_patterns(self.ptms)

        # Group by pathway
        self.pathway_ptms: Dict[str, List] = defaultdict(list)
        for ptm in self.ptms:
            gene = ptm.get("gene", "")
            pathways = classify_gene_pathway(gene)
            for pw in pathways:
                self.pathway_ptms[pw].append(ptm)

        # Statistics
        ptm_fcs = [float(p.get("ptm_relative_log2fc", 0)) for p in self.ptms]
        prot_fcs = [float(p.get("protein_log2fc", 0)) for p in self.ptms]

        self.ptm_dist = calculate_distribution(ptm_fcs)
        self.prot_dist = calculate_distribution(prot_fcs)
        self.correlation = calculate_correlation(prot_fcs, ptm_fcs)
        self.enrichment = calculate_enrichment(self.pathway_ptms, len(self.ptms))

    def get_statistics_context(self) -> str:
        """Generate statistics context string for prompts."""
        lines = [
            "**Statistical Summary:**",
            f"- Conventionally quantified PTMs: {len(self.ptms)}",
            f"- De novo detection-representation rows (reported separately): {self.denovo_count}",
            f"- Pattern 1A (higher protein-abundance-adjusted PTM signal): {len(self.patterns['1A'])} PTMs",
            f"- Pattern 1B (lower protein-abundance-adjusted PTM signal): {len(self.patterns['1B'])} PTMs",
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
            lines.append("\n**Descriptive pathway-category counts (not statistical enrichment):**")
            for pw, stats in sorted_enrichment[:5]:
                lines.append(
                    f"- {pw}: {stats['count']} PTMs "
                    f"({stats['percentage']:.1f}% of this descriptive classification set)"
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

        lines = ["**Top higher PTM signals (Pattern 1A, conventionally quantified only):**"]
        for ptm in top_activated[:10]:
            fc = float(ptm.get("ptm_relative_log2fc", 0))
            lines.append(
                f"- {ptm.get('gene', '?')} {ptm.get('position', '?')}: "
                f"protein-abundance-adjusted PTM Log2FC={fc:.2f}, "
                f"Protein Log2FC={float(ptm.get('protein_log2fc', 0)):.3f}"
            )

        lines.append("\n**Top lower PTM signals (Pattern 1B, conventionally quantified only):**")
        for ptm in top_inhibited[:10]:
            fc = float(ptm.get("ptm_relative_log2fc", 0))
            lines.append(
                f"- {ptm.get('gene', '?')} {ptm.get('position', '?')}: "
                f"protein-abundance-adjusted PTM Log2FC={fc:.2f}, "
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
    v98c: Build a data fidelity guide block for LLM prompts.

    This block is inserted at the TOP of every LLM prompt to establish
    data fidelity as the primary constraint before any writing instructions.

    v98c: Rewritten with positive, encouraging tone to promote rich and
    detailed writing while maintaining data accuracy. Removes threatening
    language that caused LLM to produce overly cautious, thin output.

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

    directive = f"""## DATA FIDELITY GUIDE (v98c)

You are writing {section_name} based on real experimental data. Use the protein names
and Log2FC values from the VERIFIED DATA sections below to write a comprehensive,
detailed, and publication-quality analysis.

### VERIFIED PROTEIN REGISTRY ({len(unique_names)} proteins in this dataset)
{names_str}

### DATA USAGE GUIDELINES
1. **Use proteins from the registry above** — reference specific protein names and their Log2FC values from the data tables
2. **Cite actual Log2FC values** from the data tables when discussing specific proteins
3. **Prefer proteins from this dataset** over well-known examples from general knowledge (e.g., avoid GSK3B, YWHAZ, HSP90, ACTB, GAPDH unless they appear in the registry above)
4. **NEVER use example proteins from prompt templates** — any proteins/sites in examples (e.g., ACC1, Ser79, MAPK3, AMPK) are for style illustration only. Use ONLY proteins from the VERIFIED PROTEIN REGISTRY above.
5. **Write concretely** — instead of "proteins such as X", name the actual proteins from the data
6. **Interpret evidence first** — distinguish a measured observation, a computational candidate context, cited external biological context, and a testable hypothesis. Rich interpretation is welcome only when this evidence class is explicit.
7. **Preserve the claim ceiling** — a PTM/protein contrast, temporal profile, local co-membership, motif, pathway membership, or network connector does not alone establish direct regulation, kinase activity, biological priority, pathway placement, or causality.

### NON-PTM / PTM SIGNALING INTERPRETATION GUIDELINES
When discussing Non-PTM effector proteins alongside PTM-modified proteins:
1. **Report layers separately** — describe PTM and Non-PTM trajectories as measured observations unless an eligible, persisted cross-layer evidence record explicitly supports a more limited statement.
2. **Do not assign directionality** — independent PTM and protein timing cannot establish upstream/downstream order, feedback, direct interaction, transcriptional regulation, or stable-complex formation.
3. **Use pathways as cited context** — literature or pathway membership may frame an observation, but may not convert it into an Order-specific edge, regulatory role, or direct relationship.
4. **Describe sampled-timepoint profiles** — early, intermediate, late, transient, and sustained are profile labels, not mechanistic stages or causal sequence labels.
5. **State hypotheses conditionally** — proposed validation may test a hypothesis, but do not present perturbation outcomes, kinase action, or functional effects as current findings.

### WRITING QUALITY EXPECTATIONS
- Write at the level of a peer-reviewed journal article (e.g., Molecular Cell, Cell Reports)
- Each paragraph should contain 3-6 precise sentences with data references where relevant
- Provide biological context only at its supported level: measured data, computational candidate context, traceable cited context, or testable hypothesis
- State what a result does and does not establish; do not compensate for an unavailable layer by inventing a pathway role or mechanism
- Large conventional Log2FC values remain measured contrasts and must not determine biological priority, mechanistic importance, direct regulatory strength, or visual/narrative prominence by themselves
- Prefer compact evidence-rich synthesis over repeated mechanistic speculation
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
    observed_nodes = []

    for i, tp in enumerate(timepoints):
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue

        active = net.get("active_nodes", [])
        inhibited = net.get("inhibited_nodes", [])

        if active or inhibited:
            first_tp = tp
            first_panel = chr(65 + i)

            observed_nodes = sorted(
                [n for n in [*active, *inhibited] if isinstance(n, dict)],
                key=lambda x: (str(x.get("gene", x.get("id", ""))).upper(), str(x.get("site", ""))),
            )[:3]
            break

    if not first_tp or not observed_nodes:
        return ""

    net = networks.get(first_tp, {})
    n_active = len(net.get("active_nodes", []))
    n_inhibited = len(net.get("inhibited_nodes", []))
    n_nonptm = len(net.get("non_ptm_nodes", []))

    # Format top proteins
    protein_examples = []
    for node in observed_nodes:
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
    if len(timepoints) >= 2 and observed_nodes:
        first_gene = observed_nodes[0].get("gene", "Unknown")
        first_site = observed_nodes[0].get("site", "")
        first_val = observed_nodes[0].get("value", observed_nodes[0].get("ptm_log2fc", 0))

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
                            temporal_example = (
                                f"\n> {protein_ref} changed from a measured PTM Log2FC of {first_val:.2f} "
                                f"at {first_tp} to {later_val:.2f} at {later_tp}. This is a sampled-timepoint "
                                "profile observation; it does not by itself assign a regulatory mechanism, "
                                "pathway position, or causal order."
                            )
                        break

    example = f"""## EVIDENCE-FIRST WRITING EXAMPLE (Use this style — uses YOUR actual data)

GOOD EXAMPLE:
> At {first_tp}, the network display contains {n_active} PTM nodes with higher measured abundance,
> {n_inhibited} with lower measured abundance, and {n_nonptm} Non-PTM observations. Illustrative
> observed sites include {example_proteins_text}. These values are measured contrasts, not a ranking
> of biological priority and not evidence of direct regulation or catalytic activity.{temporal_example}

BAD EXAMPLE (NEVER write this):
> The most strongly modified substrate proves a pathway switch, drives a cascade, or confirms kinase activation.
> Do not rank sites by raw contrast, assign a pathway mechanism from local co-membership, or copy placeholder
> proteins from prompts. Use only actual data and name the evidence class for every interpretation.
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
        key=lambda x: max(
            (abs(x[1].get(tp, {}).get("ptm_log2fc", 0)) for tp in timepoints if tp in x[1]),
            default=0,
        ),
        reverse=True,
    )

    lines = []
    lines.append("## ═══════════════════════════════════════════════════════════")
    lines.append("## 📊 VERIFIED EXPERIMENTAL DATA — STRUCTURED FORMAT (v98)")
    lines.append("## ═══════════════════════════════════════════════════════════")
    lines.append("")
    lines.append("**INSTRUCTION**: The tables below contain ALL verified experimental data.")
    lines.append("You MUST cite protein names and Log2FC values EXACTLY as they appear here.")
    lines.append("Any protein or value NOT in these tables is HALLUCINATED.")
    lines.append("")

    # PTM Protein Table (with both PTM_Log2FC and Prot_Log2FC per timepoint)
    lines.append(f"### Table A: Verified {ptm_type.capitalize()} Modification Data")
    header = "| # | Protein | Site |"
    for tp in timepoints:
        header += f" {tp} PTM_Log2FC | {tp} Prot_Log2FC |"
    header += " Max |PTM_Log2FC| |"
    lines.append(header)

    sep = "|---|---|---|"
    for _ in timepoints:
        sep += "---|---|"  # two columns per timepoint
    sep += "---|"
    lines.append(sep)

    for i, (key, data) in enumerate(sorted_ptms[:top_n], 1):
        gene = data.get("gene", "?")
        site = data.get("site", "")
        row = f"| {i} | **{gene}** | {site} |"
        max_abs = 0
        for tp in timepoints:
            if tp in data and isinstance(data[tp], dict):
                ptm_val = data[tp]["ptm_log2fc"]
                prot_val = data[tp].get("protein_log2fc", 0)
                row += f" {ptm_val:.2f} | {prot_val:.2f} |"
                if abs(ptm_val) > max_abs:
                    max_abs = abs(ptm_val)
            else:
                row += " \u2014 | \u2014 |"
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
    lines.append("## ═══════════════════════════════════════════════════════════")
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

    from ptm_shared.de_novo_representation import (
        format_denovo_prompt_line,
        is_de_novo_representation,
    )

    quantified = [p for p in parsed_ptms if not is_de_novo_representation(p)]
    up = sum(1 for p in quantified if float(p.get("ptm_relative_log2fc", 0) or 0) > 0)
    down = sum(1 for p in quantified if float(p.get("ptm_relative_log2fc", 0) or 0) < 0)
    denovo_n = total - len(quantified)

    def _rank(p):
        score = p.get("ranking_score")
        if score not in (None, ""):
            try:
                return abs(float(score))
            except (TypeError, ValueError):
                pass
        if is_de_novo_representation(p):
            return 0.0
        return abs(float(p.get("ptm_relative_log2fc", 0) or 0))

    sorted_ptms = sorted(parsed_ptms, key=_rank, reverse=True)

    lines = [
        "## PTM DATA SUMMARY",
        f"- **Total {ptm_type} sites**: {total}",
        f"- **Upregulated (quantified)**: {up} ({up/total*100:.1f}%)" if total > 0 else "",
        f"- **Downregulated (quantified)**: {down} ({down/total*100:.1f}%)" if total > 0 else "",
        f"- **De novo (Log2FC=NA)**: {denovo_n}",
        "",
        "**Top 5 ranked PTMs (de novo uses LOD-relative rank, not pseudo-Log2FC):**",
    ]
    for i, p in enumerate(sorted_ptms[:5], 1):
        gene = p.get("gene", "?")
        pos = p.get("position", "?")
        if is_de_novo_representation(p):
            lines.append(f"  {i}. {format_denovo_prompt_line(p).strip()}")
            continue
        ptm_fc = float(p.get("ptm_relative_log2fc", 0))
        prot_fc = float(p.get("protein_log2fc", 0))
        direction = "UP" if ptm_fc > 0 else "DOWN"
        lines.append(
            f"  {i}. **{gene}-{pos}**: PTM Log2FC={ptm_fc:.2f} ({direction}), "
            f"Protein Log2FC={prot_fc:.2f}"
        )
    lines.append("")
    return "\n".join(lines)


def build_substrate_dynamics_summary(
    parsed_ptms: List[dict],
    *,
    max_sites: int = 500,
) -> str:
    """Build substrate-level temporal dynamics summary using the P1 contract.

    Extracts the trajectory from each PTM entry, classifies each site using
    ``compute_site_kinetic_profile``, and returns a concise Markdown block
    describing the population-level pattern distribution.

    구현 대상: Substrate-level Temporal Dynamics Deepening Plan v1 §4 (P1), P4 report integration.
    해석 한계: pattern label은 궤적 형태 기술이며 kinase 귀속이나 인과관계가 아니다.
    """
    if not parsed_ptms:
        return ""

    try:
        from ptm_shared.substrate_temporal_dynamics import (
            SiteKineticConfig,
            compute_site_kinetic_profile,
        )
    except ImportError:
        return ""

    cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)

    pattern_counts: Counter = Counter()
    amplitudes: List[float] = []
    n_missingness_warning = 0
    n_processed = 0

    for ptm in parsed_ptms[:max_sites]:
        traj = ptm.get("trajectory") or {}
        tps_raw = traj.get("timepoints") or []
        if len(tps_raw) < 3:
            continue

        labels = [tp.get("timeLabel", "") for tp in tps_raw]
        values = [
            tp.get("ptmLog2FC") if tp.get("ptmLog2FC") is not None
            else tp.get("ptm_relative_log2fc")
            for tp in tps_raw
        ]
        if all(v is None for v in values):
            continue

        try:
            profile = compute_site_kinetic_profile(labels, values, config=cfg)
        except Exception:
            continue

        pattern_counts[profile.primary_pattern] += 1
        if profile.amplitude is not None:
            amplitudes.append(profile.amplitude)
        if profile.missingness_warning:
            n_missingness_warning += 1
        n_processed += 1

    if n_processed == 0:
        return ""

    top_patterns = pattern_counts.most_common(5)
    mean_amp = sum(amplitudes) / len(amplitudes) if amplitudes else None
    n_quality = sum(v for k, v in pattern_counts.items() if k != "flat_or_low_evidence")

    lines = [
        "## SUBSTRATE TEMPORAL DYNAMICS SUMMARY (P1 Contract v1)",
        f"- **Sites classified**: {n_processed}",
        f"- **Quality-passed sites**: {n_quality} ({n_quality / n_processed * 100:.1f}%)",
        f"- **Mean peak amplitude (|Log2FC|)**: {mean_amp:.2f}" if mean_amp else "",
        f"- **Missingness warnings**: {n_missingness_warning}",
        "",
        "**Pattern distribution (top 5):**",
    ]
    for pattern, count in top_patterns:
        pct = count / n_processed * 100
        lines.append(f"  - `{pattern}`: {count} ({pct:.1f}%)")
    lines.append("")

    return "\n".join(line for line in lines if line is not None)


def build_temporal_evidence_packet(
    temporal_sidecar: Mapping[str, Any] | None,
    *,
    max_edges: int = 12,
    max_waves: int = 8,
    kinase_activity_heatmap: Mapping[str, Any] | None = None,
    max_tmm_candidates: int = 6,
    max_counterevidence: int = 4,
) -> dict:
    """Build a compact, numerical, observational evidence packet for Report LLMs.

    The packet is deliberately derived only from the production temporal sidecar.
    It does not use benchmark truth, RAG, or an LLM-derived hypothesis.  Every
    record receives a stable ``DATA-*`` identifier so writer prompts can tie a
    temporal statement to an auditable numerical source.
    """
    sidecar = dict(temporal_sidecar or {})
    if not sidecar:
        return {
            "contract_version": "report_temporal_evidence_packet.v3",
            "status": "unavailable",
            "reason": "No production temporal PTM-protein sidecar was available for this Order.",
            "records": [],
            "claim_boundary": "Do not infer temporal, kinase, PTM-protein, or causal claims from this packet.",
        }

    records: list[dict] = []

    def add_record(
        evidence_id: str,
        tier: str,
        text: str,
        *,
        availability: str,
        claim_level: str,
        allowed_verbs: tuple[str, ...],
        forbidden_verbs: tuple[str, ...] = (
            "causes", "drives", "directly activates", "proves",
            "kinase switching", "causal propagation",
        ),
    ) -> None:
        """Attach machine-readable claim constraints to every temporal record."""
        records.append({
            "evidence_id": evidence_id,
            "tier": tier,
            "text": text,
            "availability": availability,
            "claim_level": claim_level,
            "allowed_verbs": list(allowed_verbs),
            "forbidden_verbs": list(forbidden_verbs),
        })

    heatmap = dict(kinase_activity_heatmap or {})
    add_record(
        "DATA-TEMPORAL-SUMMARY",
        "observational_summary",
        (
            "Measured scope: protein trajectories={protein}; same-gene PTM-protein pairs={pairs}; "
            "cross-layer edges={edges}; temporally eligible edges={eligible}; mechanism candidates={chains}; "
            "evidence-supported mechanism candidates={supported}; kinase timing status={timing}."
        ).format(
            protein=sidecar.get("protein_trajectory_count", 0),
            pairs=sidecar.get("ptm_protein_pair_count", 0),
            edges=sidecar.get("cross_layer_edge_count", 0),
            eligible=sidecar.get("temporally_eligible_edge_count", 0),
            chains=sidecar.get("mechanism_chain_count", 0),
            supported=sidecar.get("evidence_supported_mechanism_count", 0),
            timing=sidecar.get("kinase_timing_status", "not_evaluable"),
        ),
        availability="computed",
        claim_level="L1_observed_scope",
        allowed_verbs=("measured", "quantified", "observed", "reported"),
    )

    ledger_summary = dict(sidecar.get("kinase_feature_evidence_ledger_summary") or {})
    if ledger_summary:
        direct_tiers = dict(ledger_summary.get("direct_kinase_evidence_tier_counts") or {})
        temporal_tiers = dict(ledger_summary.get("temporal_evidence_tier_counts") or {})
        mapping_readiness = dict(ledger_summary.get("mapping_readiness") or {})
        relation_readiness = dict(ledger_summary.get("relation_readiness") or {})
        allocation_readiness = dict(ledger_summary.get("candidate_allocation_readiness") or {})
        mapping_counts = dict(mapping_readiness.get("mapping_class_counts") or {})
        relation_counts = dict(relation_readiness.get("relation_class_counts") or {})
        localization_counts = dict(
            (ledger_summary.get("identity_readiness_counts") or {}).get("localization_status") or {}
        )
        add_record(
            "DATA-KINASE-ATTRIBUTION-READINESS",
            "provenance_no_call",
            (
                "Kinase-attribution readiness (aggregate only): P0 explicit modified-precursor feature records={features}; "
                "site-level nominal aggregates={aggregates}; localization provenance counts={localization_counts}. "
                "P1 mapping bundle status={mapping_status}; M0={m0}, M1={m1}, M2={m2}, M3={m3}, M4={m4}. "
                "P2 relation bundle status={relation_status}; R0={r0}, R1={r1}, R2={r2}, R3={r3}, R4={r4}. "
                "P3 candidate allocation status={allocation_status}; eligible feature sets={eligible}; "
                "mass conservation status={mass_status}. direct kinase attribution status=not established ({direct_status}). "
                "These are aggregate provenance statuses only; no feature, accession, residue, candidate kinase, edge, "
                "reference, peptide, sequence, or raw quantitative value is available in this report packet. {boundary}"
            ).format(
                features=ledger_summary.get("feature_record_count"),
                aggregates=ledger_summary.get("nominal_aggregate_count"),
                localization_counts=localization_counts,
                mapping_status=mapping_readiness.get("mapping_bundle_status", "not_assessed"),
                m0=mapping_counts.get("M0", 0),
                m1=mapping_counts.get("M1", 0),
                m2=mapping_counts.get("M2", 0),
                m3=mapping_counts.get("M3", 0),
                m4=mapping_counts.get("M4", 0),
                relation_status=relation_readiness.get("relation_bundle_status", "not_assessed"),
                r0=relation_counts.get("R0", 0),
                r1=relation_counts.get("R1", 0),
                r2=relation_counts.get("R2", 0),
                r3=relation_counts.get("R3", 0),
                r4=relation_counts.get("R4", 0),
                allocation_status=allocation_readiness.get("allocation_status", "not_assessed"),
                eligible=allocation_readiness.get("eligible_feature_count", 0),
                mass_status=allocation_readiness.get("mass_conservation_status", "not_assessed"),
                direct_status=ledger_summary.get("direct_kinase_attribution_status"),
                boundary=ledger_summary.get(
                    "claim_boundary",
                    "No direct kinase attribution is available without feature-level mapping, localization, and curated-edge provenance.",
                ),
            ),
            availability="computed",
            claim_level="L1_provenance_no_call",
            allowed_verbs=("was recorded", "was unresolved", "was not evaluated"),
        )

    dynamic_status = sidecar.get("dynamic_co_wave_transition_status", "not_requested")
    dynamic_loto = dict(sidecar.get("dynamic_transition_loto") or {})
    dynamic_exposure = dict(sidecar.get("dynamic_transition_event_exposure") or {})
    dynamic_scope = dict(sidecar.get("dynamic_transition_pair_scope") or {})
    dynamic_pair_count = int(sidecar.get("dynamic_transition_pair_count") or 0)
    adjacency_status = str(sidecar.get("dynamic_temporal_adjacency_status", "not_requested"))
    adjacency_supported = bool(sidecar.get("dynamic_temporal_adjacency_supports_global_order", False))
    null_boundary = (
        "A valid global adjacency-order null calibration supported temporal ordering."
        if adjacency_status == "computed" and adjacency_supported
        else "No valid global adjacency-order null calibration supports temporal ordering; do not call this result robust, significant, or globally temporally resolved."
    )
    sidecar_provenance = dict(sidecar.get("provenance") or {})
    wave_projection = dict(sidecar_provenance.get("wave_input_projection") or {})
    if wave_projection:
        excluded = dict(wave_projection.get("excluded_reason_counts") or {})
        add_record(
            "DATA-WAVE-INPUT-QUALITY",
            "observational_input_quality",
            (
                "Canonical static Co-Wave fitting used missing-value policy={policy}; eligible complete trajectories={eligible}; "
                "excluded input sites={excluded_total}, including incomplete time grids={incomplete}. "
                "Missing measurements were retained as missing and were not converted to biological zeroes or imputed."
            ).format(
                policy=wave_projection.get("missing_value_policy", "not_recorded"),
                eligible=wave_projection.get("eligible_site_count", "not_recorded"),
                excluded_total=wave_projection.get("excluded_site_count", "not_recorded"),
                incomplete=excluded.get("incomplete_time_grid", "not_recorded"),
            ),
            availability="computed",
            claim_level="L1_input_quality",
            allowed_verbs=("were observed", "were excluded", "were retained as missing"),
        )
    add_record(
        "DATA-DYNAMIC-SUMMARY",
        "observational_dynamic",
        (
            "Dynamic co-wave status={status}; transition-supported Waves={waves}; "
            "pair transitions={pairs}; site transitions={sites}; transition resolution={resolution}; "
            "same-Wave candidate pairs={candidate_pairs}; non-evaluable pair windows={non_evaluable_pairs}; "
            "non-evaluable site transition opportunities={non_evaluable_sites}; "
            "mean pair LOTO Jaccard={pair_loto}; mean site LOTO Jaccard={site_loto}; "
            "global adjacency-order test status={adj_status}; p={adj_p}; verdict={adj_verdict}. "
            "Transition totals are exposure-dependent descriptive counts, not biological-effect size or temporal-order proof. {null_boundary}"
        ).format(
            status=dynamic_status,
            waves=sidecar.get("dynamic_transition_supported_wave_count", 0),
            pairs=sidecar.get("dynamic_transition_pair_count", 0),
            sites=sidecar.get("dynamic_transition_site_count", 0),
            resolution=sidecar.get("dynamic_transition_resolution"),
            candidate_pairs=dynamic_scope.get("candidate_pair_count", "not_recorded"),
            non_evaluable_pairs=dynamic_scope.get("non_evaluable_pair_window_count", "not_recorded"),
            non_evaluable_sites=dynamic_exposure.get("non_evaluable_site_transition_count", "not_recorded"),
            pair_loto=dynamic_loto.get("mean_pair_transition_jaccard"),
            site_loto=dynamic_loto.get("mean_site_transition_jaccard"),
            adj_status=adjacency_status,
            adj_p=sidecar.get("dynamic_temporal_adjacency_p_value"),
            adj_verdict=sidecar.get("dynamic_temporal_adjacency_verdict", "not_evaluable"),
            null_boundary=null_boundary,
        ),
        availability="computed" if dynamic_status == "computed" and dynamic_pair_count > 0 else "not_evaluable",
        claim_level="L2_observational_dynamic",
        allowed_verbs=("co-occurred", "reorganized", "was observed", "was annotated"),
    )

    precedence = dict(sidecar.get("temporal_precedence_status") or {})
    if precedence:
        precedence_status = str(precedence.get("status") or "unavailable")
        add_record(
            "DATA-TEMPORAL-PRECEDENCE",
            (
                "observational_temporal_precedence"
                if precedence_status == "computed"
                else "temporal_uncertainty"
            ),
            (
                "Temporal event-order status={status}; event-record sites={sites}; "
                "evaluable sites={evaluable}; tier breakdown={tiers}; replicate mode={mode}; "
                "sites with replicate data={replicate_sites}; P4 validation passed={p4}. "
                "replicate bootstrap no-calls={no_calls}; partial-draw sites={partial_draws}. "
                "{boundary}"
            ).format(
                status=precedence_status,
                sites=precedence.get("n_sites"),
                evaluable=precedence.get("n_evaluable"),
                tiers=dict(precedence.get("tier_breakdown") or {}),
                mode=precedence.get("replicate_mode"),
                replicate_sites=precedence.get("n_sites_with_replicate_data"),
                p4=precedence.get("p4_gate_passed"),
                no_calls=precedence.get("replicate_bootstrap_no_call_count"),
                partial_draws=precedence.get("replicate_bootstrap_partial_draw_count"),
                boundary=precedence.get(
                    "claim_boundary",
                    "Observed response timing only; causal interpretation is not supported.",
                ),
            ),
            availability="computed" if precedence_status == "computed" and int(precedence.get("n_evaluable") or 0) > 0 else "not_evaluable",
            claim_level="L2_observational_timing",
            allowed_verbs=("preceded", "followed", "was temporally ordered", "was observed"),
        )

    for index, row in enumerate((sidecar.get("dynamic_transition_per_wave") or [])[:max_waves], 1):
        if not isinstance(row, Mapping):
            continue
        add_record(
            f"DATA-DYNAMIC-WAVE-{index}",
            "observational_dynamic",
            (
                "Static Wave {wave}: pair transitions={pairs}; non-persistence pair transitions={nonpersistence}; "
                "site transitions={sites}; pair transition types={pair_types}; site transition types={site_types}. "
                "This packet does not expose member identities or per-Wave enrichment; do not assign a functional module to this Wave."
            ).format(
                wave=row.get("static_wave_id", "unknown"),
                pairs=row.get("pair_transition_count", 0),
                nonpersistence=row.get("nonpersistence_pair_transition_count", 0),
                sites=row.get("site_transition_count", 0),
                pair_types=dict(row.get("pair_transition_type_counts") or {}),
                site_types=dict(row.get("site_transition_type_counts") or {}),
            ),
            availability="computed",
            claim_level="L2_observational_dynamic",
            allowed_verbs=("co-occurred", "reorganized", "was observed", "was annotated"),
        )

    for index, row in enumerate((sidecar.get("top_cross_layer_edges") or [])[:max_edges], 1):
        if not isinstance(row, Mapping):
            continue
        similarity = row.get("lag_aware_similarity") or {}
        if isinstance(similarity, Mapping):
            similarity = similarity.get("best_similarity")
        add_record(
            f"DATA-CROSS-LAYER-{index}",
            "observational_cross_layer",
            (
                "Candidate {edge}: Wave {wave} and protein {target}; observed sampled-timepoint order={direction}; "
                "observed onset-timepoint difference={onset} min; observed peak-timepoint difference={peak} min; "
                "lag-aware similarity={similarity}; "
                "mechanism-chain eligibility={eligible}; temporal interpretation={interpretation}; causality=not_tested."
            ).format(
                edge=row.get("edge_id", "unknown"),
                wave=row.get("source_wave_id", "unknown"),
                target=row.get("target_gene", "unknown"),
                direction=row.get("direction", "unknown"),
                onset=row.get("onset_lag_minutes"),
                peak=row.get("peak_lag_minutes"),
                similarity=similarity,
                eligible=row.get("eligible_for_mechanism_chain", False),
                interpretation=row.get("temporal_interpretation", "observational_peak_order_only"),
            ),
            availability="computed",
            claim_level="L2_observational_cross_layer",
            allowed_verbs=("was temporally consistent with", "showed an observed sampled-timepoint difference", "preceded", "was observed"),
        )

    # Candidate-level TMM evidence comes from the same production heatmap that
    # created the sidecar. It is contribution-weighted observational support,
    # not direct kinase-substrate attribution.
    weighted_cascade = dict(heatmap.get("tmm_weighted_temporal_cascade") or {})
    tmm_candidates: list[tuple[float, str, str, Mapping[str, Any]]] = []
    seen_kinases: set[str] = set()
    for timepoint in weighted_cascade.get("timepoints") or []:
        if not isinstance(timepoint, Mapping):
            continue
        timepoint_name = str(timepoint.get("timepoint") or "unknown")
        for active in timepoint.get("active_kinases") or []:
            if not isinstance(active, Mapping):
                continue
            kinase = str(active.get("canonical") or active.get("kinase") or "").strip()
            if not kinase or kinase in seen_kinases:
                continue
            selected = active.get("selected_activity", active.get("tmm_weighted_activity", 0.0))
            try:
                magnitude = abs(float(selected or 0.0))
            except (TypeError, ValueError):
                magnitude = 0.0
            tmm_candidates.append((magnitude, kinase, timepoint_name, active))
            seen_kinases.add(kinase)
    for index, (_, kinase, timepoint_name, row) in enumerate(
        sorted(tmm_candidates, key=lambda item: (-item[0], item[1]))[:max_tmm_candidates],
        1,
    ):
        evidence = dict(row.get("tmm_evidence") or {})
        add_record(
            f"DATA-TMM-KINASE-{index}",
            "observational_tmm",
            (
                "TMM candidate kinase {kinase}: timepoint={timepoint}; selected contribution-weighted activity={activity}; "
                "raw weighted activity={raw}; substrate support={support}; direction={direction}; activity metric={metric}; "
                "evidence profile={evidence}. This is a candidate attribution, not direct kinase-substrate proof."
            ).format(
                kinase=kinase,
                timepoint=timepoint_name,
                activity=row.get("selected_activity", row.get("peak_score")),
                raw=row.get("tmm_weighted_activity", row.get("peak_score")),
                support=row.get("tmm_weighted_substrate_support", row.get("substrate_count")),
                direction=row.get("direction", "observational"),
                metric=row.get("selected_activity_metric", weighted_cascade.get("activity_metric", "not_persisted")),
                evidence={key: evidence.get(key) for key in sorted(evidence)[:5]},
            ),
            availability="computed",
            claim_level="L2_candidate_attribution",
            allowed_verbs=("was a candidate", "was contribution-weighted", "was ranked", "was associated with"),
        )

    uncertainty = dict(heatmap.get("relative_tmm_uncertainty_summary") or {})
    if uncertainty:
        scalar_uncertainty = {
            key: uncertainty.get(key)
            for key in sorted(uncertainty)
            if isinstance(uncertainty.get(key), (str, int, float, bool))
        }
        add_record(
            "DATA-TMM-UNCERTAINTY",
            "uncertainty",
            (
                "Relative TMM uncertainty summary={summary}. Treat candidate ranking as uncertain where the "
                "persisted summary does not support a stable estimate."
            ).format(summary=scalar_uncertainty),
            availability="computed",
            claim_level="L0_uncertainty",
            allowed_verbs=("was uncertain", "was not stable", "was limited"),
        )

    for index, row in enumerate((sidecar.get("top_mechanism_counterevidence") or [])[:max_counterevidence], 1):
        if not isinstance(row, Mapping):
            continue
        add_record(
            f"DATA-COUNTEREVIDENCE-{index}",
            "counterevidence",
            (
                "Mechanism candidate {chain}: status={status}; counterevidence={reasons}. "
                "Do not promote this candidate to a causal mechanism without resolving these limitations."
            ).format(
                chain=row.get("chain_id", "unknown"),
                status=row.get("status", "insufficient_evidence"),
                reasons=list(row.get("reasons") or []),
            ),
            availability="computed",
            claim_level="L0_limitation",
            allowed_verbs=("was limited", "was not supported", "requires validation"),
        )

    computed_layers = {
        "dynamic": dynamic_status == "computed" and dynamic_pair_count > 0,
        "cross_layer": any(str(record.get("evidence_id", "")).startswith("DATA-CROSS-LAYER-") for record in records),
        "temporal_precedence": any(
            record.get("evidence_id") == "DATA-TEMPORAL-PRECEDENCE"
            and record.get("availability") == "computed"
            for record in records
        ),
        "tmm": any(str(record.get("evidence_id", "")).startswith("DATA-TMM-KINASE-") for record in records),
    }
    # A local Dynamic Co-Wave observation alone is not a receptor/kinase
    # cascade.  Generic cascade context is enabled only when the packet has
    # all three independent observational supports required to constrain a
    # directed temporal candidate: TMM kinase evidence, cross-layer evidence,
    # and temporal timing evidence. Dynamic context remains separately usable
    # for local co-movement wording.
    dynamic_context_allowed = bool(computed_layers["dynamic"])
    directed_temporal_context_allowed = bool(
        computed_layers["tmm"]
        and computed_layers["cross_layer"]
        and computed_layers["temporal_precedence"]
    )
    mechanism_context_allowed = directed_temporal_context_allowed

    direct_status = str(ledger_summary.get("direct_kinase_attribution_status") or "no_call").strip().lower()
    direct_kinase_attribution_allowed = direct_status in {
        "perturbation_supported_direct_kinase_attribution",
    }
    observation_only_claim_ceiling = not (
        directed_temporal_context_allowed and direct_kinase_attribution_allowed
    )

    return {
        "contract_version": "report_temporal_evidence_packet.v4",
        "status": "available",
        "shared_engine_contract": sidecar.get("shared_engine_contract"),
        "artifact_path": sidecar.get("artifact_path"),
        "record_count": len(records),
        "records": records,
        "section_plan": {
            "computed_layers": computed_layers,
            "dynamic_context_allowed": dynamic_context_allowed,
            "directed_temporal_context_allowed": directed_temporal_context_allowed,
            "mechanism_context_allowed": mechanism_context_allowed,
            "direct_kinase_attribution_allowed": direct_kinase_attribution_allowed,
            "observation_only_claim_ceiling": observation_only_claim_ceiling,
            "results_discussion_claim_ceiling": (
                "L2_observational_temporal_candidate_with_no_direct_kinase_call"
                if directed_temporal_context_allowed and not observation_only_claim_ceiling
                else "L1_observed_measurement_only"
            ),
            "high_severity_forbidden_terms": [
                "causes", "drives", "directly activates", "proves",
                "kinase switching", "causal propagation", "signal propagation",
                "direct regulation", "autophosphorylation", "feedback loop",
                "phosphatase activation", "dominant kinase", "direct biochemical evidence",
            ],
        },
        "claim_boundary": (
            "The packet contains measured temporal summaries and observational candidates only. "
            "It does not establish kinase switching, direct kinase-substrate attribution, PTM-protein causality, "
            "or mechanism proof. A numerical statement must match a DATA-* record; otherwise state that the "
            "quantity is not evaluable from current data."
        ),
    }


def format_temporal_evidence_packet_for_llm(
    packet: Mapping[str, Any],
    *,
    section_type: str = "general",
) -> str:
    """Format the packet as a mandatory, compact writer supplement."""
    if not packet or packet.get("status") != "available":
        return (
            "=== TEMPORAL NUMERICAL EVIDENCE PACKET ===\n"
            "Status: unavailable. Do not invent temporal PTM-protein, dynamic co-wave, or kinase timing results.\n"
            "=== END TEMPORAL NUMERICAL EVIDENCE PACKET ==="
        )
    section_plan = dict(packet.get("section_plan") or {})
    computed_layers = dict(section_plan.get("computed_layers") or {})
    mechanism_context_allowed = bool(section_plan.get("mechanism_context_allowed"))
    record_ids = {
        str(record.get("evidence_id"))
        for record in packet.get("records") or []
        if isinstance(record, Mapping)
    }
    has_dynamic = any(identifier.startswith("DATA-DYNAMIC") for identifier in record_ids)
    has_precedence = "DATA-TEMPORAL-PRECEDENCE" in record_ids
    has_tmm = any(identifier.startswith("DATA-TMM-KINASE") for identifier in record_ids)
    has_cross_layer = any(identifier.startswith("DATA-CROSS-LAYER") for identifier in record_ids)
    has_counterevidence = any(identifier.startswith("DATA-COUNTEREVIDENCE") for identifier in record_ids)
    section = str(section_type or "general").lower()
    if section in {"results", "discussion", "conclusion", "abstract"}:
        coverage_instruction = (
            "SECTION EVIDENCE PLAN: Start with measured observation records. Use a temporal layer only when "
            f"its computed flag is True: {computed_layers}. Claim ceiling={section_plan.get('results_discussion_claim_ceiling', 'L1_observed_measurement_only')}. "
            "Use only the allowed verbs attached to each cited record. Do not use receptor-cascade context, "
            "auxiliary directionality, generic writing examples, or signal-propagation prose as a substitute for a missing layer. "
            "If a layer is not_evaluable or has zero candidates, state that it was not evaluable and omit that mechanism claim."
        )
    else:
        coverage_instruction = "Use the relevant supplied numerical temporal records when answering this section; do not substitute generic pathway prose."
    lines = [
        "=== TEMPORAL NUMERICAL EVIDENCE PACKET (MANDATORY; OBSERVATIONAL) ===",
        "Use exact values and identifiers only from the records below. Before every temporal or PTM-protein claim, "
        "check that it is supported by one DATA-* record. Do not turn a local co-wave transition into kinase switching, "
        "or a lagged protein trajectory into direct regulation or causality.",
        "If kinase timing is not_evaluable or an edge is not evidence-supported, state that limitation explicitly.",
        "When the dynamic summary states that no valid global adjacency-order null calibration supports ordering, do not call a co-wave pattern robust, significant, validated, or globally temporally resolved. Treat it as a sampled-timepoint local observation only.",
        f"Mechanism-context allowed in this section={mechanism_context_allowed}.",
        coverage_instruction,
        f"Available required classes: temporal-precedence={has_precedence}; dynamic={has_dynamic}; TMM={has_tmm}; PTM-protein={has_cross_layer}; counterevidence={has_counterevidence}.",
        "Use DATA labels only as internal audit anchors while drafting. Never reproduce any DATA-* label in user-facing prose; "
        "the final renderer removes every internal label after traceability is checked.",
        "",
    ]
    for record in packet.get("records") or []:
        if not isinstance(record, Mapping):
            continue
        # Evidence IDs are internal routing keys. The LLM receives only the
        # human-readable aggregate statement so DATA-* labels cannot leak to DOCX.
        lines.append(str(record.get("text", "")))
    lines.extend([
        "",
        f"Claim boundary: {packet.get('claim_boundary', '')}",
        "=== END TEMPORAL NUMERICAL EVIDENCE PACKET ===",
    ])
    return "\n".join(lines)


def format_compact_attribution_readiness_for_report(packet: Mapping[str, Any] | None) -> str:
    """Render the compact P0–P3 readiness aggregate for the final Report.

    This deliberately reuses the same aggregate-only record supplied to the
    writer.  It therefore cannot expose full-ledger identities, candidate-edge
    details, source PMIDs, peptides, sequences, or raw provenance values.
    """
    packet = dict(packet or {})
    readiness = next(
        (
            record for record in packet.get("records") or []
            if isinstance(record, Mapping)
            and record.get("evidence_id") == "DATA-KINASE-ATTRIBUTION-READINESS"
        ),
        None,
    )
    if not readiness:
        return ""
    return "\n".join([
        "### Kinase-attribution readiness and provenance boundary",
        "",
        str(readiness.get("text") or ""),
        "",
        "**Interpretation boundary.** This aggregate readiness summary preserves what was available "
        "for attribution without promoting legacy annotation, motif context, pathway membership, "
        "or literature context to an Order-specific direct kinase–site relationship.",
    ])


def build_temporal_evidence_fallback_addendum(packet: Mapping[str, Any]) -> str:
    """Return deterministic temporal evidence when an LLM omits mandatory classes."""
    if not packet or packet.get("status") != "available":
        return ""
    selected: list[Mapping[str, Any]] = []
    prefixes = (
        "DATA-TEMPORAL-SUMMARY",
        "DATA-KINASE-ATTRIBUTION-READINESS",
        "DATA-TEMPORAL-PRECEDENCE",
        "DATA-DYNAMIC-SUMMARY",
        "DATA-DYNAMIC-WAVE-",
        "DATA-TMM-KINASE-",
        "DATA-TMM-UNCERTAINTY",
        "DATA-CROSS-LAYER-",
        "DATA-COUNTEREVIDENCE-",
    )
    for prefix in prefixes:
        record = next(
            (
                row for row in packet.get("records") or []
                if isinstance(row, Mapping) and str(row.get("evidence_id", "")).startswith(prefix)
            ),
            None,
        )
        if record:
            selected.append(record)
    if not selected:
        return ""
    lines = [
        "### Numerical temporal-evidence traceability",
        "The following engine-generated observations preserve numerical traceability; they do not establish causality.",
    ]
    for record in selected:
        lines.append(f"- [{record.get('evidence_id')}] {record.get('text', '')}")
    return "\n".join(lines)


def build_nonptm_temporal_analysis(
    network_results: dict, timepoints: list, ptm_type: str = "phosphorylation"
) -> str:
    """
    Build a measured Non-PTM temporal abundance context block.
    It reports protein trajectories, broad annotation categories, relative observed
    timing, and pathway context without treating abundance as a directed PTM edge.
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

    # Collect PTM proteins only for relative observed timing comparison.
    ptm_temporal: Dict[str, Dict[str, float]] = {}
    for tp in timepoints:
        net = source.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes", "ptm_nodes"]:
            for node in net.get(node_type, []):
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", node.get("id", ""))
                if not gene:
                    continue
                ptm_fc = float(node.get("value", node.get("ptm_log2fc", node.get("ptm_relative_log2fc", 0))))
                if gene not in ptm_temporal:
                    ptm_temporal[gene] = {}
                ptm_temporal[gene][tp] = ptm_fc

    # Collect network annotations only to select comparable PTM observations;
    # they are not causal edges.
    ptm_nonptm_edges: Dict[str, List[str]] = {}  # nonptm_gene -> [ptm_gene, ...]
    for tp in timepoints:
        net = source.get(tp, {})
        if not isinstance(net, dict):
            continue
        for edge in net.get("active_edges", []) + net.get("all_edges", []):
            if not isinstance(edge, dict):
                continue
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in nonptm_temporal and tgt in ptm_temporal:
                ptm_nonptm_edges.setdefault(src, []).append(tgt)
            elif tgt in nonptm_temporal and src in ptm_temporal:
                ptm_nonptm_edges.setdefault(tgt, []).append(src)

    # --- Broad protein-category annotation ---
    SIGNALING_ROLES = {
        "upstream_regulator": {
            "keywords": ["mapk", "erk", "jnk", "p38", "raf", "ras", "mek", "src", "fak",
                         "jak", "pi3k", "akt", "pkc", "pka", "camk", "rock", "cdk"],
            "label": "Kinase-family/context annotation",
        },
        "scaffold_adaptor": {
            "keywords": ["grb", "shc", "sos", "gab", "irs", "nck", "crk", "14-3-3",
                         "ywhaz", "ywhab", "ywhae", "ywhag", "ywhah", "ywhaq",
                         "axin", "akap", "homer", "shank", "dlg"],
            "label": "Scaffold/Adaptor",
        },
        "transducer": {
            "keywords": ["stat", "smad", "nfkb", "rela", "relb", "creb", "nfat",
                         "foxo", "myc", "jun", "fos", "atf"],
            "label": "Transcription/signaling context annotation",
        },
        "downstream_effector": {
            "keywords": ["casp", "bax", "bcl", "mtor", "s6k", "4ebp", "eif",
                         "rps6", "gsk3", "ctnnb", "ccn", "cdc", "chk",
                         "p53", "tp53", "rb1", "mdm"],
            "label": "Cellular process context annotation",
        },
    }

    def _classify_signaling_role(gene: str) -> str:
        gene_lower = gene.lower()
        for role_key, role_info in SIGNALING_ROLES.items():
            for kw in role_info["keywords"]:
                if kw in gene_lower:
                    return role_info["label"]
        return "Protein context annotation"

    def _classify_relative_timing(nonptm_gene: str, tp_data: Dict[str, float]) -> str:
        """Describe relative observed onset without inferring directionality."""
        connected_ptms = ptm_nonptm_edges.get(nonptm_gene, [])
        if not connected_ptms or not ptm_temporal:
            return "No comparable PTM context"

        # Compare temporal patterns: does PTM change precede Non-PTM change?
        nonptm_values = [tp_data.get(tp, 0) for tp in timepoints]
        nonptm_first_change_idx = next(
            (i for i, v in enumerate(nonptm_values) if abs(v) > 0.3), len(timepoints)
        )

        ptm_first_change_idx = len(timepoints)
        for ptm_gene in connected_ptms:
            ptm_vals = ptm_temporal.get(ptm_gene, {})
            for i, tp in enumerate(timepoints):
                if abs(ptm_vals.get(tp, 0)) > 0.3:
                    ptm_first_change_idx = min(ptm_first_change_idx, i)
                    break

        if ptm_first_change_idx < nonptm_first_change_idx:
            return "PTM change observed earlier"
        elif nonptm_first_change_idx < ptm_first_change_idx:
            return "Protein change observed earlier"
        elif nonptm_first_change_idx == ptm_first_change_idx and nonptm_first_change_idx < len(timepoints):
            return "Same first observed change"
        return "No evaluable timing comparison"

    # Sort by max absolute change
    sorted_nonptm = sorted(
        nonptm_temporal.items(),
        key=lambda x: max(abs(v) for v in x[1].values()),
        reverse=True,
    )

    lines = [
        "## NON-PTM PROTEIN TEMPORAL ABUNDANCE CONTEXT",
        f"The following Non-PTM proteins are interaction partners of identified {ptm_type}-modified "
        "substrates. They do NOT carry the target PTM modification. Their protein-abundance changes are "
        "observational temporal context, not validation of a kinase-substrate signaling axis or an upstream/downstream relationship. "
        "Use them as qualified, INLINE context when discussing biological programmes.",
        "",
    ]

    # Table header
    header = "| # | Protein | Protein Category | Relative Observed Timing |"
    for tp in timepoints:
        header += f" {tp} Prot_Log2FC |"
    header += " Trend | Pathway |"
    lines.append(header)

    sep = "|---|---|---|---|"
    for _ in timepoints:
        sep += "---|"
    sep += "---|---|"
    lines.append(sep)

    for i, (gene, tp_data) in enumerate(sorted_nonptm[:15], 1):
        role = _classify_signaling_role(gene)
        directionality = _classify_relative_timing(gene, tp_data)
        pathways = classify_gene_pathway(gene, DEFAULT_PATHWAYS)
        pw_str = ", ".join(pathways[:2]) if pathways else "—"

        row = f"| {i} | **{gene}** | {role} | {directionality} |"
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
        row += f" {trend} | {pw_str} |"
        lines.append(row)

    # Protein-category and relative observed-timing summary
    role_counts: Dict[str, int] = {}
    direction_counts: Dict[str, int] = {}
    for gene, tp_data in sorted_nonptm[:15]:
        role = _classify_signaling_role(gene)
        directionality = _classify_relative_timing(gene, tp_data)
        role_counts[role] = role_counts.get(role, 0) + 1
        direction_counts[directionality] = direction_counts.get(directionality, 0) + 1

    lines.append("")
    lines.append("### Non-PTM Protein Category Distribution")
    for role, cnt in sorted(role_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- **{role}**: {cnt} proteins")

    lines.append("")
    lines.append("### PTM/Non-PTM Relative Observed Timing")
    for direction, cnt in sorted(direction_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- **{direction}**: {cnt} proteins")

    lines.append("")
    lines.append("### Interpretation Instructions (CRITICAL — Observational Context)")
    lines.append(
        "IMPORTANT: Non-PTM proteins are interpreted as measured protein-abundance context for the PTM response.\n\n"
        "When writing about Non-PTM proteins, you MUST follow these rules:\n"
        "1. DO NOT create a separate dedicated section for Non-PTM proteins.\n"
        "2. Mention Non-PTM proteins INLINE when they sharpen a data-grounded biological programme, pathway context, "
        "   or a testable explanation for a measured PTM trajectory.\n"
        "3. The NUMBER of concordant Non-PTM proteins reports the size of an observationally consistent protein set; "
        "   it does not validate a kinase-substrate relationship.\n"
        "4. Use relative timing between PTM and Non-PTM measurements as descriptive context, not proof of signal propagation.\n"
        "5. Group Non-PTM proteins by shared temporal profile, pathway annotation, or biological programme when useful.\n"
        "6. Use broad protein-category annotations only as literature-oriented context, not as an upstream/downstream mechanism.\n"
    )

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
        "and protein abundance change. This timing is observational and does not establish a causal regulatory relationship.",
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
        f"PTM-first cases are temporally compatible with modification preceding protein change; "
        f"Protein-first cases are temporally compatible with abundance or degradation processes preceding modification. "
        f"Neither pattern establishes causality."
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
            f"{p.get('gene', p.get('Gene', '?'))}-{p.get('position', p.get('Position', '?'))}(FC={float(p.get('ptm_relative_log2fc', 0)):.2f})"
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
    GAP A-5: Build signal propagation JSON block with canonical pathway
    annotation and biological significance interpretation.
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

        # Newly higher-abundance PTM genes at this timepoint.
        new_activations = active_genes - prev_active_genes
        lost_activations = prev_active_genes - active_genes

        # Annotate newly higher-abundance PTM genes by canonical pathway context.
        pathway_groups: Dict[str, List[str]] = {}
        for gene in new_activations:
            matched = classify_gene_pathway(gene, DEFAULT_PATHWAYS)
            for pw in matched:
                pathway_groups.setdefault(pw, []).append(gene)

        # Annotate no-longer-higher-abundance PTM genes by canonical pathway context.
        lost_pathway_groups: Dict[str, List[str]] = {}
        for gene in lost_activations:
            matched = classify_gene_pathway(gene, DEFAULT_PATHWAYS)
            for pw in matched:
                lost_pathway_groups.setdefault(pw, []).append(gene)

        # Describe measured set turnover without inferring propagation or causality.
        bio_significance = []
        if len(new_activations) > len(lost_activations) * 2:
            bio_significance.append("ptm_set_expansion")
        elif len(lost_activations) > len(new_activations) * 2:
            bio_significance.append("ptm_set_contraction")
        elif new_activations and lost_activations:
            bio_significance.append("ptm_set_reconfiguration")
        if pathway_groups:
            if len(pathway_groups) > 2:
                bio_significance.append("pathway_divergence")
            elif len(pathway_groups) == 1:
                bio_significance.append("pathway_focused")

        tp_data = {
            "timepoint": tp,
            "n_active": len(active_nodes),
            "n_inhibited": len(inhibited_nodes),
            "n_nonptm": len(nonptm_nodes),
            "new_activations": sorted(new_activations)[:10],
            "lost_activations": sorted(lost_activations)[:10],
            "canonical_pathways_activated": {
                pw: sorted(genes) for pw, genes in sorted(pathway_groups.items(), key=lambda x: len(x[1]), reverse=True)
            },
            "canonical_pathways_deactivated": {
                pw: sorted(genes) for pw, genes in sorted(lost_pathway_groups.items(), key=lambda x: len(x[1]), reverse=True)
            },
            "biological_significance": bio_significance,
        }
        propagation["timepoints"].append(tp_data)

        if prev_active_genes and new_activations:
            # Describe local temporal turnover; do not infer a cascade.
            cascade_meaning = "ptm_set_reconfiguration"
            if len(new_activations) > 5:
                cascade_meaning = "ptm_set_expansion"
            elif lost_activations and len(lost_activations) > len(new_activations):
                cascade_meaning = "ptm_set_contraction"
            elif not lost_activations and new_activations:
                cascade_meaning = "new_ptm_set_emergence"

            propagation["propagation_events"].append({
                "from_tp": timepoints[timepoints.index(tp) - 1] if timepoints.index(tp) > 0 else tp,
                "to_tp": tp,
                "new_signals": sorted(new_activations)[:5],
                "lost_signals": sorted(lost_activations)[:5],
                "cascade_type": cascade_meaning,
                "pathways_involved": list(pathway_groups.keys())[:5],
                "interpretation": (
                    f"{len(new_activations)} newly higher-abundance PTM genes were observed at {tp} "
                    f"({cascade_meaning.replace('_', ' ')}). "
                    f"Pathway annotations: {', '.join(list(pathway_groups.keys())[:3]) or 'unclassified'}."
                ),
            })

        prev_active_genes = active_genes

    if not propagation["timepoints"]:
        return ""

    # Build Markdown table summary in addition to JSON
    lines = [
        "## TEMPORAL PTM-SET RECONFIGURATION (with Canonical Pathway Context)",
        "Use this structured timeline to describe measured PTM-set turnover across timepoints.",
        "For each transition, discuss: (1) which pathway annotations are represented, "
        "(2) whether the observed set expands, contracts, or reconfigures, "
        "(3) the biological interpretation and alternatives without asserting directional propagation.",
        "",
    ]

    # Summary table
    lines.append("### Temporal Reconfiguration Summary")
    lines.append("| Timepoint | Higher PTM | Lower PTM | Non-PTM | Newly Higher | No Longer Higher | Pattern | Top Pathways |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for tp_d in propagation["timepoints"]:
        pathways_str = ", ".join(list(tp_d.get("canonical_pathways_activated", {}).keys())[:3]) or "\u2014"
        sig_str = ", ".join(tp_d.get("biological_significance", [])) or "\u2014"
        lines.append(
            f"| {tp_d['timepoint']} | {tp_d['n_active']} | {tp_d['n_inhibited']} | "
            f"{tp_d['n_nonptm']} | {len(tp_d['new_activations'])} | "
            f"{len(tp_d['lost_activations'])} | {sig_str} | {pathways_str} |"
        )
    lines.append("")

    # Local temporal reconfiguration events
    if propagation["propagation_events"]:
        lines.append("### Temporal Reconfiguration Events")
        for evt in propagation["propagation_events"]:
            lines.append(
                f"- **{evt['from_tp']} \u2192 {evt['to_tp']}**: {evt['interpretation']} "
                f"(type: {evt['cascade_type']})"
            )
        lines.append("")

    # Full JSON
    lines.append("### Detailed JSON Data")
    lines.append("```json")
    lines.append(_json.dumps(propagation, indent=2))
    lines.append("```")
    lines.append("")
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
            formatted.append(w.capitalize() if w and not w[0].isupper() else w)

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
    lines.append("## ═══════════════════════════════════════════════════════════")
    lines.append("## 📊 VERIFIED CROSS-TALK DATA — STRUCTURED FORMAT (v98)")
    lines.append("## ═══════════════════════════════════════════════════════════")
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
    lines.append("## ═══════════════════════════════════════════════════════════")
    lines.append("")

    return ("\n".join(lines), unique_proteins, log2fc_values)


# ---------------------------------------------------------------------------
# v11.8: TF Activity Inference from Non-PTM Protein Changes
# ---------------------------------------------------------------------------

def build_tf_activity_inference(
    network_results: dict,
    timepoints: list,
    ptm_type: str = "phosphorylation",
    organism: str = "",
) -> tuple:
    """
    Infer transcription factor activity from non-PTM protein temporal changes.

    Strategy:
    1. Collect non-PTM proteins that show significant change (|FC| >= 0.3)
       grouped by temporal onset (early vs late responders)
    2. Call MCP server's TF inference endpoint (DoRothEA + TRRUST)
    3. Cross-validate with PTM-inferred kinase->TF relationships
    4. Return (llm_context_string, tf_inference_json_for_frontend)

    Args:
        network_results: Full network analysis results dict
        timepoints: Sorted list of timepoint labels
        ptm_type: Type of PTM being analyzed
        organism: Organism name (for species mapping)

    Returns:
        Tuple of (llm_context_str, tf_inference_data_dict)
    """
    from common.temporal_utils import tp_to_minutes

    networks = network_results.get("networks", {})
    if not networks:
        # Fallback: some callers store per-timepoint data under 'timepoint_results'
        networks = network_results.get("timepoint_results", {})
    if not networks or not timepoints:
        return ("", {})

    # --- Step 1: Collect changed non-PTM proteins per timepoint ---
    nonptm_temporal = {}  # gene -> {tp: log2fc}
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
            protein_log2fc = node.get("protein_log2fc", node.get("log2fc", 0))
            if gene not in nonptm_temporal:
                nonptm_temporal[gene] = {}
            nonptm_temporal[gene][tp] = protein_log2fc

    if not nonptm_temporal:
        return ("", {})

    # Identify significantly changed genes per temporal window
    THRESHOLD = 0.3
    early_changed = set()  # genes changed at early timepoints (<=15min)
    late_changed = set()   # genes changed at late timepoints (>15min)
    all_changed = set()

    for gene, tp_data in nonptm_temporal.items():
        for tp, fc in tp_data.items():
            if abs(fc) >= THRESHOLD:
                all_changed.add(gene)
                if tp_to_minutes(tp) <= 15:
                    early_changed.add(gene)
                else:
                    late_changed.add(gene)

    if len(all_changed) < 5:
        return ("", {})

    # --- Step 2: Call MCP TF inference endpoint ---
    species = "mouse"  # default
    org_lower = organism.lower() if organism else ""
    if "human" in org_lower or "homo" in org_lower:
        species = "human"
    elif "rat" in org_lower or "rattus" in org_lower:
        species = "rat"
    elif "mouse" in org_lower or "mus" in org_lower or "murine" in org_lower:
        species = "mouse"

    try:
        from common.mcp_client import MCPClient
        mcp = MCPClient()
    except Exception as e:
        logger.warning(f"[v11.8] Cannot initialize MCP client for TF inference: {e}")
        return ("", {})

    # Infer TFs from all changed genes
    tf_result_all = mcp.infer_tf_activity(
        gene_list=list(all_changed),
        species=species,
        min_confidence="medium",
        min_targets_overlap=3,
        top_n=15,
    )

    # Also do per-temporal-window inference for temporal resolution
    tf_result_temporal = {}
    if early_changed and len(early_changed) >= 3:
        tf_result_temporal["early"] = mcp.infer_tf_activity(
            gene_list=list(early_changed),
            species=species,
            min_confidence="medium",
            min_targets_overlap=2,
            top_n=10,
        )
    if late_changed and len(late_changed) >= 3:
        tf_result_temporal["late"] = mcp.infer_tf_activity(
            gene_list=list(late_changed),
            species=species,
            min_confidence="medium",
            min_targets_overlap=2,
            top_n=10,
        )

    # --- Step 3: Cross-validate with PTM data (kinase->TF links) ---
    # Collect PTM-modified proteins that are known TFs
    ptm_modified_tfs = set()
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes"]:
            for node in net.get(node_type, []):
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", "")
                if gene:
                    ptm_modified_tfs.add(gene.upper())

    # Check which inferred TFs are also PTM-modified (cross-validation)
    inferred_tfs = tf_result_all.get("inferred_tfs", [])
    cross_validated = []
    nonptm_only_tfs = []

    for tf_entry in inferred_tfs:
        tf_name = tf_entry.get("tf", "")
        if tf_name.upper() in ptm_modified_tfs:
            tf_entry["cross_validated"] = True
            tf_entry["validation_type"] = "PTM+NonPTM_convergent"
            cross_validated.append(tf_entry)
        else:
            tf_entry["cross_validated"] = False
            tf_entry["validation_type"] = "NonPTM_inferred_only"
            nonptm_only_tfs.append(tf_entry)

    # --- Step 4: Build LLM context string ---
    lines = [
        "",
        "## TF ACTIVITY INFERENCE FROM NON-PTM PROTEIN DYNAMICS",
        f"(DoRothEA + TRRUST | species={species} | {len(all_changed)} changed proteins analyzed)",
        "",
    ]

    if cross_validated:
        lines.append("### CROSS-VALIDATED TFs (PTM modification + target gene expression convergent)")
        lines.append("These TFs are BOTH post-translationally modified in the PTM data AND their")
        lines.append("known target genes show coordinated abundance changes - HIGH CONFIDENCE axes.")
        lines.append("")
        for tf in cross_validated[:8]:
            pval_str = f"{tf['pvalue']:.2e}" if tf.get('pvalue', 1) < 0.05 else f"{tf.get('pvalue', 1):.2e}"
            lines.append(
                f"  **{tf['tf']}** - {tf['n_overlap']} targets changed "
                f"(p={pval_str}, FDR={tf.get('fdr', 1):.2e}, "
                f"fold={tf.get('fold_enrichment', 0):.1f}x) "
                f"[{tf.get('dominant_mode', 'unknown')}]"
            )
            overlap_genes = tf.get("overlap_genes", [])
            if overlap_genes:
                lines.append(f"    Targets: {', '.join(overlap_genes[:8])}")
        lines.append("")

    if nonptm_only_tfs:
        sig_nonptm = [t for t in nonptm_only_tfs if t.get("fdr", 1) < 0.1]
        if sig_nonptm:
            lines.append("### NON-PTM INFERRED TFs (target gene evidence only, no PTM on TF detected)")
            lines.append("These TFs show target gene activation but NO detectable PTM modification.")
            lines.append("Possible explanations: (1) PTM below detection limit, (2) non-PTM activation,")
            lines.append("(3) constitutively active TF with newly synthesized targets.")
            lines.append("")
            for tf in sig_nonptm[:5]:
                pval_str = f"{tf['pvalue']:.2e}"
                lines.append(
                    f"  {tf['tf']} - {tf['n_overlap']} targets changed "
                    f"(p={pval_str}, FDR={tf.get('fdr', 1):.2e}) "
                    f"[{tf.get('dominant_mode', 'unknown')}]"
                )
            lines.append("")

    # Temporal resolution
    if tf_result_temporal:
        lines.append("### TEMPORAL RESOLUTION OF TF ACTIVITY")
        if "early" in tf_result_temporal:
            early_tfs = tf_result_temporal["early"].get("inferred_tfs", [])
            sig_early = [t for t in early_tfs if t.get("fdr", 1) < 0.1]
            if sig_early:
                lines.append(f"  Early responders (<=15min): {', '.join(t['tf'] for t in sig_early[:5])}")
                lines.append("  -> Likely post-translational activation (no time for transcription)")
        if "late" in tf_result_temporal:
            late_tfs = tf_result_temporal["late"].get("inferred_tfs", [])
            sig_late = [t for t in late_tfs if t.get("fdr", 1) < 0.1]
            if sig_late:
                lines.append(f"  Late responders (>15min): {', '.join(t['tf'] for t in sig_late[:5])}")
                lines.append("  -> Likely transcriptional program activation")
        lines.append("")

    lines.append("### INTERPRETATION GUIDANCE")
    lines.append("- Cross-validated TFs represent HIGH-CONFIDENCE signaling axes")
    lines.append("- Use temporal resolution to distinguish post-translational vs transcriptional mechanisms")
    lines.append("- Discuss PTM->TF->target gene cascades as complete signaling narratives")
    lines.append("- Discordant cases (PTM present but no target activation) suggest non-transcriptional PTM functions")
    lines.append("")

    llm_context = "\n".join(lines)

    # --- Step 5: Build frontend JSON data ---
    tf_inference_data = {
        "species": species,
        "n_changed_proteins": len(all_changed),
        "n_early_changed": len(early_changed),
        "n_late_changed": len(late_changed),
        "all_inferred_tfs": inferred_tfs[:15],
        "cross_validated_tfs": cross_validated[:10],
        "nonptm_only_tfs": [t for t in nonptm_only_tfs if t.get("fdr", 1) < 0.1][:10],
        "temporal_inference": {
            "early": tf_result_temporal.get("early", {}).get("inferred_tfs", [])[:10],
            "late": tf_result_temporal.get("late", {}).get("inferred_tfs", [])[:10],
        },
        "sources": ["DoRothEA (A/B/C)", "TRRUST v2"],
        "ptm_modified_proteins_checked": len(ptm_modified_tfs),
    }

    logger.info(
        f"[v11.8] TF Activity Inference: {len(all_changed)} changed proteins -> "
        f"{len(inferred_tfs)} TFs inferred, {len(cross_validated)} cross-validated, "
        f"context={len(llm_context):,} chars"
    )

    return (llm_context, tf_inference_data)
