"""Shared embedding contracts for PTM-platform ChromaDB collections.

The registry keeps document and query embeddings in the same vector space.  It
is deliberately dependency-light: sentence-transformers is imported only when
an embedding is requested, allowing API metadata endpoints to remain available
even when a model image has not yet been rebuilt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Iterable, Sequence


@dataclass(frozen=True)
class EmbeddingSpec:
    key: str
    hf_model_id: str
    dimension: int
    normalize_embeddings: bool
    hnsw_space: str
    label: str
    license_class: str
    status: str = "supported"
    max_sequence_length: int | None = None

    def chromadb_metadata(self) -> dict:
        """Return the immutable embedding contract stored with a collection."""
        return {
            "hnsw:space": self.hnsw_space,
            "ptm_embedding_contract_version": "1",
            "ptm_embedding_model_key": self.key,
            "ptm_embedding_model_id": self.hf_model_id,
            "ptm_embedding_dimension": self.dimension,
            "ptm_embedding_normalized": self.normalize_embeddings,
        }

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("hnsw_space", None)
        return data


_SPECS = (
    # Legacy models preserve the platform's existing L2/non-normalized behavior.
    EmbeddingSpec(
        key="all-MiniLM-L6-v2",
        hf_model_id="all-MiniLM-L6-v2",
        dimension=384,
        normalize_embeddings=False,
        hnsw_space="l2",
        label="all-MiniLM-L6-v2 (general)",
        license_class="permissive",
    ),
    EmbeddingSpec(
        key="all-mpnet-base-v2",
        hf_model_id="all-mpnet-base-v2",
        dimension=768,
        normalize_embeddings=False,
        hnsw_space="l2",
        label="all-mpnet-base-v2 (general)",
        license_class="permissive",
    ),
    EmbeddingSpec(
        key="NeuML/pubmedbert-base-embeddings",
        hf_model_id="NeuML/pubmedbert-base-embeddings",
        dimension=768,
        normalize_embeddings=True,
        hnsw_space="cosine",
        label="PubMedBERT embeddings (biomedical literature)",
        license_class="Apache-2.0",
        max_sequence_length=512,
    ),
)

_REGISTRY = {spec.key: spec for spec in _SPECS}


def supported_embedding_models() -> list[dict]:
    """Return supported public model metadata in UI display order."""
    return [spec.public_dict() for spec in _SPECS if spec.status == "supported"]


def resolve_embedding_spec(model_key: str | None) -> EmbeddingSpec:
    """Resolve a persisted model key without allowing arbitrary model loading."""
    normalized = (model_key or "all-MiniLM-L6-v2").strip()
    spec = _REGISTRY.get(normalized)
    if spec is None:
        supported = ", ".join(_REGISTRY)
        raise ValueError(
            f"Unsupported embedding model '{normalized}'. Supported models: {supported}"
        )
    return spec


def collection_embedding_spec(collection, *, legacy_default: bool = True) -> EmbeddingSpec:
    """Resolve a collection's persisted embedding contract.

    Collections created before contract v1 have no Chroma metadata.  They are
    treated as the historical all-MiniLM default only for backward-compatible
    retrieval.  New non-default collections must carry explicit metadata.
    """
    metadata = getattr(collection, "metadata", None) or {}
    key = metadata.get("ptm_embedding_model_key")
    if key:
        spec = resolve_embedding_spec(str(key))
        dimension = metadata.get("ptm_embedding_dimension")
        if dimension is not None and int(dimension) != spec.dimension:
            raise ValueError(
                f"Embedding contract dimension mismatch for collection "
                f"'{getattr(collection, 'name', '?')}': metadata={dimension}, "
                f"registry={spec.dimension}"
            )
        normalized = metadata.get("ptm_embedding_normalized")
        if normalized is not None and bool(normalized) != spec.normalize_embeddings:
            raise ValueError(
                f"Embedding normalization mismatch for collection "
                f"'{getattr(collection, 'name', '?')}'"
            )
        return spec
    if legacy_default:
        return resolve_embedding_spec("all-MiniLM-L6-v2")
    raise ValueError(
        f"Collection '{getattr(collection, 'name', '?')}' has no embedding contract; "
        "clone and reindex it before using a non-default embedding model."
    )


@lru_cache(maxsize=4)
def _load_model(model_key: str, device: str | None):
    spec = resolve_embedding_spec(model_key)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - exercised in container startup
        raise RuntimeError(
            "sentence-transformers is required for explicit RAG query embeddings. "
            "Rebuild the API/worker images after adding the embedding dependency."
        ) from exc
    return SentenceTransformer(spec.hf_model_id, device=device)


def encode_texts(
    texts: Sequence[str] | Iterable[str],
    model_key: str,
    *,
    device: str | None = None,
    show_progress_bar: bool = False,
) -> list[list[float]]:
    """Encode text with the registry contract and validate its vector dimension."""
    text_list = list(texts)
    if not text_list:
        return []
    spec = resolve_embedding_spec(model_key)
    model = _load_model(spec.key, device)
    embeddings = model.encode(
        text_list,
        show_progress_bar=show_progress_bar,
        normalize_embeddings=spec.normalize_embeddings,
    )
    vectors = embeddings.tolist()
    if any(len(vector) != spec.dimension for vector in vectors):
        actual = len(vectors[0]) if vectors else 0
        raise RuntimeError(
            f"Embedding dimension mismatch for '{spec.key}': expected {spec.dimension}, got {actual}"
        )
    return vectors
