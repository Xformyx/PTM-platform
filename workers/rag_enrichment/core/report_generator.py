"""
Comprehensive PTM Report Generator — produces Markdown reports from enriched PTM data.
Ported from ptm-rag-backend/src/comprehensiveReport-v3.ts (v7.8.0 — Multi-PTM Support).

Restored sections:
  - Expression Context (HPA + GTEx + Isoform)
  - Time-Course Trajectory
  - Antibody Validation
  - PTM Novelty Assessment (iPTMnet)
  - Cellular Localization (HPA + UniProt)
  - KEGG Pathways (individual)
  - STRING-DB Interactions (individual)
  - Recent Research Findings
  - Clinical Relevance
  - Regulation Details (upstream/downstream with confidence)
  - Drug Repositioning
  - Kinase Prediction (LLM)
  - Functional Impact (LLM)
  - Classification Criteria (8-category)
  - Global Signaling Pathway Analysis (Common KEGG, Shared Network,
    Temporal Cascade, Signaling Interpretation, Network Summary)
"""

import logging
import math
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ===========================================================================
# Multi-PTM Type Helper Functions (v7.8.0)
# ===========================================================================

def get_modification_verb(modification_type: Optional[str] = None, residue_type: Optional[str] = None) -> str:
    mod = (modification_type or "").lower()
    if "ubiquityl" in mod or "ubiquitin" in mod:
        return "ubiquitylated"
    if "acetyl" in mod:
        return "acetylated"
    if "methyl" in mod:
        return "methylated"
    if "sumo" in mod:
        return "SUMOylated"
    if "phospho" in mod:
        return "phosphorylated"
    if residue_type in ("S", "T", "Y"):
        return "phosphorylated"
    return "modified"


def get_modification_noun(modification_type: Optional[str] = None) -> str:
    mod = (modification_type or "").lower()
    if "ubiquityl" in mod or "ubiquitin" in mod:
        return "ubiquitylation"
    if "acetyl" in mod:
        return "acetylation"
    if "methyl" in mod:
        return "methylation"
    if "sumo" in mod:
        return "SUMOylation"
    if "phospho" in mod:
        return "phosphorylation"
    return "modification"


def get_regulator_terms(modification_type: Optional[str] = None) -> Dict[str, str]:
    mod = (modification_type or "").lower()
    if "ubiquityl" in mod or "ubiquitin" in mod:
        return {"activator": "E3 ubiquitin ligase", "deactivator": "deubiquitinase (DUB)",
                "activator_plural": "E3 ubiquitin ligases", "deactivator_plural": "deubiquitinases (DUBs)"}
    if "acetyl" in mod:
        return {"activator": "acetyltransferase (HAT)", "deactivator": "deacetylase (HDAC)",
                "activator_plural": "acetyltransferases", "deactivator_plural": "deacetylases"}
    if "methyl" in mod:
        return {"activator": "methyltransferase", "deactivator": "demethylase",
                "activator_plural": "methyltransferases", "deactivator_plural": "demethylases"}
    if "sumo" in mod:
        return {"activator": "SUMO ligase", "deactivator": "SUMO protease",
                "activator_plural": "SUMO ligases", "deactivator_plural": "SUMO proteases"}
    return {"activator": "kinase", "deactivator": "phosphatase",
            "activator_plural": "kinases", "deactivator_plural": "phosphatases"}


def is_ubiquitylation(modification_type: Optional[str] = None) -> bool:
    mod = (modification_type or "").lower()
    return "ubiquityl" in mod or "ubiquitin" in mod


def parse_ubiquitin_chain_types(matched_motifs: Optional[str] = None) -> List[Dict[str, object]]:
    if not matched_motifs:
        return []
    chain_info = {
        "K48": {"function": "Proteasomal degradation signal", "is_proteolytic": True},
        "K63": {"function": "Non-proteolytic signaling (NF-κB, DNA damage response)", "is_proteolytic": False},
        "K11": {"function": "Cell cycle regulation (APC/C-mediated degradation)", "is_proteolytic": True},
        "K6":  {"function": "Mitochondrial quality control (Parkin-mediated mitophagy)", "is_proteolytic": False},
        "K27": {"function": "DNA damage response (histone modification)", "is_proteolytic": False},
        "K29": {"function": "Wnt signaling regulation", "is_proteolytic": False},
        "K33": {"function": "TCR signaling and immune response", "is_proteolytic": False},
        "M1":  {"function": "Linear ubiquitin chain (NF-κB activation, inflammation)", "is_proteolytic": False},
        "Mono": {"function": "Endocytosis, localization, histone regulation", "is_proteolytic": False},
    }
    results, seen = [], set()
    for motif in re.split(r"[;|,]", matched_motifs):
        motif_upper = motif.strip().upper()
        for chain_type, info in chain_info.items():
            if chain_type.upper() in motif_upper and chain_type not in seen:
                results.append({"chain_type": chain_type, **info})
                seen.add(chain_type)
    return results


def categorize_ubiquitin_regulators(predicted_regulators: Optional[List[str]] = None) -> Dict[str, List[str]]:
    if not predicted_regulators:
        return {"e3_ligases": [], "dubs": []}
    known_e3 = ["CHIP", "STUB1", "MDM2", "NEDD4", "HUWE1", "APC/C", "SCF", "PARKIN", "PARK2",
                 "ITCH", "WWP1", "WWP2", "SMURF1", "SMURF2", "TRIM", "RNF", "MARCH", "XIAP",
                 "BIRC", "CBL", "VHL", "BRCA1", "BARD1", "UBR", "HERC", "HECTD", "UBE3",
                 "FBXW", "FBXO", "SKP2", "BTRC", "CDC20", "CDH1", "KEAP1", "CUL", "SPOP"]
    known_dub = ["USP", "UCH", "OTU", "OTUD", "OTUB", "CYLD", "A20", "TNFAIP3", "BAP1",
                 "UCHL", "ATXN3", "JOSD", "MINDY", "ZUFSP", "MYSM1", "BRCC36", "COPS5",
                 "PSMD14", "STAMBP", "STAMBPL"]
    e3_ligases, dubs = [], []
    for reg in predicted_regulators:
        reg_upper = reg.upper()
        is_e3 = any(e3.upper() in reg_upper for e3 in known_e3)
        is_dub = any(dub.upper() in reg_upper for dub in known_dub)
        if is_e3 and reg not in e3_ligases:
            e3_ligases.append(reg)
        elif is_dub and reg not in dubs:
            dubs.append(reg)
        elif not is_e3 and not is_dub and reg not in e3_ligases:
            e3_ligases.append(reg)
    return {"e3_ligases": e3_ligases, "dubs": dubs}


def get_classification_interpretation(classification: str, modification_type: Optional[str] = None) -> str:
    is_ubi = is_ubiquitylation(modification_type)
    interps = {
        "PTM-driven hyperactivation": (
            "Strong phosphorylation increase indicates active signaling regulation through kinase activation",
            "Strong ubiquitylation increase suggests enhanced protein degradation (K48) or activated signaling cascade (K63)",
        ),
        "PTM-driven inactivation": (
            "Strong phosphorylation decrease indicates signaling shutdown through phosphatase activity",
            "Strong ubiquitylation decrease suggests protein stabilization through DUB activity or reduced E3 ligase targeting",
        ),
        "Compensatory PTM hyperactivation": (
            "Increased phosphorylation despite decreased protein levels suggests compensatory signaling mechanism",
            "Increased ubiquitylation despite decreased protein levels suggests accelerated clearance of remaining protein pool",
        ),
        "Coupled activation": (
            "Coordinated increase in both protein expression and phosphorylation indicates pathway activation",
            "Coordinated increase in both protein expression and ubiquitylation may indicate quality control mechanism or active signaling",
        ),
        "Coupled shutdown": (
            "Coordinated decrease in both protein expression and phosphorylation indicates pathway downregulation",
            "Coordinated decrease in both protein expression and ubiquitylation indicates reduced protein turnover",
        ),
        "Desensitization-like pattern": (
            "Decreased phosphorylation despite increased protein levels suggests feedback inhibition or desensitization",
            "Decreased ubiquitylation despite increased protein levels suggests protein stabilization and accumulation",
        ),
        "Expression-driven change": (
            "PTM changes primarily reflect protein abundance changes rather than active signaling",
            "Ubiquitylation changes primarily reflect protein abundance changes rather than active targeting",
        ),
        "Baseline / low-change state": (
            "No significant changes in phosphorylation or protein levels",
            "No significant changes in ubiquitylation or protein levels",
        ),
    }
    pair = interps.get(classification)
    if pair:
        return pair[1] if is_ubi else pair[0]
    return "Classification interpretation not available"


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _safe_str(item) -> str:
    """Convert any item to a string, handling dicts and other non-str types."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("name") or item.get("label") or item.get("id") or str(item)
    return str(item)


def _safe_join(sep: str, items) -> str:
    """Join items with separator, converting each to string safely."""
    return sep.join(_safe_str(x) for x in items)


def _fmt_fc(val, decimals: int = 3) -> str:
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "N/A"


def _interpret_log2fc(val) -> str:
    try:
        v = float(val)
    except (ValueError, TypeError):
        return ""
    if v > 2.0:
        return "strongly up-regulated"
    if v > 0.5:
        return "moderately up-regulated"
    if v > 0:
        return "slightly up-regulated"
    if v > -0.5:
        return "slightly down-regulated"
    if v > -2.0:
        return "moderately down-regulated"
    return "strongly down-regulated"


# ===========================================================================
# ComprehensiveReportGenerator
# ===========================================================================

class ComprehensiveReportGenerator:
    """Generates Markdown PTM analysis reports from enriched data."""

    def __init__(self, experimental_context: Optional[dict] = None):
        self.context = experimental_context or {}
        self.citation_counter = 0
        self.citations: List[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_full_report(self, enriched_ptms: List[dict]) -> str:
        """Generate a combined comprehensive report for all enriched PTMs."""
        lines = []

        lines.append("# PTM Comprehensive Analysis Report")
        lines.append(f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        # Experimental context
        if self.context:
            lines.append(self._generate_context_section())

        # Classification criteria
        lines.append(self._generate_classification_criteria())

        # Summary table
        lines.append(self._generate_summary_table(enriched_ptms))

        # Individual PTM sections
        for i, ptm in enumerate(enriched_ptms):
            lines.append(self._generate_ptm_section(ptm, i + 1))

        # Global pathway analysis
        lines.append(self._generate_global_pathway_analysis(enriched_ptms))

        # References
        lines.append(self._generate_references())

        return "\n".join(lines)

    def generate_single_ptm_report(self, ptm: dict) -> str:
        """Generate a standalone report for a single PTM."""
        lines = []
        gene = ptm.get("gene") or ptm.get("Gene.Name", "Unknown")
        position = ptm.get("position") or ptm.get("PTM_Position", "Unknown")

        lines.append(f"# PTM Analysis: {gene} {position}")
        lines.append(f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
        lines.append(self._generate_ptm_section(ptm, 1))
        lines.append(self._generate_references())

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Experimental Context
    # ------------------------------------------------------------------

    def _generate_context_section(self) -> str:
        lines = ["## Experimental Context\n"]
        for key in ("tissue", "organism", "species", "treatment", "condition",
                     "cell_type", "biological_question", "special_conditions"):
            val = self.context.get(key)
            if val:
                lines.append(f"- **{key.replace('_', ' ').title()}**: {val}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Classification Criteria (8-category)
    # ------------------------------------------------------------------

    def _generate_classification_criteria(self) -> str:
        lines = [
            "## PTM Classification Criteria\n",
            "This report uses an **8-category cell-signaling classification system** based on the relationship "
            "between PTM changes (PTM Relative Log2FC) and protein abundance changes (Protein Log2FC).\n",
            "| Category | PTM Change | Protein Change | Significance |",
            "|----------|-----------|----------------|--------------|",
            "| PTM-driven hyperactivation | ↑↑ (>2.0) | Stable | High |",
            "| PTM-driven inactivation | ↓↓ (<-2.0) | Stable | High |",
            "| Compensatory PTM hyperactivation | ↑↑ (>2.0) | ↓ | High |",
            "| Coupled activation | ↑ (>0.5) | ↑ | Moderate |",
            "| Coupled shutdown | ↓ (<-0.5) | ↓ | Moderate |",
            "| Desensitization-like pattern | ↓ (<-0.5) | ↑ | Moderate |",
            "| Expression-driven change | Minimal | ↑ or ↓ | Low |",
            "| Baseline / low-change state | Minimal | Minimal | Low |",
            "",
            "> **Thresholds**: PTM High = |Log2FC| > 2.0, PTM Low = |Log2FC| ≤ 0.5, Protein Change = |Log2FC| > 0.5\n",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Summary Table
    # ------------------------------------------------------------------

    def _generate_summary_table(self, ptms: List[dict]) -> str:
        lines = [
            "## Summary\n",
            f"Total PTM sites analyzed: **{len(ptms)}**\n",
            "| # | Gene | Position | PTM Type | Classification | Protein Log2FC | PTM Relative Log2FC | Significance | Articles |",
            "|---|------|----------|----------|----------------|---------------|---------------------|--------------|----------|",
        ]

        for idx, ptm in enumerate(ptms, 1):
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")
            ptype = ptm.get("ptm_type") or ptm.get("PTM_Type", "?")
            prot_fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
            ptm_fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
            enr = ptm.get("rag_enrichment", {})
            classification = enr.get("classification", {})
            class_label = classification.get("short_label", classification.get("quadrant", "?"))
            significance = classification.get("significance", "?")
            n_articles = enr.get("search_summary", {}).get("total_articles", 0)

            lines.append(
                f"| {idx} | {gene} | {pos} | {ptype} | {class_label} | "
                f"{_fmt_fc(prot_fc)} | {_fmt_fc(ptm_fc)} | {significance} | {n_articles} |"
            )

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Individual PTM Section (FULL — 21 sub-sections)
    # ------------------------------------------------------------------

    def _generate_ptm_section(self, ptm: dict, index: int) -> str:
        gene = ptm.get("gene") or ptm.get("Gene.Name", "Unknown")
        position = ptm.get("position") or ptm.get("PTM_Position", "Unknown")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        enr = ptm.get("rag_enrichment", {})

        lines = [f"\n---\n\n## {index}. {gene} {position} ({ptm_type})\n"]

        # 1. Overview (with classification)
        lines.append(self._generate_overview(ptm, enr))

        # 2. Expression Context (HPA + GTEx + Isoform)
        lines.append(self._generate_expression_context(ptm, enr))

        # 3. Time-Course Trajectory
        lines.append(self._generate_trajectory_section(ptm, enr))

        # 4. Antibody Validation
        lines.append(self._generate_antibody_validation(gene, enr))

        # 5. PTM Novelty Assessment
        lines.append(self._generate_novelty_assessment(gene, position, ptm_type, enr))

        # 6. Cellular Localization
        lines.append(self._generate_cellular_localization(gene, enr))

        # 7. Literature Evidence (categorized)
        lines.append(self._generate_literature_evidence(enr))

        # 8. Biological Interpretation
        lines.append(self._generate_biological_interpretation(ptm, enr))

        # 9. Quantitative Data
        lines.append(self._generate_quantitative_data(ptm))

        # 10. Regulatory Network
        lines.append(self._generate_regulatory_network(gene, enr, ptm_type))

        # 11. KEGG Pathways (individual)
        lines.append(self._generate_kegg_pathways(gene, enr))

        # 12. STRING-DB Interactions (individual)
        lines.append(self._generate_stringdb_interactions(gene, enr))

        # 13. Recent Research Findings
        lines.append(self._generate_recent_findings(gene, enr))

        # 14. Clinical Relevance
        lines.append(self._generate_clinical_relevance(gene, enr))

        # 15. Regulation Details
        lines.append(self._generate_regulation_details(gene, enr, ptm_type))

        # 16. Drug Repositioning
        lines.append(self._generate_drug_repositioning(gene, enr))

        # 17. Kinase Prediction (LLM)
        lines.append(self._generate_kinase_prediction(gene, position, enr, ptm_type))

        # 18. Functional Impact (LLM)
        lines.append(self._generate_functional_impact(gene, position, enr))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 1. Overview
    # ------------------------------------------------------------------

    def _generate_overview(self, ptm: dict, enr: dict) -> str:
        lines = ["### Overview\n"]

        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        position = ptm.get("position") or ptm.get("PTM_Position", "?")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        condition = ptm.get("Condition") or ptm.get("condition", "")

        classification = enr.get("classification", {})
        class_level = classification.get("level", "unknown")
        short_label = classification.get("short_label", "?")
        significance = classification.get("significance", "?")
        protein_context = classification.get("protein_context", "?")

        prot_fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
        ptm_fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
        ptm_abs_fc = ptm.get("ptm_absolute_log2fc") or ptm.get("PTM_Absolute_Log2FC", "")

        mod_noun = get_modification_noun(ptm_type)
        interp = get_classification_interpretation(class_level, ptm_type)

        n_articles = enr.get("search_summary", {}).get("total_articles", 0)
        evidence_count = enr.get("regulation", {}).get("evidence_count", 0)

        # Overview table
        lines.append("| Property | Value |")
        lines.append("|----------|-------|")
        lines.append(f"| Gene | {gene} |")
        lines.append(f"| PTM Site | {position} |")
        lines.append(f"| PTM Type | {ptm_type} |")
        if condition:
            lines.append(f"| Condition | {condition} |")
        lines.append(f"| Classification | **{class_level}** ({short_label}) |")
        lines.append(f"| Significance | {significance} |")
        lines.append(f"| Protein Log2FC | {_fmt_fc(prot_fc)} ({_interpret_log2fc(prot_fc)}) |")
        lines.append(f"| PTM Relative Log2FC | {_fmt_fc(ptm_fc)} ({_interpret_log2fc(ptm_fc)}) |")
        if ptm_abs_fc:
            lines.append(f"| PTM Absolute Log2FC | {_fmt_fc(ptm_abs_fc)} |")
        lines.append(f"| Protein Context | {protein_context} |")
        lines.append(f"| Evidence Level | {n_articles} articles, {evidence_count} regulatory patterns |")
        lines.append("")

        # Interpretation
        lines.append(f"**Interpretation**: {interp}\n")

        # Function summary
        func_summary = enr.get("function_summary", "")
        if func_summary:
            lines.append(f"**Protein Function**: {func_summary[:600]}\n")

        # Localization (brief)
        loc = enr.get("localization", [])
        if loc:
            lines.append(f"**Subcellular Localization**: {_safe_join(', ', loc[:5])}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 2. Expression Context (HPA + GTEx + Isoform)
    # ------------------------------------------------------------------

    def _generate_expression_context(self, ptm: dict, enr: dict) -> str:
        lines = ["### Expression Context\n"]

        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        prot_fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
        ptm_fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
        ptm_abs_fc = ptm.get("ptm_absolute_log2fc") or ptm.get("PTM_Absolute_Log2FC", "")

        # Protein Level Changes
        lines.append("#### Protein Level Changes\n")
        try:
            prot_fc_val = float(prot_fc)
            fold_change = 2 ** abs(prot_fc_val)
            direction = "increased" if prot_fc_val > 0 else "decreased"
            lines.append(f"- **Protein Log2FC**: {_fmt_fc(prot_fc)} ({direction} by {fold_change:.2f}-fold)")
        except (ValueError, TypeError):
            lines.append(f"- **Protein Log2FC**: {prot_fc}")

        prot_fold = ptm.get("Protein_Fold_Change") or ptm.get("protein_fold_change")
        if prot_fold:
            lines.append(f"- **Protein Fold Change**: {_fmt_fc(prot_fold)}")

        prot_pval = ptm.get("Protein_PValue") or ptm.get("protein_pvalue")
        if prot_pval:
            lines.append(f"- **Protein p-value**: {_fmt_fc(prot_pval, 6)}")
        lines.append("")

        # PTM Quantification
        lines.append("#### PTM Quantification\n")
        try:
            ptm_fc_val = float(ptm_fc)
            ptm_fold = 2 ** abs(ptm_fc_val)
            ptm_dir = "increased" if ptm_fc_val > 0 else "decreased"
            lines.append(f"- **PTM Relative Log2FC**: {_fmt_fc(ptm_fc)} ({ptm_dir} by {ptm_fold:.2f}-fold)")
        except (ValueError, TypeError):
            lines.append(f"- **PTM Relative Log2FC**: {ptm_fc}")

        if ptm_abs_fc:
            lines.append(f"- **PTM Absolute Log2FC**: {_fmt_fc(ptm_abs_fc)}")

        ptm_pval = ptm.get("PTM_PValue") or ptm.get("ptm_pvalue")
        if ptm_pval:
            lines.append(f"- **PTM p-value**: {_fmt_fc(ptm_pval, 6)}")
        lines.append("")

        # HPA RNA Expression
        hpa = enr.get("hpa", {})
        if hpa and not hpa.get("error"):
            has_hpa_data = False

            # RNA tissue expression (keys: tissue_expression from local, rna_tissue from MCP)
            rna_tissue = hpa.get("tissue_expression", hpa.get("rna_tissue", []))
            if rna_tissue:
                has_hpa_data = True
                lines.append("#### RNA Expression (Human Protein Atlas)\n")
                lines.append("| Tissue | nTPM | Detection |")
                lines.append("|--------|------|-----------|")
                for entry in rna_tissue[:10]:
                    tissue = entry.get("tissue", "?")
                    ntpm = entry.get("tpm") or entry.get("value") or entry.get("nTPM", "?")
                    detection = entry.get("level") or entry.get("detection", "?")
                    lines.append(f"| {tissue} | {ntpm} | {detection} |")
                lines.append("")

            # Top tissues summary
            top_tissues = hpa.get("top_tissues", [])
            if top_tissues and not rna_tissue:
                has_hpa_data = True
                lines.append("#### Top Tissue Expression (HPA)\n")
                for t in top_tissues[:5]:
                    tissue = t.get("tissue", "?")
                    tpm = t.get("tpm", "?")
                    lines.append(f"- **{tissue}**: {tpm} nTPM")
                lines.append("")

            protein_tissue = hpa.get("protein_tissue", [])
            if protein_tissue:
                has_hpa_data = True
                lines.append("**Protein Expression (IHC)**:\n")
                for entry in protein_tissue[:5]:
                    tissue = entry.get("tissue", "?")
                    level = entry.get("level", "?")
                    lines.append(f"- {tissue}: {level}")
                lines.append("")

            # Subcellular location (keys: locations from local, subcellular_location from MCP)
            subcellular = hpa.get("locations", hpa.get("subcellular_location", []))
            if subcellular:
                has_hpa_data = True
                lines.append(f"**HPA Subcellular Location**: {', '.join(str(s) for s in subcellular[:5])}\n")

            if hpa.get("source"):
                lines.append(f"*Data source: {hpa['source']}*\n")

        # GTEx Tissue Expression
        gtex = enr.get("gtex", {})
        if gtex:
            lines.append("#### Tissue Expression (GTEx)\n")
            expressions = gtex.get("expressions", gtex.get("tissues", []))
            if expressions:
                lines.append("| Tissue | Median TPM |")
                lines.append("|--------|-----------|")
                for entry in expressions[:10]:
                    tissue = entry.get("tissue") or entry.get("tissueSiteDetailId", "?")
                    tpm = entry.get("median_tpm") or entry.get("median", "?")
                    lines.append(f"| {tissue} | {_fmt_fc(tpm, 2)} |")
                lines.append("")

        # Protein Isoforms
        isoform_info = enr.get("isoform_info", [])
        if isoform_info:
            lines.append("#### Protein Isoforms\n")
            for iso in isoform_info[:5]:
                name = iso.get("name") or iso.get("isoform_id", "?")
                sequence_length = iso.get("sequence_length") or iso.get("length", "?")
                note = iso.get("note") or iso.get("description", "")
                lines.append(f"- **{name}**: {sequence_length} aa")
                if note:
                    lines.append(f"  - {note}")
            lines.append("")

        hpa_has_data = bool(hpa and not hpa.get("error") and
                           (hpa.get("tissue_expression") or hpa.get("rna_tissue") or
                            hpa.get("locations") or hpa.get("subcellular_location") or
                            hpa.get("top_tissues")))
        gtex_has_data = bool(gtex and not gtex.get("error") and
                            (gtex.get("expressions") or gtex.get("tissues")))
        if not hpa_has_data and not gtex_has_data and not isoform_info:
            lines.append(f"No expression context data available from HPA or GTEx for **{gene}**.\n")
            lines.append(f"Consider checking [Human Protein Atlas](https://www.proteinatlas.org/{gene}) "
                         f"or [GTEx Portal](https://gtexportal.org/home/gene/{gene}) for expression data.\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 3. Time-Course Trajectory
    # ------------------------------------------------------------------

    def _generate_trajectory_section(self, ptm: dict, enr: dict) -> str:
        trajectory = enr.get("trajectory", {})
        timepoints = trajectory.get("timepoints", [])
        trend = trajectory.get("trend", "unknown")

        if not timepoints or len(timepoints) < 2:
            return ""

        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        position = ptm.get("position") or ptm.get("PTM_Position", "?")

        lines = ["### Time-Course Trajectory\n"]

        lines.append("| Time Point | PTM Log2FC | Protein Log2FC | Classification |")
        lines.append("|-----------|-----------|----------------|----------------|")
        for tp in timepoints:
            label = tp.get("timeLabel", "?")
            ptm_fc = _fmt_fc(tp.get("ptmLog2FC", 0))
            prot_fc = _fmt_fc(tp.get("proteinLog2FC", 0))
            cls = tp.get("classification", "")
            lines.append(f"| {label} | {ptm_fc} | {prot_fc} | {cls} |")

        lines.append(f"\n**Temporal Trend**: {trend.replace('_', ' ').title()}")

        # Trend interpretation
        trend_interps = {
            "increasing": f"The {get_modification_noun(ptm.get('ptm_type'))} at {gene} {position} shows a progressive increase over time, suggesting sustained signaling activation.",
            "decreasing": f"The {get_modification_noun(ptm.get('ptm_type'))} at {gene} {position} shows a progressive decrease over time, indicating gradual signaling attenuation.",
            "transient_peak": f"The {get_modification_noun(ptm.get('ptm_type'))} at {gene} {position} shows a transient peak followed by decline, consistent with an acute signaling response.",
            "transient_dip": f"The {get_modification_noun(ptm.get('ptm_type'))} at {gene} {position} shows a transient dip followed by recovery, suggesting a biphasic response.",
            "stable": f"The {get_modification_noun(ptm.get('ptm_type'))} at {gene} {position} remains relatively stable across time points.",
        }
        if trend in trend_interps:
            lines.append(f"\n{trend_interps[trend]}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 4. Antibody Validation
    # ------------------------------------------------------------------

    def _generate_antibody_validation(self, gene: str, enr: dict) -> str:
        # Extract from fulltext_analysis or abstract_analysis
        fulltext = enr.get("fulltext_analysis", {})
        abstract = enr.get("abstract_analysis", {})

        antibody_info = fulltext.get("antibody_info", []) or abstract.get("antibody_info", [])
        wb_detected = fulltext.get("western_blot_detected", False) or abstract.get("western_blot_detected", False)

        if not antibody_info and not wb_detected:
            return ""

        lines = ["### Antibody Validation\n"]

        if wb_detected:
            lines.append(f"Western blot validation for {gene} was detected in the literature.\n")

        if antibody_info:
            lines.append("| Target | Company | Catalog # | Species | Application | Confidence |")
            lines.append("|--------|---------|-----------|---------|-------------|------------|")
            for ab in antibody_info[:5]:
                target = ab.get("target", gene)
                company = ab.get("company", "N/A")
                catalog = ab.get("catalog", "N/A")
                species = ab.get("species", "N/A")
                app = ab.get("application", "N/A")
                confidence = ab.get("confidence", "Medium")
                lines.append(f"| {target} | {company} | {catalog} | {species} | {app} | {confidence} |")
            lines.append("")
        else:
            lines.append("Specific antibody details could not be extracted from available literature.\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 5. PTM Novelty Assessment
    # ------------------------------------------------------------------

    def _generate_novelty_assessment(self, gene: str, position: str, ptm_type: str, enr: dict) -> str:
        validation = enr.get("ptm_validation", {})
        if not validation:
            return ""

        lines = ["### PTM Novelty Assessment\n"]

        is_known = validation.get("is_known", None)
        novelty_score = validation.get("novelty_score", None)
        sources = validation.get("sources", [])
        evidence = validation.get("evidence", [])

        if is_known is True:
            lines.append(f"**Status**: This {get_modification_noun(ptm_type)} at {gene} {position} is a **known/previously reported** PTM site.\n")
        elif is_known is False:
            lines.append(f"**Status**: This {get_modification_noun(ptm_type)} at {gene} {position} appears to be a **novel/unreported** PTM site.\n")
        else:
            lines.append(f"**Status**: Novelty assessment could not be determined for {gene} {position}.\n")

        if novelty_score is not None:
            lines.append(f"**Novelty Score**: {novelty_score}/100 (higher = more novel)\n")

        if sources:
            lines.append("**Database Sources**:\n")
            for src in sources:
                db = src.get("database", "?")
                found = src.get("found", False)
                details = src.get("details", "")
                status = "Found" if found else "Not found"
                lines.append(f"- **{db}**: {status}")
                if details:
                    lines.append(f"  - {details}")
            lines.append("")

        if evidence:
            lines.append("**Key Publications**:\n")
            for ev in evidence[:3]:
                pmid = ev.get("pmid", "")
                title = ev.get("title", "")
                year = ev.get("year", "")
                self.citation_counter += 1
                self.citations.append({"number": self.citation_counter, "pmid": pmid, "title": title, "journal": ev.get("journal", ""), "pub_date": year})
                lines.append(f"- {title} ({year}) [{self.citation_counter}]")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 6. Cellular Localization
    # ------------------------------------------------------------------

    def _generate_cellular_localization(self, gene: str, enr: dict) -> str:
        loc = enr.get("localization", [])
        hpa = enr.get("hpa", {})
        go_cc = enr.get("go_terms", {}).get("cellular_component", [])

        if not loc and not hpa and not go_cc:
            return ""

        lines = ["### Cellular Localization\n"]

        # HPA subcellular data (handle both local and MCP key formats)
        hpa_locations = hpa.get("locations", hpa.get("subcellular_location", []))
        hpa_main = hpa.get("main_location", [])
        hpa_additional = hpa.get("additional_location", [])
        hpa_single_cell = hpa.get("single_cell_variation", [])

        if hpa_main or hpa_locations:
            lines.append("**Human Protein Atlas**:\n")
            if hpa_main:
                lines.append(f"- Main location: {', '.join(str(x) for x in hpa_main)}")
            elif hpa_locations:
                lines.append(f"- Subcellular location: {', '.join(str(x) for x in hpa_locations[:5])}")
            if hpa_additional:
                lines.append(f"- Additional locations: {', '.join(str(x) for x in hpa_additional)}")
            if hpa_single_cell:
                lines.append(f"- Single-cell variation: {', '.join(str(x) for x in hpa_single_cell[:3])}")
            lines.append(f"- [View HPA images](https://www.proteinatlas.org/{gene}/subcellular)")
            lines.append("")

        # UniProt localization
        if loc:
            lines.append("**UniProt Localization**:\n")
            for l in loc[:5]:
                lines.append(f"- {l}")
            lines.append("")

        # GO Cellular Component
        if go_cc:
            lines.append(f"**GO Cellular Component**: {_safe_join('; ', go_cc[:5])}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 7. Literature Evidence (categorized)
    # ------------------------------------------------------------------

    def _generate_literature_evidence(self, enr: dict) -> str:
        findings = enr.get("recent_findings", [])
        if not findings:
            # Still show classification-based interpretation even without literature
            classification = enr.get("classification", {})
            class_level = classification.get("level", "unknown")
            significance = classification.get("significance", "Low")
            return ("### Literature Evidence\n\n"
                    f"No relevant literature found in PubMed for this specific PTM site.\n\n"
                    f"**Classification**: {class_level} (Significance: {significance})\n\n"
                    f"This classification is based on quantitative PTM and protein abundance changes. "
                    f"Further manual literature search may reveal additional context.\n")

        lines = [
            "### Literature Evidence\n",
            f"Found **{len(findings)}** relevant articles:\n",
        ]

        # Categorize articles based on regulation evidence
        reg_evidence = enr.get("regulation", {}).get("regulation_evidence", [])
        activation_articles = []
        inhibition_articles = []
        other_articles = []

        article_categories = {}
        for ev in reg_evidence:
            pmid = ev.get("pmid", "")
            ev_type = (ev.get("type") or "").lower()
            if "activat" in ev_type or "phosphorylat" in ev_type or "upregulat" in ev_type:
                article_categories[pmid] = "activation"
            elif "inhibit" in ev_type or "dephosphorylat" in ev_type or "downregulat" in ev_type:
                article_categories[pmid] = "inhibition"

        for article in findings:
            pmid = article.get("pmid", "")
            cat = article_categories.get(pmid, "other")
            if cat == "activation":
                activation_articles.append(article)
            elif cat == "inhibition":
                inhibition_articles.append(article)
            else:
                other_articles.append(article)

        # Print categorized articles
        if activation_articles:
            lines.append("#### Activation / Phosphorylation Evidence\n")
            for a in activation_articles[:4]:
                lines.append(self._format_article(a))

        if inhibition_articles:
            lines.append("#### Inhibition / Dephosphorylation Evidence\n")
            for a in inhibition_articles[:4]:
                lines.append(self._format_article(a))

        if other_articles:
            label = "#### General Evidence\n" if (activation_articles or inhibition_articles) else ""
            if label:
                lines.append(label)
            for a in other_articles[:6]:
                lines.append(self._format_article(a))

        return "\n".join(lines)

    def _format_article(self, article: dict) -> str:
        pmid = article.get("pmid", "")
        title = _clean_text(article.get("title", ""))
        journal = article.get("journal", "")
        pub_date = article.get("pub_date", "")
        score = article.get("relevance_score", 0)
        excerpt = _clean_text(article.get("abstract_excerpt") or article.get("abstract", ""))

        self.citation_counter += 1
        self.citations.append({
            "number": self.citation_counter, "pmid": pmid, "title": title,
            "journal": journal, "pub_date": pub_date,
            "authors": article.get("authors", []), "doi": article.get("doi", ""),
        })

        result = f"**{title}** [{self.citation_counter}]\n"
        result += f"*{journal}* ({pub_date}) | Relevance: {score}/100 | PMID: {pmid}\n"
        if excerpt:
            result += f"> {excerpt[:250]}...\n"
        result += "\n"
        return result

    # ------------------------------------------------------------------
    # 8. Biological Interpretation
    # ------------------------------------------------------------------

    def _generate_biological_interpretation(self, ptm: dict, enr: dict) -> str:
        lines = ["### Biological Interpretation\n"]

        classification = enr.get("classification", {})
        class_level = classification.get("level", "unknown")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        position = ptm.get("position") or ptm.get("PTM_Position", "?")
        mod_noun = get_modification_noun(ptm_type)

        interp = get_classification_interpretation(class_level, ptm_type)
        lines.append(f"The {mod_noun} at {gene} {position} is classified as **{class_level}**.\n")
        lines.append(f"{interp}\n")

        # Abstract analysis (LLM) results
        abstract_analysis = enr.get("abstract_analysis", {})
        if abstract_analysis:
            mechanism = abstract_analysis.get("mechanism_summary", "")
            if mechanism:
                lines.append(f"**Mechanism Summary** (from literature analysis):\n{mechanism}\n")

            context_relevance = abstract_analysis.get("context_relevance", "")
            if context_relevance:
                lines.append(f"**Context Relevance**: {context_relevance}\n")

        # Functional impact (LLM) summary
        fi = enr.get("functional_impact", {})
        if fi:
            impact_summary = fi.get("impact_summary", "")
            if impact_summary:
                lines.append(f"**Functional Impact**: {impact_summary}\n")

        # Disease associations
        diseases = enr.get("diseases", [])
        if diseases:
            lines.append(f"**Disease Associations**: {_safe_join(', ', diseases)}\n")

        # Evidence count
        evidence_count = enr.get("regulation", {}).get("evidence_count", 0)
        if evidence_count > 0:
            lines.append(f"Pattern-based analysis identified **{evidence_count}** regulatory relationships from the literature.\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 9. Quantitative Data
    # ------------------------------------------------------------------

    def _generate_quantitative_data(self, ptm: dict) -> str:
        lines = ["### Quantitative Data\n"]

        data_fields = [
            ("Protein.Group", "Protein Group"),
            ("Protein.Name", "Protein Name"),
            ("Gene.Name", "Gene"),
            ("Modified.Sequence", "Modified Sequence"),
            ("PTM_Position", "PTM Position"),
            ("PTM_Type", "PTM Type"),
            ("Condition", "Condition"),
            ("Protein_Log2FC", "Protein Log2FC"),
            ("PTM_Relative_Log2FC", "PTM Relative Log2FC"),
            ("PTM_Absolute_Log2FC", "PTM Absolute Log2FC"),
            ("Protein_Fold_Change", "Protein Fold Change"),
            ("Protein_PValue", "Protein p-value"),
            ("PTM_PValue", "PTM p-value"),
            ("Sample_Size", "Sample Size"),
        ]

        lines.append("| Field | Value |")
        lines.append("|-------|-------|")

        for key, label in data_fields:
            val = ptm.get(key)
            if val is not None:
                if isinstance(val, float):
                    lines.append(f"| {label} | {val:.4f} |")
                else:
                    lines.append(f"| {label} | {val} |")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 10. Regulatory Network
    # ------------------------------------------------------------------

    def _generate_regulatory_network(self, gene: str, enr: dict, ptm_type: str = "Phosphorylation") -> str:
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        downstream = reg.get("downstream_targets", [])
        ks = reg.get("kinase_substrate", [])
        interactions = enr.get("string_interactions", [])
        pathways = enr.get("pathways", [])
        terms = get_regulator_terms(ptm_type)

        lines = ["### Regulatory Network\n"]

        if upstream:
            lines.append(f"**Upstream Regulators ({terms['activator_plural']})**: {_safe_join(', ', upstream[:8])}\n")
        if downstream:
            lines.append(f"**Downstream Targets**: {_safe_join(', ', downstream[:8])}\n")

        if ks:
            ks_label = f"{terms['activator'].title()}-Substrate Relationships"
            lines.append(f"**{ks_label}**:\n")
            for rel in ks[:5]:
                lines.append(f"- {rel.get('kinase', '?')} → {rel.get('substrate', '?')} (PMID: {rel.get('pmid', '?')})")
            lines.append("")

        if pathways:
            pw_names = [p.get("name", p) if isinstance(p, dict) else str(p) for p in pathways[:5]]
            lines.append(f"**KEGG Pathways**: {_safe_join(', ', pw_names)}\n")

        if interactions:
            lines.append(f"**STRING-DB Interaction Partners**: {_safe_join(', ', interactions[:5])}\n")

        # Ubiquitylation-specific sections
        if is_ubiquitylation(ptm_type):
            matched_motifs = enr.get("matched_motifs", "")
            chain_types = parse_ubiquitin_chain_types(matched_motifs)
            if chain_types:
                lines.append("**Ubiquitin Chain Type Analysis**:\n")
                for ct in chain_types:
                    prot_label = "proteolytic" if ct.get("is_proteolytic") else "non-proteolytic"
                    lines.append(f"- **{ct['chain_type']}**: {ct['function']} ({prot_label})")
                lines.append("")

            predicted_regs = enr.get("predicted_regulators", [])
            cats = categorize_ubiquitin_regulators(predicted_regs)
            if cats["e3_ligases"] or cats["dubs"]:
                lines.append("**E3 Ligase / DUB Regulatory Network**:\n")
                if cats["e3_ligases"]:
                    lines.append(f"- E3 Ligases: {', '.join(cats['e3_ligases'])}")
                if cats["dubs"]:
                    lines.append(f"- DUBs: {', '.join(cats['dubs'])}")
                lines.append("")

        # GO terms
        go = enr.get("go_terms", {})
        bp = go.get("biological_process", [])
        mf = go.get("molecular_function", [])
        if bp:
            lines.append(f"**GO Biological Process**: {_safe_join('; ', bp[:3])}\n")
        if mf:
            lines.append(f"**GO Molecular Function**: {_safe_join('; ', mf[:3])}\n")

        if not upstream and not downstream and not ks and not pathways:
            lines.append("No regulatory information found from literature analysis.\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 11. KEGG Pathways (individual)
    # ------------------------------------------------------------------

    def _generate_kegg_pathways(self, gene: str, enr: dict) -> str:
        pathways = enr.get("pathways", [])
        if not pathways:
            return ""

        lines = ["### KEGG Pathways\n"]
        lines.append(f"**{gene}** is involved in the following KEGG pathways:\n")

        for pw in pathways[:10]:
            if isinstance(pw, dict):
                pw_id = pw.get("id", "")
                pw_name = pw.get("name", "")
                lines.append(f"- **{pw_name}** ({pw_id})")
            else:
                lines.append(f"- {pw}")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 12. STRING-DB Interactions (individual)
    # ------------------------------------------------------------------

    def _generate_stringdb_interactions(self, gene: str, enr: dict) -> str:
        string_db = enr.get("string_db", {})
        interactions = string_db.get("interactions", [])
        if not interactions:
            return ""

        lines = ["### STRING-DB Protein Interactions\n"]
        lines.append(f"Top interaction partners for **{gene}**:\n")
        lines.append("| Partner | Score | Evidence Types |")
        lines.append("|---------|-------|----------------|")

        for inter in interactions[:10]:
            partner = inter.get("partner", "?")
            score = inter.get("score", 0)
            evidence = inter.get("evidence", [])
            ev_str = _safe_join(", ", evidence[:3]) if evidence else "N/A"
            lines.append(f"| {partner} | {score} | {ev_str} |")

        lines.append(f"\n[View full network on STRING-DB](https://string-db.org/network/{gene})\n")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 13. Recent Research Findings
    # ------------------------------------------------------------------

    def _generate_recent_findings(self, gene: str, enr: dict) -> str:
        findings = enr.get("recent_findings", [])
        if not findings:
            return ""

        # Filter for recent articles (last 3 years)
        recent = [f for f in findings if _is_recent(f.get("pub_date", ""), years=3)]
        if not recent:
            return ""

        lines = ["### Recent Research Findings\n"]
        lines.append(f"Recent publications (last 3 years) related to **{gene}**:\n")

        for article in recent[:5]:
            title = _clean_text(article.get("title", ""))
            journal = article.get("journal", "")
            pub_date = article.get("pub_date", "")
            pmid = article.get("pmid", "")
            abstract = _clean_text(article.get("abstract", article.get("abstract_excerpt", "")))

            self.citation_counter += 1
            self.citations.append({
                "number": self.citation_counter, "pmid": pmid, "title": title,
                "journal": journal, "pub_date": pub_date,
            })

            lines.append(f"- **{title}** [{self.citation_counter}]")
            lines.append(f"  *{journal}* ({pub_date}) | PMID: {pmid}")
            if abstract:
                lines.append(f"  > {abstract[:200]}...")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 14. Clinical Relevance
    # ------------------------------------------------------------------

    def _generate_clinical_relevance(self, gene: str, enr: dict) -> str:
        diseases = enr.get("diseases", [])
        fi = enr.get("functional_impact", {})
        clinical_notes = fi.get("clinical_relevance", "")

        if not diseases and not clinical_notes:
            return ""

        lines = ["### Clinical Relevance\n"]

        if diseases:
            lines.append(f"**{gene}** has been associated with the following diseases:\n")
            for d in diseases:
                lines.append(f"- {_safe_str(d).title()}")
            lines.append("")

        if clinical_notes:
            lines.append(f"**Clinical Notes**: {clinical_notes}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 15. Regulation Details
    # ------------------------------------------------------------------

    def _generate_regulation_details(self, gene: str, enr: dict, ptm_type: str) -> str:
        reg = enr.get("regulation", {})
        evidence = reg.get("regulation_evidence", [])
        if not evidence:
            return ""

        terms = get_regulator_terms(ptm_type)
        lines = ["### Regulation Details\n"]

        lines.append("| Type | Regulator | Target | Evidence | PMID | Confidence |")
        lines.append("|------|-----------|--------|----------|------|------------|")

        for ev in evidence[:15]:
            ev_type = ev.get("type", "?")
            regulator = ev.get("regulator", "?")
            target = ev.get("target", gene)
            text = _clean_text(ev.get("evidence_text", ""))[:80]
            pmid = ev.get("pmid", "?")
            confidence = ev.get("confidence", "Medium")
            lines.append(f"| {ev_type} | {regulator} | {target} | {text}... | {pmid} | {confidence} |")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 16. Drug Repositioning
    # ------------------------------------------------------------------

    def _generate_drug_repositioning(self, gene: str, enr: dict) -> str:
        fi = enr.get("functional_impact", {})
        drugs = fi.get("drug_targets", [])
        abstract = enr.get("abstract_analysis", {})
        drug_mentions = abstract.get("drug_mentions", [])

        if not drugs and not drug_mentions:
            return ""

        lines = ["### Drug Repositioning\n"]

        if drugs:
            lines.append(f"Potential drug targets related to **{gene}**:\n")
            for drug in drugs[:5]:
                if isinstance(drug, dict):
                    name = drug.get("name", "?")
                    mechanism = drug.get("mechanism", "")
                    status = drug.get("status", "")
                    lines.append(f"- **{name}**: {mechanism}")
                    if status:
                        lines.append(f"  - Status: {status}")
                else:
                    lines.append(f"- {drug}")
            lines.append("")

        if drug_mentions:
            lines.append("**Drug Mentions in Literature**:\n")
            for dm in drug_mentions[:5]:
                lines.append(f"- {dm}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 17. Kinase Prediction (LLM)
    # ------------------------------------------------------------------

    def _generate_kinase_prediction(self, gene: str, position: str, enr: dict, ptm_type: str) -> str:
        kp = enr.get("kinase_prediction", {})
        if not kp:
            return ""

        lines = ["### Kinase / Regulator Prediction\n"]

        predicted = kp.get("predicted_kinases", kp.get("predicted_regulators", []))
        confidence = kp.get("confidence", "")
        reasoning = kp.get("reasoning", "")

        terms = get_regulator_terms(ptm_type)

        if predicted:
            lines.append(f"**Predicted {terms['activator_plural'].title()}** for {gene} {position}:\n")
            for k in predicted[:5]:
                if isinstance(k, dict):
                    name = k.get("name", "?")
                    score = k.get("score", "")
                    evidence = k.get("evidence", "")
                    lines.append(f"- **{name}** (score: {score})")
                    if evidence:
                        lines.append(f"  - Evidence: {evidence}")
                else:
                    lines.append(f"- **{k}**")
            lines.append("")

        if confidence:
            lines.append(f"**Prediction Confidence**: {confidence}\n")

        if reasoning:
            lines.append(f"**Reasoning**: {reasoning}\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 18. Functional Impact (LLM)
    # ------------------------------------------------------------------

    def _generate_functional_impact(self, gene: str, position: str, enr: dict) -> str:
        fi = enr.get("functional_impact", {})
        if not fi:
            return ""

        lines = ["### Functional Impact Analysis\n"]

        impact_summary = fi.get("impact_summary", "")
        structural_effect = fi.get("structural_effect", "")
        signaling_effect = fi.get("signaling_effect", "")
        confidence = fi.get("confidence", "")

        if impact_summary:
            lines.append(f"**Impact Summary**: {impact_summary}\n")
        if structural_effect:
            lines.append(f"**Structural Effect**: {structural_effect}\n")
        if signaling_effect:
            lines.append(f"**Signaling Effect**: {signaling_effect}\n")
        if confidence:
            lines.append(f"**Analysis Confidence**: {confidence}\n")

        return "\n".join(lines)

    # ==================================================================
    # Global Pathway Analysis (FULL)
    # ==================================================================

    def _generate_global_pathway_analysis(self, ptms: List[dict]) -> str:
        lines = ["\n---\n\n## Global Signaling Pathway Analysis\n"]

        # Collect global data
        global_data = self._collect_global_pathway_data(ptms)

        # 1. Analyzed PTMs Overview
        lines.append("### Analyzed PTMs Overview\n")
        lines.append(f"Total PTM sites: **{len(ptms)}**\n")

        # Classification distribution
        class_counts = global_data["classification_counts"]
        if class_counts:
            lines.append("| Classification | Count | Significance |")
            lines.append("|---------------|-------|--------------|")
            sig_map = {
                "PTM-driven hyperactivation": "High",
                "PTM-driven inactivation": "High",
                "Compensatory PTM hyperactivation": "High",
                "Coupled activation": "Moderate",
                "Coupled shutdown": "Moderate",
                "Desensitization-like pattern": "Moderate",
                "Expression-driven change": "Low",
                "Baseline / low-change state": "Low",
            }
            for cls, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
                sig = sig_map.get(cls, "?")
                lines.append(f"| {cls} | {cnt} | {sig} |")
            lines.append("")

        # 2. Common KEGG Pathways
        pathway_counts = global_data["pathway_counts"]
        if pathway_counts:
            lines.append("### Common KEGG Pathways\n")
            lines.append("Pathways shared across multiple PTM sites:\n")
            lines.append("| Pathway | PTM Sites | Genes |")
            lines.append("|---------|-----------|-------|")
            for pw, info in sorted(pathway_counts.items(), key=lambda x: -x[1]["count"])[:15]:
                genes = ", ".join(sorted(info["genes"])[:5])
                lines.append(f"| {pw} | {info['count']} | {genes} |")
            lines.append("")

        # 3. Shared Protein Interaction Network
        interaction_counts = global_data["interaction_counts"]
        if interaction_counts:
            lines.append("### Shared Protein Interaction Network\n")
            lines.append("Proteins that interact with multiple PTM-bearing proteins:\n")
            lines.append("| Interaction Partner | Connected PTM Proteins | Connections |")
            lines.append("|--------------------|-----------------------|-------------|")
            for partner, info in sorted(interaction_counts.items(), key=lambda x: -x[1]["count"])[:15]:
                genes = ", ".join(sorted(info["genes"])[:5])
                lines.append(f"| {partner} | {genes} | {info['count']} |")
            lines.append("")

        # 4. Temporal Signaling Cascade
        temporal_data = global_data["temporal_data"]
        if temporal_data:
            lines.append("### Temporal Signaling Cascade\n")
            lines.append("Time-course analysis of PTM changes across conditions:\n")
            for time_label, entries in sorted(temporal_data.items()):
                lines.append(f"\n**{time_label}**:\n")
                for entry in entries[:10]:
                    gene = entry.get("gene", "?")
                    pos = entry.get("position", "?")
                    ptm_fc = _fmt_fc(entry.get("ptm_log2fc", 0))
                    cls = entry.get("classification", "?")
                    lines.append(f"- {gene} {pos}: PTM Log2FC = {ptm_fc} ({cls})")
            lines.append("")

        # 5. PTM Connection Evidence
        connections = global_data["ptm_connections"]
        if connections:
            lines.append("### PTM Connection Evidence\n")
            lines.append("Evidence for functional connections between PTM sites:\n")
            lines.append("| PTM 1 | PTM 2 | Connection Type | Evidence |")
            lines.append("|-------|-------|----------------|----------|")
            for conn in connections[:20]:
                ptm1 = conn.get("ptm1", "?")
                ptm2 = conn.get("ptm2", "?")
                conn_type = conn.get("type", "?")
                evidence = conn.get("evidence", "")[:60]
                lines.append(f"| {ptm1} | {ptm2} | {conn_type} | {evidence} |")
            lines.append("")

        # 6. Disease Associations
        disease_counts = global_data["disease_counts"]
        if disease_counts:
            lines.append("### Disease Associations\n")
            for d, cnt in sorted(disease_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- **{_safe_str(d).title()}**: {cnt} PTM sites")
            lines.append("")

        # 7. Signaling Network Summary
        lines.append("### Signaling Network Summary\n")
        lines.append(f"- Total PTM sites analyzed: {len(ptms)}")
        lines.append(f"- Total unique pathways: {len(pathway_counts)}")
        lines.append(f"- Total interaction partners: {len(interaction_counts)}")
        lines.append(f"- Total PTM connections: {len(connections)}")
        high_sig = sum(1 for p in ptms if p.get("rag_enrichment", {}).get("classification", {}).get("significance") == "High")
        lines.append(f"- High-significance PTMs: {high_sig}")
        lines.append("")

        return "\n".join(lines)

    def _collect_global_pathway_data(self, ptms: List[dict]) -> dict:
        """Collect aggregated data across all PTMs for global analysis."""
        pathway_counts: Dict[str, dict] = {}
        disease_counts: Dict[str, int] = {}
        interaction_counts: Dict[str, dict] = {}
        classification_counts: Dict[str, int] = {}
        temporal_data: Dict[str, list] = {}
        ptm_connections: List[dict] = []

        # Gene-to-pathways mapping for connection detection
        gene_pathways: Dict[str, set] = {}
        gene_interactions: Dict[str, set] = {}

        for ptm in ptms:
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            position = ptm.get("position") or ptm.get("PTM_Position", "?")
            condition = ptm.get("Condition") or ptm.get("condition", "")
            enr = ptm.get("rag_enrichment", {})

            # Classification counts
            cls = enr.get("classification", {}).get("level", "unknown")
            classification_counts[cls] = classification_counts.get(cls, 0) + 1

            # Pathway counts (normalize to string - pathways can be dicts)
            for pw in enr.get("pathways", []):
                pw_name = pw.get("name", str(pw)) if isinstance(pw, dict) else str(pw)
                if pw_name not in pathway_counts:
                    pathway_counts[pw_name] = {"count": 0, "genes": set()}
                pathway_counts[pw_name]["count"] += 1
                pathway_counts[pw_name]["genes"].add(gene)
                gene_pathways.setdefault(gene, set()).add(pw_name)

            # Disease counts
            for d in enr.get("diseases", []):
                d_str = _safe_str(d)
                disease_counts[d_str] = disease_counts.get(d_str, 0) + 1

            # Interaction counts
            string_db = enr.get("string_db", {})
            for inter in string_db.get("interactions", []):
                partner = inter.get("partner", "")
                if partner:
                    if partner not in interaction_counts:
                        interaction_counts[partner] = {"count": 0, "genes": set()}
                    interaction_counts[partner]["count"] += 1
                    interaction_counts[partner]["genes"].add(gene)
                    gene_interactions.setdefault(gene, set()).add(partner)

            # Temporal data
            if condition:
                temporal_data.setdefault(condition, []).append({
                    "gene": gene,
                    "position": position,
                    "ptm_log2fc": ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0),
                    "classification": enr.get("classification", {}).get("short_label", "?"),
                })

        # Detect PTM connections
        ptm_labels = []
        for ptm in ptms:
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")
            ptm_labels.append(f"{gene} {pos}")

        for i in range(len(ptms)):
            for j in range(i + 1, len(ptms)):
                gene_i = ptms[i].get("gene") or ptms[i].get("Gene.Name", "?")
                gene_j = ptms[j].get("gene") or ptms[j].get("Gene.Name", "?")
                if gene_i == gene_j:
                    continue

                # Shared pathway connection
                shared_pw = gene_pathways.get(gene_i, set()) & gene_pathways.get(gene_j, set())
                if shared_pw:
                    ptm_connections.append({
                        "ptm1": ptm_labels[i], "ptm2": ptm_labels[j],
                        "type": "Shared KEGG Pathway",
                        "evidence": f"Both in: {', '.join(list(shared_pw)[:3])}",
                    })

                # STRING-DB direct interaction
                if gene_j in gene_interactions.get(gene_i, set()) or gene_i in gene_interactions.get(gene_j, set()):
                    ptm_connections.append({
                        "ptm1": ptm_labels[i], "ptm2": ptm_labels[j],
                        "type": "STRING-DB Interaction",
                        "evidence": f"Direct protein-protein interaction",
                    })

                # Shared interaction partner
                shared_partners = gene_interactions.get(gene_i, set()) & gene_interactions.get(gene_j, set())
                if shared_partners and not (gene_j in gene_interactions.get(gene_i, set())):
                    ptm_connections.append({
                        "ptm1": ptm_labels[i], "ptm2": ptm_labels[j],
                        "type": "Shared Interaction Partner",
                        "evidence": f"Shared partners: {', '.join(list(shared_partners)[:3])}",
                    })

        return {
            "pathway_counts": pathway_counts,
            "disease_counts": disease_counts,
            "interaction_counts": interaction_counts,
            "classification_counts": classification_counts,
            "temporal_data": temporal_data,
            "ptm_connections": ptm_connections,
        }

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def _generate_references(self) -> str:
        if not self.citations:
            return ""

        # Deduplicate by PMID
        seen_pmids = set()
        unique_citations = []
        for c in self.citations:
            pmid = c.get("pmid", "")
            if pmid and pmid not in seen_pmids:
                seen_pmids.add(pmid)
                unique_citations.append(c)
            elif not pmid:
                unique_citations.append(c)

        lines = ["\n---\n\n## References\n"]
        for c in unique_citations:
            pmid = c.get("pmid", "")
            title = c.get("title", "")
            journal = c.get("journal", "")
            pub_date = c.get("pub_date", "")
            authors = c.get("authors", [])
            doi = c.get("doi", "")

            author_str = ""
            if authors:
                if len(authors) > 3:
                    author_str = f"{_safe_join(', ', authors[:3])}, et al. "
                else:
                    author_str = f"{_safe_join(', ', authors)}. "

            ref_line = f"[{c['number']}] {author_str}{title}. *{journal}* ({pub_date})."
            if pmid:
                ref_line += f" PMID: {pmid}"
            if doi:
                ref_line += f" DOI: {doi}"
            lines.append(ref_line)

        lines.append("")
        return "\n".join(lines)


# ===========================================================================
# Module-level Helpers
# ===========================================================================

def _is_recent(pub_date: str, years: int = 3) -> bool:
    """Check if a publication date is within the last N years."""
    if not pub_date:
        return False
    try:
        year = int(pub_date[:4])
        return year >= datetime.now().year - years
    except (ValueError, IndexError):
        return False
