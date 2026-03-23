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
        clusters, singletons = _cluster_comoving_ptms(sig_matrix, sig_meta, timepoints)

        # Step 5: Annotate clusters with biological context
        # pathway_candidates is a dict {"candidates": [...], "gene_data": {...}}
        pw_candidates_list = pathway_candidates.get("candidates", []) if isinstance(pathway_candidates, dict) else pathway_candidates
        clusters = _annotate_clusters(clusters, enriched_data, pw_candidates_list)

        # Step 5b: Enrichr cluster-level enrichment (Layer 2: 3-Layer Pathway Enrichment)
        clusters = _enrich_clusters_with_enrichr(clusters)

        # Step 6: Link to Non-PTM interactors
        clusters = _link_to_nonptm_interactors(clusters, networks, timepoints)

        # Step 7: Generate visualizations
        figures = _generate_comovement_figures(
            clusters, singletons, timepoints, sig_matrix, sig_meta, output_dir,
            ptm_type=ptm_type,
        )

        # Step 8: Build LLM context
        llm_context = _build_comovement_llm_context(clusters, singletons, timepoints, ptm_type=ptm_type)

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
                f"Kinase: {top_k['kinase']} ({top_k['count']} substrates)"
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
                        f"{len(burst_clusters)} co-movement cluster(s) comprising "
                        f"{n_sites} PTM sites exhibited rapid activation followed by "
                        f"return to baseline. Peak responses observed at "
                        f"{', '.join(sorted(peak_tps))}. "
                        f"(a) Individual PTM time-series profiles colored by cluster membership "
                        f"with cluster mean (bold). "
                        f"(b) Peak amplitude profiles showing Log2FC magnitude ranked by intensity. "
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
                "caption": "Temporal Co-movement Heatmap: PTM sites grouped by "
                           "correlated temporal dynamics. Color intensity represents "
                           "Log2FC magnitude (red=activated, blue=inhibited). "
                           "Cluster assignments shown on left sidebar.",
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
    # Panel (a): Time-series profiles — smooth spline, distinct colors per PTM
    # ══════════════════════════════════════════════════════════════════════
    # Build a per-member color palette so each PTM is visually distinct
    _MEMBER_COLORS = [
        "#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F",
        "#8491B4", "#91D1C2", "#DC9A6C", "#7E6148", "#B09C85",
        "#E377C2", "#17BECF", "#BCBD22", "#9467BD", "#D62728",
        "#FF7F0E", "#2CA02C", "#1F77B4", "#AEC7E8", "#FFBB78",
    ]
    x_arr = np.array(x, dtype=float)
    # Smooth interpolation x-axis (200 points)
    x_smooth = np.linspace(x_arr[0], x_arr[-1], 200) if len(x_arr) >= 4 else x_arr

    global_member_idx = 0
    for ci, cluster in enumerate(burst_clusters):
        cluster_base_color = _NATURE_COLORS[ci % len(_NATURE_COLORS)]
        members = cluster["member_details"]

        # Individual member lines (thin, semi-transparent, distinct colors)
        for mi, md in enumerate(members):
            vals = np.array([md["temporal_values"].get(tp, 0) for tp in timepoints], dtype=float)
            member_color = _MEMBER_COLORS[global_member_idx % len(_MEMBER_COLORS)]
            global_member_idx += 1
            label = md["key"] if len(all_members) <= 15 else (md["key"] if mi < 5 else None)

            # Smooth spline interpolation
            if len(x_arr) >= 4:
                try:
                    spl = make_interp_spline(x_arr, vals, k=3)
                    vals_smooth = spl(x_smooth)
                    ax_a.plot(
                        x_smooth, vals_smooth, linewidth=1.0,
                        alpha=0.55, color=member_color, label=label,
                    )
                except Exception:
                    ax_a.plot(x, vals, linewidth=1.0, alpha=0.55, color=member_color, label=label)
            else:
                ax_a.plot(x, vals, linewidth=1.0, alpha=0.55, color=member_color, label=label)
            # Small markers at actual data points
            ax_a.scatter(x, vals, s=12, color=member_color, alpha=0.6, zorder=5, edgecolors="white", linewidths=0.3)

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
        all_vals = np.array([
            [md["temporal_values"].get(tp, 0) for tp in timepoints]
            for md in members
        ], dtype=float)
        if all_vals.shape[0] > 1:
            min_vals = np.min(all_vals, axis=0)
            max_vals = np.max(all_vals, axis=0)
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

    # Legend: show up to 15 entries, then add "..."
    handles, labels = ax_a.get_legend_handles_labels()
    if len(handles) > 15:
        handles = handles[:15]
        labels = labels[:15]
        labels[-1] = f"... +{len(all_members) - 14} more"
    ax_a.legend(
        handles, labels, loc="upper right", ncol=2,
        framealpha=0.9, borderaxespad=0.5,
        handlelength=1.5, columnspacing=0.8,
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
        color = _NATURE_COLORS[ci % len(_NATURE_COLORS)]

        # Smooth curve outline only — no fill
        ax_b.plot(x_chrom, peak, color=color, linewidth=1.2, alpha=0.85)
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
        ax_c.legend(loc="upper right", framealpha=0.9)

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
    x_arr = np.array(x, dtype=float)
    # Smooth interpolation x-axis
    x_smooth = np.linspace(x_arr[0], x_arr[-1], 200) if len(x_arr) >= 4 else x_arr

    # Distinct color palette for individual PTM members
    _MEMBER_COLORS = [
        "#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F",
        "#8491B4", "#91D1C2", "#DC9A6C", "#7E6148", "#B09C85",
        "#E377C2", "#17BECF", "#BCBD22", "#9467BD", "#D62728",
        "#FF7F0E", "#2CA02C", "#1F77B4", "#AEC7E8", "#FFBB78",
    ]

    # ── PTM member lines (smooth spline, distinct colors) ──
    for i, md in enumerate(members):
        vals = np.array([md["temporal_values"].get(tp, 0) for tp in timepoints], dtype=float)
        color = _MEMBER_COLORS[i % len(_MEMBER_COLORS)]

        # Smooth spline interpolation
        if len(x_arr) >= 4:
            try:
                spl = make_interp_spline(x_arr, vals, k=3)
                vals_smooth = spl(x_smooth)
                ax_ptm.plot(x_smooth, vals_smooth, linewidth=1.2,
                            alpha=0.7, color=color, label=md["key"])
            except Exception:
                ax_ptm.plot(x, vals, linewidth=1.2, alpha=0.7, color=color, label=md["key"])
        else:
            ax_ptm.plot(x, vals, linewidth=1.2, alpha=0.7, color=color, label=md["key"])
        # Small markers at actual data points
        ax_ptm.scatter(x, vals, s=16, color=color, alpha=0.7, zorder=5, edgecolors="white", linewidths=0.3)

    # Cluster mean (thick dashed, smooth)
    mean_vals = np.array([cluster["mean_profile"].get(tp, 0) for tp in timepoints], dtype=float)
    if len(x_arr) >= 4:
        try:
            spl_mean = make_interp_spline(x_arr, mean_vals, k=3)
            ax_ptm.plot(x_smooth, spl_mean(x_smooth), "--", linewidth=2.5, color="#333333",
                        alpha=0.8, label="Cluster Mean")
        except Exception:
            ax_ptm.plot(x, mean_vals, "--", linewidth=2.5, color="#333333", alpha=0.8, label="Cluster Mean")
    else:
        ax_ptm.plot(x, mean_vals, "--", linewidth=2.5, color="#333333", alpha=0.8, label="Cluster Mean")
    ax_ptm.scatter(x, mean_vals, s=20, color="#333333", alpha=0.8, zorder=6, edgecolors="white", linewidths=0.3)

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

def _build_comovement_llm_context(
    clusters: list, singletons: list, timepoints: list,
    ptm_type: str = "phosphorylation",
) -> str:
    """Build structured text for LLM injection into write_sections.

    v8.4: Transient burst clusters are presented first with detailed context.
    v8.10: PTM-type-aware labels and ubiquitylation-specific interpretation.
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
        "\n## TEMPORAL PTM CO-MOVEMENT ANALYSIS\n",
        "Correlation-based hierarchical clustering of PTM Log2FC time-series "
        "vectors identified the following co-movement clusters. Transient burst "
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
        parts.append("\n### Other Co-movement Patterns")
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
        "   - The transient phosphorylation burst clusters MUST be the primary "
        "analytical focus of the Results section.\n"
        "   - Dedicate at least 2-3 paragraphs to interpreting the burst dynamics: "
        "what triggers the rapid phosphorylation, which kinases are likely responsible, "
        "and why the signal returns to baseline (phosphatase activity, negative feedback).\n"
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
        "     cascade (e.g., receptor → adaptor → effector). Relate to known kinase\n"
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
        "     upstream regulation (common kinase/phosphatase). Identify potential\n"
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
        "     represents the immediate kinase activation upon stimulus, while the sequential\n"
        "     wave (Fig 3) shows the downstream propagation of this signal through adaptor\n"
        "     and effector proteins. The biphasic switch (Fig 5) may reflect negative\n"
        "     feedback that terminates the initial burst, and sustained changes (Fig 6)\n"
        "     indicate commitment to long-term cellular responses.'\n"
        "   - Identify SHARED PROTEINS or PATHWAYS across clusters — if the same kinase\n"
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
        "     * Do they share a common upstream kinase or phosphatase?\n"
        "     * Are they on proteins in the same signaling complex or pathway?\n"
        "     * Do they have similar subcellular localization?\n"
        "     * Are they known substrates of the same kinase family?\n"
        "   - For PTMs that peak at DIFFERENT timepoints, discuss what the temporal\n"
        "     offset implies about signal propagation speed and mechanism.\n"
        "   - The PEAK SHAPE (sharp vs. broad) is biologically informative:\n"
        "     * Sharp peaks suggest rapid kinase-phosphatase cycling\n"
        "     * Broad peaks suggest sustained kinase activity or slow phosphatase\n"
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
        "   - The Discussion must synthesize how the temporal phosphorylation patterns\n"
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
        "treatment affect phosphorylation dynamics in the specified cell type?\n"
        "   - Do NOT fabricate connections to unrelated biological systems "
        "(e.g., if studying osteocytes, do NOT extensively discuss neuronal "
        "or immune cell-specific pathways unless directly supported by data).\n"
        "\n"
        "10. CLUSTER \u2194 FIGURE 1 PATHWAY CONNECTION (CRITICAL \u2014 v8.10):\n"
        "   - For EACH cluster (Figures 2-6), you are provided with:\n"
        "     (a) Per-Gene Pathway Mapping: the pathways each cluster member\n"
        "         participates in, from the same 3-Layer enrichment shown in Figure 1.\n"
        "     (b) Shared Pathways Explaining Co-movement: pathways shared by 2+\n"
        "         cluster members, which explain WHY they move together.\n"
        "   - When discussing each cluster, you MUST:\n"
        "     * Identify the shared pathways from the Per-Gene Pathway Mapping data\n"
        "     * Explicitly state: 'These proteins co-move because they share\n"
        "       membership in [pathway name(s)] (Figure 1), suggesting coordinated\n"
        "       regulation within this signaling axis.'\n"
        "     * If a cluster's shared pathways overlap with Figure 1's top pathways,\n"
        "       reference Figure 1 explicitly to connect the two analyses.\n"
        "   - This creates a coherent narrative arc: Figure 1 identifies the active\n"
        "     pathways, and Figures 2-6 show HOW proteins within those pathways\n"
        "     respond temporally as coordinated groups.\n"
        "   - If a cluster has NO shared pathways from the 3-Layer data, state this\n"
        "     honestly and discuss alternative explanations (e.g., novel interactions,\n"
        "     shared upstream kinase, or physical proximity in a protein complex).\n"
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

    parts.append(f"\n#### Cluster {cid}: {pattern} ({len(members)} members) [Figure {figure_num}]")
    parts.append(
        f"Members: {', '.join(members[:20])}"
        + (f" ... (+{len(members)-20} more)" if len(members) > 20 else "")
    )
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
        parts.append("\nShared Pathways Explaining Co-movement (from 3-Layer Enrichment):")
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
            parts.append("Predicted Upstream Kinases:\n" + "\n".join(k_strs))

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
            parts.append("Predicted Kinases:\n" + "\n".join(k_strs))
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
