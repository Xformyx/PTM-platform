"""
Network Node — temporal PTM signaling network analysis + Cytoscape visualization.
Ported from multi_agent_system/agents/network_analyzer.py and ptm_network_automation.py.

Option A: connects to Cytoscape Desktop on the Docker host via host.docker.internal.
Falls back to text-based legend when Cytoscape is unavailable.
"""

import base64
import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CYTOSCAPE_HOST = os.getenv("CYTOSCAPE_HOST", "host.docker.internal")
CYTOSCAPE_PORT = int(os.getenv("CYTOSCAPE_PORT", "1234"))

# Publication-quality node colors (matching original project)
NODE_COLORS = {
    "activated": "#E74C3C",          # Red — high activation
    "moderate_active": "#FF8C00",    # Dark Orange — moderate activation
    "baseline": "#F7DC6F",           # Yellow — baseline
    "inhibited": "#3498DB",          # Blue — inhibited/suppressed
    "kinase_identified": "#27AE60",  # Green — identified kinase
    "kinase_predicted": "#FFFFFF",   # White (hollow) — predicted kinase
    "non_ptm": "#9B59B6",           # Purple — non-PTM interactor
    "missing": "#BDC3C7",           # Gray — missing data
}

# Publication-quality edge colors
EDGE_COLORS = {
    "STRING-DB": "#2CA02C",                  # Green
    "KEGG": "#17BECF",                       # Cyan
    "Literature": "#E377C2",                 # Pink
    "Pathway": "#8C564B",                    # Brown
    "Shared Pathway": "#FF9800",             # Orange
    "Predicted": "#BCBD22",                  # Yellow-green
    "Co-activation": "#7F7F7F",              # Gray
    "Kinase-Substrate": "#9467BD",           # Purple
    "Kinase-Substrate-Predicted": "#D8BFD8", # Light purple
    "Unknown": "#C7C7C7",                    # Light gray
    "default": "#95A5A6",                    # Default gray
}


def _build_network_results_for_writer(parsed_ptms: list, context: dict) -> dict:
    """Build network_results structure for writer_node (ptm_only mode).
    Enables build_structured_protein_data_for_llm to extract protein names and Log2FC values.
    """
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


def run_network_analysis(state: dict) -> dict:
    """Analyze temporal networks and optionally generate Cytoscape images."""
    os.environ["DEFAULT_BASE_URL"] = _cytoscape_base_url()

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
        network_images = _generate_cytoscape_networks(network_data, output_dir, parsed_ptms)
    else:
        logger.info("Cytoscape not available — using text-based legends only")

    if cb:
        cb(65, f"Network analysis complete (Cytoscape: {cytoscape_connected})")

    # Build network_results for writer_node (ptm_only mode) — enables v98 structured data
    network_results = _build_network_results_for_writer(parsed_ptms, state.get("experimental_context", {}))

    return {
        "network_analysis": {
            "network_data": network_data,
            "legends": legends,
            "cytoscape_connected": cytoscape_connected,
            "network_images": network_images,
            "ptm_count": len(parsed_ptms),
        },
        "network_results": network_results,
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
            "label": node_id,
        })
        gene_ptms[ptm["gene"]].append(node_id)

    # Build edges from enrichment data (STRING interactions, shared pathways)
    for ptm_data in enriched_data:
        enr = ptm_data.get("rag_enrichment", {})
        gene = ptm_data.get("gene") or ptm_data.get("Gene.Name", "")
        source_id = f"{gene}-{ptm_data.get('position') or ptm_data.get('PTM_Position', '')}"

        # STRING-DB interaction edges (with confidence score)
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
                        "evidence_type": "STRING-DB",
                        "confidence": confidence,
                        "pathway_str": "",
                    })

        # Shared pathway edges (normalize to strings - pathways can be dicts)
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
                    "evidence_type": "Shared Pathway",
                    "confidence": 0.5,
                    "pathway_str": ", ".join(list(shared)[:2]),
                })

        # Kinase-substrate edges from regulation data
        reg = enr.get("regulation", {})
        upstream = reg.get("upstream_regulators", [])
        for kinase in upstream[:3]:
            kinase_name = kinase if isinstance(kinase, str) else str(kinase)
            if kinase_name in gene_ptms:
                for target_id in gene_ptms[kinase_name]:
                    edges.append({
                        "source": target_id,
                        "target": source_id,
                        "evidence_type": "Kinase-Substrate",
                        "confidence": 0.8,
                        "pathway_str": "",
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
        return "activated"
    elif value > 0:
        return "moderate_active"
    elif value > -1:
        return "baseline"
    else:
        return "inhibited"


# ---------------------------------------------------------------------------
# Legend generation (always available, no Cytoscape needed)
# ---------------------------------------------------------------------------

def _generate_legends(network_data: dict, ptms: list) -> dict:
    """Generate text-based figure legends for the network."""
    nodes = network_data["nodes"]
    edges = network_data["edges"]

    active = [n for n in nodes if n["state"] in ("activated", "moderate_active")]
    suppressed = [n for n in nodes if n["state"] == "inhibited"]

    legend_lines = [
        "### PTM Signaling Network Legend\n",
        f"**Total PTM nodes**: {len(nodes)}",
        f"**Active PTMs** (Log2FC > 0): {len(active)}",
        f"**Suppressed PTMs** (Log2FC < -1): {len(suppressed)}",
        f"**Total edges**: {len(edges)}",
        "",
        "**Node Colors**:",
        f"- Red ({NODE_COLORS['activated']}): High activation (Log2FC > 1)",
        f"- Orange ({NODE_COLORS['moderate_active']}): Moderate activation (0 < Log2FC <= 1)",
        f"- Yellow ({NODE_COLORS['baseline']}): Baseline (-1 <= Log2FC <= 0)",
        f"- Blue ({NODE_COLORS['inhibited']}): Inhibited (Log2FC < -1)",
        "",
        "**Node Shapes**:",
        "- Circle (ELLIPSE): PTM sites",
        "- Diamond: Kinases (upstream regulators)",
        "- Rounded Rectangle: Non-PTM interactors",
        "- Hexagon: Pathway members",
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

    if suppressed:
        legend_lines.append("\n**Key Inhibited PTMs**:")
        for n in sorted(suppressed, key=lambda x: x["value"])[:5]:
            legend_lines.append(f"- {n['id']}: Log2FC = {n['value']}")

    return {
        "full_legend": "\n".join(legend_lines),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


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

    # Fallback: if py4cytoscape ping fails (e.g. version check), try simple HTTP
    if _check_cytoscape_http(base_url):
        logger.info("Cytoscape reachable via HTTP; py4cytoscape ping failed (may be version mismatch)")
        return True

    logger.info(
        f"Cytoscape not reachable at {base_url} — ensure Cytoscape Desktop is running with CyREST on port {CYTOSCAPE_PORT}"
    )
    return False


def _generate_cytoscape_networks(
    network_data: dict, output_dir: str, parsed_ptms: list = None
) -> Dict[str, str]:
    """Generate Cytoscape network visualization and export as PNG.
    
    Creates a single comprehensive network with all PTM nodes and edges,
    applying publication-quality visual styling.
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
        # --- Main network ---
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

        # --- Condition-specific sub-networks (if multiple conditions) ---
        if parsed_ptms:
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

    return network_images


def _apply_visual_style(p4c, network_suid: int, network_name: str, nodes: list):
    """Apply publication-quality visual style to Cytoscape network.
    
    Matches the original project's visual styling:
    - Node colors by activation state
    - Node shapes by type (PTM=Circle, Kinase=Diamond, Interactor=RoundRect, Pathway-Member=Hexagon)
    - Node size scaled by |Log2FC| magnitude
    - Edge colors by evidence type
    - Edge width by confidence score
    - Optimized force-directed layout with overlap removal
    """
    try:
        style_name = f"PTM_Pub_Style_{network_name}"
        existing = p4c.get_visual_style_names()

        if style_name not in existing:
            p4c.create_visual_style(style_name)

        # ========== NODE STYLING ==========

        # Node color (state-based) — publication-quality palette
        pub_node_colors = {
            "activated": "#E74C3C",          # Red
            "moderate_active": "#FF8C00",    # Dark Orange
            "baseline": "#F7DC6F",           # Yellow
            "inhibited": "#3498DB",          # Blue
            "kinase_identified": "#27AE60",  # Green (Identified)
            "kinase_predicted": "#FFFFFF",   # White (hollow) (Predicted)
            "non_ptm": "#9B59B6",           # Purple
            "missing": "#BDC3C7",           # Gray
        }
        p4c.set_node_color_mapping(
            table_column="state",
            table_column_values=list(pub_node_colors.keys()),
            colors=list(pub_node_colors.values()),
            mapping_type="d",
            style_name=style_name,
        )

        # Node shape (type-based) — including Kinase, Interactor, Pathway-Member
        p4c.set_node_shape_mapping(
            table_column="type",
            table_column_values=["PTM", "Non-PTM", "Kinase", "Interactor", "Pathway-Member"],
            shapes=["ELLIPSE", "ROUND_RECTANGLE", "DIAMOND", "ROUND_RECTANGLE", "HEXAGON"],
            style_name=style_name,
        )

        # Kinase node border styling for hollow effect
        try:
            p4c.set_node_border_width_mapping(
                table_column="state",
                table_column_values=["kinase_identified", "kinase_predicted"],
                widths=[2.5, 4.0],
                mapping_type="d",
                style_name=style_name,
            )
        except Exception:
            pass

        # Node size (value-based) — 10-step mapping for both positive and negative values
        p4c.set_node_size_mapping(
            table_column="value",
            table_column_values=[-3, -1.5, -0.5, 0, 0.5, 1.5, 3, 5, 10, 20],
            sizes=[80, 60, 45, 35, 45, 60, 80, 90, 100, 120],
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

        # Node border — thicker for publication
        p4c.set_node_border_width_default(2.5, style_name=style_name)
        p4c.set_node_border_color_default("#333333", style_name=style_name)

        try:
            p4c.set_node_fill_opacity_default(230, style_name=style_name)
        except Exception:
            pass

        # ========== EDGE STYLING ==========

        pub_edge_colors = {
            "STRING-DB": "#2CA02C",
            "KEGG": "#17BECF",
            "Literature": "#E377C2",
            "Pathway": "#8C564B",
            "Shared Pathway": "#FF9800",
            "Predicted": "#BCBD22",
            "Co-activation": "#7F7F7F",
            "Kinase-Substrate": "#9467BD",
            "Kinase-Substrate-Predicted": "#D8BFD8",
            "Unknown": "#C7C7C7",
        }
        p4c.set_edge_color_mapping(
            table_column="evidence_type",
            table_column_values=list(pub_edge_colors.keys()),
            colors=list(pub_edge_colors.values()),
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
                table_column_values=["Kinase-Substrate", "Kinase-Substrate-Predicted"],
                line_styles=["LONG_DASH", "DOT"],
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
        # Fallback
        try:
            p4c.set_visual_style("default", network=network_suid)
            p4c.layout_network("force-directed", network=network_suid)
        except Exception:
            pass


def _apply_optimized_layout(p4c, network_suid: int, nodes: list):
    """Apply optimized layout based on network size.
    
    Small dense networks use Kamada-Kawai, larger networks use force-directed
    with optimized parameters for maximum node separation.
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
            # Force-directed with optimized parameters for better node separation
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

        # Fit content with padding
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
    Falls back to export_image if direct download fails.
    """
    try:
        import requests as _requests

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        png_file = output_path / f"{network_name}.png"

        # Delete existing file
        if png_file.exists():
            try:
                png_file.unlink()
            except Exception as del_err:
                logger.warning(f"Could not delete existing file: {del_err}")

        p4c.fit_content(network=network_suid)
        time.sleep(0.5)

        # --- Method 1: CyREST direct image download (Docker-safe) ---
        base_url = _cytoscape_base_url()
        try:
            # Get first view SUID
            views_resp = _requests.get(
                f"{base_url}/networks/{network_suid}/views",
                timeout=10,
            )
            if views_resp.status_code == 200:
                views = views_resp.json()
                view_suid = views[0] if views else None
            else:
                view_suid = None

            if view_suid is not None:
                img_resp = _requests.get(
                    f"{base_url}/networks/{network_suid}/views/{view_suid}/export/png"
                    f"?h=2400",
                    timeout=60,
                )
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    with open(png_file, "wb") as f:
                        f.write(img_resp.content)
                    logger.info(
                        f"Network PNG saved via CyREST direct: {png_file} "
                        f"({len(img_resp.content):,} bytes)"
                    )
                    return str(png_file)
                else:
                    logger.warning(
                        f"CyREST image download returned status={img_resp.status_code}, "
                        f"size={len(img_resp.content) if img_resp.content else 0}"
                    )
        except Exception as direct_err:
            logger.warning(f"CyREST direct download failed: {direct_err}")

        # --- Method 2: Fallback to export_image with host path mapping ---
        host_data_dir = os.getenv("HOST_DATA_DIR", "")
        if host_data_dir:
            order_dir_name = Path(output_dir).name
            host_png = Path(host_data_dir) / "outputs" / order_dir_name / f"{network_name}.png"
            host_png.parent.mkdir(parents=True, exist_ok=True)
            try:
                p4c.export_image(
                    filename=str(host_png),
                    type="PNG",
                    resolution=300,
                    network=network_suid,
                    overwrite_file=True,
                )
                time.sleep(1.5)
                if png_file.exists() and png_file.stat().st_size > 1000:
                    logger.info(f"Network PNG saved via host path mapping: {png_file}")
                    return str(png_file)
            except Exception as host_err:
                logger.warning(f"Host path export failed: {host_err}")

        # --- Method 3: Last resort - try original export_image ---
        try:
            p4c.export_image(
                filename=str(png_file),
                type="PNG",
                resolution=300,
                network=network_suid,
                overwrite_file=True,
            )
            time.sleep(1.5)
            if png_file.exists() and png_file.stat().st_size > 1000:
                logger.info(f"Network PNG saved via export_image: {png_file}")
                return str(png_file)
        except Exception as fallback_err:
            logger.warning(f"export_image fallback failed: {fallback_err}")

        logger.warning(f"All PNG export methods failed for {network_name}")
        return None

    except Exception as e:
        logger.warning(f"PNG export failed: {e}")
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


def generate_network_figure_section(network_analysis: dict) -> str:
    """Generate Markdown section with embedded network figures and legends.
    
    Creates Base64-embedded images in Markdown for each network image,
    with detailed figure legends including node/edge statistics.
    """
    network_images = network_analysis.get("network_images", {})
    legends = network_analysis.get("legends", {})
    network_data = network_analysis.get("network_data", {})

    if not network_images and not legends.get("full_legend"):
        return ""

    section = "## Network Visualization\n\n"

    nodes = network_data.get("nodes", [])
    edges = network_data.get("edges", [])

    active_nodes = [n for n in nodes if n.get("state") in ("activated", "moderate_active")]
    inhibited_nodes = [n for n in nodes if n.get("state") == "inhibited"]

    figure_num = 1
    for label, img_path in sorted(network_images.items()):
        path_obj = Path(img_path) if img_path else None
        # Use relative filename for Markdown (works in both browser and docx conversion)
        # The image file is in the same output directory as final_report.md
        if path_obj and path_obj.exists() and path_obj.stat().st_size > 1000:
            img_ref = path_obj.name  # relative filename (e.g., "PTM_Signaling_Network.png")
        else:
            # Fallback: base64 inline embedding
            base64_img = image_to_base64(img_path) if img_path else None
            img_ref = base64_img

        display_label = "Combined PTM Signaling Network" if label == "main" else f"PTM Network — {label}"

        if img_ref:
            section += f"### Figure {figure_num}: {display_label}\n\n"
            section += f"![{display_label}]({img_ref})\n\n"
        else:
            section += f"### Figure {figure_num}: {display_label}\n\n"
            section += f"*[Network image: {path_obj.name if path_obj else '?'}]*\n\n"

        # Figure legend
        section += f"**Figure {figure_num} Legend:**\n\n"
        section += (
            f"This network represents the PTM signaling interactions. "
            f"The network contains **{len(active_nodes)} activated PTMs** (red/orange nodes), "
            f"**{len(inhibited_nodes)} inhibited PTMs** (blue nodes), "
            f"and **{len(edges)} interaction edges**.\n\n"
        )

        # Top activated PTMs
        if active_nodes:
            top_active = sorted(active_nodes, key=lambda x: -x.get("value", 0))[:5]
            top_str = "; ".join(
                f"{n.get('gene', '?')}({n.get('site', '')}): Log2FC={n.get('value', 0):.2f}"
                for n in top_active
            )
            section += f"**Top Activated PTMs**: {top_str}\n\n"

        # Top inhibited PTMs
        if inhibited_nodes:
            top_inhib = sorted(inhibited_nodes, key=lambda x: x.get("value", 0))[:5]
            top_str = "; ".join(
                f"{n.get('gene', '?')}({n.get('site', '')}): Log2FC={n.get('value', 0):.2f}"
                for n in top_inhib
            )
            section += f"**Top Inhibited PTMs**: {top_str}\n\n"

        # Edge type breakdown
        edge_types = defaultdict(int)
        for e in edges:
            edge_types[e.get("evidence_type", "Unknown")] += 1
        if edge_types:
            section += "**Edge Types**: " + ", ".join(
                f"{et} ({cnt})" for et, cnt in sorted(edge_types.items(), key=lambda x: -x[1])
            ) + "\n\n"

        section += "---\n\n"
        figure_num += 1

    # If no images but legends exist, include text legend
    if not network_images and legends.get("full_legend"):
        section += legends["full_legend"] + "\n\n"

    return section
