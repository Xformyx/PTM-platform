"""
Comprehensive PTM Report Generator — produces Markdown reports from enriched PTM data.
Ported from ptm-rag-backend/src/comprehensiveReport-v3.ts (v7.8.0 — Multi-PTM Support).

Changes from original:
  - LLM-based sections (abstract analysis, signaling interpretation) REMOVED
  - Pattern-based evidence extraction retained
  - TypeScript → Python
  - Generates MD files per PTM and a combined summary
  - v7.8.0: Full multi-PTM type support (Phosphorylation, Ubiquitylation, Acetylation, etc.)
"""

import logging
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

    results: List[Dict[str, object]] = []
    seen: set = set()

    for motif in re.split(r"[;|,]", matched_motifs):
        motif_upper = motif.strip().upper()
        for chain_type, info in chain_info.items():
            if chain_type.upper() in motif_upper:
                if chain_type not in seen:
                    results.append({"chain_type": chain_type, **info})
                    seen.add(chain_type)
        if "LYSINE_UBIQUITINATION_GENERAL" in motif_upper or "RING_E3" in motif_upper:
            if "General" not in seen:
                results.append({"chain_type": "General", "function": "General ubiquitylation (chain type undetermined)", "is_proteolytic": False})
                seen.add("General")

    return results


def categorize_ubiquitin_regulators(predicted_regulators: Optional[List[str]] = None) -> Dict[str, List[str]]:
    if not predicted_regulators:
        return {"e3_ligases": [], "dubs": []}

    known_e3 = [
        "CHIP", "STUB1", "MDM2", "NEDD4", "HUWE1", "APC/C", "SCF", "PARKIN", "PARK2",
        "ITCH", "WWP1", "WWP2", "SMURF1", "SMURF2", "TRIM", "RNF", "MARCH", "XIAP",
        "BIRC", "CBL", "VHL", "BRCA1", "BARD1", "UBR", "HERC", "HECTD", "UBE3",
        "FBXW", "FBXO", "SKP2", "BTRC", "CDC20", "CDH1", "KEAP1", "CUL", "SPOP",
    ]
    known_dub = [
        "USP", "UCH", "OTU", "OTUD", "OTUB", "CYLD", "A20", "TNFAIP3", "BAP1",
        "UCHL", "ATXN3", "JOSD", "MINDY", "ZUFSP", "MYSM1", "BRCC36", "COPS5",
        "PSMD14", "STAMBP", "STAMBPL",
    ]

    e3_ligases: List[str] = []
    dubs: List[str] = []

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


class ComprehensiveReportGenerator:
    """Generates Markdown PTM analysis reports from enriched data."""

    def __init__(self, experimental_context: Optional[dict] = None):
        self.context = experimental_context or {}
        self.citation_counter = 0
        self.citations: List[dict] = []

    def generate_full_report(self, enriched_ptms: List[dict]) -> str:
        """Generate a combined comprehensive report for all enriched PTMs."""
        lines = []

        lines.append("# PTM Comprehensive Analysis Report")
        lines.append(f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        # Context section
        if self.context:
            lines.append(self._generate_context_section())

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
    # Context section
    # ------------------------------------------------------------------

    def _generate_context_section(self) -> str:
        lines = ["## Experimental Context\n"]
        for key in ("tissue", "organism", "treatment", "condition", "cell_type", "biological_question", "special_conditions"):
            val = self.context.get(key)
            if val:
                lines.append(f"- **{key.replace('_', ' ').title()}**: {val}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------

    def _generate_summary_table(self, ptms: List[dict]) -> str:
        lines = [
            "## Summary\n",
            f"Total PTM sites analyzed: **{len(ptms)}**\n",
            "| Gene | Position | PTM Type | Protein Log2FC | PTM Relative Log2FC | Quadrant | Articles |",
            "|------|----------|----------|---------------|---------------------|----------|----------|",
        ]

        for ptm in ptms:
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")
            ptype = ptm.get("ptm_type") or ptm.get("PTM_Type", "?")
            prot_fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
            ptm_fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)
            enr = ptm.get("rag_enrichment", {})
            quadrant = enr.get("classification", {}).get("quadrant", "?")
            n_articles = enr.get("search_summary", {}).get("total_articles", 0)

            try:
                prot_fc_str = f"{float(prot_fc):.3f}"
                ptm_fc_str = f"{float(ptm_fc):.3f}"
            except (ValueError, TypeError):
                prot_fc_str = str(prot_fc)
                ptm_fc_str = str(ptm_fc)

            lines.append(f"| {gene} | {pos} | {ptype} | {prot_fc_str} | {ptm_fc_str} | {quadrant} | {n_articles} |")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Individual PTM section
    # ------------------------------------------------------------------

    def _generate_ptm_section(self, ptm: dict, index: int) -> str:
        gene = ptm.get("gene") or ptm.get("Gene.Name", "Unknown")
        position = ptm.get("position") or ptm.get("PTM_Position", "Unknown")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        enr = ptm.get("rag_enrichment", {})

        lines = [f"\n---\n\n## {index}. {gene} {position} ({ptm_type})\n"]

        # Overview
        lines.append(self._generate_overview(ptm, enr))

        # Literature evidence
        lines.append(self._generate_literature_evidence(enr))

        # Regulatory network
        lines.append(self._generate_regulatory_network(gene, enr, ptm_type))

        # Biological interpretation
        lines.append(self._generate_biological_interpretation(ptm, enr))

        # Quantitative data
        lines.append(self._generate_quantitative_data(ptm))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Sub-sections
    # ------------------------------------------------------------------

    def _generate_overview(self, ptm: dict, enr: dict) -> str:
        lines = ["### Overview\n"]

        classification = enr.get("classification", {})
        quadrant = classification.get("quadrant", "unknown")
        interp = classification.get("interpretation", "")

        prot_fc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
        ptm_fc = ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)

        try:
            lines.append(f"- **Protein Log2FC**: {float(prot_fc):.3f}")
            lines.append(f"- **PTM Relative Log2FC**: {float(ptm_fc):.3f}")
        except (ValueError, TypeError):
            lines.append(f"- **Protein Log2FC**: {prot_fc}")
            lines.append(f"- **PTM Relative Log2FC**: {ptm_fc}")

        lines.append(f"- **Quadrant**: {quadrant}")
        lines.append(f"- **Interpretation**: {interp}")

        func_summary = enr.get("function_summary", "")
        if func_summary:
            lines.append(f"\n**Protein Function**: {func_summary[:500]}")

        loc = enr.get("localization", [])
        if loc:
            lines.append(f"\n**Subcellular Localization**: {', '.join(loc)}")

        lines.append("")
        return "\n".join(lines)

    def _generate_literature_evidence(self, enr: dict) -> str:
        findings = enr.get("recent_findings", [])
        if not findings:
            return "### Literature Evidence\n\nNo relevant literature found.\n"

        lines = [
            "### Literature Evidence\n",
            f"Found **{len(findings)}** relevant articles:\n",
        ]

        for i, article in enumerate(findings[:8], 1):
            pmid = article.get("pmid", "")
            title = _clean_text(article.get("title", ""))
            journal = article.get("journal", "")
            pub_date = article.get("pub_date", "")
            score = article.get("relevance_score", 0)
            excerpt = _clean_text(article.get("abstract_excerpt", ""))

            self.citation_counter += 1
            self.citations.append({"number": self.citation_counter, "pmid": pmid, "title": title, "journal": journal, "pub_date": pub_date})

            lines.append(f"**{i}. {title}** [{self.citation_counter}]")
            lines.append(f"   *{journal}* ({pub_date}) | Relevance: {score}/100 | PMID: {pmid}")
            if excerpt:
                lines.append(f"   > {excerpt[:200]}...")
            lines.append("")

        return "\n".join(lines)

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
            lines.append(f"**Upstream Regulators**: {', '.join(upstream[:8])}")
        if downstream:
            lines.append(f"**Downstream Targets**: {', '.join(downstream[:8])}")

        if ks:
            ks_label = f"{terms['activator'].title()}-Substrate Relationships"
            lines.append(f"\n**{ks_label}**:\n")
            for rel in ks[:5]:
                lines.append(f"- {rel.get('kinase', '?')} → {rel.get('substrate', '?')} (PMID: {rel.get('pmid', '?')})")

        if pathways:
            lines.append(f"\n**KEGG Pathways**: {', '.join(pathways[:5])}")

        if interactions:
            lines.append(f"\n**STRING-DB Interaction Partners**: {', '.join(interactions[:5])}")

        # Ubiquitylation-specific sections (v7.8.0)
        if is_ubiquitylation(ptm_type):
            matched_motifs = enr.get("matched_motifs", "")
            chain_types = parse_ubiquitin_chain_types(matched_motifs)
            if chain_types:
                lines.append("\n**Ubiquitin Chain Type Analysis**:\n")
                for ct in chain_types:
                    prot_label = "proteolytic" if ct.get("is_proteolytic") else "non-proteolytic"
                    lines.append(f"- **{ct['chain_type']}**: {ct['function']} ({prot_label})")

            predicted_regs = enr.get("predicted_regulators", [])
            cats = categorize_ubiquitin_regulators(predicted_regs)
            if cats["e3_ligases"] or cats["dubs"]:
                lines.append("\n**E3 Ligase / DUB Regulatory Network**:\n")
                if cats["e3_ligases"]:
                    lines.append(f"- E3 Ligases: {', '.join(cats['e3_ligases'])}")
                if cats["dubs"]:
                    lines.append(f"- DUBs: {', '.join(cats['dubs'])}")

                proteolytic = any(ct.get("is_proteolytic") for ct in chain_types)
                if proteolytic:
                    lines.append(f"\n**Protein Fate Prediction**: {gene} is likely targeted for **proteasomal degradation**")
                elif chain_types:
                    lines.append(f"\n**Protein Fate Prediction**: {gene} ubiquitylation appears to be **signaling-related** (non-proteolytic)")

        # GO terms
        go = enr.get("go_terms", {})
        bp = go.get("biological_process", [])
        mf = go.get("molecular_function", [])
        if bp:
            lines.append(f"\n**GO Biological Process**: {'; '.join(bp[:3])}")
        if mf:
            lines.append(f"**GO Molecular Function**: {'; '.join(mf[:3])}")

        if not upstream and not downstream and not ks and not pathways:
            lines.append("No regulatory information found from literature analysis.")

        lines.append("")
        return "\n".join(lines)

    def _generate_biological_interpretation(self, ptm: dict, enr: dict) -> str:
        lines = ["### Biological Interpretation\n"]

        classification = enr.get("classification", {})
        quadrant = classification.get("quadrant", "unknown")
        class_label = classification.get("classification", "")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")

        interp = classification.get("interpretation", "")
        if not interp and class_label:
            interp = get_classification_interpretation(class_label, ptm_type)

        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        position = ptm.get("position") or ptm.get("PTM_Position", "?")
        mod_noun = get_modification_noun(ptm_type)
        mod_verb = get_modification_verb(ptm_type)

        lines.append(f"The {mod_noun} at {gene} {position} falls in **{quadrant}** of the PTM vector analysis.")
        lines.append(f"{interp}\n")

        diseases = enr.get("diseases", [])
        if diseases:
            lines.append(f"**Disease Associations**: {', '.join(diseases)}")

        reg = enr.get("regulation", {})
        evidence_count = reg.get("evidence_count", 0)
        if evidence_count > 0:
            terms = get_regulator_terms(ptm_type)
            lines.append(f"\nPattern-based analysis identified **{evidence_count}** regulatory relationships from the literature.")

        lines.append("")
        return "\n".join(lines)

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
    # Global analysis
    # ------------------------------------------------------------------

    def _generate_global_pathway_analysis(self, ptms: List[dict]) -> str:
        lines = ["\n---\n\n## Global Pathway Analysis\n"]

        pathway_counts: Dict[str, int] = {}
        disease_counts: Dict[str, int] = {}
        quadrant_counts: Dict[str, int] = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0, "center": 0, "unknown": 0}

        for ptm in ptms:
            enr = ptm.get("rag_enrichment", {})
            for pw in enr.get("pathways", []):
                pathway_counts[pw] = pathway_counts.get(pw, 0) + 1
            for d in enr.get("diseases", []):
                disease_counts[d] = disease_counts.get(d, 0) + 1
            q = enr.get("classification", {}).get("quadrant", "unknown")
            quadrant_counts[q] = quadrant_counts.get(q, 0) + 1

        # Quadrant distribution
        lines.append("### Quadrant Distribution\n")
        lines.append("| Quadrant | Count | Description |")
        lines.append("|----------|-------|-------------|")
        desc = {
            "Q1": "Protein↑ + PTM↑",
            "Q2": "Protein↓ + PTM↑",
            "Q3": "Protein↓ + PTM↓",
            "Q4": "Protein↑ + PTM↓",
            "center": "Minimal change",
            "unknown": "Insufficient data",
        }
        for q in ("Q1", "Q2", "Q3", "Q4", "center", "unknown"):
            if quadrant_counts.get(q, 0) > 0:
                lines.append(f"| {q} | {quadrant_counts[q]} | {desc.get(q, '')} |")

        # Top pathways
        if pathway_counts:
            lines.append("\n### Most Frequent Pathways\n")
            for pw, cnt in sorted(pathway_counts.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"- **{pw}**: {cnt} PTM sites")

        # Disease associations
        if disease_counts:
            lines.append("\n### Disease Associations\n")
            for d, cnt in sorted(disease_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- **{d.title()}**: {cnt} PTM sites")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def _generate_references(self) -> str:
        if not self.citations:
            return ""

        lines = ["\n---\n\n## References\n"]
        for c in self.citations:
            pmid = c.get("pmid", "")
            title = c.get("title", "")
            journal = c.get("journal", "")
            pub_date = c.get("pub_date", "")
            lines.append(f"[{c['number']}] {title}. *{journal}* ({pub_date}). PMID: {pmid}")

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text
