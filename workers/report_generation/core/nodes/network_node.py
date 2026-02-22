"""
Network Node — temporal PTM signaling network analysis + Cytoscape visualization.
Ported from multi_agent_system/agents/network_analyzer.py and ptm_network_automation.py.

Option A: connects to Cytoscape Desktop on the Docker host via host.docker.internal.
Falls back to text-based legend when Cytoscape is unavailable.
"""

import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CYTOSCAPE_HOST = os.getenv("CYTOSCAPE_HOST", "host.docker.internal")
CYTOSCAPE_PORT = int(os.getenv("CYTOSCAPE_PORT", "1234"))

NODE_COLORS = {
    "high_active": "#E74C3C",
    "moderate_active": "#F39C12",
    "baseline": "#F7DC6F",
    "suppressed": "#3498DB",
    "missing": "#BDC3C7",
    "non_ptm": "#9B59B6",
}

EDGE_COLORS = {
    "STRING-DB": "#2ECC71",
    "KEGG": "#00BCD4",
    "Literature": "#E91E63",
    "Shared Pathway": "#FF9800",
    "default": "#95A5A6",
}

ACTIVE_THRESHOLD = 0.0


def run_network_analysis(state: dict) -> dict:
    """Analyze temporal networks and optionally generate Cytoscape images."""
    cb = state.get("progress_callback")
    if cb:
        cb(55, "Analyzing signaling networks")

    parsed_ptms = state.get("parsed_ptms", [])
    enriched_data = state.get("enriched_ptm_data", [])
    output_dir = state.get("output_dir", "/tmp")

    # Build network data from enriched PTMs
    network_data = _build_network_data(parsed_ptms, enriched_data)

    # Generate legends
    legends = _generate_legends(network_data, parsed_ptms)

    # Attempt Cytoscape visualization (Option A)
    network_images = {}
    cytoscape_connected = False

    if cb:
        cb(60, "Connecting to Cytoscape Desktop")

    if _check_cytoscape():
        cytoscape_connected = True
        logger.info("Cytoscape Desktop connected via host.docker.internal")
        if cb:
            cb(62, "Generating Cytoscape network images")
        network_images = _generate_cytoscape_networks(network_data, output_dir)
    else:
        logger.info("Cytoscape not available — using text-based legends only")

    if cb:
        cb(65, f"Network analysis complete (Cytoscape: {cytoscape_connected})")

    return {
        "network_analysis": {
            "network_data": network_data,
            "legends": legends,
            "cytoscape_connected": cytoscape_connected,
            "network_images": network_images,
            "ptm_count": len(parsed_ptms),
        }
    }


# ---------------------------------------------------------------------------
# Network data construction
# ---------------------------------------------------------------------------

def _build_network_data(parsed_ptms: list, enriched_data: list) -> dict:
    """Build network nodes and edges from enriched PTM data."""
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
        })
        gene_ptms[ptm["gene"]].append(node_id)

    # Build edges from enrichment data (STRING interactions, shared pathways)
    for ptm_data in enriched_data:
        enr = ptm_data.get("rag_enrichment", {})
        gene = ptm_data.get("gene") or ptm_data.get("Gene.Name", "")
        source_id = f"{gene}-{ptm_data.get('position') or ptm_data.get('PTM_Position', '')}"

        # STRING-DB interaction edges
        for interaction in enr.get("string_interactions", [])[:3]:
            partner = interaction.split("(")[0].strip() if "(" in interaction else interaction
            if partner in gene_ptms:
                for target_id in gene_ptms[partner]:
                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "evidence_type": "STRING-DB",
                        "confidence": 0.7,
                        "pathway_str": "",
                    })

        # Shared pathway edges
        pathways = enr.get("pathways", [])
        for other_data in enriched_data:
            other_gene = other_data.get("gene") or other_data.get("Gene.Name", "")
            if other_gene == gene:
                continue
            other_enr = other_data.get("rag_enrichment", {})
            shared = set(pathways) & set(other_enr.get("pathways", []))
            if shared:
                other_id = f"{other_gene}-{other_data.get('position') or other_data.get('PTM_Position', '')}"
                edges.append({
                    "source": source_id,
                    "target": other_id,
                    "evidence_type": "Shared Pathway",
                    "confidence": 0.5,
                    "pathway_str": ", ".join(list(shared)[:2]),
                })

    # Deduplicate edges
    seen = set()
    unique_edges = []
    for e in edges:
        key = tuple(sorted([e["source"], e["target"]])) + (e["evidence_type"],)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    return {"nodes": nodes, "edges": unique_edges}


def _classify_state(value: float) -> str:
    if value > 1:
        return "high_active"
    elif value > 0:
        return "moderate_active"
    elif value > -1:
        return "baseline"
    else:
        return "suppressed"


# ---------------------------------------------------------------------------
# Legend generation (always available, no Cytoscape needed)
# ---------------------------------------------------------------------------

def _generate_legends(network_data: dict, ptms: list) -> dict:
    """Generate text-based figure legends for the network."""
    nodes = network_data["nodes"]
    edges = network_data["edges"]

    active = [n for n in nodes if n["state"] in ("high_active", "moderate_active")]
    suppressed = [n for n in nodes if n["state"] == "suppressed"]

    legend_lines = [
        "### PTM Signaling Network Legend\n",
        f"**Total PTM nodes**: {len(nodes)}",
        f"**Active PTMs** (Log2FC > 0): {len(active)}",
        f"**Suppressed PTMs** (Log2FC < -1): {len(suppressed)}",
        f"**Total edges**: {len(edges)}",
        "",
        "**Node Colors**:",
        f"- Red ({NODE_COLORS['high_active']}): High activation (Log2FC > 1)",
        f"- Orange ({NODE_COLORS['moderate_active']}): Moderate activation (0 < Log2FC ≤ 1)",
        f"- Yellow ({NODE_COLORS['baseline']}): Baseline (-1 ≤ Log2FC ≤ 0)",
        f"- Blue ({NODE_COLORS['suppressed']}): Suppressed (Log2FC < -1)",
        "",
        "**Edge Types**:",
    ]
    evidence_types = defaultdict(int)
    for e in edges:
        evidence_types[e["evidence_type"]] += 1
    for et, cnt in evidence_types.items():
        color = EDGE_COLORS.get(et, EDGE_COLORS["default"])
        legend_lines.append(f"- {et} ({color}): {cnt} connections")

    if active:
        legend_lines.append("\n**Key Active PTMs**:")
        for n in sorted(active, key=lambda x: -x["value"])[:10]:
            legend_lines.append(f"- {n['id']}: Log2FC = {n['value']}")

    return {
        "full_legend": "\n".join(legend_lines),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


# ---------------------------------------------------------------------------
# Cytoscape integration (Option A: host.docker.internal)
# ---------------------------------------------------------------------------

def _check_cytoscape() -> bool:
    """Check if Cytoscape Desktop is accessible."""
    try:
        import py4cytoscape as p4c
        p4c.cyrest.CyRestClient(base_url=f"http://{CYTOSCAPE_HOST}:{CYTOSCAPE_PORT}/v1")
        os.environ["DEFAULT_BASE_URL"] = f"http://{CYTOSCAPE_HOST}:{CYTOSCAPE_PORT}/v1"
        p4c.cytoscape_ping()
        return True
    except Exception as e:
        logger.info(f"Cytoscape not reachable: {e}")
        return False


def _generate_cytoscape_networks(network_data: dict, output_dir: str) -> Dict[str, str]:
    """Generate Cytoscape network visualization and export as PNG."""
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

    try:
        nodes_df = pd.DataFrame(nodes)
        edges_df = pd.DataFrame(edges) if edges else pd.DataFrame(columns=["source", "target"])

        network_name = "PTM_Signaling_Network"
        network_suid = p4c.create_network_from_data_frames(
            nodes=nodes_df,
            edges=edges_df,
            title=network_name,
            collection="PTM Analysis",
        )
        logger.info(f"Cytoscape network created: {network_name} (SUID: {network_suid})")

        _apply_visual_style(network_suid, network_name)
        time.sleep(1)

        png_path = _save_network_png(network_suid, network_name, str(output_path))
        if png_path:
            return {"main": png_path}

    except Exception as e:
        logger.error(f"Cytoscape network generation failed: {e}")

    return {}


def _apply_visual_style(network_suid: int, network_name: str):
    """Apply publication-quality visual style to Cytoscape network."""
    try:
        import py4cytoscape as p4c

        style_name = "PTM_Analysis_Style"
        existing = p4c.get_visual_style_names()

        if style_name not in existing:
            p4c.create_visual_style(style_name)

            p4c.set_node_color_mapping(
                table_column="state",
                table_column_values=list(NODE_COLORS.keys()),
                colors=list(NODE_COLORS.values()),
                mapping_type="d",
                style_name=style_name,
            )

            p4c.set_node_shape_mapping(
                table_column="type",
                table_column_values=["PTM", "Non-PTM"],
                shapes=["ELLIPSE", "DIAMOND"],
                style_name=style_name,
            )

            p4c.set_node_size_mapping(
                table_column="value",
                table_column_values=[-5, 0, 5, 15],
                sizes=[30, 40, 60, 100],
                mapping_type="c",
                style_name=style_name,
            )

            p4c.set_node_label_mapping(table_column="id", style_name=style_name)

            p4c.set_edge_color_mapping(
                table_column="evidence_type",
                table_column_values=list(EDGE_COLORS.keys()),
                colors=list(EDGE_COLORS.values()),
                mapping_type="d",
                style_name=style_name,
            )

            p4c.set_edge_line_width_default(2.5, style_name=style_name)

        p4c.set_visual_style(style_name, network=network_suid)
        p4c.layout_network("force-directed", network=network_suid)
        logger.info(f"Visual style applied: {style_name}")

    except Exception as e:
        logger.warning(f"Visual style application failed: {e}")


def _save_network_png(network_suid: int, network_name: str, output_dir: str) -> Optional[str]:
    """Export network as 300dpi PNG."""
    try:
        import py4cytoscape as p4c

        png_file = str(Path(output_dir) / f"{network_name}.png")
        p4c.fit_content(network=network_suid)
        time.sleep(0.5)
        p4c.export_image(
            filename=png_file,
            type="PNG",
            resolution=300,
            network=network_suid,
            overwrite_file=True,
        )
        logger.info(f"Network PNG saved: {png_file}")
        return png_file

    except Exception as e:
        logger.warning(f"PNG export failed: {e}")
        return None
