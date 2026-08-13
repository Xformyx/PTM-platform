"""
Hypothesis Node — generates structured hypotheses from multi-source PTM data.

v2.0 (Co-Scientist Mode): Integrates 4 data sources for richer hypothesis generation:
  1. Temporal Cascade — time-ordered kinase activation sequence
  2. Co-Wave Modules — substrates co-activated at the same timepoint
  3. Kinase Autophosphorylation — self-phosphorylation as activation marker
  4. TMM Contribution — data-driven kinase-substrate attribution

v1.0 (Standard Mode): Top PTMs + pathway enrichment → IF-THEN-BECAUSE hypotheses.
"""

import collections
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)

_LLM_WORKERS = int(os.getenv("REPORT_LLM_WORKERS", "4"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_hypothesis_generation(state: dict) -> dict:
    """Generate hypotheses from research results (parallel LLM calls)."""
    cb = state.get("progress_callback")
    if cb:
        cb(30, "Generating hypotheses")

    report_type = state.get("report_type", "comprehensive")
    research_results = state.get("research_results", [])
    context = state.get("experimental_context", {})
    ptm_type = state.get("ptm_type", "phosphorylation")

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    # Co-Scientist mode: extract rich multi-source context
    if report_type == "co_scientist":
        multi_ctx = _build_multi_source_context(state)
        hypotheses = _generate_co_scientist_hypotheses(multi_ctx, context, llm, ptm_type)
        if cb:
            cb(40, f"[Co-Scientist] Generated {len(hypotheses)} data-grounded hypotheses")
        return {"hypotheses": hypotheses, "co_scientist_context": multi_ctx}

    # Standard mode: per-question parallel generation
    n = len(research_results)
    if n == 0:
        return {"hypotheses": []}

    def _do(idx_result):
        idx, result = idx_result
        return idx, _generate_hypotheses(result, context, llm, ptm_type=ptm_type)

    ordered: dict = {}
    workers = min(_LLM_WORKERS, n)
    logger.info(f"[hypothesis] Generating hypotheses for {n} questions with {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_do, (i, r)): i for i, r in enumerate(research_results)}
        for fut in as_completed(futs):
            idx, hyps = fut.result()
            ordered[idx] = hyps
            if cb:
                done = len(ordered)
                pct = 30 + (done / n) * 10
                cb(pct, f"Hypothesis for Q{idx+1} done ({done}/{n})")

    hypotheses = []
    for i in range(n):
        hypotheses.extend(ordered.get(i, []))

    if cb:
        cb(40, f"Generated {len(hypotheses)} hypotheses")

    return {"hypotheses": hypotheses}


# ---------------------------------------------------------------------------
# Co-Scientist: Multi-source context builder
# ---------------------------------------------------------------------------

def _build_multi_source_context(state: dict) -> dict:
    """Extract and structure all 4 data sources for co-scientist hypothesis generation."""
    ctx = {}

    # ── Source 1: Temporal Cascade ──────────────────────────────────────────
    kad = state.get("frontend_kinase_analysis") or state.get("global_kinase_modules") or {}
    kah = state.get("kinase_activity_heatmap") or {}
    temporal_cascade = kad.get("temporal_cascade", {})
    cascade_flow = temporal_cascade.get("cascade_flow", [])
    ctx["temporal_cascade"] = cascade_flow  # [{timepoint, active_kinases, new_kinases, lost_kinases}]
    ctx["tmm_weighted_temporal_cascade"] = temporal_cascade.get("tmm_weighted") or kah.get("tmm_weighted_temporal_cascade") or {}

    # ── Source 2: Co-Wave Modules ────────────────────────────────────────────
    cowave_groups = kah.get("cowave_groups", [])
    kinase_scores = kah.get("kinase_scores", [])
    conditions = kah.get("conditions", [])
    ctx["cowave_groups"] = cowave_groups
    ctx["conditions"] = conditions

    # Build cowave → substrates mapping
    cowave_substrates: dict[str, list] = collections.defaultdict(list)
    cowave_kinases: dict[str, list] = collections.defaultdict(list)
    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        cw_id = str(ks.get("cowave_group", -1))
        k_name = ks.get("kinase", "")
        for sub in ks.get("substrates", []):
            gene = sub.get("gene", "")
            pos = sub.get("position", "")
            if gene:
                cowave_substrates[cw_id].append({"gene": gene, "position": pos, "kinase": k_name})
        if k_name and cw_id != "-1":
            cowave_kinases[cw_id].append({
                "kinase": k_name,
                "peak_condition": ks.get("peak_condition", ""),
                "peak_score": ks.get("peak_score", 0),
                "direction": ks.get("direction", "up"),
                "coherence": ks.get("coherence", 0),
                "tmm_n_exclusive": ks.get("tmm_n_exclusive", 0),
                "tmm_n_shared": ks.get("tmm_n_shared", 0),
            })
    ctx["cowave_substrates"] = dict(cowave_substrates)
    ctx["cowave_kinases"] = dict(cowave_kinases)

    # ── Source 3: Autophosphorylation ────────────────────────────────────────
    # self_ptm is a list[dict] (sorted by |correlation_with_activity| desc)
    # from kinase-activity-heatmap; tolerate legacy single-dict shape.
    auto_phospho = []
    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        self_ptm = ks.get("self_ptm")
        if not self_ptm:
            continue
        sites = self_ptm if isinstance(self_ptm, list) else [self_ptm]
        for sp in sites:
            if not isinstance(sp, dict):
                continue
            corr = sp.get("correlation_with_activity", sp.get("correlation", 0)) or 0
            auto_phospho.append({
                "kinase": ks.get("kinase", ""),
                "self_ptm_site": sp.get("site", ""),
                "self_ptm_corr": corr,
                "self_ptm_type": "activation" if corr > 0 else "inhibition",
                "peak_condition": sp.get("peak_condition") or ks.get("peak_condition", ""),
            })
    ctx["autophosphorylation"] = auto_phospho

    # ── Source 4: TMM Contribution ───────────────────────────────────────────
    tmm_summary = []
    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        n_excl = ks.get("tmm_n_exclusive", 0)
        n_shared = ks.get("tmm_n_shared", 0)
        if n_excl + n_shared > 0:
            tmm_summary.append({
                "kinase": ks.get("kinase", ""),
                "n_exclusive": n_excl,
                "n_shared": n_shared,
                "exclusivity_ratio": round(n_excl / (n_excl + n_shared), 2) if (n_excl + n_shared) > 0 else 0,
                "top_contributions": ks.get("tmm_top_contributions", [])[:5],
                "profile_type": ks.get("tmm_profile_type", ""),
            })
    ctx["tmm_summary"] = tmm_summary

    # ── Top kinases by peak score ─────────────────────────────────────────────
    top_kinases = sorted(
        [ks for ks in kinase_scores if not ks.get("is_sub_pattern")],
        key=lambda x: abs(x.get("peak_score", 0)),
        reverse=True
    )[:10]
    ctx["top_kinases"] = top_kinases

    # ── Vector plot top PTMs ──────────────────────────────────────────────────
    vp = state.get("vector_plot_raw_data", [])
    sorted_vp = sorted(vp, key=lambda r: abs(float(r.get("ptm_relative_log2fc", 0) or 0)), reverse=True)
    ctx["top_ptms"] = sorted_vp[:30]

    # ── Source 6: Observational directionality evidence ─────────────────────
    # Directionality remains independent from the kinase cascade heuristics and
    # is never promoted to causality without a later perturbation upload.
    signal_propagation = state.get("signal_propagation_data") or {}
    directed_records = []
    if isinstance(signal_propagation, dict):
        for record in (signal_propagation.get("self_timelags") or []) + (signal_propagation.get("cascade_timelags") or []):
            relation = record.get("directionality") or {}
            if not relation:
                continue
            directed_records.append({
                "source": record.get("ptm_key") or record.get("ptm_substrate") or relation.get("source", {}).get("key", ""),
                "target": record.get("effector") or f"{record.get('gene', '')} protein abundance",
                "direction": relation.get("direction", record.get("direction", "unresolved")),
                "tier": relation.get("directionality_tier", record.get("directionality_tier", "D0_unresolved")),
                "onset_lag_minutes": relation.get("onset_lag_minutes"),
                "peak_lag_minutes": relation.get("peak_lag_minutes"),
                "causality_status": relation.get("causality_status", record.get("causality_status", "not_tested")),
            })
    ctx["directionality_records"] = directed_records

    # Observational precedence between contribution-weighted kinase profiles is
    # separate from PTM→effector directionality and always has causality=not_tested.
    ctx["tmm_kinase_pair_directionality"] = (
        temporal_cascade.get("tmm_kinase_pair_directionality")
        or kah.get("tmm_kinase_pair_directionality")
        or []
    )

    logger.info(
        f"[Co-Scientist] Built multi-source context: "
        f"cascade={len(cascade_flow)} steps, cowave={len(cowave_groups)} groups, "
        f"autophospho={len(auto_phospho)}, tmm={len(tmm_summary)}, "
        f"directionality={len(directed_records)}, top_ptms={len(ctx['top_ptms'])}"
    )
    return ctx


# ---------------------------------------------------------------------------
# Co-Scientist: Hypothesis generation from multi-source context
# ---------------------------------------------------------------------------

def _generate_co_scientist_hypotheses(
    multi_ctx: dict,
    exp_context: dict,
    llm: LLMClient,
    ptm_type: str = "phosphorylation",
) -> list:
    """Generate data-grounded hypotheses using all 4 sources."""

    # Build structured prompt sections
    sections = []

    # Section A: Temporal Cascade
    cascade = multi_ctx.get("temporal_cascade", [])
    if cascade:
        lines = ["=== TEMPORAL KINASE CASCADE (time-ordered activation) ==="]
        for step in cascade:
            tp = step.get("timepoint", "")
            active = ", ".join(step.get("active_kinases", [])[:8])
            new = ", ".join(step.get("new_kinases", [])[:5])
            lost = ", ".join(step.get("lost_kinases", [])[:5])
            lines.append(f"  {tp}: active=[{active}]" + (f", NEW=[{new}]" if new else "") + (f", LOST=[{lost}]" if lost else ""))
        sections.append("\n".join(lines))

    # Section B: Co-Wave Modules
    cw_kinases = multi_ctx.get("cowave_kinases", {})
    cw_subs = multi_ctx.get("cowave_substrates", {})
    if cw_kinases:
        lines = ["=== CO-WAVE MODULES (substrates co-activated at same timepoint) ==="]
        for cw_id, kinases in list(cw_kinases.items())[:6]:
            if cw_id == "-1":
                continue
            k_names = ", ".join(k["kinase"] for k in kinases[:4])
            peak_c = kinases[0].get("peak_condition", "") if kinases else ""
            subs = cw_subs.get(cw_id, [])
            sub_genes = list({s["gene"] for s in subs})[:8]
            lines.append(f"  Wave G{cw_id} (peak:{peak_c}): kinases=[{k_names}], substrates=[{', '.join(sub_genes)}]")
            lines.append(f"    → These {len(subs)} substrates move TOGETHER → likely share upstream regulator")
        sections.append("\n".join(lines))

    # Section C: Autophosphorylation
    auto = multi_ctx.get("autophosphorylation", [])
    if auto:
        lines = ["=== KINASE AUTOPHOSPHORYLATION (self-activation markers) ==="]
        for a in auto:
            atype = a["self_ptm_type"]
            lines.append(
                f"  {a['kinase']} → self-phospho at {a['self_ptm_site']} "
                f"(r={a['self_ptm_corr']:+.2f}, {atype}) @ peak={a['peak_condition']}"
            )
        sections.append("\n".join(lines))

    # Section D: TMM Contribution
    tmm = multi_ctx.get("tmm_summary", [])
    if tmm:
        lines = ["=== TMM KINASE CONTRIBUTION (data-driven substrate attribution) ==="]
        for t in sorted(tmm, key=lambda x: x["n_exclusive"], reverse=True)[:8]:
            lines.append(
                f"  {t['kinase']}: exclusive={t['n_exclusive']}, shared={t['n_shared']}, "
                f"exclusivity={t['exclusivity_ratio']:.0%}, profile={t['profile_type']}"
            )
        sections.append("\n".join(lines))

    # Section D1: contribution-weighted cascade
    tmm_cascade = multi_ctx.get("tmm_weighted_temporal_cascade") or {}
    if tmm_cascade.get("timepoints"):
        lines = [
            "=== TMM-WEIGHTED KINASE CASCADE (condition-specific; non-causal) ===",
            "Raw co-wave membership and TMM-weighted activity are separate evidence layers.",
        ]
        for step in tmm_cascade.get("timepoints", [])[:10]:
            active = step.get("active_kinases", [])
            names = ", ".join(
                f"{item.get('kinase')}({item.get('tmm_weighted_activity', 0):+.2f};"
                f"{(item.get('tmm_evidence') or {}).get('confidence_tier', 'unknown')})"
                for item in active[:6]
            )
            lines.append(f"  {step.get('timepoint')}: [{names}]")
        sections.append("\n".join(lines))

    # Section E: Top PTMs
    top_ptms = multi_ctx.get("top_ptms", [])
    if top_ptms:
        lines = ["=== TOP 30 PTMs BY |LOG2FC| ==="]
        for r in top_ptms[:30]:
            lines.append(
                f"  {r.get('gene','')} {r.get('position','')} @ {r.get('condition','')}: "
                f"PTM_FC={float(r.get('ptm_relative_log2fc',0) or 0):+.2f}"
            )
        sections.append("\n".join(lines))

    # Section F: Directionality evidence (observational only)
    directionality_records = multi_ctx.get("directionality_records", [])
    if directionality_records:
        lines = [
            "=== OBSERVATIONAL TEMPORAL DIRECTIONALITY ===",
            "D0=unresolved; D1=temporal precedence; D2=reproducible directionality; D3=temporal + biological support.",
            "These records have NOT been intervention-tested. They are not causal conclusions.",
        ]
        for record in directionality_records[:15]:
            lines.append(
                f"  {record['source']} → {record['target']}: direction={record['direction']}, "
                f"tier={record['tier']}, onset_lag={record['onset_lag_minutes']} min, "
                f"peak_lag={record['peak_lag_minutes']} min, causality={record['causality_status']}"
            )
        sections.append("\n".join(lines))

    kinase_pair_directionality = multi_ctx.get("tmm_kinase_pair_directionality", [])
    if kinase_pair_directionality:
        lines = [
            "=== TMM-WEIGHTED KINASE-PROFILE TEMPORAL PRECEDENCE ===",
            "These are observational profile relationships only; do not infer direct kinase-to-kinase causality.",
        ]
        for relation in kinase_pair_directionality[:12]:
            lines.append(
                f"  {relation.get('source')} → {relation.get('target')}: "
                f"tier={relation.get('directionality_tier')}, "
                f"onset_lag={relation.get('onset_lag_minutes')} min, "
                f"peak_lag={relation.get('peak_lag_minutes')} min"
            )
        sections.append("\n".join(lines))

    # Experimental context
    tissue = exp_context.get("tissue") or exp_context.get("cell_type") or "cells"
    treatment = exp_context.get("treatment") or "the applied treatment"
    bio_q = (exp_context.get("biological_question") or "").strip()

    data_block = "\n\n".join(sections)

    prompt = f"""You are an expert molecular biologist performing Data-Grounded Analysis on PTM proteomics data.

Experimental context:
- Cell/Tissue: {tissue}
- Treatment: {treatment}
- PTM type: {ptm_type}
{f'- Research focus: {bio_q}' if bio_q else ''}

Below is comprehensive multi-source data from the experiment:

{data_block}

Based on ALL data sources above, generate 6-8 high-quality, data-grounded hypotheses.

CRITICAL INSTRUCTIONS:
1. TEMPORAL HYPOTHESES: For each major kinase, describe WHEN it activates and what substrates it targets at each timepoint. Explain the biological meaning of the timing.
2. CO-WAVE HYPOTHESES: For each co-wave group, identify what the co-activated substrates have in common (cellular compartment, function, pathway). Propose the upstream regulator.
3. AUTOPHOSPHORYLATION HYPOTHESES: For kinases with self-phosphorylation, describe an activation or inhibition marker candidate. Do NOT call it a positive/negative feedback mechanism without intervention evidence.
4. TMM CONTRIBUTION HYPOTHESES: For kinases with high exclusivity ratio, propose what makes their substrate specificity unique. For kinases with many shared substrates, propose cooperative signaling.
5. SUBSTRATE-LEVEL SPECIFICITY: Name specific substrates (gene_position) and explain their biological roles.
6. DATA-GROUNDED: Every hypothesis must cite specific numbers from the data (e.g., "21/28 substrates peak at 1h").
7. DIRECTIONALITY BOUNDARY: D0–D3 directionality is observational. Use "temporally precedes", "is consistent with", or "candidate regulatory path". Never write "causes", "drives", "directly activates", "feedback loop", or "proves" unless separately supplied perturbation evidence explicitly supports it.

Format each hypothesis as:
HYPOTHESIS:
TYPE: [temporal|cowave|autophospho|tmm_contribution|integrated]
IF: [observed data pattern with specific numbers]
THEN: [predicted biological outcome]
BECAUSE: [proposed mechanism with substrate-level detail]
KEY_SUBSTRATES: [gene_position, gene_position, ...]
COWAVE_GROUP: [G0/G1/G2/... or N/A]
TESTABLE_PREDICTION: [specific experiment to validate]
CONFIDENCE: [0.0-1.0]
EVIDENCE_BOUNDARY: [observational directionality only | perturbation-supported only if supplied]
"""

    if llm.is_available():
        response = llm.generate(
            prompt,
            system_prompt=(
                "You are a molecular biology expert specializing in post-translational modifications "
                "and cell signaling. Generate precise, data-grounded hypotheses with substrate-level detail."
            ),
            temperature=0.4,
            max_tokens=4096,
        )
        hypotheses = _parse_co_scientist_hypotheses(response)
    else:
        hypotheses = _generate_rule_based_co_scientist(multi_ctx, exp_context, ptm_type)

    logger.info(f"[Co-Scientist] Generated {len(hypotheses)} hypotheses")
    return hypotheses


def _parse_co_scientist_hypotheses(response: str) -> list:
    """Parse co-scientist LLM response into structured hypotheses."""
    hypotheses = []
    blocks = response.split("HYPOTHESIS:")

    for block in blocks[1:]:
        lines = block.strip().split("\n")
        hyp = {
            "id": str(uuid.uuid4())[:8],
            "type": "integrated",
            "condition": "",
            "prediction": "",
            "mechanism": "",
            "key_substrates": [],
            "cowave_group": "N/A",
            "testable_prediction": "",
            "confidence": 0.5,
            "status": "generated",
            "source": "co_scientist",
        }

        for line in lines:
            line = line.strip()
            if line.startswith("TYPE:"):
                hyp["type"] = line[5:].strip().lower()
            elif line.startswith("IF:"):
                hyp["condition"] = line[3:].strip()
            elif line.startswith("THEN:"):
                hyp["prediction"] = line[5:].strip()
            elif line.startswith("BECAUSE:"):
                hyp["mechanism"] = line[8:].strip()
            elif line.startswith("KEY_SUBSTRATES:"):
                hyp["key_substrates"] = [s.strip() for s in line[15:].split(",") if s.strip()]
            elif line.startswith("COWAVE_GROUP:"):
                hyp["cowave_group"] = line[13:].strip()
            elif line.startswith("TESTABLE_PREDICTION:"):
                hyp["testable_prediction"] = line[20:].strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    hyp["confidence"] = float(line[11:].strip())
                except ValueError:
                    pass

        if hyp["condition"] and hyp["prediction"]:
            hypotheses.append(hyp)

    return hypotheses


def _generate_rule_based_co_scientist(multi_ctx: dict, context: dict, ptm_type: str) -> list:
    """Fallback: generate rule-based co-scientist hypotheses without LLM."""
    hypotheses = []
    top_kinases = multi_ctx.get("top_kinases", [])
    cascade = multi_ctx.get("temporal_cascade", [])
    auto = multi_ctx.get("autophosphorylation", [])
    cw_kinases = multi_ctx.get("cowave_kinases", {})

    # Temporal hypothesis from cascade
    if len(cascade) >= 2:
        early = cascade[0]
        late = cascade[-1]
        early_ks = early.get("active_kinases", ["unknown"])[:2]
        late_ks = late.get("active_kinases", ["unknown"])[:2]
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "type": "temporal",
            "condition": (
                f"{', '.join(early_ks)} are activated at {early.get('timepoint','early')} "
                f"while {', '.join(late_ks)} dominate at {late.get('timepoint','late')}"
            ),
            "prediction": "A temporal kinase handoff separates acute from sustained signaling phases",
            "mechanism": (
                f"Early kinases ({', '.join(early_ks)}) initiate rapid response, "
                f"while late kinases ({', '.join(late_ks)}) maintain prolonged signaling"
            ),
            "key_substrates": [],
            "cowave_group": "N/A",
            "testable_prediction": f"Inhibiting {early_ks[0] if early_ks else 'early kinase'} should block acute but not sustained response",
            "confidence": 0.65,
            "status": "generated",
            "source": "co_scientist_rule_based",
        })

    # Autophosphorylation hypothesis
    for a in auto[:2]:
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "type": "autophospho",
            "condition": (
                f"{a['kinase']} shows self-phosphorylation at {a['self_ptm_site']} "
                f"(r={a['self_ptm_corr']:+.2f}) at {a['peak_condition']}"
            ),
            "prediction": f"{a['kinase']} undergoes {a['self_ptm_type']} loop at {a['peak_condition']}",
            "mechanism": (
                f"Self-phosphorylation at {a['self_ptm_site']} represents "
                f"{'positive feedback amplification' if a['self_ptm_type'] == 'activation' else 'negative feedback auto-inhibition'}"
            ),
            "key_substrates": [f"{a['kinase']}_{a['self_ptm_site']}"],
            "cowave_group": "N/A",
            "testable_prediction": f"Mutation of {a['self_ptm_site']} should {'reduce' if a['self_ptm_type'] == 'activation' else 'prolong'} {a['kinase']} activity",
            "confidence": 0.70,
            "status": "generated",
            "source": "co_scientist_rule_based",
        })

    # Co-wave hypothesis
    for cw_id, kinases in list(cw_kinases.items())[:2]:
        if cw_id == "-1" or not kinases:
            continue
        k_names = [k["kinase"] for k in kinases[:3]]
        peak_c = kinases[0].get("peak_condition", "")
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "type": "cowave",
            "condition": (
                f"Co-wave G{cw_id}: {', '.join(k_names)} co-activate substrates at {peak_c}"
            ),
            "prediction": f"Substrates in co-wave G{cw_id} share a common upstream regulator or functional module",
            "mechanism": (
                f"Simultaneous activation by {', '.join(k_names)} at {peak_c} suggests "
                f"coordinated regulation of a functional substrate cluster"
            ),
            "key_substrates": [],
            "cowave_group": f"G{cw_id}",
            "testable_prediction": f"Inhibiting the dominant kinase in G{cw_id} should block all co-wave substrates simultaneously",
            "confidence": 0.60,
            "status": "generated",
            "source": "co_scientist_rule_based",
        })

    return hypotheses


# ---------------------------------------------------------------------------
# Standard mode helpers (unchanged from v1.0)
# ---------------------------------------------------------------------------

def _generate_hypotheses(research: dict, context: dict, llm: LLMClient, ptm_type: str = "phosphorylation") -> list:
    """Generate hypotheses for a single research result."""
    if llm.is_available():
        return _generate_with_llm(research, context, llm)
    return _generate_rule_based(research, context, ptm_type=ptm_type)


def _generate_with_llm(research: dict, context: dict, llm: LLMClient) -> list:
    """Use LLM to generate structured hypotheses."""
    activated = research.get("activated", [])
    inhibited = research.get("inhibited", [])
    pathways = research.get("enriched_pathways", [])

    activated_str = ", ".join(f"{p['gene']}-{p['position']} (Log2FC={p['ptm_relative_log2fc']})" for p in activated[:5])
    inhibited_str = ", ".join(f"{p['gene']}-{p['position']} (Log2FC={p['ptm_relative_log2fc']})" for p in inhibited[:5])
    pathway_str = ", ".join(
        p.get("pathway", p.get("name", str(p))) if isinstance(p, dict) else str(p) for p in pathways[:5]
    )

    tissue = context.get("tissue") or context.get("cell_type") or "the given experimental system"
    treatment = context.get("treatment", "the applied treatment")
    biological_question = (context.get("biological_question") or "").strip()
    bio_focus = f"\nResearch focus (Biological Question): {biological_question}\n" if biological_question else ""

    prompt = f"""Based on the following PTM analysis results, generate 1-2 testable hypotheses.

Research Question: {research['question']}{bio_focus}

Key Upregulated PTMs: {activated_str or 'None'}
Key Downregulated PTMs: {inhibited_str or 'None'}
Enriched Pathways: {pathway_str or 'None'}
Experimental Context: {tissue}, {treatment}

For each hypothesis, provide:
1. IF: The observed condition
2. THEN: The predicted biological outcome
3. BECAUSE: The proposed mechanism
4. Supporting PTMs: List the relevant PTM sites
5. Testable Prediction: A specific experiment to test this

Format each hypothesis as:
HYPOTHESIS:
IF: ...
THEN: ...
BECAUSE: ...
SUPPORTING: ...
PREDICTION: ...
CONFIDENCE: (0.0-1.0)
"""

    response = llm.generate(
        prompt,
        system_prompt="You are a molecular biology expert specializing in post-translational modifications.",
        temperature=0.5,
    )

    return _parse_llm_hypotheses(response, research)


def _parse_llm_hypotheses(response: str, research: dict) -> list:
    """Parse LLM response into structured hypotheses."""
    hypotheses = []
    blocks = response.split("HYPOTHESIS:")

    for block in blocks[1:]:
        lines = block.strip().split("\n")
        hyp = {
            "id": str(uuid.uuid4())[:8],
            "question": research["question"],
            "condition": "",
            "prediction": "",
            "mechanism": "",
            "supporting_ptms": [],
            "testable_prediction": "",
            "confidence": 0.5,
            "status": "generated",
        }

        for line in lines:
            line = line.strip()
            if line.startswith("IF:"):
                hyp["condition"] = line[3:].strip()
            elif line.startswith("THEN:"):
                hyp["prediction"] = line[5:].strip()
            elif line.startswith("BECAUSE:"):
                hyp["mechanism"] = line[8:].strip()
            elif line.startswith("SUPPORTING:"):
                hyp["supporting_ptms"] = [s.strip() for s in line[11:].split(",") if s.strip()]
            elif line.startswith("PREDICTION:"):
                hyp["testable_prediction"] = line[11:].strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    hyp["confidence"] = float(line[11:].strip())
                except ValueError:
                    pass

        if hyp["condition"] and hyp["prediction"]:
            hypotheses.append(hyp)

    if not hypotheses:
        return _generate_rule_based(research, {})

    return hypotheses


def _generate_rule_based(research: dict, context: dict, ptm_type: str = "phosphorylation") -> list:
    """Fallback: generate hypotheses from rules."""
    hypotheses = []
    activated = research.get("activated", [])
    inhibited = research.get("inhibited", [])
    pathways = research.get("enriched_pathways", [])
    ptm_label = ptm_type.capitalize() if ptm_type else "Phosphorylation"

    if activated and pathways:
        top = activated[0]
        pw = pathways[0]["pathway"]
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "question": research["question"],
            "condition": f"{ptm_label} of {top['gene']} at {top['position']} is upregulated (Log2FC={top['ptm_relative_log2fc']})",
            "prediction": f"The {pw} pathway is activated",
            "mechanism": f"{top['gene']} {top['position']} {ptm_label.lower()} activates downstream signaling through {pw}",
            "supporting_ptms": [f"{top['gene']}-{top['position']}"],
            "testable_prediction": f"Inhibition of {top['gene']} {ptm_label.lower()} should reduce {pw} pathway activity",
            "confidence": min(0.7, research.get("confidence", 0.5)),
            "status": "generated",
        })

    if activated and inhibited:
        up = activated[0]
        down = inhibited[0]
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "question": research["question"],
            "condition": f"{up['gene']} is upregulated while {down['gene']} is downregulated",
            "prediction": f"A signaling switch from {down['gene']} to {up['gene']} axis is occurring",
            "mechanism": f"Reciprocal regulation of {up['gene']} and {down['gene']} indicates a coordinated signaling transition",
            "supporting_ptms": [f"{up['gene']}-{up['position']}", f"{down['gene']}-{down['position']}"],
            "testable_prediction": f"Restoring {down['gene']} activity should attenuate {up['gene']} {ptm_label.lower()}",
            "confidence": 0.5,
            "status": "generated",
        })

    return hypotheses
