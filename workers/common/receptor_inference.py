"""
v11.5f: Receptor Inference for Workers (Sync Implementation)
============================================================
Self-contained receptor inference that runs inside the Celery worker
without requiring the async api-server code.

Sources:
  A) Literature (upstream_regulators from enriched data)
  B) Reactome pathway mapping (sync HTTP with Redis cache)
  B-1.5) Curated kinase→receptor DB fallback
  C) Treatment-context (ligand→receptor DB)

This mirrors the logic in api-server/app/api/orders.py (vector-plot-data endpoint)
but uses synchronous calls suitable for Celery workers.
"""
import json
import logging
import math
import re
import time
from collections import defaultdict
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ─── Reactome Constants ───────────────────────────────────────────────────────
REACTOME_BASE = "https://reactome.org/ContentService"
CACHE_PREFIX = "reactome:kinase_receptors"
CACHE_TTL_SECONDS = 90 * 24 * 3600  # 90 days
SPECIES_ID = 9606

_SIGNALING_BY_RE = re.compile(r"^Signaling by (.+)$", re.IGNORECASE)
_SKIP_NAMES = {
    "receptor tyrosine kinases", "nuclear receptors", "interleukins",
    "wnt", "notch", "hedgehog", "gpcrs, class a rhodopsin-like",
    "gpcrs, class b secretin-like", "gpcrs, class c metabotropic glutamate",
}

_RECEPTOR_CLASS_RULES = [
    (re.compile(r"EGFR|ERBB|HER\d", re.I), "RTK"),
    (re.compile(r"FGFR\d?", re.I), "RTK"),
    (re.compile(r"VEGFR|KDR|FLT", re.I), "RTK"),
    (re.compile(r"PDGFR", re.I), "RTK"),
    (re.compile(r"INSR|IGF1R|Insulin", re.I), "RTK"),
    (re.compile(r"NTRK\d|TRK[A-C]|NGF|BDNF", re.I), "RTK"),
    (re.compile(r"MET|HGFR", re.I), "RTK"),
    (re.compile(r"ALK", re.I), "RTK"),
    (re.compile(r"RET", re.I), "RTK"),
    (re.compile(r"KIT|SCF", re.I), "RTK"),
    (re.compile(r"Integrin|ITGA|ITGB", re.I), "Integrin"),
    (re.compile(r"TGF.?[Bb]|TGFBR|BMP|BMPR|Activin", re.I), "TGFβ"),
    (re.compile(r"Notch", re.I), "Developmental"),
    (re.compile(r"Wnt|Frizzled|FZD", re.I), "Developmental"),
    (re.compile(r"Hedgehog|SMO|PTCH", re.I), "Developmental"),
    (re.compile(r"TLR\d|Toll", re.I), "Immune"),
    (re.compile(r"TNF|TNFR|TRAIL", re.I), "Immune"),
    (re.compile(r"IL\d|Interleukin", re.I), "Cytokine"),
    (re.compile(r"IFN|Interferon|IFNAR|IFNGR", re.I), "Cytokine"),
    (re.compile(r"GPCR|Adrenergic|Muscarinic|Serotonin|Dopamine|Opioid", re.I), "GPCR"),
    (re.compile(r"Estrogen|ESR|Androgen|Progesterone", re.I), "Nuclear Receptor"),
    (re.compile(r"EPH|Ephrin", re.I), "RTK"),
    (re.compile(r"NMDA|Glutamate|GABA", re.I), "Ion Channel"),
    (re.compile(r"LEPR|ADIPOR", re.I), "Metabolic"),
    (re.compile(r"LRP", re.I), "Lipoprotein Receptor"),
]

_HUB_KINASES = {"AKT1", "AKT2", "MAPK1", "MAPK3", "PI3K", "SRC",
                "ERK1", "ERK2", "PIK3CA", "PIK3R1"}
_HUB_PENALTY = 0.2

_SOURCE_RELIABILITY = {
    "treatment_context": 1.0,
    "treatment_context_uniprot": 0.7,
    "curated_kinase_receptor_db": 0.8,
    "reactome": 0.6,
    "e3_ligase_db": 0.7,
    "ubiquitylation_db_client": 0.6,
    "literature": 0.3,
}


def _classify_receptor(receptor_name: str) -> str:
    """Classify receptor into a category based on name."""
    for pattern, cls in _RECEPTOR_CLASS_RULES:
        if pattern.search(receptor_name):
            return cls
    return "Receptor"


# ─── Sync Reactome API ────────────────────────────────────────────────────────

def _get_redis_client():
    """Get Redis client from workers/common/progress.py."""
    try:
        from common.progress import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def _reactome_lookup_kinase_sync(gene_name: str) -> list[dict]:
    """Sync version of Reactome kinase→receptor lookup with Redis caching."""
    redis_client = _get_redis_client()
    cache_key = f"{CACHE_PREFIX}:{gene_name.upper()}"

    # Check Redis cache
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.debug(f"Redis cache read failed for {gene_name}: {e}")

    # Cache miss — call Reactome API (sync)
    receptors = []
    try:
        # Step 1: Search entity
        resp = requests.get(
            f"{REACTOME_BASE}/search/query",
            params={"query": gene_name, "species": "Homo sapiens", "types": "Protein"},
            timeout=10, verify=False,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return []
        entries = results[0].get("entries", [])
        if not entries:
            return []
        stid = entries[0].get("stId")
        if not stid:
            return []

        # Step 2: Get pathways
        resp2 = requests.get(
            f"{REACTOME_BASE}/data/pathways/low/entity/{stid}/allForms",
            params={"species": SPECIES_ID},
            timeout=10, verify=False,
        )
        if resp2.status_code != 200:
            return []
        pathways = resp2.json()
        if not pathways:
            return []

        # Step 3: Get ancestors for each pathway (limit to 10)
        receptor_map: dict[str, dict] = {}
        for pw in pathways[:10]:
            pw_stid = pw.get("stId")
            if not pw_stid:
                continue
            try:
                resp3 = requests.get(
                    f"{REACTOME_BASE}/data/event/{pw_stid}/ancestors",
                    timeout=10, verify=False,
                )
                if resp3.status_code != 200:
                    continue
                ancestors = resp3.json()
                for chain in ancestors:
                    for node in chain:
                        name = node.get("displayName", "")
                        m = _SIGNALING_BY_RE.match(name)
                        if m:
                            candidate = m.group(1).strip()
                            if candidate.lower() not in _SKIP_NAMES:
                                if candidate not in receptor_map:
                                    receptor_map[candidate] = {
                                        "receptor": candidate,
                                        "receptor_class": _classify_receptor(candidate),
                                        "pathway": pw.get("displayName", ""),
                                        "pathway_id": pw_stid,
                                        "signaling_pathway": name,
                                    }
            except Exception:
                continue

        receptors = list(receptor_map.values())

    except Exception as e:
        logger.warning(f"Reactome sync lookup failed for {gene_name}: {e}")
        receptors = []

    # Cache result (even empty)
    if redis_client:
        try:
            redis_client.set(cache_key, json.dumps(receptors), ex=CACHE_TTL_SECONDS)
        except Exception:
            pass

    return receptors


def _reactome_lookup_kinases_sync(kinase_names: list[str]) -> dict[str, list[dict]]:
    """Batch sync Reactome lookup for multiple kinases."""
    result = {}
    for name in kinase_names:
        try:
            result[name] = _reactome_lookup_kinase_sync(name)
        except Exception as e:
            logger.warning(f"Reactome lookup failed for {name}: {e}")
            result[name] = []
        time.sleep(0.1)  # Rate limiting
    return result


# ─── Main Receptor Inference Function ─────────────────────────────────────────

def run_receptor_inference(
    order_id: int,
    enriched_data: list,
    kinase_analysis_data: dict,
    config: dict,
    vector_data: list = None,
    top_n_ptms: list = None,
) -> dict:
    """
    Run full receptor inference pipeline (sync, for Celery workers).

    Args:
        order_id: Order ID for logging
        enriched_data: List of enriched PTM dicts
        kinase_analysis_data: Result from _auto_run_global_analysis
        config: Order config with experimental_context, treatment, etc.
        vector_data: Raw vector plot data (optional, for co-wave analysis)
        top_n_ptms: Top N PTMs list (optional)

    Returns:
        dict with keys: receptors, top_n_setting, cowave_analysis, saved_at
    """
    from common.ligand_receptor_db import (
        _RECEPTOR_DOWNSTREAM_KINASES,
        get_upstream_receptors_for_kinases,
        lookup_receptors_for_treatment,
    )
    from common.progress import publish_progress

    publish_progress(order_id, "rag_enrichment", "receptor_inference", "running", 96,
                     "Auto-running Receptor Inference")
    t0 = time.time()

    experimental_context = config.get("experimental_context") or {}
    ptm_type = experimental_context.get("ptm_type", "phosphorylation")
    treatment_text = experimental_context.get("treatment", "")
    top_n_setting = config.get("top_n_ptms", 50)

    # ── Normalize kinase_analysis_data schema ──
    # _auto_run_global_analysis() returns {kinase_modules: [...]} where each module has
    # {kinase, canonical, members: [{gene, position, ...}]}.
    # Older/alternative callers may pass {modules: [...]} with {kinase_name, substrates: [...]}.
    # Build a unified view so the extraction loop below works for both.
    if "kinase_modules" in kinase_analysis_data and "modules" not in kinase_analysis_data:
        _normalized_modules = []
        for _m in kinase_analysis_data["kinase_modules"]:
            _normalized_modules.append({
                **_m,
                "kinase_name": _m.get("kinase_name") or _m.get("kinase", ""),
                # Map "members" → "substrates" so existing extraction code works
                "substrates": _m.get("substrates") or _m.get("members", []),
            })
        kinase_analysis_data = {**kinase_analysis_data, "modules": _normalized_modules}

    # ── Extract kinase names from kinase_analysis_data ──
    kinase_names_set: set = set()
    kinase_ptm_map: dict = {}  # kinase_name -> set of ptm_labels

    modules = kinase_analysis_data.get("modules", [])
    for mod in modules:
        kin_name = mod.get("kinase_name") or mod.get("kinase", "")
        if kin_name:
            kinase_names_set.add(kin_name)
            ptm_labels = set()
            for sub in mod.get("substrates") or mod.get("members", []):
                lbl = sub.get("label") or f"{sub.get('gene', '')} {sub.get('position', '')}".strip()
                if lbl:
                    ptm_labels.add(lbl)
            kinase_ptm_map[kin_name] = ptm_labels

    if not kinase_names_set:
        logger.warning(f"[Order {order_id}] Receptor inference: no kinases found")
        publish_progress(order_id, "rag_enrichment", "receptor_inference", "completed", 97,
                         "Receptor inference skipped: no kinases")
        return {}

    logger.info(f"[Order {order_id}] Receptor inference: {len(kinase_names_set)} kinases found")

    # ── Source B: Reactome pathway mapping (sync) ──
    reactome_receptors: dict = {}
    try:
        kinase_list = sorted(kinase_names_set)[:30]
        kinase_receptor_map = _reactome_lookup_kinases_sync(kinase_list)

        receptor_kinase_map: dict = defaultdict(lambda: {
            "kinases": [], "receptor_class": "", "pathway": "", "signaling_pathway": ""
        })
        for kinase_name, receptors in kinase_receptor_map.items():
            for rec in receptors:
                rec_name = rec["receptor"]
                receptor_kinase_map[rec_name]["kinases"].append(kinase_name)
                if not receptor_kinase_map[rec_name]["receptor_class"]:
                    receptor_kinase_map[rec_name]["receptor_class"] = rec["receptor_class"]
                if not receptor_kinase_map[rec_name]["pathway"]:
                    receptor_kinase_map[rec_name]["pathway"] = rec.get("pathway", "")
                if not receptor_kinase_map[rec_name]["signaling_pathway"]:
                    receptor_kinase_map[rec_name]["signaling_pathway"] = rec.get("signaling_pathway", "")

        for rec_name, info in receptor_kinase_map.items():
            downstream_ptms = set()
            for kin in info["kinases"]:
                downstream_ptms.update(kinase_ptm_map.get(kin, set()))
            unique_kinases = sorted(set(info["kinases"]))

            # Supplement with receptor-specific kinases from curated DB
            _b_aliases = [rec_name.split("(")[0].strip().upper()]
            if "(" in rec_name:
                _b_alias = rec_name.split("(")[1].replace(")", "").strip().upper()
                if _b_alias:
                    _b_aliases.append(_b_alias)
            for _ba in list(_b_aliases):
                _bc = _ba.replace("-", "").replace(" ", "")
                if _bc != _ba:
                    _b_aliases.append(_bc)
            _b_rec_specific: set = set()
            for _ba in _b_aliases:
                if _ba in _RECEPTOR_DOWNSTREAM_KINASES:
                    _b_rec_specific.update(_RECEPTOR_DOWNSTREAM_KINASES[_ba])
            _b_has_specific = len(_b_rec_specific) > 0
            if _b_has_specific:
                _existing_set = set(unique_kinases)
                _priority = [k for k in _b_rec_specific
                             if k in kinase_names_set and k not in _existing_set]
                unique_kinases = _priority + unique_kinases
                unique_kinases = unique_kinases[:8]
                for _pk in _priority:
                    downstream_ptms.update(kinase_ptm_map.get(_pk, set()))

            reactome_receptors[rec_name] = {
                "name": rec_name,
                "receptor_class": info["receptor_class"],
                "downstream_ptm_count": max(len(downstream_ptms), 1),
                "downstream_ptms": sorted(downstream_ptms)[:10],
                "via_kinases": unique_kinases,
                "pathway": info["pathway"],
                "signaling_pathway": info["signaling_pathway"],
                "source": "reactome",
                "has_receptor_specific_db": _b_has_specific,
            }

        logger.info(f"[Order {order_id}] Reactome (Source B): {len(reactome_receptors)} receptors")
    except Exception as e:
        logger.warning(f"[Order {order_id}] Reactome receptor lookup failed: {e}")

    # ── Source B-1.5: Curated kinase→receptor DB fallback ──
    try:
        _mapped_kinases = set()
        for _ri in reactome_receptors.values():
            _mapped_kinases.update(_ri.get("via_kinases", []))
        _unmapped_kinases = [k for k in kinase_names_set if k not in _mapped_kinases]

        if _unmapped_kinases:
            curated_map = get_upstream_receptors_for_kinases(_unmapped_kinases)
            for kinase_name, receptors in curated_map.items():
                for rec in receptors:
                    rec_name = rec["receptor"]
                    if rec_name not in reactome_receptors:
                        downstream_ptms = kinase_ptm_map.get(kinase_name, set())
                        reactome_receptors[rec_name] = {
                            "name": rec_name,
                            "receptor_class": rec.get("receptor_class", ""),
                            "downstream_ptm_count": max(len(downstream_ptms), 1),
                            "downstream_ptms": sorted(downstream_ptms)[:10],
                            "via_kinases": [kinase_name],
                            "pathway": rec.get("pathway", ""),
                            "signaling_pathway": rec.get("pathway", ""),
                            "source": "curated_kinase_receptor_db",
                            "has_receptor_specific_db": True,
                        }
                    else:
                        existing = reactome_receptors[rec_name]
                        via = existing.get("via_kinases") or []
                        if kinase_name not in via:
                            via.append(kinase_name)
                            existing["via_kinases"] = via[:8]

            logger.info(
                f"[Order {order_id}] Curated DB (Source B-1.5): supplemented from "
                f"{len(_unmapped_kinases)} unmapped kinases"
            )
    except Exception as e:
        logger.warning(f"[Order {order_id}] Curated DB receptor lookup failed: {e}")

    # ── Source C: Treatment-context-based receptor inference ──
    treatment_receptors: dict = {}
    if treatment_text:
        try:
            matches = lookup_receptors_for_treatment(treatment_text)
            for m in matches:
                rec_name = m.get("receptor_name", "")
                if not rec_name:
                    continue
                rec_class = m.get("receptor_class", "Receptor")

                # Score against kinase activity
                _c_aliases = [rec_name.split("(")[0].strip().upper()]
                if "(" in rec_name:
                    _c_alias = rec_name.split("(")[1].replace(")", "").strip().upper()
                    if _c_alias:
                        _c_aliases.append(_c_alias)
                for _ca in list(_c_aliases):
                    _cc = _ca.replace("-", "").replace(" ", "")
                    if _cc != _ca:
                        _c_aliases.append(_cc)

                _c_rec_specific: set = set()
                for _ca in _c_aliases:
                    if _ca in _RECEPTOR_DOWNSTREAM_KINASES:
                        _c_rec_specific.update(_RECEPTOR_DOWNSTREAM_KINASES[_ca])

                # Find via_kinases that are in our kinase set
                detected_via_kinases = []
                for k in kinase_names_set:
                    if k in _c_rec_specific:
                        detected_via_kinases.append(k)
                # Also check kinase_ptm_map overlap
                downstream_ptms = set()
                for k in detected_via_kinases:
                    downstream_ptms.update(kinase_ptm_map.get(k, set()))

                if not detected_via_kinases and not downstream_ptms:
                    # No kinase overlap - still include but with lower score
                    pass

                treatment_receptors[rec_name] = {
                    "name": rec_name,
                    "receptor_class": rec_class,
                    "downstream_ptm_count": max(len(downstream_ptms), 1),
                    "downstream_ptms": sorted(downstream_ptms)[:10],
                    "via_kinases": detected_via_kinases[:8],
                    "pathway": m.get("pathway", ""),
                    "evidence": m.get("evidence", ""),
                    "matched_ligand": m.get("ligand", ""),
                    "source": m.get("source", "treatment_context"),
                    "has_receptor_specific_db": len(_c_rec_specific) > 0,
                }

            logger.info(
                f"[Order {order_id}] Source C: {len(treatment_receptors)} receptors "
                f"for treatment '{treatment_text}'"
            )
        except Exception as e:
            logger.warning(f"[Order {order_id}] Treatment-context receptor lookup failed: {e}")

    # ── Merge all sources (C > B priority) ──
    merged: dict = {}
    for rec_name, info in treatment_receptors.items():
        merged[rec_name] = info
    for rec_name, info in reactome_receptors.items():
        if rec_name not in merged:
            merged[rec_name] = info
        else:
            existing = merged[rec_name]
            if not existing.get("via_kinases") and info.get("via_kinases"):
                existing["via_kinases"] = info["via_kinases"]
            if not existing.get("signaling_pathway") and info.get("signaling_pathway"):
                existing["signaling_pathway"] = info["signaling_pathway"]

    if not merged:
        logger.warning(f"[Order {order_id}] Receptor inference: no receptors found from any source")
        publish_progress(order_id, "rag_enrichment", "receptor_inference", "completed", 97,
                         "Receptor inference: no receptors found")
        return {}

    # ── Compute unique PTM ratio ──
    all_ptm_freq: dict = defaultdict(int)
    for _ri in merged.values():
        for p in _ri.get("downstream_ptms", []):
            all_ptm_freq[p] += 1

    for _ri in merged.values():
        ds_ptms = set(_ri.get("downstream_ptms", []))
        unique_ptms = [p for p in ds_ptms if all_ptm_freq.get(p, 0) == 1]
        _ri["unique_ptms"] = unique_ptms
        _ri["unique_ptm_ratio"] = len(unique_ptms) / max(len(ds_ptms), 1)

    # ── Specificity-Weighted Activity Score (v11.5) ──
    # Classify PTMs
    _ptm_activity_class: dict = {}
    _ptm_max_abs_fc: dict = {}
    _ptm_is_denovo: set = set()
    _ptm_min_q: dict = {}

    for r in (enriched_data or []):
        gene = r.get("gene") or r.get("Gene.Name", "")
        pos = r.get("position") or r.get("PTM_Position", "")
        lbl = f"{gene} {pos}".strip()
        if r.get("control_pseudocount_used"):
            _ptm_is_denovo.add(lbl)
        _cur_fc = abs(r.get("ptm_relative_log2fc", 0) or r.get("log2fc", 0) or 0)
        if lbl not in _ptm_max_abs_fc or _cur_fc > _ptm_max_abs_fc[lbl]:
            _ptm_max_abs_fc[lbl] = _cur_fc
        _q = r.get("q_value")
        if _q is not None and not (isinstance(_q, float) and math.isnan(_q)):
            if lbl not in _ptm_min_q or _q < _ptm_min_q[lbl]:
                _ptm_min_q[lbl] = _q

    for lbl in _ptm_max_abs_fc:
        if lbl in _ptm_is_denovo:
            _ptm_activity_class[lbl] = "de_novo"
        elif _ptm_min_q.get(lbl, 1.0) < 0.05 and _ptm_max_abs_fc[lbl] >= 1.0:
            _ptm_activity_class[lbl] = "regulated"
        else:
            _ptm_activity_class[lbl] = "minor"

    _SIGNAL_WEIGHT = {"de_novo": 0.3, "regulated": 1.0, "minor": 0.5}
    _FC_CAP = {"de_novo": 1.0, "regulated": 3.0, "minor": 3.0}

    for _ri in merged.values():
        _ds_ptms = set(_ri.get("downstream_ptms", []))
        _unique_set = set(_ri.get("unique_ptms", []))
        _total_weighted_activity = 0.0
        _unique_regulated_count = 0
        for _p in _ds_ptms:
            _cls = _ptm_activity_class.get(_p, "minor")
            _w = _SIGNAL_WEIGHT[_cls]
            _fc = min(_ptm_max_abs_fc.get(_p, 0.0), _FC_CAP[_cls])
            _sharing_factor = 1.0 if _p in _unique_set else (1.0 / max(all_ptm_freq.get(_p, 1), 1))
            _total_weighted_activity += _w * _fc * _sharing_factor
            if _p in _unique_set and _cls == "regulated":
                _unique_regulated_count += 1
        _max_possible = max(len(_ds_ptms), 1) * 1.0 * 3.0
        _specificity_score = min(_total_weighted_activity / _max_possible, 1.0)
        _unique_reg_ratio = _unique_regulated_count / max(len(_ds_ptms), 1)
        _ri["specificity_score"] = round(_specificity_score, 4)
        _ri["unique_regulated_ratio"] = round(_unique_reg_ratio, 4)
        _ri["unique_regulated_count"] = _unique_regulated_count

    # ── Co-wave Analysis (simplified — full version needs vector_data with time series) ──
    _cowave_analysis = None
    # For now, set cowave_score to 0 (will be recalculated by frontend if needed)
    for _ri in merged.values():
        _ri["cowave_score"] = 0.0

    # ── Confidence Score ──
    _all_cowave_scores = [r.get("cowave_score", 0) for r in merged.values()]
    _max_cowave = max(_all_cowave_scores) if _all_cowave_scores else 1.0
    if _max_cowave == 0:
        _max_cowave = 1.0

    for _ri in merged.values():
        _vk = _ri.get("via_kinases", [])
        _n_kinases = len(_vk)
        _norm_cowave = _ri.get("cowave_score", 0) / _max_cowave
        _convergence = min(_n_kinases / 5.0, 1.0) if _n_kinases > 0 else 0.0
        _source = _ri.get("source", "literature")
        _source_rel = _SOURCE_RELIABILITY.get(_source, 0.3)
        _specificity = _ri.get("specificity_score", 0.0)
        _upr = _ri.get("unique_regulated_ratio", 0.0)
        _has_db = 1.0 if _ri.get("has_receptor_specific_db") else 0.0

        # v11.5 confidence formula
        confidence = (
            0.30 * _norm_cowave +
            0.20 * _convergence +
            0.15 * _source_rel +
            0.20 * _specificity +
            0.05 * _upr +
            0.10 * _has_db
        )
        _ri["confidence_score"] = round(min(max(confidence, 0.0), 1.0), 4)

    # ── Hard Filter: kinase group dedup ──
    # Group receptors by their via_kinases set to remove duplicates
    _filtered_merged: dict = {}
    _group_best: dict = {}
    for _rn, _ri in merged.items():
        _vk = sorted(_ri.get("via_kinases", []))
        _gid = "|".join(_vk) if _vk else None
        if _gid:
            if _gid not in _group_best:
                _group_best[_gid] = (_rn, _ri["confidence_score"])
                _filtered_merged[_rn] = _ri
            else:
                _prev_name, _prev_score = _group_best[_gid]
                if _ri["confidence_score"] > _prev_score:
                    _filtered_merged.pop(_prev_name, None)
                    _filtered_merged[_rn] = _ri
                    _group_best[_gid] = (_rn, _ri["confidence_score"])
        else:
            _filtered_merged[_rn] = _ri

    # ── Soft Threshold: confidence >= 0.3 ──
    _CONFIDENCE_THRESHOLD = 0.3
    _above_threshold = {
        rn: ri for rn, ri in _filtered_merged.items()
        if ri["confidence_score"] >= _CONFIDENCE_THRESHOLD
    }
    if len(_above_threshold) < 5 and len(_filtered_merged) >= 5:
        _sorted_filtered = sorted(
            _filtered_merged.values(),
            key=lambda x: x["confidence_score"],
            reverse=True,
        )
        _above_threshold = {r["name"]: r for r in _sorted_filtered[:5]}
    # Always keep treatment_context receptors
    for _rn, _ri in _filtered_merged.items():
        if _ri.get("source") in ("treatment_context", "treatment_context_uniprot"):
            _above_threshold[_rn] = _ri

    # ── Final sorting ──
    inferred_receptors = sorted(
        _above_threshold.values(),
        key=lambda x: (x.get("confidence_score", 0), x.get("cowave_score", 0)),
        reverse=True,
    )

    logger.info(
        f"[Order {order_id}] Receptor inference complete: "
        f"{len(merged)} raw → {len(_filtered_merged)} filtered → "
        f"{len(inferred_receptors)} final ({round(time.time() - t0, 1)}s)"
    )

    # ── Save to DB ──
    result_data = {
        "receptors": inferred_receptors,
        "top_n_setting": top_n_setting,
        "locked": False,
        "cowave_analysis": _cowave_analysis,
        "saved_at": __import__('datetime').datetime.utcnow().isoformat(),
        "source": "auto_pipeline",  # Mark as auto-computed (not from frontend)
    }

    try:
        from common.db_engine import get_engine as _get_engine
        from sqlalchemy import text as _text
        _engine = _get_engine()
        with _engine.connect() as _conn:
            _conn.execute(
                _text("UPDATE orders SET receptor_inference_data = :rid WHERE id = :oid"),
                {"oid": order_id, "rid": json.dumps(result_data, default=str)},
            )
            _conn.commit()
        logger.info(
            f"[Order {order_id}] Saved {len(inferred_receptors)} inferred receptors to DB"
        )
    except Exception as _save_err:
        logger.warning(f"[Order {order_id}] Failed to save receptor_inference_data: {_save_err}")

    publish_progress(order_id, "rag_enrichment", "receptor_inference", "completed", 97,
                     f"Receptor inference done: {len(inferred_receptors)} receptors")

    return result_data
