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

from common.temporal_utils import tp_to_minutes

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
MIN_TIMEPOINTS = 3          # Need at least 3 timepoints for meaningful clustering
MIN_VARIANCE = 0.5          # Minimum variance across timepoints to be "significant"
MIN_AMPLITUDE = 1.5         # Minimum max |Log2FC| to be "significant"
CORRELATION_THRESHOLD = 0.70  # Minimum |correlation| to be in same cluster
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
        clusters, singletons = _cluster_comoving_ptms(sig_matrix, sig_meta, timepoints)

        # Step 5: Annotate clusters with biological context
        # pathway_candidates is a dict {"candidates": [...], "gene_data": {...}}
        pw_candidates_list = pathway_candidates.get("candidates", []) if isinstance(pathway_candidates, dict) else pathway_candidates
        clusters = _annotate_clusters(clusters, enriched_data, pw_candidates_list)

        # Step 6: Link to Non-PTM interactors
        clusters = _link_to_nonptm_interactors(clusters, networks, timepoints)

        # Step 7: Generate visualizations
        figures = _generate_comovement_figures(
            clusters, singletons, timepoints, sig_matrix, sig_meta, output_dir
        )

        # Step 8: Build LLM context
        llm_context = _build_comovement_llm_context(clusters, singletons, timepoints)

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
                    ptm_meta_map[key] = {"gene": gene, "site": site, "key": key}
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
    matrix: np.ndarray, meta: list, timepoints: list
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

    # Distance = 1 - |correlation| (anti-correlated PTMs can also cluster)
    dist_matrix = 1.0 - np.abs(corr_matrix)
    np.fill_diagonal(dist_matrix, 0.0)
    # Ensure symmetry and non-negative
    dist_matrix = (dist_matrix + dist_matrix.T) / 2
    dist_matrix = np.maximum(dist_matrix, 0.0)

    # Hierarchical clustering (Ward's method on condensed distance)
    condensed = squareform(dist_matrix, checks=False)
    Z = linkage(condensed, method="average")

    # Cut at threshold
    threshold = 1.0 - CORRELATION_THRESHOLD  # distance threshold
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
    }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5: BIOLOGICAL ANNOTATION
# ═══════════════════════════════════════════════════════════════════════════

def _annotate_clusters(
    clusters: list, enriched_data: list, pathway_candidates: list
) -> list:
    """Annotate each cluster with shared biological features."""
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
        }

        # --- Pathway enrichment ---
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

        # --- GO terms, kinases, complexes from enriched_data ---
        go_term_counts: Dict[str, List[str]] = defaultdict(list)
        kinase_counts: Dict[str, List[str]] = defaultdict(list)
        location_counts: Dict[str, int] = defaultdict(int)
        complex_counts: Dict[str, List[str]] = defaultdict(list)

        for gene in cluster_genes:
            ed = gene_enrichment.get(gene, {})
            enr = ed.get("rag_enrichment", ed)

            # GO terms
            for go in enr.get("go_terms", enr.get("biological_process", [])):
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
            loc = enr.get("subcellular_location", "")
            if isinstance(loc, list):
                for l in loc:
                    location_counts[l] += 1
            elif loc:
                location_counts[loc] += 1

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
        summary_parts = []
        if annotations["shared_pathways"]:
            top_pw = annotations["shared_pathways"][0]
            summary_parts.append(
                f"{top_pw['name']} ({top_pw['overlap_count']}/{len(cluster_genes)} members)"
            )
        if annotations["shared_kinases"]:
            top_k = annotations["shared_kinases"][0]
            summary_parts.append(
                f"Kinase: {top_k['kinase']} ({top_k['count']} substrates)"
            )
        if annotations["shared_complexes"]:
            top_c = annotations["shared_complexes"][0]
            summary_parts.append(f"Complex: {top_c['name']}")
        if annotations["shared_go_terms"]:
            top_go = annotations["shared_go_terms"][0]
            summary_parts.append(top_go["term"])

        annotations["biological_summary"] = "; ".join(summary_parts) if summary_parts else "No shared annotations found"

        cluster["annotations"] = annotations

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

    return clusters


# ═══════════════════════════════════════════════════════════════════════════
# STEP 7: VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════

def _generate_comovement_figures(
    clusters: list, singletons: list, timepoints: list,
    matrix: np.ndarray, meta: list, output_dir: str
) -> list:
    """Generate publication-quality cluster visualizations."""
    figures = []
    os.makedirs(output_dir, exist_ok=True)

    if not clusters:
        return figures

    # ── Figure A: Summary Heatmap ──
    try:
        heatmap_path = _generate_summary_heatmap(
            clusters, singletons, timepoints, matrix, meta, output_dir
        )
        if heatmap_path:
            figures.append({
                "path": heatmap_path,
                "caption": "Temporal Co-movement Heatmap: PTM sites grouped by "
                           "correlated temporal dynamics. Color intensity represents "
                           "Log2FC magnitude (red=activated, blue=inhibited). "
                           "Cluster assignments shown on left sidebar.",
                "type": "heatmap",
            })
    except Exception as e:
        logger.warning(f"Heatmap generation failed: {e}")

    # ── Figure B: Per-cluster line plots ──
    for cluster in clusters[:6]:  # Max 6 cluster detail figures
        try:
            cluster_path = _generate_cluster_lineplot(
                cluster, timepoints, output_dir
            )
            if cluster_path:
                ann = cluster.get("annotations", {})
                bio_summary = ann.get("biological_summary", "")
                pattern_label = _pattern_display_name(cluster["pattern"])
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

    return figures


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

    # Create figure
    n_rows = len(ordered_indices)
    fig_height = max(6, min(20, n_rows * 0.35 + 2))
    fig_width = max(8, len(timepoints) * 0.8 + 4)

    fig, (ax_sidebar, ax_heatmap, ax_cbar) = plt.subplots(
        1, 3, figsize=(fig_width, fig_height),
        gridspec_kw={"width_ratios": [0.3, 6, 0.3], "wspace": 0.02}
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
        "Temporal PTM Co-movement Analysis",
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

    # ── PTM member lines ──
    for i, md in enumerate(members):
        vals = [md["temporal_values"].get(tp, 0) for tp in timepoints]
        color = CLUSTER_COLORS[0] if len(members) <= 3 else \
                plt.cm.tab20(i / max(len(members) - 1, 1))
        ax_ptm.plot(x, vals, marker="o", markersize=4, linewidth=1.2,
                    alpha=0.7, color=color, label=md["key"])

    # Cluster mean (thick dashed)
    mean_vals = [cluster["mean_profile"].get(tp, 0) for tp in timepoints]
    ax_ptm.plot(x, mean_vals, "--", linewidth=2.5, color="#333333",
                alpha=0.8, label="Cluster Mean")

    ax_ptm.axhline(y=0, color="gray", linewidth=0.5, linestyle=":")
    ax_ptm.set_ylabel("PTM Log2FC", fontsize=11)
    ax_ptm.grid(True, alpha=0.2)

    # Legend
    if len(members) <= 12:
        ax_ptm.legend(fontsize=7, loc="upper right", ncol=2,
                      framealpha=0.8, borderaxespad=0.5)
    else:
        # Too many members — show only top 5 by max_fc + mean
        top_members = sorted(members, key=lambda m: m["max_fc"], reverse=True)[:5]
        handles = []
        for md in top_members:
            handles.append(Line2D([0], [0], marker="o", markersize=4,
                                  label=md["key"], linewidth=1.2))
        handles.append(Line2D([0], [0], linestyle="--", linewidth=2.5,
                              color="#333333", label="Cluster Mean"))
        ax_ptm.legend(handles=handles, fontsize=7, loc="upper right",
                      ncol=2, framealpha=0.8)

    # Title with biological annotation
    ann = cluster.get("annotations", {})
    bio_summary = ann.get("biological_summary", "")
    pattern_label = _pattern_display_name(cluster["pattern"])
    title = (
        f"Cluster {cluster['cluster_id']}: {pattern_label}\n"
        f"{cluster['member_count']} PTM sites | "
        f"Mean correlation: {cluster['correlation_mean']:.2f} | "
        f"Peak: {cluster['peak_timepoint']}"
    )
    if bio_summary:
        title += f"\n{bio_summary}"
    ax_ptm.set_title(title, fontsize=10, fontweight="normal", loc="left", pad=8)

    # ── Non-PTM interactor lines ──
    if ax_nonptm and nonptm_links:
        for i, link in enumerate(nonptm_links[:8]):
            vals = [link["temporal_profile"].get(tp, 0) for tp in timepoints]
            color = plt.cm.Greys(0.4 + 0.4 * i / max(len(nonptm_links[:8]) - 1, 1))
            label = f"{link['gene']} (r={link['correlation_with_cluster']:.2f})"
            ax_nonptm.plot(x, vals, marker="s", markersize=3, linewidth=1.0,
                           alpha=0.7, color=color, label=label)

        ax_nonptm.axhline(y=0, color="gray", linewidth=0.5, linestyle=":")
        ax_nonptm.set_ylabel("Non-PTM Protein Log2FC", fontsize=10)
        ax_nonptm.set_xlabel("Timepoint", fontsize=11)
        ax_nonptm.grid(True, alpha=0.2)
        ax_nonptm.legend(fontsize=7, loc="upper right", ncol=2, framealpha=0.8)
        ax_nonptm.set_title(
            "Connected Non-PTM Interactors (Protein Abundance)",
            fontsize=9, fontweight="normal", loc="left"
        )

    # X-axis labels
    bottom_ax = ax_nonptm if ax_nonptm else ax_ptm
    bottom_ax.set_xticks(x)
    bottom_ax.set_xticklabels(timepoints, fontsize=9)
    bottom_ax.set_xlabel("Timepoint", fontsize=11)

    plt.tight_layout()
    path = os.path.join(
        output_dir, f"comovement_cluster_{cluster['cluster_id']}.png"
    )
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _pattern_display_name(pattern: str) -> str:
    """Convert pattern code to human-readable display name."""
    return {
        "co_activated": "Co-activated",
        "co_inhibited": "Co-inhibited",
        "transient_burst": "Transient Phosphorylation Burst",
        "transient_suppression": "Transient Dephosphorylation",
        "sustained_activation": "Sustained Activation",
        "sustained_inhibition": "Sustained Inhibition",
        "biphasic_switch": "Biphasic Switch",
        "sequential_wave": "Sequential Signaling Wave",
        "mixed_response": "Mixed Response",
    }.get(pattern, pattern.replace("_", " ").title())


# ═══════════════════════════════════════════════════════════════════════════
# STEP 8: LLM CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def _build_comovement_llm_context(
    clusters: list, singletons: list, timepoints: list
) -> str:
    """Build structured text for LLM injection into write_sections."""
    if not clusters:
        return ""

    parts = [
        "\n## TEMPORAL PTM CO-MOVEMENT ANALYSIS\n",
        "The following co-movement clusters were detected by correlation-based "
        "hierarchical clustering of PTM Log2FC time-series vectors. Only PTMs with "
        "significant temporal variation are included.\n",
    ]

    for cluster in clusters:
        cid = cluster["cluster_id"]
        pattern = _pattern_display_name(cluster["pattern"])
        members = cluster["members"]
        ann = cluster.get("annotations", {})
        bio_summary = ann.get("biological_summary", "No shared annotations found")

        parts.append(f"### Cluster {cid}: {pattern} ({len(members)} members)")
        parts.append(
            f"Members: {', '.join(members[:15])}"
            + (f" ... (+{len(members)-15} more)" if len(members) > 15 else "")
        )
        parts.append(f"Mean intra-cluster correlation: {cluster['correlation_mean']:.2f}")
        parts.append(f"Peak timepoint: {cluster['peak_timepoint']}")

        # Mean temporal profile
        profile_str = " → ".join(
            f"{tp}: {cluster['mean_profile'].get(tp, 0):+.1f}"
            for tp in timepoints
        )
        parts.append(f"Mean profile: {profile_str}")

        # Biological annotations
        parts.append(f"\nBiological Context: {bio_summary}")

        if ann.get("shared_pathways"):
            pw_strs = []
            for pw in ann["shared_pathways"][:3]:
                pw_strs.append(
                    f"  - {pw['name']} ({pw['overlap_count']}/{pw['total_cluster']} members: "
                    f"{', '.join(pw['members'][:5])})"
                )
            parts.append("Shared Pathways:\n" + "\n".join(pw_strs))

        if ann.get("shared_kinases"):
            k_strs = []
            for k in ann["shared_kinases"][:3]:
                k_strs.append(
                    f"  - {k['kinase']} → {', '.join(k['substrates'][:5])}"
                )
            parts.append("Predicted Upstream Kinases:\n" + "\n".join(k_strs))

        if ann.get("shared_go_terms"):
            go_strs = [f"  - {g['term']} ({g['count']} members)"
                       for g in ann["shared_go_terms"][:3]]
            parts.append("Shared GO Terms:\n" + "\n".join(go_strs))

        # Non-PTM interactor links
        nonptm_links = cluster.get("nonptm_links", [])
        if nonptm_links:
            parts.append("\nConnected Non-PTM Interactors:")
            for link in nonptm_links[:5]:
                parts.append(
                    f"  - {link['gene']} ({link['role']}): "
                    f"r={link['correlation_with_cluster']:.2f}, "
                    f"{link['response_pattern']}, "
                    f"lag={link['time_lag_minutes']:.0f}min, "
                    f"max|FC|={link['max_change']:.2f}"
                )

        parts.append("")

    # Singletons
    notable_singletons = [s for s in singletons if s["max_fc"] >= 3.0]
    if notable_singletons:
        parts.append("### Notable Unclustered PTMs (unique temporal profiles)")
        for s in notable_singletons[:10]:
            profile_str = " → ".join(
                f"{tp}: {s['temporal_values'].get(tp, 0):+.1f}"
                for tp in timepoints
            )
            parts.append(
                f"- {s['key']}: max|FC|={s['max_fc']:.1f}, "
                f"peak={s['peak_tp']}, profile: {profile_str}"
            )
        parts.append("")

    # Instructions for LLM
    parts.append(
        "\nINSTRUCTIONS FOR REPORT WRITING:\n"
        "- Discuss co-movement clusters as a central analytical theme in Results\n"
        "- For each cluster, explain WHY these PTMs move together (shared kinase, "
        "pathway, complex)\n"
        "- Connect cluster temporal patterns to downstream Non-PTM interactor changes\n"
        "- For transient bursts, discuss what triggers the rapid phosphorylation and "
        "why it returns to baseline\n"
        "- For sustained patterns, discuss continuous signaling vs. constitutive modification\n"
        "- Reference the co-movement figures by their figure numbers\n"
        "- Compare cluster findings with known signaling cascades from the literature\n"
    )

    return "\n".join(parts)
