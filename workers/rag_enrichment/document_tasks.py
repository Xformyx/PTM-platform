"""
RAG Document Indexing — Celery Task.

Indexes uploaded documents (PDF, MD, TXT) into ChromaDB collections
using the DocumentIndexer from common/document_indexer.py.

Runs on the rag_enrichment queue alongside the main enrichment task.
"""

import logging
import os
import time
import traceback

from celery_app import app
from common.document_indexer import DocumentIndexer

logger = logging.getLogger("ptm-workers.document-indexing")

from sqlalchemy import text

from common.db_engine import get_engine as _get_engine


def _update_document_status(doc_id: int, status: str, chunk_count: int = 0, error_message: str = None):
    """Update rag_documents row with indexing result."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE rag_documents SET status = :status, chunk_count = :chunk_count, "
                    "error_message = :error_message WHERE id = :doc_id"
                ),
                {
                    "doc_id": doc_id,
                    "status": status,
                    "chunk_count": chunk_count,
                    "error_message": error_message,
                },
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update document {doc_id} status: {e}")


def _update_collection_counts(collection_id: int):
    """Recalculate and update document_count and chunk_count for a collection."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) AS doc_count, COALESCE(SUM(chunk_count), 0) AS total_chunks "
                    "FROM rag_documents WHERE collection_id = :cid AND status = 'indexed'"
                ),
                {"cid": collection_id},
            ).fetchone()
            if row:
                conn.execute(
                    text(
                        "UPDATE rag_collections SET document_count = :doc_count, "
                        "chunk_count = :total_chunks WHERE id = :cid"
                    ),
                    {"doc_count": row[0], "total_chunks": row[1], "cid": collection_id},
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update collection {collection_id} counts: {e}")


def _get_collection_info(collection_id: int) -> dict:
    """Fetch collection metadata from DB."""
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT chromadb_name, embedding_model, chunk_size, chunk_strategy "
                "FROM rag_collections WHERE id = :cid"
            ),
            {"cid": collection_id},
        ).fetchone()
    if not row:
        raise ValueError(f"Collection {collection_id} not found")
    return {
        "chromadb_name": row[0],
        "embedding_model": row[1],
        "chunk_size": row[2],
        "chunk_strategy": row[3],
    }


@app.task(bind=True, name="rag_enrichment.document_tasks.index_document", max_retries=2)
def index_document(self, doc_id: int, collection_id: int, file_path: str):
    """
    Index a single uploaded document into its ChromaDB collection.

    Args:
        doc_id: rag_documents.id
        collection_id: rag_collections.id
        file_path: Absolute path to the uploaded file
    """
    start_time = time.time()
    logger.info(f"[Doc {doc_id}] Starting indexing: {file_path}")

    # Mark as processing
    _update_document_status(doc_id, "processing")

    try:
        # Get collection settings
        col_info = _get_collection_info(collection_id)
        chromadb_name = col_info["chromadb_name"]
        embedding_model = col_info["embedding_model"]
        chunk_size = col_info["chunk_size"]

        logger.info(
            f"[Doc {doc_id}] Collection: {chromadb_name}, "
            f"model: {embedding_model}, chunk_size: {chunk_size}"
        )

        # Create indexer
        indexer = DocumentIndexer(
            embedding_model=embedding_model,
            chunk_size=chunk_size,
            overlap_sentences=2,
        )

        # Index the document
        result = indexer.index_document(
            file_path=file_path,
            collection_name=chromadb_name,
            extra_metadata={"collection_id": collection_id, "doc_id": doc_id},
        )

        elapsed = round(time.time() - start_time, 1)

        if result["status"] == "success":
            _update_document_status(doc_id, "indexed", chunk_count=result["chunk_count"])
            _update_collection_counts(collection_id)
            logger.info(
                f"[Doc {doc_id}] Indexed successfully: {result['chunk_count']} chunks "
                f"in {elapsed}s"
            )
            return {
                "doc_id": doc_id,
                "status": "indexed",
                "chunk_count": result["chunk_count"],
                "elapsed_seconds": elapsed,
            }
        else:
            error_msg = result.get("message", "Unknown indexing error")
            _update_document_status(doc_id, "failed", error_message=error_msg)
            logger.error(f"[Doc {doc_id}] Indexing failed: {error_msg}")
            return {
                "doc_id": doc_id,
                "status": "failed",
                "error": error_msg,
                "elapsed_seconds": elapsed,
            }

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        error_msg = f"Indexing error: {str(e)}"
        logger.error(f"[Doc {doc_id}] {error_msg}", exc_info=True)
        _update_document_status(doc_id, "failed", error_message=error_msg)

        # Retry on transient errors (ChromaDB connection, etc.)
        try:
            self.retry(countdown=30, exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"[Doc {doc_id}] Max retries exceeded")
            return {
                "doc_id": doc_id,
                "status": "failed",
                "error": error_msg,
                "elapsed_seconds": elapsed,
            }


@app.task(bind=True, name="rag_enrichment.document_tasks.index_publication_manifest", max_retries=1)
def index_publication_manifest(self, collection_id: int, manifest_path: str):
    """Reindex publication-identified sources into an existing collection.

    This task is deliberately separate from ordinary uploads. It accepts only a
    validated manifest with title + PMID/DOI per source and therefore cannot
    turn a generic bundle label into a Report citation.
    """
    start_time = time.time()
    logger.info("[Publication manifest] Starting reindex: collection=%s manifest=%s", collection_id, manifest_path)
    try:
        col_info = _get_collection_info(collection_id)
        indexer = DocumentIndexer(
            embedding_model=col_info["embedding_model"],
            chunk_size=col_info["chunk_size"],
            overlap_sentences=2,
        )
        result = indexer.index_publication_manifest(
            manifest_path=manifest_path,
            collection_name=col_info["chromadb_name"],
        )
        _update_collection_counts(collection_id)
        result.update({
            "collection_id": collection_id,
            "elapsed_seconds": round(time.time() - start_time, 1),
        })
        logger.info("[Publication manifest] Reindex completed: %s", result)
        return result
    except Exception as exc:
        logger.error("[Publication manifest] Reindex failed: %s", exc, exc_info=True)
        try:
            self.retry(countdown=30, exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "collection_id": collection_id,
                "status": "failed",
                "error": str(exc),
                "elapsed_seconds": round(time.time() - start_time, 1),
            }
