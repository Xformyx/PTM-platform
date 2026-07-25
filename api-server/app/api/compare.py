"""
Cross-Order Comparative Analysis API.

Compares two completed orders' reports and analysis data to identify
shared signaling mechanisms, treatment-specific responses, and temporal dynamics differences.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.comparison_report import ComparisonReport
from app.models.order import Order

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compare", tags=["compare"])


# ─── Request / Response Models ────────────────────────────────────────────────

class CompareRequest(BaseModel):
    order_id_a: int
    order_id_b: int
    llm_model: Optional[str] = None
    llm_provider: Optional[str] = None
    user_instructions: Optional[str] = None  # User's comparison focus points


class CompareChatRequest(BaseModel):
    order_id_a: int
    order_id_b: int
    messages: list[dict]  # [{"role": "user"|"assistant", "content": "..."}]
    llm_model: Optional[str] = None
    llm_provider: Optional[str] = None


class CompareSummary(BaseModel):
    """Quick numeric summary returned before the LLM report streams."""
    order_a: dict  # {id, order_code, project_name, ptm_type, species, conditions}
    order_b: dict
    shared_ptms: list[dict]  # [{gene, position, a_max_fc, b_max_fc, classification}]
    a_only_ptms: list[dict]
    b_only_ptms: list[dict]
    shared_kinases: list[str]
    a_only_kinases: list[str]
    b_only_kinases: list[str]
    shared_receptors: list[str]
    a_only_receptors: list[str]
    b_only_receptors: list[str]
    stats: dict  # {total_shared, total_a_only, total_b_only, direction_concordance, ...}


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _check_order_access(order: Order, user, db: AsyncSession):
    """Verify user has access to the order."""
    if user.role == "admin":
        return
    if order.user_id == user.id:
        return
    # Check shared access
    from app.models.order import OrderShare
    result = await db.execute(
        select(OrderShare).where(
            OrderShare.order_id == order.id,
            OrderShare.shared_with_user_id == user.id,
        )
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=403, detail="Access denied")


def _load_vector_data(output_dir: Path, ptm_type: str) -> list[dict]:
    """Load the ptm_vector_data TSV for an order."""
    import csv
    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    for name in (f"ptm_vector_data_normalized{suffix}.tsv", f"ptm_vector_data_with_motifs{suffix}.tsv"):
        p = output_dir / name
        if p.exists():
            rows = []
            with open(p, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    rows.append(row)
            return rows
    return []


def _load_report_md(output_dir: Path, ptm_type: str) -> str:
    """Load the comprehensive report markdown."""
    ptm_mode = "phospho" if ptm_type == "phosphorylation" else "ubi"
    candidates = list(output_dir.glob(f"comprehensive_report_{ptm_mode}.md"))
    if not candidates:
        candidates = list(output_dir.glob("comprehensive_report_*.md"))
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8", errors="replace")


# ─── Comparative Context Builders ────────────────────────────────────────────
# These functions extract rich temporal/mechanistic data from each order
# and format them as side-by-side comparisons for the LLM prompt.


def _build_kinase_heatmap_comparison(order_a: Order, order_b: Order) -> str:
    """Compare kinase activity heatmaps: temporal scores, co-wave groups, peak sync."""
    lines = []

    for label, order in [("A", order_a), ("B", order_b)]:
        heatmap = order.kinase_activity_heatmap
        if not heatmap:
            lines.append(f"[실험 {label}] Kinase Activity Heatmap: 데이터 없음")
            continue

        conditions = heatmap.get("conditions", [])
        kinase_scores = heatmap.get("kinase_scores", [])
        cowave_groups = heatmap.get("cowave_groups", [])

        lines.append(f"[실험 {label}] 시간대: {', '.join(conditions)}")

        # Co-Wave Groups
        if cowave_groups:
            lines.append(f"  Co-Wave Groups ({len(cowave_groups)}개):")
            for grp in cowave_groups:
                gid = grp.get("group_id", "?")
                kinases = grp.get("kinases", [])
                mean_corr = grp.get("mean_correlation", 0)
                dom_peak = grp.get("dominant_peak", "")
                lines.append(
                    f"    G{gid}: {', '.join(kinases)} "
                    f"(r={mean_corr:.2f}, peak={dom_peak})"
                )

        # Top kinase scores with temporal profile
        if kinase_scores:
            lines.append(f"  Kinase Activity Scores (상위 25개):")
            for ks in kinase_scores[:25]:
                kinase = ks.get("kinase", "")
                scores = ks.get("scores", {})
                sub_count = ks.get("substrate_count", 0)
                coherence = ks.get("coherence", 0)
                direction = ks.get("direction", "")
                peak_cond = ks.get("peak_condition", "")
                peak_score = ks.get("peak_score", 0)
                cw_group = ks.get("cowave_group", -1)

                score_str = ", ".join(f"{c}={scores.get(c, 0):.2f}" for c in conditions)
                cw_str = f", CW=G{cw_group}" if cw_group >= 0 else ""
                lines.append(
                    f"    {kinase}: [{score_str}] "
                    f"(#sub={sub_count}, coh={coherence:.2f}, "
                    f"dir={direction}, peak={peak_cond}@{peak_score:.2f}{cw_str})"
                )
        lines.append("")

    return "\n".join(lines)


def _build_temporal_cascade_comparison(order_a: Order, order_b: Order) -> str:
    """Compare temporal cascades: time-ordered kinase activation and cascade flow."""
    lines = []

    for label, order in [("A", order_a), ("B", order_b)]:
        kad = order.kinase_analysis_data or {}
        tc = kad.get("temporal_cascade", {})
        if not tc or not tc.get("timepoints"):
            lines.append(f"[실험 {label}] Temporal Cascade: 데이터 없음")
            continue

        timepoints = tc.get("timepoints", [])
        lines.append(f"[실험 {label}] Temporal Cascade ({len(timepoints)} timepoints):")

        for tp in timepoints:
            cond = tp.get("condition", "")
            minutes = tp.get("minutes", 0)
            ptm_count = tp.get("ptm_count", 0)
            kinases = tp.get("kinases", [])
            kinase_names = [k.get("canonical", "") or k.get("kinase", "") for k in kinases[:10]]
            lines.append(
                f"  {cond} ({minutes}min): {ptm_count} PTMs, "
                f"활성 kinase=[{', '.join(kinase_names)}]"
            )

        # Cascade flow (transitions between timepoints)
        cascade_flow = tc.get("cascade_flow", [])
        if cascade_flow:
            lines.append(f"  Cascade Flow (시간대 간 전이):")
            for flow in cascade_flow:
                fr = flow.get("from", "")
                to = flow.get("to", "")
                shared = flow.get("shared_kinases", [])
                new = flow.get("new_kinases", [])
                lost = flow.get("lost_kinases", [])
                lines.append(
                    f"    {fr}→{to}: 유지={shared[:8]}, "
                    f"신규활성={new[:8]}, 소실={lost[:8]}"
                )
        lines.append("")

    return "\n".join(lines)


def _build_wave_kinase_profile_comparison(order_a: Order, order_b: Order) -> str:
    """Compare wave kinase profiles: co-wave-based kinase tiers and receptors."""
    lines = []

    for label, order in [("A", order_a), ("B", order_b)]:
        kad = order.kinase_analysis_data or {}
        wkp = kad.get("wave_kinase_profile", [])
        if not wkp:
            lines.append(f"[실험 {label}] Wave Kinase Profile: 데이터 없음")
            continue

        lines.append(f"[실험 {label}] Wave Kinase Profile ({len(wkp)} waves):")
        for wave in wkp:
            wave_id = wave.get("wave_id", "")
            wave_label = wave.get("wave_label", "")
            peak_min = wave.get("peak_minutes", 0)
            tier = wave.get("tier", "")
            kinases = wave.get("kinases", [])
            cascade_ctx = wave.get("cascade_context", "")
            suggested_rec = wave.get("suggested_receptors", [])

            kinase_names = [k.get("canonical", "") or k.get("kinase", "") for k in kinases[:8]]
            rec_names = [r if isinstance(r, str) else r.get("name", "") for r in suggested_rec[:5]]

            lines.append(
                f"  Wave {wave_id} ({wave_label}, peak={peak_min}min, tier={tier}): "
                f"kinases=[{', '.join(kinase_names)}]"
            )
            if rec_names:
                lines.append(f"    suggested_receptors=[{', '.join(rec_names)}]")
            if cascade_ctx:
                lines.append(f"    cascade_context: {cascade_ctx[:150]}")
        lines.append("")

    return "\n".join(lines)


def _build_signal_flow_comparison(order_a: Order, order_b: Order) -> str:
    """Compare receptor → kinase → substrate signal flow."""
    lines = []

    for label, order in [("A", order_a), ("B", order_b)]:
        rid = order.receptor_inference_data
        if not rid:
            lines.append(f"[실험 {label}] Signal Flow: 데이터 없음")
            continue

        receptors = rid.get("receptors", []) if isinstance(rid, dict) else rid
        if not receptors:
            lines.append(f"[실험 {label}] Signal Flow: receptor 없음")
            continue

        lines.append(f"[실험 {label}] Receptor → Kinase → Substrate ({len(receptors)}개 receptor):")
        for rec in receptors[:15]:
            if not isinstance(rec, dict):
                continue
            name = rec.get("name", "") or rec.get("receptor", "")
            rec_class = rec.get("receptor_class", "")
            via_kinases = rec.get("via_kinases", [])
            downstream = rec.get("downstream_ptms", [])
            pathway = rec.get("pathway", "") or rec.get("signaling_pathway", "")
            ptm_count = rec.get("downstream_ptm_count", len(downstream))

            lines.append(
                f"  {name} ({rec_class}): {ptm_count} PTMs, "
                f"via_kinases={via_kinases[:5]}, "
                f"substrates={downstream[:6]}, "
                f"pathway={pathway}"
            )
        lines.append("")

    return "\n".join(lines)


def _build_kinase_substrate_comparison(order_a: Order, order_b: Order) -> str:
    """Compare kinase module substrate compositions between two orders."""
    lines = []

    def _get_modules(order: Order) -> dict:
        kad = order.kinase_analysis_data or {}
        modules = kad.get("kinase_modules", [])
        result = {}
        for km in modules:
            kinase = km.get("canonical", "") or km.get("kinase", "")
            members = km.get("members", [])
            sources = km.get("sources", [])
            confirmed = km.get("confirmed", 0)
            inferred = km.get("inferred", 0)
            member_labels = [
                f"{m.get('gene', '')}_{m.get('position', '')}" for m in members[:20]
            ]
            result[kinase] = {
                "count": len(members),
                "confirmed": confirmed,
                "inferred": inferred,
                "sources": sources,
                "substrates": member_labels,
            }
        return result

    mods_a = _get_modules(order_a)
    mods_b = _get_modules(order_b)

    shared_kinases = sorted(set(mods_a.keys()) & set(mods_b.keys()))
    a_only = sorted(set(mods_a.keys()) - set(mods_b.keys()))
    b_only = sorted(set(mods_b.keys()) - set(mods_a.keys()))

    if shared_kinases:
        lines.append(f"공통 Kinase Module 상세 비교 ({len(shared_kinases)}개):")
        for k in shared_kinases[:20]:
            ma = mods_a[k]
            mb = mods_b[k]
            subs_a = set(ma["substrates"])
            subs_b = set(mb["substrates"])
            shared_subs = subs_a & subs_b
            a_only_subs = subs_a - subs_b
            b_only_subs = subs_b - subs_a
            lines.append(
                f"  {k}: A={ma['count']}sub(conf={ma['confirmed']}) vs B={mb['count']}sub(conf={mb['confirmed']})"
            )
            if shared_subs:
                lines.append(f"    공통 substrate: {', '.join(sorted(shared_subs)[:10])}")
            if a_only_subs:
                lines.append(f"    A 전용 substrate: {', '.join(sorted(a_only_subs)[:10])}")
            if b_only_subs:
                lines.append(f"    B 전용 substrate: {', '.join(sorted(b_only_subs)[:10])}")

    if a_only:
        lines.append(f"\nA 전용 Kinase Module ({len(a_only)}개):")
        for k in a_only[:15]:
            ma = mods_a[k]
            lines.append(f"  {k}: {ma['count']}sub, sources={ma['sources']}, top={', '.join(ma['substrates'][:8])}")

    if b_only:
        lines.append(f"\nB 전용 Kinase Module ({len(b_only)}개):")
        for k in b_only[:15]:
            mb = mods_b[k]
            lines.append(f"  {k}: {mb['count']}sub, sources={mb['sources']}, top={', '.join(mb['substrates'][:8])}")

    return "\n".join(lines)


def _build_effector_comparison(order_a: Order, order_b: Order) -> str:
    """Compare non-PTM effector proteins between two orders."""
    lines = []

    for label, order in [("A", order_a), ("B", order_b)]:
        kad = order.kinase_analysis_data or {}
        effectors = kad.get("effector_proteins", [])
        if not effectors:
            lines.append(f"[실험 {label}] Effector Proteins: 없음")
            continue

        lines.append(f"[실험 {label}] Non-PTM Effector Proteins ({len(effectors)}개):")
        for eff in effectors[:15]:
            gene = eff.get("gene", "")
            role = eff.get("role", "")
            evidence = eff.get("evidence_strength", "")
            score = eff.get("evidence_score", 0)
            connected = eff.get("connected_substrates", [])
            conn_names = [s.get("gene", "") for s in connected[:5]] if isinstance(connected, list) else []
            lines.append(
                f"  {gene}: role={role}, evidence={evidence}(score={score}), "
                f"connected={conn_names}"
            )
        lines.append("")

    return "\n".join(lines)


def _build_comovement_comparison(output_dir_a: Path, output_dir_b: Path, ptm_type: str) -> str:
    """Compare temporal co-movement clusters between two orders."""
    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    lines = []

    for label, output_dir in [("A", output_dir_a), ("B", output_dir_b)]:
        path = output_dir / f"temporal_comovement{suffix}.json"
        if not path.exists():
            lines.append(f"[실험 {label}] Co-movement Clusters: 파일 없음")
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                lines.append(f"[실험 {label}] Co-movement Clusters: 데이터 없음")
                continue

            clusters = data if isinstance(data, list) else data.get("clusters", [])
            lines.append(f"[실험 {label}] Co-movement Clusters ({len(clusters)}개):")
            for cl in clusters[:10]:
                if isinstance(cl, dict):
                    cl_id = cl.get("cluster_id", cl.get("id", "?"))
                    peak = cl.get("peak_condition", cl.get("dominant_peak", ""))
                    members = cl.get("members", cl.get("ptms", []))
                    size = len(members) if isinstance(members, list) else cl.get("size", 0)
                    member_names = []
                    for m in (members[:8] if isinstance(members, list) else []):
                        if isinstance(m, str):
                            member_names.append(m)
                        elif isinstance(m, dict):
                            member_names.append(f"{m.get('gene', '')}_{m.get('position', '')}")
                    lines.append(
                        f"  Cluster {cl_id} (peak={peak}, size={size}): "
                        f"{', '.join(member_names)}"
                    )
        except Exception:
            lines.append(f"[실험 {label}] Co-movement Clusters: 로드 실패")
        lines.append("")

    return "\n".join(lines)


def _build_report_summary_comparison(report_a: str, report_b: str) -> str:
    """Extract key conclusions from each order's comprehensive report."""
    lines = []

    for label, report in [("A", report_a), ("B", report_b)]:
        if not report:
            lines.append(f"[실험 {label}] 개별 분석 보고서: 없음")
            continue

        # Extract abstract/conclusion sections (first 1500 chars as summary)
        # Try to find abstract or executive summary
        summary = ""
        for marker in ["## Abstract", "## Executive Summary", "## 요약", "# Abstract"]:
            idx = report.find(marker)
            if idx >= 0:
                end_idx = report.find("\n## ", idx + len(marker))
                if end_idx < 0:
                    end_idx = idx + 1500
                summary = report[idx:end_idx].strip()
                break

        if not summary:
            # Fallback: first 1200 chars
            summary = report[:1200].strip()

        if len(summary) > 1500:
            summary = summary[:1500] + "..."

        lines.append(f"[실험 {label}] 개별 분석 보고서 요약:")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines)


def _build_temporal_substrate_activity_comparison(
    vector_a: list[dict], vector_b: list[dict],
    conds_a: list[str], conds_b: list[str],
    common_conds: list[str],
    shared_ptms: list[dict],
) -> str:
    """Build temporal substrate activity comparison context.

    Analyzes:
    - Per-timepoint active substrate counts (|log2FC| > 0.5)
    - Peak activation timing distribution
    - Early vs Late responder ratios
    - Shared substrates with temporal shift (different peak in A vs B)
    """
    FC_THRESHOLD = 0.5
    lines = []

    # --- 1. Per-timepoint active substrate counts ---
    lines.append("[시간대별 활성 substrate 수 (|log2FC| > 0.5)]")
    lines.append(f"{'Condition':<12} {'A_up':>5} {'A_down':>6} {'A_total':>7}  |  {'B_up':>5} {'B_down':>6} {'B_total':>7}")

    a_per_cond: dict[str, dict] = {c: {"up": 0, "down": 0} for c in conds_a}
    b_per_cond: dict[str, dict] = {c: {"up": 0, "down": 0} for c in conds_b}

    _, a_map = _parse_vector_sites(vector_a)
    _, b_map = _parse_vector_sites(vector_b)

    for site in a_map.values():
        for c in conds_a:
            v = site["values"].get(c, 0.0)
            if v > FC_THRESHOLD:
                a_per_cond[c]["up"] += 1
            elif v < -FC_THRESHOLD:
                a_per_cond[c]["down"] += 1

    for site in b_map.values():
        for c in conds_b:
            v = site["values"].get(c, 0.0)
            if v > FC_THRESHOLD:
                b_per_cond[c]["up"] += 1
            elif v < -FC_THRESHOLD:
                b_per_cond[c]["down"] += 1

    # Display common conditions first, then unique
    display_conds = common_conds[:] if common_conds else []
    for c in conds_a:
        if c not in display_conds:
            display_conds.append(c)
    for c in conds_b:
        if c not in display_conds:
            display_conds.append(c)

    for c in display_conds[:12]:  # Limit to 12 timepoints
        a_up = a_per_cond.get(c, {}).get("up", 0)
        a_down = a_per_cond.get(c, {}).get("down", 0)
        a_total = a_up + a_down
        b_up = b_per_cond.get(c, {}).get("up", 0)
        b_down = b_per_cond.get(c, {}).get("down", 0)
        b_total = b_up + b_down
        a_str = f"{a_up:>5} {a_down:>6} {a_total:>7}" if c in a_per_cond else f"{'—':>5} {'—':>6} {'—':>7}"
        b_str = f"{b_up:>5} {b_down:>6} {b_total:>7}" if c in b_per_cond else f"{'—':>5} {'—':>6} {'—':>7}"
        lines.append(f"{c:<12} {a_str}  |  {b_str}")

    # --- 2. Peak activation timing distribution ---
    lines.append("")
    lines.append("[Peak Activation Timing 분포]")

    def _get_peak_cond(site_values: dict, conditions: list[str]) -> str:
        """Find the condition with max |FC|."""
        if not conditions or not site_values:
            return ""
        best_c, best_v = "", 0.0
        for c in conditions:
            v = abs(site_values.get(c, 0.0))
            if v > best_v:
                best_v = v
                best_c = c
        return best_c

    a_peak_dist: dict[str, int] = {c: 0 for c in conds_a}
    b_peak_dist: dict[str, int] = {c: 0 for c in conds_b}

    for site in a_map.values():
        if site["max_abs_fc"] >= FC_THRESHOLD:
            pc = _get_peak_cond(site["values"], conds_a)
            if pc:
                a_peak_dist[pc] = a_peak_dist.get(pc, 0) + 1

    for site in b_map.values():
        if site["max_abs_fc"] >= FC_THRESHOLD:
            pc = _get_peak_cond(site["values"], conds_b)
            if pc:
                b_peak_dist[pc] = b_peak_dist.get(pc, 0) + 1

    lines.append(f"{'Condition':<12} {'A_peak_count':>12} {'B_peak_count':>12}")
    for c in display_conds[:12]:
        a_cnt = a_peak_dist.get(c, 0)
        b_cnt = b_peak_dist.get(c, 0)
        if a_cnt > 0 or b_cnt > 0:
            lines.append(f"{c:<12} {a_cnt:>12} {b_cnt:>12}")

    # --- 3. Early vs Late responder ratio ---
    lines.append("")
    lines.append("[Early vs Late Responder 비율]")

    def _classify_early_late(peak_dist: dict, conditions: list[str]) -> tuple[int, int, int]:
        """Classify into early (first 1/3), mid, late (last 1/3)."""
        n = len(conditions)
        if n < 3:
            return sum(peak_dist.values()), 0, 0
        early_boundary = max(1, n // 3)
        late_boundary = n - max(1, n // 3)
        early = sum(peak_dist.get(c, 0) for c in conditions[:early_boundary])
        mid = sum(peak_dist.get(c, 0) for c in conditions[early_boundary:late_boundary])
        late = sum(peak_dist.get(c, 0) for c in conditions[late_boundary:])
        return early, mid, late

    a_early, a_mid, a_late = _classify_early_late(a_peak_dist, conds_a)
    b_early, b_mid, b_late = _classify_early_late(b_peak_dist, conds_b)
    a_total_resp = a_early + a_mid + a_late
    b_total_resp = b_early + b_mid + b_late

    lines.append(f"  실험 A: Early={a_early} ({a_early/max(a_total_resp,1)*100:.0f}%), "
                 f"Mid={a_mid} ({a_mid/max(a_total_resp,1)*100:.0f}%), "
                 f"Late={a_late} ({a_late/max(a_total_resp,1)*100:.0f}%) [총 {a_total_resp}개]")
    lines.append(f"  실험 B: Early={b_early} ({b_early/max(b_total_resp,1)*100:.0f}%), "
                 f"Mid={b_mid} ({b_mid/max(b_total_resp,1)*100:.0f}%), "
                 f"Late={b_late} ({b_late/max(b_total_resp,1)*100:.0f}%) [총 {b_total_resp}개]")

    if a_total_resp > 0 and b_total_resp > 0:
        a_ratio = a_early / max(a_late, 1)
        b_ratio = b_early / max(b_late, 1)
        if a_ratio > 2 * b_ratio:
            lines.append("  → 실험 A가 더 빠른 초기 반응 패턴을 보임")
        elif b_ratio > 2 * a_ratio:
            lines.append("  → 실험 B가 더 빠른 초기 반응 패턴을 보임")
        elif abs(a_ratio - b_ratio) < 0.3:
            lines.append("  → 두 실험의 temporal response 패턴이 유사함")

    # --- 4. Shared PTMs with temporal shift ---
    lines.append("")
    lines.append("[Temporal Shift 분석 - 동일 substrate, 다른 peak timing]")

    if common_conds and shared_ptms:
        shifts = []
        for ptm in shared_ptms:
            a_prof = ptm.get("a_profile", {})
            b_prof = ptm.get("b_profile", {})
            if not a_prof or not b_prof:
                continue
            # Find peak condition for each
            a_peak_c = max(common_conds, key=lambda c: abs(a_prof.get(c, 0.0)))
            b_peak_c = max(common_conds, key=lambda c: abs(b_prof.get(c, 0.0)))
            if a_peak_c != b_peak_c:
                a_peak_v = a_prof.get(a_peak_c, 0.0)
                b_peak_v = b_prof.get(b_peak_c, 0.0)
                # Only include if both have meaningful signal
                if abs(a_peak_v) >= FC_THRESHOLD and abs(b_peak_v) >= FC_THRESHOLD:
                    shifts.append({
                        "gene": ptm["gene"],
                        "position": ptm["position"],
                        "a_peak": a_peak_c,
                        "a_fc": a_peak_v,
                        "b_peak": b_peak_c,
                        "b_fc": b_peak_v,
                    })

        # Sort by magnitude of shift (difference in condition index)
        cond_idx = {c: i for i, c in enumerate(common_conds)}
        shifts.sort(
            key=lambda s: abs(cond_idx.get(s["a_peak"], 0) - cond_idx.get(s["b_peak"], 0)),
            reverse=True,
        )

        if shifts:
            lines.append(f"  총 {len(shifts)}개 substrate에서 temporal shift 감지")
            lines.append(f"  {'Gene':<10} {'Position':<10} {'A_peak':<10} {'A_FC':>6} {'B_peak':<10} {'B_FC':>6}")
            for s in shifts[:20]:  # Top 20
                lines.append(
                    f"  {s['gene']:<10} {s['position']:<10} {s['a_peak']:<10} "
                    f"{s['a_fc']:>+.2f} {s['b_peak']:<10} {s['b_fc']:>+.2f}"
                )
        else:
            lines.append("  Temporal shift 감지된 substrate 없음")
    else:
        lines.append("  공통 조건 또는 공통 PTM 데이터 부족")

    return "\n".join(lines)


_CHATML_TOKEN_RE = re.compile(
    r"<\|(?:im_start|im_end|endoftext|system|user|assistant)\|>",
    re.IGNORECASE,
)


def _sanitize_llm_chunk(text: str) -> str:
    """Strip ChatML / template tokens that some models leak into output."""
    if not text:
        return text
    return _CHATML_TOKEN_RE.sub("", text)


def _make_ollama_stream_filter():
    """Return a stateful filter function for a single streaming response.

    Handles two thinking-token styles:
    - ``message.thinking`` field  → ignored (already separated by Ollama)
    - ``<thought>...</thought>`` / ``<think>...</think>`` embedded in content
      (e.g. exaone-deep) → strip the thinking block, pass through the rest
    """
    buf = ""
    in_think = False
    think_done = False
    OPEN_TAGS = ("<thought>", "<think>", "<thinking>")
    CLOSE_TAGS = ("</thought>", "</think>", "</thinking>")

    def filter_chunk(chunk: str) -> str:
        nonlocal buf, in_think, think_done
        if not chunk:
            return ""
        if think_done:
            return chunk
        buf += chunk
        # Try to detect opening tag in accumulated buffer
        for otag in OPEN_TAGS:
            if otag in buf:
                in_think = True
                break
        if in_think:
            for ctag in CLOSE_TAGS:
                if ctag in buf:
                    # Strip everything up to and including the closing tag
                    idx = buf.index(ctag) + len(ctag)
                    remainder = buf[idx:].lstrip("\n")
                    buf = ""
                    think_done = True
                    return remainder
            # Still inside thinking block — emit nothing
            return ""
        # No opening tag found; once we've accumulated enough to be sure,
        # flush and mark done
        if len(buf) >= 30:
            think_done = True
            out = buf
            buf = ""
            return out
        return ""

    return filter_chunk


def _ollama_chat_payload(
    model: str,
    messages: list[dict],
    *,
    temperature: float,
    num_predict: int,
    num_ctx: int = 32768,
) -> dict:
    """Build an Ollama /api/chat payload.

    ``think: false`` suppresses internal reasoning for models that support it
    (qwen3.5, glm-4.7, etc.). The streaming filter above handles models that
    embed thinking in ``<thought>`` / ``<think>`` tags within the content field.
    """
    return {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        },
    }


def _condition_sort_key(s: str) -> tuple:
    """Sort time-point labels chronologically (0.5h, 1h, 24h, ...)."""
    s_str = str(s).strip()
    m = re.match(r"^([\d.]+)\s*(sec|s|min|m|hr|h|hour|d|day)s?$", s_str, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit in ("sec", "s"):
            return (val / 60.0, "")
        if unit in ("min", "m"):
            return (val, "")
        if unit in ("hr", "h", "hour"):
            return (val * 60.0, "")
        if unit in ("d", "day"):
            return (val * 1440.0, "")
    m2 = re.match(r"^([\d.]+)$", s_str)
    if m2:
        return (float(m2.group(1)), "")
    return (float("inf"), s_str)


def _is_long_format(vector_data: list[dict]) -> bool:
    if not vector_data:
        return False
    row = vector_data[0]
    return bool(row.get("Condition") or row.get("condition"))


def _extract_wide_conditions(vector_data: list[dict]) -> list[str]:
    """Extract condition columns from wide-format vector data."""
    if not vector_data:
        return []
    skip_cols = {
        "Gene", "Position", "Protein", "Motif", "Sequence", "UniProt_ID",
        "PTM_Score", "Localization_Prob", "Motif_Class", "Kinase_Prediction",
        "gene", "position", "protein", "motif", "sequence", "uniprot_id",
        "ptm_score", "localization_prob", "motif_class", "kinase_prediction",
        "max_abs_fc", "peak_condition", "direction", "cluster_id",
        "Gene.Name", "PTM_Position", "Condition", "Comparison",
        "PTM_Relative_Log2FC", "PTM_Absolute_Log2FC", "Protein.Group",
    }
    skip_lower = {c.lower() for c in skip_cols}
    first_row = vector_data[0]
    conditions = []
    for col in first_row.keys():
        if col in skip_cols or col.lower() in skip_lower:
            continue
        try:
            float(first_row[col])
            conditions.append(col)
        except (ValueError, TypeError):
            continue
    return sorted(conditions, key=_condition_sort_key)


def _parse_vector_sites(vector_data: list[dict]) -> tuple[list[str], dict[str, dict]]:
    """Parse vector TSV rows into per-site time series (long or wide format)."""
    if not vector_data:
        return [], {}

    if _is_long_format(vector_data):
        conditions_set: set[str] = set()
        sites: dict[str, dict] = {}
        for row in vector_data:
            gene = (
                row.get("Gene.Name") or row.get("Gene") or row.get("gene") or ""
            ).strip()
            position = str(
                row.get("PTM_Position") or row.get("Position") or row.get("position") or ""
            ).strip()
            if not gene and not position:
                continue
            key = f"{gene}_{position}"
            cond = (row.get("Condition") or row.get("condition") or "").strip()
            if not cond:
                continue
            fc_raw = row.get("PTM_Relative_Log2FC")
            if fc_raw in (None, ""):
                fc_raw = row.get("PTM_Absolute_Log2FC")
            try:
                fc = float(fc_raw or 0)
            except (ValueError, TypeError):
                fc = 0.0
            conditions_set.add(cond)
            if key not in sites:
                sites[key] = {
                    "gene": gene,
                    "position": position,
                    "values": {},
                    "max_abs_fc": 0.0,
                }
            sites[key]["values"][cond] = fc
            abs_fc = abs(fc)
            if abs_fc > sites[key]["max_abs_fc"]:
                sites[key]["max_abs_fc"] = abs_fc
        conditions = sorted(conditions_set, key=_condition_sort_key)
        return conditions, sites

    conditions = _extract_wide_conditions(vector_data)
    sites = {}
    for row in vector_data:
        gene = (row.get("Gene") or row.get("gene") or "").strip()
        position = str(row.get("Position") or row.get("position") or "").strip()
        if not gene and not position:
            continue
        key = f"{gene}_{position}"
        values = {}
        max_abs = 0.0
        for cond in conditions:
            try:
                v = float(row.get(cond, 0))
            except (ValueError, TypeError):
                v = 0.0
            values[cond] = v
            if abs(v) > max_abs:
                max_abs = abs(v)
        sites[key] = {
            "gene": gene,
            "position": position,
            "values": values,
            "max_abs_fc": max_abs,
        }
    return conditions, sites


def _extract_conditions(vector_data: list[dict]) -> list[str]:
    """Extract ordered condition names from vector data."""
    conditions, _ = _parse_vector_sites(vector_data)
    return conditions


def _extract_top_ptms(vector_data: list[dict], top_n: int = 50) -> list[dict]:
    """Extract top N PTMs by max absolute fold-change."""
    _, sites = _parse_vector_sites(vector_data)
    ptms = list(sites.values())
    ptms.sort(key=lambda x: x["max_abs_fc"], reverse=True)
    return ptms[:top_n]


def _classify_response(corr: float, a_max: float, b_max: float) -> str:
    """Classify the response pattern between two orders for a shared PTM."""
    if corr > 0.8 and abs(a_max - b_max) / max(abs(a_max), abs(b_max), 0.01) < 0.3:
        return "identical"
    elif corr > 0.8:
        return "dose_dependent"
    elif corr > 0.6:
        return "delayed"
    elif corr < -0.5:
        return "opposite"
    else:
        return "independent"


def _compute_correlation(vals_a: list[float], vals_b: list[float]) -> float:
    """Compute Pearson correlation between two value lists."""
    n = len(vals_a)
    if n < 2:
        return 0.0
    mean_a = sum(vals_a) / n
    mean_b = sum(vals_b) / n
    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(vals_a, vals_b))
    std_a = (sum((a - mean_a) ** 2 for a in vals_a)) ** 0.5
    std_b = (sum((b - mean_b) ** 2 for b in vals_b)) ** 0.5
    if std_a < 1e-10 or std_b < 1e-10:
        return 0.0
    return cov / (std_a * std_b)


def _build_comparison_data(
    order_a: Order, order_b: Order,
    vector_a: list[dict], vector_b: list[dict],
) -> dict:
    """Build the comparison summary data."""
    conds_a, a_map = _parse_vector_sites(vector_a)
    conds_b, b_map = _parse_vector_sites(vector_b)

    shared_keys = set(a_map.keys()) & set(b_map.keys())
    a_only_keys = set(a_map.keys()) - set(b_map.keys())
    b_only_keys = set(b_map.keys()) - set(a_map.keys())

    # Find common conditions for correlation
    common_conds = [c for c in conds_a if c in conds_b]

    # Classify shared PTMs
    shared_ptms = []
    concordant = 0
    for key in sorted(shared_keys):
        pa = a_map[key]
        pb = b_map[key]
        if common_conds:
            vals_a = [pa["values"].get(c, 0.0) for c in common_conds]
            vals_b = [pb["values"].get(c, 0.0) for c in common_conds]
            corr = _compute_correlation(vals_a, vals_b)
        else:
            corr = 0.0
            vals_a = list(pa["values"].values())
            vals_b = list(pb["values"].values())

        a_max = max(vals_a, key=abs) if vals_a else 0.0
        b_max = max(vals_b, key=abs) if vals_b else 0.0
        classification = _classify_response(corr, a_max, b_max)

        # Direction concordance
        if (a_max > 0 and b_max > 0) or (a_max < 0 and b_max < 0):
            concordant += 1

        # Build per-condition profile strings for prompt use
        a_profile = {c: round(pa["values"].get(c, 0.0), 3) for c in common_conds} if common_conds else {}
        b_profile = {c: round(pb["values"].get(c, 0.0), 3) for c in common_conds} if common_conds else {}

        shared_ptms.append({
            "gene": pa["gene"],
            "position": pa["position"],
            "a_max_fc": round(a_max, 3),
            "b_max_fc": round(b_max, 3),
            "correlation": round(corr, 3),
            "classification": classification,
            "a_profile": a_profile,
            "b_profile": b_profile,
        })

    shared_ptms.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    a_only_ptms = [{"gene": a_map[k]["gene"], "position": a_map[k]["position"],
                    "max_fc": round(a_map[k]["max_abs_fc"], 3)} for k in sorted(a_only_keys)]
    b_only_ptms = [{"gene": b_map[k]["gene"], "position": b_map[k]["position"],
                    "max_fc": round(b_map[k]["max_abs_fc"], 3)} for k in sorted(b_only_keys)]

    # Extract kinases from kinase_analysis_data
    def _get_kinases(order: Order) -> list[str]:
        data = order.kinase_analysis_data or {}
        modules = data.get("kinase_modules", [])
        kinases = set()
        for m in modules:
            if isinstance(m, dict):
                k = m.get("kinase") or m.get("name", "")
                if k:
                    kinases.add(k)
        return sorted(kinases)

    # Extract receptors from receptor_inference_data
    def _get_receptors(order: Order) -> list[str]:
        data = order.receptor_inference_data
        if not data:
            return []
        receptors = set()
        items = data if isinstance(data, list) else data.get("receptors", [])
        for r in items:
            if isinstance(r, dict):
                name = r.get("name") or r.get("receptor", "")
                if name:
                    receptors.add(name)
        return sorted(receptors)

    kinases_a = _get_kinases(order_a)
    kinases_b = _get_kinases(order_b)
    receptors_a = _get_receptors(order_a)
    receptors_b = _get_receptors(order_b)

    shared_kinases = sorted(set(kinases_a) & set(kinases_b))
    a_only_kinases = sorted(set(kinases_a) - set(kinases_b))
    b_only_kinases = sorted(set(kinases_b) - set(kinases_a))
    shared_receptors = sorted(set(receptors_a) & set(receptors_b))
    a_only_receptors = sorted(set(receptors_a) - set(receptors_b))
    b_only_receptors = sorted(set(receptors_b) - set(receptors_a))

    # Classification counts
    class_counts = {}
    for p in shared_ptms:
        c = p["classification"]
        class_counts[c] = class_counts.get(c, 0) + 1

    direction_concordance = concordant / len(shared_ptms) if shared_ptms else 0.0

    return {
        "order_a": {
            "id": order_a.id,
            "order_code": order_a.order_code,
            "project_name": order_a.project_name,
            "ptm_type": order_a.ptm_type,
            "species": order_a.species,
            "conditions": conds_a,
        },
        "order_b": {
            "id": order_b.id,
            "order_code": order_b.order_code,
            "project_name": order_b.project_name,
            "ptm_type": order_b.ptm_type,
            "species": order_b.species,
            "conditions": conds_b,
        },
        "shared_ptms": shared_ptms,
        "a_only_ptms": a_only_ptms,
        "b_only_ptms": b_only_ptms,
        "shared_kinases": shared_kinases,
        "a_only_kinases": a_only_kinases,
        "b_only_kinases": b_only_kinases,
        "shared_receptors": shared_receptors,
        "a_only_receptors": a_only_receptors,
        "b_only_receptors": b_only_receptors,
        "stats": {
            "total_shared": len(shared_ptms),
            "total_a_only": len(a_only_ptms),
            "total_b_only": len(b_only_ptms),
            "direction_concordance": round(direction_concordance, 3),
            "classification_counts": class_counts,
            "common_conditions": common_conds,
            "shared_kinase_count": len(shared_kinases),
            "shared_receptor_count": len(shared_receptors),
        },
    }


def _build_comparison_prompt(
    comparison_data: dict,
    report_a: str,
    report_b: str,
    user_instructions: str = "",
    *,
    order_a: Optional[Order] = None,
    order_b: Optional[Order] = None,
    output_dir_a: Optional[Path] = None,
    output_dir_b: Optional[Path] = None,
    vector_a: Optional[list[dict]] = None,
    vector_b: Optional[list[dict]] = None,
) -> str:
    """Build the LLM prompt for comparative analysis from structured data.

    Includes rich temporal/mechanistic context:
    - Kinase Activity Heatmap (temporal scores, co-wave groups)
    - Temporal Cascade (time-ordered kinase activation flow)
    - Wave Kinase Profile (co-wave-based upstream regulator inference)
    - Signal Flow (receptor → kinase → substrate cascade)
    - Kinase substrate composition comparison
    - Effector proteins comparison
    - Co-movement clusters comparison
    - Individual report summaries
    """
    order_a_info = comparison_data["order_a"]
    order_b_info = comparison_data["order_b"]
    stats = comparison_data["stats"]
    common_conds = stats.get("common_conditions", [])

    # ── Shared PTMs: top 30 with temporal profiles ──────────────────────────
    top_shared = sorted(
        comparison_data["shared_ptms"],
        key=lambda p: max(abs(p["a_max_fc"]), abs(p["b_max_fc"])),
        reverse=True,
    )[:30]

    shared_lines = []
    for p in top_shared:
        gene_pos = f"{p['gene']} {p['position']}"
        if common_conds and p.get("a_profile") and p.get("b_profile"):
            a_vals = "  ".join(f"{c}:{p['a_profile'].get(c, 0):+.2f}" for c in common_conds)
            b_vals = "  ".join(f"{c}:{p['b_profile'].get(c, 0):+.2f}" for c in common_conds)
            shared_lines.append(
                f"  {gene_pos}  [r={p['correlation']:.2f}, class={p['classification']}]\n"
                f"    A: {a_vals}\n"
                f"    B: {b_vals}"
            )
        else:
            shared_lines.append(
                f"  {gene_pos}  A_max={p['a_max_fc']:+.2f}  B_max={p['b_max_fc']:+.2f}"
                f"  r={p['correlation']:.2f}  class={p['classification']}"
            )

    # ── A-only and B-only PTMs: top 20 each ─────────────────────────────────
    top_a_only = sorted(comparison_data["a_only_ptms"], key=lambda p: abs(p["max_fc"]), reverse=True)[:20]
    top_b_only = sorted(comparison_data["b_only_ptms"], key=lambda p: abs(p["max_fc"]), reverse=True)[:20]
    a_only_lines = [f"  {p['gene']} {p['position']}  max_fc={p['max_fc']:+.2f}" for p in top_a_only]
    b_only_lines = [f"  {p['gene']} {p['position']}  max_fc={p['max_fc']:+.2f}" for p in top_b_only]

    user_focus = (
        user_instructions.strip()
        if user_instructions and user_instructions.strip()
        else "일반적인 비교 분석 수행 (공통 경로, 물질 특이적 반응, temporal dynamics 비교)"
    )

    # ── Build rich comparative context sections ────────────────────────────
    rich_sections = []

    if order_a and order_b:
        # Kinase Activity Heatmap comparison (temporal scores per condition)
        heatmap_ctx = _build_kinase_heatmap_comparison(order_a, order_b)
        if heatmap_ctx.strip():
            rich_sections.append(f"════ Kinase Activity Heatmap 비교 (시간대별 활성도) ════\n\n{heatmap_ctx}")

        # Temporal Cascade comparison (time-ordered kinase activation)
        cascade_ctx = _build_temporal_cascade_comparison(order_a, order_b)
        if cascade_ctx.strip():
            rich_sections.append(f"════ Temporal Cascade 비교 (시간 순서 kinase 활성화 흐름) ════\n\n{cascade_ctx}")

        # Wave Kinase Profile comparison (co-wave upstream regulators)
        wave_ctx = _build_wave_kinase_profile_comparison(order_a, order_b)
        if wave_ctx.strip():
            rich_sections.append(f"════ Wave Kinase Profile 비교 (Co-Wave 기반 Upstream Regulator) ════\n\n{wave_ctx}")

        # Signal Flow comparison (receptor → kinase → substrate)
        signal_ctx = _build_signal_flow_comparison(order_a, order_b)
        if signal_ctx.strip():
            rich_sections.append(f"════ Signal Flow 비교 (Receptor → Kinase → Substrate) ════\n\n{signal_ctx}")

        # Kinase substrate composition comparison
        substrate_ctx = _build_kinase_substrate_comparison(order_a, order_b)
        if substrate_ctx.strip():
            rich_sections.append(f"════ Kinase Substrate 구성 비교 ════\n\n{substrate_ctx}")

        # Effector proteins comparison
        effector_ctx = _build_effector_comparison(order_a, order_b)
        if effector_ctx.strip():
            rich_sections.append(f"════ Non-PTM Effector Proteins 비교 ════\n\n{effector_ctx}")

    # Co-movement clusters comparison
    if output_dir_a and output_dir_b and order_a:
        ptm_type_str = order_a_info.get("ptm_type", "phosphorylation")
        comove_ctx = _build_comovement_comparison(output_dir_a, output_dir_b, ptm_type_str)
        if comove_ctx.strip():
            rich_sections.append(f"════ Temporal Co-movement Clusters 비교 ════\n\n{comove_ctx}")

    # Temporal Substrate Activity comparison
    if vector_a and vector_b:
        conds_a = comparison_data["order_a"].get("conditions", [])
        conds_b = comparison_data["order_b"].get("conditions", [])
        tsa_ctx = _build_temporal_substrate_activity_comparison(
            vector_a, vector_b, conds_a, conds_b, common_conds,
            comparison_data["shared_ptms"],
        )
        if tsa_ctx.strip():
            rich_sections.append(f"════ Temporal Substrate Activity 비교 ════\n\n{tsa_ctx}")

    # Individual report summaries
    report_summary_ctx = _build_report_summary_comparison(report_a, report_b)
    if report_summary_ctx.strip():
        rich_sections.append(f"════ 개별 분석 보고서 요약 ════\n\n{report_summary_ctx}")

    rich_context_block = "\n\n".join(rich_sections)

    prompt = f"""당신은 PTM(번역 후 변형) 프로테오믹스 전문 선임 연구자입니다.
두 PTM 시계열 실험의 비교 분석 리포트를 아래 제공된 정량적 데이터를 기반으로 한국어로 작성하세요.

════ 실험 정보 ════

[실험 A] {order_a_info['project_name']}
  - 종: {order_a_info['species']}, PTM 유형: {order_a_info['ptm_type']}
  - 시간대(조건): {', '.join(order_a_info['conditions'])}

[실험 B] {order_b_info['project_name']}
  - 종: {order_b_info['species']}, PTM 유형: {order_b_info['ptm_type']}
  - 시간대(조건): {', '.join(order_b_info['conditions'])}

════ 정량적 비교 요약 ════

공통 PTM site: {stats['total_shared']}개  |  A 전용: {stats['total_a_only']}개  |  B 전용: {stats['total_b_only']}개
방향 일치율: {stats['direction_concordance']:.1%}
반응 패턴 분류: {json.dumps(stats['classification_counts'], ensure_ascii=False)}

공통 Kinase ({stats['shared_kinase_count']}개): {', '.join(comparison_data['shared_kinases'][:20]) or '없음'}
A 전용 Kinase: {', '.join(comparison_data['a_only_kinases'][:15]) or '없음'}
B 전용 Kinase: {', '.join(comparison_data['b_only_kinases'][:15]) or '없음'}

공통 Receptor ({stats['shared_receptor_count']}개): {', '.join(comparison_data['shared_receptors'][:15]) or '없음'}
A 전용 Receptor: {', '.join(comparison_data['a_only_receptors'][:10]) or '없음'}
B 전용 Receptor: {', '.join(comparison_data['b_only_receptors'][:10]) or '없음'}

════ 공통 PTM 상위 {len(top_shared)}개 — 시계열 프로파일 ════
(조건: {', '.join(common_conds) if common_conds else 'N/A'})

{chr(10).join(shared_lines) if shared_lines else '공통 PTM 없음'}

════ A 전용 PTM 상위 {len(top_a_only)}개 ════

{chr(10).join(a_only_lines) if a_only_lines else '없음'}

════ B 전용 PTM 상위 {len(top_b_only)}개 ════

{chr(10).join(b_only_lines) if b_only_lines else '없음'}

{rich_context_block}

════ 분석 초점 ════

{user_focus}

════ 작성 지시 ════

위 데이터를 바탕으로 다음 8개 섹션의 비교 분석 리포트를 작성하세요.
각 섹션당 300~500단어, 구체적인 유전자명·위치·수치 인용 필수.

## 1. Temporal Substrate Activity 비교
시간대별로 활성화(|log2FC|>0.5)되는 substrate 수를 비교하여 반응 규모의 시간적 차이를 서술.
Peak activation timing 분포를 비교하여 어느 시간대에 가장 많은 substrate가 반응하는지 분석.
Early/Mid/Late responder 비율을 비교하여 두 실험의 temporal response 패턴 차이를 해석.
Temporal shift가 큰 공통 substrate를 식별하여 동일 단백질이 다른 시간대에 인산화되는 현상을 설명.

## 2. Temporal Signaling Cascade 비교
시간대별로 어떤 kinase가 활성화되는지 두 실험을 나란히 비교.
Co-Wave Group 정보를 활용하여 동시에 활성화되는 kinase 클러스터를 식별.
Cascade Flow(시간대 간 kinase 유지/신규/소실)를 비교하여 신호전달 흐름의 차이를 서술.

## 3. Co-Wave 기반 Upstream Regulator 비교
Wave Kinase Profile에서 예측된 upstream regulator(receptor, kinase)를 비교.
각 wave의 tier, peak timing, suggested receptor를 대조하여 상위 신호 입력의 차이를 해석.

## 4. 공통 Signaling Mechanism
두 실험에서 공통으로 활성화된 신호전달 경로 및 kinase를 서술.
공통 kinase의 substrate 구성 차이도 분석 (동일 kinase가 다른 substrate를 인산화하는 패턴).

## 5. 물질 특이적 반응 및 작용기전
각 실험에서만 나타나는 고유한 신호 이벤트를 서술.
Signal Flow (Receptor → Kinase → Substrate) 정보를 활용하여 작용기전을 설명.
Effector protein 차이도 포함.

## 6. Kinase Activity 정량 비교
두 실험의 kinase activity score를 시간대별로 직접 비교.
coherence, direction, peak timing 차이를 해석.
공통/고유 기질 인산화 패턴의 생물학적 의미를 설명.

## 7. Signaling Divergence 분기점
공통 상위 신호에서 실험별로 어떻게 분기되는지 경로 매핑.
Temporal co-movement cluster 차이를 활용하여 분기 시점과 원인을 식별.

## 8. 종합 결론 및 치료적 함의
두 실험의 세포신호전달 차이를 종합하여 작용기전의 핵심 차이를 명확히 설명.
공통/고유 경로 기반 약물 타겟 제안, 병용 또는 길항 가능성 논의.

주의: 제공된 데이터에 근거한 결론만 작성하고, 데이터가 없는 경우 추측임을 명시하세요.
"""
    return prompt


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/summary")
async def get_comparison_summary(
    body: CompareRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get quantitative comparison summary between two orders (no LLM call)."""
    from app.config import get_settings
    settings = get_settings()

    # Load both orders
    result_a = await db.execute(select(Order).where(Order.id == body.order_id_a))
    order_a = result_a.scalar_one_or_none()
    result_b = await db.execute(select(Order).where(Order.id == body.order_id_b))
    order_b = result_b.scalar_one_or_none()

    if not order_a or not order_b:
        raise HTTPException(status_code=404, detail="One or both orders not found")

    await _check_order_access(order_a, user, db)
    await _check_order_access(order_b, user, db)

    # Validate: both must be completed
    if order_a.status != "completed" or order_b.status != "completed":
        raise HTTPException(status_code=400, detail="Both orders must be completed")

    # Validate: same species and PTM type
    if order_a.species != order_b.species:
        raise HTTPException(status_code=400, detail=f"Species mismatch: {order_a.species} vs {order_b.species}")
    if order_a.ptm_type != order_b.ptm_type:
        raise HTTPException(status_code=400, detail=f"PTM type mismatch: {order_a.ptm_type} vs {order_b.ptm_type}")

    # Load vector data
    output_dir_a = Path(settings.OUTPUT_DIR) / order_a.order_code
    output_dir_b = Path(settings.OUTPUT_DIR) / order_b.order_code
    vector_a = _load_vector_data(output_dir_a, order_a.ptm_type)
    vector_b = _load_vector_data(output_dir_b, order_b.ptm_type)

    if not vector_a or not vector_b:
        raise HTTPException(status_code=400, detail="Vector data not available for one or both orders")

    comparison = _build_comparison_data(order_a, order_b, vector_a, vector_b)
    return comparison


@router.post("/report")
async def stream_comparison_report(
    body: CompareRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Stream LLM-generated comparative analysis report (SSE)."""
    from app.config import get_settings
    settings = get_settings()

    # Load both orders
    result_a = await db.execute(select(Order).where(Order.id == body.order_id_a))
    order_a = result_a.scalar_one_or_none()
    result_b = await db.execute(select(Order).where(Order.id == body.order_id_b))
    order_b = result_b.scalar_one_or_none()

    if not order_a or not order_b:
        raise HTTPException(status_code=404, detail="One or both orders not found")

    await _check_order_access(order_a, user, db)
    await _check_order_access(order_b, user, db)

    if order_a.status != "completed" or order_b.status != "completed":
        raise HTTPException(status_code=400, detail="Both orders must be completed")
    if order_a.species != order_b.species:
        raise HTTPException(status_code=400, detail="Species mismatch")
    if order_a.ptm_type != order_b.ptm_type:
        raise HTTPException(status_code=400, detail="PTM type mismatch")

    # Load data
    output_dir_a = Path(settings.OUTPUT_DIR) / order_a.order_code
    output_dir_b = Path(settings.OUTPUT_DIR) / order_b.order_code
    vector_a = _load_vector_data(output_dir_a, order_a.ptm_type)
    vector_b = _load_vector_data(output_dir_b, order_b.ptm_type)

    if not vector_a or not vector_b:
        raise HTTPException(status_code=400, detail="Vector data not available")

    # Build comparison data and prompt
    comparison = _build_comparison_data(order_a, order_b, vector_a, vector_b)
    report_a = _load_report_md(output_dir_a, order_a.ptm_type)
    report_b = _load_report_md(output_dir_b, order_b.ptm_type)
    prompt = _build_comparison_prompt(
        comparison, report_a, report_b, body.user_instructions or "",
        order_a=order_a, order_b=order_b,
        output_dir_a=output_dir_a, output_dir_b=output_dir_b,
        vector_a=vector_a, vector_b=vector_b,
    )

    # Determine LLM settings
    llm_model = body.llm_model or (order_a.report_options or {}).get("llm_model") or os.getenv("LLM_MODEL", "gemma3:27b")
    llm_provider = body.llm_provider or os.getenv("LLM_PROVIDER", "auto")
    ollama_url = settings.OLLAMA_URL

    # Determine provider and endpoint
    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    async def _stream():
        """Stream LLM response as SSE events."""
        import re as _re

        # First send the summary data
        yield f"data: {json.dumps({'type': 'summary', 'data': comparison})}\n\n"

        try:
            # Determine which provider to use
            use_provider = llm_provider
            if use_provider == "auto":
                # Try Ollama first, then OpenAI, then Gemini
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                        resp = await client.get(f"{ollama_url}/api/tags")
                        if resp.status_code == 200:
                            use_provider = "ollama"
                        else:
                            use_provider = "openai" if openai_key else ("gemini" if gemini_key else "ollama")
                except Exception:
                    use_provider = "openai" if openai_key else ("gemini" if gemini_key else "ollama")

            if use_provider == "ollama":
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=600.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{ollama_url}/api/chat",
                        json=_ollama_chat_payload(
                            llm_model,
                            [
                                {"role": "system", "content": "You are a senior proteomics bioinformatician specializing in comparative PTM analysis."},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.6,
                            num_predict=8192,
                        ),
                    ) as resp:
                        if resp.status_code != 200:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM error: {resp.status_code}'})}\n\n"
                            return
                        had_content = False
                        think_filter = _make_ollama_stream_filter()
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                raw = data.get("message", {}).get("content", "")
                                content = _sanitize_llm_chunk(think_filter(raw))
                                done = data.get("done", False)
                                if content and content.strip():
                                    had_content = True
                                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                                if done:
                                    if not had_content:
                                        reason = data.get("done_reason", "unknown")
                                        model_hint = "gemma3:27b 또는 qwen2.5:14b 모델을 선택해 주세요."
                                        yield f"data: {json.dumps({'type': 'error', 'message': f'선택한 모델이 비교 분석 리포트를 생성하지 못했습니다 (reason={reason}). {model_hint}'})}\n\n"
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            except json.JSONDecodeError:
                                continue

            elif use_provider in ("openai", "gemini"):
                api_key = openai_key if use_provider == "openai" else gemini_key
                base_url = (
                    os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
                    if use_provider == "openai"
                    else "https://generativelanguage.googleapis.com/v1beta/openai"
                )
                model = llm_model if llm_model != "gemma3:27b" else (
                    os.getenv("OPENAI_MODEL", "gpt-4.1-mini") if use_provider == "openai"
                    else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                )

                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=600.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": "You are a senior proteomics bioinformatician specializing in comparative PTM analysis."},
                                {"role": "user", "content": prompt},
                            ],
                            "stream": True,
                            "temperature": 0.6,
                            "max_tokens": 8192,
                        },
                    ) as resp:
                        if resp.status_code != 200:
                            error_text = ""
                            async for chunk in resp.aiter_text():
                                error_text += chunk
                            yield f"data: {json.dumps({'type': 'error', 'message': f'API error ({resp.status_code}): {error_text[:200]}'})}\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:]
                            if payload.strip() == "[DONE]":
                                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                break
                            try:
                                data = json.loads(payload)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = _sanitize_llm_chunk(delta.get("content", ""))
                                if content:
                                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                            except (json.JSONDecodeError, IndexError):
                                continue

        except httpx.ConnectError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Cannot connect to LLM service'})}\n\n"
        except Exception as e:
            logger.exception("Comparison report streaming error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:200]})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Saved Report Endpoints ───────────────────────────────────────────────────

class SaveReportRequest(BaseModel):
    order_id_a: int
    order_id_b: int
    report_text: str
    chat_messages: Optional[list] = None
    llm_model: Optional[str] = None
    user_instructions: Optional[str] = None


@router.post("/save")
async def save_comparison_report(
    body: SaveReportRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Save (upsert) a comparison report for a given order pair and user."""
    from app.models.comparison_report import ComparisonReport as CR
    user_id = user.id if user else None

    stmt = select(CR).where(
        CR.order_id_a == body.order_id_a,
        CR.order_id_b == body.order_id_b,
        CR.user_id == user_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.report_text = body.report_text
        existing.chat_messages = body.chat_messages
        existing.llm_model = body.llm_model
        existing.user_instructions = body.user_instructions
        record = existing
    else:
        record = CR(
            order_id_a=body.order_id_a,
            order_id_b=body.order_id_b,
            user_id=user_id,
            report_text=body.report_text,
            chat_messages=body.chat_messages,
            llm_model=body.llm_model,
            user_instructions=body.user_instructions,
        )
        db.add(record)

    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "report_text": record.report_text or "",
        "chat_messages": record.chat_messages or [],
        "llm_model": record.llm_model,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.post("/save-chat")
async def save_comparison_chat_only(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Update only chat_messages for an existing comparison report."""
    from app.models.comparison_report import ComparisonReport as CR
    order_id_a: int = body.get("order_id_a")
    order_id_b: int = body.get("order_id_b")
    chat_messages: list = body.get("chat_messages", [])
    user_id = user.id if user else None

    stmt = select(CR).where(
        CR.order_id_a == order_id_a,
        CR.order_id_b == order_id_b,
        CR.user_id == user_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.chat_messages = chat_messages
        await db.commit()
        return {"ok": True}
    return {"ok": False, "detail": "No saved report found for this pair"}


@router.get("/saved")
async def get_saved_report(
    a: int = Query(..., description="Order A ID"),
    b: int = Query(..., description="Order B ID"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Retrieve a previously saved comparison report for the given order pair."""
    from app.models.comparison_report import ComparisonReport as CR
    user_id = user.id if user else None

    stmt = select(CR).where(
        CR.order_id_a == a,
        CR.order_id_b == b,
        CR.user_id == user_id,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="No saved report found")

    return {
        "id": record.id,
        "order_id_a": record.order_id_a,
        "order_id_b": record.order_id_b,
        "report_text": record.report_text or "",
        "chat_messages": record.chat_messages or [],
        "llm_model": record.llm_model,
        "user_instructions": record.user_instructions,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@router.get("/list")
async def list_comparison_reports(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List all saved comparison reports for the current user, with order metadata."""
    from app.models.comparison_report import ComparisonReport as CR
    user_id = user.id if user else None

    stmt = (
        select(CR)
        .where(CR.user_id == user_id)
        .order_by(CR.updated_at.desc())
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    # Collect all order IDs to batch-fetch order metadata
    order_ids = {r.order_id_a for r in records} | {r.order_id_b for r in records}
    orders_map: dict[int, dict] = {}
    if order_ids:
        ord_result = await db.execute(
            select(Order).where(Order.id.in_(order_ids))
        )
        for o in ord_result.scalars().all():
            orders_map[o.id] = {
                "id": o.id,
                "order_code": o.order_code,
                "project_name": o.project_name,
            }

    return [
        {
            "id": r.id,
            "order_id_a": r.order_id_a,
            "order_id_b": r.order_id_b,
            "order_a": orders_map.get(r.order_id_a, {"id": r.order_id_a, "order_code": "?", "project_name": "Unknown"}),
            "order_b": orders_map.get(r.order_id_b, {"id": r.order_id_b, "order_code": "?", "project_name": "Unknown"}),
            "llm_model": r.llm_model,
            "chat_count": len(r.chat_messages) if r.chat_messages else 0,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in records
    ]


@router.delete("/saved/{report_id}")
async def delete_comparison_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a saved comparison report (only the owner can delete)."""
    from app.models.comparison_report import ComparisonReport as CR
    user_id = user.id if user else None

    stmt = select(CR).where(CR.id == report_id, CR.user_id == user_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Report not found or not owned by you")

    await db.delete(record)
    await db.commit()
    return {"ok": True}


@router.post("/export-pdf")
async def export_comparison_pdf(
    body: CompareRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export a saved comparison report as a formatted PDF.

    Retrieves the saved report text and converts it to a professional
    PDF using the Typst template.
    """
    from app.models.comparison_report import ComparisonReport as CR
    from app.services.pdf_report_generator import generate_report_pdf

    user_id = user.id if user else None

    # Get saved report
    stmt = select(CR).where(
        CR.order_id_a == body.order_id_a,
        CR.order_id_b == body.order_id_b,
        CR.user_id == user_id,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record or not record.report_text:
        raise HTTPException(
            status_code=404,
            detail="No saved report found. Generate and save a report first."
        )

    # Get order metadata
    order_a = await db.get(Order, body.order_id_a)
    order_b = await db.get(Order, body.order_id_b)
    if not order_a or not order_b:
        raise HTTPException(status_code=404, detail="Order not found")

    # Generate PDF
    import tempfile
    output_dir = Path(tempfile.mkdtemp())
    try:
        pdf_path = generate_report_pdf(
            markdown_content=record.report_text,
            experiment_a=order_a.project_name or order_a.order_code,
            experiment_b=order_b.project_name or order_b.order_code,
            species=order_a.species or "",
            ptm_type=order_a.ptm_type or "phosphorylation",
            output_path=output_dir / "comparative_report.pdf",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    # Return PDF as file response
    from fastapi.responses import FileResponse
    filename = f"comparative_{order_a.order_code}_vs_{order_b.order_code}.pdf"
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/chat")
async def stream_comparison_chat(
    body: CompareChatRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Stream follow-up Q&A about the comparison (SSE). Data-grounded answers."""
    from app.config import get_settings
    settings = get_settings()

    # Load both orders
    result_a = await db.execute(select(Order).where(Order.id == body.order_id_a))
    order_a = result_a.scalar_one_or_none()
    result_b = await db.execute(select(Order).where(Order.id == body.order_id_b))
    order_b = result_b.scalar_one_or_none()

    if not order_a or not order_b:
        raise HTTPException(status_code=404, detail="One or both orders not found")

    await _check_order_access(order_a, user, db)
    await _check_order_access(order_b, user, db)

    if order_a.status != "completed" or order_b.status != "completed":
        raise HTTPException(status_code=400, detail="Both orders must be completed")

    # Load data for context
    output_dir_a = Path(settings.OUTPUT_DIR) / order_a.order_code
    output_dir_b = Path(settings.OUTPUT_DIR) / order_b.order_code
    vector_a = _load_vector_data(output_dir_a, order_a.ptm_type)
    vector_b = _load_vector_data(output_dir_b, order_b.ptm_type)
    comparison = _build_comparison_data(order_a, order_b, vector_a, vector_b)
    report_a = _load_report_md(output_dir_a, order_a.ptm_type)
    report_b = _load_report_md(output_dir_b, order_b.ptm_type)

    # Build system prompt with data context
    order_a_info = comparison["order_a"]
    order_b_info = comparison["order_b"]
    stats = comparison["stats"]

    common_conds = stats.get("common_conditions", [])
    top_shared = sorted(
        comparison["shared_ptms"],
        key=lambda p: max(abs(p["a_max_fc"]), abs(p["b_max_fc"])),
        reverse=True,
    )[:20]

    def _fmt_shared(p: dict) -> str:
        gene_pos = f"{p['gene']} {p['position']}"
        if common_conds and p.get("a_profile") and p.get("b_profile"):
            a_v = "  ".join(f"{c}:{p['a_profile'].get(c,0):+.2f}" for c in common_conds[:6])
            b_v = "  ".join(f"{c}:{p['b_profile'].get(c,0):+.2f}" for c in common_conds[:6])
            return f"  {gene_pos} [r={p['correlation']:.2f}]\n    A: {a_v}\n    B: {b_v}"
        return f"  {gene_pos}: A={p['a_max_fc']:+.2f}, B={p['b_max_fc']:+.2f}, r={p['correlation']:.2f}"

    shared_table = "\n".join(_fmt_shared(p) for p in top_shared)
    a_only_table = "\n".join(
        f"  {p['gene']} {p['position']}: {p['max_fc']:+.2f}"
        for p in sorted(comparison["a_only_ptms"], key=lambda x: abs(x["max_fc"]), reverse=True)[:15]
    )
    b_only_table = "\n".join(
        f"  {p['gene']} {p['position']}: {p['max_fc']:+.2f}"
        for p in sorted(comparison["b_only_ptms"], key=lambda x: abs(x["max_fc"]), reverse=True)[:15]
    )

    # Build rich temporal/mechanistic context for chat
    chat_rich_sections = []
    if order_a and order_b:
        _hm = _build_kinase_heatmap_comparison(order_a, order_b)
        if _hm.strip():
            chat_rich_sections.append(f"[KINASE ACTIVITY HEATMAP 비교]\n{_hm}")
        _tc = _build_temporal_cascade_comparison(order_a, order_b)
        if _tc.strip():
            chat_rich_sections.append(f"[TEMPORAL CASCADE 비교]\n{_tc}")
        _wk = _build_wave_kinase_profile_comparison(order_a, order_b)
        if _wk.strip():
            chat_rich_sections.append(f"[WAVE KINASE PROFILE 비교]\n{_wk}")
        _sf = _build_signal_flow_comparison(order_a, order_b)
        if _sf.strip():
            chat_rich_sections.append(f"[SIGNAL FLOW 비교]\n{_sf}")
        _ks = _build_kinase_substrate_comparison(order_a, order_b)
        if _ks.strip():
            chat_rich_sections.append(f"[KINASE SUBSTRATE 구성 비교]\n{_ks}")
        _ef = _build_effector_comparison(order_a, order_b)
        if _ef.strip():
            chat_rich_sections.append(f"[EFFECTOR PROTEINS 비교]\n{_ef}")

    ptm_type_for_chat = order_a_info.get("ptm_type", "phosphorylation")
    _cm = _build_comovement_comparison(output_dir_a, output_dir_b, ptm_type_for_chat)
    if _cm.strip():
        chat_rich_sections.append(f"[CO-MOVEMENT CLUSTERS 비교]\n{_cm}")

    # Temporal Substrate Activity for chat
    if vector_a and vector_b:
        _tsa = _build_temporal_substrate_activity_comparison(
            vector_a, vector_b,
            order_a_info.get("conditions", []),
            order_b_info.get("conditions", []),
            common_conds,
            comparison["shared_ptms"],
        )
        if _tsa.strip():
            chat_rich_sections.append(f"[TEMPORAL SUBSTRATE ACTIVITY 비교]\n{_tsa}")

    _rpt = _build_report_summary_comparison(report_a, report_b)
    if _rpt.strip():
        chat_rich_sections.append(f"[개별 보고서 요약]\n{_rpt}")

    chat_rich_block = "\n\n".join(chat_rich_sections)

    system_prompt = f"""당신은 PTM 프로테오믹스 전문 선임 연구자입니다. 두 실험 비교 결과에 대한 후속 질문에 답변합니다.

중요 규칙: 아래 데이터에 근거한 답변만 하세요. 데이터에 없는 내용은 추측임을 명시하세요.

[실험 A] {order_a_info['project_name']} ({order_a_info['species']}, {order_a_info['ptm_type']})
  조건: {', '.join(order_a_info['conditions'])}

[실험 B] {order_b_info['project_name']} ({order_b_info['species']}, {order_b_info['ptm_type']})
  조건: {', '.join(order_b_info['conditions'])}

공통 PTM: {stats['total_shared']}개 | A 전용: {stats['total_a_only']}개 | B 전용: {stats['total_b_only']}개
방향 일치율: {stats['direction_concordance']:.1%}
반응 패턴: {json.dumps(stats.get('classification_counts', {{}}), ensure_ascii=False)}

공통 Kinase: {', '.join(comparison['shared_kinases'][:20]) or '없음'}
A 전용 Kinase: {', '.join(comparison['a_only_kinases'][:15]) or '없음'}
B 전용 Kinase: {', '.join(comparison['b_only_kinases'][:15]) or '없음'}
공통 Receptor: {', '.join(comparison['shared_receptors'][:15]) or '없음'}
A 전용 Receptor: {', '.join(comparison['a_only_receptors'][:10]) or '없음'}
B 전용 Receptor: {', '.join(comparison['b_only_receptors'][:10]) or '없음'}

공통 PTM 상위 20개 (조건: {', '.join(common_conds[:6]) if common_conds else 'N/A'}):
{shared_table or '없음'}

A 전용 PTM:
{a_only_table or '없음'}

B 전용 PTM:
{b_only_table or '없음'}

{chat_rich_block}

답변 형식: 한국어, 영문 유전자명 사용, 구체적 수치 인용, 마크다운 형식."""

    # Build messages list for LLM
    llm_messages = [{"role": "system", "content": system_prompt}]
    for msg in body.messages:
        if msg.get("role") in ("user", "assistant"):
            llm_messages.append({"role": msg["role"], "content": msg["content"]})

    # Determine LLM settings
    llm_model = body.llm_model or os.getenv("LLM_MODEL", "gemma3:27b")
    llm_provider = body.llm_provider or os.getenv("LLM_PROVIDER", "auto")
    ollama_url = settings.OLLAMA_URL
    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    async def _stream():
        try:
            use_provider = llm_provider
            if use_provider == "auto":
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                        resp = await client.get(f"{ollama_url}/api/tags")
                        if resp.status_code == 200:
                            use_provider = "ollama"
                        else:
                            use_provider = "openai" if openai_key else ("gemini" if gemini_key else "ollama")
                except Exception:
                    use_provider = "openai" if openai_key else ("gemini" if gemini_key else "ollama")

            if use_provider == "ollama":
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=600.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{ollama_url}/api/chat",
                        json=_ollama_chat_payload(
                            llm_model,
                            llm_messages,
                            temperature=0.4,
                            num_predict=4096,
                        ),
                    ) as resp:
                        if resp.status_code != 200:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM error: {resp.status_code}'})}\n\n"
                            return
                        had_content = False
                        think_filter = _make_ollama_stream_filter()
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                raw = data.get("message", {}).get("content", "")
                                content = _sanitize_llm_chunk(think_filter(raw))
                                done = data.get("done", False)
                                if content and content.strip():
                                    had_content = True
                                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                                if done:
                                    if not had_content:
                                        reason = data.get("done_reason", "unknown")
                                        yield f"data: {json.dumps({'type': 'error', 'message': f'모델이 답변을 생성하지 못했습니다 (reason={reason}). gemma3:27b 또는 qwen2.5:14b를 선택해 주세요.'})}\n\n"
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            except json.JSONDecodeError:
                                continue

            elif use_provider in ("openai", "gemini"):
                api_key = openai_key if use_provider == "openai" else gemini_key
                base_url = (
                    os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
                    if use_provider == "openai"
                    else "https://generativelanguage.googleapis.com/v1beta/openai"
                )
                model = llm_model if llm_model != "gemma3:27b" else (
                    os.getenv("OPENAI_MODEL", "gpt-4.1-mini") if use_provider == "openai"
                    else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                )

                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=600.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": llm_messages,
                            "stream": True,
                            "temperature": 0.4,
                            "max_tokens": 4096,
                        },
                    ) as resp:
                        if resp.status_code != 200:
                            error_text = ""
                            async for chunk in resp.aiter_text():
                                error_text += chunk
                            yield f"data: {json.dumps({'type': 'error', 'message': f'API error ({resp.status_code}): {error_text[:200]}'})}\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:]
                            if payload.strip() == "[DONE]":
                                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                break
                            try:
                                data = json.loads(payload)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = _sanitize_llm_chunk(delta.get("content", ""))
                                if content:
                                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                            except (json.JSONDecodeError, IndexError):
                                continue

        except httpx.ConnectError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Cannot connect to LLM service'})}\n\n"
        except Exception as e:
            logger.exception("Comparison chat streaming error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:200]})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
