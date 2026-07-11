"""
Cross-Order Comparative Analysis API.

Compares two completed orders' reports and analysis data to identify
shared signaling mechanisms, treatment-specific responses, and temporal dynamics differences.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.order import Order

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compare", tags=["compare"])


# ─── Request / Response Models ────────────────────────────────────────────────

class CompareRequest(BaseModel):
    order_id_a: int
    order_id_b: int
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


def _extract_conditions(vector_data: list[dict]) -> list[str]:
    """Extract condition names from vector data columns."""
    if not vector_data:
        return []
    # Condition columns are those that look like time-points (e.g., 0hr, 30min, 1hr)
    skip_cols = {"Gene", "Position", "Protein", "Motif", "Sequence", "UniProt_ID",
                 "PTM_Score", "Localization_Prob", "Motif_Class", "Kinase_Prediction",
                 "gene", "position", "protein", "motif", "sequence", "uniprot_id",
                 "ptm_score", "localization_prob", "motif_class", "kinase_prediction",
                 "max_abs_fc", "peak_condition", "direction", "cluster_id"}
    first_row = vector_data[0]
    conditions = []
    for col in first_row.keys():
        if col not in skip_cols and col.lower() not in {c.lower() for c in skip_cols}:
            # Try to parse as a numeric value (fold-change)
            try:
                float(first_row[col])
                conditions.append(col)
            except (ValueError, TypeError):
                continue
    return conditions


def _extract_top_ptms(vector_data: list[dict], top_n: int = 50) -> list[dict]:
    """Extract top N PTMs by max absolute fold-change."""
    ptms = []
    conditions = _extract_conditions(vector_data)
    for row in vector_data:
        gene = row.get("Gene") or row.get("gene", "")
        position = row.get("Position") or row.get("position", "")
        values = {}
        max_abs = 0.0
        for cond in conditions:
            try:
                v = float(row.get(cond, 0))
                values[cond] = v
                if abs(v) > max_abs:
                    max_abs = abs(v)
            except (ValueError, TypeError):
                values[cond] = 0.0
        ptms.append({
            "gene": gene,
            "position": position,
            "values": values,
            "max_abs_fc": max_abs,
        })
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
    # Extract top PTMs
    top_a = _extract_top_ptms(vector_a)
    top_b = _extract_top_ptms(vector_b)

    # Build lookup by gene+position
    a_map = {f"{p['gene']}_{p['position']}": p for p in top_a}
    b_map = {f"{p['gene']}_{p['position']}": p for p in top_b}

    shared_keys = set(a_map.keys()) & set(b_map.keys())
    a_only_keys = set(a_map.keys()) - set(b_map.keys())
    b_only_keys = set(b_map.keys()) - set(a_map.keys())

    # Find common conditions for correlation
    conds_a = _extract_conditions(vector_a)
    conds_b = _extract_conditions(vector_b)
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

        shared_ptms.append({
            "gene": pa["gene"],
            "position": pa["position"],
            "a_max_fc": round(a_max, 3),
            "b_max_fc": round(b_max, 3),
            "correlation": round(corr, 3),
            "classification": classification,
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
) -> str:
    """Build the LLM prompt for comparative analysis."""
    order_a = comparison_data["order_a"]
    order_b = comparison_data["order_b"]
    stats = comparison_data["stats"]

    # Truncate reports if too long (keep first 8000 chars each)
    max_report_len = 8000
    report_a_trunc = report_a[:max_report_len] if len(report_a) > max_report_len else report_a
    report_b_trunc = report_b[:max_report_len] if len(report_b) > max_report_len else report_b

    # Top shared PTMs for context
    top_shared = comparison_data["shared_ptms"][:20]
    shared_table = "\n".join(
        f"  {p['gene']} {p['position']}: A={p['a_max_fc']:+.2f}, B={p['b_max_fc']:+.2f}, r={p['correlation']:.2f}, class={p['classification']}"
        for p in top_shared
    )

    prompt = f"""You are a senior proteomics bioinformatician. Analyze the comparison between two PTM time-series experiments and write a comprehensive comparative report.

═══ EXPERIMENT OVERVIEW ═══

Order A: {order_a['project_name']}
  - Species: {order_a['species']}, PTM: {order_a['ptm_type']}
  - Conditions (timepoints): {', '.join(order_a['conditions'])}

Order B: {order_b['project_name']}
  - Species: {order_b['species']}, PTM: {order_b['ptm_type']}
  - Conditions (timepoints): {', '.join(order_b['conditions'])}

═══ QUANTITATIVE COMPARISON SUMMARY ═══

Shared PTMs: {stats['total_shared']} | A-only: {stats['total_a_only']} | B-only: {stats['total_b_only']}
Direction concordance: {stats['direction_concordance']:.1%}
Classification: {json.dumps(stats['classification_counts'])}

Shared Kinases ({stats['shared_kinase_count']}): {', '.join(comparison_data['shared_kinases'][:15])}
A-only Kinases: {', '.join(comparison_data['a_only_kinases'][:10])}
B-only Kinases: {', '.join(comparison_data['b_only_kinases'][:10])}

Shared Receptors ({stats['shared_receptor_count']}): {', '.join(comparison_data['shared_receptors'][:10])}
A-only Receptors: {', '.join(comparison_data['a_only_receptors'][:10])}
B-only Receptors: {', '.join(comparison_data['b_only_receptors'][:10])}

═══ TOP SHARED PTMs (by correlation) ═══
{shared_table}

═══ ORDER A REPORT (excerpt) ═══
{report_a_trunc}

═══ ORDER B REPORT (excerpt) ═══
{report_b_trunc}

═══ INSTRUCTIONS ═══

Write a structured comparative analysis report in Korean with the following sections:

## 1. 공통 Signaling Mechanism
- Identify shared pathways activated by both treatments
- Explain the biological significance of common kinase/receptor activation

## 2. 물질 특이적 반응 (Treatment-Specific Responses)
- For each treatment, describe unique signaling events
- Explain what these differences reveal about mechanism of action

## 3. Temporal Dynamics 비교
- Compare the timing of responses (early vs late, transient vs sustained)
- Identify any delayed or dose-dependent patterns

## 4. Kinase Activity 비교
- Compare active kinases between treatments
- Identify shared vs unique substrate phosphorylation patterns

## 5. Receptor → Cascade 분기점 (Signaling Divergence)
- Map where shared upstream signals diverge into treatment-specific cascades
- Identify the branching points in signaling networks

## 6. 치료적 함의 (Therapeutic Implications)
- Suggest potential drug targets based on shared/unique pathways
- Discuss synergy or antagonism possibilities

RULES:
- Base ALL conclusions on the provided data. Do NOT fabricate findings.
- Use specific gene names, positions, and fold-change values from the data.
- Clearly distinguish between confirmed observations and hypotheses.
- Write in academic Korean with English gene/protein names.
- Keep each section concise but informative (200-400 words per section).
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
    prompt = _build_comparison_prompt(comparison, report_a, report_b)

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
                        json={
                            "model": llm_model,
                            "messages": [
                                {"role": "system", "content": "You are a senior proteomics bioinformatician specializing in comparative PTM analysis."},
                                {"role": "user", "content": prompt},
                            ],
                            "stream": True,
                            "options": {
                                "temperature": 0.6,
                                "num_predict": 8192,
                                "num_ctx": 32768,
                            },
                        },
                    ) as resp:
                        if resp.status_code != 200:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM error: {resp.status_code}'})}\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                content = data.get("message", {}).get("content", "")
                                done = data.get("done", False)
                                if content:
                                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                                if done:
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
                                content = delta.get("content", "")
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
