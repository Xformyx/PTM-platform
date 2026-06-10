"""
TF-Target Inference Tool — DoRothEA + TRRUST combined TF-target database.

Provides:
1. Forward query: TF → list of target genes
2. Reverse query: gene list → inferred active TFs (enrichment-based)
3. Batch reverse query: multiple gene lists → TF activity inference

Data sources:
- DoRothEA (OmniPath): Confidence levels A, B, C (mouse + human)
- TRRUST v2: Manually curated TF-target interactions (mouse + human)
"""
import hashlib
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from scipy import stats as scipy_stats

logger = logging.getLogger("mcp-server.tf_targets")

# ---------------------------------------------------------------------------
# Data Loading (singleton pattern — loaded once at import time)
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).parent.parent.parent / "data"

_tf_data: Dict[str, dict] = {}  # species -> {tf_to_targets, target_to_tfs}


def _load_species_data(species: str) -> dict:
    """Load TF-target data for a species (lazy singleton)."""
    if species in _tf_data:
        return _tf_data[species]

    filename = f"tf_target_{species}.json"
    filepath = _DATA_DIR / filename
    if not filepath.exists():
        logger.warning(f"TF-target data not found: {filepath}")
        _tf_data[species] = {"tf_to_targets": {}, "target_to_tfs": {}, "_missing": True}
        return _tf_data[species]

    logger.info(f"Loading TF-target data from {filepath}")
    with open(filepath) as f:
        data = json.load(f)
    _tf_data[species] = data
    n_tfs = len(data.get("tf_to_targets", {}))
    n_targets = len(data.get("target_to_tfs", {}))
    logger.info(f"Loaded {species}: {n_tfs} TFs, {n_targets} target genes")
    return _tf_data[species]


# ---------------------------------------------------------------------------
# Forward Query: TF → Targets
# ---------------------------------------------------------------------------
async def query_tf_targets(
    tf_name: str,
    species: str = "mouse",
    min_confidence: str = "medium",
    redis=None,
) -> dict:
    """
    Get all known target genes for a given transcription factor.

    Args:
        tf_name: Gene symbol of the TF (case-insensitive)
        species: 'mouse' or 'human'
        min_confidence: Minimum confidence level ('very_high', 'high', 'medium')

    Returns:
        Dict with TF info and list of target genes with regulation mode.
    """
    # Cache check
    cache_key = f"tf_targets:{tf_name.upper()}:{species}:{min_confidence}"
    if redis:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    data = _load_species_data(species)
    tf_to_targets = data.get("tf_to_targets", {})

    if not tf_to_targets:
        return {
            "tf": tf_name.upper(),
            "species": species,
            "total_targets": 0,
            "targets": [],
            "sources": [],
            "error": f"No TF-target data available for species '{species}'",
        }

    tf_upper = tf_name.upper()
    targets = tf_to_targets.get(tf_upper, [])

    # Filter by confidence
    confidence_order = ["very_high", "high", "medium", "low"]
    if min_confidence not in confidence_order:
        logger.warning(f"Invalid min_confidence '{min_confidence}', defaulting to 'medium'")
    min_idx = confidence_order.index(min_confidence) if min_confidence in confidence_order else 2

    filtered = []
    for t in targets:
        t_conf = t.get("confidence", "medium")
        t_idx = confidence_order.index(t_conf) if t_conf in confidence_order else 2
        if t_idx <= min_idx:
            filtered.append(t)

    # Deduplicate targets (same target from multiple sources = higher confidence)
    target_map = {}
    for t in filtered:
        tgt = t["target"]
        if tgt not in target_map:
            target_map[tgt] = {
                "gene": tgt,
                "mode": t["mode"],
                "sources": [t["source"]],
                "confidence": t["confidence"],
            }
        else:
            if t["source"] not in target_map[tgt]["sources"]:
                target_map[tgt]["sources"].append(t["source"])
            # Upgrade confidence if confirmed by multiple sources
            if len(target_map[tgt]["sources"]) > 1:
                target_map[tgt]["confidence"] = "very_high"

    result = {
        "tf": tf_upper,
        "species": species,
        "total_targets": len(target_map),
        "targets": sorted(target_map.values(), key=lambda x: x["gene"]),
        "sources": ["DoRothEA", "TRRUST"],
    }

    if redis:
        await redis.set(cache_key, json.dumps(result), ex=86400 * 7)

    return result


# ---------------------------------------------------------------------------
# Reverse Query: Gene List → Inferred TF Activity (Fisher's exact test)
# ---------------------------------------------------------------------------
async def infer_tf_activity(
    gene_list: List[str],
    species: str = "mouse",
    min_confidence: str = "medium",
    min_targets_overlap: int = 3,
    top_n: int = 20,
    background_size: Optional[int] = None,
    redis=None,
) -> dict:
    """
    Infer active transcription factors from a list of changed genes.
    Uses Fisher's exact test (over-representation analysis).

    Args:
        gene_list: List of gene symbols (changed Non-PTM proteins)
        species: 'mouse' or 'human'
        min_confidence: Minimum confidence for TF-target edges
        min_targets_overlap: Minimum number of overlapping targets to report a TF
        top_n: Number of top TFs to return
        background_size: Total number of genes in background (default: all target genes in DB)

    Returns:
        Dict with ranked TF activity predictions.
    """
    if not gene_list:
        return {"gene_list": [], "inferred_tfs": [], "error": "Empty gene list"}

    # Cache check
    gene_key = ",".join(sorted(set(g.upper() for g in gene_list)))
    _gene_hash = hashlib.md5(gene_key.encode()).hexdigest()[:16]
    cache_key = f"tf_infer:{_gene_hash}:{species}:{min_confidence}:{min_targets_overlap}"
    if redis:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    data = _load_species_data(species)
    tf_to_targets = data.get("tf_to_targets", {})
    target_to_tfs = data.get("target_to_tfs", {})

    if not tf_to_targets:
        return {
            "gene_list_size": len(gene_list),
            "species": species,
            "inferred_tfs": [],
            "error": f"No TF-target data available for species '{species}'",
        }

    # Normalize input
    gene_set = set(g.upper() for g in gene_list)

    # Background: all unique target genes in the DB
    all_target_genes = set(target_to_tfs.keys())
    bg_size = background_size or len(all_target_genes)

    # Filter gene_set to only genes present in the DB background for a valid contingency table
    effective_gene_set = gene_set & all_target_genes

    # Confidence filter
    confidence_order = ["very_high", "high", "medium", "low"]
    min_idx = confidence_order.index(min_confidence) if min_confidence in confidence_order else 2

    # For each TF, compute overlap with gene_list
    tf_results = []
    for tf, targets in tf_to_targets.items():
        # Filter targets by confidence
        tf_target_genes = set()
        for t in targets:
            t_conf = t.get("confidence", "medium")
            t_idx = confidence_order.index(t_conf) if t_conf in confidence_order else 2
            if t_idx <= min_idx:
                tf_target_genes.add(t["target"])

        if not tf_target_genes:
            continue

        # Overlap
        overlap = effective_gene_set & tf_target_genes
        n_overlap = len(overlap)

        if n_overlap < min_targets_overlap:
            continue

        # Fisher's exact test (one-sided, over-representation)
        # Contingency table:
        #                    In effective_gene_set   Not in effective_gene_set
        # TF targets:        n_overlap               len(tf_targets) - n_overlap
        # Non-TF targets:    len(eff_set)-n_overlap  bg_size - ...
        # All cells are non-negative because effective_gene_set ⊆ all_target_genes ⊆ background
        a = n_overlap
        b = len(tf_target_genes) - n_overlap
        c = len(effective_gene_set) - n_overlap
        d = bg_size - a - b - c

        if d < 0:
            d = 0

        _, pvalue = scipy_stats.fisher_exact([[a, b], [c, d]], alternative="greater")

        # Determine dominant regulation mode
        modes = defaultdict(int)
        for t in targets:
            if t["target"] in overlap:
                modes[t.get("mode", "unknown")] += 1
        dominant_mode = max(modes, key=modes.get) if modes else "unknown"

        # Sources contributing
        sources = set()
        for t in targets:
            if t["target"] in overlap:
                sources.add(t.get("source", "unknown"))

        tf_results.append({
            "tf": tf,
            "n_targets_in_db": len(tf_target_genes),
            "n_overlap": n_overlap,
            "overlap_genes": sorted(overlap),
            "pvalue": pvalue,
            "fold_enrichment": round(
                (n_overlap / len(effective_gene_set)) / (len(tf_target_genes) / bg_size), 2
            ) if len(effective_gene_set) > 0 and len(tf_target_genes) > 0 else 0,
            "dominant_mode": dominant_mode,
            "mode_counts": dict(modes),
            "sources": sorted(sources),
        })

    # Sort by p-value
    tf_results.sort(key=lambda x: x["pvalue"])

    # Benjamini-Hochberg FDR correction (monotone step-up procedure)
    n_tests = len(tf_results)
    if n_tests > 0:
        # tf_results is already sorted by p-value ascending
        fdrs = [r["pvalue"] * n_tests / (i + 1) for i, r in enumerate(tf_results)]
        # Enforce monotonicity by reverse cumulative minimum
        running_min = 1.0
        for i in range(n_tests - 1, -1, -1):
            running_min = min(fdrs[i], running_min)
            fdrs[i] = running_min
        for r, fdr in zip(tf_results, fdrs):
            r["fdr"] = round(min(fdr, 1.0), 6)

    # Top N
    top_results = tf_results[:top_n]

    result = {
        "gene_list_size": len(gene_set),
        "effective_gene_list_size": len(effective_gene_set),
        "species": species,
        "background_size": bg_size,
        "total_tfs_tested": n_tests,
        "significant_tfs": len([r for r in tf_results if r["fdr"] < 0.05]),
        "inferred_tfs": top_results,
        "sources": ["DoRothEA (A/B/C)", "TRRUST v2"],
    }

    if redis:
        await redis.set(cache_key, json.dumps(result), ex=86400)

    return result


# ---------------------------------------------------------------------------
# Batch Reverse Query: Multiple gene sets → TF inference per set
# ---------------------------------------------------------------------------
async def infer_tf_activity_batch(
    gene_sets: Dict[str, List[str]],
    species: str = "mouse",
    min_confidence: str = "medium",
    min_targets_overlap: int = 3,
    top_n: int = 10,
    redis=None,
) -> dict:
    """
    Infer TF activity for multiple gene sets (e.g., per-timepoint changed genes).

    Args:
        gene_sets: Dict of {label: gene_list} (e.g., {"5min": [...], "15min": [...]})
        species: 'mouse' or 'human'

    Returns:
        Dict with per-set TF inference results.
    """
    results = {}
    for label, genes in gene_sets.items():
        r = await infer_tf_activity(
            gene_list=genes,
            species=species,
            min_confidence=min_confidence,
            min_targets_overlap=min_targets_overlap,
            top_n=top_n,
            redis=redis,
        )
        results[label] = r

    return {
        "n_sets": len(gene_sets),
        "species": species,
        "results": results,
    }
