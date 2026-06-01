"""
Kinase Annotation Node — v9.14

Runs after temporal_comovement and before write_sections.
Collects kinase information from 8 sources for each co-wave cluster,
builds a temporal kinase cascade, performs cross-timepoint inference,
and generates structured LLM context for cell signaling interpretation.

v9.13: Auto-build Global Kinase Modules inside the pipeline.
  - Step 5 now builds kinase-centric modules from ALL enriched_ptm_data
    (not just co-wave cluster members), equivalent to the frontend
    'Global Kinase Modules' analysis.
  - If frontend_kinase_analysis is already available (pre-computed),
    it is used directly (no re-computation).
  - Result is stored in state["global_kinase_modules"] and appended
    to the LLM context automatically — no manual user action required.

v9.14: Ubiquitylation Analysis Suite — 3-module integration.
  - Module 1: Ubiquitin Chain Type Classifier (chain_type per site)
  - Module 2: E3 Ligase Module (RING/HECT/RBR family, degron motifs, E2 partners)
  - Module 3: Temporal Ubiquitylation Cascade (Phospho-Ub cross-talk, DUB inference)
  All three modules run automatically when ptm_type == 'ubiquitylation'.

Pipeline position:
    temporal_comovement → kinase_annotation → write_sections

Input (from state):
    - comovement_analysis: {clusters, singletons, summary}
    - enriched_ptm_data: List[dict]  (with rag_enrichment per PTM)
    - experimental_context: dict
    - network_analysis: dict  (for timepoint info)
    - frontend_kinase_analysis: dict  (optional, from DB if pre-computed)

Output (to state):
    - temporal_kinase_cascade: dict  (structured cascade data)
    - temporal_kinase_cascade_llm_context: str  (for LLM injection)
    - global_kinase_modules: dict  (kinase-centric module analysis, all PTMs)
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from report_generation.core.nodes.ubiquitin_chain_classifier import classify_ubiquitin_chain_types
from report_generation.core.nodes.e3_ligase_module import build_e3_ligase_modules
from report_generation.core.nodes.temporal_ubiquitylation_cascade import build_temporal_ubiquitylation_cascade

from common.kinase_utils import (
    normalize_kinase_name,
    are_kinases_same_family,
    KINASE_ALIAS_MAP,
)
from common.temporal_utils import tp_to_minutes

logger = logging.getLogger(__name__)


# ── Motif DB (same as orders.py — inline matching fallback) ──────────────
PHOSPHO_MOTIF_DB = {
    "CDK1/CDK2": r"[ST]P.[KR]",
    "CDK/MAPK": r"[ST]P",
    "ERK1/ERK2": r"P.[ST]P",
    "JNK": r"[ST]P",
    "p38": r"[ST]P",
    "DYRK1A/DYRK1B": r"R..[ST]P",
    "PKA": r"[RK][RK].[ST]",
    "PKC": r"[RK].[ST][RK]",
    "AKT/PKB": r"R.R..[ST]",
    "RSK": r"[RK].[RK]..[ST]",
    "CAMK2": r"[RK]..[ST]..[RK]",
    "AMPK": r"[LMVIF].[RK]..[ST]",
    "CK2": r"[ST].{1,2}[ED]",
    "CK1": r"[ST]..[ST]",
    "GSK3": r"[ST]...[ST]P",
    "PLK1": r"[DE].[ST][ILVM]",
    "Aurora_A/B": r"[RK].[ST][ILVM]",
    "ATM/ATR": r"[ST]Q",
    "DNA-PK": r"[ST]Q..",
    "Src/Fyn/Yes": r"[EDAY].[YF].{1,3}[PGAS]",
    "ABL": r"[IVLA]Y..[PG]",
    "JAK1/JAK2": r"Y..[LIV]",
    "mTOR": r"[ST]F",
    "CHK1/CHK2": r"[LM].[RK]..[ST]",
    "NEK2/NEK6": r"[LM].[ST]",
}

UBI_MOTIF_DB = {
    # SCF complex degrons
    "SCF_complex": r"[DE].{0,2}[ST].[DE]",
    "SCF-FBXW7": r"[LI].{0,1}[ST]P.{0,2}[ED]",
    "SCF-BTRC": r"DS.{1,2}[AG][IL]D",
    "SCF-SKP2": r"[LI].[KR].{1,2}[ST]P",
    # APC/C degrons
    "APC/C_D-box": r"R..L.{2,4}[ILVM]",
    "APC/C_KEN-box": r"KEN",
    "APC/C_ABBA": r"[FY].{0,2}[ILVM].{0,2}[FY]",
    # HECT E3 ligases
    "NEDD4/HECT": r"[LP]P.Y",
    "NEDD4L": r"[LP]P.Y",
    "SMURF1/2": r"[LP]P.Y",
    "WWP1/2": r"[LP]P.Y",
    "ITCH": r"[LP]P.[YF]",
    # RING E3 ligases
    "VHL": r"LA.{1,2}[ILVM]P",
    "MDM2": r"F..W..L",
    "CHIP/STUB1": r"[RK].{0,2}[ILVM].{0,2}[ED]",
    "PARKIN": r"[RK].{1,3}[ST].{1,3}[DE]",
    "TRAF6": r"[ST].{0,2}[KR].{0,2}[ED]",
    "TRIM21": r"[ILVM].{0,2}[KR].{0,2}[FY]",
    "TRIM25": r"[FY].{1,3}[KR]",
    # Phosphodegron-dependent E3s
    "SCF_phosphodegron": r"[ST]P.{0,2}[ST]P",
    "FBXO4": r"[DE].{1,2}[ST].{1,2}[DE]",
    "FBXO31": r"[ST].{1,3}[DE].{1,3}[ST]",
    # Autophagy/selective autophagy receptors
    "p62/SQSTM1": r"[ILVM].{0,2}[KR].{0,2}[ILVM]",
    "NBR1": r"[FY].{0,2}[ILVM].{0,2}[FY]",
    # Ubiquitin-binding domain degrons
    "UBR1/UBR2_N-degron": r"^[RKHFYWLIV]",
    "KEAP1": r"[DE].{1,3}[ST][GS][ED]",
    "SPOP": r"[ST].{0,1}[ST].{0,2}[ST]",
}

RESIDUE_KINASE_FAMILIES = {
    "S": ["CK2", "CK1", "CDK/MAPK", "PKA", "PKC", "AKT", "GSK3", "PLK1", "Aurora", "ATM/ATR", "AMPK", "mTOR"],
    "T": ["CDK/MAPK", "CK2", "GSK3", "PKC", "AMPK", "PLK1", "Aurora", "NEK", "MST1/2", "CAMK"],
    "Y": ["Src-family", "EGFR", "ABL", "JAK", "SYK", "FAK", "PDGFR", "VEGFR", "BTK", "FLT3"],
    # Ubiquitylation: Lysine is the primary ubiquitylation site
    "K": ["SCF_complex", "APC/C", "MDM2", "NEDD4", "CHIP/STUB1", "TRAF6", "PARKIN", "TRIM25", "VHL"],
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def run_kinase_annotation(state: dict) -> dict:
    """Annotate co-wave clusters with multi-source kinase info and build temporal cascade.

    v9.12: If frontend_kinase_analysis is available (from Global Kinase Modules),
    use it to enrich the LLM context with the more comprehensive 8-source analysis.
    """
    try:
        comovement = state.get("comovement_analysis", {})
        clusters = comovement.get("clusters", [])
        enriched_data = state.get("enriched_ptm_data", [])
        ptm_type = state.get("ptm_type", "phosphorylation")
        network_analysis = state.get("network_analysis", {})

        # v9.12: Check for frontend kinase analysis (Global Kinase Modules result)
        frontend_kinase = state.get("frontend_kinase_analysis", {})
        has_frontend_kinase = bool(
            frontend_kinase
            and frontend_kinase.get("kinase_modules")
            and len(frontend_kinase["kinase_modules"]) > 0
        )

        # v9.48: Load kinase activity heatmap data (CW Groups, per-condition scores)
        kinase_activity_heatmap = state.get("kinase_activity_heatmap", {})

        if not clusters:
            logger.info("[KINASE-ANNOTATION] No co-wave clusters — building Global Kinase Modules from all enriched PTMs")
            enriched_map = _build_enriched_map(enriched_data)
            motif_db = PHOSPHO_MOTIF_DB if ptm_type == "phosphorylation" else UBI_MOTIF_DB

            if has_frontend_kinase:
                global_km = frontend_kinase
                logger.info("[KINASE-ANNOTATION] Using pre-computed frontend kinase analysis (no clusters)")
            else:
                global_km = _build_global_kinase_modules(
                    enriched_data=enriched_data,
                    cluster_annotations=[],
                    clusters=[],
                    motif_db=motif_db,
                    ptm_type=ptm_type,
                )
                logger.info(
                    f"[KINASE-ANNOTATION] Global Kinase Modules (no clusters): "
                    f"{global_km['summary']['total_kinase_modules']} modules"
                )

            llm_context = _build_frontend_kinase_llm_context(global_km, ptm_type, kinase_activity_heatmap)
            # v9.33: Generate figures even without clusterss
            signal_flow_figures = []
            output_dir = state.get("output_dir", "")
            inferred_receptors = state.get("inferred_receptors", []) or []
            if output_dir:
                try:
                    from report_generation.core.nodes.signal_flow_figure import (
                        generate_signal_flow_figure,
                        generate_kinase_temporal_heatmap,
                        generate_pathway_diagram,
                    )

                    entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"

                    # Figure A (v10.2): Pathway Diagram — publication-standard cascade arrows
                    if inferred_receptors:
                        _effector_data = (global_km or {}).get("effector_proteins", [])
                        pd_path = generate_pathway_diagram(
                            inferred_receptors=inferred_receptors,
                            global_kinase_modules=global_km,
                            enriched_ptm_data=enriched_data,
                            output_dir=output_dir,
                            ptm_type=ptm_type,
                            experimental_context=state.get("experimental_context"),
                            kinase_activity_heatmap=kinase_activity_heatmap,
                            effector_proteins=_effector_data,
                        )
                        if pd_path:
                            signal_flow_figures.append({
                                "path": pd_path,
                                "caption": f"Inferred Signaling Pathway: Receptor → {entity_label} → Substrate cascade",
                                "type": "pathway_diagram",
                            })

                        # Signal Flow (4-layer) → Supplementary
                        sf_path = generate_signal_flow_figure(
                            inferred_receptors=inferred_receptors,
                            global_kinase_modules=global_km,
                            enriched_ptm_data=enriched_data,
                            output_dir=output_dir,
                            ptm_type=ptm_type,
                            effector_proteins=_effector_data,
                        )
                        _has_eff = " + Non-PTM Effectors" if _effector_data else ""
                        if sf_path:
                            signal_flow_figures.append({
                                "path": sf_path,
                                "caption": f"Detailed Signal Flow: Upstream Receptor → {entity_label} → PTM Substrate{_has_eff} (Supplementary)",
                                "type": "signal_flow_supplementary",
                            })

                    # Figure B: Kinase Temporal Activity Heatmap (directional)
                    ht_path = generate_kinase_temporal_heatmap(
                        global_kinase_modules=global_km,
                        output_dir=output_dir,
                        ptm_type=ptm_type,
                        kinase_activity_heatmap=kinase_activity_heatmap,
                    )
                    if ht_path:
                        entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
                        signal_flow_figures.append({
                            "path": ht_path,
                            "caption": f"Temporal {entity_label} Activity: Activation (Red) vs Inhibition (Blue) across conditions",
                            "type": "kinase_heatmap",
                        })
                except Exception as fig_err:
                    logger.warning(f"[KINASE-ANNOTATION] Figure generation failed (no clusters): {fig_err}")

            return {
                "temporal_kinase_cascade": {},
                "temporal_kinase_cascade_llm_context": llm_context,
                "global_kinase_modules": global_km,
                "signal_flow_figures": signal_flow_figures,
            }

        # Build gene → enriched_ptm_data lookup
        enriched_map = _build_enriched_map(enriched_data)
        logger.info(f"[KINASE-ANNOTATION] Built enriched map: {len(enriched_map)} PTM entries")

        # Select motif DB
        motif_db = PHOSPHO_MOTIF_DB if ptm_type == "phosphorylation" else UBI_MOTIF_DB

        # Step 1: Annotate each cluster's PTMs with 8-source kinase info
        cluster_annotations = []
        for cluster in clusters:
            ca = _annotate_cluster_kinases(cluster, enriched_map, motif_db, ptm_type)
            cluster_annotations.append(ca)
            logger.info(
                f"[KINASE-ANNOTATION] Cluster {cluster['cluster_id']}: "
                f"{ca['total_known']} known, {ca['total_motif']} motif-predicted, "
                f"{len(ca['anchor_kinases'])} anchor kinases"
            )

        # Step 2: Build temporal kinase cascade (ordered by peak timepoint)
        temporal_cascade = _build_temporal_cascade(cluster_annotations, clusters)

        # Step 3: Cross-timepoint inference
        temporal_cascade = _cross_timepoint_inference(temporal_cascade)

        # Step 4: Build LLM context (pipeline-internal cascade)
        llm_context = _build_temporal_kinase_llm_context(
            temporal_cascade, cluster_annotations, clusters, ptm_type
        )

        # Step 5: Build Global Kinase Modules from ALL enriched_ptm_data
        # v9.13: If frontend already has pre-computed data, use it directly.
        # Otherwise, build it here automatically — no manual user action needed.
        if has_frontend_kinase:
            global_km = frontend_kinase
            logger.info(
                f"[KINASE-ANNOTATION] Using pre-computed frontend kinase analysis "
                f"({len(frontend_kinase['kinase_modules'])} kinase modules)"
            )
        else:
            logger.info(
                f"[KINASE-ANNOTATION] Auto-building Global Kinase Modules from "
                f"{len(enriched_data)} enriched PTMs (v9.13)"
            )
            global_km = _build_global_kinase_modules(
                enriched_data=enriched_data,
                cluster_annotations=cluster_annotations,
                clusters=clusters,
                motif_db=motif_db,
                ptm_type=ptm_type,
            )
            logger.info(
                f"[KINASE-ANNOTATION] Global Kinase Modules built: "
                f"{global_km['summary']['total_kinase_modules']} modules, "
                f"{global_km['summary']['total_confirmed']} confirmed, "
                f"{global_km['summary']['total_inferred']} inferred"
            )

        # Append Global Kinase Modules context to LLM context
        global_km_ctx = _build_frontend_kinase_llm_context(global_km, ptm_type, kinase_activity_heatmap)
        if global_km_ctx:
            llm_context = llm_context + "\n\n" + global_km_ctx

        # ── Step 6 (v9.14): Ubiquitylation Analysis Suite ──────────────────
        ubi_chain_classifications = {}
        ubi_e3_modules_result = {}
        ubi_temporal_cascade_result = {}

        if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination"):
            logger.info("[KINASE-ANNOTATION] Running Ubiquitylation Analysis Suite (v9.14)")

            # Module 1: Chain Type Classifier
            ubi_chain_classifications = classify_ubiquitin_chain_types(
                enriched_data=enriched_data,
                ptm_type=ptm_type,
            )
            logger.info(
                f"[KINASE-ANNOTATION] Module 1 (Chain Type): "
                f"{len(ubi_chain_classifications)} sites classified"
            )

            # Module 2: E3 Ligase Module
            ubi_e3_modules_result = build_e3_ligase_modules(
                enriched_data=enriched_data,
                chain_classifications=ubi_chain_classifications,
                clusters=clusters,
                ptm_type=ptm_type,
            )
            logger.info(
                f"[KINASE-ANNOTATION] Module 2 (E3 Ligase): "
                f"{ubi_e3_modules_result.get('summary', {}).get('total_e3_modules', 0)} modules"
            )

            # Module 3: Temporal Ubiquitylation Cascade
            ubi_temporal_cascade_result = build_temporal_ubiquitylation_cascade(
                enriched_data=enriched_data,
                chain_classifications=ubi_chain_classifications,
                e3_modules=ubi_e3_modules_result.get("e3_modules", []),
                clusters=clusters,
                comovement_analysis=state.get("comovement_analysis", {}),
                ptm_type=ptm_type,
            )
            logger.info(
                f"[KINASE-ANNOTATION] Module 3 (Temporal Ubi Cascade): "
                f"{ubi_temporal_cascade_result.get('summary', {}).get('total_phospho_ub_crosstalk', 0)} "
                f"phospho-ub crosstalk events"
            )

            # Append ubiquitylation contexts to LLM context
            e3_ctx = ubi_e3_modules_result.get("llm_context", "")
            ubi_cascade_ctx = ubi_temporal_cascade_result.get("llm_context", "")
            if e3_ctx:
                llm_context = llm_context + "\n\n" + e3_ctx
            if ubi_cascade_ctx:
                llm_context = llm_context + "\n\n" + ubi_cascade_ctx

        logger.info(
            f"[KINASE-ANNOTATION] Temporal cascade: {len(temporal_cascade['timepoint_order'])} timepoints, "
            f"{len(temporal_cascade.get('cross_timepoint_inferences', []))} cross-timepoint inferences, "
            f"LLM context: {len(llm_context)} chars"
        )

        # ── Step 7 (v9.33): Generate Signal Flow & Kinase Heatmap figures ──
        signal_flow_figures = []
        output_dir = state.get("output_dir", "")
        inferred_receptors = state.get("inferred_receptors", []) or []

        if output_dir:
            try:
                from report_generation.core.nodes.signal_flow_figure import (
                    generate_signal_flow_figure,
                    generate_kinase_temporal_heatmap,
                    generate_pathway_diagram,
                )

                entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"

                # Figure A (v10.2): Pathway Diagram — publication-standard cascade arrows
                if inferred_receptors:
                    _effector_data = (global_km or {}).get("effector_proteins", [])
                    pd_path = generate_pathway_diagram(
                        inferred_receptors=inferred_receptors,
                        global_kinase_modules=global_km,
                        enriched_ptm_data=enriched_data,
                        output_dir=output_dir,
                        ptm_type=ptm_type,
                        experimental_context=state.get("experimental_context"),
                        kinase_activity_heatmap=kinase_activity_heatmap,
                        effector_proteins=_effector_data,
                    )
                    if pd_path:
                        signal_flow_figures.append({
                            "path": pd_path,
                            "caption": f"Inferred Signaling Pathway: Receptor → {entity_label} → Substrate cascade",
                            "type": "pathway_diagram",
                        })
                        logger.info(f"[KINASE-ANNOTATION] Generated Pathway Diagram: {pd_path}")

                    # Signal Flow (4-layer) → Supplementary
                    sf_path = generate_signal_flow_figure(
                        inferred_receptors=inferred_receptors,
                        global_kinase_modules=global_km,
                        enriched_ptm_data=enriched_data,
                        output_dir=output_dir,
                        ptm_type=ptm_type,
                        effector_proteins=_effector_data,
                    )
                    _has_eff = " + Non-PTM Effectors" if _effector_data else ""
                    if sf_path:
                        signal_flow_figures.append({
                            "path": sf_path,
                            "caption": f"Detailed Signal Flow: Upstream Receptor → {entity_label} → PTM Substrate{_has_eff} (Supplementary)",
                            "type": "signal_flow_supplementary",
                        })
                        logger.info(f"[KINASE-ANNOTATION] Generated Signal Flow (supplementary): {sf_path}")
                else:
                    logger.info("[KINASE-ANNOTATION] No inferred receptors — skipping pathway figures")

                # Figure B: Kinase Temporal Activity Heatmap (v10.2: directional)
                ht_path = generate_kinase_temporal_heatmap(
                    global_kinase_modules=global_km,
                    output_dir=output_dir,
                    ptm_type=ptm_type,
                    kinase_activity_heatmap=kinase_activity_heatmap,
                )
                if ht_path:
                    entity_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
                    signal_flow_figures.append({
                        "path": ht_path,
                        "caption": f"Temporal {entity_label} Activity: Activation (Red) vs Inhibition (Blue) across conditions",
                        "type": "kinase_heatmap",
                    })
                    logger.info(f"[KINASE-ANNOTATION] Generated Kinase Temporal Heatmap: {ht_path}")

            except Exception as fig_err:
                logger.warning(f"[KINASE-ANNOTATION] Signal Flow figure generation failed: {fig_err}", exc_info=True)

        return {
            "temporal_kinase_cascade": temporal_cascade,
            "temporal_kinase_cascade_llm_context": llm_context,
            "global_kinase_modules": global_km,
            "signal_flow_figures": signal_flow_figures,
            "ubi_chain_classifications": ubi_chain_classifications,
            "ubi_e3_modules": ubi_e3_modules_result,
            "ubi_temporal_cascade": ubi_temporal_cascade_result,
        }

    except Exception as e:
        logger.error(f"[KINASE-ANNOTATION] Failed: {e}", exc_info=True)
        return {
            "temporal_kinase_cascade": {},
            "temporal_kinase_cascade_llm_context": "",
        }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: PER-CLUSTER KINASE ANNOTATION (8 sources from enriched_ptm_data)
# ═══════════════════════════════════════════════════════════════════════════

def _build_enriched_map(enriched_data: list) -> dict:
    """Build GENE_POSITION → enriched entry lookup."""
    emap = {}
    for ed in enriched_data:
        gene = (ed.get("gene") or ed.get("Gene.Name", "")).strip().upper()
        pos = ed.get("position") or ed.get("PTM_Position", "")
        if gene and pos:
            key = f"{gene}_{str(pos).upper()}"
            emap[key] = ed
    return emap


def _collect_known_kinases_from_enriched(
    gene: str, position: str, enriched_entry: dict
) -> List[dict]:
    """Collect known kinases from enriched_ptm_data (Sources 1-6)."""
    known = []
    rag = enriched_entry.get("rag_enrichment", {})
    if not rag or not isinstance(rag, dict):
        return known

    # Source 1: kinase_prediction (LLM-based)
    kp = rag.get("kinase_prediction", {})
    if isinstance(kp, str):
        import ast
        try:
            kp = ast.literal_eval(kp) if kp.startswith("{") else {}
        except Exception:
            kp = {}
    if isinstance(kp, dict):
        for k in kp.get("predicted_kinases", []):
            if isinstance(k, dict) and k.get("kinase"):
                known.append({
                    "kinase": k["kinase"],
                    "confidence": k.get("confidence", ""),
                    "source": "rag_kinase_prediction",
                })
            elif isinstance(k, str) and k:
                known.append({"kinase": k, "confidence": "predicted", "source": "rag_kinase_prediction"})

    # Source 2: regulation
    reg = rag.get("regulation", {})
    if isinstance(reg, dict):
        for ks in reg.get("kinase_substrate", []):
            if isinstance(ks, dict) and ks.get("kinase"):
                known.append({
                    "kinase": ks["kinase"],
                    "confidence": "literature",
                    "source": "kinase_substrate_pair",
                    "pmid": ks.get("pmid", ""),
                })
        for ur in reg.get("upstream_regulators", []):
            if isinstance(ur, dict) and ur.get("regulator"):
                known.append({
                    "kinase": ur["regulator"],
                    "confidence": ur.get("confidence", "literature"),
                    "source": "upstream_regulator",
                })
            elif isinstance(ur, str) and ur:
                known.append({"kinase": ur, "confidence": "literature", "source": "upstream_regulator"})
        # Source 2b: E3 ligase-substrate pairs (ubiquitylation)
        for e3s in reg.get("e3_substrate", []):
            if isinstance(e3s, dict) and e3s.get("e3_ligase"):
                known.append({
                    "kinase": e3s["e3_ligase"],
                    "confidence": "literature",
                    "source": "e3_substrate_pair",
                    "pmid": e3s.get("pmid", ""),
                })
        # Source 2c: DUB-substrate pairs (ubiquitylation)
        for dubs in reg.get("dub_substrate", []):
            if isinstance(dubs, dict) and dubs.get("dub"):
                known.append({
                    "kinase": dubs["dub"],
                    "confidence": "literature",
                    "source": "dub_substrate_pair",
                    "pmid": dubs.get("pmid", ""),
                })

    # Source 3: ptm_validation (iPTMnet cached)
    ptm_val = rag.get("ptm_validation", {})
    if isinstance(ptm_val, dict):
        for hit in ptm_val.get("iptmnet_hits", []):
            if isinstance(hit, dict):
                enz = hit.get("enzyme") or {}
                if isinstance(enz, dict) and enz.get("name"):
                    known.append({
                        "kinase": enz["name"],
                        "confidence": "database",
                        "source": "iPTMnet",
                    })
        novelty = ptm_val.get("novelty") if isinstance(ptm_val.get("novelty"), dict) else {}
        if novelty:
            enz = novelty.get("enzyme") or {}
            if isinstance(enz, dict) and enz.get("name"):
                known.append({
                    "kinase": enz["name"],
                    "confidence": "database",
                    "source": "iPTMnet",
                })

    # Source 4: fulltext_analysis
    ft = rag.get("fulltext_analysis", {})
    if isinstance(ft, dict):
        # Phosphorylation pattern
        kinase_pattern = re.compile(
            r'(?:substrate\s+of|phosphorylated\s+by|target\s+of|regulated\s+by)'
            r'\s+([A-Z][A-Za-z0-9]{1,10}(?:\s+kinase)?)',
            re.IGNORECASE,
        )
        # Ubiquitylation-specific patterns
        e3_pattern = re.compile(
            r'(?:ubiquitylated\s+by|ubiquitinated\s+by|ubiquitylation\s+by|ubiquitination\s+by'
            r'|E3\s+ligase\s+([A-Z][A-Za-z0-9]{1,15})'
            r'|([A-Z][A-Za-z0-9]{1,15})\s+(?:E3|ligase|RING|HECT|RBR)'
            r'|([A-Z][A-Za-z0-9]{1,15})\s+(?:ubiquitylates?|ubiquitinates?|mediates?\s+ubiquitylation)'
            r'|degradation\s+(?:of\s+\w+\s+)?(?:by|via|through)\s+([A-Z][A-Za-z0-9]{1,15}))'
            r'(?:\s+([A-Z][A-Za-z0-9]{1,15}))?',
            re.IGNORECASE,
        )
        e3_simple_pattern = re.compile(
            r'([A-Z][A-Za-z0-9]{1,15})\s+(?:ubiquitylates?|ubiquitinates?|poly-?ubiquitylates?'
            r'|mono-?ubiquitylates?|promotes?\s+ubiquitylation|mediates?\s+ubiquitylation'
            r'|catalyzes?\s+ubiquitylation|targets?\s+\w+\s+for\s+(?:proteasomal\s+)?degradation)',
            re.IGNORECASE,
        )
        all_findings = list(ft.get("key_findings", []))
        for article in ft.get("per_article", []):
            if isinstance(article, dict):
                all_findings.extend([(f, article.get("pmid", "")) for f in article.get("key_findings", [])])

        for item in all_findings:
            if isinstance(item, tuple):
                finding, pmid = item
            else:
                finding, pmid = item, ""
            if not isinstance(finding, str):
                continue
            # Phosphorylation kinase extraction
            for m in kinase_pattern.finditer(finding):
                kname = m.group(1).strip()
                if kname and len(kname) > 1:
                    known.append({
                        "kinase": kname,
                        "confidence": "text_mining",
                        "source": "fulltext_analysis",
                        "pmid": pmid,
                    })
            # E3 ligase extraction (ubiquitylation)
            for m in e3_simple_pattern.finditer(finding):
                kname = m.group(1).strip()
                if kname and len(kname) > 1 and kname.upper() not in (
                    "THE", "THIS", "THAT", "THESE", "THOSE", "WHICH", "WHEN", "WITH"
                ):
                    known.append({
                        "kinase": kname,
                        "confidence": "text_mining",
                        "source": "fulltext_e3_extraction",
                        "pmid": pmid,
                    })

    # Source 5: abstract_analysis (LLM NER)
    aa = rag.get("abstract_analysis", {})
    if isinstance(aa, dict):
        for ki in aa.get("kinases", []):
            if isinstance(ki, dict) and ki.get("name"):
                known.append({
                    "kinase": ki["name"],
                    "confidence": ki.get("confidence", "predicted"),
                    "source": "abstract_analysis",
                })
            elif isinstance(ki, str) and ki:
                known.append({"kinase": ki, "confidence": "predicted", "source": "abstract_analysis"})
        for key_name in ("upstream_kinases", "predicted_kinases", "regulators"):
            for item in aa.get(key_name, []):
                if isinstance(item, str) and item:
                    known.append({"kinase": item, "confidence": "predicted", "source": "abstract_analysis"})
                elif isinstance(item, dict) and (item.get("kinase") or item.get("name")):
                    known.append({
                        "kinase": item.get("kinase") or item.get("name"),
                        "confidence": item.get("confidence", "predicted"),
                        "source": "abstract_analysis",
                    })
        # Source 5b: E3 ligase fields from abstract_analysis (ubiquitylation)
        for key_name in ("e3_ligases", "ubiquitin_ligases", "e3_ligase", "ligases"):
            for item in aa.get(key_name, []):
                if isinstance(item, str) and item:
                    known.append({"kinase": item, "confidence": "predicted", "source": "abstract_e3_analysis"})
                elif isinstance(item, dict) and (item.get("e3_ligase") or item.get("name") or item.get("kinase")):
                    known.append({
                        "kinase": item.get("e3_ligase") or item.get("name") or item.get("kinase"),
                        "confidence": item.get("confidence", "predicted"),
                        "source": "abstract_e3_analysis",
                    })

    # Source 6: STRING DB interactions
    string_ints = rag.get("string_interactions", [])
    if isinstance(string_ints, list):
        kinase_keywords = {
            "kinase", "phosphotransferase", "CK1", "CK2", "CDK", "MAPK",
            "PKA", "PKC", "GSK", "AKT", "mTOR", "ATM", "ATR", "PLK",
            "AURK", "NEK", "DYRK", "CLK", "SRPK", "CAMK", "AMPK",
        }
        # E3 ligase keywords for ubiquitylation
        e3_keywords = {
            "ligase", "RING", "HECT", "RBR", "SCF", "APC", "MDM2", "NEDD4",
            "CHIP", "SIAH", "FBXW", "FBXL", "FBXO", "BTRC", "KEAP1", "VHL",
            "TRAF", "BIRC", "XIAP", "ITCH", "WWP", "SMURF", "HUWE", "HERC",
            "UBR", "TRIM", "RNF", "ZNRF", "MARCH", "PARK", "PARKIN",
        }
        for si in string_ints:
            if isinstance(si, dict):
                partner = si.get("preferredName_B") or si.get("partner") or si.get("name", "")
                score = si.get("score", 0)
                if partner and score >= 700:
                    partner_upper = partner.upper()
                    if any(kw.upper() in partner_upper for kw in kinase_keywords):
                        known.append({
                            "kinase": partner,
                            "confidence": f"STRING (score={score})",
                            "source": "string_db",
                        })
                    elif any(kw.upper() in partner_upper for kw in e3_keywords):
                        known.append({
                            "kinase": partner,
                            "confidence": f"STRING_E3 (score={score})",
                            "source": "string_db_e3",
                        })

    # Normalize & deduplicate
    for kk in known:
        canonical, display = normalize_kinase_name(kk["kinase"])
        kk["canonical_name"] = canonical
        kk["display_name"] = display

    seen = set()
    unique = []
    for kk in known:
        canon = kk["canonical_name"]
        if canon and canon not in seen:
            seen.add(canon)
            unique.append(kk)
        elif canon in seen:
            # Merge source
            for existing in unique:
                if existing["canonical_name"] == canon:
                    if "merged_sources" not in existing:
                        existing["merged_sources"] = [existing.get("source", "")]
                    if kk["source"] not in existing.get("merged_sources", []) and kk["source"] != existing.get("source"):
                        existing["merged_sources"].append(kk["source"])
                    break

    return unique


def _predict_motif_kinases(
    position: str, enriched_entry: dict, motif_db: dict
) -> List[dict]:
    """Predict kinases from motif analysis (inline matching + residue fallback)."""
    predicted = []

    # Try sequence from enriched data
    seq = ""
    rag = enriched_entry.get("rag_enrichment", {})
    for seq_key in ("modified_sequence", "Modified.Sequence", "sequence_window",
                     "Sequence_Window", "flanking_sequence"):
        val = enriched_entry.get(seq_key, "")
        if val and isinstance(val, str) and len(val) > 3:
            seq = re.sub(r'\(UniMod:\d+\)', '', val).strip()
            break
    if not seq and isinstance(rag, dict):
        for seq_key in ("sequence_window", "flanking_sequence"):
            val = rag.get(seq_key, "")
            if val and isinstance(val, str) and len(val) > 3:
                seq = val
                break

    if seq and len(seq) > 2:
        for kinase_name, pattern in motif_db.items():
            try:
                if re.search(pattern, seq):
                    canonical, display = normalize_kinase_name(kinase_name)
                    predicted.append({
                        "kinase_family": kinase_name,
                        "canonical_family": canonical,
                        "display_family": display,
                        "source": "inline_motif_match",
                    })
            except re.error:
                continue

    # Fallback: residue-based
    if not predicted and position:
        residue = str(position)[0].upper()
        if residue in RESIDUE_KINASE_FAMILIES:
            for family in RESIDUE_KINASE_FAMILIES[residue]:
                canonical, display = normalize_kinase_name(family)
                predicted.append({
                    "kinase_family": family,
                    "canonical_family": canonical,
                    "display_family": display,
                    "source": "residue_prediction",
                })

    return predicted


def _annotate_cluster_kinases(
    cluster: dict, enriched_map: dict, motif_db: dict, ptm_type: str
) -> dict:
    """Annotate a single cluster with 8-source kinase info + motif prediction + group inference."""
    cluster_id = cluster["cluster_id"]
    peak_tp = cluster.get("peak_timepoint", "")
    pattern = cluster.get("pattern", "")

    ptm_annotations = []
    anchor_kinases: Dict[str, dict] = {}  # canonical → info

    for md in cluster.get("member_details", []):
        gene = md.get("gene", "")
        site = md.get("site", md.get("position", ""))
        key = f"{gene.upper()}_{str(site).upper()}"
        enriched_entry = enriched_map.get(key, {})

        # Collect known kinases (Sources 1-6)
        known = _collect_known_kinases_from_enriched(gene, site, enriched_entry)

        # Motif prediction
        motif_pred = _predict_motif_kinases(site, enriched_entry, motif_db)

        # Concordance
        concordance = "not_applicable"
        if motif_pred and known:
            motif_canons = set()
            for m in motif_pred:
                for part in m.get("canonical_family", "").split("/"):
                    if part and len(part) >= 2:
                        motif_canons.add(part)
            known_canons = set()
            for k in known:
                for part in k.get("canonical_name", "").split("/"):
                    if part and len(part) >= 2:
                        known_canons.add(part)
            matched = False
            for kc in known_canons:
                for mc in motif_canons:
                    if are_kinases_same_family(kc, mc):
                        matched = True
                        break
                if matched:
                    break
            concordance = "concordant" if matched else "discordant"

        ptm_ann = {
            "key": md["key"],
            "gene": gene,
            "site": site,
            "peak_tp": md.get("peak_tp", ""),
            "max_fc": md.get("max_fc", 0),
            "known_kinases": known,
            "motif_predicted": motif_pred,
            "concordance": concordance,
        }
        ptm_annotations.append(ptm_ann)

        # Collect anchor kinases
        for kk in known:
            canon = kk["canonical_name"]
            if canon not in anchor_kinases:
                anchor_kinases[canon] = {
                    "kinase": kk["display_name"],
                    "canonical": canon,
                    "confirmed_ptms": [],
                    "sources": set(),
                }
            anchor_kinases[canon]["confirmed_ptms"].append(md["key"])
            anchor_kinases[canon]["sources"].add(kk.get("source", "unknown"))

    # Group inference within cluster
    inferred = []
    novel = []
    for pa in ptm_annotations:
        if pa["known_kinases"]:
            continue
        motif_canons = set()
        for m in pa["motif_predicted"]:
            for part in m.get("canonical_family", "").split("/"):
                if part:
                    motif_canons.add(part)

        matched_anchor = None
        for anchor_canon, anchor_info in anchor_kinases.items():
            for mc in motif_canons:
                if are_kinases_same_family(anchor_canon, mc):
                    matched_anchor = anchor_info
                    break
            if matched_anchor:
                break

        if matched_anchor:
            inferred.append({
                "ptm": pa["key"],
                "inferred_kinase": matched_anchor["kinase"],
                "inferred_canonical": matched_anchor["canonical"],
            })
        else:
            novel.append({
                "ptm": pa["key"],
                "motif_families": [m["canonical_family"] for m in pa["motif_predicted"]],
            })

    total_known = sum(1 for pa in ptm_annotations if pa["known_kinases"])
    total_motif = sum(1 for pa in ptm_annotations if pa["motif_predicted"] and not pa["known_kinases"])

    return {
        "cluster_id": cluster_id,
        "peak_timepoint": peak_tp,
        "pattern": pattern,
        "member_count": len(ptm_annotations),
        "ptm_annotations": ptm_annotations,
        "anchor_kinases": anchor_kinases,
        "inferred_assignments": inferred,
        "novel_candidates": novel,
        "total_known": total_known,
        "total_motif": total_motif,
    }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: BUILD TEMPORAL KINASE CASCADE
# ═══════════════════════════════════════════════════════════════════════════

def _build_temporal_cascade(
    cluster_annotations: list, clusters: list
) -> dict:
    """Build temporal cascade: timepoint → kinases active at that timepoint."""
    # Group clusters by peak timepoint
    tp_clusters: Dict[str, list] = defaultdict(list)
    for ca, cl in zip(cluster_annotations, clusters):
        peak_tp = cl.get("peak_timepoint", "")
        if peak_tp:
            tp_clusters[peak_tp].append(ca)

    # Sort timepoints chronologically
    sorted_tps = sorted(tp_clusters.keys(), key=lambda t: tp_to_minutes(t))

    timepoint_kinase_map: Dict[str, dict] = {}
    for tp in sorted_tps:
        tp_kinases: Dict[str, dict] = {}  # canonical → info
        tp_ptms = []
        for ca in tp_clusters[tp]:
            for canon, info in ca["anchor_kinases"].items():
                if canon not in tp_kinases:
                    tp_kinases[canon] = {
                        "kinase": info["kinase"],
                        "canonical": canon,
                        "sources": list(info["sources"]),
                        "confirmed_ptms": list(info["confirmed_ptms"]),
                        "cluster_ids": [ca["cluster_id"]],
                    }
                else:
                    tp_kinases[canon]["confirmed_ptms"].extend(info["confirmed_ptms"])
                    tp_kinases[canon]["cluster_ids"].append(ca["cluster_id"])
                    tp_kinases[canon]["sources"] = list(
                        set(tp_kinases[canon]["sources"]) | info["sources"]
                    )
            for pa in ca["ptm_annotations"]:
                tp_ptms.append({
                    "key": pa["key"],
                    "gene": pa["gene"],
                    "site": pa["site"],
                    "has_known_kinase": bool(pa["known_kinases"]),
                    "top_kinase": pa["known_kinases"][0]["display_name"] if pa["known_kinases"] else "",
                    "motif_families": [m["canonical_family"] for m in pa["motif_predicted"]],
                })

        timepoint_kinase_map[tp] = {
            "minutes": tp_to_minutes(tp),
            "kinases": tp_kinases,
            "ptms": tp_ptms,
            "cluster_ids": [ca["cluster_id"] for ca in tp_clusters[tp]],
        }

    # Identify shared kinases across timepoints
    all_kinase_tps: Dict[str, list] = defaultdict(list)
    for tp, data in timepoint_kinase_map.items():
        for canon in data["kinases"]:
            all_kinase_tps[canon].append(tp)

    persistent_kinases = {
        k: tps for k, tps in all_kinase_tps.items() if len(tps) >= 2
    }

    return {
        "timepoint_order": sorted_tps,
        "timepoint_kinase_map": timepoint_kinase_map,
        "all_kinase_timepoints": dict(all_kinase_tps),
        "persistent_kinases": persistent_kinases,
        "cross_timepoint_inferences": [],  # populated in Step 3
    }


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3: CROSS-TIMEPOINT INFERENCE
# ═══════════════════════════════════════════════════════════════════════════

def _cross_timepoint_inference(cascade: dict) -> dict:
    """Infer kinases for early timepoints using later timepoint knowledge.

    Key insight: if 20min has known CDK5 as anchor kinase, and 5min has PTMs
    with CDK motif but no known kinase, we can infer CDK5 was already active
    at 5min (the kinase was active before its substrates peaked at 20min).
    """
    tp_order = cascade["timepoint_order"]
    tp_map = cascade["timepoint_kinase_map"]
    inferences = []

    # Collect ALL known kinases from all timepoints
    all_known: Dict[str, dict] = {}  # canonical → {kinase, sources, timepoints}
    for tp in tp_order:
        for canon, info in tp_map[tp]["kinases"].items():
            if canon not in all_known:
                all_known[canon] = {
                    "kinase": info["kinase"],
                    "canonical": canon,
                    "sources": set(info["sources"]),
                    "known_timepoints": [tp],
                }
            else:
                all_known[canon]["known_timepoints"].append(tp)
                all_known[canon]["sources"].update(info["sources"])

    # For each timepoint, check PTMs without known kinase
    for tp in tp_order:
        tp_data = tp_map[tp]
        for ptm in tp_data["ptms"]:
            if ptm["has_known_kinase"]:
                continue

            # Check if any motif family matches a known kinase from OTHER timepoints
            for motif_canon in ptm["motif_families"]:
                for known_canon, known_info in all_known.items():
                    if are_kinases_same_family(motif_canon, known_canon):
                        # Check if this kinase is NOT already known at this timepoint
                        if tp not in known_info["known_timepoints"]:
                            inferences.append({
                                "target_timepoint": tp,
                                "target_ptm": ptm["key"],
                                "inferred_kinase": known_info["kinase"],
                                "inferred_canonical": known_canon,
                                "evidence_timepoints": known_info["known_timepoints"],
                                "evidence_sources": list(known_info["sources"]),
                                "motif_match": motif_canon,
                                "reasoning": (
                                    f"{known_info['kinase']} is a confirmed kinase at "
                                    f"{', '.join(known_info['known_timepoints'])}. "
                                    f"{ptm['key']} at {tp} has {motif_canon} motif, "
                                    f"suggesting {known_info['kinase']} was already active "
                                    f"at {tp} before its substrates peaked later."
                                ),
                            })
                            break  # One inference per PTM-kinase pair
                    # Don't break outer loop — a PTM might match multiple kinases

    cascade["cross_timepoint_inferences"] = inferences
    logger.info(f"[KINASE-ANNOTATION] Cross-timepoint inferences: {len(inferences)}")
    return cascade


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4: BUILD LLM CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# v9.35: EVIDENCE STRENGTH GRADING
# ═══════════════════════════════════════════════════════════════════════════

# Source tiers for evidence grading
_HIGH_CONFIDENCE_SOURCES = {
    "kinase_substrate_pair",   # Literature-confirmed kinase-substrate
    "e3_substrate_pair",       # Literature-confirmed E3-substrate
    "iPTMnet",                 # Database-confirmed
    "dub_substrate_pair",      # Literature-confirmed DUB-substrate
}
_MEDIUM_CONFIDENCE_SOURCES = {
    "upstream_regulator",      # Literature upstream regulator
    "fulltext_analysis",       # Text-mined from full-text articles
    "fulltext_e3_extraction",  # Text-mined E3 from full-text
    "abstract_analysis",       # NER from abstracts
    "abstract_e3_analysis",    # NER E3 from abstracts
}
_LOW_CONFIDENCE_SOURCES = {
    "rag_kinase_prediction",   # LLM-based prediction
    "string_db",               # STRING PPI interaction
    "string_db_e3",            # STRING PPI E3
}


def _grade_evidence_strength(
    sources: set,
    has_concordant_motif: bool = False,
    has_pmid: bool = False,
    n_effectors: int = 0,
) -> str:
    """Grade the evidence strength for a kinase-substrate relationship.

    Returns:
        'Strong', 'Moderate', or 'Inferred'

    Grading criteria:
        Strong:   2+ independent sources (at least 1 high-confidence)
                  OR 1 high-confidence source + concordant motif + PMID
                  OR 1 high-confidence source + 3+ concordant effectors
        Moderate: 1 high/medium source + concordant motif
                  OR 2+ medium sources
                  OR 1 high source alone
        Inferred: motif prediction only, or only low-confidence sources
    """
    high = sources & _HIGH_CONFIDENCE_SOURCES
    medium = sources & _MEDIUM_CONFIDENCE_SOURCES
    low = sources & _LOW_CONFIDENCE_SOURCES
    total_confirmed = len(high) + len(medium)

    # Strong evidence
    if len(high) >= 1 and (total_confirmed >= 2 or (has_concordant_motif and has_pmid)):
        return "Strong"
    if len(high) >= 1 and n_effectors >= 3:
        return "Strong"
    if total_confirmed >= 3:
        return "Strong"

    # Moderate evidence
    if len(high) >= 1:
        return "Moderate"
    if len(medium) >= 2:
        return "Moderate"
    if len(medium) >= 1 and has_concordant_motif:
        return "Moderate"

    # Inferred
    return "Inferred"


def _compute_cascade_evidence_grades(
    cluster_annotations: list,
) -> Dict[str, dict]:
    """Compute evidence grades for each kinase across all clusters.

    Returns:
        Dict[canonical_kinase] → {
            'grade': 'Strong'|'Moderate'|'Inferred',
            'sources': set,
            'n_confirmed': int,
            'n_inferred': int,
            'has_pmid': bool,
            'concordance_ratio': float,
        }
    """
    kinase_evidence: Dict[str, dict] = {}

    for ca in cluster_annotations:
        # Anchor kinases
        for canon, info in ca.get("anchor_kinases", {}).items():
            if canon not in kinase_evidence:
                kinase_evidence[canon] = {
                    "kinase": info["kinase"],
                    "sources": set(),
                    "n_confirmed": 0,
                    "n_inferred": 0,
                    "has_pmid": False,
                    "concordant_count": 0,
                    "total_ptms": 0,
                }
            ke = kinase_evidence[canon]
            ke["sources"].update(info.get("sources", set()))
            ke["n_confirmed"] += len(info.get("confirmed_ptms", []))

        # Check PTM annotations for concordance and PMID
        for pa in ca.get("ptm_annotations", []):
            for kk in pa.get("known_kinases", []):
                canon = kk.get("canonical_name", "")
                if canon and canon in kinase_evidence:
                    if kk.get("pmid"):
                        kinase_evidence[canon]["has_pmid"] = True
                    kinase_evidence[canon]["total_ptms"] += 1
                    if pa.get("concordance") == "concordant":
                        kinase_evidence[canon]["concordant_count"] += 1

        # Inferred assignments
        for inf in ca.get("inferred_assignments", []):
            canon = inf.get("inferred_canonical", "")
            if canon and canon in kinase_evidence:
                kinase_evidence[canon]["n_inferred"] += 1

    # Compute grades
    for canon, ke in kinase_evidence.items():
        total = ke["total_ptms"] or 1
        concordance_ratio = ke["concordant_count"] / total
        ke["concordance_ratio"] = concordance_ratio
        ke["grade"] = _grade_evidence_strength(
            sources=ke["sources"],
            has_concordant_motif=concordance_ratio > 0.3,
            has_pmid=ke["has_pmid"],
        )

    return kinase_evidence


def _build_temporal_kinase_llm_context(
    cascade: dict,
    cluster_annotations: list,
    clusters: list,
    ptm_type: str,
) -> str:
    """Build structured LLM context for temporal kinase cascade interpretation."""
    if not cascade.get("timepoint_order"):
        return ""

    regulator_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
    tp_order = cascade["timepoint_order"]
    tp_map = cascade["timepoint_kinase_map"]

    parts = [
        "\n## TEMPORAL KINASE CASCADE ANALYSIS",
        "",
        f"Multi-source {regulator_label.lower()} annotation was performed for each co-wave cluster, "
        f"collecting {regulator_label.lower()} information from 6 independent sources: "
        "LLM-based kinase prediction, literature kinase-substrate pairs, upstream regulators, "
        "iPTMnet database, text mining of full-text articles, abstract NER analysis, "
        "and STRING protein-protein interactions. "
        f"Motif-based {regulator_label.lower()} prediction was also applied as an independent validation.",
        "",
    ]

    # ── Section A: Timepoint-by-timepoint kinase landscape ──
    parts.append(f"### A. Temporal {regulator_label} Landscape (timepoint-by-timepoint)")
    parts.append("")

    # v9.35: Compute evidence grades for all kinases
    evidence_grades = _compute_cascade_evidence_grades(cluster_annotations)

    for tp in tp_order:
        tp_data = tp_map[tp]
        minutes = tp_data["minutes"]
        kinases = tp_data["kinases"]
        ptms = tp_data["ptms"]
        cluster_ids = tp_data["cluster_ids"]

        parts.append(f"**{tp} ({minutes:.0f} min) — Cluster(s) {', '.join(str(c) for c in cluster_ids)}:**")

        known_ptms = [p for p in ptms if p["has_known_kinase"]]
        unknown_ptms = [p for p in ptms if not p["has_known_kinase"]]

        if kinases:
            parts.append(f"  Known {regulator_label}s ({len(kinases)}):")
            for canon, info in sorted(kinases.items(), key=lambda x: len(x[1]["confirmed_ptms"]), reverse=True):
                sources_str = ", ".join(info["sources"])
                ptms_str = ", ".join(info["confirmed_ptms"][:8])
                if len(info["confirmed_ptms"]) > 8:
                    ptms_str += f" (+{len(info['confirmed_ptms']) - 8} more)"
                # v9.35: Add evidence grade
                eg = evidence_grades.get(canon, {})
                grade = eg.get("grade", "Inferred")
                grade_emoji = {"Strong": "★★★", "Moderate": "★★☆", "Inferred": "★☆☆"}.get(grade, "★☆☆")
                parts.append(
                    f"    - {info['kinase']} (canonical: {canon}): "
                    f"{len(info['confirmed_ptms'])} confirmed substrates ({ptms_str}), "
                    f"sources: [{sources_str}], "
                    f"Evidence: {grade} {grade_emoji}"
                )
        else:
            parts.append(f"  No known {regulator_label.lower()}s at this timepoint.")

        parts.append(f"  Total PTMs: {len(ptms)} ({len(known_ptms)} with known {regulator_label.lower()}, {len(unknown_ptms)} unknown)")

        # Show motif predictions for unknown PTMs
        if unknown_ptms:
            motif_summary: Dict[str, int] = defaultdict(int)
            for p in unknown_ptms:
                for mf in p["motif_families"]:
                    motif_summary[mf] += 1
            if motif_summary:
                top_motifs = sorted(motif_summary.items(), key=lambda x: x[1], reverse=True)[:5]
                motif_str = ", ".join(f"{k} ({v})" for k, v in top_motifs)
                parts.append(f"  Top motif-predicted families for unknown PTMs: {motif_str}")

        parts.append("")

    # ── Section B: Cross-timepoint kinase inference ──
    cross_inferences = cascade.get("cross_timepoint_inferences", [])
    if cross_inferences:
        parts.append(f"### B. Cross-Timepoint {regulator_label} Inference")
        parts.append("")
        parts.append(
            f"CRITICAL INSIGHT: {regulator_label}s confirmed at later timepoints can explain "
            f"PTM events at earlier timepoints. If a {regulator_label.lower()} is known to phosphorylate "
            f"substrates at 20 min, and PTMs with matching motifs appear at 5 min, "
            f"this suggests the {regulator_label.lower()} was already active at 5 min — "
            f"its activity preceded the peak of its substrates."
        )
        parts.append("")

        # Group inferences by target timepoint
        tp_inferences: Dict[str, list] = defaultdict(list)
        for inf in cross_inferences:
            tp_inferences[inf["target_timepoint"]].append(inf)

        for tp in tp_order:
            if tp not in tp_inferences:
                continue
            infs = tp_inferences[tp]
            parts.append(f"  **{tp}** — {len(infs)} inferred {regulator_label.lower()} assignment(s):")
            # Deduplicate by kinase
            seen_kinases: Dict[str, list] = defaultdict(list)
            for inf in infs:
                seen_kinases[inf["inferred_canonical"]].append(inf)
            for canon, inf_list in seen_kinases.items():
                inf0 = inf_list[0]
                ptm_list = [i["target_ptm"] for i in inf_list]
                parts.append(
                    f"    - {inf0['inferred_kinase']} (confirmed at {', '.join(inf0['evidence_timepoints'])}): "
                    f"inferred for {len(ptm_list)} PTMs ({', '.join(ptm_list[:5])})"
                )
                parts.append(f"      Evidence: {inf0['reasoning']}")
            parts.append("")

    # ── Section C: Persistent kinases (active across multiple timepoints) ──
    persistent = cascade.get("persistent_kinases", {})
    if persistent:
        parts.append(f"### C. Persistent {regulator_label}s (active across multiple timepoints)")
        parts.append("")
        parts.append(
            f"These {regulator_label.lower()}s were identified at 2+ timepoints, "
            f"suggesting sustained signaling activity:"
        )
        parts.append("")
        for canon, tps in sorted(persistent.items(), key=lambda x: len(x[1]), reverse=True):
            # Get display name from first occurrence
            display = canon
            for tp in tps:
                if canon in tp_map[tp]["kinases"]:
                    display = tp_map[tp]["kinases"][canon]["kinase"]
                    break
            tp_str = " → ".join(tps)
            parts.append(f"  - {display} ({canon}): active at {tp_str} ({len(tps)} timepoints)")
        parts.append("")

    # ── Section D: Signaling cascade flow summary ──
    parts.append(f"### D. Cell Signaling Cascade Flow")
    parts.append("")
    parts.append(
        "Based on the temporal kinase landscape and cross-timepoint inference, "
        "the following signaling cascade flow is proposed:"
    )
    parts.append("")

    flow_parts = []
    for i, tp in enumerate(tp_order):
        tp_data = tp_map[tp]
        kinases = tp_data["kinases"]
        minutes = tp_data["minutes"]

        if kinases:
            kinase_entries = []
            for canon, info in sorted(kinases.items(), key=lambda x: len(x[1]["confirmed_ptms"]), reverse=True):
                eg = evidence_grades.get(canon, {})
                grade = eg.get("grade", "Inferred")
                kinase_entries.append(f"{info['kinase']}({grade[0]})")
            kinase_str = ", ".join(kinase_entries[:5])
            if len(kinase_entries) > 5:
                kinase_str += f" (+{len(kinase_entries) - 5})"
            kinase_names = [info["kinase"] for _, info in sorted(kinases.items(), key=lambda x: len(x[1]["confirmed_ptms"]), reverse=True)]
        else:
            # Use cross-timepoint inferences for this timepoint
            inferred_at_tp = set()
            for inf in cross_inferences:
                if inf["target_timepoint"] == tp:
                    inferred_at_tp.add(inf["inferred_kinase"])
            if inferred_at_tp:
                kinase_str = ", ".join(sorted(inferred_at_tp)[:5]) + " (inferred)"
            else:
                kinase_str = "unknown"

        flow_parts.append(f"{tp} [{kinase_str}]")

    parts.append("  " + " → ".join(flow_parts))
    parts.append("")

    # ── Section E: Per-cluster detailed kinase annotation ──
    parts.append(f"### E. Per-Cluster {regulator_label} Annotation Detail")
    parts.append("")

    for ca, cl in zip(cluster_annotations, clusters):
        cid = ca["cluster_id"]
        peak = ca["peak_timepoint"]
        pattern = ca["pattern"]
        n_members = ca["member_count"]
        n_known = ca["total_known"]
        n_motif = ca["total_motif"]
        n_novel = len(ca["novel_candidates"])

        parts.append(f"**Cluster {cid}** (peak: {peak}, pattern: {pattern}, {n_members} PTMs):")
        parts.append(
            f"  {n_known} PTMs with known {regulator_label.lower()}, "
            f"{n_motif} motif-only, {n_novel} novel candidates"
        )

        if ca["anchor_kinases"]:
            parts.append(f"  Anchor {regulator_label}s:")
            for canon, info in ca["anchor_kinases"].items():
                sources = ", ".join(info["sources"])
                eg = evidence_grades.get(canon, {})
                grade = eg.get("grade", "Inferred")
                parts.append(
                    f"    - {info['kinase']} ({canon}): "
                    f"{len(info['confirmed_ptms'])} confirmed substrates, "
                    f"sources: [{sources}], Evidence: {grade}"
                )

        if ca["inferred_assignments"]:
            parts.append(f"  Inferred {regulator_label} Assignments:")
            for inf in ca["inferred_assignments"][:10]:
                parts.append(
                    f"    - {inf['ptm']} → {inf['inferred_kinase']} "
                    f"(motif match within co-wave group)"
                )

        if ca["novel_candidates"]:
            parts.append(f"  Novel Candidates (no matching anchor {regulator_label.lower()}):")
            for nc in ca["novel_candidates"][:5]:
                motif_str = ", ".join(nc["motif_families"][:3]) if nc["motif_families"] else "none"
                parts.append(f"    - {nc['ptm']} (motif predictions: {motif_str})")

        parts.append("")

    # ── LLM Instructions ──
    parts.append(f"### INSTRUCTIONS FOR INTERPRETING TEMPORAL {regulator_label.upper()} CASCADE")
    parts.append("")
    parts.append(
        f"1. USE THE TEMPORAL {regulator_label.upper()} LANDSCAPE to explain the signaling cascade:\n"
        f"   - Start with the earliest timepoint and describe which {regulator_label.lower()}s are active.\n"
        f"   - Explain how early {regulator_label.lower()} activity leads to downstream effects at later timepoints.\n"
        f"   - Use cross-timepoint inference to connect early PTM events to later confirmed {regulator_label.lower()}s.\n"
    )
    parts.append(
        f"2. HIGHLIGHT PERSISTENT {regulator_label.upper()}S:\n"
        f"   - {regulator_label}s active across multiple timepoints suggest sustained signaling.\n"
        f"   - Discuss their biological significance and potential feedback loops.\n"
    )
    parts.append(
        f"3. EXPLAIN THE SIGNALING CASCADE FLOW:\n"
        f"   - Use the proposed cascade flow (Section D) as a framework.\n"
        f"   - For each transition (e.g., 5min → 20min), explain what biological events\n"
        f"     connect the {regulator_label.lower()} activities at adjacent timepoints.\n"
        f"   - Consider known signaling pathways (e.g., MAPK cascade, PI3K/AKT pathway)\n"
        f"     that could explain the observed temporal pattern.\n"
    )
    parts.append(
        f"4. CROSS-TIMEPOINT INFERENCE IS KEY:\n"
        f"   - When a {regulator_label.lower()} is confirmed at 20min but PTMs with matching motifs\n"
        f"     appear at 5min, this is strong evidence for early {regulator_label.lower()} activation.\n"
        f"   - Discuss the biological plausibility of this inference.\n"
    )
    parts.append(
        f"5. INTEGRATE WITH CO-MOVEMENT ANALYSIS:\n"
        f"   - The {regulator_label.lower()} cascade data complements the co-movement cluster analysis.\n"
        f"   - Use both to build a coherent narrative of the signaling response.\n"
    )
    parts.append(
        f"6. EVIDENCE STRENGTH GRADING (v9.35):\n"
        f"   Each {regulator_label.lower()}-substrate relationship has an evidence grade:\n"
        f"   - **Strong** (★★★): Confirmed by 2+ independent sources (database + literature + motif),\n"
        f"     or 1 high-confidence source with PMID + concordant motif prediction.\n"
        f"     These relationships should be presented as HIGH-CONFIDENCE findings.\n"
        f"   - **Moderate** (★★☆): Supported by 1 high-confidence source or 2+ medium sources.\n"
        f"     Present as SUPPORTED findings with appropriate caveats.\n"
        f"   - **Inferred** (★☆☆): Based on motif prediction or low-confidence sources only.\n"
        f"     Present as PREDICTED relationships requiring further validation.\n"
        f"   IMPORTANT: When describing each {regulator_label.lower()}-substrate cascade in the report,\n"
        f"   you MUST explicitly state the evidence grade (e.g., 'MAPK1 phosphorylation of ELK1\n"
        f"   (Evidence: Strong) was confirmed by...').\n"
    )

    # v9.35: Evidence Summary Table
    if evidence_grades:
        parts.append(f"\n### F. Evidence Strength Summary Table")
        parts.append("")
        parts.append(f"| {regulator_label} | Grade | Sources | Confirmed | Inferred | Concordance |")
        parts.append("|---|---|---|---|---|---|")
        for canon, eg in sorted(
            evidence_grades.items(),
            key=lambda x: ({"Strong": 0, "Moderate": 1, "Inferred": 2}.get(x[1]["grade"], 3), -x[1]["n_confirmed"]),
        ):
            sources_str = ", ".join(sorted(eg["sources"]))[:50]
            conc = f"{eg['concordance_ratio']:.0%}" if eg.get("concordance_ratio") else "N/A"
            parts.append(
                f"| {eg['kinase']} ({canon}) | {eg['grade']} | {sources_str} | "
                f"{eg['n_confirmed']} | {eg['n_inferred']} | {conc} |"
            )
        parts.append("")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# v9.12: FRONTEND GLOBAL KINASE MODULES → LLM CONTEXT
# ═══════════════════════════════════════════════════════════════════════════

def _build_frontend_kinase_llm_context(frontend_kinase: dict, ptm_type: str, kinase_activity_heatmap: dict = None) -> str:
    """Build structured LLM context from the frontend Global Kinase Modules analysis.

    This supplements the pipeline-internal kinase annotation with the more
    comprehensive 8-source analysis performed interactively by the user.

    Args:
        frontend_kinase: Result from global_kinase_modules API
            {kinase_modules, temporal_cascade, cowave_cross_analysis, summary, saved_at}
        ptm_type: 'phosphorylation' or 'ubiquitylation'
        kinase_activity_heatmap: Optional heatmap data from DB
            {kinase_scores, conditions, peak_sync, cowave_groups}

    Returns:
        Structured markdown string for LLM injection
    """
    if not frontend_kinase:
        return ""

    regulator_label = "E3 Ligase" if ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
    kinase_modules = frontend_kinase.get("kinase_modules", [])
    temporal_cascade = frontend_kinase.get("temporal_cascade", {})
    summary = frontend_kinase.get("summary", {})
    saved_at = frontend_kinase.get("saved_at", "")

    if not kinase_modules:
        return ""

    parts = [
        f"\n## GLOBAL {regulator_label.upper()} MODULE ANALYSIS (User-Performed, 8-Source Integration)",
        "",
        f"The following {regulator_label.lower()} module analysis was performed interactively using "
        f"8 independent annotation sources: LLM-based prediction, literature kinase-substrate pairs, "
        f"upstream regulators, iPTMnet database, text mining, abstract NER, STRING PPI, and motif prediction.",
        "",
    ]

    if saved_at:
        parts.append(f"*Analysis performed: {saved_at[:10]}*")
        parts.append("")

    # ── Section A: Summary statistics ──
    parts.append(f"### A. Analysis Summary")
    parts.append("")
    total_km = summary.get("total_kinase_modules", len(kinase_modules))
    total_confirmed = summary.get("total_confirmed", 0)
    total_inferred = summary.get("total_inferred", 0)
    parts.append(
        f"- Total {regulator_label} Modules identified: **{total_km}**\n"
        f"- Confirmed substrate assignments: **{total_confirmed}**\n"
        f"- Inferred substrate assignments: **{total_inferred}**"
    )
    parts.append("")

    # ── Section B: Top kinase modules ──
    parts.append(f"### B. Top {regulator_label} Modules (by substrate count)")
    parts.append("")

    for km in kinase_modules[:15]:  # Top 15 kinase modules
        kinase_name = km.get("kinase", "Unknown")
        canonical = km.get("canonical", kinase_name)
        sources = km.get("sources", [])
        source_count = km.get("source_count", len(sources))
        confirmed = km.get("confirmed_count", 0)
        inferred = km.get("inferred_count", 0)
        total = km.get("total_count", confirmed + inferred)
        members = km.get("members", [])

        # Build member summary (top 8 substrates)
        member_names = []
        for m in members[:8]:
            gene = m.get("gene", "")
            pos = m.get("position", "")
            if gene and pos:
                member_names.append(f"{gene}_{pos}")
            elif gene:
                member_names.append(gene)
        member_str = ", ".join(member_names)
        if len(members) > 8:
            member_str += f" (+{len(members) - 8} more)"

        sources_str = ", ".join(sources[:5])
        parts.append(
            f"**{kinase_name}** (canonical: {canonical}) — "
            f"{total} substrates ({confirmed} confirmed, {inferred} inferred), "
            f"{source_count} sources: [{sources_str}]"
        )
        if member_str:
            parts.append(f"  Substrates: {member_str}")
        parts.append("")

    # ── Section C: Temporal cascade from frontend ──
    tc_timepoints = temporal_cascade.get("timepoints", [])
    if tc_timepoints:
        parts.append(f"### C. Temporal {regulator_label} Activation Order")
        parts.append("")
        parts.append(
            f"Based on co-wave module peak timepoints, the {regulator_label.lower()} activation "
            f"order is as follows:"
        )
        parts.append("")

        # Build cascade flow string
        flow_parts = []
        for tp_data in tc_timepoints:
            tp_label = tp_data.get("timepoint", "")
            active_kinases = tp_data.get("active_kinases", [])
            if active_kinases:
                k_names = [k.get("kinase", k) if isinstance(k, dict) else str(k) for k in active_kinases[:4]]
                k_str = ", ".join(k_names)
                if len(active_kinases) > 4:
                    k_str += f" (+{len(active_kinases) - 4})"
                flow_parts.append(f"{tp_label} [{k_str}]")
            else:
                flow_parts.append(f"{tp_label} [unknown]")

        parts.append("  " + " → ".join(flow_parts))
        parts.append("")

        # Per-timepoint detail
        for tp_data in tc_timepoints:
            tp_label = tp_data.get("timepoint", "")
            active_kinases = tp_data.get("active_kinases", [])
            ptm_count = tp_data.get("ptm_count", 0)
            module_count = tp_data.get("module_count", 0)

            parts.append(f"**{tp_label}** ({ptm_count} PTMs, {module_count} modules):")
            if active_kinases:
                for k in active_kinases[:6]:
                    if isinstance(k, dict):
                        k_name = k.get("kinase", "")
                        k_confirmed = k.get("confirmed", 0)
                        k_inferred = k.get("inferred", 0)
                        parts.append(f"  - {k_name}: {k_confirmed} confirmed, {k_inferred} inferred")
                    else:
                        parts.append(f"  - {k}")
            parts.append("")

    # ── Section D: Cascade flow transitions ──
    cascade_flow = temporal_cascade.get("cascade_flow", [])
    if cascade_flow:
        parts.append(f"### D. {regulator_label} Transition Between Timepoints")
        parts.append("")
        for flow in cascade_flow:
            from_tp = flow.get("from_timepoint", "")
            to_tp = flow.get("to_timepoint", "")
            persistent = flow.get("persistent_kinases", [])
            new_kinases = flow.get("new_kinases", [])
            lost_kinases = flow.get("lost_kinases", [])

            parts.append(f"**{from_tp} → {to_tp}:**")
            if persistent:
                parts.append(f"  Persistent: {', '.join(persistent[:5])}")
            if new_kinases:
                parts.append(f"  Newly activated: {', '.join(new_kinases[:5])}")
            if lost_kinases:
                parts.append(f"  Deactivated: {', '.join(lost_kinases[:5])}")
            parts.append("")

    # ── Section D2: Co-Wave Module × Kinase Module Cross-Analysis ──
    cowave_cross = frontend_kinase.get("cowave_cross_analysis", {})
    if cowave_cross:
        parts.append(f"### D2. Co-Wave PTM Module × {regulator_label} Module Cross-Analysis")
        parts.append("")
        parts.append(
            f"This section maps which {regulator_label.lower()}s are responsible for phosphorylating "
            f"PTMs within each temporal Co-Wave module. Overlaps indicate that a {regulator_label.lower()} "
            f"is driving the coordinated temporal pattern of an entire PTM cluster."
        )
        parts.append("")

        for cw_id, cw_data in sorted(cowave_cross.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            cw_label = cw_data.get("cowave_label", f"Module {cw_id}")
            total_ptms = cw_data.get("total_ptms", 0)
            overlapping = cw_data.get("overlapping_kinases", [])
            if not overlapping:
                continue

            parts.append(f"**{cw_label}** ({total_ptms} PTMs):")
            for ok in sorted(overlapping, key=lambda x: x.get("shared_count", 0), reverse=True)[:5]:
                k_name = ok.get("kinase", ok.get("canonical", ""))
                shared = ok.get("shared_count", 0)
                parts.append(f"  - {k_name}: {shared} shared substrates")
            parts.append("")

        parts.append(
            f"*Interpretation: {regulator_label}s with high substrate overlap in a Co-Wave module "
            f"are likely the primary drivers of that module's temporal pattern. Multiple "
            f"{regulator_label.lower()}s sharing substrates in the same module suggest convergent "
            f"signaling or sequential phosphorylation events.*"
        )
        parts.append("")

    # ── Section E: Co-Wave Kinase Groups (CW Groups) ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("cowave_groups"):
        cowave_groups = kinase_activity_heatmap["cowave_groups"]
        parts.append(f"### E. Co-Wave {regulator_label} Groups (Temporal Correlation Clusters)")
        parts.append("")
        parts.append(
            f"{regulator_label}s were grouped by temporal substrate activity correlation (Pearson r ≥ 0.7). "
            f"{regulator_label}s within the same Co-Wave Group exhibit highly correlated substrate "
            f"phosphorylation dynamics across all measured timepoints, suggesting they participate "
            f"in the same signaling cascade or are co-activated by a common upstream signal."
        )
        parts.append("")
        parts.append(f"**Total CW Groups: {len(cowave_groups)}**")
        parts.append("")

        for grp in cowave_groups:
            gid = grp.get("group_id", "?")
            kinases = grp.get("kinases", [])
            size = grp.get("size", len(kinases))
            mean_corr = grp.get("mean_correlation", 0)
            dominant_peak = grp.get("dominant_peak", "unknown")
            k_str = ", ".join(kinases[:8])
            if len(kinases) > 8:
                k_str += f" (+{len(kinases) - 8} more)"
            parts.append(
                f"**CW Group G{gid}** — {size} {regulator_label.lower()}s, "
                f"mean r={mean_corr:.2f}, dominant peak: {dominant_peak}"
            )
            parts.append(f"  Members: {k_str}")
            parts.append("")

        parts.append(
            f"*Biological interpretation: {regulator_label}s in the same CW Group are likely "
            f"co-regulated — either by a shared upstream activator, or as sequential members "
            f"of a tightly coupled signaling relay. Groups peaking at the same timepoint "
            f"represent parallel signaling branches activated simultaneously.*"
        )
        parts.append("")

    # ── Section F: Per-Condition Kinase Activity Scores ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("kinase_scores"):
        ks_list = kinase_activity_heatmap["kinase_scores"]
        conditions = kinase_activity_heatmap.get("conditions", [])
        parts.append(f"### F. {regulator_label} Activity Scores (Weighted Mean Log2FC per Condition)")
        parts.append("")
        parts.append(
            f"Each {regulator_label.lower()}'s activity score represents the weighted mean Log2FC "
            f"of its substrate PTMs at each timepoint. Weights are based on annotation confidence "
            f"(confirmed substrates weighted higher than inferred). Direction indicates whether "
            f"the {regulator_label.lower()} is predominantly activating (substrates up-phosphorylated) "
            f"or being inactivated (substrates de-phosphorylated)."
        )
        parts.append("")

        # Top 25 kinases by absolute peak score
        sorted_ks = sorted(ks_list, key=lambda x: abs(x.get("peak_score", 0)), reverse=True)
        for ks in sorted_ks[:25]:
            kinase_name = ks.get("kinase", "")
            sub_count = ks.get("substrate_count", 0)
            confidence = ks.get("confidence", 0)
            peak_cond = ks.get("peak_condition", "")
            peak_score = ks.get("peak_score", 0)
            direction = ks.get("direction", "neutral")
            coherence = ks.get("coherence", 0)
            cw_group = ks.get("cowave_group", -1)
            cw_str = f"CW-G{cw_group}" if cw_group >= 0 else "ungrouped"

            # Per-condition scores (compact)
            scores = ks.get("scores", {})
            score_parts = []
            for c in conditions[:6]:  # Max 6 conditions
                v = scores.get(c, 0)
                if abs(v) >= 0.01:
                    score_parts.append(f"{c}:{v:+.2f}")
            score_str = ", ".join(score_parts) if score_parts else "flat"

            # v10.1: Include temporal pattern classification
            temporal_pattern = ks.get("temporal_pattern", "")
            pattern_str = f", pattern={temporal_pattern}" if temporal_pattern else ""

            # v11.3.2: Nuclear evidence
            nuclear_ev = ks.get("nuclear_evidence", {})
            nuc_str = ""
            if nuclear_ev and nuclear_ev.get("score", 0) > 0:
                t1_genes = nuclear_ev.get("tier1_genes", [])
                t2_genes = nuclear_ev.get("tier2_genes", [])
                nuc_parts = []
                if t1_genes:
                    nuc_parts.append(f"NucT1[{','.join(t1_genes[:5])}]")
                if t2_genes:
                    nuc_parts.append(f"NucT2[{','.join(t2_genes[:5])}]")
                nuc_str = f", nuclear_evidence={nuclear_ev.get('score', 0)} ({' '.join(nuc_parts)})"

            # v11.3.3: Self-PTM inline summary
            self_ptm_list = ks.get("self_ptm") or []
            self_ptm_str = ""
            if self_ptm_list:
                sp_parts = []
                for sp in self_ptm_list[:3]:
                    sp_parts.append(
                        f"{sp.get('site', '')}(r={sp.get('correlation_with_activity', 0):+.2f},{sp.get('relationship', '')})"
                    )
                self_ptm_str = f", self_ptm=[{'; '.join(sp_parts)}]"

            parts.append(
                f"**{kinase_name}** [{cw_str}] — {sub_count} substrates, "
                f"conf={confidence:.0%}, peak={peak_cond} ({peak_score:+.2f}), "
                f"direction={direction}, coherence={coherence:.2f}{pattern_str}{nuc_str}{self_ptm_str}"
            )
            parts.append(f"  Temporal profile: [{score_str}]")
            parts.append("")

    # ── Section F2: Temporal Pattern Summary ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("all_patterns"):
        all_patterns = kinase_activity_heatmap["all_patterns"]
        parts.append(f"### F2. {regulator_label} Temporal Pattern Classification")
        parts.append("")
        parts.append(
            f"Each {regulator_label.lower()} was automatically classified into temporal activation "
            f"patterns based on its activity score trajectory across all measured conditions. "
            f"These patterns identify biologically significant behaviors such as sudden emergence, "
            f"direction reversal, transient spikes, or progressive amplification/decay."
        )
        parts.append("")

        # Group kinases by pattern
        from collections import defaultdict as _defaultdict
        pattern_groups = _defaultdict(list)
        for kinase_name_p, patterns_list in all_patterns.items():
            if isinstance(patterns_list, list):
                for pat in patterns_list:
                    pattern_groups[pat].append(kinase_name_p)
            elif isinstance(patterns_list, str):
                pattern_groups[patterns_list].append(kinase_name_p)

        # Sort by number of kinases in each pattern
        for pat, kinases_in_pat in sorted(pattern_groups.items(), key=lambda x: len(x[1]), reverse=True):
            k_str = ", ".join(kinases_in_pat[:10])
            if len(kinases_in_pat) > 10:
                k_str += f" (+{len(kinases_in_pat) - 10} more)"
            parts.append(f"**{pat}** ({len(kinases_in_pat)} {regulator_label.lower()}s): {k_str}")
        parts.append("")

        parts.append(
            f"*Interpretation: Temporal patterns reveal the dynamic behavior of {regulator_label.lower()} "
            f"activation. 'Emergence' patterns indicate newly activated signaling nodes at specific "
            f"timepoints. 'Reversal' patterns suggest feedback regulation or pathway switching. "
            f"'Spike' patterns indicate transient signaling bursts. 'Sustained' patterns represent "
            f"persistent signaling that drives long-term cellular responses.*"
        )
        parts.append("")

    # ── Section G: Peak Synchronization Events ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("peak_sync"):
        peak_sync = kinase_activity_heatmap["peak_sync"]
        parts.append(f"### G. Peak Synchronization Events (≥3 {regulator_label}s Peaking Simultaneously)")
        parts.append("")
        parts.append(
            f"Timepoints where multiple {regulator_label.lower()}s reach peak substrate activity "
            f"simultaneously indicate major signaling activation events — potential therapeutic "
            f"intervention windows or critical decision points in the cellular response."
        )
        parts.append("")

        for cond, data in sorted(peak_sync.items(), key=lambda x: x[1].get("count", 0), reverse=True):
            count = data.get("count", 0)
            kinases = data.get("kinases", [])
            k_str = ", ".join(kinases[:10])
            if len(kinases) > 10:
                k_str += f" (+{len(kinases) - 10} more)"
            parts.append(f"**{cond}** — {count} {regulator_label.lower()}s peak simultaneously:")
            parts.append(f"  {k_str}")
            parts.append("")

    # ── Section G2: Nuclear-Exclusive Substrate Evidence Summary ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("kinase_scores"):
        ks_list = kinase_activity_heatmap["kinase_scores"]
        nuc_kinases = [
            ks for ks in ks_list
            if ks.get("nuclear_evidence", {}).get("score", 0) > 0
            and not ks.get("is_sub_pattern")
        ]
        if nuc_kinases:
            parts.append(f"### G2. Nuclear-Exclusive Substrate Evidence")
            parts.append("")
            parts.append(
                f"The following {regulator_label.lower()}s have substrates that are exclusively or "
                f"predominantly localized in the nucleus. This provides direct biochemical evidence "
                f"that these {regulator_label.lower()}s were active inside the nucleus during the "
                f"experimental conditions. Tier 1 markers (histones, lamins, PCNA, PARP1, DNA-PKcs, "
                f"RNA Pol II) never leave the nucleus. Tier 2 markers (splicing factors, chromatin "
                f"remodelers, transcription factors) are predominantly nuclear."
            )
            parts.append("")
            parts.append("Scoring: Tier1 substrates = 2 points each, Tier2 = 1 point each.")
            parts.append("")
            # Sort by nuclear evidence score
            for ks in sorted(nuc_kinases, key=lambda x: x.get("nuclear_evidence", {}).get("score", 0), reverse=True)[:20]:
                ne = ks.get("nuclear_evidence", {})
                kinase_name = ks.get("kinase", "")
                t1_genes = ne.get("tier1_genes", [])
                t2_genes = ne.get("tier2_genes", [])
                t1_str = f"T1: {', '.join(t1_genes[:8])}" if t1_genes else ""
                t2_str = f"T2: {', '.join(t2_genes[:8])}" if t2_genes else ""
                gene_str = "; ".join(filter(None, [t1_str, t2_str]))
                parts.append(
                    f"**{kinase_name}** — Nuclear Score: {ne.get('score', 0)} "
                    f"(T1={ne.get('tier1_count', 0)}, T2={ne.get('tier2_count', 0)}) "
                    f"[{gene_str}]"
                )
            parts.append("")

    # ── Section G3: Regulator Self-PTM Temporal Tracking ──
    if kinase_activity_heatmap and kinase_activity_heatmap.get("kinase_scores"):
        ks_list_sp = kinase_activity_heatmap["kinase_scores"]
        self_ptm_kinases = [
            ks for ks in ks_list_sp
            if ks.get("self_ptm") and not ks.get("is_sub_pattern")
        ]
        if self_ptm_kinases:
            parts.append(f"### G3. {regulator_label} Self-PTM Temporal Tracking")
            parts.append("")
            parts.append(
                f"The following {regulator_label.lower()}s have their own PTM sites detected in the "
                f"experimental data. By comparing the temporal profile of these self-PTM changes "
                f"with the substrate-inferred activity profile, we can validate the activity "
                f"inference and identify activation/inhibitory phosphorylation sites. "
                f"Concordant (r≥0.7) sites likely represent activation marks. "
                f"Discordant (r≤-0.7) sites may represent inhibitory marks or feedback regulation."
            )
            parts.append("")
            # Sort by number of self-PTM sites
            for ks in sorted(self_ptm_kinases, key=lambda x: len(x.get("self_ptm", [])), reverse=True)[:20]:
                kinase_name_sp = ks.get("kinase", "")
                self_ptms = ks.get("self_ptm", [])
                parts.append(f"**{kinase_name_sp}** — {len(self_ptms)} self-PTM site(s) detected:")
                for sp in self_ptms[:5]:
                    r_val = sp.get('correlation_with_activity', 0)
                    rel = sp.get('relationship', 'independent')
                    ts_str = ", ".join(f"{c}:{v:+.2f}" for c, v in sp.get('timeseries', {}).items())
                    parts.append(
                        f"  {sp.get('ptm_key', '')} — peak@{sp.get('peak_condition', '')} "
                        f"({sp.get('peak_fc', 0):+.2f}), r={r_val:+.3f} ({rel})"
                    )
                    parts.append(f"    Temporal: [{ts_str}]")
                if len(self_ptms) > 5:
                    parts.append(f"  (+{len(self_ptms) - 5} more sites)")
                parts.append("")

    # ── Section H: Non-PTM Effector Proteins (Downstream Functional Outputs) ──
    effector_proteins = frontend_kinase.get("effector_proteins", [])
    if effector_proteins:
        parts.append(f"### H. Non-PTM Effector Proteins (Downstream Functional Outputs)")
        parts.append("")
        parts.append(
            f"These are proteins identified as downstream functional effectors of the "
            f"active {regulator_label.lower()}s. They represent the biological output of the "
            f"signaling cascade — transcription factors, metabolic enzymes, structural proteins, "
            f"or other functional mediators that translate kinase activity into cellular responses."
        )
        parts.append("")

        for eff in effector_proteins[:20]:  # Top 20 effectors
            eff_name = eff.get("name", eff.get("gene", ""))
            eff_function = eff.get("function", eff.get("category", ""))
            upstream_kinases = eff.get("upstream_kinases", [])
            confidence = eff.get("confidence", 0)
            uk_str = ", ".join(upstream_kinases[:4]) if upstream_kinases else "unknown"
            if len(upstream_kinases) > 4:
                uk_str += f" (+{len(upstream_kinases) - 4})"
            parts.append(
                f"**{eff_name}** — {eff_function}, "
                f"upstream: [{uk_str}], conf={confidence:.0%}"
            )
        parts.append("")

    # ── LLM Instructions ──
    parts.append(f"### INSTRUCTIONS FOR USING GLOBAL {regulator_label.upper()} MODULE DATA")
    parts.append("")
    parts.append(
        f"1. INTEGRATE KINASE MODULES WITH TEMPORAL DATA:\n"
        f"   - Use the {regulator_label} Module data above to identify the key signaling regulators.\n"
        f"   - Cross-reference with the temporal activation order to build a coherent cascade narrative.\n"
        f"   - Prioritize {regulator_label.lower()}s with high substrate counts and multiple source evidence.\n"
    )
    parts.append(
        f"2. EXPLAIN SUBSTRATE SPECIFICITY:\n"
        f"   - For each major {regulator_label.lower()}, explain why it phosphorylates its specific substrates.\n"
        f"   - Connect substrate identities to their biological functions in the signaling context.\n"
    )
    parts.append(
        f"3. TEMPORAL NARRATIVE:\n"
        f"   - Use the temporal activation order (Section C) to describe early vs. late signaling events.\n"
        f"   - Explain how {regulator_label.lower()} activity at early timepoints primes downstream responses.\n"
        f"   - Discuss {regulator_label.lower()}s active across multiple timepoints as sustained regulators.\n"
    )
    parts.append(
        f"4. CROSS-VALIDATE WITH PIPELINE ANALYSIS:\n"
        f"   - The Global {regulator_label} Modules data was computed from all significant PTMs.\n"
        f"   - The pipeline-internal cascade (above) was computed from co-wave clusters only.\n"
        f"   - Where both analyses agree, this represents high-confidence signaling events.\n"
        f"   - Discrepancies may indicate context-specific or cluster-specific regulation.\n"
    )
    parts.append(
        f"5. CO-WAVE GROUP INTERPRETATION:\n"
        f"   - {regulator_label}s in the same CW Group have highly correlated substrate activity (r≥0.7).\n"
        f"   - Interpret CW Groups as functional signaling units — co-activated kinase cassettes.\n"
        f"   - Explain WHY these {regulator_label.lower()}s are co-regulated (shared upstream receptor, \n"
        f"     common scaffold protein, or sequential cascade members).\n"
        f"   - Use Peak Synchronization events (Section G) to identify major signaling activation waves.\n"
    )
    parts.append(
        f"6. ACTIVITY SCORE INTERPRETATION:\n"
        f"   - Use per-condition scores (Section F) to describe the temporal dynamics of each {regulator_label.lower()}.\n"
        f"   - 'Activation' direction = substrates are up-phosphorylated = kinase is active.\n"
        f"   - 'Inactivation' direction = substrates are de-phosphorylated = phosphatase action or kinase suppression.\n"
        f"   - High coherence (>0.5) = substrates move together = high-confidence activity measurement.\n"
        f"   - Low coherence (<0.3) = substrates are heterogeneous = possible multi-functional kinase.\n"
    )
    parts.append(
        f"7. EFFECTOR PROTEIN NARRATIVE:\n"
        f"   - Use Non-PTM Effector Proteins (Section H) to explain the FUNCTIONAL OUTPUT of the signaling.\n"
        f"   - Connect upstream {regulator_label.lower()} activity to downstream cellular responses.\n"
        f"   - Explain how the kinase cascade ultimately affects cell fate, metabolism, or gene expression.\n"
    )
    parts.append(
        f"8. CROSS-ANALYSIS (PTM Module × {regulator_label} Module):\n"
        f"   - Use Section D2 to explain which {regulator_label.lower()}s drive each Co-Wave PTM module.\n"
        f"   - High substrate overlap = that {regulator_label.lower()} is the primary driver of the module's temporal pattern.\n"
        f"   - Multiple {regulator_label.lower()}s sharing substrates in one module = convergent signaling.\n"
    )

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# v9.13: AUTO-BUILD GLOBAL KINASE MODULES FROM ENRICHED PTM DATA
# ═══════════════════════════════════════════════════════════════════════════

def _build_global_kinase_modules(
    enriched_data: list,
    cluster_annotations: list,
    clusters: list,
    motif_db: dict,
    ptm_type: str,
) -> dict:
    """Build kinase-centric modules from ALL enriched_ptm_data.

    This replicates the logic of the frontend 'Global Kinase Modules' API
    (orders.py::global_kinase_modules) but runs inside the pipeline worker,
    so no manual user action is required.

    Args:
        enriched_data: Full enriched_ptm_data list from state
        cluster_annotations: Per-cluster annotation results (from Step 1)
        clusters: Co-wave cluster list (for temporal cascade)
        motif_db: PHOSPHO_MOTIF_DB or UBI_MOTIF_DB
        ptm_type: 'phosphorylation' or 'ubiquitylation'

    Returns:
        Dict with keys: kinase_modules, temporal_cascade, summary
        (same structure as global_kinase_modules API response)
    """
    enriched_map = _build_enriched_map(enriched_data)

    # ── Step A: Annotate ALL PTMs (not just cluster members) ─────────────
    # Collect gene+position from enriched_data
    all_ptm_entries = []
    for ed in enriched_data:
        gene = (ed.get("gene") or ed.get("Gene.Name", "")).strip()
        pos = ed.get("position") or ed.get("PTM_Position", "")
        if gene and pos:
            all_ptm_entries.append((gene, str(pos), ed))

    # ── Step B: Build kinase-centric modules ─────────────────────────────
    kinase_members: Dict[str, dict] = {}  # canonical → {kinase, sources, confirmed, inferred}

    for gene, pos, enriched_entry in all_ptm_entries:
        ptm_key = f"{gene.upper()}_{str(pos).upper()}"

        # Collect known kinases (Sources 1-6)
        known = _collect_known_kinases_from_enriched(gene, pos, enriched_entry)

        for kk in known:
            canon = kk.get("canonical_name", "")
            display = kk.get("display_name", kk.get("kinase", ""))
            source = kk.get("source", "unknown")
            _KINASE_STOP_WORDS = {
                "OF", "THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM",
                "BY", "TO", "IN", "ON", "AT", "IS", "IT", "AS", "OR", "AN",
                "BE", "IF", "NO", "NOT", "BUT", "ALL", "CAN", "HAD", "HAS",
                "CELL", "GENE", "PROTEIN", "DOMAIN", "SITE", "TYPE", "ROLE",
                "ACTIVITY", "FUNCTION", "PATHWAY", "SIGNAL", "TARGET", "EFFECT",
                "RESULT", "LEVEL", "FACTOR", "COMPLEX", "FAMILY", "GROUP",
                "REGION", "SEQUENCE", "RESIDUE", "MOTIF", "SUBSTRATE",
            }
            if not canon or len(canon) < 3 or canon in _KINASE_STOP_WORDS:
                continue

            if canon not in kinase_members:
                kinase_members[canon] = {
                    "kinase": display,
                    "canonical": canon,
                    "sources": set(),
                    "confirmed": [],
                    "inferred": [],
                }
            kinase_members[canon]["sources"].add(source)
            if ptm_key not in [m["key"] for m in kinase_members[canon]["confirmed"]]:
                kinase_members[canon]["confirmed"].append({
                    "key": ptm_key,
                    "gene": gene.upper(),
                    "position": pos,
                    "membership": "confirmed",
                    "evidence": source,
                })

    # ── Step C: Infer kinases for PTMs without known kinase ──────────────
    for gene, pos, enriched_entry in all_ptm_entries:
        ptm_key = f"{gene.upper()}_{str(pos).upper()}"

        # Skip if already confirmed
        already_confirmed = any(
            ptm_key in [m["key"] for m in info["confirmed"]]
            for info in kinase_members.values()
        )
        if already_confirmed:
            continue

        # Motif prediction
        motif_pred = _predict_motif_kinases(pos, enriched_entry, motif_db)
        motif_families: Set[str] = set()
        for mp in motif_pred:
            for part in mp.get("canonical_family", "").split("/"):
                if part and len(part) >= 2:
                    motif_families.add(part)

        if not motif_families:
            continue

        # Match to existing kinase modules
        matched_kinases = []
        for canon in kinase_members:
            for mf in motif_families:
                if are_kinases_same_family(canon, mf):
                    matched_kinases.append(canon)
                    break

        if matched_kinases:
            best_canon = max(matched_kinases, key=lambda c: len(kinase_members[c]["confirmed"]))
            if ptm_key not in [m["key"] for m in kinase_members[best_canon]["inferred"]]:
                kinase_members[best_canon]["inferred"].append({
                    "key": ptm_key,
                    "gene": gene.upper(),
                    "position": pos,
                    "membership": "inferred",
                    "evidence": f"motif match ({', '.join(sorted(motif_families))})",
                })

    # ── Step D: Format kinase module list ────────────────────────────────
    kinase_module_list = []
    for canon, info in kinase_members.items():
        members = info["confirmed"] + info["inferred"]
        kinase_module_list.append({
            "kinase": info["kinase"],
            "canonical": canon,
            "sources": sorted(info["sources"]),
            "source_count": len(info["sources"]),
            "members": members,
            "confirmed_count": len(info["confirmed"]),
            "inferred_count": len(info["inferred"]),
            "total_count": len(members),
        })

    kinase_module_list.sort(key=lambda x: x["total_count"], reverse=True)

    # ── Step E: Build temporal cascade from cluster peak timepoints ───────
    temporal_cascade = {"timepoints": [], "kinase_activity": [], "cascade_flow": []}

    if clusters and cluster_annotations:
        # Build peak_timepoint → kinases map
        tp_kinase_map: Dict[str, dict] = {}

        for cluster, ca in zip(clusters, cluster_annotations):
            peak_tp = cluster.get("peak_timepoint", "")
            if not peak_tp:
                continue

            member_keys = set(md.get("key", "") for md in cluster.get("member_details", []))

            if peak_tp not in tp_kinase_map:
                tp_kinase_map[peak_tp] = {
                    "kinases": {},
                    "ptm_count": 0,
                    "module_count": 0,
                }

            tp_kinase_map[peak_tp]["ptm_count"] += len(member_keys)
            tp_kinase_map[peak_tp]["module_count"] += 1

            for km in kinase_module_list:
                km_keys = set(m["key"] for m in km["members"])
                shared = member_keys & km_keys
                if shared:
                    canon = km["canonical"]
                    if canon not in tp_kinase_map[peak_tp]["kinases"]:
                        tp_kinase_map[peak_tp]["kinases"][canon] = {
                            "kinase": km["kinase"],
                            "canonical": canon,
                            "sources": km["sources"],
                            "ptm_count": len(shared),
                            "confirmed": sum(1 for m in km["members"] if m["key"] in shared and m["membership"] == "confirmed"),
                            "inferred": sum(1 for m in km["members"] if m["key"] in shared and m["membership"] == "inferred"),
                        }
                    else:
                        tp_kinase_map[peak_tp]["kinases"][canon]["ptm_count"] += len(shared)

        # Sort timepoints chronologically
        sorted_tps = sorted(tp_kinase_map.keys(), key=lambda t: tp_to_minutes(t))

        temporal_cascade["timepoints"] = [
            {
                "timepoint": tp,
                "minutes": tp_to_minutes(tp),
                "ptm_count": tp_kinase_map[tp]["ptm_count"],
                "module_count": tp_kinase_map[tp]["module_count"],
                "active_kinases": sorted(
                    tp_kinase_map[tp]["kinases"].values(),
                    key=lambda k: k["ptm_count"],
                    reverse=True,
                ),
            }
            for tp in sorted_tps
        ]

        # Kinase activity swimlane
        all_kinase_tps: Dict[str, dict] = {}
        for tp_data in temporal_cascade["timepoints"]:
            for k in tp_data["active_kinases"]:
                canon = k["canonical"]
                if canon not in all_kinase_tps:
                    all_kinase_tps[canon] = {
                        "kinase": k["kinase"],
                        "canonical": canon,
                        "timepoints": [],
                    }
                all_kinase_tps[canon]["timepoints"].append({
                    "timepoint": tp_data["timepoint"],
                    "ptm_count": k["ptm_count"],
                    "confirmed": k.get("confirmed", 0),
                    "inferred": k.get("inferred", 0),
                })

        temporal_cascade["kinase_activity"] = sorted(
            all_kinase_tps.values(),
            key=lambda x: len(x["timepoints"]),
            reverse=True,
        )

        # Cascade flow between adjacent timepoints
        cascade_flow = []
        for i in range(len(sorted_tps) - 1):
            tp_a = sorted_tps[i]
            tp_b = sorted_tps[i + 1]
            kinases_a = set(tp_kinase_map[tp_a]["kinases"].keys())
            kinases_b = set(tp_kinase_map[tp_b]["kinases"].keys())
            cascade_flow.append({
                "from_timepoint": tp_a,
                "to_timepoint": tp_b,
                "persistent_kinases": sorted(kinases_a & kinases_b),
                "new_kinases": sorted(kinases_b - kinases_a),
                "lost_kinases": sorted(kinases_a - kinases_b),
            })

        temporal_cascade["cascade_flow"] = cascade_flow

    # ── Step F: Summary ───────────────────────────────────────────────────
    summary = {
        "total_ptms": len(all_ptm_entries),
        "total_kinase_modules": len(kinase_module_list),
        "total_confirmed": sum(km["confirmed_count"] for km in kinase_module_list),
        "total_inferred": sum(km["inferred_count"] for km in kinase_module_list),
        "top_kinases": [
            {"kinase": km["kinase"], "canonical": km["canonical"], "total": km["total_count"]}
            for km in kinase_module_list[:10]
        ],
    }

    return {
        "kinase_modules": kinase_module_list,
        "temporal_cascade": temporal_cascade,
        "summary": summary,
        "source": "pipeline_auto",  # Distinguish from frontend-computed
    }
