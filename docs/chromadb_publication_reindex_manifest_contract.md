# Publication-Level ChromaDB Reindex Manifest Contract

## Purpose

This contract defines the minimum metadata required to reindex a selected literature collection for a citation-complete PTM-Vector Report. A collection name, bundle label, or generic review heading is **not** a bibliographic identity and must never be rendered as a reference.

## Manifest

Create `publication_manifest.json` beside the source documents.

```json
{
  "documents": [
    {
      "path": "papers/example_article.pdf",
      "title": "Full publication title",
      "pmid": "12345678",
      "authors": "Surname AB, Surname CD",
      "journal": "Journal Name",
      "year": "2024"
    },
    {
      "path": "papers/another_article.md",
      "title": "Another full publication title",
      "doi": "10.1000/example.1"
    }
  ]
}
```

Every entry requires `path`, `title`, and at least one stable identifier: `pmid` or `doi`. The optional author, journal, and year fields improve the final bibliography but do not replace the identifier requirement.

## Reindex rules

Use `DocumentIndexer.index_publication_manifest(manifest_path, collection_name)` on the RAG worker. It indexes only manifest-declared sources and attaches the publication metadata to every Chroma chunk. Reindex into the actual selected collection only after confirming its embedding contract; do not overwrite an incompatible collection. Rebuild the selected collection before regenerating the Report.

For Celery-based deployment, dispatch `rag_enrichment.document_tasks.index_publication_manifest(collection_id, manifest_path)`. The task obtains the selected collection's embedding contract from `rag_collections`, preserves its collection name, and indexes only validated manifest sources. It does not rerun the Order, preprocessing, Heatmap, or temporal sidecar.

## Report gate

The Report may use literature comparison only when inline stable citation markers resolve to the reindexed article identities. If no markers resolve, the final renderer enters `data_only_review_mode`, withholds external biology/pathway/cascade prose, and reports `blocked_for_review_missing_traceable_references`.
