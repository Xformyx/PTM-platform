"""
Kinase Annotation Node — v9.11

Runs after temporal_comovement and before write_sections.
Collects kinase information from 8 sources for each co-wave cluster,
builds a temporal kinase cascade, performs cross-timepoint inference,
and generates structured LLM context for cell signaling interpretation.

Pipeline position:
    temporal_comovement → kinase_annotation → write_sections

Input (from state):
    - comovement_analysis: {clusters, singletons, summary}
    - enriched_ptm_data: List[dict]  (with rag_enrichment per PTM)
    - experimental_context: dict
    - network_analysis: dict  (for timepoint info)

Output (to state):
    - temporal_kinase_cascade: dict  (structured cascade data)
    - temporal_kinase_cascade_llm_context: str  (for LLM injection)
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

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
    "SCF_complex": r"[DE].{0,2}[ST].[DE]",
    "APC/C_D-box": r"R..L.{2,4}[ILVM]",
    "APC/C_KEN-box": r"KEN",
    "HECT_E3": r"[LP]P.Y",
    "VHL": r"LA.{1,2}[ILVM]P",
    "MDM2": r"F..W..L",
}

RESIDUE_KINASE_FAMILIES = {
    "S": ["CK2", "CK1", "CDK/MAPK", "PKA", "PKC", "AKT", "GSK3", "PLK1", "Aurora", "ATM/ATR", "AMPK", "mTOR"],
    "T": ["CDK/MAPK", "CK2", "GSK3", "PKC", "AMPK", "PLK1", "Aurora", "NEK", "MST1/2", "CAMK"],
    "Y": ["Src-family", "EGFR", "ABL", "JAK", "SYK", "FAK", "PDGFR", "VEGFR", "BTK", "FLT3"],
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def run_kinase_annotation(state: dict) -> dict:
    """Annotate co-wave clusters with multi-source kinase info and build temporal cascade."""
    try:
        comovement = state.get("comovement_analysis", {})
        clusters = comovement.get("clusters", [])
        enriched_data = state.get("enriched_ptm_data", [])
        ptm_type = state.get("ptm_type", "phosphorylation")
        network_analysis = state.get("network_analysis", {})

        if not clusters:
            logger.info("[KINASE-ANNOTATION] No co-wave clusters — skipping")
            return {
                "temporal_kinase_cascade": {},
                "temporal_kinase_cascade_llm_context": "",
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

        # Step 4: Build LLM context
        llm_context = _build_temporal_kinase_llm_context(
            temporal_cascade, cluster_annotations, clusters, ptm_type
        )

        logger.info(
            f"[KINASE-ANNOTATION] Temporal cascade: {len(temporal_cascade['timepoint_order'])} timepoints, "
            f"{len(temporal_cascade.get('cross_timepoint_inferences', []))} cross-timepoint inferences, "
            f"LLM context: {len(llm_context)} chars"
        )

        return {
            "temporal_kinase_cascade": temporal_cascade,
            "temporal_kinase_cascade_llm_context": llm_context,
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
        kinase_pattern = re.compile(
            r'(?:substrate\s+of|phosphorylated\s+by|target\s+of|regulated\s+by)'
            r'\s+([A-Z][A-Za-z0-9]{1,10}(?:\s+kinase)?)',
            re.IGNORECASE,
        )
        for finding in ft.get("key_findings", []):
            if isinstance(finding, str):
                for m in kinase_pattern.finditer(finding):
                    kname = m.group(1).strip()
                    if kname and len(kname) > 1:
                        known.append({
                            "kinase": kname,
                            "confidence": "text_mining",
                            "source": "fulltext_analysis",
                        })
        for article in ft.get("per_article", []):
            if isinstance(article, dict):
                for finding in article.get("key_findings", []):
                    if isinstance(finding, str):
                        for m in kinase_pattern.finditer(finding):
                            kname = m.group(1).strip()
                            if kname and len(kname) > 1:
                                known.append({
                                    "kinase": kname,
                                    "confidence": "text_mining",
                                    "source": "fulltext_analysis",
                                    "pmid": article.get("pmid", ""),
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

    # Source 6: STRING DB interactions
    string_ints = rag.get("string_interactions", [])
    if isinstance(string_ints, list):
        kinase_keywords = {
            "kinase", "phosphotransferase", "CK1", "CK2", "CDK", "MAPK",
            "PKA", "PKC", "GSK", "AKT", "mTOR", "ATM", "ATR", "PLK",
            "AURK", "NEK", "DYRK", "CLK", "SRPK", "CAMK", "AMPK",
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
                parts.append(
                    f"    - {info['kinase']} (canonical: {canon}): "
                    f"{len(info['confirmed_ptms'])} confirmed substrates ({ptms_str}), "
                    f"sources: [{sources_str}]"
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
            kinase_names = [info["kinase"] for _, info in sorted(kinases.items(), key=lambda x: len(x[1]["confirmed_ptms"]), reverse=True)]
            kinase_str = ", ".join(kinase_names[:5])
            if len(kinase_names) > 5:
                kinase_str += f" (+{len(kinase_names) - 5})"
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
                parts.append(
                    f"    - {info['kinase']} ({canon}): "
                    f"{len(info['confirmed_ptms'])} confirmed substrates, "
                    f"sources: [{sources}]"
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

    return "\n".join(parts)
