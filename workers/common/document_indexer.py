"""
Document Indexer — embeds and indexes documents into ChromaDB collections.

Ported from ptm-chromadb-web/python_backend/document_embedder.py and
knowledge_retriever.py.

Features:
  - PDF, Markdown, TXT parsing
  - Section-aware chunking via section_chunker
  - Enhanced PTM tokenizer for domain-specific text processing
  - Batch embedding with sentence-transformers
  - Metadata preservation (title, year, PMID, section, source)
  - Duplicate detection via content hashing
"""

import hashlib
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_embedding_device() -> str:
    """Auto-detect the best available device for sentence-transformers.

    Returns 'cuda' when an NVIDIA GPU is accessible, 'cpu' otherwise.
    Respects EMBEDDING_DEVICE env var for manual override.
    """
    override = os.environ.get("EMBEDDING_DEVICE", "").strip().lower()
    if override in ("cuda", "cpu", "mps"):
        return override
    try:
        import torch
        if torch.cuda.is_available():
            logger.info(
                "CUDA detected — embedding model will run on GPU "
                f"({torch.cuda.get_device_name(0)})"
            )
            return "cuda"
    except Exception:
        pass
    return "cpu"


# ---------------------------------------------------------------------------
# Collection Name Sanitizer (v84)
# ---------------------------------------------------------------------------

def sanitize_collection_name(name: str) -> str:
    """
    ChromaDB 컬렉션 이름을 유효한 형식으로 변환.
    ChromaDB 규칙: [a-zA-Z0-9._-], 3~512자, 시작/끝은 [a-zA-Z0-9]

    예: 'Hippocampal Neurons' -> 'Hippocampal-Neurons'
        'My Collection!@#' -> 'My-Collection'
        '  test  ' -> 'test'
    """
    if not name or not name.strip():
        return 'unnamed-collection'

    # 앞뒤 공백 제거
    sanitized = name.strip()
    # 공백 → 하이픈
    sanitized = sanitized.replace(' ', '-')
    # 허용되지 않는 문자 제거 (a-zA-Z0-9._- 만 허용)
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '', sanitized)
    # 연속 하이픈/점 정리
    sanitized = re.sub(r'[-]+', '-', sanitized)
    sanitized = re.sub(r'[.]+', '.', sanitized)
    # 시작/끝은 [a-zA-Z0-9]만 허용
    sanitized = sanitized.strip('.-_')
    # 최소 3자 보장
    if len(sanitized) < 3:
        sanitized = sanitized + '-col'
    # 최대 512자
    sanitized = sanitized[:512]
    # 끝이 특수문자로 끝나면 제거
    sanitized = sanitized.rstrip('.-_')

    if not sanitized or len(sanitized) < 3:
        return 'unnamed-collection'

    return sanitized

CHROMADB_URL = os.getenv("CHROMADB_URL", "http://chromadb:8000")


# ---------------------------------------------------------------------------
# Enhanced PTM Tokenizer
# ---------------------------------------------------------------------------

# Patterns for PTM-specific text normalization
PTM_PATTERNS = {
    # Phosphorylation sites: pSer473, p-Ser473, Ser(P)473, S473
    "phospho_site": re.compile(
        r"\b(?:p-?(?:Ser|Thr|Tyr)|(?:Ser|Thr|Tyr)\(P\))\s*\d+\b", re.IGNORECASE,
    ),
    # Gene names: uppercase 2-6 chars followed by optional number
    "gene_name": re.compile(r"\b[A-Z][A-Z0-9]{1,5}\d*\b"),
    # PTM types
    "ptm_type": re.compile(
        r"\b(?:phosphorylation|acetylation|ubiquitylation|ubiquitination|methylation|"
        r"sumoylation|glycosylation|nitrosylation)\b",
        re.IGNORECASE,
    ),
    # Kinase/phosphatase names
    "enzyme": re.compile(
        r"\b(?:[A-Z][A-Z0-9]{1,5}(?:\s*kinase|\s*phosphatase))\b", re.IGNORECASE,
    ),
}


def enhance_ptm_text(text: str) -> str:
    """
    Enhance text for better PTM-specific embedding by normalizing PTM terms.

    This helps sentence-transformers better capture PTM-specific semantics.
    """
    enhanced = text

    # Normalize phospho-site notation: pSer473 → phospho-Ser473
    enhanced = re.sub(
        r"\bp-?(Ser|Thr|Tyr)(\d+)",
        r"phospho-\1\2",
        enhanced,
        flags=re.IGNORECASE,
    )

    # Normalize Ser(P)473 → phospho-Ser473
    enhanced = re.sub(
        r"(Ser|Thr|Tyr)\(P\)(\d+)",
        r"phospho-\1\2",
        enhanced,
        flags=re.IGNORECASE,
    )

    return enhanced


# ---------------------------------------------------------------------------
# Document Parser
# ---------------------------------------------------------------------------

def parse_document(file_path: str) -> Dict:
    """
    Parse a document file and extract text content with metadata.

    Supports: PDF, Markdown (.md), plain text (.txt)

    Returns:
        dict with keys: text, title, file_type, metadata
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(path)
    elif ext == ".md":
        return _parse_markdown(path)
    elif ext in (".txt", ".csv"):
        return _parse_text(path)
    else:
        logger.warning(f"Unsupported file type: {ext}, treating as plain text")
        return _parse_text(path)


def _parse_pdf(path: Path) -> Dict:
    """Parse PDF file."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        text = "\n\n".join(pages)
        doc.close()

        # Extract title from first page or filename
        title = _extract_title_from_text(text) or path.stem

        return {
            "text": text,
            "title": title,
            "file_type": "pdf",
            "metadata": {"pages": len(pages), "filename": path.name},
        }
    except ImportError:
        logger.warning("PyMuPDF not available, falling back to pdftotext")
        import subprocess

        result = subprocess.run(
            ["pdftotext", str(path), "-"], capture_output=True, text=True,
        )
        text = result.stdout
        return {
            "text": text,
            "title": path.stem,
            "file_type": "pdf",
            "metadata": {"filename": path.name},
        }


def _parse_markdown(path: Path) -> Dict:
    """Parse Markdown file."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Extract title from first heading
    title_match = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    return {
        "text": text,
        "title": title,
        "file_type": "md",
        "metadata": {"filename": path.name},
    }


def _parse_text(path: Path) -> Dict:
    """Parse plain text file."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "text": text,
        "title": path.stem,
        "file_type": "txt",
        "metadata": {"filename": path.name},
    }


def _extract_title_from_text(text: str) -> Optional[str]:
    """Try to extract paper title from text."""
    lines = text.strip().split("\n")
    for line in lines[:10]:
        stripped = line.strip()
        if 20 < len(stripped) < 200 and not stripped.startswith(("http", "doi", "©")):
            return stripped
    return None


# ---------------------------------------------------------------------------
# Document Indexer
# ---------------------------------------------------------------------------

class DocumentIndexer:
    """Indexes documents into ChromaDB with section-aware chunking."""

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        chunk_size: int = 2000,
        overlap_sentences: int = 2,
    ):
        self.embedding_model_name = embedding_model
        self.chunk_size = chunk_size
        self.overlap_sentences = overlap_sentences
        self._chromadb_client = None
        self._embedding_model = None

    @property
    def chromadb_client(self):
        if self._chromadb_client is None:
            try:
                import chromadb

                host = CHROMADB_URL.replace("http://", "").split(":")[0]
                port = int(CHROMADB_URL.split(":")[-1])
                self._chromadb_client = chromadb.HttpClient(host=host, port=port)
                logger.info(f"ChromaDB connected at {CHROMADB_URL}")
            except Exception as e:
                logger.error(f"ChromaDB connection failed: {e}")
        return self._chromadb_client

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            try:
                from ptm_shared.embedding_registry import resolve_embedding_spec
                from sentence_transformers import SentenceTransformer

                # Auto-detect CUDA; fall back to CPU gracefully
                device = _get_embedding_device()
                spec = resolve_embedding_spec(self.embedding_model_name)
                self._embedding_model = SentenceTransformer(
                    spec.hf_model_id, device=device
                )
                logger.info(
                    f"Loaded embedding model: {spec.key} (device={device})"
                )
            except (ImportError, ValueError) as exc:
                logger.error(f"Embedding model unavailable: {exc}")
        return self._embedding_model

    def index_document(
        self,
        file_path: str,
        collection_name: str,
        extra_metadata: Optional[Dict] = None,
        progress_callback=None,
    ) -> Dict:
        """
        Index a single document into a ChromaDB collection.

        Args:
            file_path: Path to the document file
            collection_name: Target ChromaDB collection name
            extra_metadata: Additional metadata to attach to each chunk
            progress_callback: Optional callback(pct, msg)

        Returns:
            dict with indexing results (chunk_count, status, etc.)
        """
        if progress_callback:
            progress_callback(0, f"Parsing document: {Path(file_path).name}")

        # 1. Parse document
        doc = parse_document(file_path)
        if not doc["text"].strip():
            return {"status": "error", "message": "Empty document", "chunk_count": 0}

        if progress_callback:
            progress_callback(20, "Chunking document")

        # 2. Chunk with section awareness
        from common.section_chunker import section_aware_chunk

        chunks = section_aware_chunk(
            text=doc["text"],
            max_chunk_size=self.chunk_size,
            overlap_sentences=self.overlap_sentences,
            source=doc["title"],
        )

        if not chunks:
            return {"status": "error", "message": "No chunks generated", "chunk_count": 0}

        if progress_callback:
            progress_callback(40, f"Embedding {len(chunks)} chunks")

        # 3. Enhance text for PTM-specific embedding
        enhanced_texts = [enhance_ptm_text(c["text"]) for c in chunks]

        # 4. Generate embeddings
        if self.embedding_model is None:
            return {"status": "error", "message": "Embedding model not available", "chunk_count": 0}

        from ptm_shared.embedding_registry import resolve_embedding_spec

        spec = resolve_embedding_spec(self.embedding_model_name)
        embeddings = self.embedding_model.encode(
            enhanced_texts,
            show_progress_bar=False,
            normalize_embeddings=spec.normalize_embeddings,
        )
        if len(embeddings[0]) != spec.dimension:
            return {
                "status": "error",
                "message": (
                    f"Embedding dimension mismatch for {spec.key}: "
                    f"expected {spec.dimension}, got {len(embeddings[0])}"
                ),
                "chunk_count": 0,
            }

        if progress_callback:
            progress_callback(70, "Storing in ChromaDB")

        # 5. Prepare metadata
        base_meta = {
            "title": doc["title"],
            "file_type": doc["file_type"],
            "filename": doc["metadata"].get("filename", ""),
        }
        if extra_metadata:
            base_meta.update(extra_metadata)

        # 6. Store in ChromaDB
        try:
            collection_name = sanitize_collection_name(collection_name)
            collection = self.chromadb_client.get_or_create_collection(
                name=collection_name,
                metadata=spec.chromadb_metadata(),
            )
            existing_metadata = collection.metadata or {}
            existing_key = existing_metadata.get("ptm_embedding_model_key")
            if existing_key and existing_key != spec.key:
                return {
                    "status": "error",
                    "message": (
                        f"Embedding contract mismatch: collection uses '{existing_key}', "
                        f"index request uses '{spec.key}'. Clone and reindex instead."
                    ),
                    "chunk_count": 0,
                }
            if not existing_key and collection.count() > 0 and spec.key != "all-MiniLM-L6-v2":
                return {
                    "status": "error",
                    "message": (
                        "Legacy collection has no embedding metadata. Create a new collection "
                        "and reindex before using a non-default embedding model."
                    ),
                    "chunk_count": 0,
                }
            if not existing_key and collection.count() == 0:
                collection.modify(metadata=spec.chromadb_metadata())

            ids = []
            documents = []
            metadatas = []
            embedding_list = []

            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                # Deduplicate by content hash
                content_hash = hashlib.md5(chunk["text"].encode()).hexdigest()
                chunk_id = f"{content_hash}_{i}"

                chunk_meta = {**base_meta}
                chunk_meta["section"] = chunk.get("section", "")
                chunk_meta["section_title"] = chunk.get("section_title", "")
                chunk_meta["chunk_index"] = chunk.get("section_chunk_index", i)
                chunk_meta["chunking_method"] = chunk.get("chunking_method", "")
                chunk_meta["embedding_model_key"] = spec.key
                chunk_meta["embedding_dimension"] = spec.dimension
                chunk_meta["embedding_normalized"] = spec.normalize_embeddings

                ids.append(chunk_id)
                documents.append(chunk["text"])
                metadatas.append(chunk_meta)
                embedding_list.append(embedding.tolist())

            # Batch upsert
            batch_size = 100
            for start in range(0, len(ids), batch_size):
                end = min(start + batch_size, len(ids))
                collection.upsert(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                    embeddings=embedding_list[start:end],
                )

            if progress_callback:
                progress_callback(100, f"Indexed {len(chunks)} chunks")

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "collection": collection_name,
                "title": doc["title"],
                "embedding_model": spec.key,
                "embedding_dimension": spec.dimension,
            }

        except Exception as e:
            logger.error(f"ChromaDB indexing failed: {e}")
            return {"status": "error", "message": str(e), "chunk_count": 0}

    def index_directory(
        self,
        directory: str,
        collection_name: str,
        extra_metadata: Optional[Dict] = None,
        progress_callback=None,
    ) -> Dict:
        """
        Index all documents in a directory.

        Returns:
            dict with total_files, total_chunks, errors
        """
        dir_path = Path(directory)
        supported_exts = {".pdf", ".md", ".txt"}
        files = [f for f in dir_path.rglob("*") if f.suffix.lower() in supported_exts]

        results = {"total_files": len(files), "total_chunks": 0, "errors": []}

        for i, file_path in enumerate(files):
            if progress_callback:
                pct = (i / len(files)) * 100
                progress_callback(pct, f"Indexing {file_path.name} ({i+1}/{len(files)})")

            result = self.index_document(
                str(file_path), collection_name, extra_metadata,
            )

            if result["status"] == "success":
                results["total_chunks"] += result["chunk_count"]
            else:
                results["errors"].append(
                    {"file": str(file_path), "error": result.get("message", "Unknown error")},
                )

        return results
