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
import traceback
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
from app.dependencies import assert_not_viewer, get_current_user
from app.models.chat_message import ChatMessage as ChatMessageDB
from app.models.order import Order, OrderLog
from app.models.rag_collection import RagCollection
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["user-orders"])
logger = logging.getLogger("ptm-platform.user-orders")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# Metadata columns in DIA-NN output TSVs (not sample data)
METADATA_COLUMNS = frozenset([
    "Protein.Group", "Protein.Ids", "Protein.Names", "Genes",
    "First.Protein.Description", "Proteotypic", "Stripped.Sequence",
    "Modified.Sequence", "Precursor.Charge", "Precursor.Id",
])


def _safe_upload_filename(filename: str | None) -> str:
    """Strip directories and unsafe characters from an upload filename.

    Same rule as admin ``create_order`` ``save_upload`` in orders.py.
    A name like ``../../other_order/secret.tsv`` becomes ``secret.tsv``.
    """
    safe_name = re.sub(r"[^\w.\-]", "_", Path(filename or "file").name)
    if not safe_name or safe_name.startswith("."):
        safe_name = "upload_" + safe_name.lstrip(".")
    return safe_name


def _write_under_dir(target_dir: Path, filename: str | None, content: bytes) -> Path:
    """Write *content* under *target_dir* only. Raises 400 if the path escapes."""
    target_dir = target_dir.resolve()
    file_path = (target_dir / _safe_upload_filename(filename)).resolve()
    if not file_path.is_relative_to(target_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path.write_bytes(content)
    return file_path


def _read_tsv_sample_columns(tsv_path: str) -> list[str]:
    """Read the first line of a TSV file and extract sample columns.
    Sample columns are those NOT in METADATA_COLUMNS (typically ending with .mzML).
    This mirrors the Admin frontend's readTsvHeaders + extractSampleColumns logic.
    """
    try:
        with open(tsv_path, "r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        headers = header_line.split("\t")
        sample_cols = [h.strip() for h in headers if h.strip() and h.strip() not in METADATA_COLUMNS]
        return sample_cols
    except Exception as e:
        logger.warning(f"Failed to read TSV headers from {tsv_path}: {e}")
        return []


# Default regex pattern: handles multiple common TSV column name formats:
#   - With extension:  ..._Condition_3.mzML  → group(1)=Condition, group(2)=3
#   - Without extension: ..._Condition_3     → group(1)=Condition, group(2)=3
#   - With R prefix:  ..._Condition_R3       → group(1)=Condition, group(2)=3
#   - Simple:         Condition_R3           → group(1)=Condition, group(2)=3
DEFAULT_REGEX_PATTERN = r"(?:^|_)([^_]+?)_[Rr]?(\d+)(?:\.\w+)?$"
# Control keywords for auto-detection
CONTROL_KEYWORDS = {"control", "ctrl", "con", "wt", "wildtype", "untreated", "baseline", "sham", "vehicle"}


def _auto_parse_tsv_columns(sample_columns: list[str], contrasts: list[dict] = None) -> dict:
    """Auto-parse TSV sample columns into condition_map using regex.
    This is IDENTICAL to Admin frontend's autoParseColumns logic:
    1. Extract basename from each column
    2. Apply regex to get condition and replicate
    3. If condition matches control keyword → "Control"
    4. Otherwise use condition label as-is

    Returns {full_column_name: condition_label} dict.
    """
    condition_map = {}
    if not sample_columns:
        return condition_map

    # Determine control keyword from contrasts if available
    control_kw = "control"  # default
    if contrasts:
        for c in contrasts:
            ctrl = (c.get("control") or "").strip().lower()
            if ctrl:
                control_kw = ctrl
                break

    regex = re.compile(DEFAULT_REGEX_PATTERN)

    for col in sample_columns:
        basename = os.path.basename(col)
        match = regex.search(basename)
        if match:
            cond_label = match.group(1)
            # Check if this is a control sample
            if cond_label.lower() == control_kw.lower() or cond_label.lower() in CONTROL_KEYWORDS:
                condition_map[col] = "Control"
            else:
                condition_map[col] = cond_label
        else:
            # Fallback: check if column name contains control keywords
            col_lower = col.lower()
            if any(kw in col_lower for kw in CONTROL_KEYWORDS):
                condition_map[col] = "Control"
            else:
                condition_map[col] = "Unknown"

    logger.info(f"Auto-parsed condition_map from {len(sample_columns)} columns: {condition_map}")
    return condition_map


def _build_condition_map(sample_cfg: dict | list | None) -> dict:
    """Build {filename: condition_label} from sample_config."""
    condition_map = {}
    if not sample_cfg:
        return condition_map
    samples = []
    if isinstance(sample_cfg, dict):
        samples = sample_cfg.get("samples", [])
    elif isinstance(sample_cfg, list):
        samples = sample_cfg
    for entry in samples:
        fname = entry.get("file_name") or entry.get("File_Name", "")
        if not fname:
            continue
        group = (entry.get("group") or entry.get("Group", "")).strip()
        condition = (entry.get("condition") or entry.get("Condition", "")).strip()
        replicate = entry.get("replicate") or entry.get("Replicate")
        if group.lower() == "control":
            condition_map[fname] = "Control"
        elif condition:
            cond_group = condition
            if replicate is not None:
                suffix = f"_{replicate}"
                if cond_group.endswith(suffix):
                    cond_group = cond_group[: -len(suffix)]
            condition_map[fname] = cond_group if cond_group else condition
        elif group:
            condition_map[fname] = group
        else:
            condition_map[fname] = "Unknown"
    return condition_map


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
- Infer organism from the experiment description, or from a FASTA file name if one was uploaded
- FASTA upload is optional. If none is uploaded, the platform uses its registered reference FASTA for the inferred organism (mouse, human, or rat)
- Infer conditions and replicates from file naming patterns
- If TSV search result files are provided (pr_matrix, pg_matrix), note them as pre-processed data
- If description mentions specific treatments, time points, or cell types, use them for conditions
- Be conservative: if uncertain, set confidence to "low"
- CRITICAL: If "Actual Sample Columns from PR Matrix TSV" are provided, the sample_mapping MUST use those EXACT column names as the "filename" field. Do NOT invent or modify filenames.
- Each sample column (usually ending with .mzML) should appear exactly once in sample_mapping
- Infer condition/group from patterns in the column names (e.g., "Control_", "Treatment_", replicate numbers)
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
    assert_not_viewer(user)
    import tempfile

    # Build context for LLM
    file_info = []
    tsv_sample_columns = []  # Actual sample columns from PR matrix TSV

    for f, ft in zip(files, file_types):
        file_info.append({"filename": f.filename, "type": ft, "size_mb": round(f.size / 1024 / 1024, 2) if f.size else 0})

        # If this is a search_result (TSV), read its headers to get actual sample columns
        if ft == "search_result" and not tsv_sample_columns:
            fname_lower = (f.filename or "").lower()
            if "pr" in fname_lower or "precursor" in fname_lower or not tsv_sample_columns:
                # Save temporarily to read headers
                content_bytes = await f.read()
                await f.seek(0)  # Reset for later use
                # Do not join the client filename into the temp path.
                with tempfile.NamedTemporaryFile(delete=False, suffix=".tsv") as tmp:
                    tmp.write(content_bytes)
                    tmp_path = Path(tmp.name)
                try:
                    tsv_sample_columns = _read_tsv_sample_columns(str(tmp_path))
                finally:
                    tmp_path.unlink(missing_ok=True)
                logger.info(f"Read {len(tsv_sample_columns)} sample columns from {f.filename}")

    # Parse research questions
    questions = []
    if research_questions:
        try:
            questions = json.loads(research_questions)
        except json.JSONDecodeError:
            questions = [research_questions]

    # Build user prompt with actual TSV sample columns for accurate mapping
    tsv_columns_section = ""
    if tsv_sample_columns:
        tsv_columns_section = f"""\n## Actual Sample Columns from PR Matrix TSV
These are the REAL column names in the uploaded TSV file. Your sample_mapping MUST use these EXACT filenames:
{json.dumps(tsv_sample_columns, indent=2)}

IMPORTANT: Each entry in sample_mapping must have a 'filename' that EXACTLY matches one of the above column names."""

    user_prompt = f"""## Uploaded Files
{json.dumps(file_info, indent=2)}
{tsv_columns_section}

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
    assert_not_viewer(user)
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
    assert_not_viewer(user)
    try:
        return await _create_order_from_user_impl(
            files=files, file_types=file_types, config=config,
            description=description, research_questions=research_questions,
            db=db, settings=settings, user=user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"create_order_from_user unhandled error: {exc}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {type(exc).__name__}: {exc}",
        )


async def _create_order_from_user_impl(
    files: List[UploadFile],
    file_types: List[str],
    config: str,
    description: str,
    research_questions: Optional[str],
    db: AsyncSession,
    settings: Settings,
    user,
):
    """Internal implementation of create_order_from_user."""
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

    # Resolve the registered reference before writing any uploaded files. A
    # custom Rat_hir reference must not silently fall back to the standard rat
    # FASTA because the human INSR entry is part of the reference contract.
    organism = config_data.get("organism", "mouse")
    from ptm_shared.species_registry import resolve_species_context
    try:
        species_context = resolve_species_context(organism)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    uploaded_fasta = any(file_type == "fasta" for file_type in file_types)
    from ptm_shared.reference_fasta import missing_reference_detail, resolve_reference_fasta
    resolved_reference_fasta = None
    if not uploaded_fasta:
        resolved_reference_fasta = resolve_reference_fasta(settings.REFERENCE_DIR, species_context.label)
    if not uploaded_fasta and not resolved_reference_fasta:
        raise HTTPException(status_code=422, detail=missing_reference_detail(settings.REFERENCE_DIR, species_context))

    search_names = [f.filename or "" for f, ft in zip(files, file_types) if ft == "search_result"]
    if len(search_names) < 2:
        raise HTTPException(
            status_code=422,
            detail=(
                "PR matrix와 PG matrix가 필요합니다 "
                "(예: report.pr_matrix.tsv, report.pg_matrix.tsv). "
                "mzML만으로는 전처리를 시작할 수 없습니다. "
                "검색 결과 TSV를 함께 올려 주세요."
            ),
        )

    # Create input directory
    input_dir = Path(settings.INPUT_DIR) / order_code
    input_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded files
    pr_path = None
    pg_path = None
    fasta_path = resolved_reference_fasta
    reference_pdfs = []

    for f, ft in zip(files, file_types):
        original_name = f.filename or "file"
        content = await f.read()
        file_path = _write_under_dir(input_dir, original_name, content)

        if ft == "raw_data":
            # mzML files — stored in input dir
            pass
        elif ft == "fasta":
            fasta_path = str(file_path)
        elif ft == "search_result":
            # TSV files — detect pr vs pg (use original name so labels survive sanitization)
            fname_lower = original_name.lower()
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
        fasta_path = resolve_reference_fasta(settings.REFERENCE_DIR, species_context.label)

    if not fasta_path:
        raise HTTPException(status_code=400, detail="No FASTA file provided or found in reference directory")

    if not pr_path or not pg_path:
        raise HTTPException(
            status_code=422,
            detail=(
                "PR matrix와 PG matrix를 모두 인식하지 못했습니다. "
                "파일명에 pr/precursor와 pg/protein이 들어가거나, "
                "검색 결과 TSV를 두 개 올려 주세요."
            ),
        )

    # Build sample_config from ACTUAL TSV columns (same as Admin mode)
    # Read real sample columns from PR matrix and auto-parse with regex
    tsv_columns = _read_tsv_sample_columns(pr_path) if pr_path else []
    contrasts_for_parse = config_data.get("contrasts", [])

    if tsv_columns:
        # Deterministic auto-parse (identical to Admin frontend)
        regex = re.compile(DEFAULT_REGEX_PATTERN)
        control_kw = "control"
        if contrasts_for_parse:
            for c in contrasts_for_parse:
                ctrl = (c.get("control") or "").strip().lower()
                if ctrl:
                    control_kw = ctrl
                    break

        parsed_samples = []
        for col in tsv_columns:
            basename = os.path.basename(col)
            match = regex.search(basename)
            if match:
                cond_label = match.group(1)
                rep = int(match.group(2)) if match.group(2) else 1
                is_ctrl = cond_label.lower() == control_kw or cond_label.lower() in CONTROL_KEYWORDS
                parsed_samples.append({
                    "file_name": col,
                    "condition": f"{cond_label}_{rep}",
                    "group": "Control" if is_ctrl else "Treatment",
                    "replicate": rep,
                })
            else:
                parsed_samples.append({
                    "file_name": col,
                    "condition": basename,
                    "group": "Treatment",
                    "replicate": 1,
                })

        sample_config = {
            "source": "auto_parse",
            "regex_pattern": DEFAULT_REGEX_PATTERN,
            "single_time_point": False,
            "samples": parsed_samples,
        }
    else:
        # Fallback: use LLM-inferred sample_mapping
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
        "llm_model": "qwen3.5:27b",  # User mode: fixed model for report generation
        "rag_enrichment_llm_model": "qwen2.5:14b",  # User mode: lighter model for RAG enrichment
        "rag_enrichment_llm_provider": "ollama",
    }

    # Build analysis_context
    analysis_context = {
        "description": description,
        "conditions": config_data.get("conditions", []),
        "contrasts": config_data.get("contrasts", []),
        "detected_modifications": config_data.get("detected_modifications", []),
        "reference_pdfs": reference_pdfs,
        "organism": config_data.get("organism", "mouse"),
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

    # ── Auto-start pipeline (same logic as admin start_order) ──────────────
    order.status = "queued"
    order.current_stage = "preprocessing"
    order.progress_pct = 0
    order.started_at = datetime.now(timezone.utc)
    order.run_by_user_id = user.id if getattr(user, "id", 0) != 0 else None
    await db.commit()

    # Build condition_map from ACTUAL TSV headers (same as Admin mode)
    # Uses deterministic regex parsing - no LLM involved
    sample_columns = _read_tsv_sample_columns(pr_path) if pr_path else []
    contrasts = config_data.get("contrasts", [])

    if sample_columns:
        # Auto-parse TSV columns with regex (identical to Admin frontend logic)
        condition_map = _auto_parse_tsv_columns(sample_columns, contrasts)
        logger.info(f"Order {order_code}: condition_map from {len(sample_columns)} TSV columns: {condition_map}")
    else:
        # Fallback to sample_config-based mapping (mzML-only workflow)
        condition_map = _build_condition_map(sample_config)

    ptm_mode = "phospho" if ptm_type == "phosphorylation" else "ubi"
    # species_context was resolved during the preflight reference check above.

    # Gather ChromaDB collections for RAG retrieval (use all active)
    coll_result = await db.execute(
        select(RagCollection.chromadb_name).where(RagCollection.is_active == True)
    )
    active_collections = [r[0] for r in coll_result.fetchall()]
    logger.info(f"Order {order_code}: using {len(active_collections)} active RAG collections")

    # Build task_config identically to Admin mode (orders.py start_order)
    report_opts = order.report_options or {}
    sample_cfg = order.sample_config or {}
    task_config = {
        "order_code": order.order_code,
        "pr_matrix_path": order.pr_matrix_path,
        "pg_matrix_path": order.pg_matrix_path,
        "fasta_path": order.fasta_path,
        "config_xlsx_path": getattr(order, 'config_xlsx_path', None),
        "secondary_pr_matrix_path": getattr(order, 'secondary_pr_matrix_path', None),
        "secondary_pg_matrix_path": getattr(order, 'secondary_pg_matrix_path', None),
        "ptm_mode": ptm_mode,
        "condition_map": condition_map if condition_map else None,
        "single_time_point": sample_cfg.get("single_time_point", False),
        "species_tax_id": species_context.taxonomy_id,
        "kegg_organism": species_context.kegg_organism,
        "species": species_context.analysis_species,
        "species_label": species_context.label,
        "custom_reference": species_context.custom_reference,
        "analysis_options": order.analysis_options,
        "chromadb_collections": active_collections,
        "llm_provider": report_opts.get("llm_provider", "ollama"),
        "llm_model": report_opts.get("llm_model"),
        "rag_enrichment_llm_model": report_opts.get("rag_enrichment_llm_model"),
        "rag_enrichment_llm_provider": report_opts.get("rag_enrichment_llm_provider"),
        "rag_llm_model": report_opts.get("rag_llm_model"),
        "rag_llm_provider": report_opts.get("rag_llm_provider"),
        "report_title": report_opts.get("report_title", f"{project_name} - PTM Analysis Report"),
        "research_questions": report_opts.get("research_questions", []),
        "report_type": report_opts.get("report_type", "comprehensive"),
        "report_config": report_opts.get("report_config", {}),
        "analysis_mode": report_opts.get("analysis_mode", "ptm_only"),
        "top_n_ptms": report_opts.get("top_n_ptms", 50),
        "ptm_selection_mode": report_opts.get("ptm_selection_mode", "top_n"),
        "experimental_context": {**(order.analysis_context if isinstance(order.analysis_context, dict) else {}), "ptm_type": order.ptm_type},
        "secondary_ptm_type": getattr(order, 'secondary_ptm_type', None),
        "secondary_sample_config": getattr(order, 'secondary_sample_config', None),
        "secondary_condition_map": _build_condition_map(getattr(order, 'secondary_sample_config', None)) if getattr(order, 'secondary_sample_config', None) else None,
        # Same default as admin-started Orders: the worker chain creates the
        # canonical Wave/TMM/PTM–protein/dynamic artifact in one run.
        "run_temporal_ptm_protein_analysis": True,
    }

    from app.api.orders import _bump_run_generation, _clear_celery_task_ids, _save_celery_task_id
    await _clear_celery_task_ids(order.id)
    task_config["run_generation"] = await _bump_run_generation(order.id)

    # Dispatch Celery task
    from celery import Celery as CeleryClass
    celery_app = CeleryClass("ptm_workers")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

    task = celery_app.send_task(
        "preprocessing.tasks.run_preprocessing",
        args=[order.id, task_config],
        queue="preprocessing",
    )
    await _save_celery_task_id(order.id, task.id)
    logger.info(f"Order {order_code} auto-dispatched — task_id={task.id}")

    # Log the dispatch
    db_log = OrderLog(
        order_id=order.id,
        stage="preprocessing",
        step="dispatch",
        status="started",
        progress_pct=0,
        message=f"Auto-dispatched from User UI (task_id={task.id})",
    )
    db.add(db_log)
    await db.commit()

    return {
        "order_id": order.id,
        "order_code": order.order_code,
        "status": "queued",
        "message": "Analysis created and pipeline started automatically",
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
    assert_not_viewer(user)
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
                # Take first 8000 chars as context (covers abstract + introduction + start of results)
                report_snippet = full_report[:8000]
                context_parts.append(f"\nComprehensive Report (first 8000 chars):\n{report_snippet}")
            except Exception:
                pass

    # Load kinase analysis data (top kinases + temporal cascade)
    if order.kinase_analysis_data:
        try:
            kad = order.kinase_analysis_data if isinstance(order.kinase_analysis_data, dict) else {}
            # Top kinases from kinase_modules
            modules = kad.get("kinase_modules", [])
            if modules:
                top_kinases = sorted(modules, key=lambda m: m.get("total_count", 0), reverse=True)[:8]
                kinase_lines = []
                for km in top_kinases:
                    k = km.get("kinase", "")
                    n_conf = km.get("confirmed_count", 0)
                    n_inf = km.get("inferred_count", 0)
                    n_tot = km.get("total_count", 0)
                    kinase_lines.append(f"  {k}: {n_tot} substrates ({n_conf} confirmed, {n_inf} inferred)")
                context_parts.append(f"\nTop Predicted Kinases (from Global Kinase Module Analysis):\n" + "\n".join(kinase_lines))
            # Temporal cascade from kinase_analysis_data
            temporal_cascade = kad.get("temporal_cascade", {})
            if temporal_cascade:
                cascade_flow = temporal_cascade.get("cascade_flow", [])
                if cascade_flow:
                    flow_lines = []
                    for step in cascade_flow[:6]:
                        tp = step.get("timepoint", "")
                        kinases = ", ".join(step.get("active_kinases", [])[:5])
                        flow_lines.append(f"  {tp}: [{kinases}]")
                    context_parts.append(f"\nTemporal Kinase Cascade:\n" + "\n".join(flow_lines))
        except Exception:
            pass

    # Load kinase activity heatmap top kinases
    if order.kinase_activity_heatmap:
        try:
            hmap = order.kinase_activity_heatmap if isinstance(order.kinase_activity_heatmap, dict) else {}
            ks_list = hmap.get("kinase_scores", [])
            conditions = hmap.get("conditions", [])
            if ks_list and conditions:
                top_ks = sorted(ks_list, key=lambda x: abs(x.get("peak_score", 0)), reverse=True)[:6]
                hmap_lines = []
                for ks in top_ks:
                    k = ks.get("kinase", "")
                    peak = ks.get("peak_score", 0)
                    peak_c = ks.get("peak_condition", "")
                    direction = ks.get("direction", "")
                    n_sub = ks.get("substrate_count", 0)
                    hmap_lines.append(f"  {k}: peak={peak:+.1f} @ {peak_c}, direction={direction}, substrates={n_sub}")
                context_parts.append(f"\nKinase Activity Heatmap (top 6 by peak score):\n" + "\n".join(hmap_lines))
        except Exception:
            pass

    # Load top PTMs from vector plot data
    if output_dir.exists():
        try:
            import csv as _csv
            ptm_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
            vp_path = output_dir / f"ptm_vector_data_normalized{ptm_suffix}.tsv"
            if not vp_path.exists():
                vp_path = output_dir / f"ptm_vector_data_with_motifs{ptm_suffix}.tsv"
            if vp_path.exists():
                rows = []
                with open(vp_path, "r", encoding="utf-8") as _f:
                    reader = _csv.DictReader(_f, delimiter="\t")
                    for row in reader:
                        try:
                            fc = float(row.get("PTM_Relative_Log2FC", 0) or 0)
                        except (ValueError, TypeError):
                            fc = 0
                        rows.append({
                            "gene": row.get("Gene.Name", ""),
                            "pos": row.get("PTM_Position", ""),
                            "cond": row.get("Condition", ""),
                            "fc": fc,
                        })
                # Top 20 by absolute FC
                top_ptms = sorted(rows, key=lambda r: abs(r["fc"]), reverse=True)[:20]
                ptm_lines = [f"  {r['gene']} {r['pos']} @ {r['cond']}: {r['fc']:+.2f}" for r in top_ptms]
                context_parts.append(f"\nTop 20 PTMs by |Log2FC|:\n" + "\n".join(ptm_lines))
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
    assert_not_viewer(user)
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
