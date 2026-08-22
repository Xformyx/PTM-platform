"""
Stage 2: RAG Enrichment Pipeline — Celery Task.

Takes preprocessing TSV output and enriches each PTM site with:
  1. PubMed literature search (multi-tier, via MCP)
  2. Pattern-based regulation extraction (no LLM)
  3. KEGG / STRING / UniProt annotations (via MCP)
  4. Comprehensive MD report generation
"""

import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path

import pandas as pd

from celery_app import app
from common.db_update import get_order_status, update_order_status
from common.notifications import notify_order_status
from common.mcp_client import MCPClient
from common.progress import publish_analysis_log, publish_progress, save_celery_task_id
from common.temporal_utils import condition_sort_key
from common.webhook import send_step_webhook

logger = logging.getLogger("ptm-workers.rag-enrichment")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")

# Generic terms that should never be treated as valid kinase names
_KINASE_STOP_WORDS = {
    "OF", "THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM",
    "BY", "TO", "IN", "ON", "AT", "IS", "IT", "AS", "OR", "AN",
    "BE", "IF", "NO", "NOT", "BUT", "ALL", "CAN", "HAD", "HAS",
    "HER", "HIS", "HOW", "ITS", "MAY", "NEW", "NOW", "OLD", "OUR",
    "OUT", "OWN", "SAY", "SHE", "TOO", "USE", "WAY", "WHO", "BOY",
    "DID", "GET", "HIM", "LET", "PUT", "RUN", "SET", "TOP", "WHY",
    "CELL", "GENE", "PROTEIN", "DOMAIN", "SITE", "TYPE", "ROLE",
    "ACTIVITY", "FUNCTION", "PATHWAY", "SIGNAL", "TARGET", "EFFECT",
    "RESULT", "LEVEL", "FACTOR", "COMPLEX", "FAMILY", "GROUP",
    "REGION", "SEQUENCE", "RESIDUE", "MOTIF", "SUBSTRATE",
}


def _auto_run_global_analysis(order_id: int, enriched_data: list, config: dict, mcp_client=None) -> dict:
    """v9.44: Auto-run Global Kinase Modules + Activity Heatmap after RAG enrichment.

    Self-contained implementation — no cross-worker imports.
    Builds kinase modules from enriched_ptms and computes activity heatmap.
    Results are cached to DB.
    """
    import re
    from hashlib import md5
    from common.kinase_utils import normalize_kinase_name, are_kinases_same_family

    t0 = time.time()
    publish_progress(order_id, "rag_enrichment", "global_analysis", "running", 92,
                     "Auto-running Global Kinase Analysis")
    try:
        ptm_type = (config.get("experimental_context") or {}).get("ptm_type", "phosphorylation")

        # ── Motif databases (inline) ──
        PHOSPHO_MOTIF_DB = {
            "CDK1/CDK2": r"[ST]P.[KR]", "CDK/MAPK": r"[ST]P", "ERK1/ERK2": r"P.[ST]P",
            "JNK": r"[ST]P", "p38": r"[ST]P", "DYRK1A/DYRK1B": r"R..[ST]P",
            "PKA": r"[RK][RK].[ST]", "PKC": r"[RK].[ST][RK]", "AKT/PKB": r"R.R..[ST]",
            "RSK": r"[RK].[RK]..[ST]", "CAMK2": r"[RK]..[ST]..[RK]",
            "AMPK": r"[LMVIF].[RK]..[ST]", "CK2": r"[ST].{1,2}[ED]",
            "CK1": r"[ST]..[ST]", "GSK3": r"[ST]...[ST]P",
            "PLK1": r"[DE].[ST][ILVM]", "Aurora_A/B": r"[RK].[ST][ILVM]",
            "ATM/ATR": r"[ST]Q", "DNA-PK": r"[ST]Q..",
            "Src/Fyn/Yes": r"[EDAY].[YF].{1,3}[PGAS]", "ABL": r"[IVLA]Y..[PG]",
            "JAK1/JAK2": r"Y..[LIV]", "mTOR": r"[ST]F",
            "CHK1/CHK2": r"[LM].[RK]..[ST]", "NEK2/NEK6": r"[LM].[ST]",
        }
        UBI_MOTIF_DB = {
            "SCF_complex": r"[DE].{0,2}[ST].[DE]", "SCF-FBXW7": r"[LI].{0,1}[ST]P.{0,2}[ED]",
            "SCF-BTRC": r"DS.{1,2}[AG][IL]D", "SCF-SKP2": r"[LI].[KR].{1,2}[ST]P",
            "APC/C_D-box": r"R..L.{2,4}[ILVM]", "APC/C_KEN-box": r"KEN",
            "NEDD4/HECT": r"[LP]P.Y", "VHL": r"LA.{1,2}[ILVM]P",
            "MDM2": r"F..W..L", "CHIP/STUB1": r"[RK].{0,2}[ILVM].{0,2}[ED]",
            "PARKIN": r"[RK].{1,3}[ST].{1,3}[DE]", "TRAF6": r"[ST].{0,2}[KR].{0,2}[ED]",
            "TRIM25": r"[FY].{1,3}[KR]", "KEAP1": r"[DE].{1,3}[ST][GS][ED]",
        }
        RESIDUE_KINASE_FAMILIES = {
            "S": ["CK2", "CK1", "CDK/MAPK", "PKA", "PKC", "AKT", "GSK3", "PLK1", "Aurora", "ATM/ATR", "AMPK", "mTOR"],
            "T": ["CDK/MAPK", "CK2", "GSK3", "PKC", "AMPK", "PLK1", "Aurora", "NEK", "MST1/2", "CAMK"],
            "Y": ["Src-family", "EGFR", "ABL", "JAK", "SYK", "FAK", "PDGFR", "VEGFR", "BTK", "FLT3"],
            "K": ["SCF_complex", "APC/C", "MDM2", "NEDD4", "CHIP/STUB1", "TRAF6", "PARKIN", "TRIM25", "VHL"],
        }

        motif_db = PHOSPHO_MOTIF_DB if ptm_type == "phosphorylation" else UBI_MOTIF_DB

        # ── Helper: collect known kinases from enriched entry ──
        def _collect_known_kinases(gene, pos, entry):
            known = []
            rag = entry.get("rag_enrichment", {})
            if not rag or not isinstance(rag, dict):
                return known
            # Source 1: kinase_prediction
            kp = rag.get("kinase_prediction", {})
            if isinstance(kp, str):
                try:
                    import ast
                    kp = ast.literal_eval(kp) if kp.startswith("{") else {}
                except Exception:
                    kp = {}
            if isinstance(kp, dict):
                for k in kp.get("predicted_kinases", []):
                    if isinstance(k, dict) and k.get("kinase"):
                        known.append({"kinase": k["kinase"], "source": "rag_kinase_prediction"})
                    elif isinstance(k, str) and k:
                        known.append({"kinase": k, "source": "rag_kinase_prediction"})
            # Source 2: regulation
            reg = rag.get("regulation", {})
            if isinstance(reg, dict):
                for ks in reg.get("kinase_substrate", []):
                    if isinstance(ks, dict) and ks.get("kinase"):
                        known.append({"kinase": ks["kinase"], "source": "kinase_substrate_pair"})
                for ur in reg.get("upstream_regulators", []):
                    if isinstance(ur, dict) and ur.get("regulator"):
                        known.append({"kinase": ur["regulator"], "source": "upstream_regulator"})
                    elif isinstance(ur, str) and ur:
                        known.append({"kinase": ur, "source": "upstream_regulator"})
                for e3s in reg.get("e3_substrate", []):
                    if isinstance(e3s, dict) and e3s.get("e3_ligase"):
                        known.append({"kinase": e3s["e3_ligase"], "source": "e3_substrate_pair"})
            # Source 3: ptm_validation
            ptm_val = rag.get("ptm_validation", {})
            if isinstance(ptm_val, dict):
                for hit in ptm_val.get("iptmnet_hits", []):
                    if isinstance(hit, dict):
                        enz = hit.get("enzyme") or {}
                        if isinstance(enz, dict) and enz.get("name"):
                            known.append({"kinase": enz["name"], "source": "iPTMnet"})
            # Source 4: fulltext_analysis
            ft = rag.get("fulltext_analysis", {})
            if isinstance(ft, dict):
                kinase_pattern = re.compile(
                    r'(?:substrate\s+of|phosphorylated\s+by|target\s+of|regulated\s+by)'
                    r'\s+([A-Z][A-Za-z0-9]{1,10})', re.IGNORECASE)
                all_findings = list(ft.get("key_findings", []))
                for article in ft.get("per_article", []):
                    if isinstance(article, dict):
                        all_findings.extend(article.get("key_findings", []))
                for finding in all_findings:
                    if not isinstance(finding, str):
                        if isinstance(finding, tuple) and len(finding) >= 1:
                            finding = finding[0]
                        else:
                            continue
                    for m in kinase_pattern.finditer(finding):
                        kname = m.group(1).strip()
                        if kname and len(kname) > 1:
                            known.append({"kinase": kname, "source": "fulltext_analysis"})
            # Source 5: abstract_analysis
            aa = rag.get("abstract_analysis", {})
            if isinstance(aa, dict):
                for key_name in ("kinases", "upstream_kinases", "predicted_kinases", "regulators",
                                 "e3_ligases", "ubiquitin_ligases"):
                    for item in aa.get(key_name, []):
                        if isinstance(item, dict):
                            kn = item.get("kinase") or item.get("name") or item.get("e3_ligase")
                            if kn:
                                known.append({"kinase": kn, "source": "abstract_analysis"})
                        elif isinstance(item, str) and item:
                            known.append({"kinase": item, "source": "abstract_analysis"})
            # Source 6: STRING DB
            string_ints = rag.get("string_interactions", [])
            if isinstance(string_ints, list):
                kinase_kw = {"kinase", "CDK", "MAPK", "PKA", "PKC", "GSK", "AKT", "mTOR",
                             "ATM", "ATR", "PLK", "AURK", "NEK", "DYRK", "CLK", "CAMK", "AMPK"}
                e3_kw = {"ligase", "RING", "HECT", "SCF", "APC", "MDM2", "NEDD4", "CHIP",
                         "TRAF", "TRIM", "RNF", "PARKIN", "VHL", "FBXW", "FBXL", "FBXO"}
                for si in string_ints:
                    if isinstance(si, dict):
                        partner = si.get("preferredName_B") or si.get("partner", "")
                        score = si.get("score", 0)
                        if partner and score >= 700:
                            pu = partner.upper()
                            if any(kw.upper() in pu for kw in kinase_kw):
                                known.append({"kinase": partner, "source": "string_db"})
                            elif any(kw.upper() in pu for kw in e3_kw):
                                known.append({"kinase": partner, "source": "string_db_e3"})
            # Normalize & deduplicate
            for kk in known:
                canonical, display = normalize_kinase_name(kk["kinase"])
                kk["canonical_name"] = canonical
                kk["display_name"] = display
            seen = set()
            unique = []
            for kk in known:
                c = kk["canonical_name"]
                if c and c not in seen:
                    seen.add(c)
                    unique.append(kk)
            return unique

        # ── Helper: predict motif kinases ──
        def _predict_motif(position, entry):
            predicted = []
            seq = ""
            rag = entry.get("rag_enrichment", {})
            for seq_key in ("modified_sequence", "Modified.Sequence", "sequence_window",
                           "Sequence_Window", "flanking_sequence"):
                val = entry.get(seq_key, "")
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
                            predicted.append({"canonical_family": canonical})
                    except re.error:
                        continue
            if not predicted and position:
                residue = str(position)[0].upper()
                if residue in RESIDUE_KINASE_FAMILIES:
                    for family in RESIDUE_KINASE_FAMILIES[residue]:
                        canonical, _ = normalize_kinase_name(family)
                        predicted.append({"canonical_family": canonical})
            return predicted

        # ── Step A: Collect all PTM entries ──
        all_ptm_entries = []
        for ed in enriched_data:
            gene = (ed.get("gene") or ed.get("Gene.Name", "")).strip()
            pos = ed.get("position") or ed.get("PTM_Position", "")
            if gene and pos:
                all_ptm_entries.append((gene, str(pos), ed))

        # ── Step B: Build kinase-centric modules (confirmed) ──
        kinase_members = {}  # canonical → {kinase, sources, confirmed, inferred}
        for gene, pos, entry in all_ptm_entries:
            ptm_key = f"{gene.upper()}_{str(pos).upper()}"
            known = _collect_known_kinases(gene, pos, entry)
            for kk in known:
                canon = kk.get("canonical_name", "")
                display = kk.get("display_name", kk.get("kinase", ""))
                source = kk.get("source", "unknown")
                # Filter out invalid kinase names (stop words, too short, generic terms)
                if not canon or len(canon) < 3 or canon in _KINASE_STOP_WORDS:
                    continue
                if canon not in kinase_members:
                    kinase_members[canon] = {
                        "kinase": display, "canonical": canon,
                        "sources": set(), "confirmed": [], "inferred": [],
                    }
                kinase_members[canon]["sources"].add(source)
                if ptm_key not in [m["key"] for m in kinase_members[canon]["confirmed"]]:
                    kinase_members[canon]["confirmed"].append({
                        "key": ptm_key, "gene": gene.upper(),
                        "position": pos, "membership": "confirmed", "evidence": source,
                    })

        # ── Step C: Infer kinases via motif — assign PTMs to ALL matching kinase families ──
        # Unlike Step B (confirmed 1:1), motif inference allows a PTM to be assigned
        # to multiple kinase families, AND creates new kinase modules for unmatched motifs.
        for gene, pos, entry in all_ptm_entries:
            ptm_key = f"{gene.upper()}_{str(pos).upper()}"
            motif_pred = _predict_motif(pos, entry)
            motif_families = set()
            for mp in motif_pred:
                for part in mp.get("canonical_family", "").split("/"):
                    if part and len(part) >= 2:
                        motif_families.add(part)
            if not motif_families:
                continue
            # Assign to ALL matching existing kinase modules
            matched_any = False
            for canon in list(kinase_members.keys()):
                for mf in motif_families:
                    if are_kinases_same_family(canon, mf):
                        # Add if not already confirmed or inferred in this module
                        existing_keys = {m["key"] for m in kinase_members[canon]["confirmed"]} | \
                                        {m["key"] for m in kinase_members[canon]["inferred"]}
                        if ptm_key not in existing_keys:
                            kinase_members[canon]["inferred"].append({
                                "key": ptm_key, "gene": gene.upper(),
                                "position": pos, "membership": "inferred",
                                "evidence": f"motif match ({mf})",
                            })
                        matched_any = True
                        break
            # If no existing module matched, create new module from motif family
            if not matched_any:
                for mf in motif_families:
                    canonical, display = normalize_kinase_name(mf)
                    if not canonical or len(canonical) < 3 or canonical in _KINASE_STOP_WORDS:
                        continue
                    if canonical not in kinase_members:
                        kinase_members[canonical] = {
                            "kinase": display, "canonical": canonical,
                            "sources": set(), "confirmed": [], "inferred": [],
                        }
                    kinase_members[canonical]["sources"].add("motif_prediction")
                    existing_keys = {m["key"] for m in kinase_members[canonical]["confirmed"]} | \
                                    {m["key"] for m in kinase_members[canonical]["inferred"]}
                    if ptm_key not in existing_keys:
                        kinase_members[canonical]["inferred"].append({
                            "key": ptm_key, "gene": gene.upper(),
                            "position": pos, "membership": "inferred",
                            "evidence": f"motif match ({mf})",
                        })

        # ── Step D: Format kinase module list ──
        kinase_module_list = []
        for canon, info in kinase_members.items():
            members = info["confirmed"] + info["inferred"]
            kinase_module_list.append({
                "kinase": info["kinase"], "canonical": canon,
                "sources": sorted(info["sources"]),
                "source_count": len(info["sources"]),
                "members": members,
                "confirmed_count": len(info["confirmed"]),
                "inferred_count": len(info["inferred"]),
                "total_count": len(members),
            })
        kinase_module_list.sort(key=lambda x: x["total_count"], reverse=True)

        # ══════════════════════════════════════════════════════════════════════════
        # Step D.5: Temporal Substrate Clustering + Cluster-wise KEA3 Refinement
        # ══════════════════════════════════════════════════════════════════════════
        # This step:
        #   1. Clusters ALL regulated PTM sites by temporal trajectory (global)
        #   2. Runs KEA3 enrichment per cluster to identify time-specific kinases
        #   3. Filters kinase-substrate edges: only keep substrates whose temporal
        #      cluster matches the kinase's enriched cluster(s)
        # Result: each kinase module retains only temporally-consistent substrates.
        # ══════════════════════════════════════════════════════════════════════════
        import numpy as np

        def _temporal_refinement(all_ptm_entries, kinase_module_list, enriched_data, mcp):
            """Global temporal clustering -> cluster-wise KEA3 -> edge filtering.

            Returns refined kinase_module_list with temporally-filtered members.
            Falls back to original list if clustering fails or MCP unavailable.
            """
            MIN_CLUSTER_SIZE = 5
            MAX_CLUSTERS = 6
            MIN_PTMS_FOR_REFINEMENT = 30

            # ── 1. Build global PTM timeseries matrix ──
            conditions = set()
            ptm_timeseries = {}  # ptm_key -> {cond: log2fc}
            for item in enriched_data:
                gene = (item.get("Gene.Name") or item.get("gene", "")).strip().upper()
                pos = str(item.get("PTM_Position") or item.get("position", "")).strip().upper()
                cond = item.get("Condition") or item.get("condition", "")
                log2fc = item.get("PTM_Relative_Log2FC") or item.get("ptm_relative_log2fc") or item.get("Log2FC") or item.get("log2fc")
                if not gene or not pos or not cond:
                    continue
                conditions.add(cond)
                ptm_key = f"{gene}_{pos}"
                if ptm_key not in ptm_timeseries:
                    ptm_timeseries[ptm_key] = {}
                try:
                    ptm_timeseries[ptm_key][cond] = float(log2fc) if log2fc is not None else 0.0
                except (ValueError, TypeError):
                    ptm_timeseries[ptm_key][cond] = 0.0

            conditions = sorted(conditions, key=condition_sort_key)
            n_conditions = len(conditions)
            if n_conditions < 2 or len(ptm_timeseries) < MIN_PTMS_FOR_REFINEMENT:
                logger.info(f"[Order {order_id}] Temporal refinement skipped: {len(ptm_timeseries)} PTMs, {n_conditions} conditions")
                return kinase_module_list

            # Filter: only PTMs with at least one non-zero value
            valid_ptm_keys = []
            raw_vectors = []
            for pk, ts in ptm_timeseries.items():
                row = [ts.get(c, 0.0) for c in conditions]
                if any(abs(v) >= 0.3 for v in row):  # minimum signal threshold
                    valid_ptm_keys.append(pk)
                    raw_vectors.append(row)

            n_valid = len(valid_ptm_keys)
            if n_valid < MIN_PTMS_FOR_REFINEMENT:
                logger.info(f"[Order {order_id}] Temporal refinement skipped: only {n_valid} valid PTMs")
                return kinase_module_list

            # ── 2. L2-normalize and K-Means cluster ──
            arr = np.array(raw_vectors, dtype=np.float64)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms < 1e-9] = 1.0
            arr_normed = arr / norms

            # Determine K based on dataset size
            k = min(MAX_CLUSTERS, max(2, n_valid // 100))
            k = min(k, n_valid)

            def _simple_kmeans(data, k, n_init=10, max_iter=200, seed=42):
                rng = np.random.RandomState(seed)
                n, d = data.shape
                best_labels = np.zeros(n, dtype=int)
                best_inertia = np.inf
                for _ in range(n_init):
                    # K-Means++ init
                    centers = np.empty((k, d))
                    centers[0] = data[rng.randint(n)]
                    for c in range(1, k):
                        dists = np.min(np.sum((data[:, None] - centers[:c]) ** 2, axis=2), axis=1)
                        probs = dists / (dists.sum() + 1e-12)
                        centers[c] = data[rng.choice(n, p=probs)]
                    labels = np.zeros(n, dtype=int)
                    for _ in range(max_iter):
                        dists = np.sum((data[:, None] - centers) ** 2, axis=2)
                        new_labels = np.argmin(dists, axis=1)
                        if np.array_equal(new_labels, labels):
                            break
                        labels = new_labels
                        for c in range(k):
                            mask = labels == c
                            if mask.any():
                                centers[c] = data[mask].mean(axis=0)
                    inertia = sum(np.sum((data[labels == c] - centers[c]) ** 2) for c in range(k))
                    if inertia < best_inertia:
                        best_inertia = inertia
                        best_labels = labels.copy()
                return best_labels

            try:
                labels = _simple_kmeans(arr_normed, k=k)
            except Exception as e:
                logger.warning(f"[Order {order_id}] Temporal clustering failed: {e}")
                return kinase_module_list

            # Build cluster -> PTM key mapping
            temporal_clusters = {}  # cluster_id -> {ptm_keys, centroid, pattern_label}
            for idx, label in enumerate(labels):
                label = int(label)
                if label not in temporal_clusters:
                    temporal_clusters[label] = {"ptm_keys": [], "vectors": []}
                temporal_clusters[label]["ptm_keys"].append(valid_ptm_keys[idx])
                temporal_clusters[label]["vectors"].append(raw_vectors[idx])

            # Compute centroid and assign pattern label for each cluster
            for cid, cdata in temporal_clusters.items():
                centroid = np.mean(cdata["vectors"], axis=0)
                cdata["centroid"] = centroid.tolist()
                cdata["size"] = len(cdata["ptm_keys"])
                # Pattern label: find peak condition
                peak_idx = int(np.argmax(np.abs(centroid)))
                peak_val = centroid[peak_idx]
                direction = "up" if peak_val > 0 else "down"
                cdata["pattern_label"] = f"{direction}_{conditions[peak_idx]}"
                cdata["peak_condition"] = conditions[peak_idx]
                cdata["peak_direction"] = direction
                del cdata["vectors"]  # free memory

            # Filter out tiny clusters
            temporal_clusters = {cid: c for cid, c in temporal_clusters.items()
                                 if c["size"] >= MIN_CLUSTER_SIZE}

            logger.info(
                f"[Order {order_id}] Temporal clustering: {n_valid} PTMs -> "
                f"{len(temporal_clusters)} clusters: "
                + ", ".join(f"C{cid}({c['pattern_label']}, n={c['size']})"
                           for cid, c in sorted(temporal_clusters.items()))
            )

            if not temporal_clusters:
                return kinase_module_list

            # ── 3. Cluster-wise KEA3 enrichment ──
            cluster_kinase_ranks = {}  # cluster_id -> {kinase_canonical: rank}

            if mcp:
                for cid, cdata in sorted(temporal_clusters.items()):
                    # Extract unique gene names from PTM keys (GENE_POS -> GENE)
                    gene_set = set()
                    for pk in cdata["ptm_keys"]:
                        parts = pk.rsplit("_", 1)
                        if parts:
                            gene_set.add(parts[0])
                    gene_list = sorted(gene_set)

                    if len(gene_list) < 3:
                        continue

                    try:
                        kea3_result = mcp.query_kea3(gene_list, top_n=20)
                        kinases = kea3_result.get("kinases", [])
                        rank_map = {}
                        for rank_idx, k_entry in enumerate(kinases):
                            k_name = k_entry.get("kinase", "") if isinstance(k_entry, dict) else str(k_entry)
                            if k_name:
                                canonical, _ = normalize_kinase_name(k_name)
                                if canonical:
                                    rank_map[canonical] = rank_idx + 1
                        cluster_kinase_ranks[cid] = rank_map
                        logger.info(
                            f"[Order {order_id}] KEA3 cluster C{cid} ({cdata['pattern_label']}): "
                            f"{len(gene_list)} genes -> {len(kinases)} kinases enriched"
                        )
                    except Exception as e:
                        logger.warning(f"[Order {order_id}] KEA3 failed for cluster C{cid}: {e}")
                        continue
            else:
                logger.info(f"[Order {order_id}] No MCP client — skipping cluster-wise KEA3")

            # ── 4. Temporal Edge Filtering ──
            # For each kinase module, keep only substrates that belong to a temporal
            # cluster where the kinase is enriched (KEA3 rank <= 20).
            ptm_to_cluster = {}  # ptm_key -> cluster_id
            for cid, cdata in temporal_clusters.items():
                for pk in cdata["ptm_keys"]:
                    ptm_to_cluster[pk] = cid

            refined_modules = []
            for km in kinase_module_list:
                kinase_canon = km.get("canonical", "")
                members = km.get("members", [])
                if not members:
                    continue

                # Determine which clusters this kinase is enriched in
                enriched_clusters = set()
                if cluster_kinase_ranks:
                    for cid, rank_map in cluster_kinase_ranks.items():
                        if kinase_canon in rank_map:
                            enriched_clusters.add(cid)
                    # Also check family-level matches
                    if not enriched_clusters:
                        for cid, rank_map in cluster_kinase_ranks.items():
                            for ranked_kinase in rank_map:
                                if are_kinases_same_family(kinase_canon, ranked_kinase):
                                    enriched_clusters.add(cid)
                                    break

                # Filter members
                filtered_members = []
                for m in members:
                    ptm_key = m.get("key", f"{m.get('gene', '').upper()}_{str(m.get('position', '')).upper()}")
                    cid = ptm_to_cluster.get(ptm_key)
                    if cid is None:
                        # PTM not in any temporal cluster (below signal threshold)
                        # Keep confirmed members even if below threshold
                        if m.get("membership") == "confirmed":
                            filtered_members.append(m)
                        continue
                    if enriched_clusters:
                        # KEA3-based filtering: keep if in enriched cluster
                        if cid in enriched_clusters:
                            filtered_members.append(m)
                    else:
                        # No KEA3 data: keep all clustered members (no filtering)
                        filtered_members.append(m)

                # Ensure minimum substrate count (don't over-filter)
                MIN_FILTERED = 5
                if len(filtered_members) < MIN_FILTERED:
                    # Fall back to original members
                    filtered_members = members
                    temporal_filter_applied = False
                else:
                    temporal_filter_applied = True

                # Build refined module
                refined_km = dict(km)
                refined_km["members"] = filtered_members
                refined_km["confirmed_count"] = sum(1 for m in filtered_members if m.get("membership") == "confirmed")
                refined_km["inferred_count"] = sum(1 for m in filtered_members if m.get("membership") == "inferred")
                refined_km["total_count"] = len(filtered_members)
                refined_km["temporal_filter_applied"] = temporal_filter_applied
                refined_km["original_total_count"] = len(members)
                if enriched_clusters:
                    refined_km["enriched_clusters"] = sorted(enriched_clusters)
                    refined_km["enriched_patterns"] = [
                        temporal_clusters[cid]["pattern_label"]
                        for cid in sorted(enriched_clusters)
                        if cid in temporal_clusters
                    ]
                refined_modules.append(refined_km)

            refined_modules.sort(key=lambda x: x["total_count"], reverse=True)

            # Log summary
            n_filtered = sum(1 for m in refined_modules if m.get("temporal_filter_applied"))
            avg_reduction = 0.0
            if n_filtered > 0:
                reductions = [
                    1 - (m["total_count"] / max(m["original_total_count"], 1))
                    for m in refined_modules if m.get("temporal_filter_applied")
                ]
                avg_reduction = sum(reductions) / len(reductions)
            logger.info(
                f"[Order {order_id}] Temporal refinement: {n_filtered}/{len(refined_modules)} modules filtered, "
                f"avg substrate reduction: {avg_reduction:.1%}"
            )

            return refined_modules

        # Execute temporal refinement
        try:
            kinase_module_list = _temporal_refinement(
                all_ptm_entries, kinase_module_list, enriched_data, mcp_client
            )
            publish_progress(order_id, "rag_enrichment", "global_analysis", "running", 93,
                             "Temporal substrate refinement completed")
        except Exception as e:
            logger.warning(f"[Order {order_id}] Temporal refinement failed (non-fatal): {e}")
            import traceback as _tb2
            logger.warning(f"[Order {order_id}] Traceback: {_tb2.format_exc()}")

        # ── Step E: Summary ──
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

        # Compute cache hash compatible with global-kinase-modules API endpoint
        import hashlib as _hashlib
        _ptm_keys_sorted = sorted(f"{g.upper()}_{str(p).upper()}" for g, p, _ in all_ptm_entries)
        _cache_input_str = f"{len(all_ptm_entries)}|{'|'.join(_ptm_keys_sorted[:50])}"
        _cache_hash = _hashlib.md5(_cache_input_str.encode()).hexdigest()[:12]

        kinase_result = {
            "kinase_modules": kinase_module_list,
            "temporal_cascade": {"timepoints": [], "kinase_activity": [], "cascade_flow": []},
            "summary": summary,
            "source": "pipeline_auto",
            "_cache_hash": _cache_hash,
        }

        # Build activity heatmap
        heatmap_data = _compute_kinase_activity_heatmap(
            enriched_data,
            kinase_result,
            ptm_type,
            temporal_source=config,
        )

        # Persist to DB
        from common.db_engine import get_engine as _get_engine
        from sqlalchemy import text as _text
        _engine = _get_engine()
        with _engine.connect() as _conn:
            _conn.execute(
                _text(
                    "UPDATE orders SET kinase_analysis_data = :kad, "
                    "kinase_activity_heatmap = :kah WHERE id = :oid"
                ),
                {
                    "oid": order_id,
                    "kad": json.dumps(kinase_result, default=str),
                    "kah": json.dumps(heatmap_data, default=str),
                },
            )
            _conn.commit()

        elapsed = round(time.time() - t0, 1)
        n_modules = kinase_result.get("summary", {}).get("total_kinase_modules", 0)
        logger.info(
            f"[Order {order_id}] Auto global analysis: {n_modules} kinase modules, "
            f"heatmap with {len(heatmap_data.get('kinase_scores', []))} kinases in {elapsed}s"
        )
        publish_progress(order_id, "rag_enrichment", "global_analysis", "completed", 95,
                         f"Global analysis done: {n_modules} modules ({elapsed}s)")

        # ── v11.5f: Auto-run Receptor Inference ──────────────────────────────
        receptor_inference_result = {}
        try:
            from common.receptor_inference import run_receptor_inference
            receptor_inference_result = run_receptor_inference(
                order_id=order_id,
                enriched_data=enriched_data,
                kinase_analysis_data=kinase_result,
                config=config,
            )
            if receptor_inference_result:
                logger.info(
                    f"[Order {order_id}] Auto receptor inference: "
                    f"{len(receptor_inference_result.get('receptors', []))} receptors inferred"
                )
        except Exception as _rec_err:
            logger.warning(
                f"[Order {order_id}] Auto receptor inference failed (non-fatal): {_rec_err}"
            )
            import traceback as _rec_tb
            logger.warning(f"[Order {order_id}] Receptor traceback: {_rec_tb.format_exc()}")

        return {
            "kinase_analysis_data": kinase_result,
            "kinase_activity_heatmap": heatmap_data,
            "receptor_inference_data": receptor_inference_result,
        }
    except Exception as e:
        logger.warning(f"[Order {order_id}] Auto global analysis failed (non-fatal): {e}")
        import traceback as _tb
        logger.warning(f"[Order {order_id}] Traceback: {_tb.format_exc()}")
        publish_progress(order_id, "rag_enrichment", "global_analysis", "completed", 95,
                         f"Global analysis skipped: {e}")
        return {}


# ── v11.3.2: Nuclear-Exclusive Substrate Evidence ──────────────────────────────
_NUCLEAR_TIER1_GENES: set = {
    # Histones — the most definitive nuclear markers
    "H2AFX", "H2AFZ", "H2AFY", "H2AFY2", "H2AFB1",
    "H2BC1", "H2BC3", "H2BC4", "H2BC5", "H2BC6", "H2BC7", "H2BC8",
    "H2BC9", "H2BC10", "H2BC11", "H2BC12", "H2BC13", "H2BC14", "H2BC15",
    "H2BC17", "H2BC18", "H2BC21",
    "H2AC1", "H2AC4", "H2AC6", "H2AC7", "H2AC8", "H2AC11",
    "H2AC12", "H2AC13", "H2AC14", "H2AC15", "H2AC16", "H2AC17",
    "H2AC18", "H2AC19", "H2AC20", "H2AC21",
    "H3C1", "H3C2", "H3C3", "H3C4", "H3C6", "H3C7", "H3C8",
    "H3C10", "H3C11", "H3C12", "H3C13", "H3C14", "H3C15",
    "H4C1", "H4C2", "H4C3", "H4C4", "H4C5", "H4C6", "H4C8",
    "H4C9", "H4C11", "H4C12", "H4C13", "H4C14", "H4C15", "H4C16",
    "H1-0", "H1-1", "H1-2", "H1-3", "H1-4", "H1-5", "H1-6", "H1-10",
    # Legacy HIST nomenclature
    "HIST1H1A", "HIST1H1B", "HIST1H1C", "HIST1H1D", "HIST1H1E",
    "HIST1H2AA", "HIST1H2AB", "HIST1H2AC", "HIST1H2AD", "HIST1H2AE",
    "HIST1H2AG", "HIST1H2AH", "HIST1H2AI", "HIST1H2AJ", "HIST1H2AK",
    "HIST1H2AL", "HIST1H2AM",
    "HIST1H2BA", "HIST1H2BB", "HIST1H2BC", "HIST1H2BD", "HIST1H2BE",
    "HIST1H2BF", "HIST1H2BG", "HIST1H2BH", "HIST1H2BI", "HIST1H2BJ",
    "HIST1H2BK", "HIST1H2BL", "HIST1H2BM", "HIST1H2BN", "HIST1H2BO",
    "HIST1H3A", "HIST1H3B", "HIST1H3C", "HIST1H3D", "HIST1H3E",
    "HIST1H3F", "HIST1H3G", "HIST1H3H", "HIST1H3I", "HIST1H3J",
    "HIST1H4A", "HIST1H4B", "HIST1H4C", "HIST1H4D", "HIST1H4E",
    "HIST1H4F", "HIST1H4G", "HIST1H4H", "HIST1H4I", "HIST1H4J",
    "HIST1H4K", "HIST1H4L",
    "HIST2H2AA3", "HIST2H2AB", "HIST2H2AC", "HIST2H2BE", "HIST2H3A",
    "HIST2H3C", "HIST2H3D", "HIST2H4A", "HIST2H4B",
    "HIST3H2A", "HIST3H2BB", "HIST3H3",
    "H3F3A", "H3F3B", "H3F3C",
    "CENPA", "MACROH2A1", "MACROH2A2",
    # Nuclear Lamins
    "LMNA", "LMNB1", "LMNB2",
    # RNA Pol II
    "POLR2A",
    # DNA Replication
    "PCNA",
    # DNA Repair
    "PARP1", "XRCC5", "XRCC6", "PRKDC",
    # Nucleolar
    "FBL", "NCL", "NPM1",
}
_NUCLEAR_TIER2_GENES: set = {
    # Splicing factors
    "SRSF1", "SRSF2", "SRSF3", "SRSF4", "SRSF5", "SRSF6", "SRSF7",
    "SRSF8", "SRSF9", "SRSF10", "SRSF11", "SRSF12",
    "SRRM1", "SRRM2", "U2AF1", "U2AF2", "SF3B1", "SF3A1",
    "SNRPD1", "SNRPD2", "SNRPD3", "SNRPE", "SNRPF", "SNRPG",
    "PRPF8", "PRPF19", "PRPF31", "PRPF40A",
    # Chromatin remodeling
    "SMARCA4", "SMARCA2", "SMARCC1", "SMARCC2",
    "CHD1", "CHD3", "CHD4",
    "HDAC1", "HDAC2", "KAT2A", "KAT2B", "EP300", "CREBBP",
    # DNA repair & replication
    "BRCA1", "BRCA2", "RAD51", "RAD50", "NBN", "MRE11",
    "ATR", "ATRIP", "CHEK1", "CHEK2",
    "RPA1", "RPA2", "RPA3",
    "MCM2", "MCM3", "MCM4", "MCM5", "MCM6", "MCM7",
    "ORC1", "ORC2", "ORC3", "ORC4", "ORC5", "ORC6",
    # Transcription factors
    "TP53", "RB1", "MYC", "MYCN",
    "JUN", "FOS", "JUNB", "JUND", "FOSB", "FOSL1", "FOSL2",
    "SP1", "SP3", "E2F1", "E2F2", "E2F3", "E2F4",
    # Mediator
    "MED1", "MED12", "MED14", "MED15", "MED23", "MED24",
    # Cohesin/Condensin
    "SMC1A", "SMC3", "RAD21", "STAG1", "STAG2",
    "SMC2", "SMC4", "NCAPD2", "NCAPG", "NCAPH",
    # Topoisomerases
    "TOP1", "TOP2A", "TOP2B",
}


def _compute_nuclear_evidence(substrate_genes: list) -> dict:
    """Compute nuclear evidence score from substrate gene list.
    Returns dict with tier1/tier2 hits, total score, and matched gene names."""
    t1_hits = []
    t2_hits = []
    for g in substrate_genes:
        gu = g.upper() if g else ""
        if gu in _NUCLEAR_TIER1_GENES:
            t1_hits.append(gu)
        elif gu in _NUCLEAR_TIER2_GENES:
            t2_hits.append(gu)
    score = len(t1_hits) * 2 + len(t2_hits)
    return {
        "score": score,
        "tier1_count": len(t1_hits),
        "tier2_count": len(t2_hits),
        "tier1_genes": sorted(set(t1_hits)),
        "tier2_genes": sorted(set(t2_hits)),
    }


def _compute_kinase_activity_heatmap(
    enriched_data: list,
    kinase_result: dict,
    ptm_type: str,
    temporal_source: dict | None = None,
) -> dict:
    """Compute per-kinase per-condition weighted activity scores from enriched PTM data.

    v11.0: Substrate Temporal Clustering
    ------------------------------------
    Instead of naively averaging all substrates (which causes signal cancellation
    when substrates have opposing temporal patterns), we:
      1. Cluster substrates by L2-normalized temporal trajectory (K-Means)
      2. Score each cluster independently per condition
      3. Select the dominant cluster (highest coherence × signal strength)
      4. Report dominant cluster metrics as the kinase's primary activity
      5. Preserve all cluster details for frontend drill-down
    """
    import numpy as np
    from ptm_shared.temporal_contract import resolve_temporal_contract

    temporal = resolve_temporal_contract(temporal_source)

    # ── Pure-numpy K-Means (no sklearn dependency) ──
    def _numpy_kmeans(data: np.ndarray, k: int, n_init: int = 10,
                      max_iter: int = 300, seed: int = 42) -> np.ndarray:
        """K-Means clustering using only numpy. Returns label array."""
        rng = np.random.RandomState(seed)
        n_samples, n_features = data.shape
        best_labels = np.zeros(n_samples, dtype=int)
        best_inertia = np.inf

        for _ in range(n_init):
            # K-Means++ initialization
            centers = np.empty((k, n_features), dtype=data.dtype)
            idx = rng.randint(0, n_samples)
            centers[0] = data[idx]
            for c in range(1, k):
                dists = np.min(
                    np.sum((data[:, None, :] - centers[None, :c, :]) ** 2, axis=2),
                    axis=1,
                )
                probs = dists / max(dists.sum(), 1e-12)
                idx = rng.choice(n_samples, p=probs)
                centers[c] = data[idx]

            # Iterate
            labels = np.zeros(n_samples, dtype=int)
            for _it in range(max_iter):
                # Assign
                dists = np.sum(
                    (data[:, None, :] - centers[None, :, :]) ** 2, axis=2
                )  # (n_samples, k)
                new_labels = np.argmin(dists, axis=1)
                if np.array_equal(new_labels, labels) and _it > 0:
                    break
                labels = new_labels
                # Update centers
                for ci in range(k):
                    mask = labels == ci
                    if mask.any():
                        centers[ci] = data[mask].mean(axis=0)

            inertia = sum(
                np.sum((data[labels == ci] - centers[ci]) ** 2)
                for ci in range(k)
            )
            if inertia < best_inertia:
                best_inertia = inertia
                best_labels = labels.copy()

        return best_labels

    # Extract conditions from enriched data
    conditions = set()
    ptm_values = {}  # key: (gene, position, condition) -> log2fc
    ptm_qvalues = {}  # key: (gene, position, condition) -> q_value
    ptm_de_novo = set()  # (gene, position) that are de_novo

    for item in enriched_data:
        gene = (item.get("Gene.Name") or item.get("gene", "")).strip().upper()
        pos = str(item.get("PTM_Position") or item.get("position", "")).strip().upper()
        cond = item.get("Condition") or item.get("condition", "")
        log2fc = item.get("PTM_Relative_Log2FC") or item.get("ptm_relative_log2fc") or item.get("Log2FC") or item.get("log2fc")
        q_val = item.get("Q_Value") or item.get("q_value")
        is_pseudo = item.get("Control_Pseudocount_Used", False)

        if not gene or not pos or not cond:
            continue
        conditions.add(cond)
        try:
            raw_fc = float(log2fc) if log2fc is not None else 0.0
        except (ValueError, TypeError):
            raw_fc = 0.0
        # v11.2: Store raw Log2FC (no cap). Winsorization applied per-kinase during scoring.
        ptm_values[(gene, pos, cond)] = raw_fc
        try:
            ptm_qvalues[(gene, pos, cond)] = float(q_val) if q_val is not None else 1.0
        except (ValueError, TypeError):
            ptm_qvalues[(gene, pos, cond)] = 1.0
        if is_pseudo:
            ptm_de_novo.add((gene, pos))

    conditions = sorted(conditions, key=condition_sort_key)
    if not conditions:
        return {"kinase_scores": [], "conditions": [], "_cached": True}

    n_conditions = len(conditions)

    # Activity class weights
    def _get_weight(gene, pos, cond):
        key = (gene, pos)
        if key in ptm_de_novo:
            return 1.5  # de_novo
        q = ptm_qvalues.get((gene, pos, cond), 1.0)
        fc = abs(ptm_values.get((gene, pos, cond), 0))
        if q < 0.05 and fc >= 1.0:
            return 1.2  # regulated
        if fc >= 0.5:
            return 1.0  # coordinated-eligible
        return 0.5  # minor

    # ── Helper: compute weighted score for a subset of members per condition ──
    WINSORIZE_LOWER = 5   # percentile
    WINSORIZE_UPPER = 95  # percentile

    def _score_members(member_list, conditions):
        """Return {cond: Winsorized weighted_avg_score} for given members.
        v11.2: Applies per-condition Winsorization (5th/95th percentile) before
        weighted averaging to prevent extreme outliers from dominating."""
        scores = {}
        for cond in conditions:
            # Collect raw values for Winsorization bounds
            raw_vals = [ptm_values.get((g, p, cond), 0.0) for g, p in member_list]
            non_zero = [v for v in raw_vals if v != 0.0]
            if len(non_zero) >= 5:
                arr_v = np.array(non_zero)
                lo = float(np.percentile(arr_v, WINSORIZE_LOWER))
                hi = float(np.percentile(arr_v, WINSORIZE_UPPER))
            else:
                lo, hi = -1e9, 1e9  # no Winsorization for tiny sets

            wsum, wtot = 0.0, 0.0
            for g, p in member_list:
                val_raw = ptm_values.get((g, p, cond), 0.0)
                # Apply Winsorization
                val = max(lo, min(hi, val_raw))
                w = _get_weight(g, p, cond)
                wsum += val * w
                wtot += w
            scores[cond] = round(wsum / max(wtot, 1e-9), 4)
        return scores

    # ── Helper: compute coherence for a subset of members ──
    def _compute_coherence(member_list, conditions):
        """Return mean pairwise Pearson r for member trajectories."""
        vectors = []
        for g, p in member_list:
            row = [ptm_values.get((g, p, c), 0.0) for c in conditions]
            if any(v != 0 for v in row):
                vectors.append(row)
        if len(vectors) < 2:
            return 0.0
        try:
            arr = np.array(vectors)
            corr_matrix = np.corrcoef(arr)
            n = corr_matrix.shape[0]
            upper = [corr_matrix[i][j] for i in range(n) for j in range(i + 1, n)
                     if not np.isnan(corr_matrix[i][j])]
            return round(float(np.mean(upper)), 3) if upper else 0.0
        except Exception:
            return 0.0

    # ── Helper: cluster substrates by temporal trajectory shape ──
    # v11.3: Stratified Clustering (Magnitude Tiers) + Absolute Correlation
    MIN_SUBSTRATES_FOR_CLUSTERING = 10

    # Magnitude tier thresholds
    TIER1_THRESHOLD = 5.0   # De novo / Strong: max |Log2FC| > 5.0
    TIER2_THRESHOLD = 2.0   # Regulated / Moderate: 2.0 < max |Log2FC| <= 5.0
    # Tier 3: max |Log2FC| <= 2.0 (Minor / Weak)

    def _assign_tier(member_vector):
        """Assign magnitude tier based on max absolute Log2FC across conditions."""
        max_abs = max(abs(v) for v in member_vector)
        if max_abs > TIER1_THRESHOLD:
            return 1  # Strong / De novo
        elif max_abs > TIER2_THRESHOLD:
            return 2  # Regulated / Moderate
        else:
            return 3  # Minor / Weak

    def _abs_corr_distance(arr_normed):
        """Compute distance matrix using 1 - |Pearson r| (absolute correlation).

        This groups substrates with the SAME temporal shape regardless of sign:
        [+2, +4, +3, +1] and [-2, -4, -3, -1] will cluster together (|r| = 1.0).
        After clustering, we tag members as 'positive' or 'negative' targets.
        """
        n = arr_normed.shape[0]
        corr = np.corrcoef(arr_normed)
        # Handle NaN (constant rows)
        corr = np.nan_to_num(corr, nan=0.0)
        # Distance = 1 - |r|
        dist = 1.0 - np.abs(corr)
        np.fill_diagonal(dist, 0.0)
        return dist

    def _kmeans_with_abs_corr(arr_normed, k, n_init=10, max_iter=300, seed=42):
        """K-Means using 1 - |r| as distance metric.

        Standard K-Means uses Euclidean distance. To use correlation-based distance,
        we transform the data: project onto unit sphere in correlation space.
        For absolute correlation, we additionally take abs of normalized vectors
        before clustering (so anti-correlated patterns map to same direction).
        """
        # Strategy: fold sign — map all vectors to positive-dominant direction
        # then cluster by Euclidean on L2-normed folded vectors
        n, d = arr_normed.shape

        # For each vector, if sum < 0, flip sign (fold into positive half-space)
        folded = arr_normed.copy()
        for i in range(n):
            if np.sum(folded[i]) < 0:
                folded[i] = -folded[i]

        # Re-normalize after folding
        norms = np.linalg.norm(folded, axis=1, keepdims=True)
        norms[norms < 1e-9] = 1.0
        folded = folded / norms

        # Standard K-Means on folded vectors
        return _numpy_kmeans(folded, k=k, n_init=n_init, max_iter=max_iter, seed=seed)

    def _compute_coherence_abs(member_list, conditions):
        """Compute coherence using absolute Pearson r.

        This correctly handles anti-correlated substrates within the same
        regulatory module (e.g., kinase activates some, inhibits others).
        Returns mean pairwise |r| for member trajectories.
        """
        vectors = []
        for g, p in member_list:
            row = [ptm_values.get((g, p, c), 0.0) for c in conditions]
            if any(v != 0 for v in row):
                vectors.append(row)
        if len(vectors) < 2:
            return 0.0
        try:
            arr = np.array(vectors)
            corr_matrix = np.corrcoef(arr)
            n = corr_matrix.shape[0]
            upper = [abs(corr_matrix[i][j]) for i in range(n) for j in range(i + 1, n)
                     if not np.isnan(corr_matrix[i][j])]
            return round(float(np.mean(upper)), 3) if upper else 0.0
        except Exception:
            return 0.0

    def _tag_sign_groups(member_list, conditions):
        """Tag each member as 'positive' or 'negative' target based on net FC direction.

        Within an absolute-correlation cluster, some substrates go up and some go down.
        This separates them for biological interpretation.
        """
        positive_targets = []
        negative_targets = []
        for g, p in member_list:
            net_fc = sum(ptm_values.get((g, p, c), 0.0) for c in conditions)
            if net_fc >= 0:
                positive_targets.append((g, p))
            else:
                negative_targets.append((g, p))
        return positive_targets, negative_targets

    def _cluster_substrates(members, conditions):
        """Cluster substrates using Stratified (Magnitude Tier) + Absolute Correlation.

        v11.3 Algorithm:
          1. Assign each substrate to a Magnitude Tier (Strong/Moderate/Weak)
          2. Within each tier, cluster by absolute-correlation K-Means
             (anti-correlated substrates group together)
          3. Tag positive/negative targets within each cluster
          4. Score each sub-cluster independently
          5. Select dominant cluster across all tiers

        Returns list of clusters with sign-tagged members.
        """
        # Build trajectory matrix
        valid_members = []  # [(gene, pos)]
        raw_vectors = []    # [[fc_cond1, fc_cond2, ...]]
        for m in members:
            g = m.get("gene", "").upper()
            p = str(m.get("position", "")).upper()
            row = [ptm_values.get((g, p, c), 0.0) for c in conditions]
            if any(v != 0 for v in row):
                valid_members.append((g, p))
                raw_vectors.append(row)

        if not valid_members:
            return []

        n_subs = len(valid_members)

        # ── Single-cluster fallback ──
        if n_subs < MIN_SUBSTRATES_FOR_CLUSTERING or n_conditions < 2:
            scores = _score_members(valid_members, conditions)
            coh = _compute_coherence_abs(valid_members, conditions)
            peak_c = max(conditions, key=lambda c: abs(scores.get(c, 0)))
            peak_s = scores.get(peak_c, 0)
            direction = "activation" if peak_s > 0.3 else ("inactivation" if peak_s < -0.3 else "neutral")
            pos_targets, neg_targets = _tag_sign_groups(valid_members, conditions)
            return [{
                "cluster_id": 0,
                "member_keys": valid_members,
                "size": n_subs,
                "scores": scores,
                "coherence": coh,
                "peak_condition": peak_c,
                "peak_score": peak_s,
                "direction": direction,
                "is_dominant": True,
                "tier": "mixed",
                "positive_targets": len(pos_targets),
                "negative_targets": len(neg_targets),
            }]

        # ── Step 1: Assign Magnitude Tiers ──
        tiers = {1: [], 2: [], 3: []}  # tier -> [(idx, (gene, pos), vector)]
        for idx, (member, vec) in enumerate(zip(valid_members, raw_vectors)):
            tier = _assign_tier(vec)
            tiers[tier].append((idx, member, vec))

        # ── Step 2: Cluster within each tier using absolute correlation ──
        all_clusters = []
        cluster_id_counter = 0

        tier_names = {1: "strong", 2: "moderate", 3: "weak"}

        for tier_num in [1, 2, 3]:
            tier_data = tiers[tier_num]
            if not tier_data:
                continue

            tier_members = [(d[1][0], d[1][1]) for d in tier_data]
            tier_vectors = [d[2] for d in tier_data]
            n_tier = len(tier_members)

            if n_tier < MIN_SUBSTRATES_FOR_CLUSTERING:
                # Too few for clustering — treat as single cluster
                scores = _score_members(tier_members, conditions)
                coh = _compute_coherence_abs(tier_members, conditions)
                peak_c = max(conditions, key=lambda c: abs(scores.get(c, 0)))
                peak_s = scores.get(peak_c, 0)
                direction = "activation" if peak_s > 0.3 else ("inactivation" if peak_s < -0.3 else "neutral")
                pos_targets, neg_targets = _tag_sign_groups(tier_members, conditions)

                # Dominant selection score
                dominance = max(coh, 0.01) * (n_tier ** 0.5) * max(abs(peak_s), 0.01)

                all_clusters.append({
                    "cluster_id": cluster_id_counter,
                    "member_keys": tier_members,
                    "size": n_tier,
                    "scores": scores,
                    "coherence": coh,
                    "peak_condition": peak_c,
                    "peak_score": peak_s,
                    "direction": direction,
                    "is_dominant": False,
                    "tier": tier_names[tier_num],
                    "positive_targets": len(pos_targets),
                    "negative_targets": len(neg_targets),
                    "_dominance_score": round(dominance, 4),
                })
                cluster_id_counter += 1
                continue

            # L2-normalize for shape-based clustering
            arr = np.array(tier_vectors, dtype=np.float64)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms < 1e-9] = 1.0
            arr_normed = arr / norms

            # K within tier: scale with tier size, cap at 3
            k_tier = min(3, max(2, n_tier // 30))
            k_tier = min(k_tier, n_tier)

            try:
                labels = _kmeans_with_abs_corr(arr_normed, k=k_tier, n_init=10, max_iter=300, seed=42)
            except Exception:
                labels = np.zeros(n_tier, dtype=int)

            # Build sub-clusters within this tier
            tier_cluster_members = {}  # label -> [(gene, pos)]
            for idx, label in enumerate(labels):
                label = int(label)
                tier_cluster_members.setdefault(label, []).append(tier_members[idx])

            for sub_cid, c_members in sorted(tier_cluster_members.items()):
                c_size = len(c_members)
                if c_size < 2:
                    continue  # skip singleton clusters

                c_scores = _score_members(c_members, conditions)
                c_coh = _compute_coherence_abs(c_members, conditions)
                c_peak_c = max(conditions, key=lambda c: abs(c_scores.get(c, 0)))
                c_peak_s = c_scores.get(c_peak_c, 0)
                c_dir = "activation" if c_peak_s > 0.3 else ("inactivation" if c_peak_s < -0.3 else "neutral")
                pos_targets, neg_targets = _tag_sign_groups(c_members, conditions)

                # Dominant selection: coherence × √size × |peak_score|
                # Tier 1 (strong) gets 2x bonus, Tier 2 gets 1.5x
                tier_bonus = {1: 2.0, 2: 1.5, 3: 1.0}[tier_num]
                dominance = max(c_coh, 0.01) * (c_size ** 0.5) * max(abs(c_peak_s), 0.01) * tier_bonus

                all_clusters.append({
                    "cluster_id": cluster_id_counter,
                    "member_keys": c_members,
                    "size": c_size,
                    "scores": c_scores,
                    "coherence": c_coh,
                    "peak_condition": c_peak_c,
                    "peak_score": c_peak_s,
                    "direction": c_dir,
                    "is_dominant": False,
                    "tier": tier_names[tier_num],
                    "positive_targets": len(pos_targets),
                    "negative_targets": len(neg_targets),
                    "_dominance_score": round(dominance, 4),
                })
                cluster_id_counter += 1

        # ── Step 3: Select dominant cluster across all tiers ──
        if not all_clusters:
            # Extreme fallback: no valid clusters formed
            scores = _score_members(valid_members, conditions)
            coh = _compute_coherence_abs(valid_members, conditions)
            peak_c = max(conditions, key=lambda c: abs(scores.get(c, 0)))
            peak_s = scores.get(peak_c, 0)
            direction = "activation" if peak_s > 0.3 else ("inactivation" if peak_s < -0.3 else "neutral")
            return [{
                "cluster_id": 0,
                "member_keys": valid_members,
                "size": n_subs,
                "scores": scores,
                "coherence": coh,
                "peak_condition": peak_c,
                "peak_score": peak_s,
                "direction": direction,
                "is_dominant": True,
                "tier": "mixed",
                "positive_targets": n_subs,
                "negative_targets": 0,
            }]

        # Find dominant by dominance score
        best_idx = max(range(len(all_clusters)), key=lambda i: all_clusters[i]["_dominance_score"])
        all_clusters[best_idx]["is_dominant"] = True

        return all_clusters

    # ══════════════════════════════════════════════════════════════════════════
    # Build kinase -> PTM mapping from kinase_result
    # ══════════════════════════════════════════════════════════════════════════
    kinase_modules = kinase_result.get("kinase_modules", kinase_result.get("kinase_module_list", []))
    kinase_scores = []

    # v11.3.5: Filter out non-kinase entries (drugs, cyclins, etc.)
    _NON_KINASE_BLACKLIST = {
        "RAPAMYCIN", "WORTMANNIN", "STAUROSPORINE", "INSULIN",
        "NOCODAZOLE", "TAXOL", "PACLITAXEL", "DOXORUBICIN",
        "CISPLATIN", "ETOPOSIDE", "CAMPTOTHECIN", "THAPSIGARGIN",
        "PHORBOL", "PMA", "TPA", "EGF", "PDGF", "FGF", "NGF",
        "TNF", "TNFA", "IL1", "IL6", "IFNG", "LPS",
        "OKADAIC ACID", "CALYCULIN", "PERVANADATE",
        "SORBITOL", "ANISOMYCIN", "ARSENITE",
        "UV", "IONIZING RADIATION", "GAMMA RADIATION",
        "CYCLIN", "CYCLIN A", "CYCLIN B", "CYCLIN D", "CYCLIN E",
        "CYCLIN A1", "CYCLIN A2", "CYCLIN B1", "CYCLIN B2",
        "CYCLIN D1", "CYCLIN D2", "CYCLIN D3",
        "CYCLIN E1", "CYCLIN E2",
        "KINASE", "PHOSPHATASE", "PROTEASE", "LIGASE",
        "RECEPTOR", "CHANNEL", "TRANSPORTER",
    }
    def _is_non_kinase(name: str) -> bool:
        upper = name.upper()
        if upper in _NON_KINASE_BLACKLIST:
            return True
        for bl in _NON_KINASE_BLACKLIST:
            if upper.startswith(bl + " ") or upper.startswith(bl + "/"):
                return True
        return False

    kinase_modules = [
        km for km in kinase_modules
        if not _is_non_kinase(km.get("kinase", ""))
    ]

    for km in kinase_modules:
        kinase_name = km.get("kinase", "")
        members = km.get("members", [])
        if not kinase_name or not members:
            continue

        # ── v11.0: Cluster substrates by temporal trajectory ──
        clusters = _cluster_substrates(members, conditions)
        if not clusters:
            continue

        # Find dominant cluster
        dominant = next((c for c in clusters if c["is_dominant"]), clusters[0])

        # Use dominant cluster's metrics as the kinase's primary activity
        scores = dominant["scores"]
        peak_cond = dominant["peak_condition"]
        peak_score = dominant["peak_score"]
        coherence = dominant["coherence"]
        direction = dominant["direction"]

        confidence = km.get("confidence_score", 0.5)

        # Serialize cluster_details for output (strip member_keys to save space)
        cluster_details = []
        for cl in clusters:
            cluster_details.append({
                "cluster_id": cl["cluster_id"],
                "size": cl["size"],
                "scores": cl["scores"],
                "coherence": cl["coherence"],
                "peak_condition": cl["peak_condition"],
                "peak_score": round(cl["peak_score"], 4),
                "direction": cl["direction"],
                "is_dominant": cl["is_dominant"],
            })

        # v11.3.2: Compute nuclear evidence from ALL substrates
        all_substrate_genes = [m.get("gene", "") for m in members]
        nuclear_ev = _compute_nuclear_evidence(all_substrate_genes)
        # v11.3.4b: Annotate each nuclear marker gene with cluster membership
        if nuclear_ev["score"] > 0:
            _gene_cluster_map: dict[str, int] = {}
            for cl in clusters:
                cl_id = cl.get("cluster_id", 0)
                for pk in cl.get("ptm_keys", []):
                    gene_part = pk.split("_")[0].upper() if "_" in pk else pk.upper()
                    _gene_cluster_map[gene_part] = cl_id
            dominant_cluster_id = dominant.get("cluster_id", 0)
            nuclear_ev["tier1_details"] = [
                {"gene": g, "in_dominant": _gene_cluster_map.get(g, -1) == dominant_cluster_id}
                for g in nuclear_ev["tier1_genes"]
            ]
            nuclear_ev["tier2_details"] = [
                {"gene": g, "in_dominant": _gene_cluster_map.get(g, -1) == dominant_cluster_id}
                for g in nuclear_ev["tier2_genes"]
            ]

        # v11.3.1: Collect same-time clusters (same peak as parent) for tooltip
        same_time_clusters: list = []
        if len(clusters) >= 2:
            for _stc_cl in clusters:
                if _stc_cl["is_dominant"]:
                    continue
                if _stc_cl["size"] < 3:
                    continue
                _stc_peak = _stc_cl.get("peak_condition", "")
                _stc_peak_score = _stc_cl.get("peak_score", 0.0)
                if abs(_stc_peak_score) < 0.3:
                    continue
                if _stc_peak == peak_cond:
                    same_time_clusters.append({
                        "tier": _stc_cl.get("tier", "mixed"),
                        "size": _stc_cl["size"],
                        "peak_score": round(_stc_peak_score, 4),
                        "substrates": [
                            {"gene": gp[0], "site": gp[1]}
                            for gp in _stc_cl.get("member_keys", [])[:10]
                        ],
                    })

        # v11.3: Build substrate list from dominant cluster
        substrates_list = [
            {
                "ptm_key": f"{gp[0]}_{gp[1]}",
                "gene": gp[0],
                "site": gp[1],
                "peak_fc": round(float(max((ptm_values.get((gp[0], gp[1], c), 0.0) for c in conditions), key=abs, default=0.0)), 3),
                "temporal": {c: round(ptm_values.get((gp[0], gp[1], c), 0.0), 3) for c in conditions},
                "peak_condition": max(conditions, key=lambda c, _g=gp[0], _s=gp[1]: abs(ptm_values.get((_g, _s, c), 0.0))) if conditions else "",
                "cluster": "dominant",
            }
            for gp in dominant.get("member_keys", [])
        ]
        # v11.3.4b: Add nuclear marker substrates from non-dominant clusters with temporal data
        for cl in clusters:
            if cl["is_dominant"]:
                continue
            for gp in cl.get("member_keys", []):
                gene_upper = gp[0].upper()
                if gene_upper in _NUCLEAR_TIER1_GENES or gene_upper in _NUCLEAR_TIER2_GENES:
                    temporal = {c: round(ptm_values.get((gp[0], gp[1], c), 0.0), 3) for c in conditions}
                    substrates_list.append({
                        "ptm_key": f"{gp[0]}_{gp[1]}",
                        "gene": gp[0],
                        "site": gp[1],
                        "peak_fc": round(float(max((ptm_values.get((gp[0], gp[1], c), 0.0) for c in conditions), key=abs, default=0.0)), 3),
                        "temporal": temporal,
                        "peak_condition": max(conditions, key=lambda c, _g=gp[0], _s=gp[1]: abs(ptm_values.get((_g, _s, c), 0.0))) if conditions else "",
                        "cluster": "non_dominant_nuclear",
                        "nuclear_tier": 1 if gene_upper in _NUCLEAR_TIER1_GENES else 2,
                    })

        # v11.3.3: Regulator Self-PTM Temporal Tracking
        # Check if the kinase/E3 ligase gene itself has PTM entries in the dataset.
        self_ptm_data: list = []
        kinase_gene_upper = kinase_name.strip().upper()
        # Collect all (gene, position) pairs matching the kinase gene
        self_ptm_sites = set()
        for (g, p, c) in ptm_values:
            if g == kinase_gene_upper:
                self_ptm_sites.add((g, p))
        for (sp_gene, sp_site) in sorted(self_ptm_sites):
            # Build temporal vectors
            self_vec = [ptm_values.get((sp_gene, sp_site, c), 0.0) for c in conditions]
            activity_vec = [scores.get(c, 0.0) for c in conditions]
            # Skip if self-PTM has no signal
            if not any(abs(v) >= 0.3 for v in self_vec):
                continue
            # Compute Pearson correlation
            sp_corr = 0.0
            try:
                self_arr = np.array(self_vec)
                act_arr = np.array(activity_vec)
                if np.std(self_arr) > 1e-9 and np.std(act_arr) > 1e-9:
                    sp_corr = float(np.corrcoef(self_arr, act_arr)[0, 1])
                    if np.isnan(sp_corr):
                        sp_corr = 0.0
            except Exception:
                sp_corr = 0.0
            # Determine self-PTM peak
            sp_peak_c = max(conditions, key=lambda c: abs(ptm_values.get((sp_gene, sp_site, c), 0.0)))
            sp_peak_fc = ptm_values.get((sp_gene, sp_site, sp_peak_c), 0.0)
            # Classify relationship
            if sp_corr >= 0.7:
                sp_relationship = "concordant"
            elif sp_corr <= -0.7:
                sp_relationship = "discordant"
            else:
                sp_relationship = "independent"
            self_ptm_data.append({
                "ptm_key": f"{sp_gene}_{sp_site}",
                "gene": sp_gene,
                "site": sp_site,
                "timeseries": {c: round(ptm_values.get((sp_gene, sp_site, c), 0.0), 4) for c in conditions},
                "peak_condition": sp_peak_c,
                "peak_fc": round(sp_peak_fc, 4),
                "correlation_with_activity": round(sp_corr, 4),
                "relationship": sp_relationship,
            })
        # Sort by absolute correlation
        self_ptm_data.sort(key=lambda x: abs(x.get("correlation_with_activity", 0)), reverse=True)

        kinase_scores.append({
            "kinase": kinase_name,
            "scores": scores,
            "substrate_count": dominant["size"],       # dominant cluster size
            "total_substrates": len(members),           # original total
            "confidence": confidence,
            "peak_condition": peak_cond,
            "peak_score": peak_score,
            "coherence": coherence,                     # dominant cluster coherence
            "direction": direction,
            "n_clusters": len(clusters),
            "cluster_details": cluster_details,
            # v11.3.1: Same-time clusters for tooltip
            "same_time_clusters": same_time_clusters,
            # v11.3.2: Nuclear-exclusive substrate evidence
            "nuclear_evidence": nuclear_ev,
            # v11.3.3: Regulator self-PTM temporal tracking
            "self_ptm": self_ptm_data if self_ptm_data else None,
            # v11.3: Substrate list from dominant cluster
            "substrates": substrates_list,
        })

        # ── Sub-pattern entries for non-dominant, different-time clusters ──
        # Mirrors the API endpoint writer logic (orders.py kinase_activity_heatmap).
        # Only generates entries for clusters whose peak differs from the dominant peak
        # and that have meaningful size and signal.
        # `legacy` contract keeps the pre-2026-08 heatmap (no _c1/_c2 rows).
        if temporal.emit_heatmap_sub_patterns and len(clusters) >= 2:
            for cl in clusters:
                if cl.get("is_dominant"):
                    continue
                cl_size = cl.get("size", 0)
                if cl_size < 2:
                    continue
                sub_peak_cond = cl.get("peak_condition", "")
                sub_peak_score = cl.get("peak_score", 0.0)
                if not sub_peak_cond or sub_peak_cond == peak_cond:
                    continue  # same-time clusters go into same_time_clusters, not sub-patterns
                if abs(sub_peak_score) < 0.3:
                    continue
                # Positional category
                cond_idx = conditions.index(sub_peak_cond) if sub_peak_cond in conditions else 0
                if cond_idx <= len(conditions) // 3:
                    sub_label_category = "early_response"
                elif cond_idx >= len(conditions) * 2 // 3:
                    sub_label_category = "late_response"
                else:
                    sub_label_category = "mid_response"
                sub_scores = _score_members(cl.get("member_keys", []), conditions)
                kinase_scores.append({
                    "kinase": f"{kinase_name}_c{cl['cluster_id']}",
                    "parent_kinase": kinase_name,
                    "is_sub_pattern": True,
                    "sub_pattern_label": sub_peak_cond,
                    "sub_pattern_category": sub_label_category,
                    "scores": sub_scores,
                    "substrate_count": cl_size,
                    "total_substrates": len(members),
                    "confidence": confidence * 0.7,
                    "peak_condition": sub_peak_cond,
                    "peak_score": round(float(sub_peak_score), 4),
                    "coherence": cl.get("coherence", 0.0),
                    "direction": "activation" if sub_peak_score > 0.3 else (
                        "inactivation" if sub_peak_score < -0.3 else "neutral"
                    ),
                    "n_clusters": 1,
                    "cluster_details": [cl],
                    "same_time_clusters": [],
                    "nuclear_evidence": {},
                    "self_ptm": None,
                    "substrates": [
                        {
                            "ptm_key": f"{gp[0]}_{gp[1]}",
                            "gene": gp[0],
                            "site": gp[1],
                            "peak_fc": round(float(max(
                                (ptm_values.get((gp[0], gp[1], c), 0.0) for c in conditions),
                                key=abs, default=0.0
                            )), 3),
                            "temporal": {c: round(ptm_values.get((gp[0], gp[1], c), 0.0), 3) for c in conditions},
                            "peak_condition": max(
                                conditions,
                                key=lambda c, _g=gp[0], _s=gp[1]: abs(ptm_values.get((_g, _s, c), 0.0))
                            ) if conditions else "",
                            "cluster": f"sub_{cl['cluster_id']}",
                        }
                        for gp in cl.get("member_keys", [])
                    ],
                })

    # ── Peak Synchronization: find kinases that peak at the same condition ──
    peak_groups = {}  # condition -> list of kinase names
    for ks in kinase_scores:
        pc = ks.get("peak_condition", "")
        if pc:
            peak_groups.setdefault(pc, []).append(ks["kinase"])

    # Mark sync groups (3+ kinases peaking at same condition)
    peak_sync = {}
    for cond, kinases in peak_groups.items():
        if len(kinases) >= 3:
            peak_sync[cond] = {
                "kinases": kinases,
                "count": len(kinases),
            }

    # ── Co-wave group assignment (kinase-level) ──
    # Cluster kinases by temporal profile similarity (using dominant cluster scores)
    cowave_groups = []
    if len(kinase_scores) >= 3 and n_conditions >= 2:
        # Build kinase score matrix
        score_matrix = []
        valid_kinases = []
        for ks in kinase_scores:
            row = [ks["scores"].get(c, 0.0) for c in conditions]
            if any(abs(v) > 0.1 for v in row):  # skip flat kinases
                score_matrix.append(row)
                valid_kinases.append(ks["kinase"])
        if len(valid_kinases) >= 3:
            arr = np.array(score_matrix)
            # Simple correlation-based clustering
            try:
                corr = np.corrcoef(arr)
                visited = set()
                group_id = 0
                for i in range(len(valid_kinases)):
                    if i in visited:
                        continue
                    group = [i]
                    visited.add(i)
                    for j in range(i + 1, len(valid_kinases)):
                        if j not in visited and not np.isnan(corr[i][j]) and corr[i][j] >= 0.7:
                            group.append(j)
                            visited.add(j)
                    if len(group) >= 2:
                        cowave_groups.append({
                            "group_id": group_id,
                            "kinases": [valid_kinases[idx] for idx in group],
                            "size": len(group),
                            "mean_correlation": round(float(np.mean(
                                [corr[a][b] for a in group for b in group if a != b and not np.isnan(corr[a][b])]
                            )), 3) if len(group) > 1 else 1.0,
                        })
                        group_id += 1
            except Exception:
                pass

    # Annotate each kinase with its co-wave group
    kinase_to_group = {}
    for grp in cowave_groups:
        for k in grp["kinases"]:
            kinase_to_group[k] = grp["group_id"]
    for ks in kinase_scores:
        ks["cowave_group"] = kinase_to_group.get(ks["kinase"], -1)

    # Sort by peak_score descending
    kinase_scores.sort(key=lambda x: abs(x["peak_score"]), reverse=True)

    # Filter: only include kinases with ≥2 substrates in dominant cluster
    kinase_scores_filtered = [ks for ks in kinase_scores if ks["substrate_count"] >= 2]
    # If filtering removes too many, keep top kinases even with 1 substrate
    if len(kinase_scores_filtered) < 5 and len(kinase_scores) >= 5:
        kinase_scores_filtered = kinase_scores[:20]  # fallback: top 20 regardless

    # ── v11.3.4: Shared-substrate deduplication ──────────────────────────────
    # When multiple kinases share highly overlapping substrate sets (Jaccard ≥ 0.8),
    # and some have self-PTM detected, hide those without self-PTM.
    _substrate_gene_sets: dict[str, set[str]] = {}
    for ks_entry in kinase_scores_filtered:
        if ks_entry.get("is_sub_pattern"):
            continue
        genes = set(
            s["gene"].upper() for s in ks_entry.get("substrates", [])
            if s.get("gene")
        )
        if genes:
            _substrate_gene_sets[ks_entry["kinase"]] = genes

    _overlap_groups: list[set[str]] = []
    _assigned: set[str] = set()
    _kinase_list = list(_substrate_gene_sets.keys())
    for i, k1 in enumerate(_kinase_list):
        if k1 in _assigned:
            continue
        group = {k1}
        g1 = _substrate_gene_sets[k1]
        for k2 in _kinase_list[i+1:]:
            if k2 in _assigned:
                continue
            g2 = _substrate_gene_sets[k2]
            if not g1 or not g2:
                continue
            jaccard = len(g1 & g2) / len(g1 | g2)
            if jaccard >= 0.8:
                group.add(k2)
        if len(group) >= 2:
            _overlap_groups.append(group)
            _assigned.update(group)

    _hidden_kinases: set[str] = set()
    for group in _overlap_groups:
        has_self_ptm = [
            k for k in group
            if any(
                ks.get("self_ptm") for ks in kinase_scores_filtered
                if ks.get("kinase") == k and not ks.get("is_sub_pattern")
            )
        ]
        if has_self_ptm:
            for k in group:
                if k not in has_self_ptm:
                    _hidden_kinases.add(k)

    for ks_entry in kinase_scores_filtered:
        if ks_entry.get("kinase") in _hidden_kinases and not ks_entry.get("is_sub_pattern"):
            ks_entry["hidden_by_self_ptm"] = True
            for group in _overlap_groups:
                if ks_entry["kinase"] in group:
                    ks_entry["superseded_by"] = [
                        k for k in group
                        if k != ks_entry["kinase"] and k not in _hidden_kinases
                    ]
                    break

    return {
        "kinase_scores": kinase_scores_filtered,
        "conditions": conditions,
        "peak_sync": peak_sync,
        "cowave_groups": cowave_groups,
        "all_kinase_scores": kinase_scores,  # unfiltered for debug
        "temporal_contract": temporal.name,
        "guard_policy": temporal.guard_policy,
        "_cached": True,
    }
    # ── TMM: Temporal Mixture Modeling (Option B) ────────────────────────────
    # Apply contribution-weighted scoring to shared substrates so that
    # kinases with overlapping substrate sets get data-driven credit allocation.
    try:
        from api.services.temporal_kinase_scoring import compute_weighted_kinase_scores  # type: ignore
        # Build ptm_timeseries from enriched_data
        ptm_timeseries: dict[str, dict[str, float]] = {}
        for row in enriched_data:
            gene = (row.get("gene") or row.get("Gene.Name") or "").upper()
            pos = str(row.get("position") or row.get("PTM_Position") or "")
            cond = row.get("condition") or row.get("Condition") or ""
            fc = row.get("ptm_relative_log2fc") or row.get("PTM_Relative_Log2FC") or 0
            if gene and pos and cond:
                key = f"{gene}_{pos}"
                if key not in ptm_timeseries:
                    ptm_timeseries[key] = {}
                try:
                    ptm_timeseries[key][cond] = float(fc)
                except (ValueError, TypeError):
                    pass
        # Build kinase_modules list for TMM
        tmm_modules = []
        for ks in kinase_scores_filtered:
            if ks.get("is_sub_pattern"):
                continue
            members = [
                {"key": f"{(s.get('gene','') or '').upper()}_{s.get('position','') or ''}"}
                for s in ks.get("substrates", [])
                if s.get("gene") and s.get("position")
                and not f"{(s.get('gene','') or '').upper()}_{s.get('position','') or ''}".endswith("_")
            ]
            tmm_modules.append({
                "canonical": ks.get("kinase", "").upper(),
                "kinase": ks.get("kinase", ""),
                "members": members,
            })
        if tmm_modules and ptm_timeseries:
            tmm_scores = compute_weighted_kinase_scores(tmm_modules, ptm_timeseries, conditions)
            for ks_entry in kinase_scores_filtered:
                if ks_entry.get("is_sub_pattern"):
                    continue
                canon = (ks_entry.get("parent_kinase") or ks_entry.get("kinase", "")).upper()
                tmm = tmm_scores.get(canon)
                if tmm:
                    ks_entry["raw_up_sums"] = dict(ks_entry.get("up_sums", {}))
                    ks_entry["raw_down_sums"] = dict(ks_entry.get("down_sums", {}))
                    w_up = {c: round(v, 3) for c, v in tmm["weighted_up_sums"].items()}
                    w_dn = {c: round(v, 3) for c, v in tmm["weighted_down_sums"].items()}
                    ks_entry["up_sums"] = w_up
                    ks_entry["down_sums"] = w_dn
                    ks_entry["up_counts"] = {c: round(v, 3) for c, v in tmm["weighted_up_counts"].items()}
                    ks_entry["down_counts"] = {c: round(v, 3) for c, v in tmm["weighted_down_counts"].items()}
                    ks_entry["tmm_n_exclusive"] = tmm.get("n_exclusive", 0)
                    ks_entry["tmm_n_shared"] = tmm.get("n_shared", 0)
                    ks_entry["tmm_profile_type"] = tmm.get("profile_type", "")
                    ks_entry["tmm_top_contributions"] = tmm.get("top_contributions", [])
                    net_sums = {c: w_up.get(c, 0) + w_dn.get(c, 0) for c in conditions}
                    if net_sums:
                        best_c = max(net_sums, key=lambda c: abs(net_sums[c]))
                        ks_entry["peak_condition"] = best_c
                        ks_entry["peak_score"] = round(net_sums[best_c], 3)
                        total_net = sum(net_sums.values())
                        ks_entry["direction"] = "up" if total_net > 0 else "down" if total_net < 0 else "neutral"
            logger.info(f"[TMM-RAG] Applied TMM to {len(tmm_scores)} kinases in heatmap")
    except Exception as _tmm_err:
        logger.warning(f"[TMM-RAG] TMM integration skipped (non-fatal): {_tmm_err}")


def _make_progress_cb(order_id, stage, step, base, span):
    def cb(frac, msg):
        pct = base + frac * span
        publish_progress(order_id, stage, step, "running", round(pct, 1), msg)
    return cb


@app.task(bind=True, name="rag_enrichment.tasks.run_rag_enrichment", max_retries=1)
def run_rag_enrichment(self, order_id: int, config: dict):
    """
    Stage 2: RAG Enrichment Pipeline.

    config keys:
      - preprocessing_output_dir: str   (absolute path to Stage 1 output)
      - ptm_mode: 'phospho' | 'ubi'
      - experimental_context: dict      (optional: tissue, treatment, keywords, etc.)
      - max_articles_per_ptm: int       (default 15)
      - ptm_selection_mode: str         (default 'top_n' — PTM selection strategy)
          'top_n'            : legacy behaviour — rank by max |FC|, take top_n
          'de_novo'          : only Control_Pseudocount_Used == True PTMs
          'regulated'        : only q_value < 0.05 AND |Log2FC| >= 1.0 PTMs
          'de_novo_regulated': de_novo UNION regulated
          'minor'            : PTMs that are neither de_novo nor regulated
          'all'              : all PTMs (no limit)
      - top_n_ptms: int                 (default 50 — used only when mode is 'top_n')
    """
    start_time = time.time()
    order_code = config.get("order_code") or str(order_id)
    order_output = Path(OUTPUT_DIR) / order_code
    order_output.mkdir(parents=True, exist_ok=True)

    update_order_status(order_id, "rag_enrichment", current_stage="rag_enrichment", progress_pct=0,
                        stage_detail="RAG enrichment started")

    # Clear stale ptm_phase/ptm_list logs from previous runs so the UI starts clean
    try:
        from common.db_engine import get_engine as _get_engine
        from sqlalchemy import text as _text
        _eng = _get_engine()
        with _eng.connect() as _conn:
            _conn.execute(
                _text(
                    "DELETE FROM order_logs WHERE order_id = :oid "
                    "AND stage = 'rag_enrichment' AND step = 'ptm_phase'"
                ),
                {"oid": order_id},
            )
            _conn.commit()
        logger.info(f"[Order {order_id}] Cleared previous ptm_phase logs")
    except Exception as _del_err:
        logger.warning(f"[Order {order_id}] Could not clear old ptm_phase logs: {_del_err}")

    logger.info(f"[Order {order_id}] RAG enrichment started")
    publish_progress(order_id, "rag_enrichment", "start", "started", 0, "RAG enrichment pipeline started")

    try:
        preprocessing_dir = Path(config.get("preprocessing_output_dir", str(order_output)))
        ptm_mode = config.get("ptm_mode", "phospho")
        single_time_point = config.get("single_time_point", False)
        experimental_context = dict(config.get("experimental_context") or {})
        experimental_context["single_time_point"] = single_time_point
        top_n = config.get("top_n_ptms", 50)
        ptm_selection_mode = config.get("ptm_selection_mode", "top_n")
        file_suffix = "_phospho" if ptm_mode == "phospho" else "_ubi"

        # ================================================================
        # Step 1: Load PTM vector data from preprocessing output (0% – 10%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "load_data", "started", 2, "Loading PTM vector data")

        vector_file = preprocessing_dir / f"ptm_vector_data_normalized{file_suffix}.tsv"
        if not vector_file.exists():
            vector_file = preprocessing_dir / f"ptm_vector_data_with_motifs{file_suffix}.tsv"
        if not vector_file.exists():
            raise FileNotFoundError(f"PTM vector file not found in {preprocessing_dir}")

        df = pd.read_csv(vector_file, sep="\t", low_memory=False)
        logger.info(f"[Order {order_id}] Loaded {len(df)} PTM entries from {vector_file.name}")

        # Select PTMs based on ptm_selection_mode.
        # Modes: top_n | de_novo | regulated | de_novo_regulated | minor | all
        # Legacy classification mode also supported via use_classification_selection flag.
        use_classification = config.get("use_classification_selection", False)

        gene_col = "Gene.Name" if "Gene.Name" in df.columns else "gene"
        pos_col = "PTM_Position" if "PTM_Position" in df.columns else "position"
        cond_col = "Condition" if "Condition" in df.columns else "condition"
        fc_col = "PTM_Relative_Log2FC" if "PTM_Relative_Log2FC" in df.columns else "ptm_relative_log2fc"

        if use_classification and fc_col in df.columns:
            # Classification-based selection (ported from ptm-vector-ai)
            from rag_enrichment.core.enrichment_pipeline import RAGEnrichmentPipeline
            all_ptm_records = df.to_dict("records")
            conditions_list = sorted(df[cond_col].dropna().unique().tolist(), key=condition_sort_key) if cond_col in df.columns else None
            classified_ptms = RAGEnrichmentPipeline.select_ptms_by_classification(
                ptm_data=all_ptm_records,
                conditions=conditions_list,
                include_high=True,
                include_moderate=True,
                include_low=False,
                top_n=top_n,
            )
            # Get keys of selected PTMs and filter df to keep all condition rows
            selected_keys = set()
            for p in classified_ptms:
                g = p.get("gene") or p.get("Gene.Name", "?")
                s = p.get("position") or p.get("PTM_Position", "?")
                selected_keys.add((str(g), str(s)))

            df["_key"] = list(zip(df[gene_col].astype(str), df[pos_col].astype(str)))
            df = df[df["_key"].isin(selected_keys)]
            df = df.drop(columns=["_key"])
            n_unique = len(selected_keys)

            # Count by significance
            sig_counts = {}
            for p in classified_ptms:
                sig = p.get("classification", {}).get("significance", "?")
                sig_counts[sig] = sig_counts.get(sig, 0) + 1
            logger.info(
                f"[Order {order_id}] Classification selection: {n_unique} unique PTMs "
                f"(High={sig_counts.get('High', 0)}, Moderate={sig_counts.get('Moderate', 0)}, "
                f"Low={sig_counts.get('Low', 0)}), {len(df)} total rows"
            )

        elif fc_col in df.columns and cond_col in df.columns:
            import numpy as _np
            df["_abs_fc"] = df[fc_col].abs()
            conditions = df[cond_col].dropna().unique()
            df["_key"] = list(zip(df[gene_col].astype(str), df[pos_col].astype(str)))

            # ── v9.26: PTM Selection Mode ──────────────────────────────────────
            # Modes: top_n | de_novo | regulated | de_novo_regulated | minor | all
            # -----------------------------------------------------------------
            pc_col = "Control_Pseudocount_Used" if "Control_Pseudocount_Used" in df.columns else None
            q_col  = "q_value" if "q_value" in df.columns else None

            # Per-PTM aggregates
            key_max_fc = df.groupby("_key")["_abs_fc"].max()
            key_denovo = df.groupby("_key")[pc_col].any() if pc_col else None
            key_min_q  = df.groupby("_key")[q_col].min() if q_col else None

            # Classify every unique PTM key
            denovo_keys: set = set()
            regulated_keys: set = set()
            minor_keys: set = set()

            # ── 2-pass regulated classification ──────────────────────────────
            # Pass 1: Strict criteria (q_value < 0.05 AND |FC| >= 1.0)
            # Pass 2: If Pass 1 yields 0 regulated, relax to |FC| >= 0.8 only
            # This handles datasets where BH correction is too conservative
            # (all q_values > 0.05) while preserving q_value when available.
            # ─────────────────────────────────────────────────────────────────
            non_denovo_keys: list = []
            for k in key_max_fc.index:
                is_denovo = bool(key_denovo is not None and key_denovo.get(k, False))
                if is_denovo:
                    denovo_keys.add(k)
                    continue  # De novo PTMs are never also Regulated
                non_denovo_keys.append(k)

            # Pass 1: strict q_value-based classification
            for k in non_denovo_keys:
                fc_val = key_max_fc.get(k, 0.0)
                is_regulated = False
                if key_min_q is not None:
                    q_val = key_min_q.get(k)
                    if q_val is not None and not _np.isnan(float(q_val)) and float(q_val) < 0.05 and fc_val >= 1.0:
                        is_regulated = True
                else:
                    # No q_value column at all — use |FC| >= 0.8
                    if fc_val >= 0.8:
                        is_regulated = True
                if is_regulated:
                    regulated_keys.add(k)
                else:
                    minor_keys.add(k)

            # Pass 2: if q_value column exists but yielded 0 regulated,
            # re-classify using |FC| >= 0.8 as fallback threshold
            if key_min_q is not None and len(regulated_keys) == 0 and len(non_denovo_keys) > 0:
                logger.info(
                    f"[Order {order_id}] Pass 1 (q<0.05 + |FC|>=1.0) yielded 0 regulated PTMs. "
                    f"Applying Pass 2 fallback: |FC| >= 0.8 for {len(non_denovo_keys)} non-de_novo PTMs."
                )
                regulated_keys = set()
                minor_keys = set()
                for k in non_denovo_keys:
                    fc_val = key_max_fc.get(k, 0.0)
                    if fc_val >= 0.8:
                        regulated_keys.add(k)
                    else:
                        minor_keys.add(k)
                logger.info(
                    f"[Order {order_id}] Pass 2 result: {len(regulated_keys)} regulated, "
                    f"{len(minor_keys)} minor PTMs."
                )

            # Apply selection based on mode
            mode = ptm_selection_mode
            if mode == "all":
                selected_keys = set(key_max_fc.index.tolist())
                fill_keys: set = set()
            elif mode == "de_novo":
                selected_keys = denovo_keys
                fill_keys = set()
            elif mode == "regulated":
                selected_keys = regulated_keys
                fill_keys = set()
            elif mode == "de_novo_regulated":
                selected_keys = denovo_keys | regulated_keys
                fill_keys = set()
            elif mode == "minor":
                selected_keys = minor_keys
                fill_keys = set()
            else:
                # Default: 'top_n' — De novo + Regulated guaranteed, fill remainder
                priority_keys = denovo_keys | regulated_keys
                remaining_slots = max(0, top_n - len(priority_keys))
                remaining_sorted = key_max_fc.drop(index=list(priority_keys), errors="ignore") \
                                             .sort_values(ascending=False)
                fill_keys = set(remaining_sorted.head(remaining_slots).index.tolist())
                selected_keys = priority_keys | fill_keys

            # Fallback: if mode-based selection yields nothing, fall back to top_n
            if not selected_keys:
                logger.warning(
                    f"[Order {order_id}] ptm_selection_mode='{mode}' yielded 0 PTMs "
                    f"(q_value data available: {q_col is not None}). "
                    f"Falling back to top_{top_n} by |FC|."
                )
                fill_keys = set(key_max_fc.sort_values(ascending=False).head(top_n).index.tolist())
                selected_keys = fill_keys

            # Keep all rows (all conditions) for the selected gene+position pairs
            df = df[df["_key"].isin(selected_keys)]
            df = df.drop(columns=["_abs_fc", "_key"])

            n_unique = len(selected_keys)
            _total_unique = len(key_max_fc.index)
            logger.info(
                f"[Order {order_id}] [RAG-SELECT] "
                f"mode='{mode}' | "
                f"전체 unique PTM={_total_unique} | "
                f"De novo={len(denovo_keys)}, Regulated={len(regulated_keys)}, Minor={len(minor_keys)} | "
                f"선택됨={n_unique} unique PTMs ({len(df)} rows, {len(conditions)} conditions) | "
                f"top_n_setting={top_n} (mode!=top_n 이면 무시됨)"
            )
        elif fc_col in df.columns:
            # Fallback: no Condition column — simple top-N by abs FC
            df["_abs_fc"] = df[fc_col].abs()
            df = df.sort_values("_abs_fc", ascending=False).head(top_n)
            df = df.drop(columns=["_abs_fc"])
            n_unique = top_n
        else:
            n_unique = len(df)

        # Collapse all selected condition rows into one site/form work item
        # before calling remote databases.  The selection mode therefore
        # controls the real RAG input universe rather than merely the report
        # display, while condition_data/trajectory preserve dense time-course
        # evidence for downstream interpretation.
        from rag_enrichment.core.ptm_merger import collapse_ptm_rows_for_enrichment

        selected_row_count = len(df)
        ptm_data = collapse_ptm_rows_for_enrichment(
            df.to_dict("records"),
            single_time_point=single_time_point,
        )
        for ptm in ptm_data:
            ptm["rag_selection_mode"] = ptm_selection_mode
        n_unique = len(ptm_data)
        publish_progress(order_id, "rag_enrichment", "load_data", "completed", 10,
                        f"[{n_unique} unique PTMs selected from {selected_row_count} condition rows] "
                        f"mode='{ptm_selection_mode}' → DB-first enrichment 시작")

        # ================================================================
        # Step 2: RAG Enrichment — PubMed + pattern matching (10% – 70%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "enrichment", "started", 10, "Starting literature enrichment")
        send_step_webhook(order_id, "rag_enrichment", "started")

        from rag_enrichment.core.enrichment_pipeline import RAGEnrichmentPipeline

        mcp = MCPClient()
        enrich_cb = _make_progress_cb(order_id, "rag_enrichment", "enrichment", 10, 60)

        def _analysis_log(msg: str, metadata: dict | None = None, *, persist: bool = False) -> None:
            publish_analysis_log(order_id, msg, metadata=metadata, persist=persist)

        rag_llm_model = config.get("rag_llm_model")
        rag_llm_provider = config.get("rag_llm_provider")
        report_llm_provider = config.get("llm_provider", "ollama")
        _order_species = (experimental_context.get("organism") or
                          experimental_context.get("species") or
                          config.get("species") or "mouse")

        def _env_bool(name: str, default: bool = True) -> bool:
            return os.getenv(name, "true" if default else "false").lower() not in ("false", "0", "no")

        pipeline = RAGEnrichmentPipeline(
            mcp_client=mcp,
            progress_callback=enrich_cb,
            analysis_log=_analysis_log,
            enable_llm_analysis=_env_bool("RAG_ENABLE_LLM", default=True),
            rag_enrichment_llm_model=config.get("rag_enrichment_llm_model"),
            rag_enrichment_llm_provider=config.get("rag_enrichment_llm_provider"),
            rag_llm_model=rag_llm_model,
            rag_llm_provider=rag_llm_provider,
            llm_provider=report_llm_provider,
            llm_model=config.get("llm_model"),
            species=_order_species,
        )

        # Cancellation: poll DB every 5 s; set event when order becomes cancelled.
        cancel_event = threading.Event()

        def _cancellation_poller():
            while not cancel_event.is_set():
                try:
                    if get_order_status(order_id) == "cancelled":
                        cancel_event.set()
                        logger.info(f"[Order {order_id}] cancellation detected — signalling pipeline to stop")
                        break
                except Exception:
                    pass
                time.sleep(1)

        _poll_thread = threading.Thread(target=_cancellation_poller, daemon=True, name=f"cancel_poll_{order_id}")
        _poll_thread.start()

        enriched_ptms = pipeline.enrich_ptm_data(
            ptm_data=ptm_data,
            experimental_context=experimental_context,
            cancel_event=cancel_event,
        )

        # Stop the poller once the pipeline finishes (normal or early exit).
        cancel_event.set()

        # Do not continue to MD report / webhooks / chain if the user cancelled (cancel_event is always set here).
        if get_order_status(order_id) == "cancelled":
            logger.info(
                f"[Order {order_id}] RAG enrichment stopped by user — skipping MD report, finalization, and chain"
            )
            try:
                mcp.close()
            except Exception:
                pass
            return {
                "order_id": order_id,
                "status": "cancelled",
                "elapsed_seconds": round(time.time() - start_time, 1),
                "message": "Stopped by user",
            }

        # Save enriched data as JSON
        enriched_json_path = order_output / f"enriched_ptm_data{file_suffix}.json"
        with open(enriched_json_path, "w", encoding="utf-8") as f:
            json.dump(enriched_ptms, f, indent=2, default=str)

        # ── Logging: JSON 저장 결과 ──────────────────────────────────────────
        _json_unique_keys = set()
        for _item in enriched_ptms:
            _g = _item.get("Gene.Name", "") or _item.get("gene", "")
            _s = _item.get("PTM_Position", "") or _item.get("position", "")
            if _g and _s:
                _json_unique_keys.add(f"{_g}_{_s}")
        logger.info(
            f"[Order {order_id}] [RAG-SAVE] "
            f"JSON: {enriched_json_path.name} | "
            f"total rows={len(enriched_ptms)}, unique PTMs={len(_json_unique_keys)}"
        )

        publish_progress(order_id, "rag_enrichment", "enrichment", "completed", 70, "Literature enrichment complete")

        # ================================================================
        # Step 3: MD Report Generation (70% – 95%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "report_generation", "started", 70, "Generating MD report")

        from rag_enrichment.core.report_generator import ComprehensiveReportGenerator
        from rag_enrichment.core.ptm_merger import merge_multi_condition_ptms

        # Merge multi-condition rows into unified PTM entries
        # When single_time_point, conditions are not treated as timepoints (no trajectory)
        merged_ptms = merge_multi_condition_ptms(enriched_ptms, single_time_point=single_time_point)
        logger.info(
            f"[Order {order_id}] Merged {len(enriched_ptms)} rows -> "
            f"{len(merged_ptms)} unique PTMs (multi-condition merged)"
        )

        generator = ComprehensiveReportGenerator(experimental_context=experimental_context)
        report_md = generator.generate_full_report(merged_ptms)

        md_path = order_output / f"comprehensive_report{file_suffix}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        logger.info(f"[Order {order_id}] Saved report: {md_path.name}")

        publish_progress(order_id, "rag_enrichment", "report_generation", "completed", 90, "MD report generated")

        # ================================================================
        # Step 3.5: Secondary PTM enrichment for Cross-Talk mode (90% – 95%)
        # ================================================================
        analysis_mode = config.get("analysis_mode", "ptm_only")
        secondary_enriched_json_path = None
        secondary_md_path_out = None
        secondary_tsv_path = None

        if analysis_mode == "cross_talk":
            secondary_ptm_type = config.get("secondary_ptm_type", "ubiquitylation")
            secondary_ptm_mode = "ubi" if secondary_ptm_type.startswith("ubiquit") else "phospho"
            secondary_file_suffix = "_ubi" if secondary_ptm_mode == "ubi" else "_phospho"

            # Look for secondary preprocessing output
            secondary_output_dir = config.get("secondary_output_dir")
            if not secondary_output_dir:
                secondary_output_dir = str(order_output / "secondary_ptm")

            sec_dir = Path(secondary_output_dir)
            sec_vector_file = sec_dir / f"ptm_vector_data_normalized{secondary_file_suffix}.tsv"
            if not sec_vector_file.exists():
                sec_vector_file = sec_dir / f"ptm_vector_data_with_motifs{secondary_file_suffix}.tsv"

            if sec_vector_file.exists():
                publish_progress(order_id, "rag_enrichment", "secondary_enrichment", "started", 90,
                                f"Enriching secondary {secondary_ptm_type} data")

                sec_df = pd.read_csv(sec_vector_file, sep="\t", low_memory=False)
                logger.info(f"[Order {order_id}] Secondary: Loaded {len(sec_df)} entries from {sec_vector_file.name}")

                # Select top-N secondary PTMs
                sec_gene_col = "Gene.Name" if "Gene.Name" in sec_df.columns else "gene"
                sec_pos_col = "PTM_Position" if "PTM_Position" in sec_df.columns else "position"
                sec_fc_col = "PTM_Relative_Log2FC" if "PTM_Relative_Log2FC" in sec_df.columns else "ptm_relative_log2fc"
                sec_cond_col = "Condition" if "Condition" in sec_df.columns else "condition"

                if sec_fc_col in sec_df.columns and sec_cond_col in sec_df.columns:
                    sec_df["_abs_fc"] = sec_df[sec_fc_col].abs()
                    sec_df["_key"] = list(zip(sec_df[sec_gene_col].astype(str), sec_df[sec_pos_col].astype(str)))
                    sec_key_max = sec_df.groupby("_key")["_abs_fc"].max().sort_values(ascending=False)
                    sec_selected = set(sec_key_max.head(top_n).index.tolist())
                    sec_df = sec_df[sec_df["_key"].isin(sec_selected)]
                    sec_df = sec_df.drop(columns=["_abs_fc", "_key"])
                    logger.info(f"[Order {order_id}] Secondary: selected {len(sec_selected)} unique PTMs")

                sec_ptm_data = collapse_ptm_rows_for_enrichment(
                    sec_df.to_dict("records"),
                    single_time_point=single_time_point,
                )
                for ptm in sec_ptm_data:
                    ptm["rag_selection_mode"] = "secondary_top_n"

                # Enrich secondary PTMs
                sec_enrich_cb = _make_progress_cb(order_id, "rag_enrichment", "secondary_enrichment", 90, 3)
                sec_pipeline = RAGEnrichmentPipeline(
                    mcp_client=mcp,
                    progress_callback=sec_enrich_cb,
                    analysis_log=_analysis_log,
                    rag_enrichment_llm_model=config.get("rag_enrichment_llm_model"),
                    rag_enrichment_llm_provider=config.get("rag_enrichment_llm_provider"),
                    rag_llm_model=rag_llm_model,
                    rag_llm_provider=rag_llm_provider,
                    llm_provider=report_llm_provider,
                    llm_model=config.get("llm_model"),
                    species=_order_species,
                )
                sec_enriched = sec_pipeline.enrich_ptm_data(
                    ptm_data=sec_ptm_data,
                    experimental_context={**experimental_context, "ptm_type": secondary_ptm_type},
                )

                # Save secondary enriched JSON
                secondary_enriched_json_path = order_output / f"enriched_ptm_data{secondary_file_suffix}.json"
                with open(secondary_enriched_json_path, "w", encoding="utf-8") as f:
                    json.dump(sec_enriched, f, indent=2, default=str)
                logger.info(f"[Order {order_id}] Saved secondary enriched data: {secondary_enriched_json_path.name}")

                # Generate secondary MD report
                sec_merged = merge_multi_condition_ptms(sec_enriched, single_time_point=single_time_point)
                sec_generator = ComprehensiveReportGenerator(
                    experimental_context={**experimental_context, "ptm_type": secondary_ptm_type}
                )
                sec_report_md = sec_generator.generate_full_report(sec_merged)
                secondary_md_path_out = order_output / f"comprehensive_report{secondary_file_suffix}.md"
                with open(secondary_md_path_out, "w", encoding="utf-8") as f:
                    f.write(sec_report_md)
                logger.info(f"[Order {order_id}] Saved secondary report: {secondary_md_path_out.name}")

                # Find secondary TSV path
                sec_bio_tsv = sec_dir / f"unified_protein_data_enriched_bio_enriched{secondary_file_suffix}.tsv"
                if sec_bio_tsv.exists():
                    secondary_tsv_path = str(sec_bio_tsv)
                else:
                    sec_tsv_candidates = list(sec_dir.glob("*bio_enriched*.tsv"))
                    if sec_tsv_candidates:
                        secondary_tsv_path = str(sec_tsv_candidates[0])

                publish_progress(order_id, "rag_enrichment", "secondary_enrichment", "completed", 95,
                                f"Secondary {secondary_ptm_type} enrichment complete ({len(sec_enriched)} PTMs)")
            else:
                logger.warning(f"[Order {order_id}] Cross-Talk: secondary vector file not found at {sec_vector_file}")
                publish_progress(order_id, "rag_enrichment", "secondary_enrichment", "skipped", 95,
                                "Secondary PTM vector file not found — skipping secondary enrichment")

        # ================================================================
        # Step 4: Finalization (95% – 100%)
        # ================================================================
        elapsed = round(time.time() - start_time, 1)
        output_files = [f.name for f in order_output.iterdir() if f.suffix in (".json", ".md")]

        publish_progress(
            order_id, "rag_enrichment", "finalization", "completed", 100,
            f"RAG enrichment complete ({elapsed}s, {len(output_files)} files)",
            metadata={"output_files": output_files, "elapsed_seconds": elapsed,
                      "ptms_enriched": len(enriched_ptms)},
        )

        logger.info(f"[Order {order_id}] RAG enrichment completed in {elapsed}s")
        send_step_webhook(order_id, "rag_enrichment", "completed")
        mcp.close()

        # Chain to Stage 3: Report Generation
        report_config = {
            "order_code": order_code,
            "rag_output_dir": str(order_output),
            "enriched_json_path": str(enriched_json_path),
            "md_report_path": str(md_path),
            "tsv_data_path": config.get("tsv_data_path", ""),
            "experimental_context": experimental_context,
            "research_questions": config.get("research_questions", []),
            "chromadb_collections": config.get("chromadb_collections", []),
            "llm_provider": config.get("llm_provider", "ollama"),
            "llm_model": config.get("llm_model"),
            "report_title": config.get("report_title", "PTM Comprehensive Analysis Report"),
            "report_type": config.get("report_type", "comprehensive"),
            "report_config": config.get("report_config", {}),
            "co_scientist_integration": config.get("co_scientist_integration", {}),
            "analysis_mode": analysis_mode,
            "secondary_ptm_type": config.get("secondary_ptm_type"),
            "temporal_contract": config.get("temporal_contract"),
        }
        # Cross-Talk: add secondary paths to report_config
        if analysis_mode == "cross_talk":
            report_config["secondary_enriched_json_path"] = str(secondary_enriched_json_path) if secondary_enriched_json_path else None
            report_config["secondary_md_report_path"] = str(secondary_md_path_out) if secondary_md_path_out else None
            report_config["secondary_tsv_data_path"] = secondary_tsv_path
            report_config["secondary_output_dir"] = str(order_output / "secondary_ptm") if (order_output / "secondary_ptm").exists() else str(order_output)
            logger.info(f"[Order {order_id}] Cross-Talk report_config: secondary_enriched={secondary_enriched_json_path}, secondary_md={secondary_md_path_out}")
        # ── v9.44: Auto-run Global Annotate + Upstream Inference before Report Gen ──
        _auto_analysis_data = _auto_run_global_analysis(order_id, enriched_ptms, config, mcp_client=mcp)
        if _auto_analysis_data:
            report_config["kinase_analysis_data"] = _auto_analysis_data.get("kinase_analysis_data", {})
            report_config["kinase_activity_heatmap"] = _auto_analysis_data.get("kinase_activity_heatmap", {})
            # v11.5f: Include receptor inference data in report_config
            _rec_data = _auto_analysis_data.get("receptor_inference_data", {})
            if _rec_data:
                report_config["receptor_inference_data"] = _rec_data
                logger.info(
                    f"[Order {order_id}] Auto receptor inference included: "
                    f"{len(_rec_data.get('receptors', []))} receptors"
                )
            logger.info(f"[Order {order_id}] Auto global analysis completed — kinase modules + heatmap + receptors cached")

        _status_before_chain = get_order_status(order_id)
        if config.get("chain_to_next", True) and _status_before_chain == "rag_enrichment":
            report_task = app.send_task(
                "report_generation.tasks.run_report_generation",
                args=[order_id, report_config],
                queue="report_generation",
            )
            save_celery_task_id(order_id, report_task.id)
            logger.info(f"[Order {order_id}] Chained to report generation (task_id={report_task.id})")
        else:
            logger.info(
                f"[Order {order_id}] RAG complete — skipping chain "
                f"(chain_to_next={config.get('chain_to_next', True)}, status={_status_before_chain!r})"
            )

        return {
            "order_id": order_id,
            "status": "completed",
            "elapsed_seconds": elapsed,
            "output_dir": str(order_output),
            "output_files": output_files,
            "ptms_enriched": len(enriched_ptms),
            "next_stage": "report_generation",
        }

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        error_msg = f"RAG enrichment failed: {str(e)}"
        logger.error(f"[Order {order_id}] {error_msg}", exc_info=True)
        update_order_status(order_id, "failed", error_message=error_msg)
        notify_order_status(order_id, "failed", error_msg)
        publish_progress(
            order_id, "rag_enrichment", "error", "failed", -1, error_msg,
            metadata={"traceback": traceback.format_exc(), "elapsed_seconds": elapsed},
        )
        raise
    finally:
        try:
            mcp.close()
        except Exception:
            pass
