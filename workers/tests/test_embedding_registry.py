from ptm_shared.embedding_registry import (
    collection_embedding_spec,
    resolve_embedding_spec,
    supported_embedding_models,
)


class DummyCollection:
    def __init__(self, name: str, metadata: dict | None):
        self.name = name
        self.metadata = metadata


def test_pubmedbert_registry_contract_is_supported_and_768d():
    spec = resolve_embedding_spec("NeuML/pubmedbert-base-embeddings")

    assert spec.dimension == 768
    assert spec.normalize_embeddings is True
    assert spec.hnsw_space == "cosine"
    assert spec.license_class == "Apache-2.0"
    assert any(model["key"] == spec.key for model in supported_embedding_models())


def test_collection_contract_rejects_registry_dimension_mismatch():
    spec = resolve_embedding_spec("NeuML/pubmedbert-base-embeddings")
    metadata = spec.chromadb_metadata()
    metadata["ptm_embedding_dimension"] = 384

    try:
        collection_embedding_spec(DummyCollection("pubmedbert_bad", metadata))
    except ValueError as exc:
        assert "dimension mismatch" in str(exc)
    else:
        raise AssertionError("Expected incompatible collection metadata to be rejected")


def test_legacy_collection_defaults_to_historical_minilm_contract():
    spec = collection_embedding_spec(DummyCollection("legacy_collection", {}))

    assert spec.key == "all-MiniLM-L6-v2"
    assert spec.dimension == 384
