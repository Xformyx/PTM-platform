import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.rag_collection import RagCollection, RagDocument
from app.utils.sanitize import sanitize_collection_name
from ptm_shared.embedding_registry import resolve_embedding_spec, supported_embedding_models

router = APIRouter(prefix="/rag", tags=["rag"])
logger = logging.getLogger("ptm-platform.rag")

# Template collections (no data in ChromaDB) — hidden from UI
TEMPLATE_CHROMADB_NAMES = frozenset({
    "neuroscience", "cancer_biology", "immunology", "stem_cell",
    "cardiovascular", "metabolism", "liver_biology",
    "phosphorylation", "acetylation", "ubiquitylation", "methylation",
    "mapk_signaling", "pi3k_akt", "wnt_signaling", "tgfb_signaling",
    "nfkb_signaling", "calcium_signaling", "cell_cycle", "apoptosis",
    "textbooks", "reviews", "pathway_databases", "ptm_databases",
})


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tier: str
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_strategy: str = "recursive"
    chunk_size: int = 1000


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


def _get_celery_app():
    """Create a lightweight Celery client for dispatching tasks."""
    from celery import Celery as CeleryClass

    celery_app = CeleryClass("ptm_workers")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    return celery_app


# ─── Collection CRUD ─────────────────────────────────────────────────────────


@router.get("/collections")
async def list_collections(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(RagCollection).order_by(RagCollection.tier, RagCollection.name)
    )
    all_collections = result.scalars().all()
    collections = [c for c in all_collections if c.chromadb_name not in TEMPLATE_CHROMADB_NAMES]

    return {
        "collections": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "tier": c.tier,
                "chromadb_name": c.chromadb_name,
                "embedding_model": c.embedding_model,
                "embedding_model_info": resolve_embedding_spec(c.embedding_model).public_dict(),
                "chunk_strategy": c.chunk_strategy,
                "chunk_size": c.chunk_size,
                "document_count": c.document_count,
                "chunk_count": c.chunk_count,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat() + "Z",
            }
            for c in collections
        ]
    }


@router.get("/embedding-models")
async def list_embedding_models(user=Depends(get_current_user)):
    """Expose supported, immutable collection embedding contracts to the UI."""
    return {"models": supported_embedding_models()}


@router.post("/collections")
async def create_collection(
    body: CollectionCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    try:
        embedding_spec = resolve_embedding_spec(body.embedding_model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    chromadb_name = sanitize_collection_name(
        f"ptm_{body.tier}_{body.name.lower().replace(' ', '_')}"
    )

    # Check for duplicate chromadb_name
    existing = await db.execute(
        select(RagCollection).where(RagCollection.chromadb_name == chromadb_name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Collection with internal name '{chromadb_name}' already exists. Please choose a different name.",
        )

    try:
        collection = RagCollection(
            name=body.name,
            description=body.description,
            tier=body.tier,
            chromadb_name=chromadb_name,
            embedding_model=embedding_spec.key,
            chunk_strategy=body.chunk_strategy,
            chunk_size=body.chunk_size,
        )
        db.add(collection)
        await db.commit()
        await db.refresh(collection)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create collection '{body.name}': {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error while creating collection: {str(e)}",
        )

    logger.info(f"RAG collection created: {body.name} (tier={body.tier})")
    return {
        "id": collection.id,
        "chromadb_name": chromadb_name,
        "embedding_model": embedding_spec.public_dict(),
        "reindex_required_on_model_change": True,
        "message": "Collection created",
    }


@router.get("/collections/{collection_id}")
async def get_collection(
    collection_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Collection not found")

    doc_result = await db.execute(
        select(RagDocument)
        .where(RagDocument.collection_id == collection_id)
        .order_by(RagDocument.created_at.desc())
    )
    documents = doc_result.scalars().all()

    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "tier": c.tier,
        "chromadb_name": c.chromadb_name,
        "embedding_model": c.embedding_model,
        "embedding_model_info": resolve_embedding_spec(c.embedding_model).public_dict(),
        "chunk_strategy": c.chunk_strategy,
        "chunk_size": c.chunk_size,
        "document_count": c.document_count,
        "chunk_count": c.chunk_count,
        "is_active": c.is_active,
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "file_type": d.file_type,
                "file_size_bytes": d.file_size_bytes,
                "chunk_count": d.chunk_count,
                "status": d.status,
                "error_message": d.error_message,
                "created_at": d.created_at.isoformat() + "Z",
            }
            for d in documents
        ],
    }


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: int,
    body: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    if body.is_active is not None:
        collection.is_active = body.is_active
    if body.name is not None:
        collection.name = body.name
    if body.description is not None:
        collection.description = body.description

    await db.commit()
    await db.refresh(collection)

    logger.info(f"RAG collection {collection_id} updated (is_active={collection.is_active})")
    return {"id": collection.id, "is_active": collection.is_active}


@router.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Delete from ChromaDB
    chromadb_name = collection.chromadb_name
    try:
        import httpx

        chromadb_url = os.getenv("CHROMADB_URL", "http://chromadb:8000")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(f"{chromadb_url}/api/v1/collections/{chromadb_name}")
            if resp.status_code in (200, 404):
                logger.info(f"ChromaDB collection '{chromadb_name}' deleted (status={resp.status_code})")
            else:
                logger.warning(f"ChromaDB delete returned {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Failed to delete ChromaDB collection '{chromadb_name}': {e}")

    await db.delete(collection)
    await db.commit()

    return {"message": "Collection deleted"}


# ─── Document Upload & Indexing ──────────────────────────────────────────────


@router.post("/collections/{collection_id}/documents")
async def upload_document(
    collection_id: int,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    """Upload one or more documents and dispatch indexing tasks."""
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    from pathlib import Path
    from app.config import get_settings

    settings = get_settings()
    doc_dir = Path(settings.INPUT_DIR) / "rag" / collection.chromadb_name
    doc_dir.mkdir(parents=True, exist_ok=True)

    celery_app = _get_celery_app()
    uploaded = []

    for file in files:
        ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"
        if ext not in ("pdf", "md", "txt", "csv"):
            uploaded.append({"filename": file.filename, "status": "rejected", "error": f"Unsupported file type: {ext}"})
            continue

        file_path = doc_dir / file.filename
        content = await file.read()
        file_path.write_bytes(content)

        doc = RagDocument(
            collection_id=collection_id,
            filename=file.filename,
            file_path=str(file_path),
            file_type=ext,
            file_size_bytes=len(content),
            status="pending",
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        # Dispatch Celery indexing task
        try:
            task = celery_app.send_task(
                "rag_enrichment.document_tasks.index_document",
                args=[doc.id, collection_id, str(file_path)],
                queue="rag_enrichment",
            )
            logger.info(f"Document '{file.filename}' uploaded, indexing task dispatched: {task.id}")
            uploaded.append({
                "id": doc.id,
                "filename": file.filename,
                "file_size_bytes": len(content),
                "status": "pending",
                "task_id": task.id,
            })
        except Exception as e:
            logger.error(f"Failed to dispatch indexing task for '{file.filename}': {e}")
            doc.status = "failed"
            doc.error_message = f"Task dispatch failed: {str(e)}"
            await db.commit()
            uploaded.append({
                "id": doc.id,
                "filename": file.filename,
                "status": "failed",
                "error": str(e),
            })

    return {"documents": uploaded}


@router.delete("/collections/{collection_id}/documents/{document_id}")
async def delete_document(
    collection_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    """Delete a document from the collection and remove its chunks from ChromaDB."""
    result = await db.execute(
        select(RagDocument).where(
            RagDocument.id == document_id,
            RagDocument.collection_id == collection_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get collection info for ChromaDB cleanup
    col_result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    collection = col_result.scalar_one_or_none()

    # Remove chunks from ChromaDB by doc_id metadata
    if collection and doc.status == "indexed":
        try:
            import httpx

            chromadb_url = os.getenv("CHROMADB_URL", "http://chromadb:8000")
            # ChromaDB delete by metadata filter
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{chromadb_url}/api/v1/collections/{collection.chromadb_name}/delete",
                    json={"where": {"doc_id": doc.id}},
                )
                logger.info(f"ChromaDB chunks deleted for doc {doc.id}: status={resp.status_code}")
        except Exception as e:
            logger.warning(f"Failed to delete ChromaDB chunks for doc {doc.id}: {e}")

    # Delete file from disk
    try:
        from pathlib import Path

        file_path = Path(doc.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to delete file {doc.file_path}: {e}")

    await db.delete(doc)
    await db.commit()

    # Update collection counts
    count_result = await db.execute(
        select(RagDocument).where(
            RagDocument.collection_id == collection_id,
            RagDocument.status == "indexed",
        )
    )
    indexed_docs = count_result.scalars().all()
    if collection:
        collection.document_count = len(indexed_docs)
        collection.chunk_count = sum(d.chunk_count for d in indexed_docs)
        await db.commit()

    return {"message": "Document deleted"}


@router.post("/collections/{collection_id}/documents/{document_id}/reindex")
async def reindex_document(
    collection_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    """Re-index a failed or existing document."""
    result = await db.execute(
        select(RagDocument).where(
            RagDocument.id == document_id,
            RagDocument.collection_id == collection_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    from pathlib import Path

    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=400, detail="Source file no longer exists on disk")

    # Reset status
    doc.status = "pending"
    doc.error_message = None
    doc.chunk_count = 0
    await db.commit()

    # Dispatch indexing task
    celery_app = _get_celery_app()
    task = celery_app.send_task(
        "rag_enrichment.document_tasks.index_document",
        args=[doc.id, collection_id, doc.file_path],
        queue="rag_enrichment",
    )

    logger.info(f"Document {document_id} re-index dispatched: {task.id}")
    return {"id": doc.id, "status": "pending", "task_id": task.id}
