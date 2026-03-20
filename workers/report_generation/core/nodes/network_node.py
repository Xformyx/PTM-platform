"""
Network Node — temporal PTM signaling network analysis + Cytoscape visualization.
Ported from multi_agent_system/agents/network_analyzer.py and ptm_network_automation.py.

v6.1 — Per-condition Signaling Cascade Diagrams:
  - When multiple timepoints/conditions exist, generate one cascade diagram per condition
  - Each condition gets its own Figure with condition-specific data filtering
  - Single-condition mode remains backward compatible (combined diagram)
  - cascade_diagram_paths dict added to network_analysis output

v6.0 — Add Signaling Cascade Diagram (Figure 2):
  - New: generate_signaling_cascade_diagram() in signaling_cascade.py
  - Draws cell cross-section with compartments: Extracellular → Membrane → Cytoplasm → Nucleus
  - Proteins placed by UniProt subcellular_location + GO Cellular Component + heuristic fallback
  - Color-coded by activation state (PTM Red/Blue, Non-PTM Green/Purple, Kinase Orange)
  - Signal flow arrows connect proteins in canonical pathway progression order
  - Focuses on top 5 pathways from Figure 1 (highest cumulative |Log2FC| scores)
  - Inserted as Figure 2 in generate_network_figure_section (between pathway graph and Cytoscape)

v5.6 — Cumulative Weighted Score for Pathway Distribution (Figure 1):
  - X-axis changed from 'Number of Proteins' to 'Cumulative |Log2FC| Score' (Σ|Protein_Log2FC|)
  - Each protein weighted by its |Protein_Log2FC| magnitude instead of equal count
  - Bar labels show 'score (n=count)' for both PTM and Non-PTM groups
  - Pathways ranked by total cumulative score (strongest expression changes at top)
  - Step 5.5 added: gene_fc_weight lookup from unified TSV + parsed_ptms
v5.5 — Load Non-PTM Protein_Log2FC from unified_protein_data_enriched TSV:
  - Added _load_unified_protein_fc() helper to read ALL protein FC from preprocessing TSV
  - _analyze_timepoint and _build_network_data now accept output_dir parameter
  - Non-PTM nodes get real Protein_Log2FC values → Green/Purple gradient instead of gray
v5.4 — Add try-except safety net to run_network_analysis to prevent pipeline failure:
  - Root cause: parsed_ptms uses 'ptm_relative_log2fc' not 'log2fc' or 'Log2FC'
  - Step 1 now reads correct field names from both parsed_ptms and enriched_data
  - Also checks condition_data for multi-timepoint Log2FC values
  - Added Step 1 logging to track activated PTM gene count
v5.2 — Pathway distribution Non-PTM fix:
  - Fixed: Non-PTM proteins were excluded because they lack Protein_Log2FC data
  - Now includes ALL connected Non-PTM proteins (they are biologically relevant by interaction)
  - Three-method pathway assignment: KEGG edges, activated PTM inheritance, all PTM inheritance
  - Comprehensive logging for debugging pathway assignment counts
v5.1 — Pathway distribution fix + Activated-only filter:
  - Non-PTM proteins now get pathway assignments via KEGG edges + PTM partner inheritance
  - Only activated proteins (Log2FC > 0) included in pathway distribution graph
  - network_data passed to _generate_pathway_distribution_graph for edge-based mapping
v5.0 — Color mapping fix + Kinase expansion:
  - Non-PTM nodes: Green/Purple/Gray gradient based on actual Protein_Log2FC (was hardcoded 0)
  - PTM nodes: Red (up) / Blue (down) gradient with intensity
  - Kinase nodes: Amber gradient, expanded sources (KEA3 + kinase_prediction + kinase_substrate)
  - gene_protein_fc lookup dictionary built from enriched_data + parsed_ptms
  - Updated legends to reflect full color gradient detail

v3.0 — Cytoscape visualization fix (5 phases):
  Phase 1: Edge generation rebuilt — PTM→Non-PTM edges, Kinase edges, Non-PTM limit removed
  Phase 2: Visual style — edge type styles, node size 40-120px, label outside, arrow heads
  Phase 3: Layout optimization — reduced iterations, kamada-kawai threshold raised
  Phase 4: Isolated node separation + auto-crop
  Phase 5: Network integrity validation + SIF export

Previous versions:
  v2.0: GAP 1-6 alignment with cytoscape_network_pipeline_guide.md
  v1.0: Initial port from multi_agent_system

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
# Color palette v4.0 — User-requested color scheme
#   PTM protein: Red gradient (intensity = |Log2FC|)
#   Non-PTM protein: Green (up) / Purple (down) / Gray (unchanged)
#   Kinase/Upstream regulator: Gold/Orange (distinct from both)
# ---------------------------------------------------------------------------

NODE_COLORS = {
    # --- PTM protein states: UP = Red gradient, DOWN = Blue gradient ---
    "high_active": "#B71C1C",       # Dark Red — PTM Log2FC > 2.0 (strong increase)
    "moderate_active": "#E53935",   # Red — PTM 1.0 < Log2FC <= 2.0
    "low_active": "#EF9A9A",        # Light Red — PTM 0 < Log2FC <= 1.0
    "neutral": "#BDBDBD",           # Gray — PTM Log2FC ≈ 0
    "low_inhibited": "#90CAF9",     # Light Blue — PTM -1.0 <= Log2FC < 0
    "inhibited": "#1E88E5",         # Blue — PTM -2.0 <= Log2FC < -1.0
    "high_inhibited": "#0D47A1",    # Dark Blue — PTM Log2FC < -2.0
    # --- Non-PTM protein states: UP = Green gradient, DOWN = Purple gradient ---
    "nonptm_up_strong": "#1B5E20",  # Dark Green — Non-PTM Log2FC > 1.5
    "nonptm_up": "#43A047",         # Green — Non-PTM 0.5 < Log2FC <= 1.5
    "nonptm_up_weak": "#A5D6A7",    # Light Green — Non-PTM 0 < Log2FC <= 0.5
    "nonptm_neutral": "#9E9E9E",    # Gray — Non-PTM Log2FC ≈ 0
    "nonptm_down_weak": "#CE93D8",  # Light Purple — Non-PTM -0.5 <= Log2FC < 0
    "nonptm_down": "#8E24AA",       # Purple — Non-PTM -1.5 <= Log2FC < -0.5
    "nonptm_down_strong": "#4A148C",# Dark Purple — Non-PTM Log2FC < -1.5
    # --- Kinase / Upstream regulator ---
    "kinase": "#FF8F00",            # Amber — Kinase/upstream regulator
    "kinase_up": "#E65100",         # Deep Orange — Kinase with increased activity
    "kinase_down": "#FFB74D",       # Light Orange — Kinase with decreased activity
    # --- Legacy / fallback ---
    "non_ptm": "#9E9E9E",           # Gray — fallback for Non-PTM without FC data
    "missing": "#E0E0E0",           # Light Gray — missing data
}

EDGE_COLORS = {
    "STRING": "#808080",            # Gray — STRING-DB PPI
    "STRING-DB": "#808080",         # Alias
    "KEGG": "#228B22",              # Forest Green — KEGG pathway
    "KEA3": "#FF4500",              # Orange-Red — Kinase-substrate
    "Shared Pathway": "#228B22",    # Same as KEGG
    "Shared-Partner": "#8B008B",    # Purple — Shared interactor
    "Shared-Regulator": "#FF6F00",  # Amber — Shared upstream regulator (v4.0 NEW)
    "Kinase-Substrate": "#FF4500",  # Same as KEA3
    "BioGRID": "#1E90FF",           # Dodger Blue — BioGRID experimental PPI
    "Kinase-Substrate-Predicted": "#D8BFD8",  # Light purple
    "Literature": "#E377C2",        # Pink
    "Co-activation": "#7F7F7F",     # Gray
    "Predicted": "#BCBD22",         # Yellow-green
    "Unknown": "#C7C7C7",          # Light gray
    "default": "#95A5A6",          # Default gray
}

# Node shape mapping v4.0
#   Proteins (PTM + Non-PTM) = Circle (ELLIPSE)
#   Kinase / Upstream regulator = Diamond (DIAMOND)
NODE_SHAPES = {
    "PTM": "ELLIPSE",              # Circle for PTM proteins
    "Non-PTM": "ELLIPSE",          # Circle for Non-PTM proteins (v4.0: was DIAMOND)
    "Kinase": "DIAMOND",           # Diamond for kinases / upstream regulators
    "Interactor": "ELLIPSE",       # Circle for interactors (v4.0: was ROUND_RECTANGLE)
    "Pathway-Member": "ELLIPSE",   # Circle (v4.0: was HEXAGON)
}


# ---------------------------------------------------------------------------
# Activation state classifier aligned with guide §7.1
# ---------------------------------------------------------------------------

def _classify_state(value: float, node_type: str = "PTM") -> str:
    """Classify node state based on Log2FC value and node type.
    
    v5.0: Separate color schemes for PTM, Non-PTM, and Kinase nodes.
    - PTM: Red gradient (up) / Blue gradient (down) — intensity = |Log2FC|
    - Non-PTM: Green gradient (up) / Purple gradient (down) / Gray (unchanged)
    - Kinase: Amber gradient
    """
    try:
        value = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return "missing"
    
    if node_type == "Kinase":
        if value > 0.5:
            return "kinase_up"
        elif value < -0.5:
            return "kinase_down"
        return "kinase"
    
    if node_type == "Non-PTM":
        if value > 1.5:
            return "nonptm_up_strong"
        elif value > 0.5:
            return "nonptm_up"
        elif value > 0.1:
            return "nonptm_up_weak"
        elif value < -1.5:
            return "nonptm_down_strong"
        elif value < -0.5:
            return "nonptm_down"
        elif value < -0.1:
            return "nonptm_down_weak"
        return "nonptm_neutral"
    
    # PTM protein — UP = Red gradient, DOWN = Blue gradient
    if value > 2.0:
        return "high_active"       # Dark Red — strong upregulation
    elif value > 1.0:
        return "moderate_active"   # Red — moderate upregulation
    elif value > 0.0:
        return "low_active"        # Light Red — weak upregulation
    elif value < -2.0:
        return "high_inhibited"    # Dark Blue — strong downregulation
    elif value < -1.0:
        return "inhibited"         # Blue — moderate downregulation
    elif value < 0.0:
        return "low_inhibited"     # Light Blue — weak downregulation
    return "neutral"               # Gray — no change


def _classify_state_legacy(value: float) -> str:
    """Legacy classifier for backward compatibility."""
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
# Phase 5: Network integrity validation
# ---------------------------------------------------------------------------

def _validate_network(nodes: list, edges: list) -> dict:
    """Validate network integrity before Cytoscape rendering.
    
    Checks:
    - All edge source/target IDs exist in node list
    - Orphan nodes (no edges)
    - Edge type distribution
    """
    node_ids = {n["id"] for n in nodes}
    edge_node_ids = set()
    for e in edges:
        edge_node_ids.add(e["source"])
        edge_node_ids.add(e["target"])

    missing_nodes = edge_node_ids - node_ids
    orphan_nodes = node_ids - edge_node_ids

    edge_types = defaultdict(int)
    for e in edges:
        edge_types[e.get("evidence_type", "Unknown")] += 1

    result = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "ptm_nodes": len([n for n in nodes if n.get("type") == "PTM"]),
        "non_ptm_nodes": len([n for n in nodes if n.get("type") == "Non-PTM"]),
        "connected_nodes": len(edge_node_ids & node_ids),
        "orphan_nodes": len(orphan_nodes),
        "orphan_node_ids": sorted(list(orphan_nodes))[:20],
        "missing_nodes": len(missing_nodes),
        "missing_node_ids": sorted(list(missing_nodes))[:20],
        "edge_types": dict(edge_types),
        "is_valid": len(missing_nodes) == 0,
    }

    logger.info(
        f"[NET-VALIDATE] nodes={result['total_nodes']} "
        f"(PTM={result['ptm_nodes']}, Non-PTM={result['non_ptm_nodes']}), "
        f"edges={result['total_edges']}, "
        f"connected={result['connected_nodes']}, orphan={result['orphan_nodes']}, "
        f"missing={result['missing_nodes']}, "
        f"edge_types={dict(edge_types)}, valid={result['is_valid']}"
    )

    if missing_nodes:
        logger.warning(
            f"[NET-VALIDATE] Missing node IDs (edges reference non-existent nodes): "
            f"{sorted(list(missing_nodes))[:10]}"
        )

    return result


# ---------------------------------------------------------------------------
# Phase 4: Isolated node separation
# ---------------------------------------------------------------------------

def _separate_isolated_nodes(
    nodes: list, edges: list
) -> Tuple[list, list]:
    """Separate truly isolated nodes (no edges) from connected nodes.
    
    Returns:
        (connected_nodes, isolated_nodes)
    """
    connected_ids = set()
    for e in edges:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])

    connected = [n for n in nodes if n["id"] in connected_ids]
    isolated = [n for n in nodes if n["id"] not in connected_ids]

    if isolated:
        logger.info(
            f"[NET-ISOLATE] Separated {len(isolated)} isolated nodes from "
            f"{len(connected)} connected nodes"
        )

    return connected, isolated


# ---------------------------------------------------------------------------
# Phase 5: SIF export for debugging
# ---------------------------------------------------------------------------

def _export_sif(edges: list, isolated_node_ids: list, output_path: str) -> Optional[str]:
    """Export network edges as SIF file for verification and debugging.
    
    SIF format: source_id\tinteraction_type\ttarget_id
    Isolated nodes: node_id (single column)
    """
    try:
        sif_path = Path(output_path) / "network.sif"
        with open(sif_path, "w") as f:
            for e in edges:
                f.write(f"{e['source']}\t{e.get('evidence_type', 'pp')}\t{e['target']}\n")
            for node_id in isolated_node_ids:
                f.write(f"{node_id}\n")
        logger.info(f"[SIF-EXPORT] Exported {len(edges)} edges + {len(isolated_node_ids)} isolated to {sif_path}")
        return str(sif_path)
    except Exception as e:
        logger.warning(f"[SIF-EXPORT] Failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Helper: Load ALL protein FC from unified_protein_data_enriched TSV
# ---------------------------------------------------------------------------
def _load_unified_protein_fc(output_dir: str, condition: str = "") -> Dict[str, float]:
    """Load Protein_Log2FC for ALL proteins (PTM + Non-PTM) from unified TSV.
    
    Returns dict: gene_upper -> Protein_Log2FC (float).
    If condition is specified, only rows matching that condition are used.
    If condition is empty, uses the max absolute FC across all conditions.
    """
    import csv
    result: Dict[str, float] = {}
    output_path = Path(output_dir)
    # Find the unified TSV file (try multiple naming patterns)
    tsv_candidates = (
        list(output_path.glob("unified_protein_data_enriched_bio_enriched*.tsv"))
        + list(output_path.glob("unified_protein_data_enriched*.tsv"))
    )
    if not tsv_candidates:
        logger.warning(f"[NET-NODE] No unified_protein_data TSV found in {output_dir}")
        return result
    tsv_path = tsv_candidates[0]
    logger.info(f"[NET-NODE] Loading unified protein FC from {tsv_path.name}")
    try:
        with open(tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                gene = (row.get("Gene.Name") or row.get("Gene_Name") or "").strip().upper()
                if not gene:
                    continue
                cond = (row.get("Condition") or "").strip()
                if condition and cond != condition:
                    continue
                pfc_raw = row.get("Protein_Log2FC") or row.get("Log2FC") or "0"
                try:
                    pfc = float(pfc_raw) if pfc_raw and pfc_raw.lower() not in ("na", "nan", "") else 0.0
                except (TypeError, ValueError):
                    pfc = 0.0
                # Keep the largest absolute value per gene
                if gene not in result or abs(pfc) > abs(result[gene]):
                    result[gene] = pfc
        logger.info(f"[NET-NODE] Loaded unified protein FC for {len(result)} genes (condition={condition or 'all'})")
    except Exception as e:
        logger.error(f"[NET-NODE] Failed to load unified protein FC: {e}", exc_info=True)
    return result


# ---------------------------------------------------------------------------
# Phase 1: Time-point based network analysis (REBUILT edge generation)
# ---------------------------------------------------------------------------

def _analyze_timepoint(
    parsed_ptms: list,
    enriched_data: list,
    timepoint: str,
    threshold: float = 0.0,
    output_dir: str = "",
) -> dict:
    """Analyze network for a single timepoint/condition.
    
    Phase 1 REBUILT: Edge generation now includes PTM→Non-PTM connections.
    
    1. Collect activated PTM nodes (Log2FC > threshold)
    2. Build edges: STRING (PTM↔PTM + PTM↔Non-PTM), KEGG, KEA3 (Kinase→Substrate)
    3. Collect Non-PTM proteins from enrichment data
    4. Only include Non-PTM nodes that have edges (Phase 1-C)
    5. Aggregate pathway information
    """
    # Filter PTMs for this timepoint
    tp_ptms = [p for p in parsed_ptms
               if (p.get("condition") or p.get("Condition", "")).strip() == timepoint]

    if not tp_ptms:
        return {
            "timepoint": timepoint,
            "active_ptm_nodes": [],
            "inhibited_ptm_nodes": [],
            "non_ptm_nodes": [],
            "active_edges": [],
            "all_edges": [],
            "pathway_summary": {},
            "stats": {
                "active_ptm_count": 0,
                "inhibited_ptm_count": 0,
                "non_ptm_count": 0,
                "active_edge_count": 0,
                "total_edge_count": 0,
            },
        }

    # v5.0: Build gene -> Protein_Log2FC lookup from ALL parsed_ptms for this timepoint
    # This allows Non-PTM nodes (STRING/BioGRID partners) to inherit protein-level FC
    # when the partner gene happens to also be in the dataset (even if not a PTM site)
    gene_protein_fc = {}  # gene_upper -> float (Protein_Log2FC)
    for ptm in tp_ptms:
        g = (ptm.get("gene") or "").strip().upper()
        pfc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
        try:
            pfc = float(pfc) if pfc is not None else 0.0
        except (TypeError, ValueError):
            pfc = 0.0
        if g and (g not in gene_protein_fc or abs(pfc) > abs(gene_protein_fc[g])):
            gene_protein_fc[g] = pfc

    # Also build lookup from enriched_data (covers all conditions)
    for ed in enriched_data:
        g = (ed.get("gene") or ed.get("Gene.Name", "")).strip().upper()
        cond = (ed.get("Condition") or ed.get("condition", "")).strip()
        if cond != timepoint or not g:
            continue
        pfc = ed.get("protein_log2fc") or ed.get("Protein_Log2FC", 0)
        try:
            pfc = float(pfc) if pfc is not None else 0.0
        except (TypeError, ValueError):
            pfc = 0.0
        if g not in gene_protein_fc or abs(pfc) > abs(gene_protein_fc[g]):
            gene_protein_fc[g] = pfc

    # v5.5: Load ALL protein FC from unified TSV (covers Non-PTM proteins)
    if output_dir:
        unified_fc = _load_unified_protein_fc(output_dir, condition=timepoint)
        # Merge: unified_fc fills in genes NOT already in gene_protein_fc
        # (PTM genes from parsed_ptms take priority)
        merged_count = 0
        for g, pfc in unified_fc.items():
            if g not in gene_protein_fc:
                gene_protein_fc[g] = pfc
                merged_count += 1
        logger.info(f"[NET-NODE] Merged {merged_count} Non-PTM protein FC values from unified TSV for timepoint {timepoint}")

    # 1. Collect PTM nodes
    active_ptm_nodes = []
    inhibited_ptm_nodes = []
    all_ptm_nodes = []
    gene_ptms = defaultdict(list)  # gene -> [node_id, ...]
    ptm_genes = set()  # uppercase gene names
    _kinase_substrates_tp = {}  # v4.0: kinase_name -> [substrate_ids] for Shared-Regulator edges

    for ptm in tp_ptms:
        fc = ptm.get("ptm_relative_log2fc", 0)
        state = _classify_state(fc, "PTM")
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

    # 2. Build edges from enrichment data (PHASE 1 REBUILT)
    all_edges = []
    active_edges = []
    active_node_ids = {n["id"] for n in active_ptm_nodes + inhibited_ptm_nodes}

    # Candidate Non-PTM nodes (will be filtered to only those with edges)
    candidate_non_ptm = {}  # id -> node dict
    seen_non_ptm_upper = set()

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

        # --- STRING-DB interactions (PHASE 1-A: PTM→Non-PTM edges added) ---
        # v101: Prefer string_db.interactions (dict with score), fallback to string_interactions
        string_interactions = enr.get("string_db", {}).get("interactions", []) or enr.get("string_interactions", [])
        for interaction in string_interactions:  # v101: no limit — use all available
            if isinstance(interaction, dict):
                partner = interaction.get("partner", "")
                confidence = interaction.get("score", 0.7)
            elif isinstance(interaction, str):
                # Legacy string format: "MAPK1(0.95)" — parse score
                if "(" in interaction:
                    parts = interaction.rsplit("(", 1)
                    partner = parts[0].strip()
                    try:
                        confidence = float(parts[1].rstrip(")"))
                    except (ValueError, IndexError):
                        confidence = 0.7
                else:
                    partner = interaction.strip()
                    confidence = 0.7
            else:
                continue

            partner_clean = partner.strip()
            partner_upper = partner_clean.upper()
            if not partner_clean:
                continue

            if partner_clean in gene_ptms:
                # PTM-to-PTM edge (existing behavior)
                for target_id in gene_ptms[partner_clean]:
                    edge = {
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "STRING",
                        "confidence": confidence,
                        "pathways": [],
                        "pathway_str": "",
                    }
                    all_edges.append(edge)
                    if source_id in active_node_ids and target_id in active_node_ids:
                        edge_copy = dict(edge)
                        edge_copy["is_active_edge"] = True
                        active_edges.append(edge_copy)
            elif partner_upper not in ptm_genes:
                # PTM → Non-PTM edge (PHASE 1-A NEW)
                edge = {
                    "source": source_id,
                    "target": partner_clean,
                    "evidence_type": "STRING",
                    "confidence": confidence,
                    "pathways": [],
                    "pathway_str": "",
                }
                all_edges.append(edge)
                # Register candidate Non-PTM node
                if partner_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(partner_upper)
                    _pfc = gene_protein_fc.get(partner_upper, 0.0)
                    candidate_non_ptm[partner_clean] = {
                        "id": partner_clean,
                        "gene": partner_clean,
                        "site": "",
                        "type": "Non-PTM",
                        "value": round(_pfc, 3),
                        "state": _classify_state(_pfc, "Non-PTM"),
                        "identified": True,
                        "label": partner_clean,
                        "source": "STRING",
                    }


        # --- BioGRID interactions (v101: NEW — experimental PPI evidence) ---
        biogrid_data = enr.get("biogrid", {})
        biogrid_interactions = biogrid_data.get("interactions", []) if isinstance(biogrid_data, dict) else []
        for bg_int in biogrid_interactions:
            if not isinstance(bg_int, dict):
                continue
            # Determine the interaction partner (the other gene)
            int_a = bg_int.get("interactor_a", "").strip()
            int_b = bg_int.get("interactor_b", "").strip()
            if int_a.upper() == gene.upper():
                partner_clean = int_b
            elif int_b.upper() == gene.upper():
                partner_clean = int_a
            else:
                continue
            partner_upper = partner_clean.upper()
            if not partner_clean or partner_upper == gene.upper():
                continue

            # BioGRID confidence: experimental > high-throughput
            throughput = bg_int.get("throughput", "")
            confidence = 0.85 if "Low" in throughput else 0.65

            if partner_clean in gene_ptms:
                # BioGRID PTM-to-PTM edge
                for target_id in gene_ptms[partner_clean]:
                    edge = {
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "BioGRID",
                        "confidence": confidence,
                        "pathways": [],
                        "pathway_str": "",
                    }
                    all_edges.append(edge)
                    if source_id in active_node_ids and target_id in active_node_ids:
                        edge_copy = dict(edge)
                        edge_copy["is_active_edge"] = True
                        active_edges.append(edge_copy)
            elif partner_upper not in ptm_genes:
                # BioGRID PTM → Non-PTM edge
                edge = {
                    "source": source_id,
                    "target": partner_clean,
                    "evidence_type": "BioGRID",
                    "confidence": confidence,
                    "pathways": [],
                    "pathway_str": "",
                }
                all_edges.append(edge)
                if partner_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(partner_upper)
                    _pfc = gene_protein_fc.get(partner_upper, 0.0)
                    candidate_non_ptm[partner_clean] = {
                        "id": partner_clean,
                        "gene": partner_clean,
                        "site": "",
                        "type": "Non-PTM",
                        "value": round(_pfc, 3),
                        "state": _classify_state(_pfc, "Non-PTM"),
                        "identified": True,
                        "label": partner_clean,
                        "source": "BioGRID",
                    }

        # --- Shared pathway edges (KEGG) ---
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
                    "pathway_str": ", ".join(list(shared)[:2]),
                }
                all_edges.append(edge)
                if source_id in active_node_ids and other_id in active_node_ids:
                    edge_copy = dict(edge)
                    edge_copy["is_active_edge"] = True
                    active_edges.append(edge_copy)

        # --- Kinase-substrate edges (PHASE 1-B: Non-PTM kinase nodes) ---
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        for kinase in upstream:  # No limit — use all available upstream regulators
            kinase_name = kinase if isinstance(kinase, str) else str(kinase)
            kinase_clean = kinase_name.strip()
            kinase_upper = kinase_clean.upper()
            if not kinase_clean:
                continue

            if kinase_clean in gene_ptms:
                # Kinase is a PTM gene — Kinase→Substrate direction
                for kinase_node_id in gene_ptms[kinase_clean]:
                    edge = {
                        "source": kinase_node_id,  # Kinase (source)
                        "target": source_id,        # Substrate (target)
                        "evidence_type": "KEA3",
                        "confidence": 0.8,
                        "pathways": [],
                        "pathway_str": "",
                    }
                    all_edges.append(edge)
                    if kinase_node_id in active_node_ids and source_id in active_node_ids:
                        edge_copy = dict(edge)
                        edge_copy["is_active_edge"] = True
                        active_edges.append(edge_copy)
            else:
                # Kinase is Non-PTM (PHASE 1-B NEW) — most kinases fall here
                edge = {
                    "source": kinase_clean,   # Kinase Non-PTM node (source)
                    "target": source_id,       # PTM Substrate (target)
                    "evidence_type": "KEA3",
                    "confidence": 0.8,
                    "pathways": [],
                    "pathway_str": "",
                }
                all_edges.append(edge)
                # Register candidate Non-PTM kinase node (v4.0: type=Kinase, shape=DIAMOND)
                if kinase_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(kinase_upper)
                    _kfc = gene_protein_fc.get(kinase_upper, 0.0)
                    candidate_non_ptm[kinase_clean] = {
                        "id": kinase_clean,
                        "gene": kinase_clean,
                        "site": "",
                        "type": "Kinase",
                        "value": round(_kfc, 3),
                        "state": _classify_state(_kfc, "Kinase"),
                        "identified": True,
                        "label": kinase_clean,
                        "source": "KEA3",
                    }
                # v4.0: Track kinase->substrate for Shared-Regulator edges
                if kinase_clean not in _kinase_substrates_tp:
                    _kinase_substrates_tp[kinase_clean] = []
                _kinase_substrates_tp[kinase_clean].append(source_id)

        # --- v5.0: Additional kinase sources: kinase_prediction (LLM) + kinase_substrate (pattern) ---
        # kinase_substrate from regulation_extractor (pattern-based from articles)
        kinase_subs = reg.get("kinase_substrate", [])
        for ks in kinase_subs:
            ks_kinase = (ks.get("kinase") or "").strip()
            ks_upper = ks_kinase.upper()
            if not ks_kinase or ks_upper == gene.upper():
                continue
            if ks_kinase not in gene_ptms:
                edge = {
                    "source": ks_kinase,
                    "target": source_id,
                    "evidence_type": "KEA3",
                    "confidence": 0.7,
                    "pathways": [],
                    "pathway_str": "kinase-substrate (literature)",
                }
                all_edges.append(edge)
                if ks_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(ks_upper)
                    _kfc = gene_protein_fc.get(ks_upper, 0.0)
                    candidate_non_ptm[ks_kinase] = {
                        "id": ks_kinase,
                        "gene": ks_kinase,
                        "site": "",
                        "type": "Kinase",
                        "value": round(_kfc, 3),
                        "state": _classify_state(_kfc, "Kinase"),
                        "identified": True,
                        "label": ks_kinase,
                        "source": "Literature",
                    }
                if ks_kinase not in _kinase_substrates_tp:
                    _kinase_substrates_tp[ks_kinase] = []
                _kinase_substrates_tp[ks_kinase].append(source_id)

        # kinase_prediction from LLM (predicted kinases)
        kp = enr.get("kinase_prediction", {})
        predicted_kinases = []
        if hasattr(kp, "predicted_kinases"):
            predicted_kinases = kp.predicted_kinases
        elif isinstance(kp, dict):
            predicted_kinases = kp.get("predicted_kinases", kp.get("predictedKinases", []))
        for pk in predicted_kinases:
            pk_name = ""
            pk_conf = 0.5
            if hasattr(pk, "kinase_name"):
                pk_name = pk.kinase_name
                pk_conf = getattr(pk, "confidence", 0.5)
            elif isinstance(pk, dict):
                pk_name = pk.get("kinase_name") or pk.get("kinaseName", "")
                pk_conf = pk.get("confidence", 0.5)
            elif isinstance(pk, str):
                pk_name = pk
            pk_name = pk_name.strip()
            pk_upper = pk_name.upper()
            if not pk_name or pk_upper == gene.upper():
                continue
            try:
                pk_conf = float(pk_conf)
            except (TypeError, ValueError):
                pk_conf = 0.5
            if pk_conf < 0.3:
                continue  # Skip low-confidence predictions
            if pk_name not in gene_ptms:
                edge = {
                    "source": pk_name,
                    "target": source_id,
                    "evidence_type": "KEA3",
                    "confidence": round(pk_conf, 2),
                    "pathways": [],
                    "pathway_str": "LLM-predicted kinase",
                }
                all_edges.append(edge)
                if pk_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(pk_upper)
                    _kfc = gene_protein_fc.get(pk_upper, 0.0)
                    candidate_non_ptm[pk_name] = {
                        "id": pk_name,
                        "gene": pk_name,
                        "site": "",
                        "type": "Kinase",
                        "value": round(_kfc, 3),
                        "state": _classify_state(_kfc, "Kinase"),
                        "identified": True,
                        "label": pk_name,
                        "source": "LLM-Predicted",
                    }
                if pk_name not in _kinase_substrates_tp:
                    _kinase_substrates_tp[pk_name] = []
                _kinase_substrates_tp[pk_name].append(source_id)

    # v4.0: Add Shared-Regulator edges (PTM proteins sharing the same upstream kinase)
    for kinase_name, substrates in _kinase_substrates_tp.items():
        if len(substrates) >= 2:
            for i in range(len(substrates)):
                for j in range(i + 1, len(substrates)):
                    all_edges.append({
                        "source": substrates[i],
                        "target": substrates[j],
                        "evidence_type": "Shared-Regulator",
                        "confidence": 0.6,
                        "pathways": [],
                        "pathway_str": f"via {kinase_name}",
                    })

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

    # Phase 1-C: Only include Non-PTM nodes that actually have edges
    edge_node_ids = set()
    for e in all_edges:
        edge_node_ids.add(e["source"])
        edge_node_ids.add(e["target"])

    non_ptm_nodes = [
        n for n in candidate_non_ptm.values()
        if n["id"] in edge_node_ids
    ]

    logger.info(
        f"[NET-TP] {timepoint}: candidate_non_ptm={len(candidate_non_ptm)}, "
        f"connected_non_ptm={len(non_ptm_nodes)}, edges={len(all_edges)}"
    )

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
# Build combined network data (PHASE 1 REBUILT)
# ---------------------------------------------------------------------------

def _build_network_data(parsed_ptms: list, enriched_data: list, output_dir: str = "") -> dict:
    """Build combined network nodes and edges from all PTMs.
    
    Phase 1 REBUILT:
    - STRING edges now connect PTM→Non-PTM (not just PTM→PTM)
    - KEA3 edges now connect Non-PTM Kinase→PTM Substrate
    - Non-PTM node limit removed (only edge-connected nodes included)
    """
    nodes = []
    edges = []
    gene_ptms = defaultdict(list)
    _kinase_substrates = {}  # v4.0: kinase_name -> [substrate_ids]

    # v5.0: Build gene -> Protein_Log2FC lookup
    gene_protein_fc = {}
    for ptm in parsed_ptms:
        g = (ptm.get("gene") or "").strip().upper()
        pfc = ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0)
        try:
            pfc = float(pfc) if pfc is not None else 0.0
        except (TypeError, ValueError):
            pfc = 0.0
        if g and (g not in gene_protein_fc or abs(pfc) > abs(gene_protein_fc[g])):
            gene_protein_fc[g] = pfc
    for ed in enriched_data:
        g = (ed.get("gene") or ed.get("Gene.Name", "")).strip().upper()
        pfc = ed.get("protein_log2fc") or ed.get("Protein_Log2FC", 0)
        try:
            pfc = float(pfc) if pfc is not None else 0.0
        except (TypeError, ValueError):
            pfc = 0.0
        if g and (g not in gene_protein_fc or abs(pfc) > abs(gene_protein_fc[g])):
            gene_protein_fc[g] = pfc

    # v5.5: Load ALL protein FC from unified TSV (covers Non-PTM proteins)
    if output_dir:
        unified_fc = _load_unified_protein_fc(output_dir)
        merged_count = 0
        for g, pfc in unified_fc.items():
            if g not in gene_protein_fc:
                gene_protein_fc[g] = pfc
                merged_count += 1
        logger.info(f"[NET-NODE] _build_network_data: Merged {merged_count} Non-PTM protein FC values from unified TSV")

    for ptm in parsed_ptms:
        fc = ptm.get("ptm_relative_log2fc", 0)
        state = _classify_state(fc, "PTM")
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

    ptm_genes = {g.upper() for g in gene_ptms.keys()}

    # Candidate Non-PTM nodes (will be filtered to only those with edges)
    candidate_non_ptm = {}  # id -> node dict
    seen_non_ptm_upper = set()

    for ptm_data in enriched_data:
        enr = ptm_data.get("rag_enrichment", {})
        gene = ptm_data.get("gene") or ptm_data.get("Gene.Name", "")
        source_id = f"{gene}-{ptm_data.get('position') or ptm_data.get('PTM_Position', '')}"

        # --- STRING-DB (PHASE 1-A: PTM→Non-PTM edges) ---
        # v101: Prefer string_db.interactions (dict with score), fallback to string_interactions
        string_interactions = enr.get("string_db", {}).get("interactions", []) or enr.get("string_interactions", [])
        for interaction in string_interactions:  # v101: no limit — use all available
            if isinstance(interaction, dict):
                partner = interaction.get("partner", "")
                confidence = interaction.get("score", 0.7)
            elif isinstance(interaction, str):
                # Legacy string format: "MAPK1(0.95)" — parse score
                if "(" in interaction:
                    parts = interaction.rsplit("(", 1)
                    partner = parts[0].strip()
                    try:
                        confidence = float(parts[1].rstrip(")"))
                    except (ValueError, IndexError):
                        confidence = 0.7
                else:
                    partner = interaction.strip()
                    confidence = 0.7
            else:
                continue

            partner_clean = partner.strip()
            partner_upper = partner_clean.upper()
            if not partner_clean:
                continue

            if partner_clean in gene_ptms:
                # PTM-to-PTM edge
                for target_id in gene_ptms[partner_clean]:
                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "STRING",
                        "confidence": confidence,
                        "pathways": [],
                        "pathway_str": "",
                    })
            elif partner_upper not in ptm_genes:
                # PTM → Non-PTM edge (PHASE 1-A NEW)
                edges.append({
                    "source": source_id,
                    "target": partner_clean,
                    "evidence_type": "STRING",
                    "confidence": confidence,
                    "pathways": [],
                    "pathway_str": "",
                })
                if partner_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(partner_upper)
                    _pfc = gene_protein_fc.get(partner_upper, 0.0)
                    candidate_non_ptm[partner_clean] = {
                        "id": partner_clean,
                        "gene": partner_clean,
                        "site": "",
                        "type": "Non-PTM",
                        "value": round(_pfc, 3),
                        "state": _classify_state(_pfc, "Non-PTM"),
                        "label": partner_clean,
                        "source": "STRING",
                    }
        # --- BioGRID interactions (v101: NEW — experimental PPI evidence) ----
        biogrid_data = enr.get("biogrid", {})
        biogrid_interactions = biogrid_data.get("interactions", []) if isinstance(biogrid_data, dict) else []
        for bg_int in biogrid_interactions:
            if not isinstance(bg_int, dict):
                continue
            int_a = bg_int.get("interactor_a", "").strip()
            int_b = bg_int.get("interactor_b", "").strip()
            if int_a.upper() == gene.upper():
                partner_clean = int_b
            elif int_b.upper() == gene.upper():
                partner_clean = int_a
            else:
                continue
            partner_upper = partner_clean.upper()
            if not partner_clean or partner_upper == gene.upper():
                continue
            throughput = bg_int.get("throughput", "")
            confidence = 0.85 if "Low" in throughput else 0.65
            if partner_clean in gene_ptms:
                for target_id in gene_ptms[partner_clean]:
                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "BioGRID",
                        "confidence": confidence,
                        "pathways": [],
                        "pathway_str": "",
                    })
            elif partner_upper not in ptm_genes:
                edges.append({
                    "source": source_id,
                    "target": partner_clean,
                    "evidence_type": "BioGRID",
                    "confidence": confidence,
                    "pathways": [],
                    "pathway_str": "",
                })
                if partner_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(partner_upper)
                    _pfc = gene_protein_fc.get(partner_upper, 0.0)
                    candidate_non_ptm[partner_clean] = {
                        "id": partner_clean,
                        "gene": partner_clean,
                        "site": "",
                        "type": "Non-PTM",
                        "value": round(_pfc, 3),
                        "state": _classify_state(_pfc, "Non-PTM"),
                        "label": partner_clean,
                        "source": "BioGRID",
                    }
        # --- Shared pathway edges (KEGG) ----
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

        # --- Kinase-substrate edges (PHASE 1-B: Non-PTM kinase nodes) ---
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        for kinase in upstream:  # No limit — use all available upstream regulators
            kinase_name = kinase if isinstance(kinase, str) else str(kinase)
            kinase_clean = kinase_name.strip()
            kinase_upper = kinase_clean.upper()
            if not kinase_clean:
                continue

            if kinase_clean in gene_ptms:
                # Kinase is PTM gene — Kinase→Substrate direction
                for kinase_node_id in gene_ptms[kinase_clean]:
                    edges.append({
                        "source": kinase_node_id,
                        "target": source_id,
                        "evidence_type": "KEA3",
                        "confidence": 0.8,
                        "pathways": [],
                        "pathway_str": "",
                    })
            else:
                # Kinase is Non-PTM (v4.0: type=Kinase, shape=DIAMOND)
                edges.append({
                    "source": kinase_clean,
                    "target": source_id,
                    "evidence_type": "KEA3",
                    "confidence": 0.8,
                    "pathways": [],
                    "pathway_str": "",
                })
                if kinase_upper not in seen_non_ptm_upper:
                    seen_non_ptm_upper.add(kinase_upper)
                    _kfc = gene_protein_fc.get(kinase_upper, 0.0)
                    candidate_non_ptm[kinase_clean] = {
                        "id": kinase_clean,
                        "gene": kinase_clean,
                        "site": "",
                        "type": "Kinase",
                        "value": round(_kfc, 3),
                        "state": _classify_state(_kfc, "Kinase"),
                        "label": kinase_clean,
                        "source": "KEA3",
                    }
                # v4.0: Track kinase->substrate for Shared-Regulator edges
                if kinase_clean not in _kinase_substrates:
                    _kinase_substrates[kinase_clean] = []
                _kinase_substrates[kinase_clean].append(source_id)

        # --- v5.0: Kinase from kinase_prediction (LLM-predicted) ---
        kinase_pred = enr.get("kinase_prediction", {})
        if isinstance(kinase_pred, dict):
            pred_kinases = kinase_pred.get("predicted_kinases", []) or kinase_pred.get("kinases", [])
            if not pred_kinases and isinstance(kinase_pred.get("result"), list):
                pred_kinases = kinase_pred["result"]
            for pk in pred_kinases:
                pk_name = pk if isinstance(pk, str) else (pk.get("kinase") or pk.get("name") or str(pk))
                pk_clean = pk_name.strip()
                pk_upper = pk_clean.upper()
                if not pk_clean or pk_upper == gene.upper():
                    continue
                if pk_clean in gene_ptms:
                    for pk_node_id in gene_ptms[pk_clean]:
                        edges.append({
                            "source": pk_node_id,
                            "target": source_id,
                            "evidence_type": "Kinase-Substrate-Predicted",
                            "confidence": 0.6,
                            "pathways": [],
                            "pathway_str": "",
                        })
                else:
                    edges.append({
                        "source": pk_clean,
                        "target": source_id,
                        "evidence_type": "Kinase-Substrate-Predicted",
                        "confidence": 0.6,
                        "pathways": [],
                        "pathway_str": "",
                    })
                    if pk_upper not in seen_non_ptm_upper:
                        seen_non_ptm_upper.add(pk_upper)
                        _kfc = gene_protein_fc.get(pk_upper, 0.0)
                        candidate_non_ptm[pk_clean] = {
                            "id": pk_clean,
                            "gene": pk_clean,
                            "site": "",
                            "type": "Kinase",
                            "value": round(_kfc, 3),
                            "state": _classify_state(_kfc, "Kinase"),
                            "label": pk_clean,
                            "source": "Kinase-Prediction",
                        }
                    if pk_clean not in _kinase_substrates:
                        _kinase_substrates[pk_clean] = []
                    _kinase_substrates[pk_clean].append(source_id)

        # --- v5.0: Kinase from kinase_substrate (pattern-matched) ---
        kinase_sub = enr.get("kinase_substrate", {})
        if isinstance(kinase_sub, dict):
            sub_kinases = kinase_sub.get("kinases", []) or kinase_sub.get("matched_kinases", [])
            if not sub_kinases and isinstance(kinase_sub.get("result"), list):
                sub_kinases = kinase_sub["result"]
            for sk in sub_kinases:
                sk_name = sk if isinstance(sk, str) else (sk.get("kinase") or sk.get("name") or str(sk))
                sk_clean = sk_name.strip()
                sk_upper = sk_clean.upper()
                if not sk_clean or sk_upper == gene.upper():
                    continue
                if sk_clean in gene_ptms:
                    for sk_node_id in gene_ptms[sk_clean]:
                        edges.append({
                            "source": sk_node_id,
                            "target": source_id,
                            "evidence_type": "Kinase-Substrate",
                            "confidence": 0.75,
                            "pathways": [],
                            "pathway_str": "",
                        })
                else:
                    edges.append({
                        "source": sk_clean,
                        "target": source_id,
                        "evidence_type": "Kinase-Substrate",
                        "confidence": 0.75,
                        "pathways": [],
                        "pathway_str": "",
                    })
                    if sk_upper not in seen_non_ptm_upper:
                        seen_non_ptm_upper.add(sk_upper)
                        _kfc = gene_protein_fc.get(sk_upper, 0.0)
                        candidate_non_ptm[sk_clean] = {
                            "id": sk_clean,
                            "gene": sk_clean,
                            "site": "",
                            "type": "Kinase",
                            "value": round(_kfc, 3),
                            "state": _classify_state(_kfc, "Kinase"),
                            "label": sk_clean,
                            "source": "Kinase-Substrate",
                        }
                    if sk_clean not in _kinase_substrates:
                        _kinase_substrates[sk_clean] = []
                    _kinase_substrates[sk_clean].append(source_id)

    # v4.0: Add Shared-Regulator edges (PTM proteins sharing the same upstream kinase)
    for kinase_name, substrates in _kinase_substrates.items():
        if len(substrates) >= 2:
            for i in range(len(substrates)):
                for j in range(i + 1, len(substrates)):
                    edges.append({
                        "source": substrates[i],
                        "target": substrates[j],
                        "evidence_type": "Shared-Regulator",
                        "confidence": 0.6,
                        "pathways": [],
                        "pathway_str": f"via {kinase_name}",
                    })

    # Deduplicate edgess
    seen = set()
    unique_edges = []
    for e in edges:
        key = tuple(sorted([e["source"], e["target"]])) + (e["evidence_type"],)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    # Phase 1-C: Only include Non-PTM nodes that have edges (no arbitrary limit)
    edge_node_ids = set()
    for e in unique_edges:
        edge_node_ids.add(e["source"])
        edge_node_ids.add(e["target"])

    connected_non_ptm = [
        n for n in candidate_non_ptm.values()
        if n["id"] in edge_node_ids
    ]

    all_nodes = nodes + connected_non_ptm

    logger.info(
        f"[NET-BUILD] Combined network: PTM_nodes={len(nodes)}, "
        f"Non-PTM_candidates={len(candidate_non_ptm)}, "
        f"Non-PTM_connected={len(connected_non_ptm)}, "
        f"edges={len(unique_edges)}"
    )

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
                        "protein_log2fc": n.get("protein_log2fc", n.get("value", 0)),
                        "state": n.get("state", _classify_state(n.get("value", 0), n.get("type", "Non-PTM"))),
                        "source": n.get("source", "STRING"),
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

     # Color Legend v4.0
    legend_lines.append("**Node Color Legend**:")
    legend_lines.append("*PTM Proteins (Red/Blue gradient — intensity = |Log2FC|):*")
    legend_lines.append(f"- Dark Red ({NODE_COLORS['high_active']}): Strong upregulation (Log2FC > 2.0)")
    legend_lines.append(f"- Red ({NODE_COLORS['moderate_active']}): Moderate upregulation (1.0 < Log2FC ≤ 2.0)")
    legend_lines.append(f"- Light Red ({NODE_COLORS['low_active']}): Weak upregulation (0 < Log2FC ≤ 1.0)")
    legend_lines.append(f"- Gray ({NODE_COLORS['neutral']}): No significant change")
    legend_lines.append(f"- Light Blue ({NODE_COLORS['low_inhibited']}): Weak downregulation (-1.0 ≤ Log2FC < 0)")
    legend_lines.append(f"- Blue ({NODE_COLORS['inhibited']}): Moderate downregulation (-2.0 ≤ Log2FC < -1.0)")
    legend_lines.append(f"- Dark Blue ({NODE_COLORS['high_inhibited']}): Strong downregulation (Log2FC < -2.0)")
    legend_lines.append("")
    legend_lines.append("*Non-PTM Proteins (Green/Purple gradient — Protein_Log2FC):*")
    legend_lines.append(f"- Dark Green ({NODE_COLORS['nonptm_up_strong']}): Strong increase (Log2FC > 1.5)")
    legend_lines.append(f"- Green ({NODE_COLORS['nonptm_up']}): Moderate increase (0.5 < Log2FC ≤ 1.5)")
    legend_lines.append(f"- Light Green ({NODE_COLORS['nonptm_up_weak']}): Weak increase (0.1 < Log2FC ≤ 0.5)")
    legend_lines.append(f"- Gray ({NODE_COLORS['nonptm_neutral']}): No significant change")
    legend_lines.append(f"- Light Purple ({NODE_COLORS['nonptm_down_weak']}): Weak decrease (-0.5 ≤ Log2FC < -0.1)")
    legend_lines.append(f"- Purple ({NODE_COLORS['nonptm_down']}): Moderate decrease (-1.5 ≤ Log2FC < -0.5)")
    legend_lines.append(f"- Dark Purple ({NODE_COLORS['nonptm_down_strong']}): Strong decrease (Log2FC < -1.5)")
    legend_lines.append("")
    legend_lines.append("*Kinase / Upstream Regulators (Diamond shape):*")
    legend_lines.append(f"- Deep Orange ({NODE_COLORS['kinase_up']}): Kinase with increased activity (Log2FC > 0.5)")
    legend_lines.append(f"- Amber ({NODE_COLORS['kinase']}): Kinase / upstream regulator (neutral)")
    legend_lines.append(f"- Light Orange ({NODE_COLORS['kinase_down']}): Kinase with decreased activity (Log2FC < -0.5)")
    legend_lines.append("")
    # Node Shape Legend v4.0
    legend_lines.append("**Node Shape Legend**:")
    legend_lines.append("- Circle (ELLIPSE): Proteins (PTM + Non-PTM)")
    legend_lines.append("- Diamond (DIAMOND): Kinase / Upstream regulators")
    legend_lines.append("")

    # Node Size Legend (Phase 2: updated range)
    legend_lines.append("**Node Size Legend**:")
    legend_lines.append("- Node size is proportional to |Log2FC| magnitude (40–120px range)")
    legend_lines.append("")

    # Edge Types
    legend_lines.append("**Edge Types**:")
    evidence_types = defaultdict(int)
    for e in edges:
        evidence_types[e.get("evidence_type", "Unknown")] += 1
    for et, cnt in sorted(evidence_types.items(), key=lambda x: -x[1]):
        color = EDGE_COLORS.get(et, EDGE_COLORS["default"])
        style = "solid" if et in ("STRING", "STRING-DB", "KEA3", "Kinase-Substrate", "BioGRID") else "dashed"
        arrow = " (directed →)" if et in ("KEA3", "Kinase-Substrate") else ""
        legend_lines.append(f"- {et} ({color}, {style}{arrow}): {cnt} connections")
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
# Canonical Pathway Distribution Bar Graph (replaces Figure 1)
# ---------------------------------------------------------------------------

def _generate_pathway_distribution_graph(
    parsed_ptms: list,
    enriched_data: list,
    network_data: dict,
    output_dir: str,
) -> Optional[str]:
    """Generate a horizontal bar graph showing canonical pathway distribution
    for **activated** PTM and Non-PTM proteins only.

    v5.1 changes:
    - Only activated proteins are included (PTM: Log2FC > 0, Non-PTM: Protein_Log2FC > 0)
    - Non-PTM proteins get pathway assignments via:
      a) KEGG edges in network_data (shared pathway with PTM partner)
      b) Inheriting pathways from their PTM interaction partners

    Returns the path to the saved PNG image, or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available — skipping pathway distribution graph")
        return None

    # ---- Step 1: Identify activated PTM genes and their pathways ----
    # Note: parsed_ptms uses 'ptm_relative_log2fc' (from context_loader),
    # while enriched_data (raw JSON) uses 'PTM_Relative_Log2FC' or 'ptm_relative_log2fc'.
    # For multi-condition data, condition_data may contain per-timepoint Log2FC values.
    ptm_genes = set()  # ALL PTM genes (for Non-PTM identification)
    activated_ptm_genes = set()  # Only activated PTM genes
    # First pass: from parsed_ptms (has normalized field names)
    for ptm in parsed_ptms:
        gene = (ptm.get("gene") or ptm.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        ptm_genes.add(gene)
        log2fc = 0.0
        try:
            # parsed_ptms field: ptm_relative_log2fc (set by context_loader)
            log2fc = float(ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0))
        except (ValueError, TypeError):
            pass
        # Also check condition_data for multi-timepoint: use max absolute value
        if log2fc == 0.0:
            for cd in ptm.get("condition_data", []):
                try:
                    cd_fc = float(cd.get("PTM_Log2FC") or cd.get("ptm_log2fc") or cd.get("Log2FC", 0))
                    if abs(cd_fc) > abs(log2fc):
                        log2fc = cd_fc
                except (ValueError, TypeError):
                    pass
        if log2fc > 0:
            activated_ptm_genes.add(gene)
    # Second pass: from enriched_data (raw JSON, may have different field names)
    for ed in enriched_data:
        gene = (ed.get("gene") or ed.get("Gene.Name", "")).strip().upper()
        if not gene or gene in activated_ptm_genes:
            continue
        ptm_genes.add(gene)
        log2fc = 0.0
        try:
            log2fc = float(ed.get("PTM_Relative_Log2FC") or ed.get("ptm_relative_log2fc", 0))
        except (ValueError, TypeError):
            pass
        if log2fc > 0:
            activated_ptm_genes.add(gene)
    logger.info(f"[NET-NODE] Pathway graph Step1: total PTM genes={len(ptm_genes)}, activated={len(activated_ptm_genes)}")

    # ---- Step 2: Build gene -> Protein_Log2FC lookup for Non-PTM filtering ----
    gene_protein_fc: Dict[str, float] = {}
    for ptm in parsed_ptms:
        gene = (ptm.get("gene") or ptm.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        try:
            pfc = float(ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0))
        except (ValueError, TypeError):
            pfc = 0.0
        gene_protein_fc[gene] = pfc
    for ed in enriched_data:
        gene = (ed.get("gene") or ed.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        try:
            pfc = float(ed.get("protein_log2fc") or ed.get("Protein_Log2FC", 0))
        except (ValueError, TypeError):
            pfc = 0.0
        if gene not in gene_protein_fc or pfc != 0.0:
            gene_protein_fc[gene] = pfc

    # ---- Step 3: Collect activated PTM gene -> pathways ----
    def _pw_name(p):
        return (p.get("name", str(p)) if isinstance(p, dict) else str(p)).strip()

    # pathway_name -> {"ptm": set(genes), "non_ptm": set(genes)}
    pathway_proteins: Dict[str, Dict[str, set]] = defaultdict(lambda: {"ptm": set(), "non_ptm": set()})

    # gene -> set of pathway names (for activated PTM genes only)
    activated_ptm_pathways: Dict[str, set] = defaultdict(set)

    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip().upper()
        if gene not in activated_ptm_genes:
            continue
        enr = ptm_data.get("rag_enrichment", {})
        pathways = enr.get("pathways", [])
        for pw in pathways:
            pw_name = _pw_name(pw)
            if pw_name:
                pathway_proteins[pw_name]["ptm"].add(gene)
                activated_ptm_pathways[gene].add(pw_name)

    # ---- Step 4: Collect ALL connected Non-PTM proteins from network_data ----
    # Note: Non-PTM proteins don't have their own Protein_Log2FC (they are interaction
    # partners, not in the original PTM dataset). We include ALL connected Non-PTM
    # proteins regardless of FC value, since their presence in the network already
    # indicates biological relevance through interaction with PTM proteins.
    non_ptm_nodes_in_network = set()
    nodes = network_data.get("nodes", [])
    for node in nodes:
        if node.get("type") == "Non-PTM":
            node_gene = node.get("gene", node.get("id", "")).strip().upper()
            if node_gene:
                non_ptm_nodes_in_network.add(node_gene)

    logger.info(
        f"[NET-NODE] Pathway graph: activated PTM genes={len(activated_ptm_genes)}, "
        f"connected Non-PTM genes={len(non_ptm_nodes_in_network)}"
    )

    # ---- Step 5: Assign pathways to Non-PTM proteins ----
    edges = network_data.get("edges", [])
    kegg_assigned = set()   # track Non-PTM genes assigned via KEGG edges
    string_assigned = set() # track Non-PTM genes assigned via STRING/BioGRID inheritance

    # Method A: From KEGG edges in network_data
    # (KEGG edges are typically PTM↔PTM, but check anyway)
    for edge in edges:
        if edge.get("evidence_type") != "KEGG":
            continue
        edge_pathways = edge.get("pathways", [])
        if not edge_pathways:
            continue
        src = edge.get("source", "").strip().upper()
        tgt = edge.get("target", "").strip().upper()
        # Extract gene name from node ID (e.g., "GENE-S123" -> "GENE")
        src_gene = src.split("-")[0] if "-" in src else src
        tgt_gene = tgt.split("-")[0] if "-" in tgt else tgt
        for pw in edge_pathways:
            pw_name = _pw_name(pw) if isinstance(pw, dict) else str(pw).strip()
            if not pw_name:
                continue
            if src_gene in non_ptm_nodes_in_network:
                pathway_proteins[pw_name]["non_ptm"].add(src_gene)
                kegg_assigned.add(src_gene)
            if tgt_gene in non_ptm_nodes_in_network:
                pathway_proteins[pw_name]["non_ptm"].add(tgt_gene)
                kegg_assigned.add(tgt_gene)

    # Method B: Inherit pathways from PTM interaction partners via STRING/BioGRID edges
    # This is the primary mechanism: if a Non-PTM protein interacts with an activated
    # PTM protein that has KEGG pathways, the Non-PTM inherits those pathways.
    for edge in edges:
        ev_type = edge.get("evidence_type", "")
        if ev_type not in ("STRING", "BioGRID"):
            continue
        src = edge.get("source", "").strip().upper()
        tgt = edge.get("target", "").strip().upper()
        src_gene = src.split("-")[0] if "-" in src else src
        tgt_gene = tgt.split("-")[0] if "-" in tgt else tgt

        # If one end is activated PTM (with pathways) and the other is Non-PTM,
        # assign the PTM's pathways to the Non-PTM
        if src_gene in activated_ptm_pathways and tgt_gene in non_ptm_nodes_in_network:
            for pw_name in activated_ptm_pathways[src_gene]:
                pathway_proteins[pw_name]["non_ptm"].add(tgt_gene)
            string_assigned.add(tgt_gene)
        if tgt_gene in activated_ptm_pathways and src_gene in non_ptm_nodes_in_network:
            for pw_name in activated_ptm_pathways[tgt_gene]:
                pathway_proteins[pw_name]["non_ptm"].add(src_gene)
            string_assigned.add(src_gene)

    # Method C: For Non-PTM proteins not yet assigned, check if they interact with
    # ANY PTM protein (not just activated ones) that has pathway data.
    # This broadens coverage for Non-PTM proteins.
    all_ptm_pathways: Dict[str, set] = defaultdict(set)
    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        enr = ptm_data.get("rag_enrichment", {})
        pathways = enr.get("pathways", [])
        for pw in pathways:
            pw_name = _pw_name(pw)
            if pw_name:
                all_ptm_pathways[gene].add(pw_name)

    for edge in edges:
        ev_type = edge.get("evidence_type", "")
        if ev_type not in ("STRING", "BioGRID"):
            continue
        src = edge.get("source", "").strip().upper()
        tgt = edge.get("target", "").strip().upper()
        src_gene = src.split("-")[0] if "-" in src else src
        tgt_gene = tgt.split("-")[0] if "-" in tgt else tgt

        if src_gene in all_ptm_pathways and tgt_gene in non_ptm_nodes_in_network:
            if tgt_gene not in string_assigned and tgt_gene not in kegg_assigned:
                for pw_name in all_ptm_pathways[src_gene]:
                    pathway_proteins[pw_name]["non_ptm"].add(tgt_gene)
                string_assigned.add(tgt_gene)
        if tgt_gene in all_ptm_pathways and src_gene in non_ptm_nodes_in_network:
            if src_gene not in string_assigned and src_gene not in kegg_assigned:
                for pw_name in all_ptm_pathways[tgt_gene]:
                    pathway_proteins[pw_name]["non_ptm"].add(src_gene)
                string_assigned.add(src_gene)

    total_assigned = kegg_assigned | string_assigned
    logger.info(
        f"[NET-NODE] Pathway assignment: KEGG-assigned={len(kegg_assigned)}, "
        f"STRING/BioGRID-inherited={len(string_assigned)}, "
        f"total Non-PTM with pathways={len(total_assigned)} / {len(non_ptm_nodes_in_network)}"
    )

    if not pathway_proteins:
        logger.warning("No pathway data found — skipping pathway distribution graph")
        return None

    # ---- Step 5.5: Build gene -> |Protein_Log2FC| lookup for weighting ----
    # Load from unified TSV (covers ALL proteins including Non-PTM)
    gene_fc_weight: Dict[str, float] = {}
    if output_dir:
        unified_fc = _load_unified_protein_fc(output_dir)
        for g, pfc in unified_fc.items():
            gene_fc_weight[g] = abs(pfc)
    # Override/supplement with PTM-specific data (ptm_relative_log2fc for PTM genes)
    for ptm in parsed_ptms:
        gene = (ptm.get("gene") or ptm.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        try:
            fc = abs(float(ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0)))
        except (ValueError, TypeError):
            fc = 0.0
        if gene not in gene_fc_weight or fc > gene_fc_weight[gene]:
            gene_fc_weight[gene] = fc
    logger.info(f"[NET-NODE] Pathway graph Step5.5: FC weights available for {len(gene_fc_weight)} genes")

    # ---- Step 6: Compute cumulative weighted scores and sort ----
    pw_data = []
    for pw_name, groups in pathway_proteins.items():
        ptm_genes_in_pw = groups["ptm"]
        non_ptm_genes_in_pw = groups["non_ptm"]
        ptm_count = len(ptm_genes_in_pw)
        non_ptm_count = len(non_ptm_genes_in_pw)
        # Cumulative |Log2FC| score: sum of absolute FC for each gene in pathway
        ptm_score = sum(gene_fc_weight.get(g, 0.0) for g in ptm_genes_in_pw)
        non_ptm_score = sum(gene_fc_weight.get(g, 0.0) for g in non_ptm_genes_in_pw)
        total_score = ptm_score + non_ptm_score
        if ptm_count + non_ptm_count > 0:
            pw_data.append({
                "pathway": pw_name,
                "ptm_score": round(ptm_score, 2),
                "non_ptm_score": round(non_ptm_score, 2),
                "total_score": round(total_score, 2),
                "ptm_count": ptm_count,
                "non_ptm_count": non_ptm_count,
            })

    if not pw_data:
        logger.warning("No pathway proteins found — skipping pathway distribution graph")
        return None

    # Sort by total cumulative score descending, take top 25
    pw_data.sort(key=lambda x: -x["total_score"])
    pw_data = pw_data[:25]
    pw_data.reverse()  # Reverse for horizontal bar (bottom = highest)

    # ---- Step 7: Generate the weighted bar graph ----
    fig, ax = plt.subplots(figsize=(14, max(7, len(pw_data) * 0.45)))

    pathways_list = [d["pathway"] for d in pw_data]
    ptm_scores = [d["ptm_score"] for d in pw_data]
    non_ptm_scores = [d["non_ptm_score"] for d in pw_data]
    y_pos = np.arange(len(pathways_list))
    bar_height = 0.35

    # Colors: PTM = coral/red tones, Non-PTM = teal/green tones
    bars_ptm = ax.barh(y_pos + bar_height / 2, ptm_scores, bar_height,
                       label="Activated PTM Proteins", color="#E74C3C", alpha=0.85,
                       edgecolor="white", linewidth=0.5)
    bars_non = ax.barh(y_pos - bar_height / 2, non_ptm_scores, bar_height,
                       label="Non-PTM Interactor Proteins", color="#2ECC71", alpha=0.85,
                       edgecolor="white", linewidth=0.5)

    # Truncate long pathway names
    display_names = []
    for name in pathways_list:
        if len(name) > 50:
            display_names.append(name[:47] + "...")
        else:
            display_names.append(name)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(display_names, fontsize=9)
    ax.set_xlabel("Cumulative |Log2FC| Score", fontsize=11, fontweight="bold")
    ax.set_title(
        "Canonical Pathway Distribution: Activated PTM vs Non-PTM Interactor Proteins\n"
        "(Weighted by |Protein_Log2FC|)",
        fontsize=13, fontweight="bold", pad=15,
    )
    ax.legend(loc="lower right", fontsize=10, framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", alpha=0.3, linestyle="--")

    # Add score + count labels on bars: "score (n=count)"
    max_width = max(max(ptm_scores, default=0), max(non_ptm_scores, default=0))
    label_offset = max_width * 0.01 + 0.1  # dynamic offset
    for bar, d in zip(bars_ptm, pw_data):
        width = bar.get_width()
        if width > 0 or d["ptm_count"] > 0:
            label_text = f"{width:.1f} (n={d['ptm_count']})"
            ax.text(max(width, 0) + label_offset, bar.get_y() + bar.get_height() / 2,
                    label_text, va="center", fontsize=7.5, color="#C0392B", fontweight="medium")
    for bar, d in zip(bars_non, pw_data):
        width = bar.get_width()
        if width > 0 or d["non_ptm_count"] > 0:
            label_text = f"{width:.1f} (n={d['non_ptm_count']})"
            ax.text(max(width, 0) + label_offset, bar.get_y() + bar.get_height() / 2,
                    label_text, va="center", fontsize=7.5, color="#27AE60", fontweight="medium")

    plt.tight_layout()

    output_path = Path(output_dir) / "pathway_distribution.png"
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    total_ptm_score = sum(d["ptm_score"] for d in pw_data)
    total_non_score = sum(d["non_ptm_score"] for d in pw_data)
    total_ptm_n = sum(d["ptm_count"] for d in pw_data)
    total_non_n = sum(d["non_ptm_count"] for d in pw_data)
    logger.info(
        f"[NET-NODE] Pathway distribution graph saved: {output_path} "
        f"({len(pw_data)} pathways, PTM: score={total_ptm_score:.1f} n={total_ptm_n}, "
        f"Non-PTM: score={total_non_score:.1f} n={total_non_n})"
    )
    return str(output_path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_network_analysis(state: dict) -> dict:
    """Analyze temporal networks and optionally generate Cytoscape images.
    
    GAP 1: Now performs per-timepoint analysis when multiple conditions exist.
    Phase 5: Validates network integrity before Cytoscape rendering.
    """
    os.environ["DEFAULT_BASE_URL"] = _cytoscape_base_url()

    cb = state.get("progress_callback")
    if cb:
        cb(55, "Analyzing signaling networks")

    try:
        return _run_network_analysis_inner(state)
    except Exception as net_err:
        logger.error(f"[NET-NODE] run_network_analysis failed: {net_err}", exc_info=True)
        if cb:
            cb(65, f"Network analysis failed: {net_err}")
        return {
            "network_analysis": {
                "network_data": {"nodes": [], "edges": []},
                "legends": {},
                "cytoscape_connected": False,
                "network_images": {},
                "pathway_graph_path": None,
                "cascade_diagram_path": None,
                "cascade_diagram_paths": {},
                "ptm_count": 0,
                "timepoint_results": {},
                "timepoints": [],
                "validation": {"is_valid": False, "total_nodes": 0, "total_edges": 0, "orphan_nodes": 0},
            },
            "network_results": {},
        }


def _run_network_analysis_inner(state: dict) -> dict:
    """Inner implementation of run_network_analysis."""
    cb = state.get("progress_callback")
    parsed_ptms = state.get("parsed_ptms", [])
    enriched_data = state.get("enriched_ptm_data", [])
    output_dir = state.get("output_dir", "/tmp")

    # GAP 1: Detect timepoints and perform per-timepoint analysis
    timepoints = _detect_timepoints(parsed_ptms)
    timepoint_results = {}

    if len(timepoints) > 1:
        logger.info(f"[NET-NODE] Detected {len(timepoints)} timepoints: {timepoints}")
        for tp in timepoints:
            tp_result = _analyze_timepoint(parsed_ptms, enriched_data, tp, output_dir=output_dir)
            timepoint_results[tp] = tp_result
            logger.info(
                f"[NET-NODE] Timepoint {tp}: "
                f"active={tp_result['stats']['active_ptm_count']}, "
                f"inhibited={tp_result['stats'].get('inhibited_ptm_count', 0)}, "
                f"non_ptm={tp_result['stats']['non_ptm_count']}, "
                f"edges={tp_result['stats']['total_edge_count']}"
            )
    else:
        logger.info("[NET-NODE] Single timepoint/condition — using combined network")

    # Build combined network data (for backward compatibility + main network image)
    network_data = _build_network_data(parsed_ptms, enriched_data, output_dir=output_dir)

    # Phase 5: Validate network integrity
    validation = _validate_network(network_data["nodes"], network_data["edges"])

    # Phase 5: Export SIF for debugging
    _export_sif(
        network_data["edges"],
        validation.get("orphan_node_ids", []),
        output_dir,
    )

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
        # Phase 1/4: Generate networks with isolated node separation
        network_images = _generate_cytoscape_networks(
            network_data, output_dir, parsed_ptms, timepoint_results
        )
    else:
        logger.info("Cytoscape not available — using text-based legends only")

    if cb:
        cb(63, "Generating pathway distribution graph")

    # v5.1: Generate Canonical Pathway Distribution Bar Graph (activated only)
    pathway_graph_path = None
    try:
        pathway_graph_path = _generate_pathway_distribution_graph(
            parsed_ptms, enriched_data, network_data, output_dir
        )
    except Exception as pw_err:
        logger.error(f"[NET-NODE] Pathway distribution graph failed: {pw_err}", exc_info=True)
        pathway_graph_path = None

    # v6.1: Generate Signaling Cascade Diagrams — per-condition when multiple timepoints
    cascade_diagram_path = None          # combined (single condition or fallback)
    cascade_diagram_paths = {}           # condition → path (per-condition diagrams)
    try:
        # v6.1 fix: Use relative import (same package) with absolute fallback.
        # Docker installs packages as 'report_generation.*' (no 'workers.' prefix)
        # while local dev may have 'workers.' in sys.path.
        try:
            from .signaling_cascade import generate_signaling_cascade_diagram
        except ImportError:
            try:
                from report_generation.core.nodes.signaling_cascade import (
                    generate_signaling_cascade_diagram,
                )
            except ImportError:
                from signaling_cascade import generate_signaling_cascade_diagram
        logger.info("[NET-NODE] signaling_cascade module imported successfully")

        if len(timepoints) > 1:
            # Multi-condition: generate one diagram per condition
            if cb:
                cb(64, f"Generating signaling cascade diagrams for {len(timepoints)} conditions")
            for tp_idx, tp in enumerate(timepoints):
                logger.info(f"[NET-NODE] Generating cascade diagram for condition: {tp}")
                tp_path = generate_signaling_cascade_diagram(
                    parsed_ptms, enriched_data, network_data, output_dir,
                    top_n_pathways=5, condition=tp,
                )
                if tp_path:
                    cascade_diagram_paths[tp] = tp_path
                    logger.info(f"[NET-NODE] Cascade diagram for '{tp}' saved: {tp_path}")
                else:
                    logger.info(f"[NET-NODE] Cascade diagram for '{tp}': no pathways with sufficient proteins")
            logger.info(
                f"[NET-NODE] Per-condition cascade diagrams: "
                f"{len(cascade_diagram_paths)}/{len(timepoints)} generated"
            )
        else:
            # Single condition: generate combined diagram (backward compatible)
            if cb:
                cb(64, "Generating signaling cascade diagram")
            cascade_diagram_path = generate_signaling_cascade_diagram(
                parsed_ptms, enriched_data, network_data, output_dir, top_n_pathways=5
            )
            if cascade_diagram_path:
                logger.info(f"[NET-NODE] Signaling cascade diagram saved: {cascade_diagram_path}")
            else:
                logger.info("[NET-NODE] Signaling cascade diagram: no pathways with sufficient proteins")
    except Exception as cascade_err:
        logger.error(f"[NET-NODE] Signaling cascade diagram FAILED: {cascade_err}", exc_info=True)
        cascade_diagram_path = None
        cascade_diagram_paths = {}

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
            "pathway_graph_path": pathway_graph_path,
            "cascade_diagram_path": cascade_diagram_path,
            "cascade_diagram_paths": cascade_diagram_paths,
            "ptm_count": len(parsed_ptms),
            "timepoint_results": timepoint_results,
            "timepoints": timepoints,
            "validation": validation,
        },
        "network_results": network_results,
    }

    logger.info(
        f"[NET-NODE] run_network_analysis returning: "
        f"cytoscape_connected={cytoscape_connected}, "
        f"timepoints={timepoints}, "
        f"pathway_graph={'OK' if pathway_graph_path else 'NONE'}, "
        f"cascade_diagram={'OK' if cascade_diagram_path else 'NONE'}, "
        f"cascade_per_condition={list(cascade_diagram_paths.keys()) if cascade_diagram_paths else 'NONE'}, "
        f"network_images={list(network_images.keys()) if network_images else 'EMPTY'}, "
        f"network_results_keys={list(network_results.keys()) if network_results else 'EMPTY'}, "
        f"validation={{'nodes': {validation['total_nodes']}, 'edges': {validation['total_edges']}, "
        f"'orphan': {validation['orphan_nodes']}, 'valid': {validation['is_valid']}}}"
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
    
    Phase 1/4: Creates networks with proper edge connectivity.
    Phase 4: Separates isolated nodes before rendering.
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
        # Phase 4: Separate isolated nodes from connected nodes
        connected_nodes, isolated_nodes = _separate_isolated_nodes(nodes, edges)

        # Phase 5: Add missing Non-PTM nodes that are referenced in edges but not in node list
        node_ids = {n["id"] for n in connected_nodes}
        edge_node_ids = set()
        for e in edges:
            edge_node_ids.add(e["source"])
            edge_node_ids.add(e["target"])
        missing_ids = edge_node_ids - node_ids
        for mid in missing_ids:
            connected_nodes.append({
                "id": mid,
                "gene": mid,
                "site": "",
                "type": "Non-PTM",
                "value": 0,
                "state": _classify_state(0, "Non-PTM"),
                "label": mid,
            })
            logger.debug(f"[CYTO-GEN] Added missing node for edge reference: {mid}")

        if not connected_nodes:
            logger.warning("[CYTO-GEN] No connected nodes after isolation separation")
            connected_nodes = nodes  # Fallback to all nodes

        # --- Main combined network ---
        nodes_df = pd.DataFrame(connected_nodes)
        edges_df = pd.DataFrame(edges) if edges else None

        network_name = "PTM_Signaling_Network"
        network_suid = p4c.create_network_from_data_frames(
            nodes=nodes_df,
            edges=edges_df,
            title=network_name,
            collection="PTM Analysis",
        )
        logger.info(f"Cytoscape network created: {network_name} (SUID: {network_suid})")

        _apply_visual_style(p4c, network_suid, network_name, connected_nodes)
        time.sleep(1)

        png_path = _save_network_png(p4c, network_suid, network_name, str(output_path))
        if png_path:
            # Phase 4: Auto-crop whitespace
            _auto_crop_image(png_path)
            network_images["main"] = png_path
            logger.info(f"Main network image saved: {png_path}")

        # --- Per-timepoint networks ---
        if timepoint_results:
            for tp, tp_data in sorted(
                timepoint_results.items(), key=lambda x: _tp_to_minutes(x[0])
            ):
                tp_nodes = (
                    tp_data.get("active_ptm_nodes", []) +
                    tp_data.get("inhibited_ptm_nodes", []) +
                    tp_data.get("non_ptm_nodes", [])
                )
                tp_edges = tp_data.get("all_edges", [])  # Use all_edges, not just active_edges

                if not tp_nodes:
                    continue

                # Phase 4: Separate isolated for timepoint
                tp_connected, tp_isolated = _separate_isolated_nodes(tp_nodes, tp_edges)

                # Phase 5: Add missing nodes referenced in edges
                tp_node_ids = {n["id"] for n in tp_connected}
                tp_edge_ids = set()
                for e in tp_edges:
                    tp_edge_ids.add(e["source"])
                    tp_edge_ids.add(e["target"])
                tp_missing = tp_edge_ids - tp_node_ids
                for mid in tp_missing:
                    tp_connected.append({
                        "id": mid, "gene": mid, "site": "", "type": "Non-PTM",
                        "value": 0, "state": _classify_state(0, "Non-PTM"), "label": mid,
                    })

                if not tp_connected:
                    tp_connected = tp_nodes

                tp_nodes_df = pd.DataFrame(tp_connected)
                tp_edges_df = pd.DataFrame(tp_edges) if tp_edges else None

                safe_tp = tp.replace(" ", "_").replace("/", "_")
                tp_net_name = f"PTM_Network_{safe_tp}"
                try:
                    tp_suid = p4c.create_network_from_data_frames(
                        nodes=tp_nodes_df,
                        edges=tp_edges_df,
                        title=tp_net_name,
                        collection="PTM_Networks_Temporal",
                    )
                    _apply_visual_style(p4c, tp_suid, tp_net_name, tp_connected)
                    time.sleep(1)
                    tp_png = _save_network_png(p4c, tp_suid, tp_net_name, str(output_path))
                    if tp_png:
                        _auto_crop_image(tp_png)
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
                    cond_nodes = [n for n in connected_nodes if n.get("gene") in cond_ptm_genes or n.get("id") in cond_ptm_genes]
                    if not cond_nodes:
                        continue

                    cond_node_ids = {n["id"] for n in cond_nodes}
                    cond_edges = [
                        e for e in edges
                        if e["source"] in cond_node_ids or e["target"] in cond_node_ids
                    ]
                    # Include Non-PTM nodes referenced in condition edges
                    cond_edge_ids = set()
                    for e in cond_edges:
                        cond_edge_ids.add(e["source"])
                        cond_edge_ids.add(e["target"])
                    for mid in cond_edge_ids - cond_node_ids:
                        matching = [n for n in connected_nodes if n["id"] == mid]
                        if matching:
                            cond_nodes.append(matching[0])

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
                            _auto_crop_image(cond_png)
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


# ---------------------------------------------------------------------------
# Phase 2: Visual style (REBUILT)
# ---------------------------------------------------------------------------

def _apply_visual_style(p4c, network_suid: int, network_name: str, nodes: list):
    """Apply publication-quality visual style to Cytoscape network.
    
    Phase 2 REBUILT:
    - Node size range: 40-120px (was 30-100px)
    - Edge line styles: STRING/KEA3=SOLID, KEGG/Shared-Partner=LONG_DASH
    - KEA3 edges: directed arrow heads
    - Label position: below node (was inside)
    - Label font size: 9px (was 11px)
    """
    try:
        style_name = f"PTM_Pub_Style_{network_name}"
        existing = p4c.get_visual_style_names()

        if style_name not in existing:
            p4c.create_visual_style(style_name)

        # ========== NODE STYLING ==========

        # Node color aligned with guide §4.3 / §7.2
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

        # Phase 2: Node size 40-120px (was 30-100px)
        p4c.set_node_size_mapping(
            table_column="value",
            table_column_values=[-5, 0, 5, 15],
            sizes=[40, 50, 80, 120],
            mapping_type="c",
            style_name=style_name,
        )

        # Phase 2: Node label — below node, smaller font
        p4c.set_node_label_mapping(table_column="label", style_name=style_name)
        p4c.set_node_font_size_default(9, style_name=style_name)

        try:
            p4c.set_node_font_face_default("Arial Bold,plain,12", style_name=style_name)
        except Exception:
            pass

        try:
            p4c.set_node_label_color_default("#000000", style_name=style_name)
        except Exception:
            pass

        # Phase 2: Label position — below node
        try:
            p4c.set_node_label_position_default(
                "S,N,c,0.00,5.00",  # South of node, 5px offset
                style_name=style_name,
            )
        except Exception:
            logger.debug("set_node_label_position_default not supported in this py4cytoscape version")

        # Node border
        p4c.set_node_border_width_default(2.0, style_name=style_name)
        p4c.set_node_border_color_default("#333333", style_name=style_name)

        try:
            p4c.set_node_fill_opacity_default(230, style_name=style_name)
        except Exception:
            pass

        # ========== EDGE STYLING ==========

        # Edge colors aligned with guide §4.3
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

        # Phase 2: Edge line style — STRING/KEA3=SOLID, KEGG/Shared-Partner=LONG_DASH
        try:
            p4c.set_edge_line_style_mapping(
                table_column="evidence_type",
                table_column_values=[
                    "STRING", "STRING-DB", "KEA3", "Kinase-Substrate",
                    "BioGRID",
                    "KEGG", "Shared Pathway", "Shared-Partner",
                    "Kinase-Substrate-Predicted",
                    "Shared-Regulator",
                ],
                line_styles=[
                    "SOLID", "SOLID", "SOLID", "SOLID",
                    "SOLID",
                    "LONG_DASH", "LONG_DASH", "LONG_DASH",
                    "DOT",
                    "EQUAL_DASH",
                ],
                mapping_type="d",
                style_name=style_name,
            )
        except Exception:
            pass

        # Phase 2: KEA3 edges — directed arrow heads (Kinase → Substrate)
        try:
            p4c.set_edge_target_arrow_shape_mapping(
                table_column="evidence_type",
                table_column_values=["KEA3", "Kinase-Substrate", "Kinase-Substrate-Predicted"],
                shapes=["ARROW", "ARROW", "ARROW"],
                mapping_type="d",
                style_name=style_name,
            )
        except Exception:
            logger.debug("set_edge_target_arrow_shape_mapping not supported")

        # Edge opacity
        try:
            p4c.set_edge_opacity_default(200, style_name=style_name)
        except Exception:
            pass

        # Apply style
        p4c.set_visual_style(style_name, network=network_suid)

        # ========== LAYOUT (Phase 3) ==========
        _apply_optimized_layout(p4c, network_suid, nodes)

        logger.info(f"Publication-quality visual style applied: {style_name}")

    except Exception as e:
        logger.warning(f"Visual style application failed: {e}")
        try:
            p4c.set_visual_style("default", network=network_suid)
            p4c.layout_network("force-directed", network=network_suid)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Phase 3: Layout optimization (REBUILT)
# ---------------------------------------------------------------------------

def _apply_optimized_layout(p4c, network_suid: int, nodes: list):
    """Apply optimized layout based on network size.
    
    Phase 3 REBUILT:
    - Kamada-Kawai threshold raised to 50 (was 20)
    - Iteration count reduced to 2 (was 5)
    - force-directed-cl overlap removal removed (unstable)
    """
    try:
        node_count = len(nodes)
        edge_count = len(p4c.get_all_edges(network=network_suid))

        logger.info(f"[LAYOUT] Applying layout for {node_count} nodes, {edge_count} edges")

        if edge_count == 0:
            # Truly no edges — circular layout
            p4c.layout_network("circular", network=network_suid)
            logger.info("[LAYOUT] No edges — using circular layout")
        elif node_count <= 50 and edge_count >= node_count:
            # Small well-connected network: Kamada-Kawai (Phase 3: threshold 20→50)
            try:
                p4c.layout_network("kamada-kawai", network=network_suid)
                logger.info("[LAYOUT] Small network — using kamada-kawai")
            except Exception:
                p4c.layout_network("force-directed", network=network_suid)
                logger.info("[LAYOUT] kamada-kawai failed, fallback to force-directed")
        else:
            # Large network: Force-directed with tuned parameters
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
            logger.info("[LAYOUT] Large network — using force-directed")

        # Wait for layout to settle
        time.sleep(2.5)

        # Phase 3: Only 1 additional iteration (was 4)
        if edge_count > 0:
            try:
                p4c.layout_network("force-directed", network=network_suid)
                time.sleep(1.5)
                logger.info("[LAYOUT] Additional force-directed iteration applied")
            except Exception:
                pass

        # Fit content (no force-directed-cl — removed in Phase 3)
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


# ---------------------------------------------------------------------------
# Phase 4: Auto-crop whitespace from network images
# ---------------------------------------------------------------------------

def _auto_crop_image(image_path: str) -> str:
    """Auto-crop whitespace from network image.
    
    Uses PIL to detect content bounding box and crop with 20px padding.
    Returns the same path (modified in-place).
    """
    try:
        from PIL import Image, ImageChops
        img = Image.open(image_path)

        # Create white background for comparison
        bg = Image.new(img.mode, img.size, (255, 255, 255))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()

        if bbox:
            # Add 20px padding around content
            padding = 20
            bbox = (
                max(0, bbox[0] - padding),
                max(0, bbox[1] - padding),
                min(img.width, bbox[2] + padding),
                min(img.height, bbox[3] + padding),
            )
            cropped = img.crop(bbox)
            cropped.save(image_path)
            logger.info(
                f"[CROP] Auto-cropped {image_path}: "
                f"{img.size} → {cropped.size}"
            )
        else:
            logger.debug(f"[CROP] No content detected in {image_path}, skipping crop")

        return image_path
    except ImportError:
        logger.debug("[CROP] PIL not available, skipping auto-crop")
        return image_path
    except Exception as e:
        logger.warning(f"[CROP] Auto-crop failed for {image_path}: {e}")
        return image_path


# ---------------------------------------------------------------------------
# Save network PNG (unchanged from v2.0 — all 3 methods preserved)
# ---------------------------------------------------------------------------

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

                logger.warning("[IMG-SAVE] All CyREST image endpoints failed")
            else:
                logger.warning("[IMG-SAVE] No view SUID available, skipping CyREST direct")

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
            logger.info("[IMG-SAVE] HOST_DATA_DIR not set, skipping Method 2")

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
    
    Phase 4: Includes isolated node table when applicable.
    Phase 5: Includes validation summary.
    """
    network_images = network_analysis.get("network_images", {})
    legends = network_analysis.get("legends", {})
    network_data = network_analysis.get("network_data", {})
    timepoint_results = network_analysis.get("timepoint_results", {})
    individual_legends = legends.get("individual_legends", {})
    comparison_legend = legends.get("comparison_legend", "")
    validation = network_analysis.get("validation", {})
    pathway_graph_path = network_analysis.get("pathway_graph_path")
    cascade_diagram_path = network_analysis.get("cascade_diagram_path")
    cascade_diagram_paths = network_analysis.get("cascade_diagram_paths", {})

    logger.info(
        f"[NET-SECTION] generate_network_figure_section called: "
        f"network_images={list(network_images.keys()) if network_images else 'EMPTY'}, "
        f"legends_keys={list(legends.keys()) if legends else 'EMPTY'}, "
        f"has_full_legend={bool(legends.get('full_legend'))}, "
        f"pathway_graph={'OK' if pathway_graph_path else 'NONE'}, "
        f"cascade_per_condition={list(cascade_diagram_paths.keys()) if cascade_diagram_paths else 'NONE'}, "
        f"timepoint_results={list(timepoint_results.keys()) if timepoint_results else 'EMPTY'}, "
        f"validation={{'valid': {validation.get('is_valid', '?')}, "
        f"'orphan': {validation.get('orphan_nodes', '?')}}}"
    )

    has_cascade = cascade_diagram_path or cascade_diagram_paths
    if not network_images and not legends.get("full_legend") and not pathway_graph_path and not has_cascade:
        logger.warning("[NET-SECTION] No network_images, no full_legend, no pathway_graph, no cascade — returning empty")
        return ""

    section = "## Network Visualization\n\n"

    nodes = network_data.get("nodes", [])
    edges = network_data.get("edges", [])

    ptm_nodes = [n for n in nodes if n.get("type") == "PTM"]
    non_ptm_nodes = [n for n in nodes if n.get("type") == "Non-PTM"]
    active_nodes = [n for n in ptm_nodes if n.get("state") in ("high_active", "moderate_active")]
    inhibited_nodes = [n for n in ptm_nodes if n.get("state") in ("inhibited", "low_inhibited")]

    # Phase 5: Network statistics summary
    if validation:
        section += (
            f"**Network Statistics**: {validation.get('total_nodes', 0)} nodes "
            f"({validation.get('ptm_nodes', 0)} PTM, {validation.get('non_ptm_nodes', 0)} Non-PTM), "
            f"{validation.get('total_edges', 0)} edges, "
            f"{validation.get('connected_nodes', 0)} connected nodes"
        )
        if validation.get("orphan_nodes", 0) > 0:
            section += f", {validation['orphan_nodes']} isolated nodes"
        section += "\n\n"

        # Edge type breakdown
        edge_types = validation.get("edge_types", {})
        if edge_types:
            section += "**Edge Distribution**: " + ", ".join(
                f"{et}: {cnt}" for et, cnt in sorted(edge_types.items(), key=lambda x: -x[1])
            ) + "\n\n"

    figure_num = 1
    panel_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # v5.0: Figure 1 = Canonical Pathway Distribution Bar Graph (replaces Combined Network)
    if pathway_graph_path:
        pw_path_obj = Path(pathway_graph_path)
        if pw_path_obj.exists() and pw_path_obj.stat().st_size > 1000:
            pw_img_ref = pw_path_obj.name
            section += f"### Figure {figure_num}. Canonical Pathway Distribution of Activated PTM and Non-PTM Interactor Proteins (Weighted by |Protein_Log2FC|)\n\n"
            section += f"![Canonical Pathway Distribution]({pw_img_ref})\n\n"
            section += (
                f"**Figure Legend:** This bar graph illustrates the cumulative |Protein_Log2FC| score "
                f"of **activated** PTM proteins (red, Log2FC > 0) and Non-PTM interactor proteins (green) "
                f"across canonical signaling pathways identified via KEGG pathway analysis. "
                f"The X-axis represents the cumulative |Log2FC| score (\u03a3|Protein_Log2FC|), which weights "
                f"each protein by its fold-change magnitude rather than counting proteins equally. "
                f"Bar labels show the score followed by protein count in parentheses (n=count). "
                f"Non-PTM proteins are assigned to pathways through interaction-based pathway inheritance "
                f"from their PTM partners (STRING/BioGRID edges). "
                f"Pathways are ranked by total cumulative score, highlighting pathways with the "
                f"strongest combined expression changes.\n\n"
            )
            section += "---\n\n"
            figure_num += 1
            logger.info(f"[NET-SECTION] Pathway distribution graph inserted as Figure {figure_num - 1}")

    # v6.1: Figure 2+ = Signaling Cascade Diagrams (per-condition or combined)
    _cascade_legend_text = (
        "**Figure Legend:** This compartmentalized signaling cascade diagram depicts "
        "the signal transduction flow across cellular compartments (Extracellular Space, "
        "Plasma Membrane, Cytoplasm, Nucleus) for the top 5 canonical pathways ranked by "
        "cumulative |Log2FC| score. Each horizontal lane represents a distinct signaling "
        "pathway, with proteins positioned in their annotated subcellular compartment "
        "(based on UniProt subcellular location and GO Cellular Component annotations). "
        "Protein nodes are color-coded by activation state: "
        "**red circles** = activated PTM proteins (Log2FC > 0), "
        "**blue circles** = inhibited PTM proteins (Log2FC < 0), "
        "**green circles** = upregulated Non-PTM interactors, "
        "**purple circles** = downregulated Non-PTM interactors, "
        "**orange diamonds** = kinases. "
        "Node size is proportional to |Log2FC| magnitude. "
        "Gray arrows indicate the canonical signal flow direction from upstream "
        "receptors/adaptors to downstream effectors/transcription factors. "
        "Fold-change values (Log2FC) are annotated above each node."
    )

    if cascade_diagram_paths:
        # Per-condition cascade diagrams (multi-condition mode)
        cascade_timepoints = network_analysis.get("timepoints", sorted(cascade_diagram_paths.keys()))
        for tp in cascade_timepoints:
            tp_path = cascade_diagram_paths.get(tp)
            if not tp_path:
                continue
            tp_path_obj = Path(tp_path)
            if tp_path_obj.exists() and tp_path_obj.stat().st_size > 1000:
                tp_img_ref = tp_path_obj.name
                section += (
                    f"### Figure {figure_num}. Signal Transduction Pathway Cascade Diagram "
                    f"\u2014 {tp} "
                    f"(Top 5 Canonical Pathways by Cumulative |Log2FC| Score)\n\n"
                )
                section += f"![Signal Transduction Pathway Cascade Diagram \u2014 {tp}]({tp_img_ref})\n\n"
                section += _cascade_legend_text + f" Data shown for condition: **{tp}**.\n\n"
                section += "---\n\n"
                logger.info(f"[NET-SECTION] Per-condition cascade diagram for '{tp}' inserted as Figure {figure_num}")
                figure_num += 1
    elif cascade_diagram_path:
        # Single combined cascade diagram (backward compatible)
        cascade_path_obj = Path(cascade_diagram_path)
        if cascade_path_obj.exists() and cascade_path_obj.stat().st_size > 1000:
            cascade_img_ref = cascade_path_obj.name
            section += (
                f"### Figure {figure_num}. Signal Transduction Pathway Cascade Diagram "
                f"(Top 5 Canonical Pathways by Cumulative |Log2FC| Score)\n\n"
            )
            section += f"![Signal Transduction Pathway Cascade Diagram]({cascade_img_ref})\n\n"
            section += _cascade_legend_text + "\n\n"
            section += "---\n\n"
            figure_num += 1
            logger.info(f"[NET-SECTION] Signaling cascade diagram inserted as Figure {figure_num - 1}")

    # Sort images: skip "main" (replaced by pathway graph), include timepoints
    sorted_labels = []
    # v5.0: Do NOT include "main" network image — replaced by pathway distribution graph
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

        # Figure title (guide §6.1) — v5.0: "main" is excluded from sorted_labels
        phase = _tp_to_phase(label)
        panel = panel_labels[idx] if idx < len(panel_labels) else str(idx + 1)
        display_label = f"PTM-NonPTM Integrated Network at {label} ({phase})"
        fig_title = f"Figure {figure_num}{panel}. {display_label}"

        if img_ref:
            section += f"### {fig_title}\n\n"
            section += f"![{display_label}]({img_ref})\n\n"
        else:
            section += f"### {fig_title}\n\n"
            section += f"*[Network image: {path_obj.name if path_obj else '?'}]*\n\n"

        # Figure legend (guide §6.1) — v5.0: "main" removed, timepoint-only
        section += f"**Figure Legend ({label}):**\n\n"

        if label in individual_legends:
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
                    f"and **{stats.get('total_edge_count', 0)} edges**.\n\n"
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
        # v5.0: "main" label removed from sorted_labels, no fallback needed

        section += "---\n\n"
        figure_num += 1

    # Temporal comparison legend (guide §5.1 row 3)
    if comparison_legend:
        section += comparison_legend + "\n\n---\n\n"

    # Phase 4: Isolated nodes table
    if validation and validation.get("orphan_nodes", 0) > 0:
        orphan_ids = validation.get("orphan_node_ids", [])
        if orphan_ids:
            section += "### Isolated Nodes (No Network Connections)\n\n"
            section += "The following PTM nodes had no interaction edges in the network:\n\n"
            section += "| Node ID | Type |\n|---------|------|\n"
            for oid in orphan_ids[:20]:
                node_type = "PTM" if "-" in oid else "Non-PTM"
                section += f"| {oid} | {node_type} |\n"
            if len(orphan_ids) > 20:
                section += f"| ... | ({len(orphan_ids) - 20} more) |\n"
            section += "\n---\n\n"

    # If no images but legends exist, include text legend
    if not network_images and legends.get("full_legend"):
        full_legend = legends["full_legend"]
        full_legend = re.sub(r'^## ', '### ', full_legend, flags=re.MULTILINE)
        section += full_legend + "\n\n"

    return section
