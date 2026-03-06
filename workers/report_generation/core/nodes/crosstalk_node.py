"""
Cross-Talk Node — Cross-Talk (Phos x Ub) analysis pipeline.
Ported from ptm_nonptm_network_command.py (v47~v95).

Identifies dual-PTM proteins, concordant/discordant regulation patterns,
sequential gating events, and shared non-PTM interactors across two PTM datasets.
Generates a full cross-talk report with LLM-written sections.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from common.llm_client import LLMClient
from common.temporal_utils import tp_to_minutes, format_condition_display_name
from common.report_postprocessor import postprocess_full_report
from report_generation.core.rag_retriever import RAGRetriever
from report_generation.core.temporal_analysis import (
    build_nonptm_temporal_analysis,
    build_ptm_protein_timelag_analysis,
    build_signal_propagation_json_from_crosstalk,
)
from report_generation.core.report_utils import (
    ensure_abstract_completeness,
    merge_empty_subsections,
)
from report_generation.core.crosstalk_fallbacks import (
    generate_crosstalk_results_fallback,
    generate_crosstalk_discussion_fallback,
    generate_crosstalk_conclusion_fallback,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: parse timepoint string for sorting
# ---------------------------------------------------------------------------

def _parse_timepoint(tp_str: str) -> float:
    """Convert timepoint string to minutes for sorting."""
    return tp_to_minutes(tp_str)


# ---------------------------------------------------------------------------
# Helper: infer gating mechanism
# ---------------------------------------------------------------------------

def _infer_gating_mechanism(leading_ptm: str, lagging_ptm: str, time_lag: float) -> str:
    """Infer the likely mechanism behind sequential PTM gating."""
    leading = leading_ptm.lower()
    lagging = lagging_ptm.lower()
    if leading in ("phosphorylation", "phos") and lagging in ("ubiquitylation", "ubiquitination", "ub"):
        if time_lag <= 5:
            return "Phosphodegron (rapid phosphorylation-triggered ubiquitylation)"
        elif time_lag <= 30:
            return "Kinase-E3 ligase relay (phosphorylation primes E3 ligase recognition)"
        else:
            return "Transcriptional reprogramming (phosphorylation activates TF → new E3 expression)"
    elif leading in ("ubiquitylation", "ubiquitination", "ub") and lagging in ("phosphorylation", "phos"):
        if time_lag <= 5:
            return "Ubiquitin-dependent kinase activation (rapid ubiquitin signaling)"
        elif time_lag <= 30:
            return "Proteasomal processing activates kinase cascade"
        else:
            return "Ubiquitin-mediated protein turnover alters kinase substrate availability"
    return f"Sequential {leading}→{lagging} regulation (time lag: {time_lag:.0f} min)"


# ---------------------------------------------------------------------------
# Core: build_crosstalk_data
# ---------------------------------------------------------------------------

def build_crosstalk_data(
    primary_results: dict,
    primary_ptm_type: str,
    primary_md_content: str,
    secondary_results: dict,
    secondary_ptm_type: str,
    secondary_md_content: str,
    primary_tsv_path: Optional[str] = None,
    secondary_tsv_path: Optional[str] = None,
) -> dict:
    """
    Build comprehensive cross-talk analysis data from two PTM datasets.
    Returns a dict with dual_ptm_proteins, concordant/discordant pairs,
    sequential gating events, shared non-PTM interactors, etc.
    """
    crosstalk = {
        "primary_ptm_type": primary_ptm_type,
        "secondary_ptm_type": secondary_ptm_type,
        "dual_ptm_proteins": [],
        "concordant_pairs": [],
        "discordant_pairs": [],
        "sequential_gating": [],
        "shared_nonptm": [],
        "shared_nonptm_details": [],
        "primary_only_nonptm": [],
        "secondary_only_nonptm": [],
        "ptm_protein_timelags": [],
        "primary_summary": {},
        "secondary_summary": {},
    }

    # ── Parse TSV files ──────────────────────────────────────────────────
    def _parse_tsv_proteins(tsv_path: Optional[str]) -> dict:
        proteins = {}
        if not tsv_path or not os.path.exists(tsv_path):
            return proteins
        try:
            import csv
            with open(tsv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    gene = row.get("Gene", row.get("gene", "")).strip()
                    if not gene:
                        continue
                    gene_upper = gene.upper()
                    site = row.get("Site", row.get("site", "")).strip()
                    tp_str = row.get("Timepoint", row.get("timepoint", row.get("Condition", ""))).strip()
                    ptm_relative_log2fc = _safe_float(
                        row.get("PTM_Relative_Log2FC", row.get("ptm_relative_log2fc", 0))
                    )
                    protein_log2fc = _safe_float(
                        row.get("Protein_Log2FC", row.get("protein_log2fc", 0))
                    )

                    if gene_upper not in proteins:
                        proteins[gene_upper] = {
                            "original_name": gene,
                            "timepoints": {},
                            "ptm_sites": set(),
                            "all_sites_data": {},
                            "node_type_history": {},
                        }

                    if site:
                        proteins[gene_upper]["ptm_sites"].add(site)

                    # Per-site temporal data
                    if site:
                        if site not in proteins[gene_upper]["all_sites_data"]:
                            proteins[gene_upper]["all_sites_data"][site] = {}
                        existing_site_val = proteins[gene_upper]["all_sites_data"][site].get(tp_str, 0)
                        if abs(ptm_relative_log2fc) > abs(existing_site_val):
                            proteins[gene_upper]["all_sites_data"][site][tp_str] = ptm_relative_log2fc

                    # Gene-level temporal data
                    state = "active" if ptm_relative_log2fc > 0 else "inhibited"
                    if tp_str not in proteins[gene_upper]["timepoints"]:
                        proteins[gene_upper]["timepoints"][tp_str] = {
                            "ptm_log2fc": ptm_relative_log2fc,
                            "protein_log2fc": protein_log2fc,
                            "state": state,
                            "site_count": 1,
                        }
                        proteins[gene_upper]["node_type_history"][tp_str] = state
                    else:
                        existing = proteins[gene_upper]["timepoints"][tp_str]
                        if abs(ptm_relative_log2fc) > abs(existing["ptm_log2fc"]):
                            existing["ptm_log2fc"] = ptm_relative_log2fc
                            existing["state"] = state
                            existing["protein_log2fc"] = protein_log2fc
                            proteins[gene_upper]["node_type_history"][tp_str] = state
                        existing["site_count"] = existing.get("site_count", 1) + 1
        except Exception as e:
            logger.error(f"Error parsing TSV file {tsv_path}: {e}")
        return proteins

    def _safe_float(val, default=0.0):
        try:
            return float(val) if val else default
        except (ValueError, TypeError):
            return default

    # ── Step 1: Parse TSV files as PRIMARY data source ────────────────────
    primary_proteins = _parse_tsv_proteins(primary_tsv_path)
    secondary_proteins = _parse_tsv_proteins(secondary_tsv_path)
    logger.info(f"[TSV] Primary proteins: {len(primary_proteins)}, Secondary proteins: {len(secondary_proteins)}")

    # ── Step 2: Fallback to network nodes if TSV is not available ─────────
    if not primary_proteins:
        logger.warning("[TSV] Primary TSV not available, falling back to network nodes")
        primary_proteins = _extract_proteins_from_network(primary_results)
    if not secondary_proteins:
        logger.warning("[TSV] Secondary TSV not available, falling back to network nodes")
        secondary_proteins = _extract_proteins_from_network(secondary_results)

    # ── Step 3: Annotate network-significant proteins ─────────────────────
    primary_network_genes = _extract_network_gene_set(primary_results)
    secondary_network_genes = _extract_network_gene_set(secondary_results)
    for gene in primary_proteins:
        primary_proteins[gene]["is_network_hub"] = gene in primary_network_genes
    for gene in secondary_proteins:
        secondary_proteins[gene]["is_network_hub"] = gene in secondary_network_genes

    # ── Step 4: Find dual-PTM proteins ────────────────────────────────────
    shared_genes = set(primary_proteins.keys()) & set(secondary_proteins.keys())
    logger.info(f"[CrossTalk] Dual-PTM proteins found: {len(shared_genes)}")

    threshold = 0.0  # activation threshold

    for gene in sorted(shared_genes):
        p_data = primary_proteins[gene]
        s_data = secondary_proteins[gene]
        p_tps = set(p_data.get("timepoints", {}).keys())
        s_tps = set(s_data.get("timepoints", {}).keys())
        shared_tps = sorted(p_tps & s_tps, key=_parse_timepoint)

        dual_entry = {
            "gene": gene,
            "original_name": p_data.get("original_name", gene),
            "primary_sites": sorted(p_data.get("ptm_sites", set())),
            "secondary_sites": sorted(s_data.get("ptm_sites", set())),
            "primary_site_count": len(p_data.get("ptm_sites", set())),
            "secondary_site_count": len(s_data.get("ptm_sites", set())),
            "shared_timepoints": shared_tps,
            "temporal_comparison": {},
            "concordant_count": 0,
            "discordant_count": 0,
            "neutral_count": 0,
            "meaningful_comparisons": 0,
            "concordant_ratio": 0.0,
            "pattern": "neutral",
            "is_network_hub_primary": p_data.get("is_network_hub", False),
            "is_network_hub_secondary": s_data.get("is_network_hub", False),
        }

        for tp in shared_tps:
            p_tp = p_data["timepoints"].get(tp, {})
            s_tp = s_data["timepoints"].get(tp, {})
            p_fc = p_tp.get("ptm_log2fc", 0)
            s_fc = s_tp.get("ptm_log2fc", 0)
            p_state = "up" if p_fc > threshold else ("down" if p_fc < -threshold else "neutral")
            s_state = "up" if s_fc > threshold else ("down" if s_fc < -threshold else "neutral")

            if p_state != "neutral" and s_state != "neutral":
                concordant = (p_state == s_state)
                dual_entry["meaningful_comparisons"] += 1
                if concordant:
                    dual_entry["concordant_count"] += 1
                else:
                    dual_entry["discordant_count"] += 1
            else:
                concordant = None
                dual_entry["neutral_count"] += 1

            dual_entry["temporal_comparison"][tp] = {
                "primary_ptm_log2fc": p_fc,
                "secondary_ptm_log2fc": s_fc,
                "primary_state": p_state,
                "secondary_state": s_state,
                "concordant": concordant,
            }

        if dual_entry["meaningful_comparisons"] > 0:
            dual_entry["concordant_ratio"] = (
                dual_entry["concordant_count"] / dual_entry["meaningful_comparisons"]
            )
            if dual_entry["concordant_ratio"] >= 0.7:
                dual_entry["pattern"] = "concordant"
            elif dual_entry["concordant_ratio"] <= 0.3:
                dual_entry["pattern"] = "discordant"
            else:
                dual_entry["pattern"] = "mixed"

        crosstalk["dual_ptm_proteins"].append(dual_entry)
        if dual_entry["pattern"] == "concordant":
            crosstalk["concordant_pairs"].append(dual_entry)
        elif dual_entry["pattern"] == "discordant":
            crosstalk["discordant_pairs"].append(dual_entry)

    # ── Step 5: Sequential gating analysis ────────────────────────────────
    for gene in sorted(shared_genes):
        p_data = primary_proteins[gene]
        s_data = secondary_proteins[gene]
        p_tps = set(p_data.get("timepoints", {}).keys())
        s_tps = set(s_data.get("timepoints", {}).keys())

        p_first_active = None
        for tp in sorted(p_tps, key=_parse_timepoint):
            tp_data = p_data.get("timepoints", {}).get(tp, {})
            if abs(tp_data.get("ptm_log2fc", 0)) >= threshold:
                p_first_active = tp
                break

        s_first_active = None
        for tp in sorted(s_tps, key=_parse_timepoint):
            tp_data = s_data.get("timepoints", {}).get(tp, {})
            if abs(tp_data.get("ptm_log2fc", 0)) >= threshold:
                s_first_active = tp
                break

        if p_first_active and s_first_active:
            p_first_min = _parse_timepoint(p_first_active)
            s_first_min = _parse_timepoint(s_first_active)
            time_lag = abs(s_first_min - p_first_min)
            if time_lag > 0:
                leading_ptm = primary_ptm_type if p_first_min < s_first_min else secondary_ptm_type
                lagging_ptm = secondary_ptm_type if p_first_min < s_first_min else primary_ptm_type
                gating_entry = {
                    "gene": gene,
                    "leading_ptm": leading_ptm,
                    "lagging_ptm": lagging_ptm,
                    "time_lag_minutes": time_lag,
                    "leading_first_tp": p_first_active if p_first_min < s_first_min else s_first_active,
                    "lagging_first_tp": s_first_active if p_first_min < s_first_min else p_first_active,
                    "mechanism_hint": _infer_gating_mechanism(leading_ptm, lagging_ptm, time_lag),
                }
                crosstalk["sequential_gating"].append(gating_entry)

    # ── Step 6: Summary statistics ────────────────────────────────────────
    all_primary_tps = set()
    for p in primary_proteins.values():
        all_primary_tps.update(p.get("timepoints", {}).keys())
    all_secondary_tps = set()
    for p in secondary_proteins.values():
        all_secondary_tps.update(p.get("timepoints", {}).keys())

    crosstalk["primary_summary"] = {
        "ptm_type": primary_ptm_type,
        "total_proteins": len(primary_proteins),
        "total_sites": sum(len(p.get("ptm_sites", set())) for p in primary_proteins.values()),
        "timepoints": sorted(all_primary_tps, key=_parse_timepoint),
        "network_hub_count": sum(1 for p in primary_proteins.values() if p.get("is_network_hub", False)),
    }
    crosstalk["secondary_summary"] = {
        "ptm_type": secondary_ptm_type,
        "total_proteins": len(secondary_proteins),
        "total_sites": sum(len(p.get("ptm_sites", set())) for p in secondary_proteins.values()),
        "timepoints": sorted(all_secondary_tps, key=_parse_timepoint),
        "network_hub_count": sum(1 for p in secondary_proteins.values() if p.get("is_network_hub", False)),
    }

    # ── Step 7: Non-PTM protein overlap ───────────────────────────────────
    primary_nonptm = set()
    secondary_nonptm = set()
    for tp, net in primary_results.get("networks", {}).items():
        if isinstance(net, dict):
            for node in net.get("non_ptm_nodes", []):
                g = node.get("gene", node.get("gene_name", node.get("name", node.get("id", ""))))
                if g:
                    primary_nonptm.add(g.strip().upper())
    for tp, net in secondary_results.get("networks", {}).items():
        if isinstance(net, dict):
            for node in net.get("non_ptm_nodes", []):
                g = node.get("gene", node.get("gene_name", node.get("name", node.get("id", ""))))
                if g:
                    secondary_nonptm.add(g.strip().upper())

    crosstalk["shared_nonptm"] = sorted(primary_nonptm & secondary_nonptm)
    crosstalk["primary_only_nonptm"] = sorted(primary_nonptm - secondary_nonptm)
    crosstalk["secondary_only_nonptm"] = sorted(secondary_nonptm - primary_nonptm)

    # ── Step 7b: Enrich shared non-PTM interactors with temporal protein abundance ──
    crosstalk["shared_nonptm_details"] = []
    for nonptm_gene in crosstalk["shared_nonptm"]:
        detail = {
            "gene": nonptm_gene,
            "primary_protein_temporal": {},
            "secondary_protein_temporal": {},
            "max_primary_change": 0.0,
            "max_secondary_change": 0.0,
            "response_pattern": "stable",
        }
        p_data = primary_proteins.get(nonptm_gene, {})
        for tp, tp_data in p_data.get("timepoints", {}).items():
            plog2fc = tp_data.get("protein_log2fc", 0)
            detail["primary_protein_temporal"][tp] = plog2fc
            if abs(plog2fc) > abs(detail["max_primary_change"]):
                detail["max_primary_change"] = plog2fc
        s_data = secondary_proteins.get(nonptm_gene, {})
        for tp, tp_data in s_data.get("timepoints", {}).items():
            plog2fc = tp_data.get("protein_log2fc", 0)
            detail["secondary_protein_temporal"][tp] = plog2fc
            if abs(plog2fc) > abs(detail["max_secondary_change"]):
                detail["max_secondary_change"] = plog2fc
        # Classify response pattern
        all_changes = list(detail["primary_protein_temporal"].values()) + list(
            detail["secondary_protein_temporal"].values()
        )
        if all_changes:
            max_abs = max(abs(c) for c in all_changes)
            if max_abs < 0.3:
                detail["response_pattern"] = "stable"
            else:
                sorted_tps = sorted(
                    detail["primary_protein_temporal"].keys(), key=_parse_timepoint
                )
                if sorted_tps:
                    first_tp_val = abs(
                        detail["primary_protein_temporal"].get(sorted_tps[0], 0)
                    )
                    last_tp_val = abs(
                        detail["primary_protein_temporal"].get(sorted_tps[-1], 0)
                    )
                    if first_tp_val > 0.3 and last_tp_val < 0.3:
                        detail["response_pattern"] = "early_response"
                    elif first_tp_val < 0.3 and last_tp_val > 0.3:
                        detail["response_pattern"] = "late_response"
                    elif first_tp_val > 0.3 and last_tp_val > 0.3:
                        detail["response_pattern"] = "sustained"
                    else:
                        detail["response_pattern"] = "biphasic"
        crosstalk["shared_nonptm_details"].append(detail)

    # ── Step 7c: PTM→Protein time lag analysis ────────────────────────────
    crosstalk["ptm_protein_timelags"] = build_ptm_protein_timelag_analysis(
        primary_proteins, secondary_proteins, primary_ptm_type, secondary_ptm_type
    )

    # ── Step 8: Significance scoring and sorting ──────────────────────────
    for dp in crosstalk["dual_ptm_proteins"]:
        hub_score = (1 if dp.get("is_network_hub_primary", False) else 0) + (
            1 if dp.get("is_network_hub_secondary", False) else 0
        )
        max_ptm_change = 0
        sum_ptm_change = 0
        for tp_data in dp.get("temporal_comparison", {}).values():
            p_abs = abs(tp_data.get("primary_ptm_log2fc", 0))
            s_abs = abs(tp_data.get("secondary_ptm_log2fc", 0))
            max_ptm_change = max(max_ptm_change, p_abs, s_abs)
            sum_ptm_change += p_abs + s_abs

        meaningful = dp.get("meaningful_comparisons", 0)
        pattern = dp.get("pattern", "neutral")
        pattern_bonus = 50 if pattern in ("concordant", "discordant") else (25 if pattern == "mixed" else 0)
        site_diversity = dp.get("primary_site_count", 0) + dp.get("secondary_site_count", 0)

        dp["significance_score"] = (
            meaningful * 100
            + pattern_bonus
            + hub_score * 10
            + sum_ptm_change
            + site_diversity * 2
            + max_ptm_change
        )

    crosstalk["dual_ptm_proteins"].sort(key=lambda x: x.get("significance_score", 0), reverse=True)
    crosstalk["concordant_pairs"].sort(key=lambda x: x.get("significance_score", 0), reverse=True)
    crosstalk["discordant_pairs"].sort(key=lambda x: x.get("significance_score", 0), reverse=True)

    logger.info(
        f"[CrossTalk] Final: {len(crosstalk['dual_ptm_proteins'])} dual-PTM, "
        f"{len(crosstalk['concordant_pairs'])} concordant, "
        f"{len(crosstalk['discordant_pairs'])} discordant, "
        f"{len(crosstalk['sequential_gating'])} sequential gating"
    )
    return crosstalk


# ---------------------------------------------------------------------------
# Helper: extract proteins from network results (fallback when TSV unavailable)
# ---------------------------------------------------------------------------

def _extract_proteins_from_network(results: dict) -> dict:
    """Fallback: Extract protein data from network analysis results."""
    proteins = {}
    for tp, net in results.get("networks", {}).items():
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes"]:
            for node in net.get(node_type, []):
                gene = node.get("gene", node.get("gene_name", node.get("name", node.get("id", ""))))
                if not gene:
                    continue
                gene = gene.strip().upper()
                if gene not in proteins:
                    proteins[gene] = {
                        "original_name": gene,
                        "timepoints": {},
                        "ptm_sites": set(),
                        "node_type_history": {},
                    }
                site = node.get("site", "")
                if site:
                    proteins[gene]["ptm_sites"].add(site)
                proteins[gene]["timepoints"][tp] = {
                    "ptm_log2fc": node.get("value", node.get("ptm_log2fc", node.get("ub_log2fc", 0))),
                    "protein_log2fc": node.get("protein_log2fc", 0),
                    "state": node.get("state", node_type.replace("_nodes", "")),
                }
                proteins[gene]["node_type_history"][tp] = node_type.replace("_nodes", "")
    return proteins


def _extract_network_gene_set(results: dict) -> set:
    """Extract the set of gene names present in network analysis results."""
    genes = set()
    for tp, net in results.get("networks", {}).items():
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes"]:
            for node in net.get(node_type, []):
                gene = node.get("gene", node.get("gene_name", node.get("name", node.get("id", ""))))
                if gene:
                    genes.add(gene.strip().upper())
    return genes


# ---------------------------------------------------------------------------
# Helper: build cross-talk context string for LLM prompts
# ---------------------------------------------------------------------------

def _build_crosstalk_context_for_llm(crosstalk_data: dict) -> str:
    """Build a concise text summary of cross-talk data for LLM prompt injection."""
    lines = []
    p_type = crosstalk_data["primary_ptm_type"].capitalize()
    s_type = crosstalk_data["secondary_ptm_type"].capitalize()

    lines.append(f"## Cross-Talk Analysis: {p_type} x {s_type}")
    lines.append(f"- Dual-PTM proteins: {len(crosstalk_data['dual_ptm_proteins'])}")
    lines.append(f"- Concordant: {len(crosstalk_data['concordant_pairs'])}")
    lines.append(f"- Discordant: {len(crosstalk_data['discordant_pairs'])}")
    lines.append(f"- Sequential gating: {len(crosstalk_data['sequential_gating'])}")
    lines.append(f"- Shared non-PTM interactors: {len(crosstalk_data['shared_nonptm'])}")

    # Top dual-PTM proteins
    lines.append("\n### Top Dual-PTM Proteins:")
    for dp in crosstalk_data["dual_ptm_proteins"][:10]:
        lines.append(
            f"  {dp['gene']}: pattern={dp['pattern']}, "
            f"concordance={dp['concordant_ratio']:.0%}, "
            f"{p_type} sites={len(dp['primary_sites'])}, "
            f"{s_type} sites={len(dp['secondary_sites'])}"
        )

    # Sequential gating
    if crosstalk_data["sequential_gating"]:
        lines.append("\n### Sequential Gating Events:")
        for gate in crosstalk_data["sequential_gating"][:5]:
            lines.append(
                f"  {gate['gene']}: {gate['leading_ptm']} leads → {gate['lagging_ptm']} follows "
                f"(lag={gate['time_lag_minutes']:.0f}min, {gate['mechanism_hint']})"
            )

    # Shared non-PTM
    if crosstalk_data["shared_nonptm"]:
        lines.append(
            f"\n### Shared Non-PTM Interactors: {', '.join(crosstalk_data['shared_nonptm'][:15])}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: build protein whitelist text for LLM
# ---------------------------------------------------------------------------

def _build_whitelist_text(crosstalk_data: dict) -> str:
    """Build a protein name whitelist for LLM to prevent hallucination."""
    names = set()
    for dp in crosstalk_data["dual_ptm_proteins"]:
        names.add(dp["gene"])
    for gate in crosstalk_data["sequential_gating"]:
        names.add(gate["gene"])
    for g in crosstalk_data.get("shared_nonptm", []):
        names.add(g)
    return ", ".join(sorted(names)) if names else "(no proteins identified)"


# ---------------------------------------------------------------------------
# Main: run_crosstalk_analysis (state-based node entry point)
# ---------------------------------------------------------------------------

def run_crosstalk_analysis(state: dict) -> dict:
    """
    Run Cross-Talk analysis as a pipeline node.
    Expects state to contain primary and secondary analysis results.
    """
    cb = state.get("progress_callback")
    if cb:
        cb(45, "Starting Cross-Talk analysis")

    output_dir = state.get("output_dir", "/tmp")
    report_config = state.get("report_config", {})
    research_question = state.get("research_question", "")
    research_questions = state.get("research_questions", [])
    collection_names = state.get("collection_names")

    # Primary results (already computed by network_node)
    primary_results = state.get("primary_results", state.get("network_results", {}))
    primary_ptm_type = state.get("primary_ptm_type", state.get("ptm_type", "phosphorylation"))
    primary_md_content = state.get("primary_md_content", state.get("md_content", ""))
    primary_tsv_path = state.get("primary_tsv_path")

    # Secondary results
    secondary_results = state.get("secondary_results", {})
    secondary_ptm_type = state.get("secondary_ptm_type", "ubiquitylation")
    secondary_md_content = state.get("secondary_md_content", "")
    secondary_tsv_path = state.get("secondary_tsv_path")

    if not secondary_results:
        logger.warning("No secondary results provided for Cross-Talk analysis")
        state["crosstalk_data"] = {}
        state["crosstalk_report"] = ""
        return state

    # ── Build cross-talk data ─────────────────────────────────────────────
    if cb:
        cb(50, "Building cross-talk analysis data")

    crosstalk_data = build_crosstalk_data(
        primary_results=primary_results,
        primary_ptm_type=primary_ptm_type,
        primary_md_content=primary_md_content,
        secondary_results=secondary_results,
        secondary_ptm_type=secondary_ptm_type,
        secondary_md_content=secondary_md_content,
        primary_tsv_path=primary_tsv_path,
        secondary_tsv_path=secondary_tsv_path,
    )

    n_dual = len(crosstalk_data["dual_ptm_proteins"])
    n_conc = len(crosstalk_data["concordant_pairs"])
    n_disc = len(crosstalk_data["discordant_pairs"])
    n_gate = len(crosstalk_data["sequential_gating"])
    n_shared_nonptm = len(crosstalk_data["shared_nonptm"])

    logger.info(
        f"[CrossTalk] Data: {n_dual} dual-PTM, {n_conc} concordant, "
        f"{n_disc} discordant, {n_gate} gating, {n_shared_nonptm} shared Non-PTM"
    )

    crosstalk_context = _build_crosstalk_context_for_llm(crosstalk_data)
    _whitelist_text = _build_whitelist_text(crosstalk_data)

    # ── Prepare shared variables ──────────────────────────────────────────
    if not research_questions:
        research_questions = [research_question] if research_question else []
    all_questions_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(research_questions)])
    if research_questions and not research_question:
        research_question = research_questions[0]

    p_type = primary_ptm_type.capitalize()
    s_type = secondary_ptm_type.capitalize()
    primary_summary = primary_results.get("summary", {})
    secondary_summary = secondary_results.get("summary", {})
    primary_timepoints = sorted(primary_results.get("timepoints", []), key=_parse_timepoint)
    secondary_timepoints = sorted(secondary_results.get("timepoints", []), key=_parse_timepoint)
    all_timepoints = sorted(set(primary_timepoints + secondary_timepoints), key=_parse_timepoint)

    # ── ChromaDB search ───────────────────────────────────────────────────
    if cb:
        cb(55, "Searching literature for cross-talk context")

    literature_context = ""
    chromadb_results = []
    try:
        rag = RAGRetriever(collection_names=collection_names)
        queries = [
            f"{p_type} {s_type} cross-talk signaling",
            f"{p_type} {s_type} interplay regulation",
            f"phosphorylation ubiquitylation crosstalk",
        ]
        chromadb_results = rag.search(queries)
        if chromadb_results:
            lit_parts = [
                "The following are excerpts from previously published studies, review papers, and textbooks.",
                "Each excerpt is labeled with its SOURCE TYPE. PRIORITY: Textbook > Review Paper > Research Article.",
                "MANDATORY: Use [n] inline citations when referencing these. "
                "NEVER mention 'ChromaDB', 'knowledge base', 'database', 'collection', or 'vector store'.\n",
            ]
            for i, r in enumerate(chromadb_results[:8], 1):
                source = r.get("metadata", {}).get("source", "Literature")
                source_type = r.get("source_type", "research_article")
                type_label = {
                    "textbook": "Textbook Reference",
                    "review": "Review Paper Reference",
                    "research_article": "Research Article Reference",
                }.get(source_type, "Published Literature Reference")
                lit_parts.append(
                    f"**{type_label} [{i}]** ({source}):\n"
                    f"**Source Type:** {source_type.replace('_', ' ').title()}\n"
                    f"{r['content'][:600]}"
                )
            literature_context = "\n\n".join(lit_parts)
            logger.info(f"Retrieved {len(chromadb_results)} results from ChromaDB")
    except Exception as e:
        logger.warning(f"ChromaDB search failed: {e}")

    # ── Build detail strings for LLM prompts ──────────────────────────────
    dual_ptm_detail = ""
    for dp in crosstalk_data["dual_ptm_proteins"][:15]:
        pattern_label = dp["pattern"].upper()
        dual_ptm_detail += f"\n**{dp['gene']}** [{pattern_label}, concordance={dp['concordant_ratio']:.0%}]"
        dual_ptm_detail += f"\n  {p_type} sites: {', '.join(dp['primary_sites'][:5])}"
        dual_ptm_detail += f"\n  {s_type} sites: {', '.join(dp['secondary_sites'][:5])}"
        for tp, comp in list(dp["temporal_comparison"].items())[:4]:
            if comp["concordant"] is True:
                conc_label = "CONCORDANT"
            elif comp["concordant"] is False:
                conc_label = "DISCORDANT"
            else:
                conc_label = "NEUTRAL (one PTM below threshold)"
            dual_ptm_detail += (
                f"\n  {tp}: {p_type}={comp['primary_state']}"
                f"(Log2FC={comp['primary_ptm_log2fc']:.2f}), "
                f"{s_type}={comp['secondary_state']}"
                f"(Log2FC={comp['secondary_ptm_log2fc']:.2f}) -> {conc_label}"
            )

    gating_detail = ""
    for gate in crosstalk_data["sequential_gating"][:10]:
        gating_detail += f"\n**{gate['gene']}**: {gate['leading_ptm'].capitalize()} leads -> {gate['lagging_ptm'].capitalize()} follows"
        gating_detail += f"\n  Leading first at: {gate['leading_first_tp']}, Lagging first at: {gate['lagging_first_tp']}"
        gating_detail += f"\n  Time lag: {gate['time_lag_minutes']:.0f} min | Mechanism: {gate['mechanism_hint']}"

    shared_nonptm_text = (
        ", ".join(crosstalk_data["shared_nonptm"][:20])
        if crosstalk_data["shared_nonptm"]
        else "None identified"
    )

    # Non-PTM temporal analysis and PTM→Protein timelag for prompts
    nonptm_temporal_text = ""
    try:
        nonptm_temporal_text = build_nonptm_temporal_analysis(crosstalk_data)
    except Exception as e:
        logger.warning(f"Non-PTM temporal analysis failed: {e}")

    ptm_timelag_text = ""
    try:
        ptm_timelag_text = build_ptm_protein_timelag_analysis(
            {}, {}, primary_ptm_type, secondary_ptm_type,
            crosstalk_data=crosstalk_data
        )
        if isinstance(ptm_timelag_text, list):
            # If it returned a list (from build function), format it
            ptm_timelag_text = json.dumps(ptm_timelag_text[:10], indent=2)
    except Exception as e:
        logger.warning(f"PTM timelag analysis failed: {e}")

    # MD file context
    primary_md_file_context = primary_md_content[:2000] if primary_md_content else ""

    # ── Generate report sections with LLM ─────────────────────────────────
    if cb:
        cb(60, "Generating Cross-Talk report sections")

    llm = LLMClient()
    report_parts = []

    system_prompt = (
        "You are a scientific writer specializing in post-translational modification (PTM) cross-talk analysis. "
        "Write in formal academic English. Use flowing prose, not bullet points. "
        "Cite references using numbered brackets (e.g., [1], [2]). "
        "NEVER mention 'ChromaDB' or 'knowledge base'. "
        "Be precise with PTM site nomenclature."
    )

    # ── Title & Header ──
    report_parts.append(f"# {p_type}–{s_type} Post-Translational Modification Cross-Talk Analysis\n")
    report_parts.append(
        f"*Integrated temporal analysis of {p_type} and {s_type} co-regulation patterns, "
        f"sequential gating events, and shared signaling network topology*\n"
    )
    report_parts.append("---\n")

    # ── Abstract ──
    if cb:
        cb(65, "Writing Abstract")

    abstract_prompt = f"""You are writing the Abstract for a peer-reviewed proteomics paper on {p_type.upper()}–{s_type.upper()} post-translational modification CROSS-TALK.

## EXPERIMENTAL SYSTEM
{primary_md_file_context if primary_md_file_context else 'Quantitative PTM analysis with integrated network approach'}

## QUANTITATIVE CROSS-TALK DATA
- {p_type} dataset: {primary_summary.get('total_ptms', 0)} modification sites, {primary_summary.get('total_edges', 0)} regulatory interactions
- {s_type} dataset: {secondary_summary.get('total_ptms', 0)} modification sites, {secondary_summary.get('total_edges', 0)} regulatory interactions
- Dual-PTM proteins (bearing BOTH modifications): {n_dual}
- Concordant co-regulation: {n_conc} proteins
- Discordant regulation: {n_disc} proteins
- Sequential gating events: {n_gate}
- Shared non-PTM interactors: {n_shared_nonptm}
- Temporal resolution: {', '.join(all_timepoints)}

## PUBLISHED LITERATURE
{literature_context if literature_context else 'General PTM cross-talk biology'}

## ABSTRACT WRITING GUIDE
Write a single flowing paragraph (250-400 words):
1. OPENING: State the biological importance of PTM cross-talk.
2. APPROACH: Describe the analytical approach.
3. KEY FINDINGS: Report main results with SPECIFIC NUMBERS.
4. MECHANISTIC INSIGHT: Connect findings to known mechanisms.
5. SIGNIFICANCE: Broader implication.

## STRICT REQUIREMENTS
- Passive voice, formal academic tone
- Include specific quantitative values
- Do NOT use bullet points
- NEVER mention 'ChromaDB', 'knowledge base', 'database'
- Use [n] inline citations
- DATA INTEGRITY: If data shows 0 for any category, do NOT mention it as a finding

## Abstract
"""
    abstract_result = llm.generate(abstract_prompt, system_prompt=system_prompt, max_tokens=3072)
    if abstract_result and len(abstract_result.strip()) > 80:
        try:
            abstract_result = ensure_abstract_completeness(abstract_result, abstract_prompt, llm)
        except Exception:
            pass
        abstract_result = re.sub(r"^#+\s*(Abstract|ABSTRACT|abstract)\s*\n*", "", abstract_result.strip())
        report_parts.append(f"## Abstract\n\n{abstract_result.strip()}\n")
    else:
        report_parts.append(
            f"## Abstract\n\nThis study presents a comprehensive cross-talk analysis between "
            f"{p_type} and {s_type} post-translational modifications, identifying {n_dual} dual-PTM "
            f"proteins with {n_conc} concordant and {n_disc} discordant regulatory patterns across "
            f"{len(all_timepoints)} timepoints.\n"
        )
    report_parts.append("\n---\n")

    # ── Introduction ──
    if cb:
        cb(70, "Writing Introduction")

    intro_prompt = f"""You are writing the Introduction section for a peer-reviewed proteomics paper on {p_type.upper()}–{s_type.upper()} post-translational modification CROSS-TALK.

## RESEARCH CONTEXT
{all_questions_text if all_questions_text else 'Systematic cross-talk analysis'}

## EXPERIMENTAL SYSTEM
{primary_md_file_context}

## PUBLISHED LITERATURE
{literature_context if literature_context else 'General PTM cross-talk biology'}

## QUANTITATIVE DATA PREVIEW
- {n_dual} dual-PTM proteins, {n_conc} concordant, {n_disc} discordant
- {n_gate} sequential gating events, {n_shared_nonptm} shared non-PTM interactors

## STRUCTURE
Write 4-5 paragraphs:
1. PTM cross-talk as a fundamental regulatory mechanism
2. Specific biology of {p_type} and {s_type} and their known interplay
3. Current gaps in understanding temporal coordination
4. Rationale and objectives of this study

## STRICT REQUIREMENTS
- Formal academic tone, passive voice
- Use [n] inline citations
- Do NOT mention 'ChromaDB', 'knowledge base', 'database'
- NEVER output placeholder text

## Introduction
"""
    intro_result = llm.generate(intro_prompt, system_prompt=system_prompt, max_tokens=4096)
    if intro_result and len(intro_result.strip()) > 100:
        intro_result = re.sub(r"^#+\s*(Introduction|INTRODUCTION)\s*\n*", "", intro_result.strip())
        report_parts.append(f"## Introduction\n\n{intro_result.strip()}\n")
    else:
        report_parts.append(
            f"## Introduction\n\nPost-translational modification (PTM) cross-talk between "
            f"{p_type} and {s_type} represents a critical regulatory mechanism in cellular signaling.\n"
        )
    report_parts.append("\n---\n")

    # ── Results ──
    if cb:
        cb(75, "Writing Results")

    results_prompt = f"""You are writing the Results section for a peer-reviewed proteomics paper on {p_type.upper()}–{s_type.upper()} post-translational modification CROSS-TALK.

## RESEARCH CONTEXT
{all_questions_text if all_questions_text else 'Systematic cross-talk analysis'}

## QUANTITATIVE CROSS-TALK DATA
### Dataset Dimensions
- {p_type} dataset: {primary_summary.get('total_ptms', 0)} modification sites, {primary_summary.get('total_edges', 0)} regulatory interactions
- {s_type} dataset: {secondary_summary.get('total_ptms', 0)} modification sites, {secondary_summary.get('total_edges', 0)} regulatory interactions
- Temporal resolution: {', '.join(all_timepoints)}

### Dual-PTM Protein Landscape
- Total dual-PTM proteins: {n_dual}
- Concordant co-regulation: {n_conc} proteins
- Discordant regulation: {n_disc} proteins

### Individual Dual-PTM Protein Data
{dual_ptm_detail}

### Sequential Gating Events
{gating_detail if gating_detail else 'No sequential gating events detected.'}

### Shared Non-PTM Interactors
{shared_nonptm_text}

## DETAILED CROSS-TALK ANALYSIS DATA
{nonptm_temporal_text}
{ptm_timelag_text if isinstance(ptm_timelag_text, str) else ''}

## PUBLISHED LITERATURE
{literature_context if literature_context else 'General PTM cross-talk biology'}

## STRUCTURE
Write comprehensive results organized by:
1. Dual-PTM protein identification and classification
2. Concordant/discordant regulation patterns
3. Sequential gating analysis
4. Shared non-PTM interactors as convergence hubs
5. Signal propagation dynamics

## STRICT REQUIREMENTS
- Use SPECIFIC protein names and quantitative data
- Use [n] inline citations
- Formal academic tone, passive voice
- ONLY mention proteins from the data above
- DATA INTEGRITY: If data shows 0 for any category, do NOT discuss it

## Results
"""
    results_result = llm.generate_with_retry(
        results_prompt, system_prompt=system_prompt, max_tokens=16384, min_words=300
    )
    if results_result and len(results_result.strip()) > 100:
        results_result = re.sub(r"^#+\s*(Results|RESULTS)\s*\n*", "", results_result.strip())
        report_parts.append(f"## Results\n\n{results_result.strip()}\n")
    else:
        fallback_results = generate_crosstalk_results_fallback(
            n_dual, n_conc, n_disc, n_gate, n_shared_nonptm,
            p_type, s_type, all_timepoints, crosstalk_data
        )
        report_parts.append(f"## Results\n\n{fallback_results}\n")
    report_parts.append("\n---\n")

    # ── Cross-Talk Figures (placeholder for crosstalk_figures.py integration) ──
    # Figure generation will be handled by crosstalk_figures.py in Phase 3-3

    # ── Discussion ──
    if cb:
        cb(82, "Writing Discussion")

    discussion_prompt = f"""You are writing the Discussion section for a peer-reviewed proteomics paper on {p_type.upper()}–{s_type.upper()} post-translational modification CROSS-TALK.

## PROTEIN NAME WHITELIST
You may ONLY mention the following protein/gene names:
{_whitelist_text}

## RESEARCH CONTEXT
{all_questions_text if all_questions_text else 'Systematic cross-talk analysis'}

## EXPERIMENTAL SYSTEM
{primary_md_file_context}

## KEY FINDINGS TO INTERPRET
- {n_dual} dual-PTM proteins carrying both {p_type} and {s_type}
- {n_conc} concordant, {n_disc} discordant regulatory patterns
- {n_gate} sequential gating events
- {n_shared_nonptm} shared non-PTM interactors

## SPECIFIC PROTEIN DATA
{dual_ptm_detail}

## DETAILED CROSS-TALK ANALYSIS DATA
{nonptm_temporal_text}
{ptm_timelag_text if isinstance(ptm_timelag_text, str) else ''}

## PUBLISHED LITERATURE
{literature_context if literature_context else 'General PTM cross-talk biology'}

## STRUCTURE (8 paragraphs)
1. Overview of cross-talk landscape
2. Concordant regulation as signal amplification
3. Discordant regulation as signal switching
4. Sequential gating as temporal hierarchy
5. Non-PTM effector proteins as signal integration nodes
6. PTM→Protein time lag as signal propagation dynamics
7. Comparison with published cross-talk studies
8. Limitations and future directions

## STRICT REQUIREMENTS
- Use SPECIFIC protein names from the data
- Use [n] inline citations
- Formal academic tone, passive voice
- ONLY mention proteins from the WHITELIST
- DATA INTEGRITY: If data shows 0 for any category, do NOT discuss it as a finding

## Discussion
"""
    discussion_result = llm.generate_with_retry(
        discussion_prompt, system_prompt=system_prompt, max_tokens=12288, min_words=300
    )
    if discussion_result and len(discussion_result.strip()) > 100:
        discussion_result = re.sub(r"^#+\s*(Discussion|DISCUSSION)\s*\n*", "", discussion_result.strip())
        report_parts.append(f"## Discussion\n\n{discussion_result.strip()}\n")
    else:
        fallback_discussion = generate_crosstalk_discussion_fallback(
            n_dual, n_conc, n_disc, n_gate, n_shared_nonptm,
            p_type, s_type, all_timepoints, crosstalk_data
        )
        report_parts.append(f"## Discussion\n\n{fallback_discussion}\n")
    report_parts.append("\n---\n")

    # ── Conclusion ──
    if cb:
        cb(87, "Writing Conclusion")

    conclusion_prompt = f"""You are writing the Conclusion section for a peer-reviewed proteomics paper on {p_type.upper()}–{s_type.upper()} post-translational modification CROSS-TALK.

## PROTEIN NAME WHITELIST
{_whitelist_text}

## KEY FINDINGS
- {n_dual} dual-PTM proteins, {n_conc} concordant, {n_disc} discordant
- {n_gate} sequential gating events
- {n_shared_nonptm} shared non-PTM interactors

## STRUCTURE
Write 2-3 paragraphs:
1. Summary of key findings
2. Broader significance and mechanistic implications
3. Future directions

## STRICT REQUIREMENTS
- Formal academic tone, passive voice
- Use [n] inline citations
- ONLY mention proteins from the WHITELIST
- DATA INTEGRITY: zero means zero

## Conclusion
"""
    conclusion_result = llm.generate(conclusion_prompt, system_prompt=system_prompt, max_tokens=6144)
    if conclusion_result and len(conclusion_result.strip()) > 80:
        conclusion_result = re.sub(r"^#+\s*(Conclusion|CONCLUSION)\s*\n*", "", conclusion_result.strip())
        report_parts.append(f"## Conclusion\n\n{conclusion_result.strip()}\n")
    else:
        fallback_conclusion = generate_crosstalk_conclusion_fallback(
            n_dual, n_conc, n_disc, n_gate, n_shared_nonptm,
            p_type, s_type, all_timepoints
        )
        report_parts.append(f"## Conclusion\n\n{fallback_conclusion}\n")
    report_parts.append("\n---\n")

    # ── Methods ──
    if cb:
        cb(90, "Writing Methods")

    methods_section = f"""## Methods

### Data Acquisition and Processing

Two independent quantitative PTM datasets were analyzed in parallel: a {p_type} dataset containing modification site information and a {s_type} dataset containing modification site information. Both datasets were acquired across {len(all_timepoints)} temporal conditions ({', '.join(all_timepoints)}), enabling temporal cross-talk analysis.

### Individual PTM Network Construction

Each PTM dataset was independently processed using the PTM-NonPTM Network Analyzer to construct regulatory networks. The {p_type} network utilized upstream kinase identification via Kinase Enrichment Analysis (KEA3 API) and STRING-DB protein-protein interaction data (confidence score >= 0.4). The {s_type} network utilized E3 ubiquitin ligase-substrate relationship prediction and STRING-DB integration.

### Cross-Talk Identification and Classification

Cross-talk between {p_type} and {s_type} was assessed following established analytical frameworks. Dual-PTM proteins were identified by gene name matching across the two datasets. Concordance/discordance classification compared the direction of PTM change at each shared timepoint. Sequential gating analysis determined the temporal ordering of PTM events. Shared non-PTM interactors were identified as cross-talk convergence hubs.

### Visualization

Cross-talk patterns were visualized using structured tables and publication-quality figures including dual-PTM protein summary tables, temporal cross-talk regulation heatmaps, and PTM cross-talk regulatory relationship tables.

### Literature Integration

Biological interpretation was supported by published review papers, textbooks, and primary research articles retrieved from curated literature collections.
"""
    report_parts.append(methods_section)
    report_parts.append("\n---\n")

    # ── Assemble, post-process, save ──────────────────────────────────────
    if cb:
        cb(93, "Post-processing report")

    full_report = "\n".join(report_parts)

    # Merge empty subsections
    try:
        full_report = merge_empty_subsections(full_report)
    except Exception as e:
        logger.warning(f"Empty subsection merging failed: {e}")

    # Strip placeholder brackets
    full_report = re.sub(r"\[insert[^\]]*\]", "", full_report)
    full_report = re.sub(r"\[specific[^\]]*\]", "", full_report)
    full_report = re.sub(r"\[value\]", "", full_report)
    full_report = re.sub(r"  +", " ", full_report)

    # Post-process
    try:
        crosstalk_metadata = {
            "n_dual": n_dual,
            "n_conc": n_conc,
            "n_disc": n_disc,
            "n_gate": n_gate,
            "n_shared_nonptm": n_shared_nonptm,
        }
        full_report = postprocess_full_report(
            full_report, ptm_type=primary_ptm_type, crosstalk_metadata=crosstalk_metadata
        )
    except Exception as e:
        logger.warning(f"Post-processing failed: {e}")

    # Save report
    report_file = os.path.join(output_dir, "final_report.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(full_report)
    logger.info(f"Cross-talk report saved: {report_file}")

    # Save cross-talk JSON
    try:
        crosstalk_json_path = os.path.join(output_dir, "crosstalk_analysis.json")
        serializable = json.loads(
            json.dumps(crosstalk_data, default=lambda o: list(o) if isinstance(o, set) else str(o))
        )
        with open(crosstalk_json_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        logger.info(f"Cross-talk analysis data saved: {crosstalk_json_path}")
    except Exception as e:
        logger.warning(f"Failed to save cross-talk JSON: {e}")

    # Save signal propagation JSON
    try:
        signal_prop_data = build_signal_propagation_json_from_crosstalk(crosstalk_data)
        if signal_prop_data:
            signal_prop_path = os.path.join(output_dir, "signal_propagation.json")
            with open(signal_prop_path, "w", encoding="utf-8") as f:
                json.dump(signal_prop_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Signal propagation data saved: {signal_prop_path}")
    except Exception as e:
        logger.warning(f"Failed to save signal propagation JSON: {e}")

    if cb:
        cb(95, "Cross-talk analysis complete")

    # Update state
    state["crosstalk_data"] = crosstalk_data
    state["crosstalk_report"] = full_report
    state["report_file"] = report_file
    state["cross_talk_data"] = crosstalk_data  # for DB storage

    return state
