"""Publication manifest validation for traceable collection reindexing."""

import json

import pytest

from common.document_indexer import DocumentIndexer, load_publication_manifest


def test_publication_manifest_requires_title_and_stable_identifier(tmp_path):
    path = tmp_path / "publication_manifest.json"
    path.write_text(json.dumps({"documents": [{"path": "paper.pdf", "title": "Paper", "pmid": "12345678"}]}), encoding="utf-8")
    docs = load_publication_manifest(str(path))
    assert docs[0]["pmid"] == "12345678"

    path.write_text(json.dumps({"documents": [{"path": "paper.pdf", "title": "Paper"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="PMID or DOI"):
        load_publication_manifest(str(path))


def test_publication_manifest_reindex_forwards_identity_metadata(tmp_path, monkeypatch):
    source = tmp_path / "paper.md"
    source.write_text("# Example paper\n", encoding="utf-8")
    manifest = tmp_path / "publication_manifest.json"
    manifest.write_text(json.dumps({"documents": [{
        "path": "paper.md", "title": "Identified paper", "doi": "10.1000/example.1",
        "authors": "Author A", "journal": "Journal", "year": "2024",
    }]}), encoding="utf-8")
    captured = []

    def fake_index_document(file_path, collection_name, extra_metadata=None, progress_callback=None):
        captured.append((file_path, collection_name, extra_metadata))
        return {"status": "success", "chunk_count": 3}

    indexer = DocumentIndexer.__new__(DocumentIndexer)
    monkeypatch.setattr(indexer, "index_document", fake_index_document)
    result = indexer.index_publication_manifest(str(manifest), "selected-collection")
    assert result["total_chunks"] == 3
    assert captured[0][2]["title"] == "Identified paper"
    assert captured[0][2]["doi"] == "10.1000/example.1"
