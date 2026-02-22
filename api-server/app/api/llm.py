import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.llm_model import LlmModel

router = APIRouter(prefix="/llm", tags=["llm"])
logger = logging.getLogger("ptm-platform.llm")


class LlmModelCreate(BaseModel):
    name: str
    provider: str
    model_id: str
    endpoint_url: Optional[str] = None
    api_key: Optional[str] = None
    purpose: str = "general"
    default_temp: float = 0.7
    max_tokens: int = 4096


class LlmModelUpdate(BaseModel):
    name: Optional[str] = None
    purpose: Optional[str] = None
    default_temp: Optional[float] = None
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


@router.get("/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(LlmModel).order_by(LlmModel.provider, LlmModel.name))
    models = result.scalars().all()

    return {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "model_id": m.model_id,
                "purpose": m.purpose,
                "default_temp": float(m.default_temp),
                "max_tokens": m.max_tokens,
                "is_active": m.is_active,
                "is_default": m.is_default,
                "has_api_key": m.api_key_encrypted is not None,
            }
            for m in models
        ]
    }


@router.post("/models")
async def create_model(
    body: LlmModelCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    model = LlmModel(
        name=body.name,
        provider=body.provider,
        model_id=body.model_id,
        endpoint_url=body.endpoint_url,
        api_key_encrypted=body.api_key,
        purpose=body.purpose,
        default_temp=body.default_temp,
        max_tokens=body.max_tokens,
        is_active=True,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return {"id": model.id, "message": "Model registered"}


@router.put("/models/{model_id}")
async def update_model(
    model_id: int,
    body: LlmModelUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(LlmModel).where(LlmModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "api_key":
            model.api_key_encrypted = value
        else:
            setattr(model, field, value)

    await db.commit()
    return {"id": model.id, "message": "Model updated"}


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(LlmModel).where(LlmModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    await db.delete(model)
    await db.commit()
    return {"message": "Model deleted"}


@router.post("/models/sync-ollama")
async def sync_ollama_models(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            ollama_models = resp.json().get("models", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ollama: {e}")

    synced = []
    for m in ollama_models:
        model_name = m.get("name", "")
        existing = await db.execute(
            select(LlmModel).where(
                LlmModel.provider == "ollama", LlmModel.model_id == model_name
            )
        )
        if existing.scalar_one_or_none() is None:
            new_model = LlmModel(
                name=model_name,
                provider="ollama",
                model_id=model_name,
                endpoint_url=settings.OLLAMA_URL,
                is_active=True,
            )
            db.add(new_model)
            synced.append(model_name)

    await db.commit()
    return {"synced": synced, "total_ollama": len(ollama_models)}


@router.post("/models/{model_id}/test")
async def test_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    result = await db.execute(select(LlmModel).where(LlmModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if model.provider == "ollama":
        url = model.endpoint_url or settings.OLLAMA_URL
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{url}/api/generate",
                    json={"model": model.model_id, "prompt": "Hello", "stream": False},
                )
                resp.raise_for_status()
                return {"status": "ok", "response_preview": resp.json().get("response", "")[:100]}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    return {"status": "skipped", "detail": "Cloud LLM test not yet implemented"}


class OllamaPullRequest(BaseModel):
    model_name: str


@router.post("/ollama/pull")
async def pull_ollama_model(
    body: OllamaPullRequest,
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Stream Ollama model pull progress as SSE."""

    async def _stream():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=600.0)) as client:
                async with client.stream(
                    "POST",
                    f"{settings.OLLAMA_URL}/api/pull",
                    json={"name": body.model_name, "stream": True},
                ) as resp:
                    if resp.status_code != 200:
                        error_text = ""
                        async for chunk in resp.aiter_text():
                            error_text += chunk
                        yield f"data: {json.dumps({'error': error_text})}\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            total = data.get("total", 0)
                            completed = data.get("completed", 0)
                            pct = round(completed / total * 100, 1) if total > 0 else 0
                            yield f"data: {json.dumps({'status': status, 'pct': pct, 'total': total, 'completed': completed})}\n\n"
                        except json.JSONDecodeError:
                            pass

            yield f"data: {json.dumps({'status': 'done', 'pct': 100})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


class OllamaDeleteRequest(BaseModel):
    model_name: str


@router.post("/ollama/delete")
async def delete_ollama_model(
    body: OllamaDeleteRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Delete a model from Ollama and remove from DB."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                "DELETE",
                f"{settings.OLLAMA_URL}/api/delete",
                json={"name": body.model_name},
            )
            if resp.status_code not in (200, 404):
                raise HTTPException(status_code=502, detail=f"Ollama error: {resp.text}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ollama: {e}")

    result = await db.execute(
        select(LlmModel).where(LlmModel.provider == "ollama", LlmModel.model_id == body.model_name)
    )
    model = result.scalar_one_or_none()
    if model:
        await db.delete(model)
        await db.commit()

    return {"message": f"Model '{body.model_name}' deleted"}


@router.get("/ollama/running")
async def list_ollama_models(
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """List models currently available in Ollama."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return {
                "models": [
                    {
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                        "modified_at": m.get("modified_at", ""),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "family": m.get("details", {}).get("family", ""),
                        "quantization": m.get("details", {}).get("quantization_level", ""),
                    }
                    for m in models
                ]
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Ollama: {e}")
