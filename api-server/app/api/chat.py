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
10. 반드시 아래 제공된 [SIGNAL FLOW], [KINASE MODULE ANALYSIS], [ENRICHED PTM DATA] 섹션의 실제 데이터를 참조하여 답변하세요. 데이터에 있는 정보를 "없다"고 말하지 마세요.
11. {language_instruction}

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
        language_instruction = """절대적으로 한국어로만 답변하세요. 영어 단어를 사용하지 마세요.
단, 단백질명(MAPK1 등), PTM 위치(S473 등), 유전자명 같은 과학 고유명사는 예외입니다.
제목, 설명, 결론 모두 한국어로 작성하세요. 영어 문장을 사용하면 안 됩니다."""
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

    available = {
        "report": (output_dir / f"comprehensive_report{file_suffix}.md").exists()
                  or (output_dir / "final_report.md").exists(),
        "enriched_ptms": (output_dir / f"enriched_ptm_data{file_suffix}.json").exists(),
        "kinase_modules": has_kinase_db or (output_dir / f"global_kinase_modules{file_suffix}.json").exists(),
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
