"""
PTM Analysis AI Chat — Context-aware conversational assistant.

Provides an SSE-streaming chat endpoint that assembles rich context from:
  1. Generated report (comprehensive_report_*.md)
  2. Enriched PTM data (enriched_ptm_data_*.json)
  3. Kinase module analysis results (global_kinase_modules_*.json)
  4. Signal flow / evidence scoring data
  5. Temporal co-movement clusters
  6. ChromaDB RAG collections (user-selected)
  7. Pipeline methodology documentation (fixed)
  8. Current view state (checked PTMs, active tab, etc.)

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
from app.core.database import get_db
from app.dependencies import get_current_user
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


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessage] = []
    view_context: Optional[Dict[str, Any]] = None
    rag_collection_ids: Optional[List[int]] = None
    response_language: str = "auto"  # "ko", "en", or "auto" (match user's language)


# ── Context Assembly ─────────────────────────────────────────────────────────


def _load_report_summary(output_dir: Path, file_suffix: str) -> str:
    """Load report MD and truncate to fit context budget."""
    report_path = output_dir / f"comprehensive_report{file_suffix}.md"
    if not report_path.exists():
        # Try LangGraph report
        for name in ("final_report.md", "report.md"):
            alt = output_dir / name
            if alt.exists():
                report_path = alt
                break
    if not report_path.exists():
        return ""
    try:
        text = report_path.read_text(encoding="utf-8")
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
        # Summarize top PTMs with key info
        for ptm in data[:30]:  # Top 30 for context
            gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
            pos = ptm.get("position") or ptm.get("PTM_Position", "?")
            rag = ptm.get("rag_enrichment", {})
            if isinstance(rag, dict):
                reg = rag.get("regulation", {})
                if isinstance(reg, dict):
                    upstream = reg.get("upstream_regulators", [])
                    downstream = reg.get("downstream_targets", [])
                    function = reg.get("function_summary", "")
                    lines.append(
                        f"- {gene} {pos}: upstream={upstream[:3]}, "
                        f"downstream={downstream[:3]}, function={function[:100]}"
                    )
                else:
                    lines.append(f"- {gene} {pos}")
            else:
                lines.append(f"- {gene} {pos}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to load enriched PTM data: {e}")
        return ""


def _load_kinase_modules(output_dir: Path, file_suffix: str) -> str:
    """Load kinase module analysis results."""
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

    # 5. Kinase module results
    kinase = _load_kinase_modules(output_dir, file_suffix)
    if kinase:
        sections.append("[KINASE MODULE ANALYSIS]\n" + kinase)

    # 6. Co-movement clusters
    comovement = _load_comovement_clusters(output_dir, file_suffix)
    if comovement:
        sections.append("[TEMPORAL CO-MOVEMENT CLUSTERS]\n" + comovement)

    # 7. Pipeline methodology
    sections.append("[PIPELINE METHODOLOGY]\n" + METHODOLOGY_CONTEXT.strip())

    # 8. RAG collection context (dynamic, based on user question)
    if rag_collection_names:
        chromadb_url = settings.CHROMADB_URL
        rag_text = await _query_chromadb_collections(
            rag_collection_names, user_message, n_results=5, chromadb_url=chromadb_url
        )
        if rag_text:
            sections.append("[RELEVANT LITERATURE FROM RAG COLLECTIONS]\n" + rag_text)

    return "\n\n".join(sections)


# ── SSE Streaming Endpoint ───────────────────────────────────────────────────


SYSTEM_PROMPT_TEMPLATE = """You are a PTM (Post-Translational Modification) analysis expert assistant embedded in the PTM-Vector analysis platform.
You help researchers interpret their proteomics/PTM analysis results by answering questions based on the analysis data provided below.

IMPORTANT RULES:
1. Answer based on the provided analysis data and context. When data supports your answer, cite specific values (fold-changes, p-values, scores).
2. When discussing confidence or reliability, reference the Evidence Scoring system (0-5 scale) and explain what each score means.
3. When explaining methodology, reference the Pipeline Methodology section.
4. For literature-based answers, cite the RAG collection sources when available.
5. Be honest about limitations — if data is insufficient to answer, say so clearly.
6. {language_instruction}
7. Keep answers focused and concise but thorough. Use markdown formatting for readability.
8. When the user asks about specific PTMs, proteins, or kinases, look them up in the provided data sections.

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

    # Build messages for Ollama
    # Determine language instruction
    lang = body.response_language
    if lang == "ko":
        language_instruction = "You MUST respond entirely in Korean (한국어). All explanations, headings, and conclusions must be in Korean."
    elif lang == "en":
        language_instruction = "You MUST respond entirely in English. All explanations, headings, and conclusions must be in English."
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

    async def _stream_response():
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, read=300.0)
            ) as client:
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

                            if content:
                                yield f"data: {json.dumps({'content': content, 'done': False})}\n\n"

                            if done:
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

    available = {
        "report": (output_dir / f"comprehensive_report{file_suffix}.md").exists()
                  or (output_dir / "final_report.md").exists(),
        "enriched_ptms": (output_dir / f"enriched_ptm_data{file_suffix}.json").exists(),
        "kinase_modules": (output_dir / f"global_kinase_modules{file_suffix}.json").exists(),
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
