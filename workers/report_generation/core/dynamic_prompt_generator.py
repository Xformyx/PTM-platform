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
