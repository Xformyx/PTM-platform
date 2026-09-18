"""
Drug Repositioning Node — runs the drug repositioning pipeline
when report_type is 'extended'.

Integrates DrugRepositioningPipeline into the LangGraph report flow.
"""

import logging

logger = logging.getLogger(__name__)


def run_drug_repositioning(state: dict) -> dict:
    """Run drug repositioning analysis if report_type is 'extended'."""
    cb = state.get("progress_callback")
    report_type = state.get("report_type", "comprehensive")

    if report_type != "extended":
        logger.info("Report type is not 'extended', skipping drug repositioning")
        if cb:
            cb(92, "Drug repositioning: skipped (standard report)")
        return {"drug_repositioning_results": {"evaluation_status": "not_requested"}}

    if cb:
        cb(91, "Running drug repositioning pipeline")

    parsed_ptms = state.get("parsed_ptms", [])
    network_analysis = state.get("network_analysis", {})
    comprehensive_summary = state.get("comprehensive_summary", "")
    output_dir = state.get("output_dir", "/tmp")
    llm_model = state.get("llm_model", "gemma3:27b")

    analysis_results = _build_analysis_results(parsed_ptms, network_analysis, state)

    try:
        from report_generation.core.drug_repositioning import DrugRepositioningPipeline

        pipeline = DrugRepositioningPipeline(
            model=llm_model or "gemma3:27b",
            top_targets=10,
        )

        if cb:
            cb(92, "Drug repositioning: scoring PTM targets")

        dr_results = pipeline.run(
            analysis_results=analysis_results,
            md_context=comprehensive_summary[:5000] if comprehensive_summary else "",
            output_dir=output_dir,
        )

        if dr_results.get("success"):
            logger.info(
                f"Drug repositioning completed: "
                f"{dr_results.get('candidates_count', 0)} candidates found"
            )
            if cb:
                cb(95, f"Drug repositioning: {dr_results.get('candidates_count', 0)} candidates")
        else:
            logger.warning(f"Drug repositioning failed: {dr_results.get('error', 'unknown')}")
            if cb:
                cb(95, f"Drug repositioning: {dr_results.get('error', 'no results')}")

        # ── AI Singularity: 분석 결과 저장 ──────────────────────────────────
        try:
            from common.singularity_orchestrator import save_analysis_results, is_enabled
            if is_enabled() and dr_results.get("success"):
                order_id = state.get("order_id", 0)
                save_analysis_results(
                    state=state,
                    order_id=order_id,
                    drug_results=dr_results.get("candidates", []),
                )
        except Exception as sing_e:
            logger.debug(f"[Singularity] save_analysis_results skipped: {sing_e}")
        # ─────────────────────────────────────────────────────────────────────────

        dr_results.update(evaluation_status="computed" if dr_results.get("success") else "not_evaluable",
            evidence_role="model_hypothesis", independent_validation="not_performed",
            output_scope="companion_review", source_assertion_status="requires_verification",
            input_inventory=analysis_results["input_inventory"],
            required_limitations=["Candidate rankings and LLM evaluations do not establish drug efficacy or a direct relation in this experiment."])
        return {"drug_repositioning_results": dr_results}

    except Exception as e:
        logger.error(f"Drug repositioning failed: {e}", exc_info=True)
        if cb:
            cb(95, f"Drug repositioning error: {str(e)[:100]}")
        return {"drug_repositioning_results": {"success": False, "error": str(e), "evaluation_status": "not_evaluable"}}


def _build_analysis_results(ptms: list, network: dict, state: dict) -> dict:
    """Build analysis_results dict expected by DrugRepositioningPipeline."""
    import math
    from ptm_shared.de_novo_representation import is_de_novo_representation
    nodes, inventory = [], []
    for p in ptms:
        try:
            value = float(p.get("ptm_relative_log2fc"))
        except (TypeError, ValueError):
            value = None
        eligible = value is not None and math.isfinite(value) and not is_de_novo_representation(p)
        inventory.append({"gene": p.get("gene"), "site": p.get("position"), "condition": p.get("condition"),
                          "status": "eligible" if eligible else "not_evaluable", "reason": None if eligible else "conventional_adjusted_contrast_unavailable"})
        if not eligible:
            continue
        node = {
            "gene": p.get("gene", ""),
            "site": p.get("position", ""),
            "ptm_type": p.get("ptm_type", "Phosphorylation"),
            "log2fc": value,
            "protein_log2fc": p.get("protein_log2fc"),
            "condition": p.get("condition", ""),
        }
        enr = p.get("rag_enrichment", {})
        if enr:
            node["pathways"] = enr.get("pathways", [])
            node["function_summary"] = enr.get("function_summary", "")
            reg = enr.get("regulation", {})
            if reg:
                node["upstream_regulators"] = reg.get("upstream_regulators", [])
                node["downstream_targets"] = reg.get("downstream_targets", [])
            node["string_interactions"] = enr.get("string_interactions", [])
            node["diseases"] = enr.get("diseases", [])
        nodes.append(node)

    context = state.get("experimental_context", {})
    ptm_type = context.get("ptm_type", "phosphorylation")

    return {
        "networks": {"combined": {"nodes": nodes, "edges": network.get("edges", [])}},
        "input_inventory": inventory,
        "summary": {
            "total_ptms": len(ptms),
            "eligible_quantitative_nodes": len(nodes),
            "ptm_type": ptm_type,
            "positive_magnitude_count": len([p for p in nodes if p["log2fc"] > 0.5]),
            "negative_magnitude_count": len([p for p in nodes if p["log2fc"] < -0.5]),
        },
        "timepoints": [],
        "legends": network.get("legends", {}),
    }
