"""
Temporal Analysis — Non-PTM effector dynamics, PTM-protein timelag, and
Signal Propagation JSON builders.

Ported from ptm-chromadb-web/python_backend/ptm_nonptm_network_command.py
(v80, v81).  Adapted to use PTM-platform's LLMClient and logging.
"""

import logging
from typing import Any, Dict, List, Optional

from common.temporal_utils import tp_to_minutes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# v80: Non-PTM Temporal Abundance Analysis
# ---------------------------------------------------------------------------

def build_nonptm_temporal_analysis(
    results: dict, timepoints: List[str], ptm_type: str
) -> str:
    """Analyze temporal protein abundance dynamics of non-PTM interactors.

    Extracts protein_log2fc from non_ptm_nodes across all timepoints and
    classifies response kinetics (immediate / delayed / sustained / biphasic).

    Returns formatted string for LLM context injection.
    """
    networks = results.get("networks", {})

    # Track non-PTM proteins across all timepoints
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
            protein_log2fc = node.get("protein_log2fc", node.get("log2fc", 0))

            if gene not in nonptm_temporal:
                nonptm_temporal[gene] = {}
                nonptm_roles[gene] = role
            nonptm_temporal[gene][tp] = protein_log2fc

    if not nonptm_temporal:
        return ""

    parts = [
        "\n## NON-PTM EFFECTOR PROTEIN TEMPORAL DYNAMICS\n",
        "These are downstream effector proteins (kinases, interactors, scaffolds) whose",
        "protein abundance changes reflect the propagation of upstream PTM signaling events.\n",
    ]

    # Classify each non-PTM protein's temporal response
    classified = []  # (gene, role, pattern, max_change, temporal_data)

    for gene, tp_data in nonptm_temporal.items():
        sorted_tps = sorted(tp_data.keys(), key=tp_to_minutes)
        values = [tp_data[tp] for tp in sorted_tps]
        max_abs = max(abs(v) for v in values) if values else 0

        # Classify response kinetics
        early_tps = [tp for tp in sorted_tps if tp_to_minutes(tp) <= 15]
        late_tps = [tp for tp in sorted_tps if tp_to_minutes(tp) > 15]
        early_sig = any(abs(tp_data[tp]) >= 0.3 for tp in early_tps)
        late_sig = any(abs(tp_data[tp]) >= 0.3 for tp in late_tps)

        if early_sig and late_sig:
            early_vals = [tp_data[tp] for tp in early_tps if abs(tp_data[tp]) >= 0.3]
            late_vals = [tp_data[tp] for tp in late_tps if abs(tp_data[tp]) >= 0.3]
            if early_vals and late_vals:
                if (early_vals[0] > 0 and late_vals[-1] < 0) or (
                    early_vals[0] < 0 and late_vals[-1] > 0
                ):
                    pattern = "biphasic_switch"
                else:
                    pattern = "sustained_response"
            else:
                pattern = "sustained_response"
        elif early_sig:
            pattern = "immediate_early_response"
        elif late_sig:
            pattern = "delayed_effector_response"
        else:
            pattern = "stable_baseline"

        classified.append((gene, nonptm_roles.get(gene, "interactor"), pattern, max_abs, tp_data))

    # Sort by max absolute change
    classified.sort(key=lambda x: x[3], reverse=True)

    # Summary statistics
    pattern_counts: Dict[str, int] = {}
    for _, _, pattern, _, _ in classified:
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

    parts.append("### Signal Propagation Summary")
    parts.append(f"Total downstream effector proteins tracked: {len(classified)}")
    for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
        label = {
            "immediate_early_response": "Immediate early responders (signal relay within 15min)",
            "delayed_effector_response": "Delayed effectors (transcriptional/translational response >15min)",
            "sustained_response": "Sustained responders (continuous signal integration)",
            "biphasic_switch": "Biphasic switchers (signal adaptation/feedback)",
            "stable_baseline": "Stable (no significant abundance change)",
        }.get(pattern, pattern)
        parts.append(f"  {label}: {count}")
    parts.append("")

    # Detailed table for top 20 most responsive
    responsive = [c for c in classified if c[2] != "stable_baseline"]
    if responsive:
        parts.append("### Top Effector Protein Temporal Profiles")
        header = (
            "| Effector Protein | Role | Response Kinetics | "
            + " | ".join([f"{tp}" for tp in timepoints])
            + " | Max |delta| |"
        )
        sep = "|" + "|".join(["---"] * (len(timepoints) + 4)) + "|"
        parts.append(header)
        parts.append(sep)

        for gene, role, pattern, max_abs, tp_data in responsive[:20]:
            kinetics_label = {
                "immediate_early_response": "Immediate early",
                "delayed_effector_response": "Delayed effector",
                "sustained_response": "Sustained",
                "biphasic_switch": "Biphasic",
            }.get(pattern, pattern)
            vals = [f"{tp_data.get(tp, 0):.2f}" for tp in timepoints]
            parts.append(
                f"| **{gene}** | {role} | {kinetics_label} | "
                + " | ".join(vals)
                + f" | {max_abs:.2f} |"
            )
        parts.append("")

    # Functional group analysis
    parts.append("### Coordinated Effector Group Responses")
    parts.append("Non-PTM proteins grouped by coordinated temporal behavior:\n")

    for pattern_key in [
        "immediate_early_response",
        "delayed_effector_response",
        "sustained_response",
        "biphasic_switch",
    ]:
        group = [c for c in classified if c[2] == pattern_key]
        if group:
            label = {
                "immediate_early_response": "Immediate Signal Relay Effectors (<=15min)",
                "delayed_effector_response": "Delayed Transcriptional/Translational Effectors (>15min)",
                "sustained_response": "Sustained Signal Integration Effectors",
                "biphasic_switch": "Biphasic Adaptation Effectors (direction switch)",
            }.get(pattern_key, pattern_key)
            up_genes = [g[0] for g in group if max(g[4].values()) > 0.3]
            down_genes = [g[0] for g in group if min(g[4].values()) < -0.3]
            parts.append(f"**{label}** ({len(group)} proteins)")
            if up_genes:
                parts.append(f"  Up-regulated: {', '.join(up_genes[:8])}")
            if down_genes:
                parts.append(f"  Down-regulated: {', '.join(down_genes[:8])}")
            parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# v80: PTM-Protein Timelag Analysis
# ---------------------------------------------------------------------------

def build_ptm_protein_timelag_analysis(
    results: dict, timepoints: List[str], ptm_type: str
) -> str:
    """Analyze temporal causality between PTM modifications and protein abundance
    changes in single-PTM mode.

    For each PTM protein:
      - Compare when the PTM change first exceeds threshold vs when protein
        abundance changes.
      - Infer causal mechanism from the time lag.

    For PTM->Non-PTM interactor pairs:
      - Compare when PTM modification appears on the substrate vs when the
        interactor's protein abundance changes.

    Returns formatted string for LLM context injection.
    """
    networks = results.get("networks", {})
    PTM_THRESHOLD = 0.3
    PROTEIN_THRESHOLD = 0.3

    # -- Part A: PTM self-regulation (same protein) --
    ptm_temporal: Dict[str, Dict[str, dict]] = {}

    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes"]:
            for node in net.get(node_type, []):
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", node.get("id", "Unknown"))
                site = node.get("site", "")
                key = f"{gene}({site})" if site else gene
                ptm_log2fc = node.get("value", node.get("ptm_log2fc", node.get("log2fc", 0)))
                protein_log2fc = node.get("protein_log2fc", 0)

                if key not in ptm_temporal:
                    ptm_temporal[key] = {}
                ptm_temporal[key][tp] = {
                    "ptm_log2fc": ptm_log2fc,
                    "protein_log2fc": protein_log2fc,
                    "gene": gene,
                    "site": site,
                }

    self_timelags = []

    for ptm_key, tp_data in ptm_temporal.items():
        sorted_tps = sorted(tp_data.keys(), key=tp_to_minutes)

        # Find first significant PTM change
        ptm_first_tp = None
        ptm_first_val = 0
        for tp in sorted_tps:
            if abs(tp_data[tp]["ptm_log2fc"]) >= PTM_THRESHOLD:
                ptm_first_tp = tp
                ptm_first_val = tp_data[tp]["ptm_log2fc"]
                break

        # Find first significant protein abundance change
        prot_first_tp = None
        prot_first_val = 0
        for tp in sorted_tps:
            if abs(tp_data[tp]["protein_log2fc"]) >= PROTEIN_THRESHOLD:
                prot_first_tp = tp
                prot_first_val = tp_data[tp]["protein_log2fc"]
                break

        if ptm_first_tp and prot_first_tp:
            ptm_min = tp_to_minutes(ptm_first_tp)
            prot_min = tp_to_minutes(prot_first_tp)
            lag = prot_min - ptm_min

            if lag > 0:
                if lag <= 5:
                    mechanism = "Direct post-translational effect (PTM-dependent stabilization/destabilization)"
                elif lag <= 20:
                    mechanism = "Signal-dependent protein turnover (proteasomal degradation or chaperone-mediated stabilization)"
                else:
                    mechanism = "Transcriptional reprogramming downstream of PTM-activated signaling cascade"
                direction = "Causal: PTM modification precedes protein abundance change"
                cascade_type = "immediate" if lag <= 5 else ("rapid_relay" if lag <= 20 else "transcriptional")
            elif lag < 0:
                mechanism = "Feedback: protein abundance change precedes PTM (possible autoregulatory loop)"
                direction = "Feedback"
                cascade_type = "feedback"
            else:
                mechanism = "Co-regulated: simultaneous PTM and abundance change (shared upstream signal)"
                direction = "Simultaneous"
                cascade_type = "co_regulated"

            self_timelags.append(
                {
                    "ptm_key": ptm_key,
                    "gene": tp_data[sorted_tps[0]]["gene"],
                    "site": tp_data[sorted_tps[0]]["site"],
                    "ptm_first_tp": ptm_first_tp,
                    "ptm_log2fc": ptm_first_val,
                    "protein_first_tp": prot_first_tp,
                    "protein_log2fc": prot_first_val,
                    "time_lag_minutes": lag,
                    "direction": direction,
                    "mechanism": mechanism,
                    "cascade_type": cascade_type,
                }
            )

    self_timelags.sort(key=lambda x: abs(x["time_lag_minutes"]), reverse=True)

    # -- Part B: PTM->Non-PTM interactor signal propagation --
    cascade_timelags = []

    # Build PTM protein first-change map
    ptm_first_change: Dict[str, tuple] = {}
    for ptm_key, tp_data in ptm_temporal.items():
        gene = tp_data[list(tp_data.keys())[0]]["gene"]
        for tp in sorted(tp_data.keys(), key=tp_to_minutes):
            if abs(tp_data[tp]["ptm_log2fc"]) >= PTM_THRESHOLD:
                if gene not in ptm_first_change or tp_to_minutes(tp) < tp_to_minutes(
                    ptm_first_change[gene][0]
                ):
                    ptm_first_change[gene] = (tp, tp_data[tp]["ptm_log2fc"])
                break

    # Build non-PTM protein first-change map
    nonptm_first_change: Dict[str, tuple] = {}
    nonptm_temporal_all: Dict[str, Dict[str, float]] = {}
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node in net.get("non_ptm_nodes", []):
            if not isinstance(node, dict):
                continue
            gene = node.get("gene", node.get("id", "Unknown"))
            protein_log2fc = node.get("protein_log2fc", node.get("log2fc", 0))
            if gene not in nonptm_temporal_all:
                nonptm_temporal_all[gene] = {}
            nonptm_temporal_all[gene][tp] = protein_log2fc

    for gene, tp_data in nonptm_temporal_all.items():
        for tp in sorted(tp_data.keys(), key=tp_to_minutes):
            if abs(tp_data[tp]) >= PROTEIN_THRESHOLD:
                nonptm_first_change[gene] = (tp, tp_data[tp])
                break

    # Find PTM->Non-PTM edges and compute signal propagation lag
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for edge in net.get("active_edges", []):
            if not isinstance(edge, dict):
                continue
            source = edge.get("source", "")
            target = edge.get("target", "")
            evidence = edge.get("evidence_type", "")

            # Only STRING-DB edges
            if "string" not in evidence.lower():
                continue

            if source in ptm_first_change and target in nonptm_first_change:
                ptm_tp, ptm_val = ptm_first_change[source]
                nonptm_tp, nonptm_val = nonptm_first_change[target]

                ptm_min = tp_to_minutes(ptm_tp)
                nonptm_min = tp_to_minutes(nonptm_tp)
                lag = nonptm_min - ptm_min

                edge_key = f"{source}->{target}"
                if any(c["edge_key"] == edge_key for c in cascade_timelags):
                    continue

                if lag > 0:
                    if lag <= 5:
                        mechanism = "Immediate effector recruitment (complex formation/scaffolding)"
                    elif lag <= 20:
                        mechanism = "Signal-dependent translational activation of effector protein"
                    else:
                        mechanism = "Transcriptional induction of effector gene by PTM-activated transcription factor"
                    direction = "Signal propagation: PTM substrate -> effector protein"
                elif lag < 0:
                    mechanism = "Reverse signaling: effector abundance change precedes substrate PTM"
                    direction = "Reverse signaling"
                else:
                    mechanism = "Co-activation: simultaneous substrate modification and effector response"
                    direction = "Co-activation"

                cascade_timelags.append(
                    {
                        "edge_key": edge_key,
                        "ptm_substrate": source,
                        "effector": target,
                        "ptm_first_tp": ptm_tp,
                        "ptm_log2fc": ptm_val,
                        "effector_first_tp": nonptm_tp,
                        "effector_log2fc": nonptm_val,
                        "time_lag_minutes": lag,
                        "direction": direction,
                        "mechanism": mechanism,
                    }
                )

    cascade_timelags.sort(key=lambda x: abs(x["time_lag_minutes"]), reverse=True)

    # -- Build formatted output --
    if not self_timelags and not cascade_timelags:
        return ""

    parts = ["\n## PTM -> PROTEIN ABUNDANCE TEMPORAL CAUSALITY ANALYSIS\n"]
    parts.append(
        "This analysis reveals the temporal relationship between PTM signaling events"
    )
    parts.append(
        "and downstream protein abundance changes, enabling causal inference about"
    )
    parts.append("signal transduction mechanisms.\n")

    # Part A: Self-regulation summary
    if self_timelags:
        causal = [t for t in self_timelags if "Causal" in t["direction"]]
        feedback = [t for t in self_timelags if "Feedback" in t["direction"]]
        simultaneous = [t for t in self_timelags if "Simultaneous" in t["direction"]]

        parts.append("### PTM-Protein Abundance Coupling (Same Protein)")
        parts.append(
            f"Proteins with both significant PTM and abundance changes: {len(self_timelags)}"
        )
        parts.append(f"  Causal (PTM precedes abundance change): {len(causal)}")
        parts.append(f"  Feedback (abundance change precedes PTM): {len(feedback)}")
        parts.append(f"  Simultaneous (co-regulated): {len(simultaneous)}")
        parts.append("")

        parts.append(
            "| PTM Substrate | PTM First Change | PTM Log2FC | Protein First Change | Protein Log2FC | Lag (min) | Mechanism |"
        )
        parts.append("|" + "|".join(["---"] * 7) + "|")
        for tl in self_timelags[:15]:
            parts.append(
                f"| **{tl['ptm_key']}** | {tl['ptm_first_tp']} | {tl['ptm_log2fc']:.2f} "
                f"| {tl['protein_first_tp']} | {tl['protein_log2fc']:.2f} "
                f"| {tl['time_lag_minutes']:.0f} | {tl['mechanism'][:60]} |"
            )
        parts.append("")

    # Part B: Signal propagation
    if cascade_timelags:
        forward = [t for t in cascade_timelags if "propagation" in t["direction"]]
        reverse = [t for t in cascade_timelags if "Reverse" in t["direction"]]

        parts.append("### Signal Propagation: PTM Substrate -> Downstream Effector")
        parts.append(
            f"PTM->Effector pairs with measurable signal propagation: {len(cascade_timelags)}"
        )
        parts.append(
            f"  Forward propagation (PTM precedes effector response): {len(forward)}"
        )
        parts.append(f"  Reverse signaling: {len(reverse)}")
        parts.append("")

        parts.append(
            "| PTM Substrate | Effector Protein | Substrate PTM at | Effector Response at | Lag (min) | Signal Mechanism |"
        )
        parts.append("|" + "|".join(["---"] * 6) + "|")
        for tl in cascade_timelags[:15]:
            parts.append(
                f"| **{tl['ptm_substrate']}** | {tl['effector']} "
                f"| {tl['ptm_first_tp']} (Log2FC={tl['ptm_log2fc']:.2f}) "
                f"| {tl['effector_first_tp']} (Log2FC={tl['effector_log2fc']:.2f}) "
                f"| {tl['time_lag_minutes']:.0f} | {tl['mechanism'][:50]} |"
            )
        parts.append("")

    # Summary of signal propagation kinetics
    all_lags = [
        t["time_lag_minutes"]
        for t in self_timelags + cascade_timelags
        if t.get("time_lag_minutes", 0) > 0
    ]
    if all_lags:
        parts.append("### Signal Propagation Kinetics Summary")
        immediate = len([lag for lag in all_lags if lag <= 5])
        rapid = len([lag for lag in all_lags if 5 < lag <= 20])
        delayed = len([lag for lag in all_lags if lag > 20])
        parts.append(f"  Immediate post-translational effects (<=5min lag): {immediate}")
        parts.append(f"  Rapid signal relay (5-20min lag): {rapid}")
        parts.append(f"  Delayed transcriptional response (>20min lag): {delayed}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# v81: Signal Propagation JSON builders for frontend timeline visualization
# ---------------------------------------------------------------------------

def build_signal_propagation_json(
    results: dict, timepoints: List[str], ptm_type: str
) -> Optional[Dict[str, Any]]:
    """Build structured JSON for Signal Propagation Timeline Chart (PTM-only mode).

    Returns a dict suitable for storing in Order.signal_propagation_data and
    rendering in the frontend SignalPropagationTimeline component.
    """
    networks = results.get("networks", {})
    PTM_THRESHOLD = 0.3
    PROTEIN_THRESHOLD = 0.3

    # -- Non-PTM effector temporal profiles --
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
            protein_log2fc = node.get("protein_log2fc", node.get("log2fc", 0))
            if gene not in nonptm_temporal:
                nonptm_temporal[gene] = {}
                nonptm_roles[gene] = role
            nonptm_temporal[gene][tp] = protein_log2fc

    effectors = []
    for gene, tp_data in nonptm_temporal.items():
        sorted_tps = sorted(tp_data.keys(), key=tp_to_minutes)
        values = [tp_data[tp] for tp in sorted_tps]
        max_abs = max(abs(v) for v in values) if values else 0

        early_tps = [tp for tp in sorted_tps if tp_to_minutes(tp) <= 15]
        late_tps = [tp for tp in sorted_tps if tp_to_minutes(tp) > 15]
        early_sig = any(abs(tp_data[tp]) >= 0.3 for tp in early_tps)
        late_sig = any(abs(tp_data[tp]) >= 0.3 for tp in late_tps)

        if early_sig and late_sig:
            early_vals = [tp_data[tp] for tp in early_tps if abs(tp_data[tp]) >= 0.3]
            late_vals = [tp_data[tp] for tp in late_tps if abs(tp_data[tp]) >= 0.3]
            if early_vals and late_vals and (
                (early_vals[0] > 0 and late_vals[-1] < 0)
                or (early_vals[0] < 0 and late_vals[-1] > 0)
            ):
                pattern = "biphasic_switch"
            else:
                pattern = "sustained_response"
        elif early_sig:
            pattern = "immediate_early_response"
        elif late_sig:
            pattern = "delayed_effector_response"
        else:
            pattern = "stable_baseline"

        effectors.append(
            {
                "gene": gene,
                "role": nonptm_roles.get(gene, "interactor"),
                "pattern": pattern,
                "temporal_data": {tp: round(tp_data.get(tp, 0), 3) for tp in timepoints},
                "max_change": round(max_abs, 3),
            }
        )

    effectors.sort(key=lambda x: x["max_change"], reverse=True)

    # -- PTM self-regulation time lags --
    ptm_temporal: Dict[str, Dict[str, dict]] = {}
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for node_type in ["active_nodes", "inhibited_nodes"]:
            for node in net.get(node_type, []):
                if not isinstance(node, dict):
                    continue
                gene = node.get("gene", node.get("id", "Unknown"))
                site = node.get("site", "")
                key = f"{gene}({site})" if site else gene
                ptm_log2fc = node.get("value", node.get("ptm_log2fc", node.get("log2fc", 0)))
                protein_log2fc = node.get("protein_log2fc", 0)
                if key not in ptm_temporal:
                    ptm_temporal[key] = {}
                ptm_temporal[key][tp] = {
                    "ptm_log2fc": ptm_log2fc,
                    "protein_log2fc": protein_log2fc,
                    "gene": gene,
                    "site": site,
                }

    self_timelags = []
    for ptm_key, tp_data in ptm_temporal.items():
        sorted_tps = sorted(tp_data.keys(), key=tp_to_minutes)
        ptm_first_tp = None
        for tp in sorted_tps:
            if abs(tp_data[tp]["ptm_log2fc"]) >= PTM_THRESHOLD:
                ptm_first_tp = tp
                break
        prot_first_tp = None
        for tp in sorted_tps:
            if abs(tp_data[tp]["protein_log2fc"]) >= PROTEIN_THRESHOLD:
                prot_first_tp = tp
                break
        if ptm_first_tp and prot_first_tp:
            lag = tp_to_minutes(prot_first_tp) - tp_to_minutes(ptm_first_tp)
            if lag > 0:
                cascade_type = "immediate" if lag <= 5 else ("rapid_relay" if lag <= 20 else "transcriptional")
                direction = "causal"
            elif lag < 0:
                cascade_type = "feedback"
                direction = "feedback"
            else:
                cascade_type = "co_regulated"
                direction = "simultaneous"
            self_timelags.append(
                {
                    "ptm_key": ptm_key,
                    "gene": tp_data[sorted_tps[0]]["gene"],
                    "site": tp_data[sorted_tps[0]]["site"],
                    "ptm_first_tp": ptm_first_tp,
                    "ptm_first_minutes": tp_to_minutes(ptm_first_tp),
                    "ptm_log2fc": round(tp_data[ptm_first_tp]["ptm_log2fc"], 3),
                    "protein_first_tp": prot_first_tp,
                    "protein_first_minutes": tp_to_minutes(prot_first_tp),
                    "protein_log2fc": round(tp_data[prot_first_tp]["protein_log2fc"], 3),
                    "time_lag_minutes": round(lag, 1),
                    "direction": direction,
                    "cascade_type": cascade_type,
                }
            )
    self_timelags.sort(key=lambda x: abs(x["time_lag_minutes"]), reverse=True)

    # -- PTM->Non-PTM cascade time lags --
    ptm_first_change: Dict[str, tuple] = {}
    for ptm_key, tp_data in ptm_temporal.items():
        gene = tp_data[list(tp_data.keys())[0]]["gene"]
        for tp in sorted(tp_data.keys(), key=tp_to_minutes):
            if abs(tp_data[tp]["ptm_log2fc"]) >= PTM_THRESHOLD:
                if gene not in ptm_first_change or tp_to_minutes(tp) < tp_to_minutes(
                    ptm_first_change[gene][0]
                ):
                    ptm_first_change[gene] = (tp, tp_data[tp]["ptm_log2fc"])
                break

    nonptm_first_change: Dict[str, tuple] = {}
    for gene, tp_data in nonptm_temporal.items():
        for tp in sorted(tp_data.keys(), key=tp_to_minutes):
            if abs(tp_data[tp]) >= PROTEIN_THRESHOLD:
                nonptm_first_change[gene] = (tp, tp_data[tp])
                break

    cascade_timelags = []
    seen_edges: set = set()
    for tp in timepoints:
        net = networks.get(tp, {})
        if not isinstance(net, dict):
            continue
        for edge in net.get("active_edges", []):
            if not isinstance(edge, dict):
                continue
            source = edge.get("source", "")
            target = edge.get("target", "")
            evidence = edge.get("evidence_type", "")
            if "string" not in evidence.lower():
                continue
            edge_key = f"{source}->{target}"
            if edge_key in seen_edges:
                continue
            if source in ptm_first_change and target in nonptm_first_change:
                seen_edges.add(edge_key)
                ptm_tp, ptm_val = ptm_first_change[source]
                nonptm_tp, nonptm_val = nonptm_first_change[target]
                lag = tp_to_minutes(nonptm_tp) - tp_to_minutes(ptm_tp)
                if lag > 0:
                    direction = "forward_propagation"
                elif lag < 0:
                    direction = "reverse_signaling"
                else:
                    direction = "co_activation"
                cascade_timelags.append(
                    {
                        "ptm_substrate": source,
                        "effector": target,
                        "ptm_first_tp": ptm_tp,
                        "ptm_first_minutes": tp_to_minutes(ptm_tp),
                        "ptm_log2fc": round(ptm_val, 3),
                        "effector_first_tp": nonptm_tp,
                        "effector_first_minutes": tp_to_minutes(nonptm_tp),
                        "effector_log2fc": round(nonptm_val, 3),
                        "time_lag_minutes": round(lag, 1),
                        "direction": direction,
                    }
                )
    cascade_timelags.sort(key=lambda x: abs(x["time_lag_minutes"]), reverse=True)

    if not effectors and not self_timelags and not cascade_timelags:
        return None

    # Build summary
    pattern_counts: Dict[str, int] = {}
    for e in effectors:
        pattern_counts[e["pattern"]] = pattern_counts.get(e["pattern"], 0) + 1

    all_forward_lags = [
        t["time_lag_minutes"]
        for t in self_timelags + cascade_timelags
        if t.get("time_lag_minutes", 0) > 0
    ]

    return {
        "mode": "ptm_only",
        "ptm_type": ptm_type,
        "timepoints": timepoints,
        "timepoint_minutes": [tp_to_minutes(tp) for tp in timepoints],
        "nonptm_effectors": effectors[:30],
        "self_timelags": self_timelags[:20],
        "cascade_timelags": cascade_timelags[:20],
        "summary": {
            "total_effectors": len(effectors),
            "responsive_effectors": len(
                [e for e in effectors if e["pattern"] != "stable_baseline"]
            ),
            "pattern_counts": pattern_counts,
            "total_self_timelags": len(self_timelags),
            "causal_count": len([t for t in self_timelags if t["direction"] == "causal"]),
            "feedback_count": len([t for t in self_timelags if t["direction"] == "feedback"]),
            "simultaneous_count": len(
                [t for t in self_timelags if t["direction"] == "simultaneous"]
            ),
            "total_cascade_timelags": len(cascade_timelags),
            "forward_propagation_count": len(
                [t for t in cascade_timelags if t["direction"] == "forward_propagation"]
            ),
            "immediate_count": len([lag for lag in all_forward_lags if lag <= 5]),
            "rapid_relay_count": len([lag for lag in all_forward_lags if 5 < lag <= 20]),
            "transcriptional_count": len([lag for lag in all_forward_lags if lag > 20]),
        },
    }


def build_signal_propagation_json_from_crosstalk(
    crosstalk_data: dict,
) -> Optional[Dict[str, Any]]:
    """Build structured JSON for Signal Propagation Timeline Chart (Crosstalk mode).

    Extracts data from the existing crosstalk_data dict which already contains:
      - shared_nonptm_details: temporal protein abundance of shared non-PTM interactors
      - ptm_protein_timelags: PTM->Protein time lag analysis results

    Returns dict with same structure as build_signal_propagation_json but mode='crosstalk'.
    """
    if not crosstalk_data:
        return None

    p_type = crosstalk_data.get("primary_ptm_type", "phosphorylation")
    s_type = crosstalk_data.get("secondary_ptm_type", "ubiquitylation")

    # Extract non-PTM effector data from shared_nonptm_details
    effectors = []
    shared_details = crosstalk_data.get("shared_nonptm_details", [])
    timepoints_set: set = set()

    for detail in shared_details:
        if not isinstance(detail, dict):
            continue
        gene = detail.get("gene", "")
        temporal = detail.get("temporal_abundance", detail.get("protein_temporal", {}))
        if not gene:
            continue
        if isinstance(temporal, dict):
            for tp in temporal.keys():
                timepoints_set.add(tp)
            values = list(temporal.values())
            max_abs = max(abs(v) for v in values) if values else 0

            sorted_tps = sorted(temporal.keys(), key=tp_to_minutes)
            early_tps = [tp for tp in sorted_tps if tp_to_minutes(tp) <= 15]
            late_tps = [tp for tp in sorted_tps if tp_to_minutes(tp) > 15]
            early_sig = any(abs(temporal.get(tp, 0)) >= 0.3 for tp in early_tps)
            late_sig = any(abs(temporal.get(tp, 0)) >= 0.3 for tp in late_tps)

            if early_sig and late_sig:
                early_vals = [temporal[tp] for tp in early_tps if abs(temporal.get(tp, 0)) >= 0.3]
                late_vals = [temporal[tp] for tp in late_tps if abs(temporal.get(tp, 0)) >= 0.3]
                if (
                    early_vals
                    and late_vals
                    and (
                        (early_vals[0] > 0 and late_vals[-1] < 0)
                        or (early_vals[0] < 0 and late_vals[-1] > 0)
                    )
                ):
                    pattern = "biphasic_switch"
                else:
                    pattern = "sustained_response"
            elif early_sig:
                pattern = "immediate_early_response"
            elif late_sig:
                pattern = "delayed_effector_response"
            else:
                pattern = "stable_baseline"

            effectors.append(
                {
                    "gene": gene,
                    "role": detail.get("role", "shared_interactor"),
                    "pattern": pattern,
                    "temporal_data": {tp: round(v, 3) for tp, v in temporal.items()},
                    "max_change": round(max_abs, 3),
                }
            )

    effectors.sort(key=lambda x: x["max_change"], reverse=True)

    # Extract time lag data from ptm_protein_timelags
    timelags_data = crosstalk_data.get("ptm_protein_timelags", [])
    self_timelags = []
    cascade_timelags = []

    for tl in timelags_data:
        if not isinstance(tl, dict):
            continue
        lag = tl.get("time_lag_minutes", tl.get("lag_minutes", 0))
        gene = tl.get("gene", tl.get("protein", ""))
        ptm_tp = tl.get("ptm_first_tp", tl.get("ptm_timepoint", ""))
        prot_tp = tl.get("protein_first_tp", tl.get("protein_timepoint", ""))

        if lag > 0:
            direction = "causal"
            cascade_type = "immediate" if lag <= 5 else ("rapid_relay" if lag <= 20 else "transcriptional")
        elif lag < 0:
            direction = "feedback"
            cascade_type = "feedback"
        else:
            direction = "simultaneous"
            cascade_type = "co_regulated"

        entry = {
            "ptm_key": tl.get("ptm_key", gene),
            "gene": gene,
            "site": tl.get("site", ""),
            "ptm_first_tp": ptm_tp,
            "ptm_first_minutes": tp_to_minutes(ptm_tp) if ptm_tp else 0,
            "ptm_log2fc": round(tl.get("ptm_log2fc", 0), 3),
            "protein_first_tp": prot_tp,
            "protein_first_minutes": tp_to_minutes(prot_tp) if prot_tp else 0,
            "protein_log2fc": round(tl.get("protein_log2fc", 0), 3),
            "time_lag_minutes": round(lag, 1),
            "direction": direction,
            "cascade_type": cascade_type,
        }

        if tl.get("type") == "cascade" or tl.get("effector"):
            cascade_timelags.append(
                {
                    "ptm_substrate": tl.get("ptm_substrate", gene),
                    "effector": tl.get("effector", ""),
                    "ptm_first_tp": ptm_tp,
                    "ptm_first_minutes": tp_to_minutes(ptm_tp) if ptm_tp else 0,
                    "ptm_log2fc": round(tl.get("ptm_log2fc", 0), 3),
                    "effector_first_tp": prot_tp,
                    "effector_first_minutes": tp_to_minutes(prot_tp) if prot_tp else 0,
                    "effector_log2fc": round(
                        tl.get("protein_log2fc", tl.get("effector_log2fc", 0)), 3
                    ),
                    "time_lag_minutes": round(lag, 1),
                    "direction": (
                        "forward_propagation"
                        if lag > 0
                        else ("reverse_signaling" if lag < 0 else "co_activation")
                    ),
                }
            )
        else:
            self_timelags.append(entry)

    sorted_tps = sorted(timepoints_set, key=tp_to_minutes)

    if not effectors and not self_timelags and not cascade_timelags:
        return None

    # Build summary
    pattern_counts: Dict[str, int] = {}
    for e in effectors:
        pattern_counts[e["pattern"]] = pattern_counts.get(e["pattern"], 0) + 1

    all_forward_lags = [
        t["time_lag_minutes"]
        for t in self_timelags + cascade_timelags
        if t.get("time_lag_minutes", 0) > 0
    ]

    return {
        "mode": "crosstalk",
        "primary_ptm_type": p_type,
        "secondary_ptm_type": s_type,
        "timepoints": sorted_tps,
        "timepoint_minutes": [tp_to_minutes(tp) for tp in sorted_tps],
        "nonptm_effectors": effectors[:30],
        "self_timelags": self_timelags[:20],
        "cascade_timelags": cascade_timelags[:20],
        "summary": {
            "total_effectors": len(effectors),
            "responsive_effectors": len(
                [e for e in effectors if e["pattern"] != "stable_baseline"]
            ),
            "pattern_counts": pattern_counts,
            "total_self_timelags": len(self_timelags),
            "causal_count": len([t for t in self_timelags if t["direction"] == "causal"]),
            "feedback_count": len([t for t in self_timelags if t["direction"] == "feedback"]),
            "simultaneous_count": len(
                [t for t in self_timelags if t["direction"] == "simultaneous"]
            ),
            "total_cascade_timelags": len(cascade_timelags),
            "forward_propagation_count": len(
                [
                    t
                    for t in cascade_timelags
                    if t.get("direction") == "forward_propagation"
                ]
            ),
            "immediate_count": len([lag for lag in all_forward_lags if lag <= 5]),
            "rapid_relay_count": len([lag for lag in all_forward_lags if 5 < lag <= 20]),
            "transcriptional_count": len([lag for lag in all_forward_lags if lag > 20]),
        },
    }
