"""
Signaling Cascade Diagram — Publication-quality compartmentalized cell signaling visualization.

v6.5 — Content alignment + readability improvements:
  - Returns dict {"path": str, "pathways": list} for content alignment with LLM
  - Subtitle updated to "Key Signaling Pathways by Multi-Factor Analysis"
  - Bold formatting removed from all text (fontweight="normal")
  - Font sizes: gene names 8-11pt, FC values 7-9pt, PTM sites 7pt, pathway names 11pt, compartment labels 13pt
  - Node COLOR: PTM Log2FC (PTM/Kinase) / Protein Log2FC (Non-PTM)
  - Node SIZE: proportional to |PTM Log2FC| magnitude (Cytoscape mapping)
  - Enhanced legend with size scale and color annotation
  - Dynamic node radius scaled to gene name length
  - FC value displayed inside node (lower portion) instead of above
  - PTM site shown as small badge above-right of node
  - Dynamic min_spacing based on actual node radii
  - Max 8 proteins per pathway lane (top by |FC|)
  - Figure width auto-scales with data density (20-32 inches)
  - 5-pass overlap resolution for node positions

v6.2 — Context-aware multi-factor pathway selection:
  - Replaces simple cumulative |FC| TOP5 with multi-factor scoring
  - Factors: FC magnitude, compartment diversity, protein count, network connectivity
  - Template match (PATHWAY_SIGNAL_ORDER) is layout only, not a score prior
  - Production Figure 1 rank is Direct NES; this composite is cascade fallback only

v6.0 — Compartmentalized Signaling Cascade Diagram:
  - Draws a schematic cell cross-section with compartments:
    Extracellular → Plasma Membrane → Cytoplasm → Nucleus
  - Places proteins in their correct cellular compartment based on:
    1. UniProt subcellular_location (from rag_enrichment → localization)
    2. GO Cellular Component (from rag_enrichment → go_terms.cellular_component)
    3. Heuristic fallback based on protein function keywords
  - Proteins colored by activation state:
    PTM: Red (up) / Blue (down) gradient
    Non-PTM: Green (up) / Purple (down) gradient
    Kinase: Orange gradient
  - Signal flow arrows connect proteins in pathway progression order
  - Focuses on top N pathways from Figure 1 (signed Direct NES)
  - Node shape: Circle (PTM/Non-PTM), Diamond (Kinase)
  - Node size proportional to |Log2FC|

Integration: Called from run_network_analysis, output saved as signaling_cascade.png
Inserted as Figure 2 in generate_network_figure_section.
"""

import logging
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compartment classification
# ---------------------------------------------------------------------------

# Keywords for compartment assignment (case-insensitive matching)
COMPARTMENT_KEYWORDS = {
    "extracellular": [
        "extracellular", "secreted", "cell surface", "external side",
        "extracellular region", "extracellular space", "extracellular matrix",
    ],
    "membrane": [
        "plasma membrane", "cell membrane", "membrane", "transmembrane",
        "receptor", "integral component of membrane", "integral to membrane",
        "cell surface", "basolateral", "apical",
    ],
    "cytoplasm": [
        "cytoplasm", "cytosol", "cytoplasmic", "cytoskeletal",
        "endoplasmic reticulum", "golgi", "mitochondri", "lysosom",
        "endosom", "peroxisom", "vesicle",
    ],
    "nucleus": [
        "nucleus", "nuclear", "nucleoplasm", "chromatin", "nucleolus",
        "transcription factor", "histone", "chromosome",
    ],
}

# Known protein families → compartment (heuristic fallback)
PROTEIN_FAMILY_COMPARTMENTS = {
    # Receptors → membrane
    "EGFR": "membrane", "ERBB2": "membrane", "ERBB3": "membrane", "ERBB4": "membrane",
    "FGFR1": "membrane", "FGFR2": "membrane", "FGFR3": "membrane", "FGFR4": "membrane",
    "PDGFRA": "membrane", "PDGFRB": "membrane", "VEGFR1": "membrane", "VEGFR2": "membrane",
    "IGF1R": "membrane", "INSR": "membrane", "MET": "membrane", "KIT": "membrane",
    "TLR2": "membrane", "TLR4": "membrane", "TNFR1": "membrane", "TNFR2": "membrane",
    "NOTCH1": "membrane", "NOTCH2": "membrane", "NOTCH3": "membrane",
    "ITGA1": "membrane", "ITGB1": "membrane", "ITGB3": "membrane",
    "CDH1": "membrane", "CDH2": "membrane",
    # Cytoplasmic kinases
    "MAPK1": "cytoplasm", "MAPK3": "cytoplasm", "MAPK8": "cytoplasm",
    "MAPK14": "cytoplasm", "MAP2K1": "cytoplasm", "MAP2K2": "cytoplasm",
    "MAP3K1": "cytoplasm", "MAP3K7": "cytoplasm",
    "AKT1": "cytoplasm", "AKT2": "cytoplasm", "AKT3": "cytoplasm",
    "PIK3CA": "cytoplasm", "PIK3CB": "cytoplasm", "PIK3R1": "cytoplasm",
    "MTOR": "cytoplasm", "RPS6KB1": "cytoplasm", "RPS6KA1": "cytoplasm",
    "SRC": "cytoplasm", "ABL1": "cytoplasm", "JAK1": "cytoplasm", "JAK2": "cytoplasm",
    "RAF1": "cytoplasm", "BRAF": "cytoplasm", "ARAF": "cytoplasm",
    "CDK1": "cytoplasm", "CDK2": "cytoplasm", "CDK4": "cytoplasm", "CDK6": "cytoplasm",
    "GSK3A": "cytoplasm", "GSK3B": "cytoplasm",
    "CHEK1": "cytoplasm", "CHEK2": "cytoplasm",
    "CSNK2A1": "cytoplasm", "CSNK2B": "cytoplasm",
    "PRKCA": "cytoplasm", "PRKCB": "cytoplasm", "PRKCD": "cytoplasm",
    "CAMK2A": "cytoplasm", "CAMK2B": "cytoplasm",
    "IKK": "cytoplasm", "IKBKB": "cytoplasm", "IKBKG": "cytoplasm",
    # Adaptors → cytoplasm
    "GRB2": "cytoplasm", "SOS1": "cytoplasm", "SHC1": "cytoplasm",
    "GAB1": "cytoplasm", "IRS1": "cytoplasm", "IRS2": "cytoplasm",
    "HRAS": "membrane", "KRAS": "membrane", "NRAS": "membrane",
    # Transcription factors → nucleus
    "TP53": "nucleus", "MYC": "nucleus", "JUN": "nucleus", "FOS": "nucleus",
    "STAT1": "nucleus", "STAT3": "nucleus", "STAT5A": "nucleus", "STAT5B": "nucleus",
    "NFKB1": "nucleus", "RELA": "nucleus", "NFKB2": "nucleus",
    "SP1": "nucleus", "ELK1": "nucleus", "ETS1": "nucleus", "ETS2": "nucleus",
    "FOXO1": "nucleus", "FOXO3": "nucleus",
    "SMAD2": "nucleus", "SMAD3": "nucleus", "SMAD4": "nucleus",
    "HIF1A": "nucleus", "CREB1": "nucleus", "ATF2": "nucleus",
    "CTNNB1": "nucleus", "LEF1": "nucleus", "TCF7": "nucleus",
    "RB1": "nucleus", "E2F1": "nucleus", "E2F2": "nucleus",
    "BRCA1": "nucleus", "BRCA2": "nucleus",
    "HDAC1": "nucleus", "HDAC2": "nucleus", "HDAC3": "nucleus",
    "EP300": "nucleus", "CREBBP": "nucleus",
}

# Canonical pathway signal flow order (upstream → downstream)
# Maps pathway keywords to ordered protein lists
PATHWAY_SIGNAL_ORDER = {
    "MAPK": ["EGFR", "GRB2", "SOS1", "HRAS", "KRAS", "RAF1", "BRAF", "MAP2K1", "MAP2K2", "MAPK1", "MAPK3", "ELK1", "FOS", "JUN", "MYC"],
    "PI3K-Akt": ["IGF1R", "INSR", "IRS1", "PIK3CA", "PIK3R1", "AKT1", "AKT2", "MTOR", "RPS6KB1", "GSK3B", "FOXO1", "FOXO3"],
    "NF-kappa B": ["TLR4", "TNFR1", "IKBKB", "IKBKG", "NFKB1", "RELA"],
    "JAK-STAT": ["EGFR", "JAK1", "JAK2", "STAT1", "STAT3", "STAT5A"],
    "Wnt": ["WNT1", "FZD1", "DVL1", "GSK3B", "CTNNB1", "LEF1", "TCF7", "MYC"],
    "p53": ["ATM", "ATR", "CHEK1", "CHEK2", "TP53", "MDM2", "CDKN1A", "BAX"],
    "Apoptosis": ["TNFR1", "FADD", "CASP8", "CASP3", "CASP9", "BAX", "BCL2", "CYCS"],
    "mTOR": ["PIK3CA", "PIK3R1", "AKT1", "TSC1", "TSC2", "MTOR", "RPS6KB1", "EIF4EBP1", "RPS6"],
    "ErbB": ["EGFR", "ERBB2", "ERBB3", "GRB2", "SHC1", "SOS1", "HRAS", "RAF1", "MAP2K1", "MAPK1", "AKT1"],
    "VEGF": ["VEGFA", "KDR", "PIK3CA", "AKT1", "MAPK1", "SRC", "FAK"],
    "Ras": ["EGFR", "GRB2", "SOS1", "HRAS", "KRAS", "NRAS", "RAF1", "BRAF", "MAP2K1", "MAPK1"],
    "Rap1": ["EGFR", "GRB2", "SOS1", "RAP1A", "RAF1", "BRAF", "MAP2K1", "MAPK1"],
    "HIF-1": ["EGFR", "PIK3CA", "AKT1", "MTOR", "HIF1A", "VEGFA"],
    "FoxO": ["IGF1R", "PIK3CA", "AKT1", "FOXO1", "FOXO3", "CDKN1A"],
    "AMPK": ["PRKAA1", "PRKAA2", "TSC2", "MTOR", "FOXO3", "PPARGC1A"],
    "Calcium": ["EGFR", "PLCG1", "CALM1", "CAMK2A", "CAMK2B", "CREB1"],
    "cAMP": ["GNAS", "ADCY1", "PRKACA", "CREB1", "ATF2"],
    "Toll-like receptor": ["TLR4", "MYD88", "IRAK1", "TRAF6", "IKBKB", "NFKB1", "RELA"],
    "TNF": ["TNF", "TNFR1", "TRADD", "TRAF2", "IKBKB", "NFKB1", "RELA", "CASP8", "CASP3"],
    "Insulin": ["INSR", "IRS1", "PIK3CA", "AKT1", "GSK3B", "FOXO1", "MTOR"],
    "Neurotrophin": ["NTRK1", "NTRK2", "SHC1", "GRB2", "SOS1", "HRAS", "RAF1", "MAP2K1", "MAPK1", "CREB1"],
    "Chemokine": ["CXCR4", "CCR5", "GNB1", "PIK3CA", "AKT1", "MAPK1", "MAPK3"],
    "Cell cycle": ["CDK4", "CDK6", "CDK2", "CDK1", "RB1", "E2F1", "TP53", "CDKN1A"],
    "TGF-beta": ["TGFBR1", "TGFBR2", "SMAD2", "SMAD3", "SMAD4", "CDKN1A"],
}


def _classify_compartment(
    gene: str,
    localization: list,
    go_cc: list,
) -> str:
    """Classify a protein into a cellular compartment.
    
    Priority:
    1. UniProt subcellular_location (localization field)
    2. GO Cellular Component terms
    3. Known protein family heuristic
    4. Default to cytoplasm
    """
    gene_upper = gene.strip().upper()
    
    # Combine all text sources for keyword matching
    all_text = []
    for loc in localization:
        if isinstance(loc, str):
            all_text.append(loc.lower())
        elif isinstance(loc, dict):
            all_text.append(str(loc.get("location", "")).lower())
            all_text.append(str(loc.get("topology", "")).lower())
    for cc in go_cc:
        if isinstance(cc, str):
            all_text.append(cc.lower())
        elif isinstance(cc, dict):
            all_text.append(str(cc.get("term", "")).lower())
            all_text.append(str(cc.get("name", "")).lower())
    
    combined = " ".join(all_text)
    
    if combined:
        # Score each compartment by keyword matches
        comp_scores = {"extracellular": 0, "membrane": 0, "cytoplasm": 0, "nucleus": 0}
        for comp, keywords in COMPARTMENT_KEYWORDS.items():
            for kw in keywords:
                if kw in combined:
                    comp_scores[comp] += 1
        
        # If both cytoplasm and nucleus match, prefer cytoplasm for signaling proteins
        # (many kinases/adaptors shuttle between compartments but primarily function in cytoplasm)
        if comp_scores["cytoplasm"] > 0 and comp_scores["nucleus"] > 0:
            # Prefer cytoplasm unless nucleus has significantly more matches
            if comp_scores["nucleus"] <= comp_scores["cytoplasm"] + 1:
                return "cytoplasm"
            return "nucleus"
        
        # Otherwise, return the highest-scoring compartment
        best_comp = max(comp_scores, key=comp_scores.get)
        if comp_scores[best_comp] > 0:
            return best_comp    
    # Heuristic fallback: known protein families
    if gene_upper in PROTEIN_FAMILY_COMPARTMENTS:
        return PROTEIN_FAMILY_COMPARTMENTS[gene_upper]
    
    # Default: cytoplasm (most common for signaling proteins)
    return "cytoplasm"


def _get_cascade_node_color(fc_value: float, node_type: str) -> str:
    """Get node fill color based on fold change and type.
    
    Same color scheme as Cytoscape network:
    - PTM: Red (up) / Blue (down)
    - Non-PTM: Green (up) / Purple (down)
    - Kinase: Orange gradient
    """
    try:
        fc = float(fc_value) if fc_value is not None else 0.0
    except (TypeError, ValueError):
        fc = 0.0
    
    if node_type == "Kinase":
        if fc > 0.5:
            return "#E65100"  # Deep Orange
        elif fc < -0.5:
            return "#FFB74D"  # Light Orange
        return "#FF8F00"      # Amber
    
    if node_type == "Non-PTM":
        if fc > 1.5:
            return "#1B5E20"  # Dark Green
        elif fc > 0.5:
            return "#43A047"  # Green
        elif fc > 0.1:
            return "#A5D6A7"  # Light Green
        elif fc < -1.5:
            return "#4A148C"  # Dark Purple
        elif fc < -0.5:
            return "#8E24AA"  # Purple
        elif fc < -0.1:
            return "#CE93D8"  # Light Purple
        return "#9E9E9E"      # Gray
    
    # PTM protein
    if fc > 2.0:
        return "#B71C1C"  # Dark Red
    elif fc > 1.0:
        return "#E53935"  # Red
    elif fc > 0.0:
        return "#EF9A9A"  # Light Red
    elif fc < -2.0:
        return "#0D47A1"  # Dark Blue
    elif fc < -1.0:
        return "#1E88E5"  # Blue
    elif fc < 0.0:
        return "#90CAF9"  # Light Blue
    return "#BDBDBD"      # Gray


def _get_text_color_for_bg(bg_color: str) -> str:
    """Get contrasting text color (black or white) for a given background color."""
    try:
        hex_color = bg_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#FFFFFF" if luminance < 0.5 else "#000000"
    except Exception:
        return "#000000"


def _match_pathway_to_template(pathway_name: str) -> Optional[str]:
    """Match a KEGG pathway name to a known signal order template.
    
    Returns the template key if matched, None otherwise.
    """
    pw_lower = pathway_name.lower()
    for template_key in PATHWAY_SIGNAL_ORDER:
        if template_key.lower() in pw_lower:
            return template_key
    return None


def generate_signaling_cascade_diagram(
    parsed_ptms: list,
    enriched_data: list,
    network_data: dict,
    output_dir: str,
    top_n_pathways: int = 5,
    condition: Optional[str] = None,
) -> Optional[dict]:
    """Generate a publication-quality compartmentalized signaling cascade diagram.
    
    This creates a cell cross-section showing:
    - Cellular compartments (Extracellular, Membrane, Cytoplasm, Nucleus)
    - Proteins placed in their correct compartments
    - Color-coded by activation state (PTM Red/Blue, Non-PTM Green/Purple)
    - Signal flow arrows connecting proteins in pathway order
    
    Focuses on top N pathways. Production rank is Direct NES from Figure 1;
    PATHWAY_SIGNAL_ORDER is arrow layout only.
    
    Args:
        parsed_ptms: List of parsed PTM data
        enriched_data: List of RAG-enriched PTM data with localization info
        network_data: Network nodes and edges from _build_network_data
        output_dir: Directory to save the output image
        top_n_pathways: Number of top pathways to visualize (default: 5)
        condition: Optional condition/timepoint string to filter data.
                   When provided, only PTMs and enriched data matching this
                   condition are used. The output filename and title include
                   the condition label.
    
    Returns:
        Dict with 'path' (str) and 'pathways' (list of str), or None on failure.
        Example: {"path": "/tmp/signaling_cascade_mgAF.png", "pathways": ["MAPK signaling pathway", "PI3K-Akt signaling pathway"]}
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, RegularPolygon
        import matplotlib.patheffects as pe
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available — skipping signaling cascade diagram")
        return None

    cond_label = condition or "combined"
    logger.info(f"[CASCADE] Starting signaling cascade diagram generation (condition={cond_label})")

    # ---- Step 0: Filter data by condition if specified ----
    if condition:
        # Filter parsed_ptms to this condition
        parsed_ptms = [
            p for p in parsed_ptms
            if (p.get("condition") or p.get("Condition", "")).strip() == condition
        ]
        # Filter enriched_data to this condition
        enriched_data = [
            e for e in enriched_data
            if (e.get("Condition") or e.get("condition", "")).strip() == condition
        ]
        logger.info(
            f"[CASCADE] Filtered to condition '{condition}': "
            f"{len(parsed_ptms)} parsed_ptms, {len(enriched_data)} enriched_data"
        )
        if not parsed_ptms and not enriched_data:
            logger.warning(f"[CASCADE] No data for condition '{condition}' — skipping")
            return None

    # ---- Step 1: Collect all proteins with their data ----
    # Build gene → enrichment data lookup
    gene_enrichment: Dict[str, dict] = {}
    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip().upper()
        if gene:
            gene_enrichment[gene] = ptm_data

    # Build gene → FC and type lookup from network nodes
    gene_info: Dict[str, dict] = {}  # gene_upper → {fc, type, site, ...}
    raw_nodes = network_data.get("nodes", {})
    # network_data["nodes"] can be a dict {gene: node_data} or a list of dicts
    if isinstance(raw_nodes, dict):
        node_list = list(raw_nodes.values()) if raw_nodes else []
    else:
        node_list = raw_nodes or []
    for node in node_list:
        if not isinstance(node, dict):
            continue
        gene = (node.get("gene") or node.get("id", "")).strip().upper()
        node_type = node.get("type", "Non-PTM")
        fc = node.get("ptm_log2fc", 0.0) or node.get("value", 0.0) or 0.0
        protein_fc = node.get("protein_log2fc", 0.0) or 0.0
        site = node.get("site", "")
        if gene not in gene_info or abs(fc) > abs(gene_info[gene].get("fc", 0)):
            gene_info[gene] = {
                "fc": fc,
                "protein_log2fc": protein_fc,
                "type": node_type,
                "site": site,
                "gene": node.get("gene", gene),
            }

    # ---- Step 2: Identify top pathways (same logic as pathway distribution) ----
    def _pw_name(p):
        return (p.get("name", str(p)) if isinstance(p, dict) else str(p)).strip()

    # Collect pathway → genes mapping
    pathway_genes: Dict[str, Set[str]] = defaultdict(set)
    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        enr = ptm_data.get("rag_enrichment", {})
        for pw in enr.get("pathways", []):
            pw_n = _pw_name(pw)
            if pw_n:
                pathway_genes[pw_n].add(gene)

    # Add Non-PTM proteins from network edges
    edges = network_data.get("edges", [])
    ptm_genes_set = {g for g, info in gene_info.items() if info["type"] == "PTM"}
    
    # Build PTM gene → pathways mapping
    ptm_pathways: Dict[str, Set[str]] = defaultdict(set)
    for pw_name, genes in pathway_genes.items():
        for g in genes:
            ptm_pathways[g].add(pw_name)

    # Inherit pathways for Non-PTM proteins via edges
    for edge in edges:
        src = edge.get("source", "").strip().upper()
        tgt = edge.get("target", "").strip().upper()
        src_gene = src.split("-")[0] if "-" in src else src
        tgt_gene = tgt.split("-")[0] if "-" in tgt else tgt
        
        if src_gene in ptm_pathways and tgt_gene not in ptm_genes_set:
            for pw in ptm_pathways[src_gene]:
                pathway_genes[pw].add(tgt_gene)
        if tgt_gene in ptm_pathways and src_gene not in ptm_genes_set:
            for pw in ptm_pathways[tgt_gene]:
                pathway_genes[pw].add(src_gene)

    # ---- Context-aware multi-factor pathway scoring (v6.2) ----
    # Instead of simple cumulative |FC|, score pathways by multiple factors:
    #   1. Cumulative |FC| score (expression magnitude)
    #   2. Compartment diversity (pathways spanning multiple compartments are more informative)
    #   3. Template match (pathways matching known signal templates produce better diagrams)
    #   4. Protein count (pathways with more proteins tell a richer story)
    #   5. Network connectivity (pathways with more inter-protein edges are better supported)

    # Pre-compute compartment assignments for all genes
    _temp_compartments: Dict[str, str] = {}
    for pw_genes in pathway_genes.values():
        for g in pw_genes:
            if g not in _temp_compartments:
                enr_data = gene_enrichment.get(g, {})
                enr = enr_data.get("rag_enrichment", {})
                loc = enr.get("localization", [])
                go_cc = enr.get("go_terms", {}).get("cellular_component", [])
                _temp_compartments[g] = _classify_compartment(g, loc, go_cc)

    # Pre-compute edge connectivity per gene pair
    edge_gene_pairs: set = set()
    for edge in edges:
        src = edge.get("source", "").strip().upper().split("-")[0]
        tgt = edge.get("target", "").strip().upper().split("-")[0]
        if src and tgt:
            edge_gene_pairs.add((src, tgt))
            edge_gene_pairs.add((tgt, src))

    pathway_scores = []
    for pw_name, genes in pathway_genes.items():
        if len(genes) < 2:  # At least 2 proteins
            continue

        # Factor 1: Cumulative |FC| score (normalized by gene count to avoid size bias)
        fc_score = sum(abs(gene_info.get(g, {}).get("fc", 0)) for g in genes)

        # Factor 2: Compartment diversity — how many distinct compartments are covered?
        compartments_in_pw = set(_temp_compartments.get(g, "cytoplasm") for g in genes)
        diversity_score = len(compartments_in_pw)  # max 4

        # Template is layout order only. Not a production score prior.
        # docs/graph_aware_pathway_expansion_contract_v1.md §9
        template_key = _match_pathway_to_template(pw_name)

        count_score = math.log2(max(len(genes), 1))

        intra_edges = 0
        gene_list = list(genes)
        for i, g1 in enumerate(gene_list):
            for g2 in gene_list[i+1:]:
                if (g1, g2) in edge_gene_pairs:
                    intra_edges += 1
        connectivity_score = math.log2(max(intra_edges, 1))

        composite = (
            0.35 * fc_score +
            0.20 * (diversity_score / 4.0) * fc_score +
            0.10 * count_score * (fc_score / max(len(genes), 1)) +
            0.15 * connectivity_score * (fc_score / max(len(genes), 1))
        )

        pathway_scores.append((pw_name, composite, genes, {
            "fc_score": fc_score,
            "diversity": diversity_score,
            "template": template_key or "none",
            "gene_count": len(genes),
            "intra_edges": intra_edges,
            "composite": composite,
        }))

    pathway_scores.sort(key=lambda x: -x[1])
    top_pathways = [(name, score, genes) for name, score, genes, _ in pathway_scores[:top_n_pathways]]

    if not top_pathways:
        logger.warning("[CASCADE] No pathways with sufficient proteins — skipping diagram")
        return None

    # Log detailed scoring for top pathways
    for name, score, genes, details in pathway_scores[:top_n_pathways]:
        logger.info(
            f"[CASCADE] Selected: {name} (composite={details['composite']:.2f}, "
            f"fc={details['fc_score']:.2f}, diversity={details['diversity']}/4, "
            f"template={details['template']}, genes={details['gene_count']}, "
            f"edges={details['intra_edges']})"
        )

    logger.info(f"[CASCADE] Top {len(top_pathways)} pathways selected:")
    for pw_name, score, genes in top_pathways:
        logger.info(f"  {pw_name}: score={score:.2f}, genes={len(genes)}")

    # ---- Step 3: Classify compartments for all relevant proteins ----
    # Collect all genes from top pathways
    all_pathway_genes: Set[str] = set()
    for _, _, genes in top_pathways:
        all_pathway_genes.update(genes)

    gene_compartments: Dict[str, str] = {}
    for gene in all_pathway_genes:
        enr_data = gene_enrichment.get(gene, {})
        enr = enr_data.get("rag_enrichment", {})
        localization = enr.get("localization", [])
        go_cc = enr.get("go_terms", {}).get("cellular_component", [])
        gene_compartments[gene] = _classify_compartment(gene, localization, go_cc)

    compartment_counts = defaultdict(int)
    for comp in gene_compartments.values():
        compartment_counts[comp] += 1
    logger.info(f"[CASCADE] Compartment distribution: {dict(compartment_counts)}")

    # ---- Step 4: Build pathway-specific protein chains ----
    # For each top pathway, order proteins by signal flow
    pathway_chains: List[dict] = []
    for pw_name, score, genes in top_pathways:
        template_key = _match_pathway_to_template(pw_name)
        
        if template_key and template_key in PATHWAY_SIGNAL_ORDER:
            # Use known signal order template
            template_order = PATHWAY_SIGNAL_ORDER[template_key]
            ordered_genes = []
            remaining_genes = set(genes)
            
            for tg in template_order:
                tg_upper = tg.upper()
                if tg_upper in remaining_genes:
                    ordered_genes.append(tg_upper)
                    remaining_genes.discard(tg_upper)
            
            # Append remaining genes sorted by compartment order
            compartment_order = {"extracellular": 0, "membrane": 1, "cytoplasm": 2, "nucleus": 3}
            remaining_sorted = sorted(
                remaining_genes,
                key=lambda g: compartment_order.get(gene_compartments.get(g, "cytoplasm"), 2)
            )
            ordered_genes.extend(remaining_sorted)
        else:
            # No template — sort by compartment (upstream → downstream)
            compartment_order = {"extracellular": 0, "membrane": 1, "cytoplasm": 2, "nucleus": 3}
            ordered_genes = sorted(
                genes,
                key=lambda g: compartment_order.get(gene_compartments.get(g, "cytoplasm"), 2)
            )
        
        pathway_chains.append({
            "name": pw_name,
            "score": score,
            "genes": ordered_genes,
            "template": template_key,
        })

    # ---- Step 4b: Limit proteins per pathway for readability ----
    MAX_GENES_PER_PATHWAY = 8
    for chain in pathway_chains:
        if len(chain["genes"]) > MAX_GENES_PER_PATHWAY:
            # Keep top genes by |FC|, preserving signal order
            genes_with_fc = [(g, abs(gene_info.get(g, {}).get("fc", 0))) for g in chain["genes"]]
            # Sort by |FC| descending, keep top N
            top_genes_set = set(
                g for g, _ in sorted(genes_with_fc, key=lambda x: -x[1])[:MAX_GENES_PER_PATHWAY]
            )
            # Preserve original signal order
            chain["genes"] = [g for g in chain["genes"] if g in top_genes_set]
            logger.info(
                f"[CASCADE] Trimmed '{chain['name']}' to {len(chain['genes'])} genes (from {len(genes_with_fc)})"
            )

    # ---- Step 5: Generate the matplotlib figure ----
    # Dynamic figure dimensions based on data density
    n_pathways = len(pathway_chains)
    max_genes_in_lane = max((len(c["genes"]) for c in pathway_chains), default=5)
    fig_width = max(20, min(32, 12 + max_genes_in_lane * 2.0))
    fig_height = max(12, 5.0 + n_pathways * 2.5)  # Extra height for expanded legend
    
    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.set_aspect("equal")
    ax.axis("off")

    # ---- Draw cellular compartments ----
    # Compartment boundaries (x positions)
    margin_left = 0.8
    margin_right = 0.8
    total_width = fig_width - margin_left - margin_right
    
    # Count proteins per compartment across all pathways for dynamic width allocation
    comp_protein_counts = {"extracellular": 0, "membrane": 0, "cytoplasm": 0, "nucleus": 0}
    for chain in pathway_chains:
        for gene in chain["genes"]:
            comp = gene_compartments.get(gene, "cytoplasm")
            comp_protein_counts[comp] += 1
    
    # Dynamic compartment widths based on protein distribution
    # Minimum widths to ensure labels fit even with 0 proteins
    min_widths = {"extracellular": 1.5, "membrane": 1.5, "cytoplasm": 3.0, "nucleus": 2.0}
    # Per-protein width allocation
    per_protein_width = 2.0
    
    raw_widths = {}
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        raw_widths[comp] = max(min_widths[comp], comp_protein_counts[comp] * per_protein_width)
    
    # Normalize to fit total_width
    raw_total = sum(raw_widths.values())
    comp_widths = {}
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        comp_widths[comp] = (raw_widths[comp] / raw_total) * total_width
    
    logger.info(
        f"[CASCADE] Compartment widths: "
        f"extra={comp_widths['extracellular']:.1f} ({comp_protein_counts['extracellular']}p), "
        f"memb={comp_widths['membrane']:.1f} ({comp_protein_counts['membrane']}p), "
        f"cyto={comp_widths['cytoplasm']:.1f} ({comp_protein_counts['cytoplasm']}p), "
        f"nucl={comp_widths['nucleus']:.1f} ({comp_protein_counts['nucleus']}p)"
    )
    
    comp_x_start = {}
    x_cursor = margin_left
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        comp_x_start[comp] = x_cursor
        x_cursor += comp_widths[comp]

    # Compartment vertical bounds
    comp_y_bottom = 2.0  # Extra space for expanded legend (color + size rows)
    comp_y_top = fig_height - 0.8
    comp_height = comp_y_top - comp_y_bottom

    # Compartment colors (subtle backgrounds)
    comp_colors = {
        "extracellular": "#E3F2FD",  # Very light blue
        "membrane": "#FFF3E0",       # Very light orange
        "cytoplasm": "#F1F8E9",      # Very light green
        "nucleus": "#F3E5F5",        # Very light purple
    }
    
    comp_labels = {
        "extracellular": "Extracellular\nSpace",
        "membrane": "Plasma\nMembrane",
        "cytoplasm": "Cytoplasm",
        "nucleus": "Nucleus",
    }

    # Draw compartment backgrounds
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        rect = FancyBboxPatch(
            (comp_x_start[comp], comp_y_bottom),
            comp_widths[comp], comp_height,
            boxstyle="round,pad=0.05",
            facecolor=comp_colors[comp],
            edgecolor="#90A4AE",
            linewidth=1.5 if comp == "membrane" else 1.0,
            linestyle="-" if comp == "membrane" else "--",
            alpha=0.6,
        )
        ax.add_patch(rect)
        
        # Compartment label at top
        label_x = comp_x_start[comp] + comp_widths[comp] / 2
        label_y = comp_y_top - 0.3
        ax.text(
            label_x, label_y, comp_labels[comp],
            ha="center", va="top",
            fontsize=13, fontweight="normal",
            color="#37474F",
            fontstyle="italic",
            path_effects=[pe.withStroke(linewidth=3, foreground="white")],
        )

    # Draw membrane lines (double line effect)
    membrane_x = comp_x_start["membrane"]
    membrane_w = comp_widths["membrane"]
    for offset in [0, membrane_w]:
        ax.plot(
            [membrane_x + offset, membrane_x + offset],
            [comp_y_bottom, comp_y_top],
            color="#FF9800", linewidth=2.5, alpha=0.4, linestyle="-",
        )

    # ---- Draw pathway lanes and proteins ----
    # Calculate vertical spacing for pathway lanes
    pathway_area_top = comp_y_top - 1.0
    pathway_area_bottom = comp_y_bottom + 0.5
    pathway_area_height = pathway_area_top - pathway_area_bottom
    lane_height = pathway_area_height / max(n_pathways, 1)
    
    # Dynamic node radius based on figure width
    base_node_radius = min(0.50, max(0.35, fig_width / 50))
    
    for pw_idx, chain in enumerate(pathway_chains):
        # Lane center Y
        lane_y = pathway_area_top - (pw_idx + 0.5) * lane_height
        
        # Pathway label on the left
        ax.text(
            margin_left - 0.1, lane_y,
            "",  # We'll put the label differently
            ha="right", va="center",
            fontsize=8, fontweight="normal",
            color="#37474F",
        )
        
        # Truncate pathway name for display
        pw_display = chain["name"]
        if len(pw_display) > 35:
            pw_display = pw_display[:32] + "..."
        
        # Draw pathway name as a subtle background label
        ax.text(
            margin_left + total_width / 2, lane_y + lane_height * 0.38,
            pw_display,
            ha="center", va="bottom",
            fontsize=11, fontweight="normal",
            color="#607D8B",
            alpha=0.7,
            fontstyle="italic",
        )
        
        # Place proteins along the lane
        genes = chain["genes"]
        n_genes = len(genes)
        if n_genes == 0:
            continue
        
        gene_positions = []
        
        # Compute the global x range for signal flow
        flow_x_start = margin_left + 1.0
        flow_x_end = margin_left + total_width - 0.8
        flow_width = flow_x_end - flow_x_start
        
        # Dynamic node radius per gene (based on name length)
        gene_radii = {}
        for gene in genes:
            display_name = gene_info.get(gene, {}).get("gene", gene)
            name_len = len(display_name)
            # Scale radius: short names get smaller nodes, long names get bigger
            r = base_node_radius + max(0, name_len - 4) * 0.03
            r = min(0.60, max(base_node_radius, r))
            gene_radii[gene] = r
        
        # Dynamic min_spacing based on node radii
        avg_radius = sum(gene_radii.values()) / max(len(gene_radii), 1)
        min_spacing = avg_radius * 2 + 0.6  # Generous spacing for labels
        
        for gene_idx, gene in enumerate(genes):
            comp = gene_compartments.get(gene, "cytoplasm")
            
            # Global position based on signal order
            if n_genes == 1:
                global_x = flow_x_start + flow_width / 2
            else:
                global_x = flow_x_start + (gene_idx / (n_genes - 1)) * flow_width
            
            # Constrain within compartment boundaries (with padding)
            r = gene_radii[gene]
            padding = r + 0.3
            comp_left = comp_x_start[comp] + padding
            comp_right = comp_x_start[comp] + comp_widths[comp] - padding
            
            # Clamp to compartment
            x = max(comp_left, min(comp_right, global_x))
            
            gene_positions.append((gene, x, lane_y, comp))
        
        # Enforce minimum spacing between consecutive nodes (multiple passes)
        for pass_num in range(5):
            adjusted = False
            for i in range(1, len(gene_positions)):
                g_prev, x_prev, y_prev, comp_prev = gene_positions[i - 1]
                g_curr, x_curr, y_curr, comp_curr = gene_positions[i]
                
                # Use the max radius of adjacent nodes for spacing
                r_prev = gene_radii.get(g_prev, base_node_radius)
                r_curr = gene_radii.get(g_curr, base_node_radius)
                required_spacing = r_prev + r_curr + 0.6
                
                if abs(x_curr - x_prev) < required_spacing:
                    new_x = x_prev + required_spacing
                    # Allow slight overflow beyond compartment boundary
                    # (better than overlapping nodes)
                    r = gene_radii.get(g_curr, base_node_radius)
                    padding = r + 0.2
                    comp_right = comp_x_start[comp_curr] + comp_widths[comp_curr] - padding
                    # Allow up to 1.0 unit overflow beyond compartment
                    max_x = comp_right + 1.0
                    new_x = min(new_x, max_x)
                    
                    if new_x != x_curr:
                        gene_positions[i] = (g_curr, new_x, y_curr, comp_curr)
                        adjusted = True
            if not adjusted:
                break
        
        # Draw signal flow arrows between consecutive proteins
        for i in range(len(gene_positions) - 1):
            g1, x1, y1, _ = gene_positions[i]
            g2, x2, y2, _ = gene_positions[i + 1]
            
            dx = x2 - x1
            dy = y2 - y1
            dist = math.sqrt(dx**2 + dy**2)
            if dist < 0.01:
                continue
            
            # Shorten arrow using actual node radii
            r1 = gene_radii.get(g1, base_node_radius)
            r2 = gene_radii.get(g2, base_node_radius)
            shrink_start = r1 + 0.10
            shrink_end = r2 + 0.10
            
            if dist <= (shrink_start + shrink_end):
                continue  # Nodes too close, skip arrow
            
            ratio_s = shrink_start / dist
            ratio_e = shrink_end / dist
            
            ax1 = x1 + dx * ratio_s
            ay1 = y1 + dy * ratio_s
            ax2 = x2 - dx * ratio_e
            ay2 = y2 - dy * ratio_e
            
            arrow = FancyArrowPatch(
                (ax1, ay1), (ax2, ay2),
                arrowstyle="->,head_width=6,head_length=5",
                color="#546E7A",
                linewidth=2.0,
                alpha=0.85,
                connectionstyle="arc3,rad=0.0",
                zorder=1,
            )
            ax.add_patch(arrow)
        
        # Draw protein nodes
        for gene, x, y, comp in gene_positions:
            info = gene_info.get(gene, {"fc": 0, "protein_log2fc": 0, "type": "Non-PTM", "site": ""})
            fc = info.get("fc", 0)  # ptm_log2fc
            protein_fc = info.get("protein_log2fc", 0)
            node_type = info.get("type", "Non-PTM")
            site = info.get("site", "")
            
            # Color mapping (Cytoscape-consistent):
            #   PTM nodes: colored by ptm_log2fc (Red/Blue gradient)
            #   Non-PTM nodes: colored by protein_log2fc (Green/Purple gradient)
            #   Kinase nodes: colored by ptm_log2fc (Orange gradient)
            if node_type == "Non-PTM":
                color_fc = protein_fc if protein_fc != 0 else fc
            else:
                color_fc = fc
            fill_color = _get_cascade_node_color(color_fc, node_type)
            text_color = _get_text_color_for_bg(fill_color)
            
            # Size mapping (Cytoscape-consistent):
            #   Based on |ptm_log2fc| (= value column in Cytoscape)
            #   Cytoscape: [-5, 0, 5, 15] → [40px, 50px, 80px, 120px]
            #   Cascade:   |fc| → radius scale factor
            abs_fc = abs(fc)
            if abs_fc >= 15:
                size_scale = 1.5
            elif abs_fc >= 5:
                size_scale = 1.0 + (abs_fc - 5) / 20  # 1.0 → 1.5
            elif abs_fc > 0:
                size_scale = 0.7 + (abs_fc / 5) * 0.3  # 0.7 → 1.0
            else:
                size_scale = 0.7  # neutral / no change
            
            size = gene_radii.get(gene, base_node_radius) * size_scale
            
            if node_type == "Kinase":
                diamond = RegularPolygon(
                    (x, y), numVertices=4, radius=size * 1.1,
                    orientation=0,
                    facecolor=fill_color,
                    edgecolor="#333333",
                    linewidth=1.5,
                    zorder=3,
                )
                ax.add_patch(diamond)
            else:
                circle = Circle(
                    (x, y), radius=size,
                    facecolor=fill_color,
                    edgecolor="#333333",
                    linewidth=1.5,
                    zorder=3,
                )
                ax.add_patch(circle)
            
            # Gene label inside node (upper half)
            display_gene = info.get("gene", gene)
            if len(display_gene) > 8:
                display_gene = display_gene[:7] + "."
            
            # Font size scales with node radius
            gene_fontsize = max(8.0, min(11.0, size * 22))
            
            ax.text(
                x, y + size * 0.12, display_gene,
                ha="center", va="center",
                fontsize=gene_fontsize, fontweight="normal",
                color=text_color,
                zorder=4,
            )
            
            # FC value inside node (lower portion, smaller)
            # Show ptm_log2fc for PTM/Kinase, protein_log2fc for Non-PTM
            display_fc = fc if node_type != "Non-PTM" else (protein_fc if protein_fc != 0 else fc)
            fc_display = f"{display_fc:+.1f}" if display_fc != 0 else ""
            if fc_display:
                fc_fontsize = max(7.0, gene_fontsize - 1.5)
                ax.text(
                    x, y - size * 0.35, fc_display,
                    ha="center", va="center",
                    fontsize=fc_fontsize, color=text_color,
                    fontweight="normal",
                    alpha=0.85,
                    zorder=4,
                )
            
            # PTM site label as small badge above-right of node
            if site and node_type == "PTM":
                badge_x = x + size * 0.7
                badge_y = y + size * 0.7
                # Small background circle for badge
                badge_r = 0.20
                badge_bg = Circle(
                    (badge_x, badge_y), radius=badge_r,
                    facecolor="#FFFFFF", edgecolor="#78909C",
                    linewidth=0.8, zorder=5, alpha=0.9,
                )
                ax.add_patch(badge_bg)
                # Truncate long site labels
                site_display = site if len(site) <= 5 else site[:4] + "."
                ax.text(
                    badge_x, badge_y, site_display,
                    ha="center", va="center",
                    fontsize=7.0, color="#37474F",
                    fontweight="normal",
                    zorder=6,
                )
        
        # Draw thin horizontal lane separator
        if pw_idx < n_pathways - 1:
            sep_y = lane_y - lane_height / 2
            ax.plot(
                [margin_left, margin_left + total_width],
                [sep_y, sep_y],
                color="#CFD8DC", linewidth=0.5, linestyle=":", alpha=0.5,
            )

    # ---- Draw legend ----
    legend_y = comp_y_bottom - 0.05
    legend_x = margin_left + 0.3
    
    # Title
    title_main = "Signal Transduction Pathway Cascade Diagram"
    if condition:
        title_main += f" — {condition}"
    ax.text(
        fig_width / 2, fig_height - 0.35,
        title_main,
        ha="center", va="top",
        fontsize=16, fontweight="normal",
        color="#263238",
    )
    ax.text(
        fig_width / 2, fig_height - 0.7,
        f"Key Signaling Pathways by Multi-Factor Analysis — Compartmentalized Signal Flow",
        ha="center", va="top",
        fontsize=11,
        color="#455A64",
    )

    # Legend items — color legend (Row 1)
    legend_items = [
        ("PTM \u2191", "#E53935", "circle"),
        ("PTM \u2193", "#1E88E5", "circle"),
        ("Non-PTM \u2191", "#43A047", "circle"),
        ("Non-PTM \u2193", "#8E24AA", "circle"),
        ("Kinase", "#FF8F00", "diamond"),
        ("Neutral", "#9E9E9E", "circle"),
    ]
    
    item_spacing = 2.5
    legend_start_x = fig_width / 2 - (len(legend_items) * item_spacing + 2.5) / 2
    
    for i, (label, color, shape) in enumerate(legend_items):
        lx = legend_start_x + i * item_spacing
        ly = legend_y
        
        if shape == "diamond":
            diamond = RegularPolygon(
                (lx, ly), numVertices=4, radius=0.18,
                orientation=0,
                facecolor=color, edgecolor="#333333", linewidth=1,
                zorder=5,
            )
            ax.add_patch(diamond)
        else:
            circle = Circle(
                (lx, ly), radius=0.18,
                facecolor=color, edgecolor="#333333", linewidth=1,
                zorder=5,
            )
            ax.add_patch(circle)
        
        ax.text(
            lx + 0.3, ly, label,
            ha="left", va="center",
            fontsize=10, color="#263238",
            fontweight="normal",
            zorder=5,
        )

    # Arrow legend
    arrow_x = legend_start_x + len(legend_items) * item_spacing
    arrow = FancyArrowPatch(
        (arrow_x, legend_y), (arrow_x + 0.8, legend_y),
        arrowstyle="->,head_width=8,head_length=6",
        color="#546E7A", linewidth=2.5, zorder=5,
    )
    ax.add_patch(arrow)
    ax.text(
        arrow_x + 1.1, legend_y, "Signal flow",
        ha="left", va="center",
        fontsize=10, color="#263238",
        fontweight="normal",
        zorder=5,
    )

    # Size legend (Row 2) — shows node size reflects |Log2FC| magnitude
    size_legend_y = legend_y - 0.7
    size_examples = [
        ("Low |FC|", 0.12, "#BDBDBD"),
        ("Med |FC|", 0.20, "#E53935"),
        ("High |FC|", 0.30, "#B71C1C"),
    ]
    size_start_x = fig_width / 2 - 4.5
    ax.text(
        size_start_x - 1.0, size_legend_y, "Node size \u221d |Log2FC|:",
        ha="left", va="center",
        fontsize=9.5, color="#455A64",
        fontweight="normal",
        zorder=5,
    )
    for j, (slabel, sradius, scolor) in enumerate(size_examples):
        sx = size_start_x + 3.5 + j * 2.5
        sc = Circle(
            (sx, size_legend_y), radius=sradius,
            facecolor=scolor, edgecolor="#333333", linewidth=0.8,
            zorder=5,
        )
        ax.add_patch(sc)
        ax.text(
            sx + sradius + 0.2, size_legend_y, slabel,
            ha="left", va="center",
            fontsize=9, color="#455A64",
            zorder=5,
        )
    # Annotation: Color = PTM Log2FC (PTM) / Protein Log2FC (Non-PTM)
    ax.text(
        fig_width / 2, size_legend_y - 0.5,
        "Color: PTM Log2FC (PTM nodes) / Protein Log2FC (Non-PTM nodes)  \u2022  Size: |PTM Log2FC| magnitude",
        ha="center", va="center",
        fontsize=8.5, color="#78909C",
        fontstyle="italic",
        zorder=5,
    )

    # ---- Save figure ----
    plt.tight_layout(pad=0.5)
    # Use condition-specific filename when condition is provided
    if condition:
        # Sanitize condition string for filename
        safe_cond = condition.replace("/", "_").replace(" ", "_").replace("\\", "_")
        output_path = Path(output_dir) / f"signaling_cascade_{safe_cond}.png"
    else:
        output_path = Path(output_dir) / "signaling_cascade.png"
    fig.savefig(
        str(output_path),
        dpi=250,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    plt.close(fig)

    # Log summary
    total_genes = len(all_pathway_genes)
    selected_pathway_names = [chain["name"] for chain in pathway_chains]
    logger.info(
        f"[CASCADE] Signaling cascade diagram saved: {output_path} "
        f"(condition={cond_label}, {n_pathways} pathways, {total_genes} proteins, "
        f"pathways={selected_pathway_names})"
    )
    return {"path": str(output_path), "pathways": selected_pathway_names}


# ---------------------------------------------------------------------------
# v7.0: Content-driven cascade — accepts pre-selected pathway names
# ---------------------------------------------------------------------------

def generate_cascade_from_selected_pathways(
    selected_pathway_names: List[str],
    parsed_ptms: list,
    enriched_data: list,
    network_data: dict,
    output_dir: str,
    condition: Optional[str] = None,
) -> Optional[dict]:
    """Generate a cascade diagram using externally selected pathways.
    
    This is the content-driven variant called by cascade_mediator_node.
    Instead of scoring pathways internally, it accepts a list of pathway names
    that were extracted from the LLM-written text by the mediator.
    
    It reuses the same rendering engine as generate_signaling_cascade_diagram
    but skips the internal pathway scoring (Steps 2-2b) and instead matches
    the provided pathway names against the available data.
    
    Args:
        selected_pathway_names: List of pathway names to visualize (from mediator)
        parsed_ptms: List of parsed PTM data
        enriched_data: List of RAG-enriched PTM data with localization info
        network_data: Network nodes and edges from _build_network_data
        output_dir: Directory to save the output image
        condition: Optional condition/timepoint string to filter data
    
    Returns:
        Dict with 'path' (str) and 'pathways' (list of str), or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, RegularPolygon
        import matplotlib.patheffects as pe
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available — skipping signaling cascade diagram")
        return None

    cond_label = condition or "combined"
    logger.info(
        f"[CASCADE-MEDIATOR] Starting content-driven cascade diagram "
        f"(condition={cond_label}, requested_pathways={selected_pathway_names})"
    )

    # ---- Step 0: Filter data by condition if specified ----
    if condition:
        parsed_ptms = [
            p for p in parsed_ptms
            if (p.get("condition") or p.get("Condition", "")).strip() == condition
        ]
        enriched_data = [
            e for e in enriched_data
            if (e.get("Condition") or e.get("condition", "")).strip() == condition
        ]
        logger.info(
            f"[CASCADE-MEDIATOR] Filtered to condition '{condition}': "
            f"{len(parsed_ptms)} parsed_ptms, {len(enriched_data)} enriched_data"
        )
        if not parsed_ptms and not enriched_data:
            logger.warning(f"[CASCADE-MEDIATOR] No data for condition '{condition}' — skipping")
            return None

    # ---- Step 1: Collect all proteins with their data (same as original) ----
    gene_enrichment: Dict[str, dict] = {}
    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip().upper()
        if gene:
            gene_enrichment[gene] = ptm_data

    gene_info: Dict[str, dict] = {}
    raw_nodes = network_data.get("nodes", {})
    if isinstance(raw_nodes, dict):
        node_list = list(raw_nodes.values()) if raw_nodes else []
    else:
        node_list = raw_nodes or []
    for node in node_list:
        if not isinstance(node, dict):
            continue
        gene = (node.get("gene") or node.get("id", "")).strip().upper()
        node_type = node.get("type", "Non-PTM")
        fc = node.get("ptm_log2fc", 0.0) or node.get("value", 0.0) or 0.0
        protein_fc = node.get("protein_log2fc", 0.0) or 0.0
        site = node.get("site", "")
        if gene not in gene_info or abs(fc) > abs(gene_info[gene].get("fc", 0)):
            gene_info[gene] = {
                "fc": fc,
                "protein_log2fc": protein_fc,
                "type": node_type,
                "site": site,
                "gene": node.get("gene", gene),
            }

    # ---- Step 2: Build pathway → genes mapping (same as original) ----
    def _pw_name(p):
        return (p.get("name", str(p)) if isinstance(p, dict) else str(p)).strip()

    pathway_genes: Dict[str, Set[str]] = defaultdict(set)
    for ptm_data in enriched_data:
        gene = (ptm_data.get("gene") or ptm_data.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        enr = ptm_data.get("rag_enrichment", {})
        for pw in enr.get("pathways", []):
            pw_n = _pw_name(pw)
            if pw_n:
                pathway_genes[pw_n].add(gene)

    # Add Non-PTM proteins from network edges
    edges = network_data.get("edges", [])
    ptm_genes_set = {g for g, info in gene_info.items() if info["type"] == "PTM"}
    ptm_pathways: Dict[str, Set[str]] = defaultdict(set)
    for pw_name_key, genes in pathway_genes.items():
        for g in genes:
            ptm_pathways[g].add(pw_name_key)
    for edge in edges:
        src = edge.get("source", "").strip().upper()
        tgt = edge.get("target", "").strip().upper()
        src_gene = src.split("-")[0] if "-" in src else src
        tgt_gene = tgt.split("-")[0] if "-" in tgt else tgt
        if src_gene in ptm_pathways and tgt_gene not in ptm_genes_set:
            for pw in ptm_pathways[src_gene]:
                pathway_genes[pw].add(tgt_gene)
        if tgt_gene in ptm_pathways and src_gene not in ptm_genes_set:
            for pw in ptm_pathways[tgt_gene]:
                pathway_genes[pw].add(src_gene)

    # ---- Step 2b: Match selected pathway names to available data ----
    # Fuzzy match: selected names may not exactly match KEGG names
    matched_pathways: List[Tuple[str, float, Set[str]]] = []
    available_pw_lower = {pw.lower(): pw for pw in pathway_genes.keys()}

    for sel_name in selected_pathway_names:
        sel_lower = sel_name.lower()
        best_match = None
        best_score = 0

        for avail_lower, avail_name in available_pw_lower.items():
            # Exact match
            if sel_lower == avail_lower:
                best_match = avail_name
                best_score = 100
                break
            # Substring match
            if sel_lower in avail_lower or avail_lower in sel_lower:
                score = 80
                if score > best_score:
                    best_match = avail_name
                    best_score = score
            # Keyword match (e.g., "MAPK" in "MAPK signaling pathway")
            sel_keywords = set(sel_lower.replace("-", " ").replace("/", " ").split())
            avail_keywords = set(avail_lower.replace("-", " ").replace("/", " ").split())
            common = sel_keywords & avail_keywords - {"signaling", "pathway", "of", "the", "and", "in"}
            if common:
                score = len(common) * 20
                if score > best_score:
                    best_match = avail_name
                    best_score = score

        if best_match and best_match not in [m[0] for m in matched_pathways]:
            genes = pathway_genes[best_match]
            if len(genes) >= 2:
                # Use cumulative |FC| as score for ordering
                fc_score = sum(abs(gene_info.get(g, {}).get("fc", 0)) for g in genes)
                matched_pathways.append((best_match, fc_score, genes))
                logger.info(
                    f"[CASCADE-MEDIATOR] Matched '{sel_name}' → '{best_match}' "
                    f"(score={best_score}, genes={len(genes)}, fc={fc_score:.2f})"
                )
            else:
                logger.info(
                    f"[CASCADE-MEDIATOR] Matched '{sel_name}' → '{best_match}' "
                    f"but only {len(genes)} genes — skipping"
                )
        else:
            logger.info(f"[CASCADE-MEDIATOR] No match for '{sel_name}' in available pathways")

    if not matched_pathways:
        logger.warning("[CASCADE-MEDIATOR] No pathways matched — skipping diagram")
        return None

    # Use matched pathways as top_pathways (same format as original)
    top_pathways = matched_pathways
    logger.info(f"[CASCADE-MEDIATOR] {len(top_pathways)} pathways matched for diagram")

    # ---- From here, reuse the SAME rendering logic as generate_signaling_cascade_diagram ----
    # Step 3: Classify compartments
    all_pathway_genes: Set[str] = set()
    for _, _, genes in top_pathways:
        all_pathway_genes.update(genes)

    gene_compartments: Dict[str, str] = {}
    for gene in all_pathway_genes:
        enr_data = gene_enrichment.get(gene, {})
        enr = enr_data.get("rag_enrichment", {})
        localization = enr.get("localization", [])
        go_cc = enr.get("go_terms", {}).get("cellular_component", [])
        gene_compartments[gene] = _classify_compartment(gene, localization, go_cc)

    compartment_counts = defaultdict(int)
    for comp in gene_compartments.values():
        compartment_counts[comp] += 1
    logger.info(f"[CASCADE-MEDIATOR] Compartment distribution: {dict(compartment_counts)}")

    # Step 4: Build pathway-specific protein chains
    pathway_chains: List[dict] = []
    for pw_name_val, score, genes in top_pathways:
        template_key = _match_pathway_to_template(pw_name_val)
        if template_key and template_key in PATHWAY_SIGNAL_ORDER:
            template_order = PATHWAY_SIGNAL_ORDER[template_key]
            ordered_genes = []
            remaining_genes = set(genes)
            for tg in template_order:
                tg_upper = tg.upper()
                if tg_upper in remaining_genes:
                    ordered_genes.append(tg_upper)
                    remaining_genes.discard(tg_upper)
            compartment_order = {"extracellular": 0, "membrane": 1, "cytoplasm": 2, "nucleus": 3}
            remaining_sorted = sorted(
                remaining_genes,
                key=lambda g: compartment_order.get(gene_compartments.get(g, "cytoplasm"), 2)
            )
            ordered_genes.extend(remaining_sorted)
        else:
            compartment_order = {"extracellular": 0, "membrane": 1, "cytoplasm": 2, "nucleus": 3}
            ordered_genes = sorted(
                genes,
                key=lambda g: compartment_order.get(gene_compartments.get(g, "cytoplasm"), 2)
            )
        pathway_chains.append({
            "name": pw_name_val,
            "score": score,
            "genes": ordered_genes,
            "template": template_key,
        })

    # Step 4b: Limit proteins per pathway
    MAX_GENES_PER_PATHWAY = 8
    for chain in pathway_chains:
        if len(chain["genes"]) > MAX_GENES_PER_PATHWAY:
            genes_with_fc = [(g, abs(gene_info.get(g, {}).get("fc", 0))) for g in chain["genes"]]
            top_genes_set = set(
                g for g, _ in sorted(genes_with_fc, key=lambda x: -x[1])[:MAX_GENES_PER_PATHWAY]
            )
            chain["genes"] = [g for g in chain["genes"] if g in top_genes_set]
            logger.info(
                f"[CASCADE-MEDIATOR] Trimmed '{chain['name']}' to {len(chain['genes'])} genes"
            )

    # ---- Step 5: Generate the matplotlib figure ----
    # (Identical rendering logic as generate_signaling_cascade_diagram from Step 5 onwards)
    n_pathways = len(pathway_chains)
    max_genes_in_lane = max((len(c["genes"]) for c in pathway_chains), default=5)
    fig_width = max(20, min(32, 12 + max_genes_in_lane * 2.0))
    fig_height = max(12, 5.0 + n_pathways * 2.5)

    fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.set_aspect("equal")
    ax.axis("off")

    # ---- Draw cellular compartments ----
    margin_left = 0.8
    margin_right = 0.8
    total_width = fig_width - margin_left - margin_right

    comp_protein_counts = {"extracellular": 0, "membrane": 0, "cytoplasm": 0, "nucleus": 0}
    for chain in pathway_chains:
        for gene in chain["genes"]:
            comp = gene_compartments.get(gene, "cytoplasm")
            comp_protein_counts[comp] += 1

    min_widths = {"extracellular": 1.5, "membrane": 1.5, "cytoplasm": 3.0, "nucleus": 2.0}
    per_protein_width = 2.0
    raw_widths = {}
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        raw_widths[comp] = max(min_widths[comp], comp_protein_counts[comp] * per_protein_width)
    raw_total = sum(raw_widths.values())
    comp_widths = {}
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        comp_widths[comp] = (raw_widths[comp] / raw_total) * total_width

    comp_colors = {
        "extracellular": "#E3F2FD",
        "membrane": "#FFF3E0",
        "cytoplasm": "#F1F8E9",
        "nucleus": "#F3E5F5",
    }
    comp_labels = {
        "extracellular": "Extracellular\nSpace",
        "membrane": "Plasma\nMembrane",
        "cytoplasm": "Cytoplasm",
        "nucleus": "Nucleus",
    }

    # Vertical layout
    comp_y_top = fig_height - 1.2
    comp_y_bottom = 3.5
    comp_height = comp_y_top - comp_y_bottom

    x_cursor = margin_left
    comp_boundaries = {}
    for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
        w = comp_widths[comp]
        rect = mpatches.FancyBboxPatch(
            (x_cursor, comp_y_bottom), w, comp_height,
            boxstyle="round,pad=0.05",
            facecolor=comp_colors[comp],
            edgecolor="#B0BEC5",
            linewidth=1.0,
            alpha=0.6,
            zorder=0,
        )
        ax.add_patch(rect)
        ax.text(
            x_cursor + w / 2, comp_y_top - 0.25,
            comp_labels[comp],
            ha="center", va="top",
            fontsize=13, fontweight="normal",
            color="#37474F",
            zorder=1,
        )
        comp_boundaries[comp] = (x_cursor, x_cursor + w)
        x_cursor += w

    # ---- Place proteins in lanes ----
    lane_height = (comp_height - 1.0) / max(n_pathways, 1)
    node_positions: Dict[str, Tuple[float, float]] = {}
    node_radii: Dict[str, float] = {}

    for lane_idx, chain in enumerate(pathway_chains):
        lane_y = comp_y_top - 0.8 - (lane_idx + 0.5) * lane_height
        pw_label = chain["name"]
        if len(pw_label) > 30:
            pw_label = pw_label[:28] + "..."
        ax.text(
            0.15, lane_y,
            pw_label,
            ha="left", va="center",
            fontsize=11, fontweight="normal",
            color="#455A64",
            rotation=0,
            zorder=2,
        )

        # Group genes by compartment
        comp_gene_groups: Dict[str, List[str]] = defaultdict(list)
        for gene in chain["genes"]:
            comp = gene_compartments.get(gene, "cytoplasm")
            comp_gene_groups[comp].append(gene)

        for comp in ["extracellular", "membrane", "cytoplasm", "nucleus"]:
            genes_in_comp = comp_gene_groups.get(comp, [])
            if not genes_in_comp:
                continue
            x_start, x_end = comp_boundaries[comp]
            comp_w = x_end - x_start
            n_genes = len(genes_in_comp)
            spacing = comp_w / (n_genes + 1)

            for gi, gene in enumerate(genes_in_comp):
                x = x_start + spacing * (gi + 1)
                y = lane_y
                info = gene_info.get(gene, {})
                fc = info.get("fc", 0)
                node_type = info.get("type", "Non-PTM")
                site = info.get("site", "")

                # Dynamic radius based on gene name length
                name_len = len(gene)
                base_radius = max(0.35, min(0.55, 0.30 + name_len * 0.03))
                fc_scale = min(abs(fc) / 3.0, 1.0) if fc else 0.3
                radius = base_radius * (0.8 + 0.4 * fc_scale)
                node_radii[gene] = radius

                bg_color = _get_cascade_node_color(fc, node_type)
                text_color = _get_text_color_for_bg(bg_color)

                if node_type == "Kinase":
                    diamond = RegularPolygon(
                        (x, y), numVertices=4, radius=radius * 1.2,
                        orientation=0,
                        facecolor=bg_color, edgecolor="#424242",
                        linewidth=1.2, zorder=3,
                    )
                    ax.add_patch(diamond)
                else:
                    circle = plt.Circle(
                        (x, y), radius,
                        facecolor=bg_color, edgecolor="#424242",
                        linewidth=1.0, zorder=3,
                    )
                    ax.add_patch(circle)

                # Gene name
                gene_fontsize = max(7, min(11, 12 - name_len * 0.4))
                ax.text(
                    x, y + radius * 0.15,
                    gene,
                    ha="center", va="center",
                    fontsize=gene_fontsize, fontweight="normal",
                    color=text_color,
                    zorder=4,
                )

                # FC value inside node (lower portion)
                fc_display = f"{fc:+.1f}" if fc != 0 else "0.0"
                fc_fontsize = max(6, min(9, 10 - name_len * 0.3))
                ax.text(
                    x, y - radius * 0.35,
                    fc_display,
                    ha="center", va="center",
                    fontsize=fc_fontsize, fontweight="normal",
                    color=text_color,
                    alpha=0.85,
                    zorder=4,
                )

                # PTM site badge
                if site and node_type in ("PTM", "Kinase"):
                    ax.text(
                        x + radius * 0.7, y + radius * 0.7,
                        site,
                        ha="center", va="center",
                        fontsize=7, fontweight="normal",
                        color="#E65100",
                        bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                                  edgecolor="#FFB74D", linewidth=0.5, alpha=0.9),
                        zorder=5,
                    )

                node_positions[gene] = (x, y)

    # ---- Draw signal flow arrows ----
    for chain in pathway_chains:
        genes = chain["genes"]
        for i in range(len(genes) - 1):
            src = genes[i]
            tgt = genes[i + 1]
            if src in node_positions and tgt in node_positions:
                sx, sy = node_positions[src]
                tx, ty = node_positions[tgt]
                sr = node_radii.get(src, 0.4)
                tr = node_radii.get(tgt, 0.4)
                dx = tx - sx
                dy = ty - sy
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 0.01:
                    continue
                ux, uy = dx / dist, dy / dist
                ax.annotate(
                    "",
                    xy=(tx - ux * tr * 1.1, ty - uy * tr * 1.1),
                    xytext=(sx + ux * sr * 1.1, sy + uy * sr * 1.1),
                    arrowprops=dict(
                        arrowstyle="-|>",
                        color="#90A4AE",
                        lw=1.2,
                        mutation_scale=12,
                    ),
                    zorder=2,
                )

    # ---- Legend ----
    legend_y = comp_y_bottom - 0.05
    legend_x = margin_left + 0.3

    # Title — content-driven subtitle
    title_main = "Signal Transduction Pathway Cascade Diagram"
    if condition:
        title_main += f" — {condition}"
    ax.text(
        fig_width / 2, fig_height - 0.35,
        title_main,
        ha="center", va="top",
        fontsize=16, fontweight="normal",
        color="#263238",
    )
    ax.text(
        fig_width / 2, fig_height - 0.7,
        "Key Signaling Pathways Discussed in Analysis — Compartmentalized Signal Flow",
        ha="center", va="top",
        fontsize=11,
        color="#455A64",
        fontstyle="italic",
    )

    # Color legend
    legend_items = [
        ("#E53935", "PTM Activated (Log2FC > 0)"),
        ("#1E88E5", "PTM Inhibited (Log2FC < 0)"),
        ("#43A047", "Non-PTM Upregulated"),
        ("#8E24AA", "Non-PTM Downregulated"),
        ("#FF8F00", "Kinase (◆)"),
        ("#9E9E9E", "Neutral / No change"),
    ]
    for li, (color, label) in enumerate(legend_items):
        lx = legend_x + (li % 3) * (total_width / 3)
        ly = legend_y - 0.4 * (li // 3)
        ax.add_patch(plt.Circle((lx, ly), 0.15, facecolor=color, edgecolor="#424242",
                                linewidth=0.5, zorder=5))
        ax.text(lx + 0.25, ly, label, ha="left", va="center",
                fontsize=9, color="#455A64", zorder=5)

    # Size legend
    size_legend_y = legend_y - 1.2
    size_examples = [(0.3, "|FC| < 1"), (0.4, "|FC| ~ 2"), (0.55, "|FC| > 3")]
    for si, (r, label) in enumerate(size_examples):
        sx = legend_x + si * 2.5
        ax.add_patch(plt.Circle((sx, size_legend_y), r, facecolor="#E0E0E0",
                                edgecolor="#424242", linewidth=0.5, zorder=5))
        ax.text(sx + r + 0.2, size_legend_y, label, ha="left", va="center",
                fontsize=9, color="#455A64", zorder=5)

    ax.text(
        fig_width / 2, size_legend_y - 0.5,
        "Color: PTM Log2FC (PTM nodes) / Protein Log2FC (Non-PTM nodes)  \u2022  Size: |PTM Log2FC| magnitude",
        ha="center", va="center",
        fontsize=8.5, color="#78909C",
        fontstyle="italic",
        zorder=5,
    )

    # ---- Save figure ----
    plt.tight_layout(pad=0.5)
    if condition:
        safe_cond = condition.replace("/", "_").replace(" ", "_").replace("\\", "_")
        output_path = Path(output_dir) / f"signaling_cascade_{safe_cond}.png"
    else:
        output_path = Path(output_dir) / "signaling_cascade.png"
    fig.savefig(
        str(output_path),
        dpi=250,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    plt.close(fig)

    selected_pathway_names_final = [chain["name"] for chain in pathway_chains]
    total_genes = len(all_pathway_genes)
    logger.info(
        f"[CASCADE-MEDIATOR] Content-driven cascade diagram saved: {output_path} "
        f"(condition={cond_label}, {n_pathways} pathways, {total_genes} proteins, "
        f"pathways={selected_pathway_names_final})"
    )
    return {"path": str(output_path), "pathways": selected_pathway_names_final}
