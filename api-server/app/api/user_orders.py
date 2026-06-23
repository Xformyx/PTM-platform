"""
User-facing Order API endpoints for the simplified User UI.
Provides:
  - POST /infer-config        — AI-based config inference from uploaded files
  - POST /correct-config      — Natural language correction of inferred config
  - POST /create-from-user    — Simplified order creation from User UI
  - POST /{order_id}/chat/stream   — SSE streaming chat for Mekii AI
  - GET  /{order_id}/chat/history  — Retrieve chat history
  - DELETE /{order_id}/chat/history — Clear chat history
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import AsyncSessionLocal, get_db
from app.dependencies import get_current_user
from app.models.chat_message import ChatMessage as ChatMessageDB
from app.models.order import Order, OrderLog
from app.models.rag_collection import RagCollection
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["user-orders"])
logger = logging.getLogger("ptm-platform.user-orders")

# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class InferredConfig(BaseModel):
    project_name: str
    ptm_type: str  # "phosphorylation" | "ubiquitylation"
    organism: str  # "mouse" | "human" | "rat"
    conditions: List[str]
    contrasts: List[dict]  # [{treatment, control}]
    sample_mapping: List[dict]  # [{filename, shortname, condition, replicate}]
    detected_modifications: List[str]
    confidence: str  # "high" | "medium" | "low"
    reasoning: str


class CorrectConfigRequest(BaseModel):
    current_config: dict
    correction: str


class UserChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None  # {active_tab, order_status, ptm_type, species}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/orders/infer-config
# ─────────────────────────────────────────────────────────────────────────────

INFER_SYSTEM_PROMPT = """You are Mekii, an expert bioinformatics assistant specializing in PTM (Post-Translational Modification) proteomics analysis.

Given uploaded file names, file types, and a user description of their experiment, infer the analysis configuration.

You MUST respond with ONLY a valid JSON object (no markdown, no explanation outside the JSON) with these fields:
{
  "project_name": "short descriptive name for the analysis",
  "ptm_type": "phosphorylation" or "ubiquitylation",
  "organism": "mouse" or "human" or "rat",
  "conditions": ["condition1", "condition2", ...],
  "contrasts": [{"treatment": "condition1", "control": "condition2"}, ...],
  "sample_mapping": [
    {"filename": "file1.mzML", "shortname": "C1_R1", "condition": "condition1", "replicate": 1},
    ...
  ],
  "detected_modifications": ["Phospho (STY)", ...],
  "confidence": "high" or "medium" or "low",
  "reasoning": "Brief explanation of how you inferred this configuration"
}

Rules:
- Infer PTM type from file names, description, or modifications detected
- Infer organism from FASTA file name or description
- Infer conditions and replicates from file naming patterns
- If TSV search result files are provided (pr_matrix, pg_matrix), note them as pre-processed data
- If description mentions specific treatments, time points, or cell types, use them for conditions
- Be conservative: if uncertain, set confidence to "low"
"""


@router.post("/infer-config")
async def infer_config(
    files: List[UploadFile] = File(...),
    file_types: List[str] = Form(...),
    description: str = Form(""),
    research_questions: Optional[str] = Form(None),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Use LLM to infer analysis configuration from uploaded files and description."""
    # Build context for LLM
    file_info = []
    for f, ft in zip(files, file_types):
        file_info.append({"filename": f.filename, "type": ft, "size_mb": round(f.size / 1024 / 1024, 2) if f.size else 0})

    # Parse research questions
    questions = []
    if research_questions:
        try:
            questions = json.loads(research_questions)
        except json.JSONDecodeError:
            questions = [research_questions]

    user_prompt = f"""## Uploaded Files
{json.dumps(file_info, indent=2)}

## Experiment Description
{description}

## Research Questions
{json.dumps(questions, indent=2) if questions else "None provided"}

Based on the above information, infer the analysis configuration. Respond with ONLY a JSON object."""

    # Call Ollama for inference
    ollama_url = settings.OLLAMA_URL
    model = settings.DEFAULT_LLM_MODEL

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": INFER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 2048},
                },
            )
            if response.status_code != 200:
                logger.error(f"Ollama returned {response.status_code}: {response.text}")
                raise HTTPException(status_code=502, detail="LLM service unavailable")

            result = response.json()
            content = result.get("message", {}).get("content", "")

            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if json_match:
                content = json_match.group(1)
            else:
                # Try to find raw JSON object
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    content = json_match.group(0)

            config = json.loads(content)

            # Validate required fields
            required_fields = ["project_name", "ptm_type", "organism", "conditions", "contrasts", "sample_mapping"]
            for field in required_fields:
                if field not in config:
                    config[field] = [] if field in ("conditions", "contrasts", "sample_mapping") else "unknown"

            # Ensure defaults
            if config.get("ptm_type") not in ("phosphorylation", "ubiquitylation"):
                config["ptm_type"] = "phosphorylation"
            if config.get("organism") not in ("mouse", "human", "rat"):
                config["organism"] = "mouse"
            if "detected_modifications" not in config:
                config["detected_modifications"] = []
            if "confidence" not in config:
                config["confidence"] = "medium"
            if "reasoning" not in config:
                config["reasoning"] = "Inferred from file names and description"

            return config

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}\nContent: {content}")
        raise HTTPException(status_code=422, detail="AI response was not valid JSON. Please try again.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM inference timed out. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("infer-config failed")
        raise HTTPException(status_code=500, detail=f"Failed to infer configuration: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/orders/correct-config
# ─────────────────────────────────────────────────────────────────────────────

CORRECT_SYSTEM_PROMPT = """You are Mekii, an expert bioinformatics assistant.

The user has an inferred analysis configuration and wants to correct it using natural language.
Apply the user's correction to the current config and return the UPDATED config as a JSON object.

Rules:
- Only modify fields that the user's correction refers to
- Keep all other fields unchanged
- Respond with ONLY the complete updated JSON object (no markdown, no explanation)
- The JSON must have the same structure as the input config
"""


@router.post("/correct-config")
async def correct_config(
    body: CorrectConfigRequest,
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Use LLM to apply natural language corrections to inferred config."""
    ollama_url = settings.OLLAMA_URL
    model = settings.DEFAULT_LLM_MODEL

    user_prompt = f"""## Current Configuration
{json.dumps(body.current_config, indent=2)}

## User Correction
{body.correction}

Apply the correction and return the UPDATED configuration as a JSON object."""

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": CORRECT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 2048},
                },
            )
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="LLM service unavailable")

            result = response.json()
            content = result.get("message", {}).get("content", "")

            # Extract JSON
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if json_match:
                content = json_match.group(1)
            else:
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    content = json_match.group(0)

            updated_config = json.loads(content)
            return updated_config

    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="AI response was not valid JSON. Please try again.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM correction timed out. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("correct-config failed")
        raise HTTPException(status_code=500, detail=f"Correction failed: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/orders/create-from-user
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/create-from-user", status_code=201)
async def create_order_from_user(
    files: List[UploadFile] = File(...),
    file_types: List[str] = Form(...),
    config: str = Form(...),
    description: str = Form(""),
    research_questions: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """
    Simplified order creation from User UI.
    Accepts the AI-inferred (and possibly corrected) config + uploaded files.
    Creates an Order in the DB and saves files to the input directory.
    """
    try:
        config_data = json.loads(config)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid config JSON")

    project_name = config_data.get("project_name", "").strip()
    if not project_name:
        project_name = f"user_analysis_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # Sanitize project name for use as order_code
    order_code = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_name)[:64]

    # Check uniqueness
    existing = await db.execute(select(Order).where(Order.order_code == order_code))
    if existing.scalar_one_or_none():
        # Append timestamp to make unique
        order_code = f"{order_code[:50]}_{datetime.now(timezone.utc).strftime('%H%M%S')}"

    # Create input directory
    input_dir = Path(settings.INPUT_DIR) / order_code
    input_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded files
    pr_path = None
    pg_path = None
    fasta_path = None
    reference_pdfs = []

    for f, ft in zip(files, file_types):
        file_path = input_dir / f.filename
        content = await f.read()
        file_path.write_bytes(content)

        if ft == "raw_data":
            # mzML files — stored in input dir
            pass
        elif ft == "fasta":
            fasta_path = str(file_path)
        elif ft == "search_result":
            # TSV files — detect pr vs pg
            fname_lower = f.filename.lower()
            if "pr" in fname_lower or "precursor" in fname_lower:
                pr_path = str(file_path)
            elif "pg" in fname_lower or "protein" in fname_lower:
                pg_path = str(file_path)
            else:
                # Default: first one is pr, second is pg
                if pr_path is None:
                    pr_path = str(file_path)
                else:
                    pg_path = str(file_path)
        elif ft == "reference_paper":
            reference_pdfs.append(str(file_path))

    # Resolve FASTA from reference dir if not uploaded
    if not fasta_path:
        organism = config_data.get("organism", "mouse")
        species_dir = Path(settings.REFERENCE_DIR) / organism.lower()
        if species_dir.is_dir():
            for fa in species_dir.glob("*.fasta"):
                fasta_path = str(fa)
                break
            if not fasta_path:
                for fa in species_dir.glob("*.fa"):
                    fasta_path = str(fa)
                    break

    if not fasta_path:
        raise HTTPException(status_code=400, detail="No FASTA file provided or found in reference directory")

    # If no pr/pg matrix provided, they'll be generated by PTMQuant from mzML
    if not pr_path:
        pr_path = str(input_dir / "pending_preprocessing.tsv")
        Path(pr_path).touch()
    if not pg_path:
        pg_path = str(input_dir / "pending_preprocessing_pg.tsv")
        Path(pg_path).touch()

    # Build sample_config from inferred config
    sample_mapping = config_data.get("sample_mapping", [])
    sample_config = {
        "source": "user_ui",
        "samples": [
            {
                "file_name": s.get("filename", ""),
                "condition": s.get("condition", ""),
                "group": s.get("condition", ""),
                "replicate": s.get("replicate", 1),
            }
            for s in sample_mapping
        ],
    }

    # Build report_options
    questions = []
    if research_questions:
        try:
            questions = json.loads(research_questions)
        except json.JSONDecodeError:
            questions = [research_questions]

    report_options = {
        "report_type": "comprehensive",
        "analysis_mode": "ptm_only",
        "top_n_ptms": 50,
        "ptm_selection_mode": "top_n",
        "research_questions": questions,
        "llm_provider": "ollama",
        "llm_model": settings.DEFAULT_LLM_MODEL,
    }

    # Build analysis_context
    analysis_context = {
        "description": description,
        "conditions": config_data.get("conditions", []),
        "contrasts": config_data.get("contrasts", []),
        "detected_modifications": config_data.get("detected_modifications", []),
        "reference_pdfs": reference_pdfs,
        "source": "user_ui",
    }

    ptm_type = config_data.get("ptm_type", "phosphorylation")
    species = config_data.get("organism", "mouse")

    # Create Order
    order = Order(
        order_code=order_code,
        user_id=user.id if getattr(user, "id", 0) != 0 else None,
        project_name=project_name,
        ptm_type=ptm_type,
        species=species,
        sample_config=sample_config,
        analysis_context=analysis_context,
        analysis_options=None,
        report_options=report_options,
        pr_matrix_path=pr_path,
        pg_matrix_path=pg_path,
        fasta_path=fasta_path,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    logger.info(f"User order created: {order_code} (id={order.id}) by user {getattr(user, 'email', 'internal')}")

    return {
        "order_id": order.id,
        "order_code": order.order_code,
        "status": order.status,
        "message": "Analysis created successfully",
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/orders/{order_id}/chat/stream  (User UI Mekii Chat)
# ─────────────────────────────────────────────────────────────────────────────

MEKII_SYSTEM_PROMPT = """You are Mekii, a friendly and knowledgeable AI assistant specialized in PTM (Post-Translational Modification) proteomics analysis.

You help researchers understand their PTM analysis results, answer questions about proteomics methodology, and provide biological interpretations.

Guidelines:
- Be concise but informative
- Use scientific terminology accurately
- When discussing specific proteins or PTMs, always use English nomenclature (e.g., MAPK1, phosphorylation at S473)
- If the user writes in Korean, respond in Korean but keep all scientific terms in English
- Reference the analysis context (order status, PTM type, species) when relevant
- If you don't have enough information to answer, say so clearly

Context about the current analysis:
{context}
"""


@router.post("/{order_id}/chat/stream")
async def user_chat_stream(
    order_id: int,
    body: UserChatRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """SSE streaming chat endpoint for Mekii AI in User UI."""
    # Verify order exists and user has access
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Check access (owner or shared)
    if getattr(user, "id", 0) != 0 and order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Save user message to DB
    user_msg = ChatMessageDB(
        order_id=order_id,
        user_id=user.id if getattr(user, "id", 0) != 0 else 1,
        role="user",
        content=body.message,
        metadata_json=body.context,
    )
    db.add(user_msg)
    await db.commit()

    # Build context from order info
    context_parts = []
    if order.project_name:
        context_parts.append(f"Project: {order.project_name}")
    if order.ptm_type:
        context_parts.append(f"PTM Type: {order.ptm_type}")
    if order.species:
        context_parts.append(f"Species: {order.species}")
    if order.status:
        context_parts.append(f"Analysis Status: {order.status}")
    if body.context:
        if body.context.get("active_tab"):
            context_parts.append(f"User is viewing: {body.context['active_tab']}")

    # Try to load report summary if available
    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    report_snippet = ""
    if output_dir.exists():
        ptm_mode = "phospho" if order.ptm_type == "phosphorylation" else "ubi"
        report_files = list(output_dir.glob(f"comprehensive_report_{ptm_mode}.md"))
        if not report_files:
            report_files = list(output_dir.glob("comprehensive_report_*.md"))
        if report_files:
            try:
                full_report = report_files[0].read_text(encoding="utf-8", errors="replace")
                # Take first 3000 chars as context
                report_snippet = full_report[:3000]
                context_parts.append(f"\nReport Summary (first 3000 chars):\n{report_snippet}")
            except Exception:
                pass

    context_str = "\n".join(context_parts) if context_parts else "No analysis context available yet."
    system_prompt = MEKII_SYSTEM_PROMPT.format(context=context_str)

    # Load recent chat history
    from sqlalchemy import desc
    history_result = await db.execute(
        select(ChatMessageDB)
        .where(ChatMessageDB.order_id == order_id)
        .order_by(desc(ChatMessageDB.created_at))
        .limit(10)
    )
    history_msgs = list(reversed(history_result.scalars().all()))

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history_msgs[:-1]:  # Exclude the message we just saved
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": body.message})

    ollama_url = settings.OLLAMA_URL
    model = settings.DEFAULT_LLM_MODEL
    _full_response_parts: list[str] = []

    async def _save_assistant_response():
        """Save the complete assistant response to DB."""
        full_text = "".join(_full_response_parts).strip()
        if full_text:
            try:
                async with AsyncSessionLocal() as save_db:
                    assistant_msg = ChatMessageDB(
                        order_id=order_id,
                        user_id=user.id if getattr(user, "id", 0) != 0 else 1,
                        role="assistant",
                        content=full_text,
                    )
                    save_db.add(assistant_msg)
                    await save_db.commit()
            except Exception as e:
                logger.warning(f"Failed to save assistant message: {e}")

    async def _stream_response():
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, read=300.0)
            ) as client:
                async with client.stream(
                    "POST",
                    f"{ollama_url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": 0.7,
                            "num_predict": 2048,
                            "num_ctx": 8192,
                        },
                    },
                ) as resp:
                    if resp.status_code != 200:
                        yield f"data: {json.dumps({'error': 'LLM service unavailable'})}\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                _full_response_parts.append(token)
                                yield f"data: {json.dumps({'content': token})}\n\n"
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue

            yield "data: [DONE]\n\n"
        except httpx.TimeoutException:
            yield f"data: {json.dumps({'error': 'Response timed out'})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception(f"Chat stream error for order {order_id}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await _save_assistant_response()

    return StreamingResponse(
        _stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/orders/{order_id}/chat/history  (User UI)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{order_id}/chat/history")
async def get_user_chat_history(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Retrieve chat history for an order."""
    # Verify order exists
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if getattr(user, "id", 0) != 0 and order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    history_result = await db.execute(
        select(ChatMessageDB)
        .where(ChatMessageDB.order_id == order_id)
        .order_by(ChatMessageDB.created_at)
    )
    messages = history_result.scalars().all()

    return [
        {
            "role": msg.role,
            "content": msg.content,
            "timestamp": int(msg.created_at.timestamp() * 1000) if msg.created_at else 0,
        }
        for msg in messages
    ]


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/orders/{order_id}/chat/history  (User UI)
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{order_id}/chat/history")
async def clear_user_chat_history(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Clear chat history for an order."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if getattr(user, "id", 0) != 0 and order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await db.execute(
        ChatMessageDB.__table__.delete().where(ChatMessageDB.order_id == order_id)
    )
    await db.commit()

    return {"status": "ok", "message": "Chat history cleared"}
