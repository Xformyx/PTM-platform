"""Collection-local citation identity resolution contracts for R1.0 option A."""

from report_generation.core.rag_retriever import (
    RAGRetriever,
    traceable_reference_from_rag_result,
)
from common.document_indexer import _extract_bibliographic_hints


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _resolver_without_chroma() -> RAGRetriever:
    resolver = object.__new__(RAGRetriever)
    resolver._bibliography_cache = {}
    resolver._bibliography_lookups = 0
    resolver._last_bibliography_request = 0.0
    return resolver


def test_collection_metadata_with_pmid_is_traceable_without_external_lookup():
    reference = traceable_reference_from_rag_result({
        "title": "A collection-local study",
        "metadata": {
            "authors": "A Author",
            "year": "2024",
            "journal": "Journal of PTM",
            "pmid": "12345678",
        },
    })
    assert reference["citation_eligible"] is True
    assert reference["pmid"] == "12345678"
    assert reference["citation_identity_source"] == "collection_metadata"


def test_exact_pubmed_title_lookup_restores_traceable_identity(monkeypatch):
    calls = []

    def fake_get(url, params, timeout, headers):
        calls.append((url, params))
        if url.endswith("esearch.fcgi"):
            return _Response({"esearchresult": {"idlist": ["34567890"]}})
        return _Response({"result": {
            "34567890": {
                "title": "A Title Stored In The Selected Collection",
                "sortfirstauthor": "Evidence Author",
                "pubdate": "2023 Nov 14",
                "fulljournalname": "Evidence Journal",
                "articleids": [{"idtype": "doi", "value": "10.1000/example.1"}],
            },
        }})

    monkeypatch.setattr("report_generation.core.rag_retriever.requests.get", fake_get)
    resolver = _resolver_without_chroma()
    resolved = resolver.resolve_traceable_reference({
        "title": "A Title Stored In The Selected Collection",
        "metadata": {},
    })

    assert resolved["citation_eligible"] is True
    assert resolved["pmid"] == "34567890"
    assert resolved["doi"] == "10.1000/example.1"
    assert resolved["journal"] == "Evidence Journal"
    assert resolved["citation_identity_source"] == "pubmed_exact_title"
    assert len(calls) == 2


def test_ambiguous_or_nonmatching_title_fails_closed(monkeypatch):
    def fake_get(url, params, timeout, headers):
        if url.endswith("esearch.fcgi"):
            return _Response({"esearchresult": {"idlist": ["1", "2"]}})
        return _Response({"result": {
            "1": {"title": "Some Other Article"},
            "2": {"title": "Another Article"},
        }})

    monkeypatch.setattr("report_generation.core.rag_retriever.requests.get", fake_get)
    resolver = _resolver_without_chroma()
    resolved = resolver.resolve_traceable_reference({
        "title": "Selected Collection Item Without Metadata",
        "metadata": {},
    })
    assert resolved["citation_eligible"] is False
    assert resolved["pmid"] == ""


def test_collection_label_cannot_become_a_traceable_reference():
    reference = traceable_reference_from_rag_result({
        "title": "All PTM Articles",
        "metadata": {"collection": "All PTM Articles"},
    })
    assert reference["citation_eligible"] is False
    assert reference["pmid"] == ""
    assert reference["doi"] == ""


def test_legacy_chunk_explicit_title_and_doi_can_restore_identity():
    reference = traceable_reference_from_rag_result({
        "title": "All PTM Articles",
        "metadata": {"collection": "All PTM Articles"},
        "document": "# An Article Title Preserved In The Legacy Chunk\nDOI: 10.1000/legacy.2\n",
    })
    assert reference["citation_eligible"] is True
    assert reference["title"] == "An Article Title Preserved In The Legacy Chunk"
    assert reference["doi"] == "10.1000/legacy.2"


def test_indexer_preserves_explicit_identifier_hints_for_future_reindexing():
    hints = _extract_bibliographic_hints(
        "Article metadata\nPMID: 34567890\nhttps://doi.org/10.1000/example.3\n"
    )
    assert hints == {"pmid": "34567890", "doi": "10.1000/example.3"}
