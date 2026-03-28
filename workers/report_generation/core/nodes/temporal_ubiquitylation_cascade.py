"""
Temporal Ubiquitylation Cascade — v9.14

Module 3 of the Ubiquitylation Analysis Suite.

Analyzes the temporal dynamics of ubiquitylation events across timepoints:

1. Phospho-Ub Cross-talk Detection
   - Identifies proteins where phosphorylation precedes ubiquitylation (phosphodegron)
   - Detects kinase-E3 ligase co-regulation of the same substrate
   - Infers phosphorylation-dependent E3 recognition (e.g., CK1/GSK3 → FBXW7/BTRC)

2. DUB Activity Inference
   - Detects ubiquitylation sites that decrease over time → DUB activation
   - Identifies candidate DUBs based on chain type and temporal pattern
   - Distinguishes transient (signaling) vs sustained (degradation) ubiquitylation

3. Degradation vs Stabilization Timeline
   - K48/K11 increase → protein degradation prediction
   - K63/Mono increase → signaling amplification
   - K48 decrease (without protein decrease) → DUB-mediated stabilization

4. Temporal E3-Kinase Co-regulation
   - Identifies timepoints where both kinase and E3 ligase target the same protein
   - Infers signaling cascade order: kinase phosphorylation → E3 recognition → ubiquitylation

Output:
  {
    "phospho_ub_crosstalk": [...],
    "dub_inference": [...],
    "degradation_timeline": {...},
    "temporal_e3_kinase_coregulation": [...],
    "signaling_cascade_order": [...],
    "summary": {...},
    "llm_context": str,
  }
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── Phosphodegron Kinase → E3 Ligase Pairs ───────────────────────────────────
# Key: kinase that creates the phosphodegron
# Value: E3 ligase that recognizes the phosphodegron
PHOSPHODEGRON_PAIRS: Dict[str, Dict] = {
    # SCF-FBXW7 phosphodegrons (dual phosphorylation)
    "GSK3":    {"e3": "FBXW7", "substrates": ["CCNE1", "MYC", "NOTCH1", "JUN", "MCL1"],
                "mechanism": "GSK3 phosphorylates T380/T384 of CCNE1 creating FBXW7 degron"},
    "CDK2":    {"e3": "FBXW7", "substrates": ["CCNE1", "MYC"],
                "mechanism": "CDK2 phosphorylates T62 of MYC, priming for GSK3-T58 → FBXW7"},
    "CK1":     {"e3": "BTRC", "substrates": ["CTNNB1", "NFKBIA", "CDC25A"],
                "mechanism": "CK1 phosphorylates S45 of CTNNB1, priming for GSK3 → BTRC/β-TrCP"},
    "CK2":     {"e3": "BTRC", "substrates": ["NFKBIA", "CDC25A"],
                "mechanism": "CK2 phosphorylates S32/S36 of NFKBIA → BTRC recognition"},
    # SCF-SKP2 phosphodegrons
    "CDK2_SKP2": {"e3": "SKP2", "substrates": ["CDKN1B", "CDKN1A"],
                  "mechanism": "CDK2/CDK4 phosphorylates T187 of CDKN1B → SKP2 recognition"},
    "CDK4":    {"e3": "SKP2", "substrates": ["CDKN1B"],
                "mechanism": "CDK4 phosphorylates CDKN1B T187 → SCF-SKP2 degradation"},
    # VHL (oxygen-sensing)
    "PHD1":    {"e3": "VHL", "substrates": ["HIF1A", "HIF2A"],
                "mechanism": "PHD1/2/3 hydroxylates HIF-α P402/P564 → VHL recognition"},
    "PHD2":    {"e3": "VHL", "substrates": ["HIF1A", "HIF2A"],
                "mechanism": "PHD2 is the primary HIF-α prolyl hydroxylase"},
    # MDM2 (p53 regulation)
    "ATM":     {"e3": "MDM2", "substrates": ["TP53"],
                "mechanism": "ATM phosphorylates TP53 S15/S20 → MDM2 dissociation (stabilization)"},
    "CHK2":    {"e3": "MDM2", "substrates": ["TP53"],
                "mechanism": "CHK2 phosphorylates TP53 S20 → MDM2 binding disruption"},
    "AKT":     {"e3": "MDM2", "substrates": ["MDM2"],
                "mechanism": "AKT phosphorylates MDM2 S166/S186 → MDM2 nuclear translocation and p53 degradation"},
    # KEAP1-NRF2
    "GSK3_KEAP1": {"e3": "KEAP1", "substrates": ["NFE2L2"],
                   "mechanism": "GSK3 phosphorylates NRF2 → KEAP1-independent degradation via β-TrCP"},
    # NEDD4 family (PY-motif substrates)
    "DYRK2":   {"e3": "SMURF2", "substrates": ["SMAD2", "SMAD3"],
                "mechanism": "DYRK2 phosphorylates SMAD2/3 → SMURF2 recognition"},
    "ERK1/ERK2": {"e3": "FBXW7", "substrates": ["MYC"],
                  "mechanism": "ERK phosphorylates MYC S62 (stabilizing), primes for CDK2-T58 → FBXW7"},
    # APC/C substrates
    "PLK1":    {"e3": "APC/C", "substrates": ["CCNB1", "SECURIN"],
                "mechanism": "PLK1 phosphorylates APC/C activators → APC/C-CDC20 activation"},
    "CDK1":    {"e3": "APC/C", "substrates": ["CCNB1", "SECURIN", "PLK1"],
                "mechanism": "CDK1 phosphorylates CDC20 → APC/C-CDC20 activation at mitotic exit"},
}

# ── DUB Activity Signatures ───────────────────────────────────────────────────
# Patterns that suggest DUB activity
DUB_ACTIVITY_SIGNATURES: Dict[str, Dict] = {
    "K48_decrease": {
        "chain_type": "K48",
        "pattern": "decreasing",
        "interpretation": "Proteasomal degradation completed OR DUB-mediated stabilization",
        "candidate_dubs": ["USP7", "USP14", "UCHL5", "MINDY1"],
    },
    "K63_decrease": {
        "chain_type": "K63",
        "pattern": "decreasing",
        "interpretation": "Signal termination via DUB (CYLD, A20, OTUB2, BRCC3)",
        "candidate_dubs": ["CYLD", "A20", "OTUB2", "BRCC3", "USP4"],
    },
    "Mono_decrease": {
        "chain_type": "Mono",
        "pattern": "decreasing",
        "interpretation": "Receptor recycling or transcriptional reset",
        "candidate_dubs": ["USP8", "BAP1", "USP16", "USP22"],
    },
    "M1_decrease": {
        "chain_type": "M1",
        "pattern": "decreasing",
        "interpretation": "NF-κB signal termination via OTULIN or CYLD",
        "candidate_dubs": ["OTULIN", "CYLD"],
    },
    "transient_K48": {
        "chain_type": "K48",
        "pattern": "transient_peak",
        "interpretation": "Rapid ubiquitylation-degradation cycle; substrate is regenerated",
        "candidate_dubs": [],
    },
}

# ── Temporal Pattern Definitions ─────────────────────────────────────────────
TEMPORAL_PATTERNS = {
    "sustained_increase": "Continuous ubiquitylation accumulation → likely degradation (K48) or persistent signaling (K63)",
    "transient_peak":     "Peak then decrease → either degradation completed or DUB-mediated reversal",
    "late_onset":         "Ubiquitylation appears only at late timepoints → secondary response",
    "early_burst":        "Ubiquitylation peaks early then resolves → rapid signaling event",
    "oscillating":        "Alternating high/low → active E3-DUB cycling",
    "stable":             "Constant ubiquitylation → constitutive modification",
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

def build_temporal_ubiquitylation_cascade(
    enriched_data: List[dict],
    chain_classifications: Dict[str, dict],
    e3_modules: List[dict],
    clusters: List[dict],
    comovement_analysis: dict,
    ptm_type: str = "ubiquitylation",
) -> dict:
    """
    Build temporal ubiquitylation cascade analysis.

    Args:
        enriched_data: Full enriched_ptm_data from state
        chain_classifications: Output of classify_ubiquitin_chain_types()
        e3_modules: Output of build_e3_ligase_modules()["e3_modules"]
        clusters: Co-wave cluster list
        comovement_analysis: Full comovement analysis from state
        ptm_type: Should be 'ubiquitylation'

    Returns:
        Dict with phospho_ub_crosstalk, dub_inference, degradation_timeline, etc.
    """
    if ptm_type != "ubiquitylation":
        return {"llm_context": ""}

    # ── Step 1: Build protein-level data map ─────────────────────────────
    protein_map = _build_protein_map(enriched_data, chain_classifications)

    # ── Step 2: Detect Phospho-Ub Cross-talk ─────────────────────────────
    phospho_ub_crosstalk = _detect_phospho_ub_crosstalk(
        enriched_data, chain_classifications, e3_modules
    )

    # ── Step 3: DUB Activity Inference ───────────────────────────────────
    dub_inference = _infer_dub_activity(clusters, chain_classifications, protein_map)

    # ── Step 4: Degradation vs Stabilization Timeline ────────────────────
    degradation_timeline = _build_degradation_timeline(
        clusters, chain_classifications, protein_map
    )

    # ── Step 5: Temporal E3-Kinase Co-regulation ─────────────────────────
    e3_kinase_coregulation = _detect_e3_kinase_coregulation(
        enriched_data, chain_classifications, e3_modules, clusters
    )

    # ── Step 6: Signaling Cascade Order ──────────────────────────────────
    cascade_order = _build_signaling_cascade_order(
        phospho_ub_crosstalk, e3_kinase_coregulation, clusters
    )

    # ── Step 7: Summary ───────────────────────────────────────────────────
    summary = {
        "total_phospho_ub_crosstalk": len(phospho_ub_crosstalk),
        "total_dub_inferences": len(dub_inference),
        "degradation_events": len(degradation_timeline.get("degradation_events", [])),
        "stabilization_events": len(degradation_timeline.get("stabilization_events", [])),
        "e3_kinase_coregulated_proteins": len(e3_kinase_coregulation),
        "cascade_steps": len(cascade_order),
    }

    llm_context = _build_temporal_ub_llm_context(
        phospho_ub_crosstalk, dub_inference, degradation_timeline,
        e3_kinase_coregulation, cascade_order, summary
    )

    return {
        "phospho_ub_crosstalk": phospho_ub_crosstalk,
        "dub_inference": dub_inference,
        "degradation_timeline": degradation_timeline,
        "temporal_e3_kinase_coregulation": e3_kinase_coregulation,
        "signaling_cascade_order": cascade_order,
        "summary": summary,
        "llm_context": llm_context,
    }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: PROTEIN MAP
# ═══════════════════════════════════════════════════════════════════════════

def _build_protein_map(
    enriched_data: List[dict],
    chain_classifications: Dict[str, dict],
) -> Dict[str, dict]:
    """Build gene → {ptm_sites, chain_types, e3_ligases, trajectory} map."""
    protein_map: Dict[str, dict] = {}

    for entry in enriched_data:
        gene = (entry.get("gene") or entry.get("Gene.Name", "")).strip().upper()
        pos = str(entry.get("position") or entry.get("PTM_Position", "")).strip()
        if not gene or not pos:
            continue

        ptm_key = f"{gene}_{pos}"
        cls = chain_classifications.get(ptm_key, {})

        if gene not in protein_map:
            protein_map[gene] = {
                "gene": gene,
                "ptm_sites": [],
                "chain_types": set(),
                "e3_ligases": set(),
                "dub_candidates": set(),
                "functional_categories": set(),
                "trajectory": entry.get("rag_enrichment", {}).get("trajectory", {}),
            }

        protein_map[gene]["ptm_sites"].append(ptm_key)
        protein_map[gene]["chain_types"].update(cls.get("inferred_chain_types", []))
        protein_map[gene]["e3_ligases"].update(cls.get("e3_ligases", []))
        protein_map[gene]["dub_candidates"].update(cls.get("dub_candidates", []))
        protein_map[gene]["functional_categories"].add(cls.get("functional_category", "unknown"))

    # Convert sets to lists for serialization
    for gene, data in protein_map.items():
        data["chain_types"] = sorted(data["chain_types"])
        data["e3_ligases"] = sorted(data["e3_ligases"])
        data["dub_candidates"] = sorted(data["dub_candidates"])
        data["functional_categories"] = sorted(data["functional_categories"])

    return protein_map


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: PHOSPHO-UB CROSS-TALK DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def _detect_phospho_ub_crosstalk(
    enriched_data: List[dict],
    chain_classifications: Dict[str, dict],
    e3_modules: List[dict],
) -> List[dict]:
    """Detect proteins where phosphorylation creates E3 recognition sites (phosphodegrons)."""
    crosstalk_events = []

    # Build gene → E3 ligases map from e3_modules
    gene_e3_map: Dict[str, List[str]] = defaultdict(list)
    for mod in e3_modules:
        for sub in mod["confirmed_substrates"] + mod["inferred_substrates"]:
            gene_e3_map[sub["gene"]].append(mod["canonical"])

    for entry in enriched_data:
        gene = (entry.get("gene") or entry.get("Gene.Name", "")).strip().upper()
        pos = str(entry.get("position") or entry.get("PTM_Position", "")).strip()
        if not gene or not pos:
            continue

        ptm_key = f"{gene}_{pos}"
        rag = entry.get("rag_enrichment", {}) or {}
        regulation = rag.get("regulation", {}) or {}

        # Check if this gene has both phosphorylation and ubiquitylation evidence
        # (in a multi-PTM experiment, this would be cross-referenced)
        # Here we check if known phosphodegron kinases target this gene

        # Check upstream regulators for phosphodegron kinases
        upstream = regulation.get("upstream_regulators", [])
        upstream_names = [
            (u if isinstance(u, str) else u.get("name", "")).upper()
            for u in upstream
        ]

        # Check kinase_substrate pairs
        ks_pairs = regulation.get("kinase_substrate", [])
        kinase_names = [ks.get("kinase", "").upper() for ks in ks_pairs]
        all_kinases = list(set(upstream_names + kinase_names))

        # Also check LLM prediction
        kp = rag.get("kinase_prediction", {}) or {}
        if isinstance(kp, dict):
            for pk in kp.get("predictedKinases", kp.get("predicted_kinases", [])):
                if isinstance(pk, dict):
                    kname = (pk.get("kinase") or "").upper()
                    if kname:
                        all_kinases.append(kname)

        # Match against phosphodegron pairs
        for kinase in all_kinases:
            for pd_kinase, pd_info in PHOSPHODEGRON_PAIRS.items():
                if pd_kinase.upper() in kinase or kinase in pd_kinase.upper():
                    e3 = pd_info["e3"]
                    # Check if this gene is a known substrate of this E3
                    is_known_substrate = gene in [s.upper() for s in pd_info.get("substrates", [])]
                    # Check if E3 is also detected for this gene
                    has_e3_evidence = e3.upper() in [e.upper() for e in gene_e3_map.get(gene, [])]

                    if is_known_substrate or has_e3_evidence:
                        cls = chain_classifications.get(ptm_key, {})
                        crosstalk_events.append({
                            "gene": gene,
                            "position": pos,
                            "ptm_key": ptm_key,
                            "kinase": pd_kinase,
                            "e3_ligase": e3,
                            "chain_type": pd_info.get("substrates", []),
                            "mechanism": pd_info["mechanism"],
                            "confidence": "high" if is_known_substrate else "medium",
                            "functional_consequence": _get_phosphodegron_consequence(e3, gene),
                            "ubiquitin_chain_types": cls.get("inferred_chain_types", []),
                        })
                        break  # One match per kinase

    # Deduplicate by gene+kinase+e3
    seen = set()
    unique_events = []
    for ev in crosstalk_events:
        key = f"{ev['gene']}_{ev['kinase']}_{ev['e3_ligase']}"
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)

    return sorted(unique_events, key=lambda x: x["confidence"] == "high", reverse=True)


def _get_phosphodegron_consequence(e3: str, gene: str) -> str:
    """Get biological consequence of phosphodegron-mediated ubiquitylation."""
    consequences = {
        "FBXW7": f"K48-linked polyubiquitylation of {gene} → proteasomal degradation (SCF-FBXW7)",
        "BTRC":  f"K48-linked polyubiquitylation of {gene} → proteasomal degradation (SCF-β-TrCP)",
        "SKP2":  f"K48-linked polyubiquitylation of {gene} → proteasomal degradation (SCF-SKP2)",
        "VHL":   f"K48-linked polyubiquitylation of {gene} → proteasomal degradation (CRL2-VHL)",
        "MDM2":  f"K48-linked polyubiquitylation of {gene} → nuclear export and proteasomal degradation",
        "APC/C": f"K11/K48-linked polyubiquitylation of {gene} → mitotic degradation (APC/C)",
        "KEAP1": f"K48-linked polyubiquitylation of {gene} → proteasomal degradation (CRL3-KEAP1)",
    }
    return consequences.get(e3, f"Ubiquitylation of {gene} mediated by {e3}")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3: DUB ACTIVITY INFERENCE
# ═══════════════════════════════════════════════════════════════════════════

def _infer_dub_activity(
    clusters: List[dict],
    chain_classifications: Dict[str, dict],
    protein_map: Dict[str, dict],
) -> List[dict]:
    """Infer DUB activity from temporal ubiquitylation patterns."""
    from common.temporal_utils import tp_to_minutes

    dub_inferences = []

    if not clusters:
        return dub_inferences

    # Sort clusters by peak timepoint
    sorted_clusters = sorted(
        clusters,
        key=lambda c: tp_to_minutes(c.get("peak_timepoint", "0min"))
    )

    # Build timepoint → PTM activity map
    tp_activity: Dict[str, Dict[str, float]] = {}
    for cluster in sorted_clusters:
        peak_tp = cluster.get("peak_timepoint", "")
        if not peak_tp:
            continue

        for md in cluster.get("member_details", []):
            ptm_key = md.get("key", "")
            if not ptm_key:
                continue

            # Get log2FC as activity measure
            log2fc = md.get("log2fc", md.get("ptm_log2fc", 0)) or 0
            if peak_tp not in tp_activity:
                tp_activity[peak_tp] = {}
            tp_activity[peak_tp][ptm_key] = float(log2fc)

    # Identify PTMs that peak early then decrease (DUB activity signature)
    sorted_tps = sorted(tp_activity.keys(), key=lambda t: tp_to_minutes(t))

    if len(sorted_tps) < 2:
        return dub_inferences

    for ptm_key, cls in chain_classifications.items():
        chain_types = cls.get("inferred_chain_types", [])
        if not chain_types:
            continue

        # Get activity at each timepoint
        activities = []
        for tp in sorted_tps:
            act = tp_activity.get(tp, {}).get(ptm_key)
            if act is not None:
                activities.append((tp, act))

        if len(activities) < 2:
            continue

        # Detect temporal pattern
        pattern = _classify_temporal_pattern(activities)

        if pattern in ("transient_peak", "decreasing"):
            # Infer DUB activity
            primary_chain = chain_types[0] if chain_types else "unknown"
            sig_key = f"{primary_chain}_decrease" if pattern == "decreasing" else f"transient_{primary_chain}"
            sig = DUB_ACTIVITY_SIGNATURES.get(sig_key, DUB_ACTIVITY_SIGNATURES.get(f"{primary_chain}_decrease", {}))

            if sig:
                peak_tp = max(activities, key=lambda x: x[1])[0]
                nadir_tp = min(activities, key=lambda x: x[1])[0]

                dub_inferences.append({
                    "ptm_key": ptm_key,
                    "gene": cls.get("gene", ""),
                    "position": cls.get("position", ""),
                    "chain_types": chain_types,
                    "temporal_pattern": pattern,
                    "peak_timepoint": peak_tp,
                    "nadir_timepoint": nadir_tp,
                    "candidate_dubs": sig.get("candidate_dubs", []) + cls.get("dub_candidates", []),
                    "interpretation": sig.get("interpretation", "DUB activity inferred"),
                    "functional_category": cls.get("functional_category", "unknown"),
                })

    return dub_inferences[:30]  # Limit to top 30


def _classify_temporal_pattern(activities: List[Tuple[str, float]]) -> str:
    """Classify the temporal activity pattern of a PTM site."""
    if len(activities) < 2:
        return "stable"

    values = [a[1] for a in activities]
    max_val = max(values)
    min_val = min(values)
    first_val = values[0]
    last_val = values[-1]
    max_idx = values.index(max_val)

    if max_val - min_val < 0.5:
        return "stable"

    # Transient peak: rises then falls
    if 0 < max_idx < len(values) - 1:
        if values[max_idx] > values[0] + 0.5 and values[max_idx] > values[-1] + 0.5:
            return "transient_peak"

    # Sustained increase
    if last_val > first_val + 0.5 and values[-1] == max_val:
        if max_idx == len(values) - 1:
            return "sustained_increase"

    # Decreasing
    if first_val > last_val + 0.5 and values[0] == max_val:
        return "decreasing"

    # Late onset
    if max_idx >= len(values) * 0.6 and values[0] < max_val - 0.5:
        return "late_onset"

    # Early burst
    if max_idx == 0 and last_val < max_val - 0.5:
        return "early_burst"

    return "variable"


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4: DEGRADATION vs STABILIZATION TIMELINE
# ═══════════════════════════════════════════════════════════════════════════

def _build_degradation_timeline(
    clusters: List[dict],
    chain_classifications: Dict[str, dict],
    protein_map: Dict[str, dict],
) -> dict:
    """Build timeline of predicted degradation and stabilization events."""
    from common.temporal_utils import tp_to_minutes

    degradation_events = []
    stabilization_events = []

    if not clusters:
        return {"degradation_events": [], "stabilization_events": [], "timeline_by_tp": {}}

    sorted_clusters = sorted(
        clusters,
        key=lambda c: tp_to_minutes(c.get("peak_timepoint", "0min"))
    )

    timeline_by_tp: Dict[str, dict] = {}

    for cluster in sorted_clusters:
        peak_tp = cluster.get("peak_timepoint", "")
        if not peak_tp:
            continue

        if peak_tp not in timeline_by_tp:
            timeline_by_tp[peak_tp] = {
                "timepoint": peak_tp,
                "minutes": tp_to_minutes(peak_tp),
                "degradation": [],
                "stabilization": [],
                "signaling": [],
            }

        for md in cluster.get("member_details", []):
            ptm_key = md.get("key", "")
            if not ptm_key:
                continue

            cls = chain_classifications.get(ptm_key, {})
            chain_types = cls.get("inferred_chain_types", [])
            func_cat = cls.get("functional_category", "unknown")
            gene = cls.get("gene", ptm_key.split("_")[0])
            log2fc = float(md.get("log2fc", md.get("ptm_log2fc", 0)) or 0)

            if log2fc > 0.5:  # Increasing ubiquitylation
                if func_cat == "degradation" or "K48" in chain_types or "K11" in chain_types:
                    event = {
                        "ptm_key": ptm_key,
                        "gene": gene,
                        "timepoint": peak_tp,
                        "chain_types": chain_types,
                        "log2fc": log2fc,
                        "e3_ligases": cls.get("e3_ligases", []),
                        "prediction": f"Proteasomal degradation of {gene} predicted at {peak_tp}",
                    }
                    degradation_events.append(event)
                    timeline_by_tp[peak_tp]["degradation"].append(gene)

                elif func_cat in ("signaling", "immune", "dna_repair") or "K63" in chain_types or "M1" in chain_types:
                    event = {
                        "ptm_key": ptm_key,
                        "gene": gene,
                        "timepoint": peak_tp,
                        "chain_types": chain_types,
                        "log2fc": log2fc,
                        "prediction": f"Non-degradative ubiquitylation of {gene} at {peak_tp} → signaling",
                    }
                    timeline_by_tp[peak_tp]["signaling"].append(gene)

            elif log2fc < -0.5:  # Decreasing ubiquitylation
                if "K48" in chain_types:
                    event = {
                        "ptm_key": ptm_key,
                        "gene": gene,
                        "timepoint": peak_tp,
                        "chain_types": chain_types,
                        "log2fc": log2fc,
                        "dub_candidates": cls.get("dub_candidates", []),
                        "prediction": f"Stabilization of {gene} at {peak_tp} (K48 removal by DUB)",
                    }
                    stabilization_events.append(event)
                    timeline_by_tp[peak_tp]["stabilization"].append(gene)

    return {
        "degradation_events": sorted(degradation_events, key=lambda x: abs(x["log2fc"]), reverse=True)[:20],
        "stabilization_events": sorted(stabilization_events, key=lambda x: abs(x["log2fc"]), reverse=True)[:10],
        "timeline_by_tp": timeline_by_tp,
    }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5: E3-KINASE CO-REGULATION
# ═══════════════════════════════════════════════════════════════════════════

def _detect_e3_kinase_coregulation(
    enriched_data: List[dict],
    chain_classifications: Dict[str, dict],
    e3_modules: List[dict],
    clusters: List[dict],
) -> List[dict]:
    """Detect proteins co-regulated by both kinases and E3 ligases."""
    coregulated = []

    # Build gene → E3 map
    gene_e3_map: Dict[str, List[str]] = defaultdict(list)
    for mod in e3_modules:
        for sub in mod["confirmed_substrates"] + mod["inferred_substrates"]:
            gene_e3_map[sub["gene"]].append(mod["e3_ligase"])

    for entry in enriched_data:
        gene = (entry.get("gene") or entry.get("Gene.Name", "")).strip().upper()
        pos = str(entry.get("position") or entry.get("PTM_Position", "")).strip()
        if not gene or not pos:
            continue

        ptm_key = f"{gene}_{pos}"
        rag = entry.get("rag_enrichment", {}) or {}
        regulation = rag.get("regulation", {}) or {}

        # Get kinase evidence
        kinases = []
        for ks in regulation.get("kinase_substrate", []):
            k = ks.get("kinase", "")
            if k:
                kinases.append(k)

        kp = rag.get("kinase_prediction", {}) or {}
        if isinstance(kp, dict):
            for pk in kp.get("predictedKinases", kp.get("predicted_kinases", [])):
                if isinstance(pk, dict):
                    k = pk.get("kinase", "")
                    if k:
                        kinases.append(k)

        # Get E3 evidence
        e3s = gene_e3_map.get(gene, [])

        if kinases and e3s:
            cls = chain_classifications.get(ptm_key, {})

            # Check for known phosphodegron pairs
            pd_matches = []
            for kinase in kinases:
                for pd_kinase, pd_info in PHOSPHODEGRON_PAIRS.items():
                    if pd_kinase.upper() in kinase.upper():
                        if pd_info["e3"].upper() in [e.upper() for e in e3s]:
                            pd_matches.append({
                                "kinase": kinase,
                                "e3": pd_info["e3"],
                                "mechanism": pd_info["mechanism"],
                            })

            coregulated.append({
                "gene": gene,
                "position": pos,
                "ptm_key": ptm_key,
                "kinases": list(set(kinases))[:5],
                "e3_ligases": list(set(e3s))[:5],
                "phosphodegron_matches": pd_matches,
                "chain_types": cls.get("inferred_chain_types", []),
                "functional_category": cls.get("functional_category", "unknown"),
                "is_phosphodegron": len(pd_matches) > 0,
            })

    # Sort: phosphodegron matches first
    coregulated.sort(key=lambda x: (x["is_phosphodegron"], len(x["kinases"]) + len(x["e3_ligases"])), reverse=True)
    return coregulated[:20]


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6: SIGNALING CASCADE ORDER
# ═══════════════════════════════════════════════════════════════════════════

def _build_signaling_cascade_order(
    phospho_ub_crosstalk: List[dict],
    e3_kinase_coregulation: List[dict],
    clusters: List[dict],
) -> List[dict]:
    """Build ordered signaling cascade steps."""
    from common.temporal_utils import tp_to_minutes

    cascade_steps = []

    # From phospho-ub crosstalk: kinase → E3 → substrate
    for event in phospho_ub_crosstalk[:10]:
        cascade_steps.append({
            "step_type": "phosphodegron_cascade",
            "gene": event["gene"],
            "kinase": event["kinase"],
            "e3_ligase": event["e3_ligase"],
            "mechanism": event["mechanism"],
            "consequence": event["functional_consequence"],
            "confidence": event["confidence"],
        })

    # From temporal clusters: early → late E3 activation
    if clusters:
        sorted_clusters = sorted(
            clusters,
            key=lambda c: tp_to_minutes(c.get("peak_timepoint", "0min"))
        )
        if len(sorted_clusters) >= 2:
            early = sorted_clusters[0]
            late = sorted_clusters[-1]
            cascade_steps.append({
                "step_type": "temporal_e3_cascade",
                "early_timepoint": early.get("peak_timepoint", ""),
                "late_timepoint": late.get("peak_timepoint", ""),
                "description": (
                    f"Ubiquitylation events at {early.get('peak_timepoint', '?')} "
                    f"precede those at {late.get('peak_timepoint', '?')}"
                ),
            })

    return cascade_steps


# ═══════════════════════════════════════════════════════════════════════════
# LLM CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def _build_temporal_ub_llm_context(
    phospho_ub_crosstalk: List[dict],
    dub_inference: List[dict],
    degradation_timeline: dict,
    e3_kinase_coregulation: List[dict],
    cascade_order: List[dict],
    summary: dict,
) -> str:
    """Build LLM context string for temporal ubiquitylation cascade analysis."""
    lines = [
        "═══════════════════════════════════════════════════════════════",
        "TEMPORAL UBIQUITYLATION CASCADE ANALYSIS (Module 3 — v9.14)",
        "═══════════════════════════════════════════════════════════════",
        "",
        f"Phospho-Ub cross-talk events:      {summary['total_phospho_ub_crosstalk']}",
        f"DUB activity inferences:           {summary['total_dub_inferences']}",
        f"Predicted degradation events:      {summary['degradation_events']}",
        f"Predicted stabilization events:    {summary['stabilization_events']}",
        f"E3-Kinase co-regulated proteins:   {summary['e3_kinase_coregulated_proteins']}",
        "",
        "── Section A: Phospho-Ubiquitin Cross-talk (Phosphodegrons) ─",
    ]

    if phospho_ub_crosstalk:
        for ev in phospho_ub_crosstalk[:8]:
            conf = ev.get("confidence", "?")
            lines.append(
                f"  {ev['gene']:10s} | Kinase: {ev['kinase']:12s} → E3: {ev['e3_ligase']:10s} [{conf}]"
            )
            lines.append(f"    Mechanism: {ev['mechanism'][:120]}")
            lines.append(f"    Consequence: {ev['functional_consequence'][:100]}")
    else:
        lines.append("  No phosphodegron cross-talk detected in this dataset")

    lines += [
        "",
        "── Section B: DUB Activity Inference ────────────────────────",
    ]
    if dub_inference:
        for inf in dub_inference[:8]:
            chain_str = "/".join(inf.get("chain_types", ["?"]))
            dubs = ", ".join(inf.get("candidate_dubs", [])[:3]) or "unknown"
            lines.append(
                f"  {inf['ptm_key']:20s} [{chain_str:12s}] pattern: {inf['temporal_pattern']:15s}"
            )
            lines.append(f"    Candidate DUBs: {dubs}")
            lines.append(f"    → {inf['interpretation'][:100]}")
    else:
        lines.append("  No DUB activity patterns detected")

    lines += [
        "",
        "── Section C: Degradation vs Stabilization Timeline ─────────",
    ]
    timeline = degradation_timeline.get("timeline_by_tp", {})
    for tp, data in sorted(timeline.items()):
        deg = ", ".join(data.get("degradation", [])[:4])
        stab = ", ".join(data.get("stabilization", [])[:3])
        sig = ", ".join(data.get("signaling", [])[:4])
        if deg or stab or sig:
            lines.append(f"  {tp:8s}:")
            if deg:
                lines.append(f"    Degradation: {deg}")
            if stab:
                lines.append(f"    Stabilization (DUB): {stab}")
            if sig:
                lines.append(f"    Signaling (K63/M1): {sig}")

    lines += [
        "",
        "── Section D: E3 Ligase - Kinase Co-regulation ──────────────",
    ]
    phosphodegron_cases = [c for c in e3_kinase_coregulation if c.get("is_phosphodegron")]
    if phosphodegron_cases:
        for case in phosphodegron_cases[:6]:
            kinase_str = ", ".join(case["kinases"][:3])
            e3_str = ", ".join(case["e3_ligases"][:3])
            chain_str = "/".join(case.get("chain_types", ["?"]))
            lines.append(f"  {case['gene']:10s}: Kinases [{kinase_str}] + E3s [{e3_str}] → {chain_str}")
            for pd in case.get("phosphodegron_matches", [])[:2]:
                lines.append(f"    Phosphodegron: {pd['mechanism'][:100]}")
    else:
        lines.append("  No phosphodegron co-regulation detected")

    lines += [
        "",
        "── Section E: Signaling Cascade Order ───────────────────────",
    ]
    for step in cascade_order[:8]:
        if step["step_type"] == "phosphodegron_cascade":
            lines.append(
                f"  {step['kinase']:12s} → phosphorylation → {step['gene']:10s} "
                f"→ {step['e3_ligase']:10s} → ubiquitylation"
            )
            lines.append(f"    → {step['consequence'][:100]}")
        elif step["step_type"] == "temporal_e3_cascade":
            lines.append(f"  Temporal order: {step['description']}")

    lines += [
        "",
        "── LLM Instructions ─────────────────────────────────────────",
        "CRITICAL BIOLOGICAL INSIGHTS FOR REPORT WRITING:",
        "1. Phosphodegrons represent a key mechanism linking kinase signaling to protein degradation",
        "   — Discuss the temporal order: kinase activation → substrate phosphorylation → E3 recognition → degradation",
        "2. DUB activity creates reversibility — ubiquitylation is NOT always a one-way degradation signal",
        "   — Mention DUB-mediated stabilization where evidence exists",
        "3. Distinguish degradative (K48/K11) from signaling (K63/M1/Mono) ubiquitylation in the same dataset",
        "4. E3-Kinase co-regulation of the same substrate indicates integrated signaling control",
        "5. Temporal cascade: early ubiquitylation events may prime or inhibit later events",
        "   — Discuss how ubiquitylation of early-response proteins shapes the late response",
        "═══════════════════════════════════════════════════════════════",
    ]

    return "\n".join(lines)
