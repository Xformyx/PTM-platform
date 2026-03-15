"""
Network Node — temporal PTM signaling network analysis + Cytoscape visualization.
Ported from multi_agent_system/agents/network_analyzer.py and ptm_network_automation.py.

v2.0 — Full alignment with cytoscape_network_pipeline_guide.md:
  GAP 1: Time-point based network analysis (analyze_timepoint logic)
  GAP 2: Non-PTM node generation from KEGG pathway / enrichment data
  GAP 3: Enhanced FigureInformationGenerator integration
  GAP 4: Multi-type legend generation (full, individual panel, temporal comparison)
  GAP 5: Cross-Talk Figure integration placeholder
  GAP 6: Color palette alignment with guide

Option A: connects to Cytoscape Desktop on the Docker host via host.docker.internal.
Falls back to text-based legend when Cytoscape is unavailable.
"""

import base64
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CYTOSCAPE_HOST = os.getenv("CYTOSCAPE_HOST", "host.docker.internal")
CYTOSCAPE_PORT = int(os.getenv("CYTOSCAPE_PORT", "1234"))

# ---------------------------------------------------------------------------
# GAP 6: Color palette aligned with cytoscape_network_pipeline_guide.md §4.3
# ---------------------------------------------------------------------------

NODE_COLORS = {
    "high_active": "#FF0000",       # Red — Log2FC > 1.0
    "moderate_active": "#FF8C00",   # Dark Orange — 0 < Log2FC <= 1.0
    "low_active": "#FFD700",        # Gold — weak activation
    "inhibited": "#4169E1",         # Royal Blue — Log2FC < 0
    "low_inhibited": "#87CEEB",     # Light Blue — -1 < Log2FC < 0
    "non_ptm": "#90EE90",           # Light Green — Non-PTM protein (guide §4.3)
    "neutral": "#C0C0C0",           # Silver — neutral
    "missing": "#BDC3C7",           # Gray — missing data
}

EDGE_COLORS = {
    "STRING": "#808080",            # Gray — STRING-DB PPI (guide §4.3)
    "STRING-DB": "#808080",         # Alias
    "KEGG": "#228B22",              # Forest Green — KEGG pathway (guide §4.3)
    "KEA3": "#FF4500",              # Orange-Red — Kinase-substrate (guide §4.3)
    "Shared Pathway": "#228B22",    # Same as KEGG
    "Kinase-Substrate": "#FF4500",  # Same as KEA3
    "Kinase-Substrate-Predicted": "#D8BFD8",  # Light purple
    "Literature": "#E377C2",        # Pink
    "Co-activation": "#7F7F7F",     # Gray
    "Predicted": "#BCBD22",         # Yellow-green
    "Unknown": "#C7C7C7",          # Light gray
    "default": "#95A5A6",          # Default gray
}

# Node shape mapping (guide §4.3)
NODE_SHAPES = {
    "PTM": "ELLIPSE",              # Circle for PTM sites
    "Non-PTM": "DIAMOND",          # Diamond for Non-PTM proteins
    "Kinase": "DIAMOND",           # Diamond for kinases (package version)
    "Interactor": "ROUND_RECTANGLE",
    "Pathway-Member": "HEXAGON",
}


# ---------------------------------------------------------------------------
# GAP 6: Activation state classifier aligned with guide §7.1
# ---------------------------------------------------------------------------

def _classify_state(value: float) -> str:
    """Classify PTM activation state based on Log2FC value.
    Aligned with guide §7.1 get_activation_state().
    """
    if value is None:
        return "missing"
    if value > 1.0:
        return "high_active"
    if value > 0.0:
        return "moderate_active"
    if value < -1.0:
        return "inhibited"
    if value < 0.0:
        return "low_inhibited"
    return "neutral"


# ---------------------------------------------------------------------------
# Time-point detection helper
# ---------------------------------------------------------------------------

def _detect_timepoints(parsed_ptms: list) -> List[str]:
    """Detect unique timepoints/conditions from parsed PTM data.
    Returns sorted list of condition strings (e.g., ['2min', '5min', '10min']).
    """
    conditions = set()
    for ptm in parsed_ptms:
        cond = ptm.get("condition") or ptm.get("Condition", "")
        if cond and cond.strip():
            conditions.add(cond.strip())
    return sorted(conditions, key=_tp_to_minutes)


def _tp_to_minutes(tp: str) -> float:
    """Convert timepoint string to minutes for sorting.
    Handles formats like '2min', '5min', '1h', '30s', etc.
    Returns -1.0 for non-time conditions (alphabetical fallback).
    """
    tp_lower = tp.lower().strip()
    import re as _re
    # Minutes
    m = _re.match(r'^(\d+(?:\.\d+)?)\s*min', tp_lower)
    if m:
        return float(m.group(1))
    # Hours
    m = _re.match(r'^(\d+(?:\.\d+)?)\s*h', tp_lower)
    if m:
        return float(m.group(1)) * 60
    # Seconds
    m = _re.match(r'^(\d+(?:\.\d+)?)\s*s(?:ec)?', tp_lower)
    if m:
        return float(m.group(1)) / 60
    return -1.0


def _tp_to_phase(tp: str) -> str:
    """Classify timepoint into phase label (guide §6.1)."""
    minutes = _tp_to_minutes(tp)
    if minutes < 0:
        return "Condition"
    if minutes < 10:
        return "Early Phase"
    if minutes <= 40:
        return "Mid Phase"
    return "Late Phase"


# ---------------------------------------------------------------------------
# GAP 1: Time-point based network analysis (guide §3.1 analyze_timepoint)
# ---------------------------------------------------------------------------

def _analyze_timepoint(
    parsed_ptms: list,
    enriched_data: list,
    timepoint: str,
    threshold: float = 0.0,
) -> dict:
    """Analyze network for a single timepoint/condition.
    
    Implements guide §3.1 analyze_timepoint() logic:
    1. Collect activated PTM nodes (Log2FC > threshold)
    2. Collect active edges (both endpoints activated)
    3. Collect Non-PTM proteins from KEGG/enrichment data
    4. Aggregate pathway information
    
    Returns structure matching guide §3.1 return format.
    """
    # Filter PTMs for this timepoint
    tp_ptms = [p for p in parsed_ptms
               if (p.get("condition") or p.get("Condition", "")).strip() == timepoint]

    if not tp_ptms:
        return {
            "timepoint": timepoint,
            "active_ptm_nodes": [],
            "non_ptm_nodes": [],
            "active_edges": [],
            "all_edges": [],
            "pathway_summary": {},
            "stats": {
                "active_ptm_count": 0,
                "non_ptm_count": 0,
                "active_edge_count": 0,
                "total_edge_count": 0,
            },
        }

    # 1. Collect PTM nodes
    active_ptm_nodes = []
    inhibited_ptm_nodes = []
    all_ptm_nodes = []
    gene_ptms = defaultdict(list)
    ptm_genes = set()

    for ptm in tp_ptms:
        fc = ptm.get("ptm_relative_log2fc", 0)
        state = _classify_state(fc)
        gene = ptm.get("gene", "Unknown")
        site = ptm.get("position", "")
        node_id = f"{gene}-{site}"

        node = {
            "id": node_id,
            "gene": gene,
            "site": site,
            "type": "PTM",
            "value": round(fc, 3),
            "state": state,
            "trend": "up" if fc > 0 else ("down" if fc < 0 else "neutral"),
            "protein_log2fc": ptm.get("protein_log2fc", 0),
            "label": node_id,
        }

        all_ptm_nodes.append(node)
        gene_ptms[gene].append(node_id)
        ptm_genes.add(gene.upper())

        if abs(fc) > threshold:
            if fc > 0:
                active_ptm_nodes.append(node)
            else:
                inhibited_ptm_nodes.append(node)

    # 2. Build edges from enrichment data
    all_edges = []
    active_edges = []
    active_node_ids = {n["id"] for n in active_ptm_nodes + inhibited_ptm_nodes}

    # Map enriched data by gene for this timepoint
    enriched_by_gene = {}
    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip()
        cond = (ptm_data.get("Condition") or ptm_data.get("condition", "")).strip()
        if cond == timepoint and gene:
            enriched_by_gene[gene] = ptm_data

    for gene, ptm_data in enriched_by_gene.items():
        enr = ptm_data.get("rag_enrichment", {})
        pos = ptm_data.get("position") or ptm_data.get("PTM_Position", "")
        source_id = f"{gene}-{pos}"

        # STRING-DB interactions
        string_interactions = enr.get("string_interactions", [])
        for interaction in string_interactions[:5]:
            if isinstance(interaction, dict):
                partner = interaction.get("partner", "")
                confidence = interaction.get("score", 0.7)
            elif isinstance(interaction, str):
                partner = interaction.split("(")[0].strip() if "(" in interaction else interaction
                confidence = 0.7
            else:
                continue
            if partner in gene_ptms:
                for target_id in gene_ptms[partner]:
                    edge = {
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "STRING",
                        "confidence": confidence,
                        "pathways": [],
                    }
                    all_edges.append(edge)
                    if source_id in active_node_ids and target_id in active_node_ids:
                        edge_copy = dict(edge)
                        edge_copy["is_active_edge"] = True
                        active_edges.append(edge_copy)

        # Shared pathway edges
        def _pw_str(p):
            return p.get("name", str(p)) if isinstance(p, dict) else str(p)

        pathways = enr.get("pathways", [])
        pw_set = {_pw_str(p) for p in pathways}

        for other_gene, other_data in enriched_by_gene.items():
            if other_gene == gene:
                continue
            other_enr = other_data.get("rag_enrichment", {})
            other_pw = {_pw_str(p) for p in other_enr.get("pathways", [])}
            shared = pw_set & other_pw
            if shared:
                other_pos = other_data.get("position") or other_data.get("PTM_Position", "")
                other_id = f"{other_gene}-{other_pos}"
                edge = {
                    "source": source_id,
                    "target": other_id,
                    "evidence_type": "KEGG",
                    "confidence": 0.5,
                    "pathways": list(shared)[:3],
                }
                all_edges.append(edge)
                if source_id in active_node_ids and other_id in active_node_ids:
                    edge_copy = dict(edge)
                    edge_copy["is_active_edge"] = True
                    active_edges.append(edge_copy)

        # Kinase-substrate edges
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        for kinase in upstream[:3]:
            kinase_name = kinase if isinstance(kinase, str) else str(kinase)
            if kinase_name in gene_ptms:
                for target_id in gene_ptms[kinase_name]:
                    edge = {
                        "source": target_id,
                        "target": source_id,
                        "evidence_type": "KEA3",
                        "confidence": 0.8,
                        "pathways": [],
                    }
                    all_edges.append(edge)
                    if target_id in active_node_ids and source_id in active_node_ids:
                        edge_copy = dict(edge)
                        edge_copy["is_active_edge"] = True
                        active_edges.append(edge_copy)

    # Deduplicate edges
    def _dedup_edges(edges):
        seen = set()
        unique = []
        for e in edges:
            key = tuple(sorted([e["source"], e["target"]])) + (e["evidence_type"],)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique

    all_edges = _dedup_edges(all_edges)
    active_edges = _dedup_edges(active_edges)

    # 3. GAP 2: Non-PTM node generation from enrichment data
    non_ptm_nodes = _extract_non_ptm_nodes(enriched_by_gene, ptm_genes, timepoint)

    # 4. Pathway summary
    pathway_summary = defaultdict(list)
    for e in active_edges:
        for pw in e.get("pathways", []):
            pathway_summary[pw].append(f"{e['source']} ↔ {e['target']}")

    stats = {
        "active_ptm_count": len(active_ptm_nodes),
        "inhibited_ptm_count": len(inhibited_ptm_nodes),
        "non_ptm_count": len(non_ptm_nodes),
        "active_edge_count": len(active_edges),
        "total_edge_count": len(all_edges),
    }

    return {
        "timepoint": timepoint,
        "active_ptm_nodes": active_ptm_nodes,
        "inhibited_ptm_nodes": inhibited_ptm_nodes,
        "non_ptm_nodes": non_ptm_nodes,
        "active_edges": active_edges,
        "all_edges": all_edges,
        "pathway_summary": dict(pathway_summary),
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# GAP 2: Non-PTM node generation (guide §3.1 step 3)
# ---------------------------------------------------------------------------

def _extract_non_ptm_nodes(
    enriched_by_gene: dict,
    ptm_genes: set,
    timepoint: str,
) -> list:
    """Extract Non-PTM protein nodes from enrichment data.
    
    Non-PTM proteins are those found in KEGG pathways or STRING interactions
    but NOT already included as PTM nodes. They represent pathway members,
    kinases, and interactors that provide network context.
    
    Guide §3.1 step 3: KEGG pathway에 포함된 단백질 중 PTM으로 이미 포함되지 않은 것.
    """
    non_ptm_nodes = []
    seen_genes = set()

    for gene, ptm_data in enriched_by_gene.items():
        enr = ptm_data.get("rag_enrichment", {})

        # Extract from STRING interactions
        string_interactions = enr.get("string_interactions", [])
        for interaction in string_interactions[:8]:
            if isinstance(interaction, dict):
                partner = interaction.get("partner", "")
                score = interaction.get("score", 0)
            elif isinstance(interaction, str):
                partner = interaction.split("(")[0].strip() if "(" in interaction else interaction
                score = 0
            else:
                continue

            partner_upper = partner.strip().upper()
            if partner_upper and partner_upper not in ptm_genes and partner_upper not in seen_genes:
                seen_genes.add(partner_upper)
                non_ptm_nodes.append({
                    "id": partner.strip(),
                    "gene": partner.strip(),
                    "site": "",
                    "type": "Non-PTM",
                    "value": score if score else 0,
                    "state": "non_ptm",
                    "identified": True,
                    "label": partner.strip(),
                    "source": "STRING",
                })

        # Extract from pathways
        pathways = enr.get("pathways", [])
        for pw in pathways:
            if isinstance(pw, dict):
                pw_genes = pw.get("genes", [])
                for pg in pw_genes:
                    pg_name = pg if isinstance(pg, str) else str(pg)
                    pg_upper = pg_name.strip().upper()
                    if pg_upper and pg_upper not in ptm_genes and pg_upper not in seen_genes:
                        seen_genes.add(pg_upper)
                        non_ptm_nodes.append({
                            "id": pg_name.strip(),
                            "gene": pg_name.strip(),
                            "site": "",
                            "type": "Non-PTM",
                            "value": 0,
                            "state": "non_ptm",
                            "identified": True,
                            "label": pg_name.strip(),
                            "source": "KEGG",
                        })

        # Extract upstream regulators as potential kinase nodes
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        for kinase in upstream[:3]:
            kinase_name = kinase if isinstance(kinase, str) else str(kinase)
            kinase_upper = kinase_name.strip().upper()
            if kinase_upper and kinase_upper not in ptm_genes and kinase_upper not in seen_genes:
                seen_genes.add(kinase_upper)
                non_ptm_nodes.append({
                    "id": kinase_name.strip(),
                    "gene": kinase_name.strip(),
                    "site": "",
                    "type": "Non-PTM",
                    "value": 0,
                    "state": "non_ptm",
                    "identified": True,
                    "label": kinase_name.strip(),
                    "source": "KEA3",
                })

    # Limit to top 30 Non-PTM nodes to avoid clutter
    return non_ptm_nodes[:30]


# ---------------------------------------------------------------------------
# Build combined network data (backward compatible)
# ---------------------------------------------------------------------------

def _build_network_data(parsed_ptms: list, enriched_data: list) -> dict:
    """Build combined network nodes and edges from all PTMs.
    This is the backward-compatible single-network builder.
    """
    nodes = []
    edges = []
    gene_ptms = defaultdict(list)

    for ptm in parsed_ptms:
        fc = ptm.get("ptm_relative_log2fc", 0)
        state = _classify_state(fc)
        node_id = f"{ptm['gene']}-{ptm['position']}"
        nodes.append({
            "id": node_id,
            "gene": ptm["gene"],
            "site": ptm["position"],
            "type": "PTM",
            "value": round(fc, 3),
            "state": state,
            "label": node_id,
        })
        gene_ptms[ptm["gene"]].append(node_id)

    # Build edges from enrichment data
    ptm_genes = {g.upper() for g in gene_ptms.keys()}

    for ptm_data in enriched_data:
        enr = ptm_data.get("rag_enrichment", {})
        gene = ptm_data.get("gene") or ptm_data.get("Gene.Name", "")
        source_id = f"{gene}-{ptm_data.get('position') or ptm_data.get('PTM_Position', '')}"

        # STRING-DB
        string_interactions = enr.get("string_interactions", [])
        for interaction in string_interactions[:5]:
            if isinstance(interaction, dict):
                partner = interaction.get("partner", "")
                confidence = interaction.get("score", 0.7)
            elif isinstance(interaction, str):
                partner = interaction.split("(")[0].strip() if "(" in interaction else interaction
                confidence = 0.7
            else:
                continue
            if partner in gene_ptms:
                for target_id in gene_ptms[partner]:
                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "STRING",
                        "confidence": confidence,
                        "pathways": [],
                        "pathway_str": "",
                    })

        # Shared pathway edges
        def _pw_str(p):
            return p.get("name", str(p)) if isinstance(p, dict) else str(p)
        pathways = enr.get("pathways", [])
        pw_set = {_pw_str(p) for p in pathways}
        for other_data in enriched_data:
            other_gene = other_data.get("gene") or other_data.get("Gene.Name", "")
            if other_gene == gene:
                continue
            other_enr = other_data.get("rag_enrichment", {})
            other_pw = {_pw_str(p) for p in other_enr.get("pathways", [])}
            shared = pw_set & other_pw
            if shared:
                other_id = f"{other_gene}-{other_data.get('position') or other_data.get('PTM_Position', '')}"
                edges.append({
                    "source": source_id,
                    "target": other_id,
                    "evidence_type": "KEGG",
                    "confidence": 0.5,
                    "pathways": list(shared)[:3],
                    "pathway_str": ", ".join(list(shared)[:2]),
                })

        # Kinase-substrate edges
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        for kinase in upstream[:3]:
            kinase_name = kinase if isinstance(kinase, str) else str(kinase)
            if kinase_name in gene_ptms:
                for target_id in gene_ptms[kinase_name]:
                    edges.append({
                        "source": target_id,
                        "target": source_id,
                        "evidence_type": "KEA3",
                        "confidence": 0.8,
                        "pathways": [],
                        "pathway_str": "",
                    })

    # Deduplicate
    seen = set()
    unique_edges = []
    for e in edges:
        key = tuple(sorted([e["source"], e["target"]])) + (e["evidence_type"],)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    # GAP 2: Add Non-PTM nodes to combined network
    non_ptm_nodes = []
    seen_non_ptm = set()
    for ptm_data in enriched_data:
        enr = ptm_data.get("rag_enrichment", {})
        for interaction in enr.get("string_interactions", [])[:5]:
            if isinstance(interaction, dict):
                partner = interaction.get("partner", "")
            elif isinstance(interaction, str):
                partner = interaction.split("(")[0].strip() if "(" in interaction else interaction
            else:
                continue
            partner_upper = partner.strip().upper()
            if partner_upper and partner_upper not in ptm_genes and partner_upper not in seen_non_ptm:
                seen_non_ptm.add(partner_upper)
                non_ptm_nodes.append({
                    "id": partner.strip(),
                    "gene": partner.strip(),
                    "site": "",
                    "type": "Non-PTM",
                    "value": 0,
                    "state": "non_ptm",
                    "label": partner.strip(),
                })

    all_nodes = nodes + non_ptm_nodes[:20]

    return {"nodes": all_nodes, "edges": unique_edges}


# ---------------------------------------------------------------------------
# Build network_results for writer_node (v98 structured data)
# ---------------------------------------------------------------------------

def _build_network_results_for_writer(
    parsed_ptms: list,
    context: dict,
    timepoint_results: dict = None,
) -> dict:
    """Build network_results structure for writer_node (ptm_only mode).
    
    GAP 1/3: Now supports timepoint-based results when available.
    Enables build_structured_protein_data_for_llm to extract protein names and Log2FC values.
    """
    if timepoint_results:
        # Use timepoint-based results
        timepoints = sorted(timepoint_results.keys(), key=_tp_to_minutes)
        networks = {}
        for tp in timepoints:
            tp_data = timepoint_results[tp]
            networks[tp] = {
                "active_nodes": [
                    {
                        "gene": n["gene"],
                        "site": n["site"],
                        "value": n["value"],
                        "ptm_log2fc": n["value"],
                        "protein_log2fc": n.get("protein_log2fc", 0),
                    }
                    for n in tp_data.get("active_ptm_nodes", [])
                ],
                "inhibited_nodes": [
                    {
                        "gene": n["gene"],
                        "site": n["site"],
                        "value": n["value"],
                        "ptm_log2fc": n["value"],
                        "protein_log2fc": n.get("protein_log2fc", 0),
                    }
                    for n in tp_data.get("inhibited_ptm_nodes", [])
                ],
                "non_ptm_nodes": [
                    {
                        "gene": n["gene"],
                        "value": n.get("value", 0),
                        "state": "non_ptm",
                    }
                    for n in tp_data.get("non_ptm_nodes", [])
                ],
            }
        return {"timepoints": timepoints, "networks": networks}

    # Fallback: single network
    single_tp = context.get("single_time_point", True)
    active_nodes = []
    inhibited_nodes = []
    for p in parsed_ptms:
        node = {
            "gene": p.get("gene", "Unknown"),
            "site": str(p.get("position", "")),
            "value": p.get("ptm_relative_log2fc", 0),
            "ptm_log2fc": p.get("ptm_relative_log2fc", 0),
            "protein_log2fc": p.get("protein_log2fc", 0),
        }
        if node["value"] > 0:
            active_nodes.append(node)
        elif node["value"] < 0:
            inhibited_nodes.append(node)
    tp_name = "default" if single_tp else "multi"
    return {
        "timepoints": [tp_name],
        "networks": {
            tp_name: {
                "active_nodes": active_nodes,
                "inhibited_nodes": inhibited_nodes,
                "non_ptm_nodes": [],
            }
        },
    }


# ---------------------------------------------------------------------------
# GAP 4: Multi-type legend generation (guide §5)
# ---------------------------------------------------------------------------

def _generate_legends(
    network_data: dict,
    ptms: list,
    timepoint_results: dict = None,
) -> dict:
    """Generate multi-type figure legends (guide §5.1).
    
    Returns:
      full_legend: Comprehensive legend for the entire figure
      individual_legends: Per-timepoint panel legends
      comparison_legend: Temporal comparison analysis
      summary_table: Markdown statistics table
    """
    nodes = network_data["nodes"]
    edges = network_data["edges"]

    ptm_nodes = [n for n in nodes if n.get("type") == "PTM"]
    non_ptm_nodes = [n for n in nodes if n.get("type") == "Non-PTM"]
    active = [n for n in ptm_nodes if n["state"] in ("high_active", "moderate_active")]
    inhibited = [n for n in ptm_nodes if n["state"] in ("inhibited", "low_inhibited")]

    # --- Full Legend (guide §5.2) ---
    legend_lines = [
        "### Figure: Temporal Dynamics of PTM Signaling Networks\n",
    ]

    # Overview
    legend_lines.append(
        f"**Overview**: This figure presents the temporal dynamics of post-translational "
        f"modification (PTM) signaling networks. The network contains **{len(ptm_nodes)} PTM nodes**, "
        f"**{len(non_ptm_nodes)} Non-PTM proteins**, and **{len(edges)} interaction edges**.\n"
    )

    # Color Legend (guide §5.2 section 3)
    legend_lines.append("**Node Color Legend**:")
    legend_lines.append(f"- Red ({NODE_COLORS['high_active']}): High activation (Log2FC > 1.0)")
    legend_lines.append(f"- Orange ({NODE_COLORS['moderate_active']}): Moderate activation (0 < Log2FC ≤ 1.0)")
    legend_lines.append(f"- Gold ({NODE_COLORS['low_active']}): Weak activation")
    legend_lines.append(f"- Blue ({NODE_COLORS['inhibited']}): Inhibited (Log2FC < -1.0)")
    legend_lines.append(f"- Light Green ({NODE_COLORS['non_ptm']}): Non-PTM protein")
    legend_lines.append(f"- Gray ({NODE_COLORS['neutral']}): Neutral")
    legend_lines.append("")

    # Node Shape Legend (guide §5.2 section 4)
    legend_lines.append("**Node Shape Legend**:")
    legend_lines.append("- Circle (ELLIPSE): PTM modification sites")
    legend_lines.append("- Diamond: Non-PTM proteins / Kinases")
    legend_lines.append("- Hexagon: Pathway members")
    legend_lines.append("")

    # Node Size Legend (guide §5.2 section 5)
    legend_lines.append("**Node Size Legend**:")
    legend_lines.append("- Node size is proportional to |Log2FC| magnitude (30–100px range)")
    legend_lines.append("")

    # Edge Types
    legend_lines.append("**Edge Types**:")
    evidence_types = defaultdict(int)
    for e in edges:
        evidence_types[e.get("evidence_type", "Unknown")] += 1
    for et, cnt in sorted(evidence_types.items(), key=lambda x: -x[1]):
        color = EDGE_COLORS.get(et, EDGE_COLORS["default"])
        legend_lines.append(f"- {et} ({color}): {cnt} connections")
    legend_lines.append("")

    # Key Active PTMs
    if active:
        legend_lines.append("**Key Active PTMs**:")
        for n in sorted(active, key=lambda x: -x["value"])[:10]:
            legend_lines.append(f"- {n['id']}: Log2FC = {n['value']}")
        legend_lines.append("")

    if inhibited:
        legend_lines.append("**Key Inhibited PTMs**:")
        for n in sorted(inhibited, key=lambda x: x["value"])[:5]:
            legend_lines.append(f"- {n['id']}: Log2FC = {n['value']}")
        legend_lines.append("")

    # --- Individual Panel Legends (guide §5.1 row 2) ---
    individual_legends = {}
    if timepoint_results:
        panel_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, (tp, tp_data) in enumerate(sorted(
            timepoint_results.items(), key=lambda x: _tp_to_minutes(x[0])
        )):
            panel = panel_labels[i] if i < len(panel_labels) else str(i + 1)
            phase = _tp_to_phase(tp)
            stats = tp_data.get("stats", {})
            active_count = stats.get("active_ptm_count", 0)
            inhibited_count = stats.get("inhibited_ptm_count", 0)
            non_ptm_count = stats.get("non_ptm_count", 0)
            edge_count = stats.get("active_edge_count", 0)

            # Top activated PTMs
            top_active = sorted(
                tp_data.get("active_ptm_nodes", []),
                key=lambda x: -x.get("value", 0)
            )[:5]
            top_str = ", ".join(f"{n['gene']}({n['site']})" for n in top_active)

            # Top pathways
            pw_summary = tp_data.get("pathway_summary", {})
            top_pw = sorted(pw_summary.keys(), key=lambda k: -len(pw_summary[k]))[:3]

            panel_legend = (
                f"**Panel {panel} ({tp}, {phase})**: "
                f"{active_count} activated PTMs, {inhibited_count} inhibited PTMs, "
                f"{non_ptm_count} Non-PTM proteins, {edge_count} active edges. "
            )
            if top_str:
                panel_legend += f"Top activated: {top_str}. "
            if top_pw:
                panel_legend += f"Key pathways: {', '.join(top_pw)}."

            individual_legends[tp] = panel_legend

    # --- Summary Statistics Table (guide §5.2 section 6) ---
    summary_table_lines = []
    if timepoint_results:
        summary_table_lines.append(
            "\n| Time Point | Activated PTMs | Inhibited PTMs | Non-PTM Proteins | Active Connections | Top Pathway |"
        )
        summary_table_lines.append(
            "|------------|:--------------:|:--------------:|:----------------:|:------------------:|-------------|"
        )
        for tp, tp_data in sorted(
            timepoint_results.items(), key=lambda x: _tp_to_minutes(x[0])
        ):
            stats = tp_data.get("stats", {})
            pw_summary = tp_data.get("pathway_summary", {})
            top_pw = max(pw_summary.keys(), key=lambda k: len(pw_summary[k])) if pw_summary else "-"
            summary_table_lines.append(
                f"| {tp} | {stats.get('active_ptm_count', 0)} | "
                f"{stats.get('inhibited_ptm_count', 0)} | "
                f"{stats.get('non_ptm_count', 0)} | "
                f"{stats.get('active_edge_count', 0)} | {top_pw} |"
            )
        legend_lines.append("\n".join(summary_table_lines))

    # --- Temporal Comparison Legend (guide §5.1 row 3) ---
    comparison_legend = ""
    if timepoint_results and len(timepoint_results) > 1:
        sorted_tps = sorted(timepoint_results.keys(), key=_tp_to_minutes)
        comp_lines = ["**Temporal Comparison Analysis**:\n"]
        prev_active = 0
        for tp in sorted_tps:
            stats = timepoint_results[tp].get("stats", {})
            curr_active = stats.get("active_ptm_count", 0)
            change = curr_active - prev_active
            direction = "↑" if change > 0 else ("↓" if change < 0 else "→")
            comp_lines.append(
                f"- {tp}: {curr_active} active PTMs ({direction}{abs(change)} from previous)"
            )
            prev_active = curr_active
        comparison_legend = "\n".join(comp_lines)

    # Methods section (guide §5.2 section 7)
    legend_lines.append("\n**Methods**: Networks were constructed from enriched PTM data. "
                       "STRING-DB protein-protein interactions (confidence ≥ 0.4), "
                       "KEGG pathway co-membership, and KEA3 kinase-substrate predictions "
                       "were used as edge evidence. Nodes represent PTM sites (circles) "
                       "and Non-PTM interactors (diamonds). Visual style follows "
                       "publication-quality standards with force-directed layout.")

    return {
        "full_legend": "\n".join(legend_lines),
        "individual_legends": individual_legends,
        "comparison_legend": comparison_legend,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "ptm_count": len(ptm_nodes),
        "non_ptm_count": len(non_ptm_nodes),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_network_analysis(state: dict) -> dict:
    """Analyze temporal networks and optionally generate Cytoscape images.
    
    GAP 1: Now performs per-timepoint analysis when multiple conditions exist.
    """
    os.environ["DEFAULT_BASE_URL"] = _cytoscape_base_url()

    cb = state.get("progress_callback")
    if cb:
        cb(55, "Analyzing signaling networks")

    parsed_ptms = state.get("parsed_ptms", [])
    enriched_data = state.get("enriched_ptm_data", [])
    output_dir = state.get("output_dir", "/tmp")

    # GAP 1: Detect timepoints and perform per-timepoint analysis
    timepoints = _detect_timepoints(parsed_ptms)
    timepoint_results = {}

    if len(timepoints) > 1:
        logger.info(f"[NET-NODE] Detected {len(timepoints)} timepoints: {timepoints}")
        for tp in timepoints:
            tp_result = _analyze_timepoint(parsed_ptms, enriched_data, tp)
            timepoint_results[tp] = tp_result
            logger.info(
                f"[NET-NODE] Timepoint {tp}: "
                f"active={tp_result['stats']['active_ptm_count']}, "
                f"inhibited={tp_result['stats'].get('inhibited_ptm_count', 0)}, "
                f"non_ptm={tp_result['stats']['non_ptm_count']}, "
                f"edges={tp_result['stats']['active_edge_count']}"
            )
    else:
        logger.info("[NET-NODE] Single timepoint/condition — using combined network")

    # Build combined network data (for backward compatibility + main network image)
    network_data = _build_network_data(parsed_ptms, enriched_data)

    # GAP 4: Generate multi-type legends
    legends = _generate_legends(network_data, parsed_ptms, timepoint_results)

    # Attempt Cytoscape visualization
    network_images = {}
    cytoscape_connected = False

    if cb:
        cb(60, "Connecting to Cytoscape Desktop")

    if _check_cytoscape():
        cytoscape_connected = True
        logger.info("Cytoscape Desktop connected via host.docker.internal")
        if cb:
            cb(62, "Generating Cytoscape network images")
        # GAP 1: Generate per-timepoint networks if available
        network_images = _generate_cytoscape_networks(
            network_data, output_dir, parsed_ptms, timepoint_results
        )
    else:
        logger.info("Cytoscape not available — using text-based legends only")

    if cb:
        cb(65, f"Network analysis complete (Cytoscape: {cytoscape_connected})")

    # GAP 1/3: Build network_results with timepoint data for writer_node
    network_results = _build_network_results_for_writer(
        parsed_ptms, state.get("experimental_context", {}), timepoint_results
    )

    result = {
        "network_analysis": {
            "network_data": network_data,
            "legends": legends,
            "cytoscape_connected": cytoscape_connected,
            "network_images": network_images,
            "ptm_count": len(parsed_ptms),
            "timepoint_results": timepoint_results,
            "timepoints": timepoints,
        },
        "network_results": network_results,
    }

    logger.info(
        f"[NET-NODE] run_network_analysis returning: "
        f"cytoscape_connected={cytoscape_connected}, "
        f"timepoints={timepoints}, "
        f"network_images={list(network_images.keys()) if network_images else 'EMPTY'}, "
        f"network_results_keys={list(network_results.keys()) if network_results else 'EMPTY'}"
    )

    return result


# ---------------------------------------------------------------------------
# Cytoscape integration (Option A: host.docker.internal)
# ---------------------------------------------------------------------------

def _cytoscape_base_url() -> str:
    """Base URL for Cytoscape CyREST API (host.docker.internal from Docker)."""
    return f"http://{CYTOSCAPE_HOST}:{CYTOSCAPE_PORT}/v1"


def _check_cytoscape_http(base_url: str, timeout: int = 5) -> bool:
    """Simple HTTP connectivity check to CyREST base URL."""
    try:
        import requests
        r = requests.get(base_url, timeout=timeout)
        return r.status_code == 200
    except Exception as e:
        logger.debug(f"Cytoscape HTTP check failed: {e}")
        return False


def _check_cytoscape() -> bool:
    """Check if Cytoscape Desktop is accessible. Retries with fallback to HTTP check."""
    base_url = _cytoscape_base_url()
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            import py4cytoscape as p4c
            p4c.cytoscape_ping(base_url=base_url)
            return True
        except Exception as e:
            logger.warning(
                f"Cytoscape ping failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    # Fallback: if py4cytoscape ping fails, try simple HTTP
    if _check_cytoscape_http(base_url):
        logger.info("Cytoscape reachable via HTTP; py4cytoscape ping failed (may be version mismatch)")
        return True

    logger.info(
        f"Cytoscape not reachable at {base_url} — ensure Cytoscape Desktop is running with CyREST on port {CYTOSCAPE_PORT}"
    )
    return False


def _generate_cytoscape_networks(
    network_data: dict,
    output_dir: str,
    parsed_ptms: list = None,
    timepoint_results: dict = None,
) -> Dict[str, str]:
    """Generate Cytoscape network visualizations and export as PNG.
    
    GAP 1: Now creates per-timepoint networks when timepoint_results are available.
    Creates a main combined network + individual timepoint networks.
    """
    try:
        import py4cytoscape as p4c
        import pandas as pd
    except ImportError:
        logger.warning("py4cytoscape or pandas not installed")
        return {}

    nodes = network_data["nodes"]
    edges = network_data["edges"]

    if not nodes:
        return {}

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    network_images = {}

    try:
        # --- Main combined network ---
        nodes_df = pd.DataFrame(nodes)
        edges_df = pd.DataFrame(edges) if edges else None

        network_name = "PTM_Signaling_Network"
        network_suid = p4c.create_network_from_data_frames(
            nodes=nodes_df,
            edges=edges_df,
            title=network_name,
            collection="PTM Analysis",
        )
        logger.info(f"Cytoscape network created: {network_name} (SUID: {network_suid})")

        _apply_visual_style(p4c, network_suid, network_name, nodes)
        time.sleep(1)

        png_path = _save_network_png(p4c, network_suid, network_name, str(output_path))
        if png_path:
            network_images["main"] = png_path
            logger.info(f"Main network image saved: {png_path}")

        # --- GAP 1: Per-timepoint networks ---
        if timepoint_results:
            for tp, tp_data in sorted(
                timepoint_results.items(), key=lambda x: _tp_to_minutes(x[0])
            ):
                tp_nodes = (
                    tp_data.get("active_ptm_nodes", []) +
                    tp_data.get("inhibited_ptm_nodes", []) +
                    tp_data.get("non_ptm_nodes", [])
                )
                tp_edges = tp_data.get("active_edges", [])

                if not tp_nodes:
                    continue

                tp_nodes_df = pd.DataFrame(tp_nodes)
                tp_edges_df = pd.DataFrame(tp_edges) if tp_edges else None

                safe_tp = tp.replace(" ", "_").replace("/", "_")
                tp_net_name = f"PTM_Network_{safe_tp}"
                try:
                    tp_suid = p4c.create_network_from_data_frames(
                        nodes=tp_nodes_df,
                        edges=tp_edges_df,
                        title=tp_net_name,
                        collection=f"PTM_Networks_Temporal",
                    )
                    _apply_visual_style(p4c, tp_suid, tp_net_name, tp_nodes)
                    time.sleep(1)
                    tp_png = _save_network_png(p4c, tp_suid, tp_net_name, str(output_path))
                    if tp_png:
                        network_images[tp] = tp_png
                        logger.info(f"Timepoint network image saved: {tp} -> {tp_png}")
                except Exception as e:
                    logger.warning(f"Failed to create timepoint network for {tp}: {e}")

        # --- Condition-specific sub-networks (fallback for non-timepoint data) ---
        elif parsed_ptms:
            conditions = set()
            for ptm in parsed_ptms:
                cond = ptm.get("condition") or ptm.get("Condition", "")
                if cond:
                    conditions.add(cond)

            if len(conditions) > 1:
                for cond in sorted(conditions):
                    cond_ptm_genes = {
                        ptm["gene"]
                        for ptm in parsed_ptms
                        if (ptm.get("condition") or ptm.get("Condition", "")) == cond
                    }
                    cond_nodes = [n for n in nodes if n["gene"] in cond_ptm_genes]
                    if not cond_nodes:
                        continue

                    cond_node_ids = {n["id"] for n in cond_nodes}
                    cond_edges = [
                        e for e in edges
                        if e["source"] in cond_node_ids and e["target"] in cond_node_ids
                    ]

                    cond_nodes_df = pd.DataFrame(cond_nodes)
                    cond_edges_df = pd.DataFrame(cond_edges) if cond_edges else None

                    safe_cond = cond.replace(" ", "_").replace("/", "_")
                    cond_net_name = f"PTM_Network_{safe_cond}"
                    try:
                        cond_suid = p4c.create_network_from_data_frames(
                            nodes=cond_nodes_df,
                            edges=cond_edges_df,
                            title=cond_net_name,
                            collection=f"PTM_Networks_{safe_cond}",
                        )
                        _apply_visual_style(p4c, cond_suid, cond_net_name, cond_nodes)
                        time.sleep(1)
                        cond_png = _save_network_png(p4c, cond_suid, cond_net_name, str(output_path))
                        if cond_png:
                            network_images[cond] = cond_png
                            logger.info(f"Condition network image saved: {cond} -> {cond_png}")
                    except Exception as e:
                        logger.warning(f"Failed to create condition network for {cond}: {e}")

    except Exception as e:
        logger.error(f"Cytoscape network generation failed: {e}")

    logger.info(
        f"[CYTO-GEN] _generate_cytoscape_networks returning: "
        f"network_images={dict(network_images) if network_images else 'EMPTY'}"
    )
    return network_images


def _apply_visual_style(p4c, network_suid: int, network_name: str, nodes: list):
    """Apply publication-quality visual style to Cytoscape network.
    
    GAP 6: Colors aligned with guide §4.3 and §7.2.
    - Node colors by activation state (guide palette)
    - Node shapes by type (PTM=Circle, Non-PTM=Diamond)
    - Node size scaled by |Log2FC| magnitude
    - Edge colors by evidence type (guide palette)
    """
    try:
        style_name = f"PTM_Pub_Style_{network_name}"
        existing = p4c.get_visual_style_names()

        if style_name not in existing:
            p4c.create_visual_style(style_name)

        # ========== NODE STYLING ==========

        # GAP 6: Node color aligned with guide §4.3 / §7.2
        p4c.set_node_color_mapping(
            table_column="state",
            table_column_values=list(NODE_COLORS.keys()),
            colors=list(NODE_COLORS.values()),
            mapping_type="d",
            style_name=style_name,
        )

        # Node shape (guide §4.3)
        p4c.set_node_shape_mapping(
            table_column="type",
            table_column_values=list(NODE_SHAPES.keys()),
            shapes=list(NODE_SHAPES.values()),
            style_name=style_name,
        )

        # Node size (guide §4.3 — 30~100px range)
        p4c.set_node_size_mapping(
            table_column="value",
            table_column_values=[-5, 0, 5, 15],
            sizes=[30, 40, 60, 100],
            mapping_type="c",
            style_name=style_name,
        )

        # Node label
        p4c.set_node_label_mapping(table_column="label", style_name=style_name)
        p4c.set_node_font_size_default(11, style_name=style_name)

        try:
            p4c.set_node_font_face_default("Arial Bold,plain,14", style_name=style_name)
        except Exception:
            pass

        try:
            p4c.set_node_label_color_default("#000000", style_name=style_name)
        except Exception:
            pass

        # Node border
        p4c.set_node_border_width_default(2.0, style_name=style_name)
        p4c.set_node_border_color_default("#333333", style_name=style_name)

        try:
            p4c.set_node_fill_opacity_default(230, style_name=style_name)
        except Exception:
            pass

        # ========== EDGE STYLING ==========

        # GAP 6: Edge colors aligned with guide §4.3
        p4c.set_edge_color_mapping(
            table_column="evidence_type",
            table_column_values=list(EDGE_COLORS.keys()),
            colors=list(EDGE_COLORS.values()),
            mapping_type="d",
            style_name=style_name,
        )

        # Edge width based on confidence
        try:
            p4c.set_edge_line_width_mapping(
                table_column="confidence",
                table_column_values=[0.3, 0.5, 0.7, 1.0],
                widths=[1.5, 2.5, 3.5, 5.0],
                mapping_type="c",
                style_name=style_name,
            )
        except Exception:
            p4c.set_edge_line_width_default(2.5, style_name=style_name)

        # Kinase-substrate edge line style — dashed
        try:
            p4c.set_edge_line_style_mapping(
                table_column="evidence_type",
                table_column_values=["KEA3", "Kinase-Substrate", "Kinase-Substrate-Predicted"],
                line_styles=["LONG_DASH", "LONG_DASH", "DOT"],
                mapping_type="d",
                style_name=style_name,
            )
        except Exception:
            pass

        # Edge opacity
        try:
            p4c.set_edge_opacity_default(200, style_name=style_name)
        except Exception:
            pass

        # Apply style
        p4c.set_visual_style(style_name, network=network_suid)

        # ========== LAYOUT ==========
        _apply_optimized_layout(p4c, network_suid, nodes)

        logger.info(f"Publication-quality visual style applied: {style_name}")

    except Exception as e:
        logger.warning(f"Visual style application failed: {e}")
        try:
            p4c.set_visual_style("default", network=network_suid)
            p4c.layout_network("force-directed", network=network_suid)
        except Exception:
            pass


def _apply_optimized_layout(p4c, network_suid: int, nodes: list):
    """Apply optimized layout based on network size (guide §4.3).
    
    Force-directed layout with overlap removal.
    """
    try:
        node_count = len(nodes)
        edge_count = len(p4c.get_all_edges(network=network_suid))

        logger.info(f"Applying layout for {node_count} nodes, {edge_count} edges")

        if edge_count == 0:
            p4c.layout_network("circular", network=network_suid)
        elif node_count <= 20 and edge_count >= node_count:
            try:
                p4c.layout_network("kamada-kawai", network=network_suid)
            except Exception:
                p4c.layout_network("force-directed", network=network_suid)
        else:
            try:
                p4c.set_layout_properties(
                    layout_name="force-directed",
                    properties={
                        "defaultSpringCoefficient": 0.000005,
                        "defaultSpringLength": 400,
                        "defaultNodeMass": 15,
                        "numIterations": 800,
                        "defaultRepulsion": 50000,
                    }
                )
            except Exception:
                try:
                    p4c.set_layout_properties(
                        layout_name="force-directed",
                        properties={
                            "springCoefficient": 0.000005,
                            "springLength": 400,
                            "nodeMass": 15,
                            "iterations": 800,
                        }
                    )
                except Exception:
                    pass

            p4c.layout_network("force-directed", network=network_suid)

        # Wait for layout to settle
        time.sleep(2.5)

        # Apply layout multiple times for better convergence
        for _ in range(4):
            try:
                if edge_count > 0:
                    p4c.layout_network("force-directed", network=network_suid)
                    time.sleep(1.0)
            except Exception:
                break

        # Try overlap removal
        try:
            p4c.layout_network("force-directed-cl", network=network_suid)
            time.sleep(1.0)
        except Exception:
            pass

        # Fit content
        p4c.fit_content(network=network_suid)

    except Exception as e:
        logger.warning(f"Layout optimization failed, using basic layout: {e}")
        try:
            p4c.layout_network("force-directed", network=network_suid)
        except Exception:
            try:
                p4c.layout_network("grid", network=network_suid)
            except Exception:
                pass

    time.sleep(1.0)
    try:
        p4c.fit_content(network=network_suid)
    except Exception:
        pass


def _save_network_png(p4c, network_suid: int, network_name: str, output_dir: str) -> Optional[str]:
    """Export network as high-resolution PNG.

    Uses CyREST direct image download to avoid Docker/host path mismatch.
    Tries multiple CyREST API endpoint formats for compatibility.
    Falls back to export_image if direct download fails.
    """
    try:
        import requests as _requests

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        png_file = output_path / f"{network_name}.png"

        logger.info(
            f"[IMG-SAVE] Starting PNG export: network_suid={network_suid}, "
            f"name={network_name}, output_dir={output_dir}, target={png_file}"
        )

        # Delete existing file
        if png_file.exists():
            try:
                png_file.unlink()
                logger.info(f"[IMG-SAVE] Deleted existing file: {png_file}")
            except Exception as del_err:
                logger.warning(f"[IMG-SAVE] Could not delete existing file: {del_err}")

        p4c.fit_content(network=network_suid)
        time.sleep(0.5)

        # --- Method 1: CyREST direct image download (Docker-safe) ---
        base_url = _cytoscape_base_url()
        logger.info(f"[IMG-SAVE] Method 1: CyREST direct download (base_url={base_url})")

        try:
            views_url = f"{base_url}/networks/{network_suid}/views"
            logger.info(f"[IMG-SAVE] Fetching views: GET {views_url}")
            views_resp = _requests.get(views_url, timeout=10)
            logger.info(f"[IMG-SAVE] Views response: status={views_resp.status_code}")

            if views_resp.status_code == 200:
                views = views_resp.json()
                view_suid = views[0] if views else None
                logger.info(f"[IMG-SAVE] Views list: {views}, using view_suid={view_suid}")
            else:
                view_suid = None
                logger.warning(f"[IMG-SAVE] Views request failed: {views_resp.text[:200]}")

            if view_suid is not None:
                image_urls = [
                    f"{base_url}/networks/{network_suid}/views/first.png?h=2400",
                    f"{base_url}/networks/{network_suid}/views/{view_suid}.png?h=2400",
                    f"{base_url}/networks/{network_suid}/views/{view_suid}/export/png?h=2400",
                ]

                for img_url in image_urls:
                    try:
                        logger.info(f"[IMG-SAVE] Trying: GET {img_url}")
                        img_resp = _requests.get(img_url, timeout=60)
                        content_type = img_resp.headers.get("Content-Type", "")
                        content_len = len(img_resp.content) if img_resp.content else 0
                        logger.info(
                            f"[IMG-SAVE] Response: status={img_resp.status_code}, "
                            f"content_type={content_type}, size={content_len:,} bytes"
                        )

                        if img_resp.status_code == 200 and content_len > 1000:
                            is_png = img_resp.content[:4] == b'\x89PNG'
                            logger.info(f"[IMG-SAVE] PNG magic bytes check: {is_png}")

                            with open(png_file, "wb") as f:
                                f.write(img_resp.content)
                            logger.info(
                                f"[IMG-SAVE] SUCCESS via CyREST direct: {png_file} "
                                f"({content_len:,} bytes, url={img_url})"
                            )
                            return str(png_file)
                        else:
                            logger.warning(
                                f"[IMG-SAVE] Endpoint returned status={img_resp.status_code}, "
                                f"size={content_len} — trying next"
                            )
                    except Exception as url_err:
                        logger.warning(f"[IMG-SAVE] Endpoint failed: {img_url} — {url_err}")
                        continue

                logger.warning(f"[IMG-SAVE] All CyREST image endpoints failed")
            else:
                logger.warning(f"[IMG-SAVE] No view SUID available, skipping CyREST direct")

        except Exception as direct_err:
            logger.warning(f"[IMG-SAVE] CyREST direct download failed: {direct_err}")

        # --- Method 2: Fallback to export_image with host path mapping ---
        host_data_dir = os.getenv("HOST_DATA_DIR", "")
        logger.info(f"[IMG-SAVE] Method 2: Host path mapping (HOST_DATA_DIR={host_data_dir!r})")
        if host_data_dir:
            order_dir_name = Path(output_dir).name
            host_png = Path(host_data_dir) / "outputs" / order_dir_name / f"{network_name}.png"
            host_png.parent.mkdir(parents=True, exist_ok=True)
            try:
                logger.info(f"[IMG-SAVE] export_image to host path: {host_png}")
                p4c.export_image(
                    filename=str(host_png),
                    type="PNG",
                    resolution=300,
                    network=network_suid,
                    overwrite_file=True,
                )
                time.sleep(1.5)
                exists = png_file.exists()
                size = png_file.stat().st_size if exists else 0
                logger.info(f"[IMG-SAVE] After host export: exists={exists}, size={size}")
                if exists and size > 1000:
                    logger.info(f"[IMG-SAVE] SUCCESS via host path mapping: {png_file}")
                    return str(png_file)
            except Exception as host_err:
                logger.warning(f"[IMG-SAVE] Host path export failed: {host_err}")
        else:
            logger.info(f"[IMG-SAVE] HOST_DATA_DIR not set, skipping Method 2")

        # --- Method 3: Last resort - try original export_image ---
        logger.info(f"[IMG-SAVE] Method 3: Direct export_image to {png_file}")
        try:
            p4c.export_image(
                filename=str(png_file),
                type="PNG",
                resolution=300,
                network=network_suid,
                overwrite_file=True,
            )
            time.sleep(1.5)
            exists = png_file.exists()
            size = png_file.stat().st_size if exists else 0
            logger.info(f"[IMG-SAVE] After direct export: exists={exists}, size={size}")
            if exists and size > 1000:
                logger.info(f"[IMG-SAVE] SUCCESS via export_image: {png_file}")
                return str(png_file)
        except Exception as fallback_err:
            logger.warning(f"[IMG-SAVE] export_image fallback failed: {fallback_err}")

        logger.error(f"[IMG-SAVE] ALL METHODS FAILED for {network_name}")
        return None

    except Exception as e:
        logger.error(f"[IMG-SAVE] PNG export failed with exception: {e}")
        return None


# ---------------------------------------------------------------------------
# Base64 image embedding for Markdown reports
# ---------------------------------------------------------------------------

def image_to_base64(image_path: str) -> Optional[str]:
    """Convert image file to base64 data URI for Markdown embedding."""
    try:
        path = Path(image_path)
        if not path.exists():
            return None
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        ext = path.suffix.lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext.lstrip("."), "image/png")
        return f"data:{mime};base64,{data}"
    except Exception as e:
        logger.warning(f"Base64 conversion failed for {image_path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Network figure section for report (guide §6.1)
# ---------------------------------------------------------------------------

def generate_network_figure_section(network_analysis: dict) -> str:
    """Generate Markdown section with embedded network figures and legends.
    
    GAP 1/4: Now generates per-timepoint figure panels with individual legends.
    Creates Base64-embedded images in Markdown for each network image,
    with detailed figure legends including node/edge statistics.
    
    Guide §6.1: generate_network_figure_section()
    """
    network_images = network_analysis.get("network_images", {})
    legends = network_analysis.get("legends", {})
    network_data = network_analysis.get("network_data", {})
    timepoint_results = network_analysis.get("timepoint_results", {})
    individual_legends = legends.get("individual_legends", {})
    comparison_legend = legends.get("comparison_legend", "")

    logger.info(
        f"[NET-SECTION] generate_network_figure_section called: "
        f"network_images={list(network_images.keys()) if network_images else 'EMPTY'}, "
        f"legends_keys={list(legends.keys()) if legends else 'EMPTY'}, "
        f"has_full_legend={bool(legends.get('full_legend'))}, "
        f"timepoint_results={list(timepoint_results.keys()) if timepoint_results else 'EMPTY'}"
    )

    if not network_images and not legends.get("full_legend"):
        logger.warning("[NET-SECTION] No network_images and no full_legend — returning empty")
        return ""

    section = "## Network Visualization\n\n"

    nodes = network_data.get("nodes", [])
    edges = network_data.get("edges", [])

    ptm_nodes = [n for n in nodes if n.get("type") == "PTM"]
    non_ptm_nodes = [n for n in nodes if n.get("type") == "Non-PTM"]
    active_nodes = [n for n in ptm_nodes if n.get("state") in ("high_active", "moderate_active")]
    inhibited_nodes = [n for n in ptm_nodes if n.get("state") in ("inhibited", "low_inhibited")]

    figure_num = 1
    panel_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # Sort images: "main" first, then timepoints in order
    sorted_labels = []
    if "main" in network_images:
        sorted_labels.append("main")
    for label in sorted(
        [k for k in network_images.keys() if k != "main"],
        key=_tp_to_minutes
    ):
        sorted_labels.append(label)

    for idx, label in enumerate(sorted_labels):
        img_path = network_images[label]
        path_obj = Path(img_path) if img_path else None
        logger.info(
            f"[NET-SECTION] Processing image: label={label}, path={img_path}, "
            f"exists={path_obj.exists() if path_obj else False}, "
            f"size={path_obj.stat().st_size if path_obj and path_obj.exists() else 0}"
        )

        # Use relative filename for Markdown
        if path_obj and path_obj.exists() and path_obj.stat().st_size > 1000:
            img_ref = path_obj.name
            logger.info(f"[NET-SECTION] Using relative filename: {img_ref}")
        else:
            base64_img = image_to_base64(img_path) if img_path else None
            img_ref = base64_img
            logger.info(f"[NET-SECTION] Fallback to base64: {'OK' if img_ref else 'FAILED'}")

        # Figure title (guide §6.1)
        if label == "main":
            display_label = "Combined PTM Signaling Network"
            fig_title = f"Figure {figure_num}. {display_label}"
        else:
            phase = _tp_to_phase(label)
            panel = panel_labels[idx - 1] if idx > 0 and idx <= len(panel_labels) else str(idx)
            display_label = f"PTM-NonPTM Integrated Network at {label} ({phase})"
            fig_title = f"Figure {figure_num}{panel}. {display_label}"

        if img_ref:
            section += f"### {fig_title}\n\n"
            section += f"![{display_label}]({img_ref})\n\n"
        else:
            section += f"### {fig_title}\n\n"
            section += f"*[Network image: {path_obj.name if path_obj else '?'}]*\n\n"

        # Figure legend (guide §6.1)
        section += f"**Figure Legend ({label}):**\n\n"

        if label == "main":
            section += (
                f"This network represents the combined PTM signaling interactions. "
                f"The network contains **{len(active_nodes)} activated PTMs** (red/orange nodes), "
                f"**{len(inhibited_nodes)} inhibited PTMs** (blue nodes), "
                f"**{len(non_ptm_nodes)} Non-PTM proteins** (green diamond nodes), "
                f"and **{len(edges)} interaction edges**.\n\n"
            )
        elif label in individual_legends:
            section += individual_legends[label] + "\n\n"
        else:
            # Fallback for condition-based networks
            section += (
                f"This network represents the PTM signaling interactions at {label}. "
            )
            if label in timepoint_results:
                stats = timepoint_results[label].get("stats", {})
                section += (
                    f"The network contains **{stats.get('active_ptm_count', 0)} activated PTMs**, "
                    f"**{stats.get('inhibited_ptm_count', 0)} inhibited PTMs**, "
                    f"**{stats.get('non_ptm_count', 0)} Non-PTM proteins**, "
                    f"and **{stats.get('active_edge_count', 0)} active edges**.\n\n"
                )

        # Top activated PTMs for this panel
        if label in timepoint_results:
            tp_data = timepoint_results[label]
            top_active = sorted(
                tp_data.get("active_ptm_nodes", []),
                key=lambda x: -x.get("value", 0)
            )[:5]
            if top_active:
                top_str = "; ".join(
                    f"{n.get('gene', '?')}({n.get('site', '')}): Log2FC={n.get('value', 0):.2f}"
                    for n in top_active
                )
                section += f"**Top Activated PTMs**: {top_str}\n\n"

            top_inhib = sorted(
                tp_data.get("inhibited_ptm_nodes", []),
                key=lambda x: x.get("value", 0)
            )[:5]
            if top_inhib:
                top_str = "; ".join(
                    f"{n.get('gene', '?')}({n.get('site', '')}): Log2FC={n.get('value', 0):.2f}"
                    for n in top_inhib
                )
                section += f"**Top Inhibited PTMs**: {top_str}\n\n"
        elif label == "main":
            if active_nodes:
                top_active = sorted(active_nodes, key=lambda x: -x.get("value", 0))[:5]
                top_str = "; ".join(
                    f"{n.get('gene', '?')}({n.get('site', '')}): Log2FC={n.get('value', 0):.2f}"
                    for n in top_active
                )
                section += f"**Top Activated PTMs**: {top_str}\n\n"

            if inhibited_nodes:
                top_inhib = sorted(inhibited_nodes, key=lambda x: x.get("value", 0))[:5]
                top_str = "; ".join(
                    f"{n.get('gene', '?')}({n.get('site', '')}): Log2FC={n.get('value', 0):.2f}"
                    for n in top_inhib
                )
                section += f"**Top Inhibited PTMs**: {top_str}\n\n"

        # Edge type breakdown
        if label == "main":
            edge_types = defaultdict(int)
            for e in edges:
                edge_types[e.get("evidence_type", "Unknown")] += 1
            if edge_types:
                section += "**Edge Types**: " + ", ".join(
                    f"{et} ({cnt})" for et, cnt in sorted(edge_types.items(), key=lambda x: -x[1])
                ) + "\n\n"

        section += "---\n\n"
        figure_num += 1

    # Temporal comparison legend (guide §5.1 row 3)
    if comparison_legend:
        section += comparison_legend + "\n\n---\n\n"

    # If no images but legends exist, include text legend
    if not network_images and legends.get("full_legend"):
        full_legend = legends["full_legend"]
        full_legend = re.sub(r'^## ', '### ', full_legend, flags=re.MULTILINE)
        section += full_legend + "\n\n"

    return section
