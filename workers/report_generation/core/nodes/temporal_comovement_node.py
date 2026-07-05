"""
Temporal PTM Co-movement Analysis Node — v8.0

Detects co-moving PTM clusters from time-series data, annotates them with
biological context (shared pathways, complexes, kinases), links to Non-PTM
interactors via Cytoscape edges, generates publication-quality visualizations,
and builds structured LLM context for signaling interpretation.

Pipeline position:
    network_analysis → temporal_comovement → write_sections → cascade_mediator

Input (from state):
    - network_analysis.timepoint_results: {tp: {active_ptm_nodes, inhibited_ptm_nodes, non_ptm_nodes, active_edges}}
    - network_analysis.timepoints: list of timepoint strings
    - enriched_ptm_data, parsed_ptms, pathway_candidates (all at state top-level)

v8.3 Fix: network_node returns timepoint_results (not networks). The entry point
now converts timepoint_results to the networks format expected by internal functions.
Also fixed: enriched_data → enriched_ptm_data, pathway_candidates from state top-level.

Output (to state):
    - comovement_analysis: {clusters, singletons, summary}
    - comovement_figures: [{path, caption}]
    - comovement_llm_context: str
"""

import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from scipy.interpolate import make_interp_spline
from scipy.ndimage import gaussian_filter1d

from common.temporal_utils import tp_to_minutes

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
MIN_TIMEPOINTS = 3          # Need at least 3 timepoints for meaningful clustering
MIN_VARIANCE = 0.3          # Minimum variance across timepoints (relaxed to include patterned minor PTMs)
MIN_AMPLITUDE = 0.8         # Minimum max |Log2FC| (relaxed to include patterned minor PTMs)
CORRELATION_THRESHOLD = 0.70  # Minimum |correlation| to be in same cluster (default; may be overridden by AI Singularity)
MIN_CLUSTER_SIZE = 2        # Minimum members for a valid cluster
MAX_CLUSTERS = 8            # Maximum clusters to report
PROTEIN_THRESHOLD = 0.3     # Minimum |protein_log2fc| for Non-PTM significance

# Color palette for clusters (colorblind-friendly)
CLUSTER_COLORS = [
    "#E64B35", "#4DBBD5", "#00A087", "#3C5488",
    "#F39B7F", "#8491B4", "#91D1C2", "#DC9A6C",
    "#7E6148", "#B09C85",
]


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def run_temporal_comovement(state: dict) -> dict:
    """Main entry point — called from graph.py."""
    try:
        network_analysis = state.get("network_analysis", {})
        enriched_data = state.get("enriched_ptm_data", [])
        parsed_ptms = state.get("parsed_ptms", [])
        # v8.3 Fix: pathway_candidates is at state top-level (returned by network_node)
        pathway_candidates = state.get("pathway_candidates", {})
        output_dir = state.get("output_dir", "/tmp")
        ptm_type = state.get("ptm_type", "phosphorylation")  # v8.10

        # v8.3 Fix: network_node returns timepoint_results (not networks)
        # timepoint_results: {tp: {active_ptm_nodes, inhibited_ptm_nodes, non_ptm_nodes, ...}}
        # We need to convert this to the networks format expected by _build_temporal_matrix
        timepoint_results = network_analysis.get("timepoint_results", {})
        networks = network_analysis.get("networks", {})

        # Determine timepoints
        timepoints = network_analysis.get("timepoints", [])
        if not timepoints and timepoint_results:
            timepoints = sorted(timepoint_results.keys(), key=tp_to_minutes)
        if not timepoints and networks:
            timepoints = sorted(networks.keys(), key=tp_to_minutes)
        # Filter out condition-based keys (non-time)
        timepoints = [tp for tp in timepoints if tp_to_minutes(tp) >= 0]
        timepoints = sorted(timepoints, key=tp_to_minutes)

        logger.info(
            f"[COMOVEMENT] timepoints={timepoints}, "
            f"timepoint_results_keys={list(timepoint_results.keys()) if timepoint_results else 'EMPTY'}, "
            f"networks_keys={list(networks.keys()) if networks else 'EMPTY'}"
        )

        if len(timepoints) < MIN_TIMEPOINTS:
            logger.info(f"Only {len(timepoints)} timepoints — skipping co-movement analysis")
            return {
                "comovement_analysis": {},
                "comovement_figures": [],
                "comovement_llm_context": "",
            }

        # v8.3 Fix: Use timepoint_results as the primary data source
        # Convert timepoint_results to the networks format if networks is empty
        if not networks and timepoint_results:
            networks = {}
            for tp in timepoints:
                tp_data = timepoint_results.get(tp, {})
                if not isinstance(tp_data, dict):
                    continue
                # timepoint_results uses active_ptm_nodes/inhibited_ptm_nodes
                # _build_temporal_matrix expects active_nodes/inhibited_nodes OR active_ptm_nodes/inhibited_ptm_nodes
                networks[tp] = tp_data
            logger.info(f"[COMOVEMENT] Converted timepoint_results to networks: {list(networks.keys())}")

        # Step 1: Build temporal matrix
        ptm_matrix, ptm_meta = _build_temporal_matrix(networks, timepoints)
        if ptm_matrix.shape[0] < 2:
            logger.info("Fewer than 2 PTMs in temporal matrix — skipping")
            return {
                "comovement_analysis": {},
                "comovement_figures": [],
                "comovement_llm_context": "",
            }

        # Step 2: Filter significant PTMs
        sig_matrix, sig_meta = _filter_significant_ptms(ptm_matrix, ptm_meta)
        if sig_matrix.shape[0] < 2:
            logger.info("Fewer than 2 significant PTMs — skipping clustering")
            return {
                "comovement_analysis": {},
                "comovement_figures": [],
                "comovement_llm_context": "",
            }

        # Step 3-4: Cluster co-moving PTMs
        clusters, singletons = _cluster_comoving_ptms(sig_matrix, sig_meta, timepoints, state=state)

        # Step 5: Annotate clusters with biological context
        # pathway_candidates is a dict {"candidates": [...], "gene_data": {...}}
        pw_candidates_list = pathway_candidates.get("candidates", []) if isinstance(pathway_candidates, dict) else pathway_candidates
        clusters = _annotate_clusters(clusters, enriched_data, pw_candidates_list, ptm_type=ptm_type)

        # Step 5b: Enrichr cluster-level enrichment (Layer 2: 3-Layer Pathway Enrichment)
        clusters = _enrich_clusters_with_enrichr(clusters)

        # Step 6: Link to Non-PTM interactors
        clusters = _link_to_nonptm_interactors(clusters, networks, timepoints)

        # Step 7: Generate visualizations
        figures = _generate_comovement_figures(
            clusters, singletons, timepoints, sig_matrix, sig_meta, output_dir,
            ptm_type=ptm_type,
        )

        # Step 8: Build LLM context (v9.30: include multi-site divergence analysis)
        llm_context = _build_comovement_llm_context(
            clusters, singletons, timepoints,
            ptm_type=ptm_type,
            sig_matrix=sig_matrix,
            sig_meta=sig_meta,
            enriched_data=enriched_data,
        )

        # Build summary
        summary = {
            "total_significant_ptms": sig_matrix.shape[0],
            "num_clusters": len(clusters),
            "num_singletons": len(singletons),
            "cluster_sizes": [len(c["members"]) for c in clusters],
        }

        return {
            "comovement_analysis": {
                "clusters": clusters,
                "singletons": singletons,
                "summary": summary,
            },
            "comovement_figures": figures,
            "comovement_llm_context": llm_context,
        }

    except Exception as e:
        logger.error(f"Temporal co-movement analysis failed: {e}", exc_info=True)
        return {
            "comovement_analysis": {},
            "comovement_figures": [],
            "comovement_llm_context": "",
        }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: BUILD TEMPORAL MATRIX
# ═══════════════════════════════════════════════════════════════════════════

def _build_temporal_matrix(
    networks: dict, timepoints: list
) -> Tuple[np.ndarray, List[dict]]:
    """Build PTM × Timepoint matrix of Log2FC values.

    Returns:
        matrix: np.ndarray of shape (n_ptms, n_timepoints)
        meta: list of dicts with gene, site, key for each row
    """
    ptm_data: Dict[str, Dict[str, float]] = {}  # key -> {tp: log2fc}
    ptm_meta_map: Dict[str, dict] = {}

    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes",
                          "active_ptm_nodes", "inhibited_ptm_nodes"]:
            for node in net.get(node_type, []):
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", node.get("id", "Unknown"))
                if not gene or gene == "Unknown":
                    continue
                site = node.get("site", node.get("position", ""))
                key = f"{gene}({site})" if site else gene
                fc = node.get("value", node.get("ptm_log2fc",
                       node.get("ptm_relative_log2fc", node.get("log2fc", 0))))
                try:
                    fc = float(fc) if fc is not None else 0.0
                except (ValueError, TypeError):
                    fc = 0.0

                if key not in ptm_data:
                    ptm_data[key] = {}
                    # v9.27: carry activity_class from node
                    ptm_meta_map[key] = {
                        "gene": gene,
                        "site": site,
                        "key": key,
                        "activity_class": node.get("activity_class", "minor"),
                        "q_value": node.get("q_value"),
                        "control_pseudocount_used": node.get("control_pseudocount_used", False),
                    }
                else:
                    # Update activity_class if a more significant class is found across timepoints
                    # Priority: de_novo > regulated > minor
                    existing = ptm_meta_map[key].get("activity_class", "minor")
                    incoming = node.get("activity_class", "minor")
                    _priority = {"de_novo": 2, "regulated": 1, "minor": 0}
                    if _priority.get(incoming, 0) > _priority.get(existing, 0):
                        ptm_meta_map[key]["activity_class"] = incoming
                        ptm_meta_map[key]["q_value"] = node.get("q_value")
                        ptm_meta_map[key]["control_pseudocount_used"] = node.get("control_pseudocount_used", False)
                ptm_data[key][tp] = fc

    if not ptm_data:
        return np.empty((0, len(timepoints))), []

    # Build matrix
    keys = sorted(ptm_data.keys())
    matrix = np.zeros((len(keys), len(timepoints)))
    meta = []
    for i, key in enumerate(keys):
        for j, tp in enumerate(timepoints):
            matrix[i, j] = ptm_data[key].get(tp, 0.0)
        meta.append(ptm_meta_map[key])

    return matrix, meta


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: FILTER SIGNIFICANT PTMs
# ═══════════════════════════════════════════════════════════════════════════

def _filter_significant_ptms(
    matrix: np.ndarray, meta: list
) -> Tuple[np.ndarray, list]:
    """Remove PTMs with low variance or low amplitude (flat lines)."""
    variances = np.var(matrix, axis=1)
    amplitudes = np.max(np.abs(matrix), axis=1)
    mask = (variances >= MIN_VARIANCE) | (amplitudes >= MIN_AMPLITUDE)

    filtered_matrix = matrix[mask]
    filtered_meta = [m for m, keep in zip(meta, mask) if keep]

    logger.info(
        f"Significance filter: {matrix.shape[0]} → {filtered_matrix.shape[0]} PTMs "
        f"(variance>={MIN_VARIANCE} or amplitude>={MIN_AMPLITUDE})"
    )
    return filtered_matrix, filtered_meta


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3-4: CORRELATION-BASED CLUSTERING
# ═══════════════════════════════════════════════════════════════════════════

def _cluster_comoving_ptms(
    matrix: np.ndarray, meta: list, timepoints: list, state: Optional[dict] = None
) -> Tuple[List[dict], List[dict]]:
    """Cluster PTMs by temporal correlation using hierarchical clustering.

    Returns:
        clusters: list of cluster dicts
        singletons: list of significant but unclustered PTMs
    """
    n = matrix.shape[0]
    if n < 2:
        return [], [_build_singleton(meta[0], matrix[0], timepoints)]

    # Compute pairwise Pearson correlation
    # Normalize rows (zero-mean, unit-variance) for correlation
    row_means = matrix.mean(axis=1, keepdims=True)
    row_stds = matrix.std(axis=1, keepdims=True)
    row_stds[row_stds == 0] = 1.0  # avoid division by zero
    normed = (matrix - row_means) / row_stds

    corr_matrix = np.dot(normed, normed.T) / matrix.shape[1]
    np.fill_diagonal(corr_matrix, 1.0)
    # Clamp to [-1, 1]
    corr_matrix = np.clip(corr_matrix, -1.0, 1.0)

    # v9.1: Use signed correlation for clustering — anti-correlated PTMs should NOT
    # be in the same cluster. Previously used |correlation| which incorrectly grouped
    # anti-correlated PTMs (r=-0.8) together, leading to "Co-activated" labels for
    # clusters with negative mean correlation.
    # Distance = 1 - correlation (range: 0 for r=1, 1 for r=0, 2 for r=-1)
    dist_matrix = 1.0 - corr_matrix
    np.fill_diagonal(dist_matrix, 0.0)
    # Ensure symmetry and non-negative
    dist_matrix = (dist_matrix + dist_matrix.T) / 2
    dist_matrix = np.maximum(dist_matrix, 0.0)

    # Hierarchical clustering (Ward's method on condensed distance)
    condensed = squareform(dist_matrix, checks=False)
    Z = linkage(condensed, method="average")

    # Cut at threshold
    # ── AI Singularity: 적응형 임계값 ──────────────────────────────────────
    try:
        from common.singularity_orchestrator import get_adaptive_threshold, is_enabled
        if is_enabled() and state:
            _adaptive = get_adaptive_threshold(state, default_threshold=CORRELATION_THRESHOLD)
            logger.info(f"[COMOVEMENT][Singularity] Adaptive threshold: {_adaptive:.4f}")
            effective_threshold = _adaptive
        else:
            effective_threshold = CORRELATION_THRESHOLD
    except Exception:
        effective_threshold = CORRELATION_THRESHOLD
    # ─────────────────────────────────────────────────────────────────────────
    threshold = 1.0 - effective_threshold  # distance threshold
    labels = fcluster(Z, t=threshold, criterion="distance")

    # Group by cluster label
    cluster_groups: Dict[int, List[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        cluster_groups[label].append(idx)

    clusters = []
    singletons = []

    for label, indices in sorted(cluster_groups.items()):
        if len(indices) < MIN_CLUSTER_SIZE:
            for idx in indices:
                singletons.append(_build_singleton(meta[idx], matrix[idx], timepoints))
            continue

        members = [meta[idx]["key"] for idx in indices]
        member_details = []
        temporal_profiles = []

        for idx in indices:
            values = matrix[idx]
            peak_idx = int(np.argmax(np.abs(values)))
            member_details.append({
                "key": meta[idx]["key"],
                "gene": meta[idx]["gene"],
                "site": meta[idx]["site"],
                "temporal_values": {tp: round(float(values[j]), 2)
                                    for j, tp in enumerate(timepoints)},
                "max_fc": round(float(np.max(np.abs(values))), 2),
                "peak_tp": timepoints[peak_idx],
                # v9.27: activity classification
                "activity_class": meta[idx].get("activity_class", "minor"),
                "q_value": meta[idx].get("q_value"),
                "control_pseudocount_used": meta[idx].get("control_pseudocount_used", False),
            })
            temporal_profiles.append(values)

        # Cluster mean profile
        mean_profile = np.mean(temporal_profiles, axis=0)
        peak_tp_idx = int(np.argmax(np.abs(mean_profile)))

        # Determine cluster pattern
        pattern = _classify_cluster_pattern(temporal_profiles, timepoints)

        # Mean intra-cluster correlation
        if len(indices) > 1:
            intra_corrs = []
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    intra_corrs.append(corr_matrix[indices[i], indices[j]])
            mean_corr = float(np.mean(intra_corrs))
        else:
            mean_corr = 1.0

        # v9.27: activity class statistics for this cluster
        class_counts = {"de_novo": 0, "regulated": 0, "minor": 0}
        for md in member_details:
            ac = md.get("activity_class", "minor")
            class_counts[ac] = class_counts.get(ac, 0) + 1
        # Dominant class: de_novo > regulated > minor
        if class_counts["de_novo"] > 0:
            dominant_class = "de_novo"
        elif class_counts["regulated"] > 0:
            dominant_class = "regulated"
        else:
            dominant_class = "minor"

        cluster = {
            "cluster_id": len(clusters) + 1,
            "members": members,
            "member_count": len(members),
            "pattern": pattern,
            "peak_timepoint": timepoints[peak_tp_idx],
            "correlation_mean": round(mean_corr, 3),
            "mean_profile": {tp: round(float(mean_profile[j]), 2)
                             for j, tp in enumerate(timepoints)},
            "member_details": member_details,
            # v9.27: activity class breakdown
            "activity_class_counts": class_counts,
            "dominant_activity_class": dominant_class,
        }
        clusters.append(cluster)

    # Sort clusters by size (largest first), limit to MAX_CLUSTERS
    clusters.sort(key=lambda c: c["member_count"], reverse=True)
    if len(clusters) > MAX_CLUSTERS:
        # Move excess clusters to singletons
        for c in clusters[MAX_CLUSTERS:]:
            for md in c["member_details"]:
                singletons.append({
                    "key": md["key"],
                    "gene": md["gene"],
                    "site": md["site"],
                    "temporal_values": md["temporal_values"],
                    "max_fc": md["max_fc"],
                    "peak_tp": md["peak_tp"],
                })
        clusters = clusters[:MAX_CLUSTERS]

    # Re-number cluster IDs
    for i, c in enumerate(clusters):
        c["cluster_id"] = i + 1

    return clusters, singletons


def _classify_cluster_pattern(profiles: list, timepoints: list) -> str:
    """Classify the temporal movement pattern of a cluster."""
    mean_profile = np.mean(profiles, axis=0)
    tp_minutes = [tp_to_minutes(tp) for tp in timepoints]

    # Check if mostly positive or negative
    pos_count = np.sum(mean_profile > 0.5)
    neg_count = np.sum(mean_profile < -0.5)

    # Check for spike pattern (sharp peak then return to baseline)
    max_val = np.max(np.abs(mean_profile))
    if max_val > 0:
        above_half = np.sum(np.abs(mean_profile) > max_val * 0.5)
        spike_ratio = above_half / len(timepoints)
    else:
        spike_ratio = 0

    # Check for sustained pattern
    sustained_count = np.sum(np.abs(mean_profile) > 1.0)
    sustained_ratio = sustained_count / len(timepoints)

    # Check for biphasic (sign change)
    sign_changes = 0
    for i in range(1, len(mean_profile)):
        if mean_profile[i] * mean_profile[i - 1] < 0 and \
           abs(mean_profile[i]) > 0.5 and abs(mean_profile[i - 1]) > 0.5:
            sign_changes += 1

    # Check for sequential wave (peaks at different times)
    peak_times = [int(np.argmax(np.abs(p))) for p in profiles]
    peak_spread = max(peak_times) - min(peak_times) if peak_times else 0

    if sign_changes >= 1:
        return "biphasic_switch"
    elif peak_spread >= 3 and len(profiles) >= 3:
        return "sequential_wave"
    elif spike_ratio <= 0.4 and max_val > 3:
        if pos_count > neg_count:
            return "transient_burst"
        else:
            return "transient_suppression"
    elif sustained_ratio >= 0.6:
        if pos_count > neg_count:
            return "sustained_activation"
        else:
            return "sustained_inhibition"
    elif pos_count > neg_count:
        return "co_activated"
    elif neg_count > pos_count:
        return "co_inhibited"
    else:
        return "mixed_response"


def _build_singleton(meta: dict, values: np.ndarray, timepoints: list) -> dict:
    """Build a singleton PTM entry."""
    peak_idx = int(np.argmax(np.abs(values)))
    return {
        "key": meta["key"],
        "gene": meta["gene"],
        "site": meta["site"],
        "temporal_values": {tp: round(float(values[j]), 2)
                            for j, tp in enumerate(timepoints)},
        "max_fc": round(float(np.max(np.abs(values))), 2),
        "peak_tp": timepoints[peak_idx],
        # v9.27: activity classification
        "activity_class": meta.get("activity_class", "minor"),
        "q_value": meta.get("q_value"),
        "control_pseudocount_used": meta.get("control_pseudocount_used", False),
    }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5: BIOLOGICAL ANNOTATION
# ═══════════════════════════════════════════════════════════════════════════

def _annotate_clusters(
    clusters: list, enriched_data: list, pathway_candidates: list,
    ptm_type: str = "phosphorylation",
) -> list:
    """Annotate each cluster with shared biological features.

    v8.10: Enhanced with per-gene 3-Layer pathway mapping from enriched_ptm_data.
    Each gene's KEGG + Reactome + STRING indirect pathways are collected and
    cross-referenced within the cluster to find shared pathways that explain
    WHY these proteins co-move (i.e., they participate in the same signaling
    pathways identified in Figure 1's 3-Layer enrichment).
    """
    # Build gene → enrichment lookup
    gene_enrichment: Dict[str, dict] = {}
    for ed in enriched_data:
        gene = (ed.get("gene") or ed.get("Gene.Name", "")).strip().upper()
        if not gene:
            continue
        gene_enrichment[gene] = ed

    # Build pathway → gene set lookup from pathway_candidates
    pathway_genes: Dict[str, set] = {}
    for pc in pathway_candidates:
        pw_name = pc.get("name", "")
        genes = set(g.upper() for g in pc.get("genes", []))
        if pw_name and genes:
            pathway_genes[pw_name] = genes

    # ── v8.10: Disease pathway filter (same as network_node / cascade_mediator) ──
    _DISEASE_KEYWORDS = {
        "infection", "virus", "viral", "carcinogenesis", "cancer",
        "amoebiasis", "lupus", "leishmaniasis", "tuberculosis",
        "malaria", "pertussis", "measles", "hepatitis", "influenza",
        "herpes", "hiv", "htlv", "epstein-barr", "kaposi",
        "shigellosis", "salmonella", "cholera", "diabetes",
        "cardiomyopathy", "alzheimer", "parkinson", "huntington",
        "prion", "asthma", "graft-versus-host",
    }

    def _is_disease_pathway(pw_name: str, pw_id: str = "") -> bool:
        name_lower = pw_name.lower()
        return pw_id.startswith("05") or any(kw in name_lower for kw in _DISEASE_KEYWORDS)

    for cluster in clusters:
        cluster_genes = set()
        for md in cluster["member_details"]:
            cluster_genes.add(md["gene"].upper())

        annotations = {
            "shared_pathways": [],
            "shared_go_terms": [],
            "shared_kinases": [],
            "shared_complexes": [],
            "shared_locations": [],
            "functional_categories": [],
            "per_gene_pathways": {},       # v8.10: gene → [pathway names]
            "per_gene_shared_pathways": [], # v8.10: pathways shared by 2+ genes via per-gene data
        }

        # --- v8.10: Per-gene 3-Layer pathway collection ---
        # Collect ALL pathways for each gene from enriched_ptm_data
        # (KEGG + Reactome + STRING indirect = same data that feeds Figure 1)
        per_gene_pw: Dict[str, set] = {}  # gene → set of pathway names
        for gene in cluster_genes:
            ed = gene_enrichment.get(gene, {})
            enr = ed.get("rag_enrichment", {})
            if not enr or not isinstance(enr, dict):
                continue

            gene_pws: set = set()

            # Layer 1: KEGG pathways
            for pw in enr.get("pathways", []):
                if isinstance(pw, dict):
                    pw_name = pw.get("name", "")
                    pw_id = pw.get("id", "")
                elif isinstance(pw, str):
                    pw_name = pw
                    pw_id = ""
                else:
                    continue
                if pw_name and not _is_disease_pathway(pw_name, pw_id):
                    # Normalize: remove species suffix
                    pw_clean = re.sub(r'\s*-\s*(Mus musculus|Homo sapiens|Rattus norvegicus).*$', '', pw_name).strip()
                    gene_pws.add(pw_clean)

            # Layer 1b: Reactome signaling pathways
            reactome = enr.get("reactome", {})
            if isinstance(reactome, dict):
                for rpw in reactome.get("signaling_pathways", []):
                    rpw_name = rpw.get("name", "") if isinstance(rpw, dict) else str(rpw)
                    if rpw_name and not _is_disease_pathway(rpw_name):
                        gene_pws.add(rpw_name)

            # Layer 3: STRING indirect inferred pathways
            string_ind = enr.get("string_indirect", {})
            if isinstance(string_ind, dict):
                for spw in string_ind.get("signaling_pathways", []):
                    spw_name = spw.get("name", "") if isinstance(spw, dict) else str(spw)
                    if spw_name and not _is_disease_pathway(spw_name):
                        gene_pws.add(spw_name)

            if gene_pws:
                per_gene_pw[gene] = gene_pws

        annotations["per_gene_pathways"] = {
            g: sorted(pws) for g, pws in per_gene_pw.items()
        }

        # v8.10: Find pathways shared by 2+ cluster members via per-gene data
        pw_to_genes: Dict[str, set] = defaultdict(set)
        for gene, pws in per_gene_pw.items():
            for pw in pws:
                pw_to_genes[pw].add(gene)

        per_gene_shared = []
        for pw_name, pw_members in pw_to_genes.items():
            if len(pw_members) >= 2:
                per_gene_shared.append({
                    "name": pw_name,
                    "members": sorted(pw_members),
                    "overlap_count": len(pw_members),
                    "total_cluster": len(cluster_genes),
                    "source": "per_gene_3layer",
                })
        per_gene_shared.sort(key=lambda x: x["overlap_count"], reverse=True)
        annotations["per_gene_shared_pathways"] = per_gene_shared[:15]

        logger.info(
            f"[ANNOTATE] Cluster {cluster['cluster_id']}: "
            f"{len(cluster_genes)} genes, "
            f"{len(per_gene_pw)} genes with pathway data, "
            f"{len(per_gene_shared)} shared pathways via per-gene 3-Layer"
        )

        # --- Pathway enrichment (original: from pathway_candidates) ---
        for pw_name, pw_genes in pathway_genes.items():
            overlap = cluster_genes & pw_genes
            if len(overlap) >= 2:
                annotations["shared_pathways"].append({
                    "name": pw_name,
                    "members": sorted(overlap),
                    "overlap_count": len(overlap),
                    "total_cluster": len(cluster_genes),
                })
        annotations["shared_pathways"].sort(
            key=lambda x: x["overlap_count"], reverse=True
        )

        # v8.10: Merge per_gene_shared into shared_pathways if not already present
        existing_pw_names = {pw["name"].lower() for pw in annotations["shared_pathways"]}
        for pgpw in per_gene_shared:
            if pgpw["name"].lower() not in existing_pw_names:
                annotations["shared_pathways"].append(pgpw)
                existing_pw_names.add(pgpw["name"].lower())
        # Re-sort after merge
        annotations["shared_pathways"].sort(
            key=lambda x: x["overlap_count"], reverse=True
        )

        # --- GO terms, kinases, complexes from enriched_data ---
        go_term_counts: Dict[str, List[str]] = defaultdict(list)
        kinase_counts: Dict[str, List[str]] = defaultdict(list)
        location_counts: Dict[str, int] = defaultdict(int)
        complex_counts: Dict[str, List[str]] = defaultdict(list)

        for gene in cluster_genes:
            ed = gene_enrichment.get(gene, {})
            enr = ed.get("rag_enrichment", ed)

            # GO terms
            go_terms_data = enr.get("go_terms", {})
            if isinstance(go_terms_data, dict):
                # v8.10: go_terms is a dict with biological_process, molecular_function, etc.
                bp_terms = go_terms_data.get("biological_process", [])
            elif isinstance(go_terms_data, list):
                bp_terms = go_terms_data
            else:
                bp_terms = []
            for go in bp_terms:
                term = go if isinstance(go, str) else go.get("term", "")
                if term:
                    go_term_counts[term].append(gene)

            # Kinases (upstream regulators)
            reg = enr.get("regulation", {})
            for ur in reg.get("upstream_regulators", []):
                kinase = ur if isinstance(ur, str) else ur.get("name", "")
                if kinase:
                    kinase_counts[kinase].append(gene)

            # Kinase prediction
            kp = enr.get("kinase_prediction", {})
            for k in kp.get("predicted_kinases", []):
                kname = k if isinstance(k, str) else k.get("kinase", "")
                if kname:
                    kinase_counts[kname].append(gene)

            # Subcellular location
            loc = enr.get("subcellular_location", enr.get("localization", ""))
            if isinstance(loc, list):
                for l in loc:
                    loc_str = l if isinstance(l, str) else str(l)
                    location_counts[loc_str] += 1
            elif loc:
                location_counts[str(loc)] += 1

            # Protein complex
            for cpx in enr.get("protein_complex", enr.get("complexes", [])):
                cname = cpx if isinstance(cpx, str) else cpx.get("name", "")
                if cname:
                    complex_counts[cname].append(gene)

        # Filter shared (≥2 members)
        for term, genes in go_term_counts.items():
            if len(genes) >= 2:
                annotations["shared_go_terms"].append({
                    "term": term,
                    "members": sorted(set(genes)),
                    "count": len(set(genes)),
                })
        annotations["shared_go_terms"].sort(key=lambda x: x["count"], reverse=True)
        annotations["shared_go_terms"] = annotations["shared_go_terms"][:5]

        for kinase, substrates in kinase_counts.items():
            if len(set(substrates)) >= 2:
                annotations["shared_kinases"].append({
                    "kinase": kinase,
                    "substrates": sorted(set(substrates)),
                    "count": len(set(substrates)),
                })
        annotations["shared_kinases"].sort(key=lambda x: x["count"], reverse=True)

        for cname, members in complex_counts.items():
            if len(set(members)) >= 2:
                annotations["shared_complexes"].append({
                    "name": cname,
                    "members": sorted(set(members)),
                    "count": len(set(members)),
                })

        # Top location
        if location_counts:
            top_loc = max(location_counts, key=location_counts.get)
            annotations["shared_locations"] = [
                {"location": top_loc, "count": location_counts[top_loc]}
            ]

        # Build biological summary
        # v8.10: Prioritize per-gene shared pathways (3-Layer data) for summary
        summary_parts = []
        if annotations["shared_pathways"]:
            # Show top 3 shared pathways in summary
            top_pws = annotations["shared_pathways"][:3]
            pw_strs = [f"{pw['name']} ({pw['overlap_count']}/{len(cluster_genes)})" for pw in top_pws]
            summary_parts.append("Pathways: " + ", ".join(pw_strs))
        if annotations["shared_kinases"]:
            top_k = annotations["shared_kinases"][0]
            summary_parts.append(
                f"{'E3 Ligase' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'Kinase'}: {top_k['kinase']} ({top_k['count']} substrates)"
            )
        if annotations["shared_complexes"]:
            top_c = annotations["shared_complexes"][0]
            summary_parts.append(f"Complex: {top_c['name']}")
        if not summary_parts and annotations["shared_go_terms"]:
            top_go = annotations["shared_go_terms"][0]
            summary_parts.append(top_go["term"])

        annotations["biological_summary"] = "; ".join(summary_parts) if summary_parts else "No shared annotations found"

        cluster["annotations"] = annotations

    return clusters


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5b: ENRICHR CLUSTER-LEVEL ENRICHMENT (Layer 2)
# ═══════════════════════════════════════════════════════════════════════════

def _enrich_clusters_with_enrichr(clusters: list) -> list:
    """Enrich each cluster with Enrichr pathway enrichment analysis.

    Layer 2 of 3-Layer Pathway Enrichment: submits each cluster's gene list
    to Enrichr for pathway enrichment, providing cluster-level biological
    context that per-gene KEGG/Reactome cannot capture.
    """
    try:
        from common.mcp_client import MCPClient
        mcp = MCPClient()
    except Exception as e:
        logger.warning(f"Cannot initialize MCP client for Enrichr: {e}")
        return clusters

    for cluster in clusters:
        try:
            # Extract unique gene names from cluster members
            cluster_genes = list(set(
                md["gene"] for md in cluster.get("member_details", [])
                if md.get("gene")
            ))

            if len(cluster_genes) < 2:
                continue

            # Query Enrichr with cluster gene list
            enrichr_result = mcp.query_enrichr(
                gene_list=cluster_genes,
                libraries=[
                    "KEGG_2021_Human",
                    "Reactome_2022",
                    "MSigDB_Hallmark_2020",
                    "WikiPathway_2023_Human",
                ],
                description=f"Cluster_{cluster['cluster_id']}_{cluster.get('pattern', 'unknown')}",
                top_n=10,
            )

            # Also query STRING functional enrichment
            string_enrich = mcp.query_string_enrichment(
                gene_list=cluster_genes,
                species=10090,
            )

            # Merge enrichment results into cluster annotations
            annotations = cluster.get("annotations", {})

            # Extract top signaling pathways from Enrichr
            enrichr_pathways = []
            for lib_name, terms in enrichr_result.get("results", {}).items():
                for term in terms:
                    name = term.get("term", "")
                    pval = term.get("adjusted_p_value", term.get("p_value", 1.0))
                    genes = term.get("genes", [])
                    if pval < 0.05:  # Only significant terms
                        enrichr_pathways.append({
                            "name": name,
                            "library": lib_name,
                            "p_value": pval,
                            "genes": genes,
                            "gene_count": len(genes),
                        })
            enrichr_pathways.sort(key=lambda x: x["p_value"])
            annotations["enrichr_pathways"] = enrichr_pathways[:15]

            # Extract STRING functional enrichment
            string_kegg = string_enrich.get("kegg_terms", [])
            annotations["string_enrichment"] = {
                "kegg": string_kegg[:10],
                "all_terms": string_enrich.get("all_terms", [])[:15],
            }

            # Update biological summary with enrichment results
            if enrichr_pathways:
                top_enrichr = enrichr_pathways[0]
                existing_summary = annotations.get("biological_summary", "")
                enrichr_summary = f"Enrichr: {top_enrichr['name']} (p={top_enrichr['p_value']:.2e})"
                if existing_summary and existing_summary != "No shared annotations found":
                    annotations["biological_summary"] = f"{existing_summary}; {enrichr_summary}"
                else:
                    annotations["biological_summary"] = enrichr_summary

            cluster["annotations"] = annotations
            logger.info(
                f"Cluster {cluster['cluster_id']}: Enrichr found "
                f"{len(enrichr_pathways)} significant pathways, "
                f"STRING found {len(string_kegg)} KEGG terms"
            )

        except Exception as e:
            logger.warning(
                f"Enrichr enrichment failed for cluster {cluster.get('cluster_id', '?')}: {e}"
            )
            continue

    return clusters


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6: NON-PTM INTERACTOR LINKAGE
# ═══════════════════════════════════════════════════════════════════════════

def _link_to_nonptm_interactors(
    clusters: list, networks: dict, timepoints: list
) -> list:
    """Link each cluster to Non-PTM proteins via Cytoscape edges."""
    # Build Non-PTM temporal profiles
    nonptm_temporal: Dict[str, Dict[str, float]] = {}
    nonptm_roles: Dict[str, str] = {}

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
            role = node.get("node_role", "interactor")
            pfc = node.get("protein_log2fc", node.get("log2fc", 0))
            try:
                pfc = float(pfc) if pfc is not None else 0.0
            except (ValueError, TypeError):
                pfc = 0.0
            if gene not in nonptm_temporal:
                nonptm_temporal[gene] = {}
                nonptm_roles[gene] = role
            nonptm_temporal[gene][tp] = pfc

    # Build edge map: PTM_gene → set of Non-PTM genes
    ptm_to_nonptm: Dict[str, set] = defaultdict(set)
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for edge in net.get("active_edges", []) + net.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = edge.get("source", "").upper()
            target = edge.get("target", "").upper()
            if source in nonptm_temporal:
                # source is Non-PTM, target might be PTM
                ptm_to_nonptm[target].add(source)
            if target in nonptm_temporal:
                ptm_to_nonptm[source].add(target)

    for cluster in clusters:
        cluster_genes = set(md["gene"].upper() for md in cluster["member_details"])

        # Find all Non-PTM interactors connected to cluster members
        linked_nonptms: Dict[str, dict] = {}
        for ptm_gene in cluster_genes:
            for nonptm_gene in ptm_to_nonptm.get(ptm_gene, set()):
                if nonptm_gene not in nonptm_temporal:
                    continue
                if nonptm_gene not in linked_nonptms:
                    linked_nonptms[nonptm_gene] = {
                        "gene": nonptm_gene,
                        "edge_sources": [],
                        "role": nonptm_roles.get(nonptm_gene, "interactor"),
                    }
                linked_nonptms[nonptm_gene]["edge_sources"].append(ptm_gene)

        # Compute correlation with cluster mean profile
        mean_vals = np.array([cluster["mean_profile"].get(tp, 0) for tp in timepoints])
        mean_std = np.std(mean_vals)

        nonptm_links = []
        for nonptm_gene, info in linked_nonptms.items():
            tp_data = nonptm_temporal[nonptm_gene]
            nonptm_vals = np.array([tp_data.get(tp, 0) for tp in timepoints])
            nonptm_std = np.std(nonptm_vals)

            # Compute correlation
            if mean_std > 0 and nonptm_std > 0:
                corr = float(np.corrcoef(mean_vals, nonptm_vals)[0, 1])
            else:
                corr = 0.0

            # Determine response pattern
            cluster_peak_idx = int(np.argmax(np.abs(mean_vals)))
            nonptm_peak_idx = int(np.argmax(np.abs(nonptm_vals)))
            time_lag = tp_to_minutes(timepoints[nonptm_peak_idx]) - \
                       tp_to_minutes(timepoints[cluster_peak_idx])

            if abs(time_lag) <= 5:
                response = "simultaneous"
            elif time_lag > 0:
                response = "delayed_response"
            else:
                response = "precedes_cluster"

            max_change = float(np.max(np.abs(nonptm_vals)))
            if max_change < PROTEIN_THRESHOLD:
                continue  # Skip non-responsive interactors

            nonptm_links.append({
                "gene": nonptm_gene,
                "edge_sources": sorted(set(info["edge_sources"])),
                "role": info["role"],
                "temporal_profile": {tp: round(tp_data.get(tp, 0), 3)
                                     for tp in timepoints},
                "correlation_with_cluster": round(corr, 3),
                "response_pattern": response,
                "time_lag_minutes": round(time_lag, 1),
                "max_change": round(max_change, 3),
            })

        # Sort by |correlation| descending
        nonptm_links.sort(key=lambda x: abs(x["correlation_with_cluster"]), reverse=True)
        cluster["nonptm_links"] = nonptm_links[:10]  # Top 10

        # ── v8.10: Neighborhood Concordance Score ──
        # Detect coordinated direction changes among Non-PTM neighbors.
        # When multiple Non-PTM proteins around a PTM cluster all move in the
        # same direction simultaneously, this suggests a collective mechanism
        # (complex stoichiometry, transcriptional co-regulation, or pathway
        # feedback) rather than independent regulation.
        if nonptm_links:
            # Determine cluster direction at peak timepoint
            cluster_peak_tp_idx = int(np.argmax(np.abs(mean_vals)))
            cluster_direction = "up" if mean_vals[cluster_peak_tp_idx] > 0 else "down"

            # Count Non-PTM direction at the same timepoint
            up_count = 0
            down_count = 0
            simultaneous_count = 0
            for link in nonptm_links:
                tp_data = link["temporal_profile"]
                tp_key = timepoints[cluster_peak_tp_idx]
                nonptm_fc = tp_data.get(tp_key, 0)
                if nonptm_fc > 0.1:
                    up_count += 1
                elif nonptm_fc < -0.1:
                    down_count += 1
                if link["response_pattern"] == "simultaneous":
                    simultaneous_count += 1

            total_responsive = up_count + down_count
            if total_responsive >= 2:
                # Concordance: fraction moving in the same direction
                dominant_direction = "up" if up_count >= down_count else "down"
                dominant_count = max(up_count, down_count)
                concordance = round(dominant_count / total_responsive, 2)

                # ── Time lag statistics for mechanism inference ──
                # Collect all time lags to understand the temporal relationship
                # between PTM changes and Non-PTM protein abundance changes.
                lags = [l["time_lag_minutes"] for l in nonptm_links]
                abs_lags = [abs(lg) for lg in lags]
                median_lag = float(np.median(abs_lags)) if abs_lags else 0.0
                mean_lag = float(np.mean(abs_lags)) if abs_lags else 0.0
                delayed_count = sum(1 for l in nonptm_links
                                    if l["response_pattern"] == "delayed_response")
                precedes_count = sum(1 for l in nonptm_links
                                     if l["response_pattern"] == "precedes_cluster")

                # Mechanism hint: combine direction concordance + time lag pattern
                # 1) Simultaneous + concordant → complex stoichiometry
                # 2) Delayed (>15min median) + concordant → transcriptional co-regulation
                # 3) Mixed timing → pathway-level coordination
                if simultaneous_count >= dominant_count * 0.6 and median_lag <= 10:
                    mechanism_hint = "protein_complex_stoichiometry"
                elif delayed_count >= dominant_count * 0.5 and median_lag > 15:
                    mechanism_hint = "transcriptional_coregulation"
                elif precedes_count >= dominant_count * 0.4:
                    mechanism_hint = "upstream_regulation"
                else:
                    mechanism_hint = "pathway_level_coordination"

                cluster["neighborhood_concordance"] = {
                    "total_responsive_nonptm": total_responsive,
                    "up_count": up_count,
                    "down_count": down_count,
                    "dominant_direction": dominant_direction,
                    "concordance_score": concordance,
                    "same_as_cluster": dominant_direction == cluster_direction,
                    "simultaneous_count": simultaneous_count,
                    "delayed_count": delayed_count,
                    "precedes_count": precedes_count,
                    "median_lag_minutes": round(median_lag, 1),
                    "mean_lag_minutes": round(mean_lag, 1),
                    "mechanism_hint": mechanism_hint,
                    "cluster_direction": cluster_direction,
                }
                logger.info(
                    f"[COMOVEMENT] Cluster {cluster.get('cluster_id', '?')}: "
                    f"Neighborhood concordance={concordance:.2f} "
                    f"({dominant_count}/{total_responsive} {dominant_direction}), "
                    f"median_lag={median_lag:.0f}min, "
                    f"mechanism_hint={mechanism_hint}"
                )
            else:
                cluster["neighborhood_concordance"] = None
        else:
            cluster["neighborhood_concordance"] = None

    return clusters


# ═══════════════════════════════════════════════════════════════════════════
# STEP 7: VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════

def _generate_comovement_figures(
    clusters: list, singletons: list, timepoints: list,
    matrix: np.ndarray, meta: list, output_dir: str,
    ptm_type: str = "phosphorylation",
) -> list:
    """Generate publication-quality cluster visualizations.

    v8.4: Transient burst clusters are rendered as Fig 1 (Nature-style
    composite figure) before the summary heatmap and other cluster plots.
    """
    figures = []
    os.makedirs(output_dir, exist_ok=True)

    if not clusters:
        return figures

    # ── v8.4: Fig 1 — Transient Burst Composite (Nature style) ──
    burst_clusters = [c for c in clusters if c["pattern"] in
                      ("transient_burst", "transient_suppression")]
    other_clusters = [c for c in clusters if c["pattern"] not in
                      ("transient_burst", "transient_suppression")]

    if burst_clusters:
        try:
            burst_fig_path = _generate_transient_burst_figure(
                burst_clusters, timepoints, output_dir
            )
            if burst_fig_path:
                n_sites = sum(c["member_count"] for c in burst_clusters)
                peak_tps = set(c["peak_timepoint"] for c in burst_clusters)
                figures.append({
                    "path": burst_fig_path,
                    "caption": (
                        f"Transient {ptm_type} burst dynamics. "
                        f"{len(burst_clusters)} temporally coordinated cluster(s) comprising "
                        f"{n_sites} PTM sites exhibited rapid activation followed by "
                        f"return to baseline. Peak responses observed at "
                        f"{', '.join(sorted(peak_tps))}. "
                        f"(a) Individual PTM time-series profiles colored by activity class: "
                        f"orange/\u2605=De novo (newly induced), blue/\u25cf=Regulated (q<0.05, |FC|\u22651), "
                        f"green solid/\u25c6=Minor (patterned). Cluster mean shown as bold line. "
                        f"(b) Peak amplitude profiles ranked by intensity, colored by activity class. "
                        f"(c) Cluster mean temporal envelope showing activation-recovery kinetics."
                    ),
                    "type": "transient_burst_composite",
                })
                logger.info(f"[COMOVEMENT] Generated transient burst Fig 1: {burst_fig_path}")
        except Exception as e:
            logger.warning(f"Transient burst figure generation failed: {e}", exc_info=True)

    # ── Summary Heatmap ──
    try:
        heatmap_path = _generate_summary_heatmap(
            clusters, singletons, timepoints, matrix, meta, output_dir
        )
        if heatmap_path:
            figures.append({
                "path": heatmap_path,
                "caption": "Temporal Coordination Heatmap: PTM sites grouped by "
                           "correlated temporal dynamics. Color intensity represents "
                           "Log2FC magnitude (red=activated, blue=inhibited). "
                           "Left sidebar: cluster assignments. "
                           "Activity class sidebar: orange=De novo, blue=Regulated, green=Minor.",
                "type": "supplementary_heatmap",
            })
    except Exception as e:
        logger.warning(f"Heatmap generation failed: {e}")

    # ── Per-cluster line plots (non-burst only for Fig 3-6) ──
    # v8.7: Burst clusters are already shown in Fig 2 composite,
    # so individual plots are only for non-burst clusters.
    # User-specified main figure clusters: 1, 3, 4, 5
    # All other non-burst clusters go to supplementary.
    # Select top N non-burst clusters as main figures (sorted by member_count desc).
    # Remaining non-burst clusters become supplementary.
    MAX_MAIN_CLUSTERS = 4  # Fig 3-6 (user preference: up to 4 main cluster figs)
    sorted_other = sorted(other_clusters, key=lambda c: c["member_count"], reverse=True)
    main_clusters = sorted_other[:MAX_MAIN_CLUSTERS]
    supp_clusters = sorted_other[MAX_MAIN_CLUSTERS:]

    # Main cluster figures first (Fig 3-6)
    for cluster in main_clusters:
        try:
            cluster_path = _generate_cluster_lineplot(
                cluster, timepoints, output_dir
            )
            if cluster_path:
                ann = cluster.get("annotations", {})
                bio_summary = ann.get("biological_summary", "")
                pattern_label = _pattern_display_name(cluster["pattern"], ptm_type)
                figures.append({
                    "path": cluster_path,
                    "caption": (
                        f"Cluster {cluster['cluster_id']}: {pattern_label} "
                        f"({cluster['member_count']} PTM sites, "
                        f"mean r={cluster['correlation_mean']:.2f}). "
                        f"{bio_summary}"
                    ),
                    "type": "cluster_detail",
                    "cluster_id": cluster["cluster_id"],
                })
        except Exception as e:
            logger.warning(f"Cluster {cluster['cluster_id']} plot failed: {e}")

    # Supplementary cluster figures (after main)
    for cluster in supp_clusters:
        try:
            cluster_path = _generate_cluster_lineplot(
                cluster, timepoints, output_dir
            )
            if cluster_path:
                ann = cluster.get("annotations", {})
                bio_summary = ann.get("biological_summary", "")
                pattern_label = _pattern_display_name(cluster["pattern"], ptm_type)
                figures.append({
                    "path": cluster_path,
                    "caption": (
                        f"Cluster {cluster['cluster_id']}: {pattern_label} "
                        f"({cluster['member_count']} PTM sites, "
                        f"mean r={cluster['correlation_mean']:.2f}). "
                        f"{bio_summary}"
                    ),
                    "type": "supplementary_cluster",
                    "cluster_id": cluster["cluster_id"],
                })
        except Exception as e:
            logger.warning(f"Supplementary cluster {cluster['cluster_id']} plot failed: {e}")

    return figures


# ═══════════════════════════════════════════════════════════════════════════
# v8.4: NATURE-STYLE TRANSIENT BURST COMPOSITE FIGURE (Fig 1)
# ═══════════════════════════════════════════════════════════════════════════

# Nature-inspired color palette (colorblind-safe, high contrast)
_NATURE_COLORS = [
    "#E64B35",  # Vermillion (Nature Red)
    "#4DBBD5",  # Cyan
    "#00A087",  # Teal
    "#3C5488",  # Indigo
    "#F39B7F",  # Salmon
    "#8491B4",  # Slate
    "#91D1C2",  # Mint
    "#DC9A6C",  # Amber
    "#7E6148",  # Brown
    "#B09C85",  # Taupe
]

# ── v9.28: Activity Class visual encoding ──
# De novo: orange palette (newly induced, no control signal)
# Regulated: blue palette (statistically significant, q<0.05 & |FC|≥1)
# Minor: green palette (sub-threshold but patterned changes)
_ACTIVITY_CLASS_COLORS = {
    "de_novo": [
        "#E65100", "#F57C00", "#FB8C00", "#FFA726", "#FFB74D",
        "#FFCC80", "#D84315", "#BF360C", "#FF6D00", "#FF9100",
    ],
    "regulated": [
        "#1565C0", "#1976D2", "#1E88E5", "#2196F3", "#42A5F5",
        "#64B5F6", "#0D47A1", "#1A237E", "#2962FF", "#448AFF",
    ],
    "minor": [
        "#4CAF50", "#66BB6A", "#81C784", "#A5D6A7", "#2E7D32",
        "#388E3C", "#43A047", "#56985A", "#6DAF71", "#7BC67F",
    ],
}
_ACTIVITY_CLASS_MARKERS = {
    "de_novo": "*",      # star
    "regulated": "o",    # circle
    "minor": "D",        # thin diamond
}
_ACTIVITY_CLASS_LINEWIDTH = {
    "de_novo": 1.4,
    "regulated": 1.4,
    "minor": 1.2,
}
_ACTIVITY_CLASS_ALPHA = {
    "de_novo": 0.85,
    "regulated": 0.80,
    "minor": 0.65,
}
_ACTIVITY_CLASS_LINESTYLE = {
    "de_novo": "-",
    "regulated": "-",
    "minor": "-",
}
_ACTIVITY_CLASS_MARKER_SIZE = {
    "de_novo": 40,   # star needs bigger size
    "regulated": 18,
    "minor": 14,
}
_ACTIVITY_CLASS_LABEL = {
    "de_novo": "De novo",
    "regulated": "Regulated",
    "minor": "Minor",
}


def _generate_transient_burst_figure(
    burst_clusters: list, timepoints: list, output_dir: str
) -> Optional[str]:
    """Generate a Nature-style composite figure for transient burst clusters.

    Panel layout:
        (a) Time-series profiles — individual PTM lines colored by cluster,
            with bold cluster mean and shaded min-max envelope.
        (b) Peak amplitude profiles — smooth Gaussian curves ranked by |Log2FC|.
        (c) Cluster mean envelope — overlaid mean profiles with fill_between.

    Style: Nature journals — serif labels, minimal gridlines, panel letters,
    300 DPI, white background, thin spines.
    """
    if not burst_clusters:
        return None

    # ── Collect all members across burst clusters ──
    all_members = []  # (member_detail, cluster_idx, cluster_id)
    for ci, cluster in enumerate(burst_clusters):
        for md in cluster["member_details"]:
            all_members.append((md, ci, cluster["cluster_id"]))

    if not all_members:
        return None

    # ── Matplotlib Nature style setup ──
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Times New Roman", "serif"],
        "font.size": 9,
        "axes.linewidth": 0.6,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7,
        "legend.frameon": True,
        "legend.edgecolor": "0.8",
        "legend.fancybox": False,
    })

    x = list(range(len(timepoints)))
    n_clusters = len(burst_clusters)

    # Determine layout based on member count
    has_panel_c = n_clusters >= 2  # Only show envelope comparison if multiple clusters
    n_panels = 3 if has_panel_c else 2

    if has_panel_c:
        fig = plt.figure(figsize=(14, 10))
        gs = gridspec.GridSpec(
            2, 2, figure=fig,
            width_ratios=[3, 1.2],
            height_ratios=[1, 1],
            hspace=0.35, wspace=0.30
        )
        ax_a = fig.add_subplot(gs[0, :])
        ax_b = fig.add_subplot(gs[1, 0])
        ax_c = fig.add_subplot(gs[1, 1])
    else:
        fig = plt.figure(figsize=(14, 5.5))
        gs = gridspec.GridSpec(
            1, 2, figure=fig,
            width_ratios=[3, 1.2],
            hspace=0.30, wspace=0.30
        )
        ax_a = fig.add_subplot(gs[0, 0])
        ax_b = fig.add_subplot(gs[0, 1])
        ax_c = None

    # ══════════════════════════════════════════════════════════════════════
    # Panel (a): Time-series profiles — v9.28 activity_class color encoding
    # De novo = orange solid ★, Regulated = blue solid ●, Minor = green solid ◆
    # ══════════════════════════════════════════════════════════════════════
    # Track per-class color index for distinct shades within each class
    _class_color_idx = {"de_novo": 0, "regulated": 0, "minor": 0}
    x_arr = np.array(x, dtype=float)
    # Smooth interpolation x-axis (200 points)
    x_smooth = np.linspace(x_arr[0], x_arr[-1], 200) if len(x_arr) >= 4 else x_arr

    # v9.28: Draw Minor first (background), then Regulated, then De novo (foreground)
    draw_order = ["minor", "regulated", "de_novo"]
    zorder_base = {"minor": 2, "regulated": 4, "de_novo": 6}

    for draw_class in draw_order:
        for ci, cluster in enumerate(burst_clusters):
            members = cluster["member_details"]
            for mi, md in enumerate(members):
                ac = md.get("activity_class", "minor")
                if ac != draw_class:
                    continue
                vals = np.array([md["temporal_values"].get(tp, 0) for tp in timepoints], dtype=float)
                # Pick color from activity class palette
                palette = _ACTIVITY_CLASS_COLORS.get(ac, _ACTIVITY_CLASS_COLORS["minor"])
                color_idx = _class_color_idx[ac] % len(palette)
                member_color = palette[color_idx]
                _class_color_idx[ac] += 1
                lw = _ACTIVITY_CLASS_LINEWIDTH.get(ac, 1.0)
                alpha = _ACTIVITY_CLASS_ALPHA.get(ac, 0.6)
                ls = _ACTIVITY_CLASS_LINESTYLE.get(ac, "-")
                marker = _ACTIVITY_CLASS_MARKERS.get(ac, "o")
                ms = _ACTIVITY_CLASS_MARKER_SIZE.get(ac, 14)
                zo = zorder_base.get(ac, 3)
                label = md["key"] if len(all_members) <= 15 else (md["key"] if _class_color_idx[ac] <= 5 else None)

                # Smooth spline interpolation
                if len(x_arr) >= 4:
                    try:
                        spl = make_interp_spline(x_arr, vals, k=3)
                        vals_smooth = spl(x_smooth)
                        ax_a.plot(
                            x_smooth, vals_smooth, linewidth=lw,
                            alpha=alpha, color=member_color, label=label,
                            linestyle=ls, zorder=zo,
                        )
                    except Exception:
                        ax_a.plot(x, vals, linewidth=lw, alpha=alpha, color=member_color,
                                  label=label, linestyle=ls, zorder=zo)
                else:
                    ax_a.plot(x, vals, linewidth=lw, alpha=alpha, color=member_color,
                              label=label, linestyle=ls, zorder=zo)
                # Markers at actual data points
                ax_a.scatter(x, vals, s=ms, color=member_color, alpha=alpha,
                             zorder=zo + 1, edgecolors="white", linewidths=0.3,
                             marker=marker)

    # v9.28: Cluster mean and envelope drawn AFTER all members (outside draw_order loop)
    for ci, cluster in enumerate(burst_clusters):
        cluster_base_color = _NATURE_COLORS[ci % len(_NATURE_COLORS)]
        members = cluster["member_details"]

        # Cluster mean (bold smooth line)
        mean_vals = np.array([cluster["mean_profile"].get(tp, 0) for tp in timepoints], dtype=float)
        if len(x_arr) >= 4:
            try:
                spl_mean = make_interp_spline(x_arr, mean_vals, k=3)
                mean_smooth = spl_mean(x_smooth)
                ax_a.plot(
                    x_smooth, mean_smooth, linewidth=2.5,
                    color=cluster_base_color, alpha=0.95, zorder=10,
                    label=f"Cluster {cluster['cluster_id']} Mean",
                )
            except Exception:
                ax_a.plot(x, mean_vals, linewidth=2.5, color=cluster_base_color, alpha=0.95, zorder=10,
                          label=f"Cluster {cluster['cluster_id']} Mean")
        else:
            ax_a.plot(x, mean_vals, linewidth=2.5, color=cluster_base_color, alpha=0.95, zorder=10,
                      label=f"Cluster {cluster['cluster_id']} Mean")
        ax_a.scatter(x, mean_vals, s=25, color=cluster_base_color, alpha=0.95, zorder=11, edgecolors="white", linewidths=0.5)

        # Shaded envelope (min-max range) — smooth
        all_vals_arr = np.array([
            [md["temporal_values"].get(tp, 0) for tp in timepoints]
            for md in members
        ], dtype=float)
        if all_vals_arr.shape[0] > 1:
            min_vals = np.min(all_vals_arr, axis=0)
            max_vals = np.max(all_vals_arr, axis=0)
            if len(x_arr) >= 4:
                try:
                    spl_min = make_interp_spline(x_arr, min_vals, k=3)
                    spl_max = make_interp_spline(x_arr, max_vals, k=3)
                    ax_a.fill_between(x_smooth, spl_min(x_smooth), spl_max(x_smooth), alpha=0.10, color=cluster_base_color)
                except Exception:
                    ax_a.fill_between(x, min_vals, max_vals, alpha=0.10, color=cluster_base_color)
            else:
                ax_a.fill_between(x, min_vals, max_vals, alpha=0.10, color=cluster_base_color)

    ax_a.axhline(y=0, color="#888888", linewidth=0.4, linestyle="-")
    ax_a.set_xticks(x)
    ax_a.set_xticklabels(timepoints, rotation=0)
    ax_a.set_xlabel("Time point")
    ax_a.set_ylabel("PTM Log\u2082FC")
    ax_a.spines["top"].set_visible(False)
    ax_a.spines["right"].set_visible(False)
    ax_a.grid(axis="y", alpha=0.15, linewidth=0.3)

    # v9.28: Build legend with activity class section headers
    # First: class legend icons (De novo ★, Regulated ●, Minor ◆)
    class_handles = []
    for cls_key, cls_label in [("de_novo", "De novo"), ("regulated", "Regulated"), ("minor", "Minor")]:
        cls_palette = _ACTIVITY_CLASS_COLORS[cls_key]
        cls_marker = _ACTIVITY_CLASS_MARKERS[cls_key]
        cls_ls = _ACTIVITY_CLASS_LINESTYLE[cls_key]
        cls_lw = _ACTIVITY_CLASS_LINEWIDTH[cls_key]
        class_handles.append(Line2D(
            [0], [0], marker=cls_marker, markersize=7 if cls_key == "de_novo" else 5,
            color=cls_palette[0], linewidth=cls_lw, linestyle=cls_ls,
            label=cls_label, markerfacecolor=cls_palette[0],
        ))
    # Then: cluster mean handles
    for ci, cluster in enumerate(burst_clusters):
        cluster_base_color = _NATURE_COLORS[ci % len(_NATURE_COLORS)]
        class_handles.append(Line2D(
            [0], [0], linewidth=2.5, color=cluster_base_color,
            label=f"Cluster {cluster['cluster_id']} Mean",
        ))
    # Separator
    class_handles.append(Line2D([0], [0], linewidth=0, label="────────────"))
    # Individual PTM handles (up to 12)
    handles, labels = ax_a.get_legend_handles_labels()
    # Filter out cluster mean handles (already added above)
    ptm_handles = [(h, l) for h, l in zip(handles, labels) if "Mean" not in l]
    for h, l in ptm_handles[:12]:
        class_handles.append(h)
    if len(ptm_handles) > 12:
        class_handles.append(Line2D([0], [0], linewidth=0,
                                    label=f"... +{len(ptm_handles) - 12} more"))
    ax_a.legend(
        handles=class_handles, loc="upper left", bbox_to_anchor=(1.01, 1.0),
        ncol=1, framealpha=0.95, borderaxespad=0,
        handlelength=1.5, columnspacing=0.8, fontsize=6.5,
    )

    # Panel label
    ax_a.text(
        -0.03, 1.05, "a", transform=ax_a.transAxes,
        fontsize=14, fontweight="bold", va="bottom", ha="right",
    )

    # ══════════════════════════════════════════════════════════════════════
    # Panel (b): Peak Amplitude — smooth Gaussian curves (no fill)
    # ══════════════════════════════════════════════════════════════════════
    # Sort all members by peak |Log2FC| descending
    sorted_members = sorted(all_members, key=lambda m: m[0]["max_fc"], reverse=True)
    top_n = min(15, len(sorted_members))
    top_members = sorted_members[:top_n]

    # Build smooth peak curves: each PTM is a Gaussian curve (outline only)
    # X-axis = ranked position, Y-axis = peak height (|Log2FC|)
    n_points = 800
    x_chrom = np.linspace(0, top_n + 1, n_points)

    peak_positions = []  # for annotation
    for pi, (md, ci, cid) in enumerate(top_members):
        center = pi + 1.0  # peak center position
        sigma = 0.28  # peak width (smooth curve)
        height = md["max_fc"]
        # Gaussian peak curve
        peak = height * np.exp(-0.5 * ((x_chrom - center) / sigma) ** 2)
        # v9.28: Use activity_class color instead of cluster color
        ac = md.get("activity_class", "minor")
        ac_palette = _ACTIVITY_CLASS_COLORS.get(ac, _ACTIVITY_CLASS_COLORS["minor"])
        color = ac_palette[pi % len(ac_palette)]

        # Smooth curve outline only — no fill
        lw = 1.4 if ac != "minor" else 0.8
        alpha_val = 0.85 if ac != "minor" else 0.45
        ax_b.plot(x_chrom, peak, color=color, linewidth=lw, alpha=alpha_val)
        peak_positions.append((center, height, md["key"], color))

    # Annotate peak labels
    for center, height, label, color in peak_positions:
        ax_b.annotate(
            label, xy=(center, height), xytext=(center, height + 0.3),
            fontsize=5.5, ha="center", va="bottom", rotation=55,
            color="#333333",
        )

    ax_b.set_xlim(0, top_n + 1)
    ax_b.set_ylim(0, None)
    ax_b.set_xlabel("PTM Sites (ranked by amplitude)")
    ax_b.set_ylabel("Peak |Log\u2082FC|")
    ax_b.set_xticks([])
    ax_b.spines["top"].set_visible(False)
    ax_b.spines["right"].set_visible(False)
    ax_b.grid(axis="y", alpha=0.15, linewidth=0.3)

    ax_b.text(
        -0.08, 1.05, "b", transform=ax_b.transAxes,
        fontsize=14, fontweight="bold", va="bottom", ha="right",
    )

    # ══════════════════════════════════════════════════════════════════════
    # Panel (c): Cluster mean envelope comparison
    # ══════════════════════════════════════════════════════════════════════
    if ax_c and has_panel_c:
        for ci, cluster in enumerate(burst_clusters):
            color = _NATURE_COLORS[ci % len(_NATURE_COLORS)]
            mean_vals = np.array([cluster["mean_profile"].get(tp, 0) for tp in timepoints], dtype=float)
            members = cluster["member_details"]

            # Smooth spline for mean
            if len(x_arr) >= 4:
                try:
                    spl_c = make_interp_spline(x_arr, mean_vals, k=3)
                    ax_c.plot(
                        x_smooth, spl_c(x_smooth), linewidth=1.8,
                        color=color, alpha=0.9,
                        label=f"C{cluster['cluster_id']} ({cluster['member_count']} sites)",
                    )
                except Exception:
                    ax_c.plot(x, mean_vals, linewidth=1.8, color=color, alpha=0.9,
                              label=f"C{cluster['cluster_id']} ({cluster['member_count']} sites)")
            else:
                ax_c.plot(x, mean_vals, linewidth=1.8, color=color, alpha=0.9,
                          label=f"C{cluster['cluster_id']} ({cluster['member_count']} sites)")
            ax_c.scatter(x, mean_vals, s=18, color=color, alpha=0.9, zorder=5, edgecolors="white", linewidths=0.3)

            # Envelope — smooth
            all_vals = np.array([
                [md["temporal_values"].get(tp, 0) for tp in timepoints]
                for md in members
            ], dtype=float)
            if all_vals.shape[0] > 1:
                min_v = np.min(all_vals, axis=0)
                max_v = np.max(all_vals, axis=0)
                if len(x_arr) >= 4:
                    try:
                        spl_min_c = make_interp_spline(x_arr, min_v, k=3)
                        spl_max_c = make_interp_spline(x_arr, max_v, k=3)
                        ax_c.fill_between(x_smooth, spl_min_c(x_smooth), spl_max_c(x_smooth), alpha=0.12, color=color)
                    except Exception:
                        ax_c.fill_between(x, min_v, max_v, alpha=0.12, color=color)
                else:
                    ax_c.fill_between(x, min_v, max_v, alpha=0.12, color=color)

        ax_c.axhline(y=0, color="#888888", linewidth=0.4, linestyle="-")
        ax_c.set_xticks(x)
        ax_c.set_xticklabels(timepoints, rotation=0)
        ax_c.set_xlabel("Time point")
        ax_c.set_ylabel("Mean Log\u2082FC")
        ax_c.spines["top"].set_visible(False)
        ax_c.spines["right"].set_visible(False)
        ax_c.grid(axis="y", alpha=0.15, linewidth=0.3)
        ax_c.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0),
                    framealpha=0.95, fontsize=6.5, borderaxespad=0)

        ax_c.text(
            -0.08, 1.05, "c", transform=ax_c.transAxes,
            fontsize=14, fontweight="bold", va="bottom", ha="right",
        )

    # ── Save ──
    path = os.path.join(output_dir, "fig1_transient_burst.png")
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white", pad_inches=0.3)
    plt.close(fig)

    # Reset rcParams to defaults
    plt.rcParams.update(plt.rcParamsDefault)
    matplotlib.use("Agg")

    logger.info(
        f"[COMOVEMENT] Transient burst figure saved: {path} "
        f"({len(burst_clusters)} clusters, {len(all_members)} members)"
    )
    return path


def _generate_summary_heatmap(
    clusters: list, singletons: list, timepoints: list,
    matrix: np.ndarray, meta: list, output_dir: str
) -> Optional[str]:
    """Generate a clustered heatmap of all significant PTMs."""
    # Reorder matrix by cluster membership
    ordered_indices = []
    cluster_boundaries = []
    cluster_labels = []

    key_to_idx = {m["key"]: i for i, m in enumerate(meta)}

    for cluster in clusters:
        start = len(ordered_indices)
        for md in cluster["member_details"]:
            idx = key_to_idx.get(md["key"])
            if idx is not None:
                ordered_indices.append(idx)
        end = len(ordered_indices)
        if end > start:
            cluster_boundaries.append((start, end))
            cluster_labels.append(f"C{cluster['cluster_id']}")

    # Add singletons
    singleton_start = len(ordered_indices)
    for s in singletons:
        idx = key_to_idx.get(s["key"])
        if idx is not None:
            ordered_indices.append(idx)
    if len(ordered_indices) > singleton_start:
        cluster_boundaries.append((singleton_start, len(ordered_indices)))
        cluster_labels.append("Uncl.")

    if not ordered_indices:
        return None

    ordered_matrix = matrix[ordered_indices]
    ordered_meta = [meta[i] for i in ordered_indices]

    # Create figure — v9.28: added activity_class sidebar
    n_rows = len(ordered_indices)
    fig_height = max(6, min(20, n_rows * 0.35 + 2))
    fig_width = max(8, len(timepoints) * 0.8 + 5)

    fig, (ax_sidebar, ax_ac_sidebar, ax_heatmap, ax_cbar) = plt.subplots(
        1, 4, figsize=(fig_width, fig_height),
        gridspec_kw={"width_ratios": [0.3, 0.15, 6, 0.3], "wspace": 0.02}
    )

    # Heatmap
    vmax = min(np.max(np.abs(ordered_matrix)), 25)
    im = ax_heatmap.imshow(
        ordered_matrix, aspect="auto", cmap="RdBu_r",
        vmin=-vmax, vmax=vmax, interpolation="nearest"
    )

    # X-axis: timepoints
    ax_heatmap.set_xticks(range(len(timepoints)))
    ax_heatmap.set_xticklabels(timepoints, fontsize=9, rotation=45, ha="right")
    ax_heatmap.set_xlabel("Timepoint", fontsize=11)

    # Y-axis: PTM names
    ax_heatmap.set_yticks(range(n_rows))
    ax_heatmap.set_yticklabels(
        [m["key"] for m in ordered_meta], fontsize=7
    )

    ax_heatmap.set_title(
        "Temporal PTM Coordination Analysis",
        fontsize=13, fontweight="normal", pad=12
    )

    # Cluster sidebar
    ax_sidebar.set_xlim(0, 1)
    ax_sidebar.set_ylim(n_rows - 0.5, -0.5)
    ax_sidebar.axis("off")

    for i, (start, end) in enumerate(cluster_boundaries):
        color = CLUSTER_COLORS[i % len(CLUSTER_COLORS)] if i < len(clusters) else "#CCCCCC"
        ax_sidebar.fill_between(
            [0, 1], start - 0.5, end - 0.5,
            color=color, alpha=0.6
        )
        mid = (start + end) / 2
        ax_sidebar.text(
            0.5, mid, cluster_labels[i],
            ha="center", va="center", fontsize=8,
            fontweight="normal", color="white"
        )

    # Colorbar
    plt.colorbar(im, cax=ax_cbar, label="Log2FC")

    # v9.28: Activity class sidebar (De novo=orange, Regulated=blue, Minor=green)
    _AC_SIDEBAR_COLORS = {
        "de_novo": "#E65100",
        "regulated": "#1565C0",
        "minor": "#4CAF50",
    }
    ax_ac_sidebar.set_xlim(0, 1)
    ax_ac_sidebar.set_ylim(n_rows - 0.5, -0.5)
    ax_ac_sidebar.axis("off")
    for row_i, m in enumerate(ordered_meta):
        ac = m.get("activity_class", "minor")
        ac_color = _AC_SIDEBAR_COLORS.get(ac, "#CCCCCC")
        ax_ac_sidebar.fill_between(
            [0, 1], row_i - 0.5, row_i + 0.5,
            color=ac_color, alpha=0.8
        )
    # Activity class sidebar title
    ax_ac_sidebar.set_title("Class", fontsize=7, pad=2)

    # Draw cluster boundaries on heatmap
    for start, end in cluster_boundaries:
        ax_heatmap.axhline(y=start - 0.5, color="white", linewidth=1.5)

    plt.tight_layout()
    path = os.path.join(output_dir, "comovement_heatmap.png")
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _generate_cluster_lineplot(
    cluster: dict, timepoints: list, output_dir: str
) -> Optional[str]:
    """Generate a detailed line plot for a single cluster."""
    members = cluster["member_details"]
    nonptm_links = cluster.get("nonptm_links", [])
    has_nonptm = len(nonptm_links) > 0

    # Figure layout: PTM lines on top, Non-PTM on bottom (if available)
    if has_nonptm:
        fig, (ax_ptm, ax_nonptm) = plt.subplots(
            2, 1, figsize=(10, 7), height_ratios=[3, 2],
            sharex=True, gridspec_kw={"hspace": 0.15}
        )
    else:
        fig, ax_ptm = plt.subplots(1, 1, figsize=(10, 5))
        ax_nonptm = None

    x = list(range(len(timepoints)))
    x_arr = np.array(x, dtype=float)
    # Smooth interpolation x-axis
    x_smooth = np.linspace(x_arr[0], x_arr[-1], 200) if len(x_arr) >= 4 else x_arr

    # v9.28: Activity class-based color/marker/style for individual PTM members
    _class_color_idx = {"de_novo": 0, "regulated": 0, "minor": 0}
    draw_order = ["minor", "regulated", "de_novo"]
    zorder_base = {"minor": 2, "regulated": 4, "de_novo": 6}

    # ── PTM member lines (v9.28: activity_class encoding) ──
    for draw_class in draw_order:
        for md in members:
            ac = md.get("activity_class", "minor")
            if ac != draw_class:
                continue
            vals = np.array([md["temporal_values"].get(tp, 0) for tp in timepoints], dtype=float)
            palette = _ACTIVITY_CLASS_COLORS.get(ac, _ACTIVITY_CLASS_COLORS["minor"])
            color_idx = _class_color_idx[ac] % len(palette)
            color = palette[color_idx]
            _class_color_idx[ac] += 1
            lw = _ACTIVITY_CLASS_LINEWIDTH.get(ac, 1.0)
            alpha = _ACTIVITY_CLASS_ALPHA.get(ac, 0.6)
            ls = _ACTIVITY_CLASS_LINESTYLE.get(ac, "-")
            marker = _ACTIVITY_CLASS_MARKERS.get(ac, "o")
            ms = _ACTIVITY_CLASS_MARKER_SIZE.get(ac, 14)
            zo = zorder_base.get(ac, 3)

            # Smooth spline interpolation
            if len(x_arr) >= 4:
                try:
                    spl = make_interp_spline(x_arr, vals, k=3)
                    vals_smooth = spl(x_smooth)
                    ax_ptm.plot(x_smooth, vals_smooth, linewidth=lw,
                                alpha=alpha, color=color, label=md["key"],
                                linestyle=ls, zorder=zo)
                except Exception:
                    ax_ptm.plot(x, vals, linewidth=lw, alpha=alpha, color=color,
                                label=md["key"], linestyle=ls, zorder=zo)
            else:
                ax_ptm.plot(x, vals, linewidth=lw, alpha=alpha, color=color,
                            label=md["key"], linestyle=ls, zorder=zo)
            # Markers at actual data points
            ax_ptm.scatter(x, vals, s=ms, color=color, alpha=alpha,
                           zorder=zo + 1, edgecolors="white", linewidths=0.3,
                           marker=marker)

    # Cluster mean (thick dashed, smooth)
    mean_vals = np.array([cluster["mean_profile"].get(tp, 0) for tp in timepoints], dtype=float)
    if len(x_arr) >= 4:
        try:
            spl_mean = make_interp_spline(x_arr, mean_vals, k=3)
            ax_ptm.plot(x_smooth, spl_mean(x_smooth), "--", linewidth=2.5, color="#333333",
                        alpha=0.8, label="Cluster Mean", zorder=10)
        except Exception:
            ax_ptm.plot(x, mean_vals, "--", linewidth=2.5, color="#333333", alpha=0.8,
                        label="Cluster Mean", zorder=10)
    else:
        ax_ptm.plot(x, mean_vals, "--", linewidth=2.5, color="#333333", alpha=0.8,
                    label="Cluster Mean", zorder=10)
    ax_ptm.scatter(x, mean_vals, s=20, color="#333333", alpha=0.8, zorder=11,
                   edgecolors="white", linewidths=0.3)

    ax_ptm.axhline(y=0, color="gray", linewidth=0.5, linestyle=":")
    ax_ptm.set_ylabel("PTM Log2FC", fontsize=11)
    ax_ptm.grid(True, alpha=0.2)

    # v9.28: Legend with activity class section headers
    legend_handles = []
    for cls_key, cls_label in [("de_novo", "De novo"), ("regulated", "Regulated"), ("minor", "Minor")]:
        cls_palette = _ACTIVITY_CLASS_COLORS[cls_key]
        cls_marker = _ACTIVITY_CLASS_MARKERS[cls_key]
        cls_ls = _ACTIVITY_CLASS_LINESTYLE[cls_key]
        cls_lw = _ACTIVITY_CLASS_LINEWIDTH[cls_key]
        legend_handles.append(Line2D(
            [0], [0], marker=cls_marker, markersize=7 if cls_key == "de_novo" else 5,
            color=cls_palette[0], linewidth=cls_lw, linestyle=cls_ls,
            label=cls_label, markerfacecolor=cls_palette[0],
        ))
    legend_handles.append(Line2D([0], [0], linestyle="--", linewidth=2.5,
                                  color="#333333", label="Cluster Mean"))
    legend_handles.append(Line2D([0], [0], linewidth=0, label="────────────"))
    # Individual PTM handles (up to 12)
    handles, labels = ax_ptm.get_legend_handles_labels()
    ptm_handles = [(h, l) for h, l in zip(handles, labels) if l not in ("Cluster Mean",)]
    for h, l in ptm_handles[:12]:
        legend_handles.append(h)
    if len(ptm_handles) > 12:
        legend_handles.append(Line2D([0], [0], linewidth=0,
                                     label=f"... +{len(ptm_handles) - 12} more"))
    ax_ptm.legend(handles=legend_handles, fontsize=6.5, loc="upper left",
                  bbox_to_anchor=(1.01, 1.0), ncol=1, framealpha=0.95,
                  borderaxespad=0)

    # Title with biological annotation
    ann = cluster.get("annotations", {})
    bio_summary = ann.get("biological_summary", "")
    pattern_label = _pattern_display_name(cluster["pattern"])
    # v9.28: Include activity class composition in title
    ac_counts = cluster.get("activity_class_counts", {})
    ac_parts = []
    if ac_counts.get("de_novo", 0) > 0:
        ac_parts.append(f"★{ac_counts['de_novo']} De novo")
    if ac_counts.get("regulated", 0) > 0:
        ac_parts.append(f"●{ac_counts['regulated']} Regulated")
    if ac_counts.get("minor", 0) > 0:
        ac_parts.append(f"◆{ac_counts['minor']} Minor")
    ac_str = " | ".join(ac_parts) if ac_parts else ""
    title = (
        f"Cluster {cluster['cluster_id']}: {pattern_label}\n"
        f"{cluster['member_count']} PTM sites | "
        f"Mean correlation: {cluster['correlation_mean']:.2f} | "
        f"Peak: {cluster['peak_timepoint']}"
    )
    if ac_str:
        title += f"\n{ac_str}"
    if bio_summary:
        title += f"\n{bio_summary}"
    ax_ptm.set_title(title, fontsize=10, fontweight="normal", loc="left", pad=8)

    # ── Non-PTM interactor lines (smooth spline, distinct colors) ──
    _NONPTM_COLORS = [
        "#636363", "#969696", "#525252", "#737373", "#A8A8A8",
        "#4A4A4A", "#8C8C8C", "#5E5E5E",
    ]
    if ax_nonptm and nonptm_links:
        for i, link in enumerate(nonptm_links[:8]):
            vals = np.array([link["temporal_profile"].get(tp, 0) for tp in timepoints], dtype=float)
            color = _NONPTM_COLORS[i % len(_NONPTM_COLORS)]
            label = f"{link['gene']} (r={link['correlation_with_cluster']:.2f})"
            # Smooth spline
            if len(x_arr) >= 4:
                try:
                    spl_np = make_interp_spline(x_arr, vals, k=3)
                    ax_nonptm.plot(x_smooth, spl_np(x_smooth), linewidth=1.0,
                                   alpha=0.7, color=color, linestyle="--", label=label)
                except Exception:
                    ax_nonptm.plot(x, vals, linewidth=1.0, alpha=0.7, color=color, linestyle="--", label=label)
            else:
                ax_nonptm.plot(x, vals, linewidth=1.0, alpha=0.7, color=color, linestyle="--", label=label)
            ax_nonptm.scatter(x, vals, s=12, color=color, alpha=0.7, zorder=5, marker="s", edgecolors="white", linewidths=0.3)

        ax_nonptm.axhline(y=0, color="gray", linewidth=0.5, linestyle=":")
        ax_nonptm.set_ylabel("Non-PTM Protein Log2FC", fontsize=10)
        ax_nonptm.set_xlabel("Timepoint", fontsize=11)
        ax_nonptm.grid(True, alpha=0.2)
        ax_nonptm.legend(fontsize=6.5, loc="upper left", bbox_to_anchor=(1.01, 1.0),
                          ncol=1, framealpha=0.95, borderaxespad=0)
        ax_nonptm.set_title(
            "Connected Non-PTM Interactors (Protein Abundance)",
            fontsize=9, fontweight="normal", loc="left"
        )

    # X-axis labels
    bottom_ax = ax_nonptm if ax_nonptm else ax_ptm
    bottom_ax.set_xticks(x)
    bottom_ax.set_xticklabels(timepoints, fontsize=9)
    bottom_ax.set_xlabel("Timepoint", fontsize=11)

    fig.subplots_adjust(right=0.82)
    path = os.path.join(
        output_dir, f"comovement_cluster_{cluster['cluster_id']}.png"
    )
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _pattern_display_name(pattern: str, ptm_type: str = "phosphorylation") -> str:
    """Convert pattern code to human-readable display name.

    v8.10: PTM-type-aware labels. For ubiquitylation, uses
    'Ubiquitylation Burst' instead of 'Phosphorylation Burst', etc.
    """
    pt = ptm_type.lower().strip()
    # PTM-specific burst/suppression labels
    _PTM_LABELS = {
        "phosphorylation": {
            "burst": "Transient Phosphorylation Burst",
            "suppression": "Transient Dephosphorylation",
        },
        "ubiquitylation": {
            "burst": "Transient Ubiquitylation Burst",
            "suppression": "Transient Deubiquitylation",
        },
        "acetylation": {
            "burst": "Transient Acetylation Burst",
            "suppression": "Transient Deacetylation",
        },
        "methylation": {
            "burst": "Transient Methylation Burst",
            "suppression": "Transient Demethylation",
        },
        "sumoylation": {
            "burst": "Transient SUMOylation Burst",
            "suppression": "Transient DeSUMOylation",
        },
    }
    labels = _PTM_LABELS.get(pt, {
        "burst": f"Transient {ptm_type.title()} Burst",
        "suppression": f"Transient De-{ptm_type.lower()}",
    })
    base = {
        "co_activated": "Co-activated",
        "co_inhibited": "Co-inhibited",
        "transient_burst": labels["burst"],
        "transient_suppression": labels["suppression"],
        "sustained_activation": "Sustained Activation",
        "sustained_inhibition": "Sustained Inhibition",
        "biphasic_switch": "Biphasic Switch",
        "sequential_wave": "Sequential Signaling Wave",
        "mixed_response": "Mixed Response",
    }
    return base.get(pattern, pattern.replace("_", " ").title())


# ═══════════════════════════════════════════════════════════════════════════
# STEP 8: LLM CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def _compute_multisite_divergence_for_report(
    sig_matrix: np.ndarray,
    sig_meta: list,
    timepoints: list,
    ptm_type: str = "phosphorylation",
    enriched_data: Optional[list] = None,
    clusters: Optional[list] = None,
) -> list:
    """Compute multi-site temporal divergence pairs for LLM report injection.

    Returns a list of dicts describing site pairs within the same protein that
    show divergent temporal patterns (signal attenuation, sequential regulation,
    or multisite coordination).

    v12.1 enhancements:
    - #1 covered_by_cowave flag: marks pairs where both sites belong to the same co-wave cluster
    - #2 disambiguation: interpretation + disambiguation_confidence fields based on motif/KS-db
    - #3 lag_minutes / lag_fraction / is_meaningful_lag (real time-based)
    - #4 confidence_tier (High/Medium/Low via MAD-based effect_size)
    - #5 resolution_warning (n_timepoints <= 3)
    - #6 permutation p_value + is_significant
    """
    if sig_matrix is None or len(sig_meta) < 2 or len(timepoints) < 3:
        return []

    n_timepoints = len(timepoints)

    # ── Parse real timepoints to minutes for #3 ──
    tp_minutes = []
    for tp in timepoints:
        tp_minutes.append(tp_to_minutes(tp))
    # If any timepoint is unparseable (-1), fall back to index-based
    _has_real_time = all(m >= 0 for m in tp_minutes)

    # ── Build PTM key → cluster mapping for #1 (covered_by_cowave) ──
    _ptm_cluster_map: Dict[str, int] = {}  # ptm_key -> cluster_id
    if clusters:
        for cl in clusters:
            cid = cl.get("cluster_id", 0)
            for md in cl.get("member_details", []):
                _ptm_cluster_map[md["key"]] = cid

    # ── Build enriched lookup for #2 (disambiguation) ──
    _enr_by_gene_site: Dict[str, dict] = {}  # "GENE SITE" -> enriched entry
    if enriched_data:
        for _ed in enriched_data:
            _g = _ed.get("gene") or _ed.get("Gene.Name", "")
            _p = str(_ed.get("position") or _ed.get("PTM_Position", ""))
            if _g and _p:
                _enr_by_gene_site[f"{_g} {_p}"] = _ed

    # Build per-gene site data
    gene_sites: Dict[str, List[dict]] = defaultdict(list)
    for i, meta in enumerate(sig_meta):
        gene = meta.get("gene", "")
        site = meta.get("site", "")
        if not gene or not site:
            continue
        values = sig_matrix[i].tolist()
        peak_idx = int(np.argmax(np.abs(sig_matrix[i])))
        peak_fc = float(sig_matrix[i][peak_idx])
        gene_sites[gene].append({
            "site": site,
            "key": meta.get("key", f"{gene}({site})"),
            "values": values,
            "peak_fc": peak_fc,
            "peak_tp": timepoints[peak_idx],
            "peak_tp_idx": peak_idx,
            "activity_class": meta.get("activity_class", "minor"),
            "is_de_novo": meta.get("control_pseudocount_used", False),
        })

    # ── Collect all |FC| values for MAD calculation (#4 confidence tier) ──
    all_fc_values = []
    for i in range(sig_matrix.shape[0]):
        for v in sig_matrix[i]:
            if abs(float(v)) > 0.01:
                all_fc_values.append(abs(float(v)))
    if all_fc_values:
        _median_fc = float(np.median(all_fc_values))
        _mad_fc = float(np.median([abs(x - _median_fc) for x in all_fc_values]))
        if _mad_fc < 0.1:
            _mad_fc = 0.1  # floor to avoid division by near-zero
    else:
        _median_fc = 0.0
        _mad_fc = 1.0

    results = []
    for gene, sites in gene_sites.items():
        if len(sites) < 2:
            continue
        # Only consider sites that are at least regulated or de_novo
        sig_sites = [s for s in sites if s["activity_class"] in ("regulated", "de_novo")]
        if len(sig_sites) < 1:
            continue
        # Generate all pairs (at least one must be regulated/de_novo)
        for i in range(len(sites)):
            for j in range(i + 1, len(sites)):
                sA = sites[i]
                sB = sites[j]
                # At least one must be regulated or de_novo
                if sA["activity_class"] == "minor" and sB["activity_class"] == "minor":
                    continue
                # Sort by peak time
                early, late = (sA, sB) if sA["peak_tp_idx"] <= sB["peak_tp_idx"] else (sB, sA)
                # Classify pattern
                same_wave = early["peak_tp_idx"] == late["peak_tp_idx"]
                early_act = early["peak_fc"] > 0
                late_act = late["peak_fc"] > 0
                if same_wave:
                    pattern = "multisite_coordination"
                    # v12.1 #2: Hedged language (hypothesis-level)
                    description = (
                        f"{gene} {early['site']} and {late['site']} peak simultaneously at "
                        f"{early['peak_tp']}, consistent with co-regulation by a single enzyme "
                        f"(multisite {ptm_type}) or a tightly coupled signaling complex "
                        f"(hypothesis; requires kinase assay validation)."
                    )
                elif early_act != late_act:
                    pattern = "signal_attenuation"
                    act_site = early if early_act else late
                    inh_site = late if early_act else early
                    description = (
                        f"{gene} {act_site['site']} activates early ({act_site['peak_tp']}, "
                        f"FC={act_site['peak_fc']:+.2f}) followed by {inh_site['site']} "
                        f"inhibitory signal at {inh_site['peak_tp']} (FC={inh_site['peak_fc']:+.2f}). "
                        f"This temporal pattern is consistent with signal attenuation or "
                        f"negative feedback, though alternative explanations cannot be excluded."
                    )
                else:
                    pattern = "sequential_regulation"
                    direction = "activating" if early_act else "inhibitory"
                    description = (
                        f"{gene} shows sequential {direction} regulation: {early['site']} peaks at "
                        f"{early['peak_tp']} (FC={early['peak_fc']:+.2f}), followed by {late['site']} "
                        f"at {late['peak_tp']} (FC={late['peak_fc']:+.2f}). This may indicate two "
                        f"independent kinases regulating this protein in temporal sequence, "
                        f"pending site-specific kinase validation."
                    )

                # ── #1: covered_by_cowave flag ──
                clusterA = _ptm_cluster_map.get(early["key"])
                clusterB = _ptm_cluster_map.get(late["key"])
                covered_by_cowave = (clusterA is not None and clusterB is not None
                                     and clusterA == clusterB)

                # ── #3: Real time-based lag ──
                delta_idx = abs(late["peak_tp_idx"] - early["peak_tp_idx"])
                lag_fraction = delta_idx / max(n_timepoints - 1, 1)
                if _has_real_time and delta_idx > 0:
                    lag_minutes = abs(tp_minutes[late["peak_tp_idx"]] - tp_minutes[early["peak_tp_idx"]])
                else:
                    lag_minutes = None  # cannot compute real lag
                # is_meaningful_lag: at least 1 step AND (if real time available) >= 5 min
                is_meaningful_lag = delta_idx >= 1 and (
                    lag_minutes is None or lag_minutes >= 5.0
                )

                # ── #4: Confidence tier (effect_size via MAD) ──
                effect_size = abs(early["peak_fc"] - late["peak_fc"]) / _mad_fc
                if effect_size >= 2.0:
                    confidence_tier = "High"
                elif effect_size >= 1.0:
                    confidence_tier = "Medium"
                else:
                    confidence_tier = "Low"

                # ── #5: Resolution warning ──
                resolution_warning = None
                if n_timepoints <= 3:
                    resolution_warning = (
                        f"LOW RESOLUTION: Only {n_timepoints} timepoints available. "
                        f"Pattern classification may be unreliable; interpret with caution."
                    )

                # ── #6: Permutation-based p-value ──
                p_value = None
                is_significant = None
                valuesA = np.array(early["values"])
                valuesB = np.array(late["values"])
                if len(valuesA) >= 3 and len(valuesB) >= 3:
                    observed_divergence = float(np.sum((valuesA - valuesB) ** 2))
                    n_perm = 1000
                    count_ge = 0
                    combined = np.concatenate([valuesA, valuesB])
                    half = len(valuesA)
                    rng = np.random.default_rng(seed=42)
                    for _ in range(n_perm):
                        perm = rng.permutation(combined)
                        perm_div = float(np.sum((perm[:half] - perm[half:]) ** 2))
                        if perm_div >= observed_divergence:
                            count_ge += 1
                    p_value = (count_ge + 1) / (n_perm + 1)  # +1 correction
                    is_significant = p_value < 0.05

                # ── #2: Disambiguation (motif/KS-db based) ──
                interpretation = "likely_independent_kinases"  # default
                disambiguation_confidence = "low"
                edA = _enr_by_gene_site.get(f"{gene} {early['site']}", {})
                edB = _enr_by_gene_site.get(f"{gene} {late['site']}", {})
                ragA = edA.get("rag_enrichment", {}) or {}
                ragB = edB.get("rag_enrichment", {}) or {}
                # Extract motif families
                motifA = str(edA.get("Enhanced_Matched_Motifs", "") or edA.get("Motifs", "")).lower()
                motifB = str(edB.get("Enhanced_Matched_Motifs", "") or edB.get("Motifs", "")).lower()
                # Extract known kinases
                ks_A = ragA.get("regulation", {}).get("kinase_substrate", []) if isinstance(ragA.get("regulation"), dict) else []
                ks_B = ragB.get("regulation", {}).get("kinase_substrate", []) if isinstance(ragB.get("regulation"), dict) else []
                kinases_A = {(k.get("kinase", "") if isinstance(k, dict) else str(k)).upper() for k in (ks_A or []) if k}
                kinases_B = {(k.get("kinase", "") if isinstance(k, dict) else str(k)).upper() for k in (ks_B or []) if k}
                shared_kinases = kinases_A & kinases_B

                # Check same motif family (proline-directed, basophilic, acidophilic)
                _motif_families = [
                    ("proline_directed", ["sp", "tp", "pxsp", "mapk", "cdk", "erk", "jnk"]),
                    ("basophilic", ["rxxs", "rxs", "akt", "pkc", "pka", "agc"]),
                    ("acidophilic", ["sxxe", "sxxd", "ck2", "ck1"]),
                ]
                familyA = set()
                familyB = set()
                for fam_name, keywords in _motif_families:
                    if any(kw in motifA for kw in keywords):
                        familyA.add(fam_name)
                    if any(kw in motifB for kw in keywords):
                        familyB.add(fam_name)

                same_motif_family = bool(familyA and familyB and familyA & familyB)

                if shared_kinases:
                    interpretation = "confirmed_single_kinase"
                    disambiguation_confidence = "high"
                elif same_motif_family and pattern == "multisite_coordination":
                    interpretation = "likely_distributive"
                    disambiguation_confidence = "medium"
                elif same_motif_family:
                    interpretation = "likely_same_kinase_family"
                    disambiguation_confidence = "medium"
                else:
                    interpretation = "likely_independent_kinases"
                    disambiguation_confidence = "low"

                results.append({
                    "gene": gene,
                    "siteA": early,
                    "siteB": late,
                    "pattern": pattern,
                    "description": description,
                    # v12.1 #1
                    "covered_by_cowave": covered_by_cowave,
                    # v12.1 #2
                    "interpretation": interpretation,
                    "disambiguation_confidence": disambiguation_confidence,
                    # v12.1 #3
                    "lag_minutes": round(lag_minutes, 1) if lag_minutes is not None else None,
                    "lag_fraction": round(lag_fraction, 3),
                    "is_meaningful_lag": is_meaningful_lag,
                    # v12.1 #4
                    "effect_size": round(effect_size, 3),
                    "confidence_tier": confidence_tier,
                    # v12.1 #5
                    "resolution_warning": resolution_warning,
                    # v12.1 #6
                    "p_value": round(p_value, 4) if p_value is not None else None,
                    "is_significant": is_significant,
                })
    return results


def _build_comovement_llm_context(
    clusters: list, singletons: list, timepoints: list,
    ptm_type: str = "phosphorylation",
    sig_matrix: Optional[np.ndarray] = None,
    sig_meta: Optional[list] = None,
    enriched_data: Optional[list] = None,
) -> str:
    """Build structured text for LLM injection into write_sections.

    v8.4: Transient burst clusters are presented first with detailed context.
    v8.10: PTM-type-aware labels and ubiquitylation-specific interpretation.
    v9.30: Multi-site temporal divergence analysis added.
    """
    if not clusters:
        return ""

    # Separate burst vs non-burst clusters
    burst_clusters = [c for c in clusters if c["pattern"] in
                      ("transient_burst", "transient_suppression")]
    other_clusters = [c for c in clusters if c["pattern"] not in
                      ("transient_burst", "transient_suppression")]

    # v8.9.3: Figure numbers for co-movement figures are main figures (Figure 2+).
    # Figure 1 = Pathway Distribution (from network_node).
    # Co-movement heatmap/burst = Figure 2, individual clusters = Figure 3+.
    # Cascade diagrams and Cytoscape networks are Supplementary Figures.
    fig_burst = 2  # Transient burst composite
    fig_cluster_start = 3  # Individual cluster plots start here
    all_clusters = burst_clusters + other_clusters  # v8.9.3: fix undefined all_ordered
    cluster_fig_map = {}  # cluster_id -> figure number
    for c in burst_clusters:
        cluster_fig_map[c["cluster_id"]] = fig_burst  # All burst clusters share Fig 2
    for i, c in enumerate(other_clusters):
        cluster_fig_map[c["cluster_id"]] = fig_cluster_start + i

    parts = [
        "\n## TEMPORAL PTM COORDINATION ANALYSIS\n",
        "Correlation-based hierarchical clustering of PTM Log2FC time-series "
        "profiles identified the following temporally coordinated substrate groups. Transient burst "
        f"clusters are the primary focus of this analysis (Figure {fig_burst}).\n",
    ]

    # ── PRIMARY FOCUS: Transient Burst Clusters (detailed) ──
    if burst_clusters:
        burst_label = _pattern_display_name("transient_burst", ptm_type)
        parts.append(f"### \u2605 PRIMARY: Transient {burst_label} Clusters")
        parts.append(
            f"{len(burst_clusters)} cluster(s) exhibited transient burst dynamics "
            f"(rapid activation followed by return to baseline). These are shown "
            f"in Figure {fig_burst} of the report.\n"
        )

    for cluster in burst_clusters:
        cfig = cluster_fig_map.get(cluster["cluster_id"], "?")
        _append_cluster_detail(parts, cluster, timepoints, is_primary=True, figure_num=cfig, ptm_type=ptm_type)

    # ── SECONDARY: Other pattern clusters (with individual figures) ──
    if other_clusters:
        parts.append("\n### Other Temporal Coordination Patterns")
        parts.append(
            f"{len(other_clusters)} additional cluster(s) with non-burst patterns "
            f"were detected. Each cluster has its own figure for detailed inspection.\n"
        )

    for cluster in other_clusters:
        cfig = cluster_fig_map.get(cluster["cluster_id"], "?")
        _append_cluster_detail(parts, cluster, timepoints, is_primary=False, figure_num=cfig, ptm_type=ptm_type)

    # ── Notable singletons ──
    notable_singletons = [s for s in singletons if s["max_fc"] >= 3.0]
    if notable_singletons:
        parts.append("\n### Notable Unclustered PTMs (unique temporal profiles)")
        for s in notable_singletons[:10]:
            profile_str = " \u2192 ".join(
                f"{tp}: {s['temporal_values'].get(tp, 0):+.1f}"
                for tp in timepoints
            )
            parts.append(
                f"- {s['key']}: max|FC|={s['max_fc']:.1f}, "
                f"peak={s['peak_tp']}, profile: {profile_str}"
            )
        parts.append("")

    # ── LLM Instructions (v8.4: transient burst focus + report coherence) ──
    parts.append(
        "\nCRITICAL INSTRUCTIONS FOR REPORT WRITING:\n"
        "\n"
        "1. TRANSIENT BURST AS CENTRAL THEME:\n"
        f"   - The transient {ptm_type} burst clusters MUST be the primary "
        "analytical focus of the Results section.\n"
        "   - Dedicate at least 2-3 paragraphs to interpreting the burst dynamics: "
        f"what triggers the rapid {ptm_type}, which {'E3 ligases are' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinases are'} likely responsible, "
        f"and why the signal returns to baseline ({'DUB activity' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'phosphatase activity'}, negative feedback).\n"
        f"   - Reference Figure {fig_burst} explicitly when discussing burst clusters.\n"
        "   - Name specific PTM proteins from the burst clusters and discuss their "
        "known biological roles in the context of the treatment.\n"
        "\n"
        "2. REPORT COHERENCE:\n"
        "   - The temporal burst analysis MUST connect logically to the network analysis "
        "and cascade diagrams discussed elsewhere in the report.\n"
        "   - If burst cluster members appear in the signaling network or cascade diagrams, "
        "explicitly note this convergence as supporting evidence.\n"
        "   - The Discussion section should synthesize burst findings with pathway-level "
        "insights from other analyses (network topology, validated hypotheses).\n"
        "   - The Abstract MUST mention the transient burst finding as a key result.\n"
        "\n"
        "3. FIGURE-TEXT COHERENCE (CRITICAL):\n"
        "   - Figure 1 = Canonical Pathway Distribution (from network analysis).\n"
        f"   - Figure {fig_burst} = Transient Burst Composite (panels a, b, c).\n"
        f"   - Figures {fig_cluster_start}-{fig_cluster_start + len(all_clusters) - 1} = "
        "Individual cluster time-series plots.\n"
        "   - Cascade diagrams and Cytoscape networks are in Supplementary Figures.\n"
        "   - When discussing each cluster, ALWAYS reference its specific Figure number.\n"
        "   - The text MUST describe what is shown in each figure; do NOT introduce "
        "figures without discussing their content in the text.\n"
        "\n"
        "4. NON-BURST CLUSTER PATTERNS (SYSTEMS BIOLOGY INTERPRETATION):\n"
        "   - Each non-burst cluster MUST be discussed with its Figure reference AND\n"
        "     its systems biology significance. Dedicate 1 paragraph per main cluster.\n"
        "   - SEQUENTIAL SIGNALING WAVE: Indicates a relay-type signal propagation\n"
        "     where PTMs are activated in temporal sequence. Discuss which PTMs lead\n"
        "     the wave vs. which follow, and infer the directionality of the signaling\n"
        f"     cascade (e.g., receptor \u2192 adaptor \u2192 effector). Relate to known {'E3 ligase-substrate' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase'}\n"
        "     substrate relationships if available.\n"
        "   - BIPHASIC SWITCH: Represents a regulatory toggle where PTMs switch from\n"
        "     activation to inhibition (or vice versa). Discuss the biological meaning\n"
        "     of this switch — e.g., negative feedback loops, pathway crosstalk, or\n"
        "     transition between early signaling and late adaptive responses.\n"
        "   - SUSTAINED ACTIVATION/INHIBITION: Indicates long-term regulatory changes\n"
        "     that persist beyond the initial stimulus. Discuss implications for\n"
        "     cellular commitment, gene expression regulation, or structural\n"
        "     remodeling processes.\n"
        "   - CO-ACTIVATED/CO-INHIBITED: PTMs that move together suggest shared\n"
        f"     upstream regulation (common {'E3 ligase/DUB' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase/phosphatase'}). Identify potential\n"
        "     shared regulators from the network analysis data.\n"
        "   - Compare and contrast these patterns with the transient burst to build\n"
        "     a coherent narrative of how the treatment orchestrates multiple\n"
        "     signaling layers over time.\n"
        "\n"
        "5. INTER-FIGURE SIGNALING RELATIONSHIPS (CRITICAL):\n"
        "   - The report MUST explain how Figures 2-6 relate to each other from a\n"
        "     cell signaling perspective. These figures are NOT independent observations;\n"
        "     they represent different temporal layers of a coordinated cellular response.\n"
        "   - Construct a SIGNALING TIMELINE narrative: e.g., 'The transient burst (Fig 2)\n"
        f"     represents the immediate {'E3 ligase' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase'} activation upon stimulus, while the sequential\n"
        "     wave (Fig 3) shows the downstream propagation of this signal through adaptor\n"
        "     and effector proteins. The biphasic switch (Fig 5) may reflect negative\n"
        "     feedback that terminates the initial burst, and sustained changes (Fig 6)\n"
        "     indicate commitment to long-term cellular responses.'\n"
        f"   - Identify SHARED PROTEINS or PATHWAYS across clusters \u2014 if the same {'E3 ligase' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase'}\n"
        "     appears in both burst and wave clusters, this is strong evidence for a\n"
        "     signaling cascade connecting them.\n"
        "   - Discuss the temporal order: which cluster peaks first? Which follows?\n"
        "     What does this sequence tell us about signal flow direction?\n"
        "\n"
        "6. NON-PTM PROTEIN INSIGHTS:\n"
        "   - If non-PTM interactor proteins are shown alongside PTM members in cluster\n"
        "     plots, their temporal profiles provide CRITICAL biological information.\n"
        "   - Discuss whether non-PTM protein abundance changes PRECEDE, COINCIDE WITH,\n"
        "     or FOLLOW the PTM changes — this reveals regulatory directionality.\n"
        "   - If a non-PTM protein shows correlated movement with PTM members, discuss\n"
        "     what this implies about protein complex formation, scaffold recruitment,\n"
        "     or co-regulation.\n"
        "   - If a non-PTM protein shows ANTI-correlated movement, discuss potential\n"
        "     degradation, translocation, or competitive binding mechanisms.\n"
        "   - Name specific non-PTM proteins and their known functions in the context\n"
        "     of the cell type and treatment being studied.\n"
        "\n"
        "7. CO-MOVING PEAK COMMONALITIES:\n"
        "   - For PTMs that peak at the SAME timepoint within a cluster, explicitly\n"
        "     discuss what they have in common:\n"
        f"     * Do they share a common upstream {'E3 ligase or DUB' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase or phosphatase'}?\n"
        "     * Are they on proteins in the same signaling complex or pathway?\n"
        "     * Do they have similar subcellular localization?\n"
        f"     * Are they known substrates of the same {'E3 ligase' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase'} family?\n"
        "   - For PTMs that peak at DIFFERENT timepoints, discuss what the temporal\n"
        "     offset implies about signal propagation speed and mechanism.\n"
        "   - The PEAK SHAPE (sharp vs. broad) is biologically informative:\n"
        f"     * Sharp peaks suggest rapid {'E3 ligase-DUB' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase-phosphatase'} cycling\n"
        f"     * Broad peaks suggest sustained {'E3 ligase activity or slow DUB' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase activity or slow phosphatase'}\n"
        "     * Asymmetric peaks (fast rise, slow decay) suggest rapid activation\n"
        "       with gradual deactivation\n"
        "\n"
        "8. BIOLOGICAL QUESTION ALIGNMENT (MANDATORY):\n"
        "   - The entire report MUST directly address the biological question specified\n"
        "     in the Analysis Context. Every section must contribute to answering it.\n"
        "   - Use the ACTUAL cell type name (e.g., 'MLO-Y4 osteocyte-like cells'),\n"
        "     treatment name (e.g., 'irisin'), and specific timepoints throughout.\n"
        "   - NEVER use generic placeholders like 'the experimental system', 'the\n"
        "     applied treatment', or 'the stimulus'. Always use the real names.\n"
        "   - The Introduction must frame why this specific treatment on this specific\n"
        "     cell type is biologically important.\n"
        f"   - The Discussion must synthesize how the temporal {ptm_type} patterns\n"
        "     answer the biological question about duration-dependent signaling changes.\n"
        "\n"
        "9. BIOLOGICAL INTERPRETATION SCOPE:\n"
        "   - Base all interpretations on the provided experimental data and "
        "ChromaDB literature references ONLY.\n"
        "   - Do NOT introduce external knowledge beyond what is provided.\n"
        "   - ALL interpretations MUST remain within the biological context of "
        "the Analysis Context (cell type, treatment, timepoints) specified at "
        "the top of the prompt.\n"
        "   - Do NOT discuss biological processes or disease contexts that are "
        "biologically distant from the experimental system.\n"
        "   - Every paragraph must logically connect back to: How does the "
        f"treatment affect {ptm_type} dynamics in the specified cell type?\n"
        "   - Do NOT fabricate connections to unrelated biological systems "
        "(e.g., if studying osteocytes, do NOT extensively discuss neuronal "
        "or immune cell-specific pathways unless directly supported by data).\n"
        "\n"
        "10. CLUSTER \u2194 FIGURE 1 PATHWAY CONNECTION (CRITICAL \u2014 v8.10):\n"
        "   - For EACH cluster (Figures 2-6), you are provided with:\n"
        "     (a) Per-Gene Pathway Mapping: the pathways each cluster member\n"
        "         participates in, from the same 3-Layer enrichment shown in Figure 1.\n"
        "     (b) Shared Pathways Explaining Temporal Coordination: pathways shared by 2+\n"
        "         cluster members, which explain WHY they move together.\n"
        "   - When discussing each cluster, you MUST:\n"
        "     * Identify the shared pathways from the Per-Gene Pathway Mapping data\n"
        "     * Explicitly state: 'These proteins are temporally coordinated because they share\n"
        "       membership in [pathway name(s)] (Figure 1), suggesting coordinated\n"
        "       regulation within this signaling axis.'\n"
        "     * If a cluster's shared pathways overlap with Figure 1's top pathways,\n"
        "       reference Figure 1 explicitly to connect the two analyses.\n"
        "   - This creates a coherent narrative arc: Figure 1 identifies the active\n"
        "     pathways, and Figures 2-6 show HOW proteins within those pathways\n"
        "     respond temporally as coordinated groups.\n"
        "   - If a cluster has NO shared pathways from the 3-Layer data, state this\n"
        "     honestly and discuss alternative explanations (e.g., novel interactions,\n"
        f"     shared upstream {'E3 ligase' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase'}, or physical proximity in a protein complex).\n"
        "   - Do NOT invent pathway connections that are not in the provided data.\n"
        "\n"
        "11. NEIGHBORHOOD CONCORDANCE ANALYSIS (v8.10):\n"
        "   - When a 'Neighborhood Concordance Analysis' section is provided for a\n"
        "     cluster, it summarizes the COLLECTIVE behavior of Non-PTM protein\n"
        "     neighbors surrounding the PTM cluster members.\n"
        "   - The Concordance Score (0-1) indicates what fraction of responsive\n"
        "     Non-PTM neighbors move in the SAME direction. High concordance (>0.7)\n"
        "     indicates a coordinated neighborhood response.\n"
        "   - CRITICAL: Use the TIME LAG information to infer the MECHANISM:\n"
        "     * If most neighbors are SIMULTANEOUS (median lag <=10min):\n"
        "       → Protein complex stoichiometry: these proteins likely form a\n"
        "         physical complex whose components are co-stabilized/co-degraded.\n"
        "       → The PTM may regulate complex assembly or stability.\n"
        "     * If most neighbors are DELAYED (median lag >15min):\n"
        "       → Transcriptional co-regulation: the PTM event likely activates a\n"
        "         transcription factor, leading to new mRNA and protein synthesis\n"
        "         of the neighbor proteins after a time delay.\n"
        "       → Discuss which transcription factor might mediate this.\n"
        "     * If neighbors PRECEDE the PTM cluster:\n"
        "       → The Non-PTM abundance changes may be upstream events that\n"
        "         trigger the downstream PTM cascade.\n"
        "     * If timing is MIXED:\n"
        "       → Pathway-level coordination with both direct (complex) and\n"
        "         indirect (transcriptional) regulatory layers.\n"
        "   - When concordance direction is SAME as cluster direction:\n"
        "     → Positive feedback or co-activation/co-suppression.\n"
        "   - When concordance direction is OPPOSITE to cluster direction:\n"
        "     → Negative feedback, competitive binding, or compensatory response.\n"
        "   - Always name the specific Non-PTM proteins involved and discuss\n"
        "     their known biological roles in the experimental context.\n"
    )

    # ── v9.30 / v12.1: Multi-site Temporal Divergence Analysis ──
    divergence_pairs = _compute_multisite_divergence_for_report(
        sig_matrix, sig_meta or [], timepoints, ptm_type=ptm_type,
        enriched_data=enriched_data, clusters=clusters,
    )
    if divergence_pairs:
        pattern_order = ["signal_attenuation", "sequential_regulation", "multisite_coordination"]
        pattern_labels = {
            "signal_attenuation": "Signal Attenuation (Activation → Inhibition)",
            "sequential_regulation": "Sequential Kinase Regulation (two independent kinases)",
            "multisite_coordination": "Multisite Coordination (single kinase, multiple sites)",
        }
        parts.append("\n## MULTI-SITE TEMPORAL DIVERGENCE ANALYSIS\n")
        parts.append(
            f"The following proteins contain multiple {ptm_type} sites with "
            "divergent temporal dynamics. These intra-protein site pairs reveal "
            "distinct regulatory mechanisms operating on the same protein substrate:\n"
        )

        # v12.1 #5: Resolution warning (global)
        _first_pair_warning = divergence_pairs[0].get("resolution_warning")
        if _first_pair_warning:
            parts.append(f"⚠️ {_first_pair_warning}\n")

        for pat in pattern_order:
            pat_pairs = [p for p in divergence_pairs if p["pattern"] == pat]
            if not pat_pairs:
                continue
            parts.append(f"### {pattern_labels[pat]}")
            for pair in pat_pairs[:8]:  # limit to 8 per pattern
                de_novo_note = ""
                if pair["siteA"].get("is_de_novo"):
                    de_novo_note += f" [⚡ {pair['siteA']['site']} is de novo]"
                if pair["siteB"].get("is_de_novo"):
                    de_novo_note += f" [⚡ {pair['siteB']['site']} is de novo]"
                # v12.1: append confidence/significance metadata
                meta_tags = []
                if pair.get("confidence_tier"):
                    meta_tags.append(f"Tier={pair['confidence_tier']}")
                if pair.get("lag_minutes") is not None:
                    meta_tags.append(f"Lag={pair['lag_minutes']}min")
                elif pair.get("lag_fraction", 0) > 0:
                    meta_tags.append(f"LagFrac={pair['lag_fraction']:.2f}")
                if pair.get("p_value") is not None:
                    meta_tags.append(f"p={pair['p_value']:.3f}")
                if pair.get("interpretation") and pair["interpretation"] != "likely_independent_kinases":
                    meta_tags.append(f"Interp={pair['interpretation']}")
                if pair.get("covered_by_cowave"):
                    meta_tags.append("COVERED_BY_COWAVE")
                meta_str = f" [{', '.join(meta_tags)}]" if meta_tags else ""
                parts.append(f"- {pair['description']}{de_novo_note}{meta_str}")
            parts.append("")

        # ── v9.31: HYBRID CROSS-REFERENCE — Divergence ↔ Co-wave Predicted Kinases ──
        # Build PTM key → cluster mapping
        ptm_to_cluster: Dict[str, dict] = {}
        for cluster in clusters:
            for md in cluster.get("member_details", []):
                ptm_to_cluster[md["key"]] = cluster

        cross_ref_entries = []
        for pair in divergence_pairs:
            gene = pair["gene"]
            siteA_key = pair["siteA"]["key"]
            siteB_key = pair["siteB"]["key"]
            clusterA = ptm_to_cluster.get(siteA_key)
            clusterB = ptm_to_cluster.get(siteB_key)

            if not clusterA and not clusterB:
                continue  # both unclustered, skip

            entry_parts = []
            entry_parts.append(
                f"\n  ● {gene} | {pair['siteA']['site']} ↔ {pair['siteB']['site']} "
                f"| Pattern: {pair['pattern'].replace('_', ' ').title()}"
            )

            # Site A cluster info
            if clusterA:
                cidA = clusterA["cluster_id"]
                patternA = clusterA["pattern"]
                peakA = clusterA["peak_timepoint"]
                kinasesA = clusterA.get("annotations", {}).get("shared_kinases", [])
                kinase_strA = ", ".join(k["kinase"] for k in kinasesA[:3]) if kinasesA else "unknown"
                entry_parts.append(
                    f"    Site {pair['siteA']['site']}: Cluster {cidA} ({patternA}, "
                    f"peak={peakA}) | Predicted kinase(s): {kinase_strA}"
                )
            else:
                entry_parts.append(
                    f"    Site {pair['siteA']['site']}: UNCLUSTERED (unique temporal profile)"
                )

            # Site B cluster info
            if clusterB:
                cidB = clusterB["cluster_id"]
                patternB = clusterB["pattern"]
                peakB = clusterB["peak_timepoint"]
                kinasesB = clusterB.get("annotations", {}).get("shared_kinases", [])
                kinase_strB = ", ".join(k["kinase"] for k in kinasesB[:3]) if kinasesB else "unknown"
                entry_parts.append(
                    f"    Site {pair['siteB']['site']}: Cluster {cidB} ({patternB}, "
                    f"peak={peakB}) | Predicted kinase(s): {kinase_strB}"
                )
            else:
                entry_parts.append(
                    f"    Site {pair['siteB']['site']}: UNCLUSTERED (unique temporal profile)"
                )

            # Cross-reference interpretation hint
            if clusterA and clusterB:
                if clusterA["cluster_id"] == clusterB["cluster_id"]:
                    entry_parts.append(
                        f"    → SAME CLUSTER: Both sites co-move, confirming coordinated "
                        f"regulation by the same kinase or signaling complex."
                    )
                else:
                    # Different clusters — check if kinases form a known pathway link
                    kinasesA_set = {k["kinase"] for k in kinasesA} if kinasesA else set()
                    kinasesB_set = {k["kinase"] for k in kinasesB} if kinasesB else set()
                    shared_kinases = kinasesA_set & kinasesB_set
                    if shared_kinases:
                        entry_parts.append(
                            f"    → DIFFERENT CLUSTERS but SHARED KINASE(S): {', '.join(shared_kinases)} "
                            f"— same kinase may phosphorylate both sites at different rates "
                            f"(distributive mechanism, ultrasensitive switch)."
                        )
                    elif pair["pattern"] == "signal_attenuation":
                        entry_parts.append(
                            f"    → FEEDBACK LOOP CANDIDATE: Early site kinase ({kinase_strA}) "
                            f"may activate a downstream pathway that triggers late site "
                            f"kinase ({kinase_strB}), forming a negative feedback circuit."
                        )
                    elif pair["pattern"] == "sequential_regulation":
                        entry_parts.append(
                            f"    → INDEPENDENT KINASE CASCADE: {kinase_strA} (early) and "
                            f"{kinase_strB} (late) represent two distinct upstream pathways "
                            f"converging on {gene} at different speeds."
                        )
                    else:
                        entry_parts.append(
                            f"    → DIFFERENT CLUSTERS: Independent regulatory inputs from "
                            f"distinct kinases ({kinase_strA} vs {kinase_strB})."
                        )

            # Additional context: temporal profile correlation between the two sites
            valuesA = pair["siteA"].get("values", [])
            valuesB = pair["siteB"].get("values", [])
            if valuesA and valuesB and len(valuesA) == len(valuesB):
                corr = float(np.corrcoef(valuesA, valuesB)[0, 1]) if len(valuesA) > 2 else 0.0
                entry_parts.append(
                    f"    Pearson correlation between sites: r={corr:.3f} "
                    f"({'anti-correlated' if corr < -0.3 else 'weakly correlated' if abs(corr) < 0.3 else 'positively correlated'})"
                )

            # ── v9.32: 6 ADDITIONAL ENRICHMENT ITEMS per divergence pair ──
            # Build gene-level enrichment lookup from enriched_data
            _gene_enr: Dict[str, dict] = {}
            if enriched_data:
                for _ed in enriched_data:
                    _g = _ed.get("gene") or _ed.get("Gene.Name", "")
                    if _g and _g == gene:
                        _p = str(_ed.get("position") or _ed.get("PTM_Position", ""))
                        _gene_enr[_p] = _ed

            siteA_pos = pair["siteA"]["site"]  # e.g. "Y1068"
            siteB_pos = pair["siteB"]["site"]
            edA = _gene_enr.get(siteA_pos, {})
            edB = _gene_enr.get(siteB_pos, {})
            enrA = edA.get("rag_enrichment", {})
            enrB = edB.get("rag_enrichment", {})

            # ─── (1) SITE-SPECIFIC MOTIF CONTEXT (±7aa flanking sequence) ───
            motif_info_parts = []
            for label, ed_entry, enr_entry, site_name in [
                ("A", edA, enrA, siteA_pos), ("B", edB, enrB, siteB_pos)
            ]:
                seq = ""
                for seq_key in ("Enhanced_Sequence_Window", "Sequence_Window",
                                "sequence_window", "flanking_sequence"):
                    val = ed_entry.get(seq_key, "") or enr_entry.get(seq_key, "")
                    if val and isinstance(val, str) and len(val) > 3:
                        seq = val.strip()
                        break
                motifs_str = ed_entry.get("Enhanced_Matched_Motifs", "") or ed_entry.get("Motifs", "")
                if seq or motifs_str:
                    motif_line = f"      Site {site_name}: "
                    if seq:
                        motif_line += f"Flanking={seq} "
                    if motifs_str:
                        motif_line += f"| Motifs=[{motifs_str}]"
                    motif_info_parts.append(motif_line)
            if motif_info_parts:
                entry_parts.append("    [MOTIF CONTEXT]")
                entry_parts.extend(motif_info_parts)

            # ─── (2) KNOWN KINASE-SUBSTRATE RELATIONSHIPS ───
            ks_parts = []
            for label, enr_entry, site_name in [
                ("A", enrA, siteA_pos), ("B", enrB, siteB_pos)
            ]:
                reg = enr_entry.get("regulation", {})
                ks_pairs = reg.get("kinase_substrate", [])
                upstream = reg.get("upstream_regulators", [])
                kp = enr_entry.get("kinase_prediction", {})
                predicted = kp.get("predicted_kinases", []) if isinstance(kp, dict) else []
                known_kinases = []
                for ks in ks_pairs:
                    if isinstance(ks, dict):
                        k_name = ks.get("kinase", ks.get("name", ""))
                        if k_name:
                            known_kinases.append(f"{k_name}(KS-db)")
                    elif isinstance(ks, str) and ks:
                        known_kinases.append(f"{ks}(KS-db)")
                for ur in upstream[:3]:
                    ur_name = ur if isinstance(ur, str) else ur.get("name", "")
                    if ur_name and ur_name not in [k.split("(")[0] for k in known_kinases]:
                        known_kinases.append(f"{ur_name}(literature)")
                for pk in predicted[:2]:
                    pk_name = pk if isinstance(pk, str) else pk.get("kinase", "")
                    pk_conf = pk.get("confidence", "?") if isinstance(pk, dict) else "?"
                    pk_mech = pk.get("mechanism", "") if isinstance(pk, dict) else ""
                    if pk_name and pk_name not in [k.split("(")[0] for k in known_kinases]:
                        known_kinases.append(f"{pk_name}(predicted,{pk_conf})")
                if known_kinases:
                    ks_parts.append(f"      Site {site_name}: {', '.join(known_kinases[:5])}")
            if ks_parts:
                entry_parts.append("    [KNOWN/PREDICTED KINASE-SUBSTRATE]")
                entry_parts.extend(ks_parts)

            # ─── (3) PATHWAY MEMBERSHIP OVERLAP ───
            pathwaysA = set()
            pathwaysB = set()
            for pw in enrA.get("pathways", []):
                pw_name = pw.get("name", "") if isinstance(pw, dict) else str(pw)
                if pw_name:
                    pathwaysA.add(pw_name)
            for pw in enrB.get("pathways", []):
                pw_name = pw.get("name", "") if isinstance(pw, dict) else str(pw)
                if pw_name:
                    pathwaysB.add(pw_name)
            # Also check reactome
            for rpw in enrA.get("reactome", {}).get("signaling_pathways", []):
                rpw_name = rpw.get("name", "") if isinstance(rpw, dict) else str(rpw)
                if rpw_name:
                    pathwaysA.add(rpw_name)
            for rpw in enrB.get("reactome", {}).get("signaling_pathways", []):
                rpw_name = rpw.get("name", "") if isinstance(rpw, dict) else str(rpw)
                if rpw_name:
                    pathwaysB.add(rpw_name)
            shared_pws = pathwaysA & pathwaysB
            unique_A = pathwaysA - pathwaysB
            unique_B = pathwaysB - pathwaysA
            if shared_pws or (unique_A and unique_B):
                entry_parts.append("    [PATHWAY CONTEXT]")
                if shared_pws:
                    entry_parts.append(f"      Shared pathways: {', '.join(sorted(shared_pws)[:5])}")
                if unique_A:
                    entry_parts.append(f"      {siteA_pos}-specific: {', '.join(sorted(unique_A)[:3])}")
                if unique_B:
                    entry_parts.append(f"      {siteB_pos}-specific: {', '.join(sorted(unique_B)[:3])}")
                if shared_pws:
                    entry_parts.append(
                        f"      → Both sites in same pathway ({', '.join(sorted(shared_pws)[:2])}) "
                        f"supports intra-pathway feedback/sequential regulation."
                    )
                elif unique_A and unique_B:
                    entry_parts.append(
                        f"      → Sites in DIFFERENT pathways → convergence of distinct "
                        f"signaling axes on same protein."
                    )

            # ─── (4) PROTEIN DOMAIN CONTEXT ───
            domainsA = edA.get("Domains", "")
            domainsB = edB.get("Domains", "")
            if domainsA or domainsB:
                entry_parts.append("    [DOMAIN CONTEXT]")
                if domainsA:
                    entry_parts.append(f"      {siteA_pos} domain: {domainsA}")
                if domainsB:
                    entry_parts.append(f"      {siteB_pos} domain: {domainsB}")
                if domainsA and domainsB and domainsA != domainsB:
                    entry_parts.append(
                        f"      → Sites in DIFFERENT domains → distinct functional consequences "
                        f"(e.g., kinase domain vs regulatory tail)."
                    )
                elif domainsA and domainsB and domainsA == domainsB:
                    entry_parts.append(
                        f"      → Sites in SAME domain → may cooperatively regulate domain activity."
                    )

            # ─── (5) TEMPORAL LAG (Δt between peaks) ───
            peakA_idx = pair["siteA"]["peak_tp_idx"]
            peakB_idx = pair["siteB"]["peak_tp_idx"]
            delta_tp = abs(peakB_idx - peakA_idx)
            if delta_tp > 0 and len(timepoints) > 1:
                tp_early = timepoints[min(peakA_idx, peakB_idx)]
                tp_late = timepoints[max(peakA_idx, peakB_idx)]
                entry_parts.append(
                    f"    [TEMPORAL LAG] Δt = {tp_early} → {tp_late} "
                    f"(steps={delta_tp}/{len(timepoints)-1})"
                )
                # Interpret lag magnitude
                lag_fraction = delta_tp / (len(timepoints) - 1)
                if lag_fraction <= 0.25:
                    entry_parts.append(
                        f"      → Short lag: consistent with direct kinase cascade "
                        f"(kinaseA → kinaseB, no transcriptional delay)."
                    )
                elif lag_fraction <= 0.5:
                    entry_parts.append(
                        f"      → Medium lag: may involve intermediate signaling steps "
                        f"or protein synthesis-dependent amplification."
                    )
                else:
                    entry_parts.append(
                        f"      → Long lag: suggests transcriptional feedback, "
                        f"de novo protein synthesis, or secondary signaling wave."
                    )

            # ─── (6) FC RATIO (signal magnitude comparison) ───
            fcA = pair["siteA"]["peak_fc"]
            fcB = pair["siteB"]["peak_fc"]
            if abs(fcA) > 0.01 and abs(fcB) > 0.01:
                ratio = abs(fcB) / abs(fcA)
                entry_parts.append(
                    f"    [FC MAGNITUDE] |FC_early|={abs(fcA):.2f}, |FC_late|={abs(fcB):.2f}, "
                    f"ratio(late/early)={ratio:.2f}"
                )
                if pair["pattern"] == "signal_attenuation":
                    if ratio > 1.0:
                        entry_parts.append(
                            f"      → Inhibitory signal STRONGER than activating → "
                            f"strong negative feedback (complete signal shutdown)."
                        )
                    elif ratio > 0.5:
                        entry_parts.append(
                            f"      → Inhibitory signal comparable to activating → "
                            f"balanced feedback (signal dampening, not shutdown)."
                        )
                    else:
                        entry_parts.append(
                            f"      → Inhibitory signal WEAKER than activating → "
                            f"partial attenuation (signal persists but modulated)."
                        )
                elif pair["pattern"] == "sequential_regulation":
                    if ratio > 1.5:
                        entry_parts.append(
                            f"      → Late site has STRONGER signal → signal amplification "
                            f"(second kinase amplifies the initial signal)."
                        )
                    elif ratio < 0.67:
                        entry_parts.append(
                            f"      → Late site has WEAKER signal → signal decay "
                            f"(second kinase provides maintenance, not amplification)."
                        )
                    else:
                        entry_parts.append(
                            f"      → Similar magnitude → parallel independent regulation "
                            f"(two kinases of comparable activity)."
                        )

            cross_ref_entries.append("\n".join(entry_parts))

        if cross_ref_entries:
            parts.append(
                "\n## CROSS-REFERENCE: Multi-site Divergence ↔ Co-wave Cluster Kinase Predictions\n"
            )
            parts.append(
                "The following table links each divergent site pair to its co-wave cluster "
                "assignment and predicted upstream kinases. Use this to VALIDATE, REFINE, or "
                "CHALLENGE the kinase predictions made at the cluster level:\n"
            )
            for entry in cross_ref_entries[:12]:  # limit to 12 entries
                parts.append(entry)
            parts.append("")
            parts.append(
                "CROSS-REFERENCE INTERPRETATION RULES:\n"
                "  - When two sites are in DIFFERENT clusters with DIFFERENT predicted kinases:\n"
                "    This supports the multi-site divergence interpretation. The cluster-level\n"
                "    kinase predictions provide specific candidates for each temporal phase.\n"
                "    Name these kinases explicitly in the Discussion.\n"
                "  - When two sites are in DIFFERENT clusters but SHARE a predicted kinase:\n"
                "    This is consistent with distributive phosphorylation by the same kinase, where the\n"
                "    kinase releases the substrate between phosphorylation events, creating a\n"
                "    time delay. This is a hallmark of ultrasensitive switch-like behavior.\n"
                "  - When two sites are in the SAME cluster:\n"
                "    This is consistent with processive multisite phosphorylation or scaffold-mediated\n"
                "    co-regulation. The cluster's predicted kinase is the single regulator.\n"
                "  - When a site is UNCLUSTERED (singleton):\n"
                "    This site has a unique temporal profile not shared by other PTMs. It may\n"
                "    represent a highly specific regulatory event with a dedicated kinase.\n"
                "  - FEEDBACK LOOP CANDIDATES are especially important: when Signal Attenuation\n"
                "    pairs map to different clusters, the early cluster's kinase likely activates\n"
                "    a pathway that eventually triggers the late cluster's kinase. Trace this\n"
                "    signaling cascade using pathway data from Figure 1.\n"
                "  - Anti-correlated site pairs (r < -0.3) provide the strongest evidence for\n"
                "    opposing regulatory mechanisms on the same protein.\n"
            )

        parts.append(
            "INSTRUCTIONS FOR DISCUSSION SECTION — MULTI-SITE TEMPORAL DIVERGENCE (CRITICAL):\n"
            "   Incorporate the above intra-protein site divergence findings into the "
            "Discussion section as a dedicated subsection titled "
            "'Intra-protein Temporal Divergence and Regulatory Complexity'.\n\n"
            "   INTERPRETATION FRAMEWORK (based on established cell signaling paradigms):\n\n"
            "   A) SIGNAL ATTENUATION PATTERN (Early Activating → Late Inhibitory):\n"
            "      This pattern represents a TEMPORAL PHOSPHORYLATION CODE — a single "
            "      protein encodes multiple functional states through time-ordered "
            "      phosphorylation (Waudby et al., Nat Commun 2022; Kholodenko, Nat Rev "
            "      Mol Cell Biol 2006). Discuss the following mechanisms:\n"
            "      1. Negative feedback loop: The early activating site triggers a "
            "         downstream kinase (e.g., ERK, JNK) that later phosphorylates the "
            "         inhibitory site on the same protein, creating self-limiting signaling.\n"
            "         Example: EGFR Y1068 (activating, recruits Grb2/SOS) → T693 (ERK-mediated "
            "         inhibitory, reduces kinase activity) = receptor desensitization.\n"
            "      2. Temporal gating of effector recruitment: Early phospho-state recruits "
            "         activating co-factors, while fully phosphorylated state disfavors them.\n"
            "         Example: c-JUN S63/S73 (early, recruits TCF4 co-activator) → T91/T93 "
            "         (late, disfavors TCF4 binding, attenuates JNK signaling).\n"
            "      3. Signal duration control: The time gap between activation and inhibition "
            "         determines whether the signal is 'transient' (→ proliferation) or "
            "         'sustained' (→ differentiation), as in the ERK duration model.\n"
            "      4. If the inhibitory site is de novo (⚡): this may represent a NOVEL "
            "         negative feedback mechanism not previously characterized.\n\n"
            "   B) SEQUENTIAL REGULATION PATTERN (Same direction, different timing):\n"
            "      This pattern indicates INDEPENDENT UPSTREAM KINASES converging on the "
            "      same substrate at different speeds (Salazar & Höfer, FEBS J 2009; "
            "      Kim et al., Biochemistry 2012). Discuss:\n"
            "      1. Priming phosphorylation: The first kinase creates a docking site or "
            "         conformational change required for the second kinase to act.\n"
            "         Example: GSK3β requires prior 'priming' phosphorylation by CK1 or PKA.\n"
            "      2. Signal amplification cascade: Sequential phosphorylation progressively "
            "         increases signal strength, creating ultrasensitive threshold responses.\n"
            "      3. Temporal integration (molecular timer): The cell 'counts' stimulus "
            "         duration via progressive multisite phosphorylation — full activation "
            "         requires sustained signaling input (Thomson & Gunawardena, Nature 2009).\n"
            "      4. Pathway convergence: Two independent signaling pathways (e.g., "
            "         PI3K/AKT and MAPK/ERK) regulate the same target protein at different "
            "         speeds, reflecting pathway-specific kinetics.\n"
            "      5. Propose specific candidate kinases for each site based on:\n"
            "         - Known kinase-substrate relationships from ChromaDB literature\n"
            "         - Consensus motif matching (S/T-P for proline-directed kinases, "
            "           basophilic motifs for AGC kinases, acidophilic for CK2)\n"
            "         - Temporal alignment with known kinase activation dynamics\n\n"
            "   C) MULTISITE COORDINATION PATTERN (Same timing):\n"
            "      This pattern suggests a SINGLE KINASE performing PROCESSIVE multisite "
            "      phosphorylation without releasing the substrate (Salazar & Höfer 2009). "
            "      Discuss:\n"
            "      1. Processive mechanism: A single kinase phosphorylates multiple sites "
            "         in one binding event (vs. distributive = one site per binding).\n"
            "         Processive phosphorylation creates GRADED responses; distributive "
            "         creates SWITCH-LIKE (ultrasensitive) responses.\n"
            "      2. Scaffold-mediated proximity: A scaffold protein (e.g., KSR for "
            "         MAPK cascade) holds kinase and substrate together, enabling rapid "
            "         multi-site modification.\n"
            "      3. Cooperative phosphorylation: First site enhances affinity for the "
            "         kinase, accelerating subsequent site phosphorylation.\n"
            "      4. Functional implication: Simultaneous multi-site phosphorylation "
            "         often creates a strong, binary signal (all-or-none activation), "
            "         suggesting this protein is under tight regulatory control.\n\n"
            "   D) GENERAL RULES FOR ALL PATTERNS:\n"
            "      - De novo sites (⚡) should be highlighted as potentially novel "
            "        regulatory events not previously detected in control conditions. "
            "        These may represent condition-specific phosphorylation that only "
            "        occurs under the experimental stimulus.\n"
            "      - Connect these findings to the cluster-level co-movement analysis: "
            "        if two sites of the same protein belong to DIFFERENT clusters, this "
            "        suggests independent upstream regulators may be operating on "
            "        distinct temporal scales.\n"
            "      - If two sites belong to the SAME cluster, this is consistent with coordinated "
            "        regulation, likely by the same kinase or within the same signaling "
            "        complex.\n"
            "      - Discuss the BIOLOGICAL CONSEQUENCE of each divergence pattern for "
            "        the specific experimental system (cell type + treatment): How does "
            "        this intra-protein regulatory complexity contribute to the cellular "
            "        response to the treatment?\n"
            "      - When possible, propose a MECHANISTIC MODEL showing the temporal "
            "        sequence: stimulus → early kinase activation → early site "
            "        phosphorylation → downstream effector → late kinase activation → "
            "        late site phosphorylation → signal outcome.\n\n"
            "   E) REDUNDANCY AVOIDANCE (v12.1 — CRITICAL):\n"
            "      - Co-wave analysis (above) describes INTER-protein temporal coordination.\n"
            "      - Multi-site divergence describes INTRA-protein mechanistic detail.\n"
            "      - DO NOT repeat the same kinase predictions or pathway descriptions\n"
            "        that were already stated in the Co-wave cluster sections.\n"
            "      - Pairs marked [COVERED_BY_COWAVE] mean BOTH sites belong to the SAME\n"
            "        co-wave cluster. For these pairs, only add NOVEL mechanistic insight\n"
            "        (e.g., processive vs distributive mechanism, domain-level interpretation)\n"
            "        that was NOT already covered in the cluster-level discussion.\n"
            "      - Pairs WITHOUT the COVERED_BY_COWAVE tag are FULLY NOVEL — provide\n"
            "        complete mechanistic interpretation for these.\n"
            "      - Focus divergence discussion on: (1) intra-protein regulatory logic,\n"
            "        (2) kinase mechanism type (processive/distributive), (3) temporal\n"
            "        gating implications, (4) feedback loop architecture.\n\n"
            "   F) INTERPRETATION CONFIDENCE (v12.1):\n"
            "      - Each pair has a confidence_tier (High/Medium/Low) based on effect size.\n"
            "        LOW tier pairs should be mentioned briefly or omitted if space is limited.\n"
            "      - Each pair has a p_value from permutation testing. Pairs with p>0.05\n"
            "        (not significant) should be presented as 'tentative observations' only.\n"
            "      - Disambiguation labels (confirmed_single_kinase, likely_distributive,\n"
            "        likely_same_kinase_family, likely_independent_kinases) indicate the\n"
            "        level of evidence for the proposed mechanism. Use hedged language\n"
            "        ('consistent with', 'may indicate', 'suggests') for low-confidence\n"
            "        interpretations. Only use definitive language ('confirms', 'demonstrates')\n"
            "        for confirmed_single_kinase with High confidence tier.\n"
            "      - If resolution_warning is present, explicitly acknowledge the limited\n"
            "        temporal resolution in the discussion and note that additional timepoints\n"
            "        would strengthen the interpretation.\n"
        )

    return "\n".join(parts)


def _append_cluster_detail(
    parts: list, cluster: dict, timepoints: list, is_primary: bool,
    figure_num: int | str = "?", ptm_type: str = "phosphorylation",
) -> None:
    """Append cluster detail to LLM context parts.

    Args:
        is_primary: If True, include full detail (burst clusters).
                    If False, include condensed summary.
        figure_num: The Figure number assigned to this cluster's plot.
    """
    cid = cluster["cluster_id"]
    pattern = _pattern_display_name(cluster["pattern"], ptm_type)
    members = cluster["members"]
    ann = cluster.get("annotations", {})
    bio_summary = ann.get("biological_summary", "No shared annotations found")

    # v9.27: activity class breakdown
    class_counts = cluster.get("activity_class_counts", {})
    dominant = cluster.get("dominant_activity_class", "minor")
    class_label_map = {"de_novo": "De novo", "regulated": "Regulated", "minor": "Minor"}
    class_summary = ", ".join(
        f"{class_label_map.get(k, k)}: {v}"
        for k, v in class_counts.items() if v > 0
    ) if class_counts else "unknown"
    dominant_label = class_label_map.get(dominant, dominant)

    parts.append(f"\n#### Cluster {cid}: {pattern} ({len(members)} members) [Figure {figure_num}]")
    parts.append(
        f"Members: {', '.join(members[:20])}"
        + (f" ... (+{len(members)-20} more)" if len(members) > 20 else "")
    )
    # v9.27: show activity class composition
    parts.append(f"Activity Class Composition: {class_summary} | Dominant: {dominant_label}")
    # List De novo and Regulated members explicitly
    if class_counts.get("de_novo", 0) > 0 or class_counts.get("regulated", 0) > 0:
        denovo_members = [md["key"] for md in cluster.get("member_details", []) if md.get("activity_class") == "de_novo"]
        regulated_members = [md["key"] for md in cluster.get("member_details", []) if md.get("activity_class") == "regulated"]
        if denovo_members:
            parts.append(f"  De novo PTMs (newly induced, no control signal): {', '.join(denovo_members)}")
        if regulated_members:
            parts.append(f"  Regulated PTMs (q<0.05, |Log2FC|≥1): {', '.join(regulated_members)}")
    parts.append(f"Mean intra-cluster correlation: {cluster['correlation_mean']:.2f}")
    parts.append(f"Peak timepoint: {cluster['peak_timepoint']}")

    # Mean temporal profile
    profile_str = " \u2192 ".join(
        f"{tp}: {cluster['mean_profile'].get(tp, 0):+.1f}"
        for tp in timepoints
    )
    parts.append(f"Mean profile: {profile_str}")

    # Biological annotations
    parts.append(f"Biological Context: {bio_summary}")

    # v8.9.5: Enrichr cluster-level pathway enrichment results (Layer 2)
    enrichr_results = cluster.get("enrichr_enrichment", {})
    if enrichr_results:
        enrichr_parts = []
        for lib_name, terms in enrichr_results.items():
            if terms:
                top_terms = terms[:5] if is_primary else terms[:3]
                term_strs = []
                for t in top_terms:
                    if isinstance(t, dict):
                        term_strs.append(
                            f"    {t.get('term', '?')} "
                            f"(p={t.get('adjusted_p_value', t.get('p_value', '?')):.2e}, "
                            f"genes: {', '.join(t.get('genes', [])[:6])})"
                        )
                    else:
                        term_strs.append(f"    {t}")
                if term_strs:
                    lib_display = lib_name.replace("_", " ")
                    enrichr_parts.append(f"  [{lib_display}]\n" + "\n".join(term_strs))
        if enrichr_parts:
            parts.append("\nCluster Pathway Enrichment (Enrichr):")
            parts.extend(enrichr_parts)

    # v8.10: Per-gene pathway mapping (for ALL clusters — explains WHY they co-move)
    per_gene_pws = ann.get("per_gene_pathways", {})
    if per_gene_pws:
        parts.append("\nPer-Gene Pathway Mapping (from Figure 1 / 3-Layer Enrichment):")
        parts.append("  (These are the pathways each cluster member participates in,")
        parts.append("   as identified by the same 3-Layer enrichment shown in Figure 1)")
        for gene, pws in sorted(per_gene_pws.items()):
            pw_display = pws[:8] if isinstance(pws, list) else sorted(pws)[:8]
            more = f" (+{len(pws)-8} more)" if len(pws) > 8 else ""
            parts.append(f"  - {gene}: {', '.join(pw_display)}{more}")

    # v8.10: Shared pathways across cluster members (from per-gene 3-Layer data)
    per_gene_shared = ann.get("per_gene_shared_pathways", [])
    if per_gene_shared:
        parts.append("\nShared Pathways Explaining Temporal Coordination (from 3-Layer Enrichment):")
        parts.append("  (Pathways shared by 2+ cluster members — these explain")
        parts.append("   why these proteins move together in the same temporal pattern)")
        for pw in per_gene_shared[:8]:
            parts.append(
                f"  - {pw['name']} ({pw['overlap_count']}/{pw['total_cluster']} members: "
                f"{', '.join(pw['members'][:8])})"
            )

    if is_primary:
        # Full detail for burst clusters
        if ann.get("shared_pathways"):
            pw_strs = []
            for pw in ann["shared_pathways"][:5]:
                pw_strs.append(
                    f"  - {pw['name']} ({pw['overlap_count']}/{pw['total_cluster']} members: "
                    f"{', '.join(pw['members'][:8])})"
                )
            parts.append("Shared Pathways (from pathway_candidates):\n" + "\n".join(pw_strs))

        if ann.get("shared_kinases"):
            k_strs = []
            for k in ann["shared_kinases"][:5]:
                k_strs.append(
                    f"  - {k['kinase']} \u2192 {', '.join(k['substrates'][:8])}"
                )
            regulator_label = 'Predicted Upstream E3 Ligases' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'Predicted Upstream Kinases'
            parts.append(f"{regulator_label}:\n" + "\n".join(k_strs))

        if ann.get("shared_go_terms"):
            go_strs = [f"  - {g['term']} ({g['count']} members)"
                       for g in ann["shared_go_terms"][:5]]
            parts.append("Shared GO Terms:\n" + "\n".join(go_strs))

        # Non-PTM interactor links (important for burst interpretation)
        nonptm_links = cluster.get("nonptm_links", [])
        if nonptm_links:
            parts.append("\nConnected Non-PTM Interactors:")
            for link in nonptm_links[:8]:
                parts.append(
                    f"  - {link['gene']} ({link['role']}): "
                    f"r={link['correlation_with_cluster']:.2f}, "
                    f"{link['response_pattern']}, "
                    f"lag={link['time_lag_minutes']:.0f}min, "
                    f"max|FC|={link['max_change']:.2f}"
                )

        # v8.10: Neighborhood Concordance Summary (collective Non-PTM behavior)
        nc = cluster.get("neighborhood_concordance")
        if nc:
            parts.append("\nNeighborhood Concordance Analysis:")
            parts.append(
                f"  Concordance Score: {nc['concordance_score']:.2f} "
                f"({nc['up_count']} up / {nc['down_count']} down out of "
                f"{nc['total_responsive_nonptm']} responsive Non-PTM neighbors)"
            )
            parts.append(
                f"  Dominant direction: {nc['dominant_direction']} "
                f"({'SAME as' if nc['same_as_cluster'] else 'OPPOSITE to'} "
                f"PTM cluster direction: {nc['cluster_direction']})"
            )
            parts.append(
                f"  Time lag pattern: {nc['simultaneous_count']} simultaneous, "
                f"{nc['delayed_count']} delayed, {nc['precedes_count']} precedes; "
                f"median lag={nc['median_lag_minutes']:.0f}min, "
                f"mean lag={nc['mean_lag_minutes']:.0f}min"
            )
            hint_desc = {
                "protein_complex_stoichiometry": (
                    "Most Non-PTM neighbors change SIMULTANEOUSLY with PTM cluster, "
                    "suggesting they belong to the same protein complex whose "
                    "stability/abundance is co-regulated."),
                "transcriptional_coregulation": (
                    "Non-PTM neighbors show DELAYED response (median lag >{:.0f}min), "
                    "suggesting PTM-driven transcriptional activation leads to "
                    "new protein synthesis of these neighbors.".format(nc['median_lag_minutes'])),
                "upstream_regulation": (
                    "Non-PTM neighbors change BEFORE the PTM cluster, suggesting "
                    "they may be upstream regulators whose abundance change "
                    "triggers the downstream PTM events."),
                "pathway_level_coordination": (
                    "Mixed timing pattern among Non-PTM neighbors suggests "
                    "pathway-level coordination with both direct and indirect "
                    "regulatory connections."),
            }
            parts.append(
                f"  Mechanism hint: {nc['mechanism_hint']} — "
                f"{hint_desc.get(nc['mechanism_hint'], 'See individual lag values.')}"
            )

        # Per-member peak details for burst clusters
        parts.append("\nIndividual PTM Peak Details:")
        sorted_members = sorted(
            cluster["member_details"],
            key=lambda m: m["max_fc"], reverse=True
        )
        for md in sorted_members[:15]:
            parts.append(
                f"  - {md['key']}: peak |Log2FC|={md['max_fc']:.1f} at {md['peak_tp']}"
            )
    else:
        # v8.10: Enhanced non-burst cluster detail (was too condensed)
        if ann.get("shared_pathways"):
            pw_strs = []
            for pw in ann["shared_pathways"][:5]:
                pw_strs.append(
                    f"  - {pw['name']} ({pw['overlap_count']}/{pw['total_cluster']} members: "
                    f"{', '.join(pw['members'][:6])})"
                )
            parts.append("Shared Pathways:\n" + "\n".join(pw_strs))
        if ann.get("shared_kinases"):
            k_strs = []
            for k in ann["shared_kinases"][:3]:
                k_strs.append(
                    f"  - {k['kinase']} \u2192 {', '.join(k['substrates'][:6])}"
                )
            regulator_label = 'Predicted E3 Ligases' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'Predicted Kinases'
            parts.append(f"{regulator_label}:\n" + "\n".join(k_strs))
        if ann.get("shared_go_terms"):
            go_strs = [f"  - {g['term']} ({g['count']} members)"
                       for g in ann["shared_go_terms"][:3]]
            parts.append("Shared GO Terms:\n" + "\n".join(go_strs))

        # Non-PTM interactor links (also useful for non-burst)
        nonptm_links = cluster.get("nonptm_links", [])
        if nonptm_links:
            parts.append("Connected Non-PTM Interactors:")
            for link in nonptm_links[:5]:
                parts.append(
                    f"  - {link['gene']} ({link['role']}): "
                    f"r={link['correlation_with_cluster']:.2f}, "
                    f"{link['response_pattern']}, "
                    f"lag={link['time_lag_minutes']:.0f}min"
                )

        # v8.10: Neighborhood Concordance Summary (also for non-burst)
        nc = cluster.get("neighborhood_concordance")
        if nc:
            parts.append("\nNeighborhood Concordance Analysis:")
            parts.append(
                f"  Concordance Score: {nc['concordance_score']:.2f} "
                f"({nc['up_count']} up / {nc['down_count']} down out of "
                f"{nc['total_responsive_nonptm']} responsive Non-PTM neighbors)"
            )
            parts.append(
                f"  Dominant direction: {nc['dominant_direction']} "
                f"({'SAME as' if nc['same_as_cluster'] else 'OPPOSITE to'} "
                f"PTM cluster direction: {nc['cluster_direction']})"
            )
            parts.append(
                f"  Time lag: median={nc['median_lag_minutes']:.0f}min, "
                f"{nc['simultaneous_count']} simultaneous / "
                f"{nc['delayed_count']} delayed / "
                f"{nc['precedes_count']} precedes"
            )
            parts.append(f"  Mechanism hint: {nc['mechanism_hint']}")

    parts.append("")
