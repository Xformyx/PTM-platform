"""
PTM Analysis AI Chat — Context-aware conversational assistant.

Provides an SSE-streaming chat endpoint that assembles rich context from:
  1. Generated report (comprehensive_report_*.md)
  2. Enriched PTM data (enriched_ptm_data_*.json)
  3. Kinase module analysis (DB: order.kinase_analysis_data)
  4. Signal flow / receptor inference (DB: order.receptor_inference_data)
  5. Signal propagation timeline (DB: order.signal_propagation_data)
  6. Temporal co-movement clusters (file)
  7. ChromaDB RAG collections (user-selected)
  8. Pipeline methodology documentation (fixed)
  9. Current view state (checked PTMs, active tab, etc.)

Model: exaone-deep:7.8b (Ollama, fixed)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import AsyncSessionLocal, get_db
from app.dependencies import get_current_user
from app.models.chat_message import ChatMessage as ChatMessageDB  # DB model (renamed to avoid clash)
from app.models.order import Order
from app.models.rag_collection import RagCollection

router = APIRouter(prefix="/orders", tags=["chat"])
logger = logging.getLogger("ptm-platform.chat")

CHAT_MODEL = "exaone-deep:7.8b"
MAX_CONTEXT_CHARS = 28000  # ~7K tokens budget for context (leaving room for conversation)
MAX_REPORT_CHARS = 8000
MAX_KINASE_CHARS = 6000
MAX_RAG_CHARS = 5000

# ── Pipeline Methodology (fixed text, ~1.5K chars) ──────────────────────────

METHODOLOGY_CONTEXT = """
## PTM-Vector Analysis Methodology

**PTM-Vector Approach**: Unlike traditional PTM analysis that only considers PTM fold-change,
PTM-Vector uses a 2D vector representation: (Protein_Log2FC, PTM_Relative_Log2FC).
PTM_Relative_Log2FC = PTM_Absolute_Log2FC - Protein_Log2FC, isolating PTM-specific changes
from protein abundance changes. This reveals true PTM regulation independent of protein expression.

**PTM Selection Modes**:
- De novo: PTMs not detected in control (pseudocount imputed) — strongest biological signal
- Regulated: Statistically significant (q < 0.05, |Log2FC| ≥ 1.0) — reliable quantitative changes
- De novo + Regulated: Union of both — recommended default for comprehensive coverage

**Receptor Inference**: Three sources:
- Source A: Literature-based upstream_regulators from RAG enrichment
- Source B: Reactome pathway mapping (kinase → known receptor, unbiased)
- Source C: Treatment-context (ligand → known receptor DB)

**Kinase Module Analysis**: Groups substrates by shared upstream kinases using
KEA3 (Kinase Enrichment Analysis 3), kinase_prediction, and kinase_substrate databases.
Modules represent coordinated signaling cascades.

**Signal Flow (4-Layer)**: Receptor → Kinase → Substrate (PTM) → Effector
Effectors are non-PTM proteins from STRING (score ≥ 400) / BioGRID PPI partners.

**Evidence Scoring** (0–5 scale):
- Concordant direction (+1): kinase and substrate change in same direction
- Time-lag (+1): substrate change follows kinase change temporally
- Multi-substrate (+1): kinase has ≥ 3 substrates in dataset
- Strong FC (+1): |Log2FC| > 1.0
- Multi-source (+1): kinase found in ≥ 2 databases
→ Strong (≥ 4), Moderate (2–3), Weak (≤ 1)

**Kinase Activity Heatmap** (v11.3 — Stratified Clustering + Winsorized Mean):
Computes per-kinase temporal activity scores through:
1. Stratified Clustering: substrates grouped by magnitude tier:
   - Tier 1 (Strong): max |Log2FC| > 5.0 (de novo / high-amplitude)
   - Tier 2 (Moderate): 2.0 < max |Log2FC| ≤ 5.0
   - Tier 3 (Weak): max |Log2FC| ≤ 2.0
2. Within each tier, K-Means with Absolute Correlation (1-|r|) distance:
   - Anti-correlated substrates (e.g., +3 and -3) cluster together
   - Sign-folded before clustering, then tagged as positive/negative targets
3. Dominant cluster selection: coherence × √size × |peak_score| × tier_bonus
4. Scoring: Winsorized Mean (5th/95th percentile) per condition — outlier-robust
   - NOT a sum; represents average substrate response magnitude
   - Each timepoint scored independently (never averaged across time)
- Direction: activation (▲, positive Winsorized Mean), inactivation (▼, negative)
- Coherence: mean pairwise |Pearson r| within dominant cluster (0 to 1 scale)
- Confidence: weighted evidence score based on substrate count, source quality
- Substrates classified as Exclusive (1 kinase) or Shared (2+ kinases)

**Co-Wave Groups (CW Groups)**: Kinases whose temporal activity score profiles are
highly correlated (Pearson r≥0.7) are grouped together. Same CW Group = substrates
phosphorylated by these kinases move together over time. This implies:
- Shared upstream signaling input (common activating signal)
- Participation in the same signaling cascade
- Coordinated temporal regulation of downstream substrates
Peak Synchronization: identifies timepoints where multiple kinases reach peak activity.

**Temporal Co-movement**: Clusters PTMs by temporal profile similarity using
correlation-based clustering. 8 canonical patterns: early_transient, sustained_up,
delayed_response, biphasic, oscillatory, sustained_down, late_onset, gradual_decline.
"""


# ── Pydantic models for request ──────────────────────────────────────────────

class ChatMessageSchema(BaseModel):
    """Pydantic schema for conversation history messages."""
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessageSchema] = []
    view_context: Optional[Dict[str, Any]] = None
    rag_collection_ids: Optional[List[int]] = None
    response_language: str = "auto"  # "ko", "en", or "auto" (match user's language)


# ── Context Assembly ─────────────────────────────────────────────────────────


def _load_report_summary(output_dir: Path, file_suffix: str) -> str:
    """Load report MD and truncate to fit context budget.
    
    Search order:
    1. Glob pattern: {order_code}_report_*.md (actual report naming convention)
    2. Legacy names: comprehensive_report{suffix}.md, final_report.md, report.md
    """
    report_path = None
    
    # 1. Try glob pattern matching (actual naming: {order_code}_report_{YYMMDD_HHMM}.md)
    report_candidates = sorted(
        output_dir.glob("*_report_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,  # Most recent first
    )
    if report_candidates:
        report_path = report_candidates[0]
        logger.info(f"Found report via glob: {report_path.name}")
    
    # 2. Fallback to legacy names
    if not report_path or not report_path.exists():
        for name in (
            f"comprehensive_report{file_suffix}.md",
            "final_report.md",
            "report.md",
        ):
            alt = output_dir / name
            if alt.exists():
                report_path = alt
                logger.info(f"Found report via legacy name: {name}")
                break
    
    if not report_path or not report_path.exists():
        logger.warning(f"No report file found in {output_dir}")
        return ""
    
    try:
        text = report_path.read_text(encoding="utf-8")
        logger.info(f"Loaded report: {report_path.name} ({len(text)} chars)")
        if len(text) > MAX_REPORT_CHARS:
            # Keep abstract + first sections, truncate middle
            lines = text.split("\n")
            kept = []
            chars = 0
            for line in lines:
                chars += len(line) + 1
                kept.append(line)
                if chars > MAX_REPORT_CHARS:
                    kept.append("\n... [Report truncated for context window] ...")
                    break
            return "\n".join(kept)
        return text
    except Exception as e:
        logger.warning(f"Failed to load report: {e}")
        return ""


def _load_enriched_ptm_summary(output_dir: Path, file_suffix: str) -> str:
    """Load enriched PTM data and create a concise summary."""
    path = output_dir / f"enriched_ptm_data{file_suffix}.json"
    if not path.exists():
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return ""

        lines = [f"Total enriched PTMs: {len(data)}"]
        # Summarize top PTMs with key info — include more for better coverage
        for ptm in data[:60]:  # Top 60 for context (was 30)
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")
            rag = ptm.get("rag_enrichment", {})
            if isinstance(rag, dict):
                reg = rag.get("regulation", {})
                if isinstance(reg, dict):
                    upstream = reg.get("upstream_regulators", [])
                    downstream = reg.get("downstream_targets", [])
                    function = reg.get("function_summary", "")
                    ks = reg.get("kinase_substrate", [])
                    ks_text = ""
                    if isinstance(ks, list) and ks:
                        ks_names = [k.get("kinase", "") for k in ks if isinstance(k, dict)]
                        ks_text = f", kinases={ks_names[:3]}" if ks_names else ""
                    lines.append(
                        f"- {gene} {pos}: upstream={upstream[:3]}, "
                        f"downstream={downstream[:3]}{ks_text}, function={function[:100]}"
                    )
                else:
                    lines.append(f"- {gene} {pos}")
            else:
                lines.append(f"- {gene} {pos}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to load enriched PTM data: {e}")
        return ""


def _load_kinase_modules_from_file(output_dir: Path, file_suffix: str) -> str:
    """Load kinase module analysis results from file (fallback)."""
    path = output_dir / f"global_kinase_modules{file_suffix}.json"
    if not path.exists():
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return ""

        text = json.dumps(data, indent=1, default=str)
        if len(text) > MAX_KINASE_CHARS:
            text = text[:MAX_KINASE_CHARS] + "\n... [truncated]"
        return text
    except Exception as e:
        logger.warning(f"Failed to load kinase modules: {e}")
        return ""


def _build_kinase_analysis_context(order: Order) -> str:
    """Build kinase module analysis context from DB (order.kinase_analysis_data).
    This is the PRIMARY source — contains kinase → substrate mappings with evidence."""
    kad = order.kinase_analysis_data
    if not kad:
        return ""

    lines = []
    kinase_modules = kad.get("kinase_modules", [])
    if kinase_modules:
        lines.append(f"Total kinase modules: {len(kinase_modules)}")
        for km in kinase_modules:
            kinase = km.get("kinase", "") or km.get("canonical", "")
            members = km.get("members", [])
            sources = km.get("sources", [])
            confirmed = km.get("confirmed", 0)
            inferred = km.get("inferred", 0)
            member_labels = [
                f"{m.get('gene', '')}_{m.get('position', '')}" for m in members[:15]
            ]
            lines.append(
                f"- {kinase}: {len(members)} substrates "
                f"(confirmed={confirmed}, inferred={inferred}), "
                f"sources={sources}, "
                f"substrates=[{', '.join(member_labels)}]"
            )
            if len(members) > 15:
                lines.append(f"  ... and {len(members) - 15} more substrates")

    # Effector proteins
    effectors = kad.get("effector_proteins", [])
    if effectors:
        lines.append(f"\nNon-PTM Effector Proteins: {len(effectors)}")
        for eff in effectors[:20]:
            gene = eff.get("gene", "")
            role = eff.get("role", "")
            evidence = eff.get("evidence_strength", "")
            score = eff.get("evidence_score", 0)
            connected = eff.get("connected_substrates", [])
            conn_names = [s.get("gene", "") for s in connected[:5]] if isinstance(connected, list) else []
            lines.append(
                f"- {gene}: role={role}, evidence={evidence}(score={score}), "
                f"connected_substrates={conn_names}"
            )

    text = "\n".join(lines)
    if len(text) > MAX_KINASE_CHARS:
        text = text[:MAX_KINASE_CHARS] + "\n... [truncated]"
    return text


def _build_kinase_activity_heatmap_context(order: Order) -> str:
    """Build Kinase Activity Heatmap context from DB (order.kinase_activity_heatmap).
    Contains per-kinase temporal activity scores, CW Groups, coherence, and peak sync."""
    heatmap = order.kinase_activity_heatmap
    if not heatmap:
        return ""

    lines = []
    conditions = heatmap.get("conditions", [])
    kinase_scores = heatmap.get("kinase_scores", [])
    cowave_groups = heatmap.get("cowave_groups", [])
    peak_sync = heatmap.get("peak_sync", {})

    if conditions:
        lines.append(f"Time conditions: {', '.join(conditions)}")

    # Co-Wave Groups (kinases with correlated temporal substrate activity, r≥0.7)
    if cowave_groups:
        lines.append(f"\nCo-Wave Groups ({len(cowave_groups)} groups detected):")
        lines.append("(Kinases in the same CW Group have substrates whose phosphorylation")
        lines.append(" levels move together over time — Pearson r≥0.7)")
        for grp in cowave_groups:
            gid = grp.get("group_id", "?")
            kinases = grp.get("kinases", [])
            size = grp.get("size", 0)
            mean_corr = grp.get("mean_correlation", 0)
            dom_peak = grp.get("dominant_peak", "")
            lines.append(
                f"  G{gid}: {', '.join(kinases)} "
                f"(size={size}, r={mean_corr:.2f}, dominant_peak={dom_peak})"
            )

    # Peak Synchronization
    if peak_sync:
        lines.append(f"\nPeak Synchronization (kinases peaking at same timepoint):")
        for cond, info in peak_sync.items():
            ks_list = info.get("kinases", []) if isinstance(info, dict) else []
            count = info.get("count", len(ks_list)) if isinstance(info, dict) else 0
            lines.append(f"  {cond}: {count} kinases — {', '.join(ks_list[:10])}")

    # Per-kinase activity scores (v11.3: Stratified Clustering + Winsorized Mean)
    threshold_info = heatmap.get("scoring_threshold", {})
    if kinase_scores:
        lines.append(f"\nKinase Activity Scores ({len(kinase_scores)} kinases):")
        lines.append(f"Scoring: Winsorized Mean (5th/95th percentile) of dominant cluster substrates per condition")
        lines.append(f"Clustering: Stratified by magnitude tier (Strong >5.0, Moderate 2-5, Weak ≤2.0) + Absolute Correlation K-Means")
        lines.append(f"Threshold: q<{threshold_info.get('q_value', 0.05)} or |Log2FC|≥{threshold_info.get('fc_abs', 0.3)}")
        lines.append("Score = average substrate response magnitude (NOT sum). Higher |score| = stronger directional signal.")
        lines.append("Substrates classified as Exclusive (mapped to 1 kinase) or Shared (2+ kinases).")
        for ks in kinase_scores[:40]:  # Top 40 kinases
            kinase = ks.get("kinase", "")
            scores = ks.get("scores", {})
            sub_count = ks.get("substrate_count", 0)
            confidence = ks.get("confidence", 0)
            coherence = ks.get("coherence", 0)
            direction = ks.get("direction", "")
            peak_cond = ks.get("peak_condition", "")
            peak_score = ks.get("peak_score", 0)
            cw_group = ks.get("cowave_group", -1)
            coact_counts = ks.get("coact_counts", {})
            excl_counts = ks.get("exclusive_counts", {})
            shared_counts = ks.get("shared_counts", {})

            score_str = ", ".join(f"{c}={scores.get(c, 0):.2f}" for c in conditions)
            cw_str = f", CW=G{cw_group}" if cw_group >= 0 else ""
            # Co-activation detail for peak condition
            peak_coact = coact_counts.get(peak_cond, 0)
            peak_excl = excl_counts.get(peak_cond, 0)
            peak_shared = shared_counts.get(peak_cond, 0)
            lines.append(
                f"  {kinase}: [{score_str}] "
                f"(#sub={sub_count}, coact@peak={peak_coact} [excl={peak_excl}/shared={peak_shared}], "
                f"conf={confidence:.0%}, coh={coherence:.2f}, "
                f"dir={direction}, peak={peak_cond}@{peak_score:.2f}{cw_str})"
            )
        if len(kinase_scores) > 40:
            lines.append(f"  ... and {len(kinase_scores) - 40} more kinases")

    text = "\n".join(lines)
    if len(text) > 8000:
        text = text[:8000] + "\n... [truncated]"
    return text


def _build_signal_flow_context(order: Order) -> str:
    """Build Signal Flow context from DB (order.receptor_inference_data).
    Contains receptor → kinase → substrate cascade information."""
    rid = order.receptor_inference_data
    if not rid:
        return ""

    receptors = rid.get("receptors", [])
    if not receptors:
        return ""

    lines = [f"Total inferred receptors: {len(receptors)}"]
    for rec in receptors:
        name = rec.get("name", "")
        rec_class = rec.get("receptor_class", "")
        ptm_count = rec.get("downstream_ptm_count", 0)
        downstream_ptms = rec.get("downstream_ptms", [])
        via_kinases = rec.get("via_kinases", [])
        pathway = rec.get("pathway", "") or rec.get("signaling_pathway", "")
        source = rec.get("source", "")

        kinase_text = f", via_kinases={via_kinases}" if via_kinases else ""
        pathway_text = f", pathway={pathway}" if pathway else ""

        lines.append(
            f"- {name} ({rec_class}): {ptm_count} downstream PTMs, "
            f"substrates={downstream_ptms[:8]}{kinase_text}{pathway_text}, source={source}"
        )

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n... [truncated]"
    return text


def _build_signal_propagation_context(order: Order) -> str:
    """Build Signal Propagation Timeline context from DB."""
    spd = order.signal_propagation_data
    if not spd:
        return ""
    try:
        text = json.dumps(spd, indent=1, default=str)
        if len(text) > 3000:
            text = text[:3000] + "\n... [truncated]"
        return text
    except Exception:
        return ""


def _load_comovement_clusters(output_dir: Path, file_suffix: str) -> str:
    """Load temporal co-movement cluster data."""
    path = output_dir / f"temporal_comovement{file_suffix}.json"
    if not path.exists():
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return ""
        text = json.dumps(data, indent=1, default=str)
        if len(text) > 3000:
            text = text[:3000] + "\n... [truncated]"
        return text
    except Exception as e:
        logger.warning(f"Failed to load co-movement data: {e}")
        return ""


async def _query_chromadb_collections(
    collection_names: List[str],
    query_text: str,
    n_results: int = 5,
    chromadb_url: str = "http://chromadb:8000",
) -> str:
    """Query ChromaDB collections for relevant literature context."""
    if not collection_names:
        return ""

    results = []
    try:
        import chromadb
        host = chromadb_url.replace("http://", "").split(":")[0]
        port = int(chromadb_url.split(":")[-1])
        client = chromadb.HttpClient(host=host, port=port)

        existing = {c.name for c in client.list_collections()}

        for coll_name in collection_names:
            if coll_name not in existing:
                continue
            try:
                coll = client.get_collection(name=coll_name)
                res = coll.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )
                docs = res.get("documents", [[]])[0]
                metas = res.get("metadatas", [[]])[0]
                dists = res.get("distances", [[]])[0]

                for doc, meta, dist in zip(docs, metas, dists):
                    relevance = max(0, 1.0 - dist)
                    if relevance >= 0.3:
                        title = (meta or {}).get("title", "Unknown")
                        source = (meta or {}).get("source", "")
                        results.append(
                            f"[{title}] (relevance: {relevance:.2f}, collection: {coll_name})\n"
                            f"{doc[:400]}"
                        )
            except Exception as e:
                logger.warning(f"ChromaDB query failed for '{coll_name}': {e}")

    except Exception as e:
        logger.warning(f"ChromaDB connection failed: {e}")
        return ""

    if not results:
        return ""

    text = "\n\n".join(results[:8])  # Top 8 results
    if len(text) > MAX_RAG_CHARS:
        text = text[:MAX_RAG_CHARS] + "\n... [truncated]"
    return text


def _build_view_context_text(view_context: Optional[Dict[str, Any]]) -> str:
    """Convert frontend view state to context text."""
    if not view_context:
        return ""

    parts = []
    if view_context.get("active_tab"):
        parts.append(f"User is currently viewing: {view_context['active_tab']} tab")
    if view_context.get("checked_ptms"):
        ptms = view_context["checked_ptms"]
        if isinstance(ptms, list) and len(ptms) > 0:
            parts.append(f"Currently selected/checked PTMs ({len(ptms)}): {', '.join(ptms[:20])}")
            if len(ptms) > 20:
                parts.append(f"  ... and {len(ptms) - 20} more")
    if view_context.get("selected_module") is not None:
        parts.append(f"Selected kinase module: Module {view_context['selected_module']}")
    if view_context.get("metric"):
        parts.append(f"Metric mode: {view_context['metric']}")
    if view_context.get("trend_filter") and view_context["trend_filter"] != "all":
        parts.append(f"Trend filter: {view_context['trend_filter']}")
    if view_context.get("activity_filter") and view_context["activity_filter"] != "all":
        parts.append(f"Activity filter: {view_context['activity_filter']}")

    return "\n".join(parts)


async def _assemble_context(
    order: Order,
    settings: Settings,
    view_context: Optional[Dict[str, Any]],
    rag_collection_names: List[str],
    user_message: str,
) -> str:
    """Assemble full context for the chat system prompt."""
    output_dir = Path(settings.OUTPUT_DIR) / (order.order_code or str(order.id))
    file_suffix = "_phospho" if (order.ptm_type or "phosphorylation") == "phosphorylation" else "_ubi"

    sections = []

    # 1. Experiment context
    ctx = order.analysis_context or {}
    exp_info = []
    if order.ptm_type:
        exp_info.append(f"PTM type: {order.ptm_type}")
    if ctx.get("species"):
        exp_info.append(f"Species: {ctx['species']}")
    if ctx.get("cell_type"):
        exp_info.append(f"Cell type: {ctx['cell_type']}")
    if ctx.get("treatment"):
        exp_info.append(f"Treatment: {ctx['treatment']}")
    if ctx.get("time_points"):
        exp_info.append(f"Time points: {ctx['time_points']}")
    rqs = (order.report_options or {}).get("research_questions", [])
    if rqs:
        exp_info.append(f"Research questions: {'; '.join(rqs)}")
    if exp_info:
        sections.append("[EXPERIMENT CONTEXT]\n" + "\n".join(exp_info))

    # 2. Current view state
    view_text = _build_view_context_text(view_context)
    if view_text:
        sections.append("[CURRENT VIEW STATE]\n" + view_text)

    # 3. Report summary
    report = _load_report_summary(output_dir, file_suffix)
    if report:
        sections.append("[ANALYSIS REPORT]\n" + report)

    # 4. Enriched PTM summary
    ptm_summary = _load_enriched_ptm_summary(output_dir, file_suffix)
    if ptm_summary:
        sections.append("[ENRICHED PTM DATA]\n" + ptm_summary)

    # 5. Kinase module results — PRIMARY from DB, fallback to file
    kinase_db = _build_kinase_analysis_context(order)
    if kinase_db:
        sections.append("[KINASE MODULE ANALYSIS (from DB)]\n" + kinase_db)
    else:
        kinase_file = _load_kinase_modules_from_file(output_dir, file_suffix)
        if kinase_file:
            sections.append("[KINASE MODULE ANALYSIS]\n" + kinase_file)

    # 5b. Kinase Activity Heatmap — temporal activity scores, CW Groups, coherence (from DB)
    heatmap_ctx = _build_kinase_activity_heatmap_context(order)
    if heatmap_ctx:
        sections.append("[KINASE ACTIVITY HEATMAP: TEMPORAL SCORES & CO-WAVE GROUPS]\n" + heatmap_ctx)

    # 6. Signal Flow — receptor → kinase → substrate cascade (from DB)
    signal_flow = _build_signal_flow_context(order)
    if signal_flow:
        sections.append("[SIGNAL FLOW: RECEPTOR → KINASE → SUBSTRATE]\n" + signal_flow)

    # 7. Signal Propagation Timeline (from DB)
    signal_prop = _build_signal_propagation_context(order)
    if signal_prop:
        sections.append("[SIGNAL PROPAGATION TIMELINE]\n" + signal_prop)

    # 8. Co-movement clusters
    comovement = _load_comovement_clusters(output_dir, file_suffix)
    if comovement:
        sections.append("[TEMPORAL CO-MOVEMENT CLUSTERS]\n" + comovement)

    # 9. Pipeline methodology
    sections.append("[PIPELINE METHODOLOGY]\n" + METHODOLOGY_CONTEXT.strip())

    # 10. RAG collection context (dynamic, based on user question)
    if rag_collection_names:
        chromadb_url = settings.CHROMADB_URL
        rag_text = await _query_chromadb_collections(
            rag_collection_names, user_message, n_results=5, chromadb_url=chromadb_url
        )
        if rag_text:
            sections.append("[RELEVANT LITERATURE FROM RAG COLLECTIONS]\n" + rag_text)

    return "\n\n".join(sections)


# ── SSE Streaming Endpoint ───────────────────────────────────────────────────


SYSTEM_PROMPT_TEMPLATE = """당신은 POTATO AI입니다. PTM-Vector 분석 플랫폼에 내장된 연구 도우미입니다.
아래 제공된 분석 데이터를 기반으로 연구자의 질문에 답변합니다.

필수 규칙:
1. 모든 답변은 반드시 "저는 POTATO AI 입니다. 연구자님의 질문에 대해 답하겠습니다." 로 시작하세요.
2. 핵심만 간결하게 답변하세요. 3-5문장 이내로 핵심 결론을 먼저 말하고, 마지막에 "더 자세히 설명해드릴까요?" 라고 물어보세요.
3. 사용자가 "자세히", "구체적으로", "더 설명해줘" 등을 요청하면 그때 상세하게 데이터를 인용하며 설명하세요.
4. 딸딸한 학술체가 아니라, 동료 연구자에게 말하듯 자연스러운 구어체로 대화하세요. ("이건 ~해요", "아마 ~일 거예요", "~로 보이네요" 등)
5. 데이터가 답변을 뒷받침할 때는 구체적인 값(fold-change, p-value, score)을 인용하세요.
6. 신뢰도/신뢰성 질문에는 Evidence Scoring(0-5점)을 참조하세요.
7. 방법론 질문에는 Pipeline Methodology 섹션을 참조하세요.
8. 문헌 기반 답변 시 RAG collection 출처를 인용하세요.
9. 데이터가 부족하면 솔직하게 "이 부분은 데이터가 부족해서 확실하게 말씀드리기 어렵네요" 라고 말하세요.
10. 반드시 아래 제공된 [SIGNAL FLOW], [KINASE MODULE ANALYSIS], [KINASE ACTIVITY HEATMAP], [ENRICHED PTM DATA] 섹션의 실제 데이터를 참조하여 답변하세요. 데이터에 있는 정보를 "없다"고 말하지 마세요.
11. [KINASE ACTIVITY HEATMAP] 섹션에는 각 kinase의 시간대별 Winsorized Mean score, Co-Wave Group (CW Group) 정보, coherence, direction, peak synchronization, exclusive/shared substrate 구분 데이터가 있습니다. Score는 dominant cluster substrate의 Winsorized Mean(5th/95th percentile)으로, 합산이 아닌 평균 응답 크기입니다. Substrate는 Magnitude Tier(Strong >5.0, Moderate 2-5, Weak ≤2.0)별로 분류되어 Absolute Correlation K-Means로 클러스터링됩니다. Exclusive substrate는 해당 kinase에만 매핑된 것이고, Shared는 2개 이상 kinase에 매핑된 것입니다. 같은 CW Group에 속한 kinase들은 substrate의 phosphorylation 패턴이 시간적으로 상관관계(r≥0.7)를 보이므로, 이들은 같은 signaling cascade에 속하거나 공통 upstream signal에 반응하는 것으로 해석하세요.
12. {language_instruction}

{context}
"""


@router.post("/{order_id}/chat")
async def chat_with_analysis(
    order_id: int,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Stream AI chat responses based on order analysis context."""
    # Save user message to DB
    user_msg = ChatMessageDB(
        order_id=order_id,
        user_id=user.id,
        role="user",
        content=body.message,
        metadata_json={
            "view_context": body.view_context,
            "rag_collection_ids": body.rag_collection_ids,
            "response_language": body.response_language,
        } if body.view_context else None,
    )
    db.add(user_msg)
    await db.commit()

    # Load order
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Resolve RAG collection names from IDs
    rag_collection_names: List[str] = []
    if body.rag_collection_ids:
        coll_result = await db.execute(
            select(RagCollection).where(RagCollection.id.in_(body.rag_collection_ids))
        )
        collections = coll_result.scalars().all()
        rag_collection_names = [c.chromadb_name for c in collections]

    # Also include order-level RAG collections if any
    order_rag = (order.report_options or {}).get("rag_collections", [])
    if order_rag:
        # These might be IDs — resolve them
        if order_rag and isinstance(order_rag[0], int):
            coll_result2 = await db.execute(
                select(RagCollection).where(RagCollection.id.in_(order_rag))
            )
            order_colls = coll_result2.scalars().all()
            rag_collection_names.extend(c.chromadb_name for c in order_colls)
        elif isinstance(order_rag[0], str):
            rag_collection_names.extend(order_rag)

    # Deduplicate
    rag_collection_names = list(dict.fromkeys(rag_collection_names))

    # Assemble context
    context = await _assemble_context(
        order, settings, body.view_context, rag_collection_names, body.message
    )

    # Log context sections for debugging
    context_sections = [line for line in context.split("\n") if line.startswith("[")]
    logger.info(f"Chat context sections for order {order_id}: {context_sections}")
    logger.info(f"Chat context total length: {len(context)} chars")

    # Build messages for Ollama
    # Determine language instruction
    lang = body.response_language
    if lang == "ko":
        language_instruction = """한국어로 답변하되, 과학/생물학 전문 용어는 절대로 한글 음역하지 말고 영어 원문 그대로 쓰세요.

절대 금지 (이런 식으로 쓰면 안 됨):
- kinase → '킨아영', '킨기', '키나제', '키나아제' (전부 금지)
- substrate → '서브스트레이트' (금지)
- receptor → '리셉터' (금지)
- phosphorylation → '포스포릴레이션' (금지)
- module → '모듈' 은 허용

올바른 사용법:
- "Kinase Module Analysis 결과를 보면..." (영어 용어 그대로)
- "이 receptor에 연결된 kinase는..." (영어 용어 그대로)
- "phosphorylation 수준이 증가했어요" (영어 용어 그대로)
- "upstream regulator로 MAPK1이 확인돼요" (영어 용어 그대로)

영어 그대로 써야 하는 용어 목록:
kinase, substrate, receptor, phosphorylation, ubiquitination, upstream regulator,
downstream target, effector, signal flow, fold-change, pathway, crosstalk,
co-movement, evidence scoring, PTM-Vector, enrichment, de novo, regulated,
time-series, cluster, annotation, inference

단백질명(MAPK1, CDK5), 유전자명, PTM 위치(S473)도 반드시 영어 그대로.
문장 구조와 일반 설명만 한국어로 작성하세요."""
    elif lang == "en":
        language_instruction = "You MUST respond entirely in English. All explanations, headings, and conclusions must be in English. Do not use Korean."
    else:
        language_instruction = "Respond in the same language as the user's question (Korean or English)."

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context, language_instruction=language_instruction)
    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history (keep recent turns)
    max_history = 10
    for msg in body.conversation_history[-max_history:]:
        messages.append({"role": msg.role, "content": msg.content})

    # Add current user message
    messages.append({"role": "user", "content": body.message})

    ollama_url = settings.OLLAMA_URL

    # We'll collect the full assistant response to save to DB after streaming
    _full_response_parts: list[str] = []

    async def _save_assistant_response():
        """Save the complete assistant response to DB."""
        full_text = "".join(_full_response_parts).strip()
        if full_text:
            try:
                async with AsyncSessionLocal() as save_db:
                    assistant_msg = ChatMessageDB(
                        order_id=order_id,
                        user_id=user.id,
                        role="assistant",
                        content=full_text,
                    )
                    save_db.add(assistant_msg)
                    await save_db.commit()
            except Exception as e:
                logger.warning(f"Failed to save assistant message: {e}")

    async def _stream_response():
        import re as _re
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, read=300.0)
            ) as client:
                # ── Track <thought> filtering state ──
                # exaone-deep outputs <thought>...</thought> before the real answer.
                # We buffer everything until </thought> is seen, then discard it.
                _in_thought = False
                _thought_buffer = ""
                _thought_done = False  # True once </thought> has been fully consumed

                async with client.stream(
                    "POST",
                    f"{ollama_url}/api/chat",
                    json={
                        "model": CHAT_MODEL,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": 0.7,
                            "num_predict": 4096,
                            "num_ctx": 32768,
                        },
                    },
                ) as resp:
                    if resp.status_code != 200:
                        error_text = ""
                        async for chunk in resp.aiter_text():
                            error_text += chunk
                        yield f"data: {json.dumps({'error': f'Ollama error ({resp.status_code}): {error_text[:200]}'})}\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            done = data.get("done", False)

                            if content and not _thought_done:
                                # Still looking for / inside <thought> block
                                _thought_buffer += content
                                if not _in_thought and "<thought>" in _thought_buffer:
                                    _in_thought = True
                                if _in_thought and "</thought>" in _thought_buffer:
                                    # Discard everything up to and including </thought>
                                    idx = _thought_buffer.index("</thought>") + len("</thought>")
                                    remainder = _thought_buffer[idx:].lstrip("\n")
                                    _thought_done = True
                                    _thought_buffer = ""
                                    if remainder:
                                        _full_response_parts.append(remainder)
                                        yield f"data: {json.dumps({'content': remainder, 'done': False})}\n\n"
                                elif not _in_thought:
                                    # No <thought> tag at all — model didn't use thinking
                                    # Check if we've accumulated enough to be sure
                                    if len(_thought_buffer) > 20:
                                        _thought_done = True
                                        _full_response_parts.append(_thought_buffer)
                                        yield f"data: {json.dumps({'content': _thought_buffer, 'done': False})}\n\n"
                                        _thought_buffer = ""
                            elif content and _thought_done:
                                # Normal content after thought block — pass through
                                _full_response_parts.append(content)
                                yield f"data: {json.dumps({'content': content, 'done': False})}\n\n"

                            if done:
                                # Save assistant response to DB
                                await _save_assistant_response()
                                # Include token stats
                                eval_count = data.get("eval_count", 0)
                                eval_duration = data.get("eval_duration", 0)
                                tokens_per_sec = (
                                    round(eval_count / (eval_duration / 1e9), 1)
                                    if eval_duration > 0
                                    else 0
                                )
                                yield f"data: {json.dumps({'content': '', 'done': True, 'stats': {'tokens': eval_count, 'tokens_per_sec': tokens_per_sec}})}\n\n"
                                return

                        except json.JSONDecodeError:
                            continue

        except httpx.ConnectError:
            yield f"data: {json.dumps({'error': f'Cannot connect to Ollama at {ollama_url}. Is the service running?'})}\n\n"
        except httpx.ReadTimeout:
            yield f"data: {json.dumps({'error': 'Ollama response timed out (300s). Try a shorter question.'})}\n\n"
        except Exception as e:
            logger.error(f"Chat streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': f'Unexpected error: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(
        _stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Chat Context Info Endpoint (for frontend to show available context) ──────


@router.get("/{order_id}/chat-context-info")
async def get_chat_context_info(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Return metadata about available chat context for this order."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    output_dir = Path(settings.OUTPUT_DIR) / (order.order_code or str(order.id))
    file_suffix = "_phospho" if (order.ptm_type or "phosphorylation") == "phosphorylation" else "_ubi"

    # Check DB data availability
    has_kinase_db = bool(order.kinase_analysis_data and order.kinase_analysis_data.get("kinase_modules"))
    has_signal_flow = bool(order.receptor_inference_data and order.receptor_inference_data.get("receptors"))
    has_signal_prop = bool(order.signal_propagation_data)
    has_heatmap = bool(order.kinase_activity_heatmap and order.kinase_activity_heatmap.get("kinase_scores"))

    available = {
        "report": (output_dir / f"comprehensive_report{file_suffix}.md").exists()
                  or (output_dir / "final_report.md").exists(),
        "enriched_ptms": (output_dir / f"enriched_ptm_data{file_suffix}.json").exists(),
        "kinase_modules": has_kinase_db or (output_dir / f"global_kinase_modules{file_suffix}.json").exists(),
        "kinase_activity_heatmap": has_heatmap,
        "signal_flow": has_signal_flow,
        "signal_propagation": has_signal_prop,
        "comovement": (output_dir / f"temporal_comovement{file_suffix}.json").exists(),
        "methodology": True,  # Always available (fixed text)
    }

    # Count enriched PTMs
    enriched_count = 0
    enriched_path = output_dir / f"enriched_ptm_data{file_suffix}.json"
    if enriched_path.exists():
        try:
            with open(enriched_path, "r", encoding="utf-8") as f:
                enriched_count = len(json.load(f))
        except Exception:
            pass

    # Get available RAG collections
    coll_result = await db.execute(
        select(RagCollection).where(RagCollection.is_active == True).order_by(RagCollection.name)
    )
    collections = coll_result.scalars().all()

    return {
        "model": CHAT_MODEL,
        "available_context": available,
        "enriched_ptm_count": enriched_count,
        "rag_collections": [
            {"id": c.id, "name": c.name, "tier": c.tier, "document_count": c.document_count}
            for c in collections
            if c.chromadb_name not in {
                "neuroscience", "cancer_biology", "immunology", "stem_cell",
                "cardiovascular", "metabolism", "liver_biology",
                "phosphorylation", "acetylation", "ubiquitylation", "methylation",
                "mapk_signaling", "pi3k_akt", "wnt_signaling", "tgfb_signaling",
                "nfkb_signaling", "calcium_signaling", "cell_cycle", "apoptosis",
                "textbooks", "reviews", "pathway_databases", "ptm_databases",
            }
        ],
    }


# ── Chat History Endpoints ────────────────────────────────────────────────────


@router.get("/{order_id}/chat-history")
async def get_chat_history(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Load persisted chat history for this order (current user only)."""
    result = await db.execute(
        select(ChatMessageDB)
        .where(ChatMessageDB.order_id == order_id, ChatMessageDB.user_id == user.id)
        .order_by(ChatMessageDB.created_at.asc())
    )
    messages = result.scalars().all()
    return {
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    }


@router.delete("/{order_id}/chat-history")
async def clear_chat_history(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Clear all chat history for this order (current user only)."""
    from sqlalchemy import delete

    await db.execute(
        delete(ChatMessageDB).where(
            ChatMessageDB.order_id == order_id,
            ChatMessageDB.user_id == user.id,
        )
    )
    await db.commit()
    return {"status": "ok", "message": "Chat history cleared"}


# ── Chat Insight Extractor — chatbot → report feedback ────────────────────

_INSIGHT_SYSTEM_PROMPT = """\
You are analyzing a conversation between a researcher and POTATO AI
(a PTM analysis assistant). Extract actionable insights that should be
incorporated into the analysis report.

## EXTRACTION RULES

1. **New hypotheses**: If the conversation generated a new hypothesis
   not in the current report, extract it with supporting evidence

2. **Data corrections**: If the researcher pointed out errors in the
   analysis or provided additional context, flag these

3. **Interpretation refinements**: If the conversation led to a more
   nuanced interpretation of the data, capture the refined view

4. **Literature connections**: If new papers or biological mechanisms
   were discussed, note them for citation

5. **Experimental suggestions**: If follow-up experiments were discussed,
   include them in the Discussion section

## OUTPUT FORMAT
Return ONLY a valid JSON object (no markdown fences):
{
  "insights": [
    {
      "type": "hypothesis | correction | interpretation | literature | experiment",
      "content": "The conversation revealed that...",
      "target_section": "Results | Discussion | Conclusion",
      "priority": "must_include | nice_to_have",
      "source_messages": [3, 5, 7]
    }
  ],
  "revised_conclusions": "If the conversation changed the overall conclusion, state it here or null",
  "additional_questions": ["New research questions that emerged from the conversation"]
}
"""

_INSIGHT_USER_TEMPLATE = """\
## Conversation History
{conversation}

## Current Report Sections (summary)
{report_summary}

## Research Questions
{research_questions}

## Task
Extract insights from the conversation that should be reflected in the
report. Focus on new understanding, corrections, and refinements that
emerged through the dialogue.
"""


class ApplyToReportRequest(BaseModel):
    """Request body for chat-to-report feedback."""
    pass


@router.post("/{order_id}/chat/apply-to-report")
async def apply_chat_to_report(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Extract insights from chat conversation and trigger report re-generation."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Load chat history
    msg_result = await db.execute(
        select(ChatMessageDB)
        .where(
            ChatMessageDB.order_id == order_id,
            ChatMessageDB.user_id == user.id,
        )
        .order_by(ChatMessageDB.created_at.asc())
    )
    messages = msg_result.scalars().all()
    if not messages:
        raise HTTPException(status_code=400, detail="No chat history to extract insights from")

    conversation_lines = []
    for i, m in enumerate(messages):
        role = "Researcher" if m.role == "user" else "POTATO AI"
        conversation_lines.append(f"[{i+1}] {role}: {m.content}")
    conversation_text = "\n\n".join(conversation_lines)

    # Load report summary
    output_dir = Path(settings.OUTPUT_DIR) / (order.order_code or str(order.id))
    file_suffix = "_phospho" if (order.ptm_type or "phosphorylation") == "phosphorylation" else "_ubi"
    report_summary = _load_report_summary(output_dir, file_suffix)

    rqs = (order.report_options or {}).get("research_questions", [])

    user_prompt = _INSIGHT_USER_TEMPLATE.format(
        conversation=conversation_text[:12000],
        report_summary=report_summary[:6000] if report_summary else "(No report available)",
        research_questions="\n".join(f"- {q}" for q in rqs) if rqs else "(None)",
    )

    # Call LLM for insight extraction
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": CHAT_MODEL,
                    "messages": [
                        {"role": "system", "content": _INSIGHT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 4096},
                },
            )
            resp.raise_for_status()
            raw_content = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"[chat-insight] LLM call failed: {e}")
        raise HTTPException(status_code=502, detail=f"LLM insight extraction failed: {e}")

    # Parse JSON from LLM response
    parsed = None
    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    if not parsed:
        raise HTTPException(
            status_code=422,
            detail="Failed to parse insights from conversation. Please try again.",
        )

    insights = parsed.get("insights", [])
    if not insights:
        return {
            "status": "no_insights",
            "message": "No actionable insights found in the conversation.",
            "extracted": parsed,
        }

    # Store insights in report_options for the next report generation run
    report_options = dict(order.report_options or {})
    report_options["chat_insights"] = insights
    if parsed.get("additional_questions"):
        existing_rqs = report_options.get("research_questions", [])
        for q in parsed["additional_questions"]:
            if q not in existing_rqs:
                existing_rqs.append(q)
        report_options["research_questions"] = existing_rqs

    order.report_options = report_options
    await db.commit()

    must_count = sum(1 for i in insights if i.get("priority") == "must_include")
    nice_count = len(insights) - must_count

    return {
        "status": "ok",
        "message": f"Extracted {len(insights)} insights ({must_count} must-include, {nice_count} nice-to-have). "
                   "Re-run Report Generation to apply them.",
        "extracted": {
            "insights": insights,
            "revised_conclusions": parsed.get("revised_conclusions"),
            "additional_questions": parsed.get("additional_questions", []),
        },
    }
