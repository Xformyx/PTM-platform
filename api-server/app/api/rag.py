import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.rag_collection import RagCollection, RagDocument

router = APIRouter(prefix="/rag", tags=["rag"])
logger = logging.getLogger("ptm-platform.rag")


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


@router.get("/collections")
async def list_collections(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(RagCollection).order_by(RagCollection.tier, RagCollection.name)
    )
    collections = result.scalars().all()

    return {
        "collections": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "tier": c.tier,
                "chromadb_name": c.chromadb_name,
                "embedding_model": c.embedding_model,
                "chunk_strategy": c.chunk_strategy,
                "chunk_size": c.chunk_size,
                "document_count": c.document_count,
                "chunk_count": c.chunk_count,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat(),
            }
            for c in collections
        ]
    }


@router.post("/collections")
async def create_collection(
    body: CollectionCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    chromadb_name = f"ptm_{body.tier}_{body.name.lower().replace(' ', '_')}"

    collection = RagCollection(
        name=body.name,
        description=body.description,
        tier=body.tier,
        chromadb_name=chromadb_name,
        embedding_model=body.embedding_model,
        chunk_strategy=body.chunk_strategy,
        chunk_size=body.chunk_size,
    )
    db.add(collection)
    await db.commit()
    await db.refresh(collection)

    logger.info(f"RAG collection created: {body.name} (tier={body.tier})")
    return {"id": collection.id, "chromadb_name": chromadb_name, "message": "Collection created"}


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
        select(RagDocument).where(RagDocument.collection_id == collection_id)
    )
    documents = doc_result.scalars().all()

    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "tier": c.tier,
        "chromadb_name": c.chromadb_name,
        "embedding_model": c.embedding_model,
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
                "created_at": d.created_at.isoformat(),
            }
            for d in documents
        ],
    }


@router.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    await db.delete(collection)
    await db.commit()

    # TODO: also delete from ChromaDB

    return {"message": "Collection deleted"}


@router.post("/collections/{collection_id}/documents")
async def upload_document(
    collection_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"
    if ext not in ("pdf", "md", "txt", "csv"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    from pathlib import Path
    from app.config import get_settings
    settings = get_settings()

    doc_dir = Path(settings.INPUT_DIR) / "rag" / collection.chromadb_name
    doc_dir.mkdir(parents=True, exist_ok=True)

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

    # TODO: dispatch indexing task via Celery

    return {"id": doc.id, "filename": file.filename, "status": "pending"}
