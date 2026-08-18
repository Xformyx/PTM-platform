from .uniprot import query_uniprot
from .kegg import query_kegg
from .stringdb import query_stringdb
from .interpro import query_interpro
from .pubmed import (
    search_ptm_pubmed, fetch_articles_by_pmids, get_gene_aliases,
    list_cached_articles, get_cached_article, delete_cached_article,
    clear_all_cached_articles, get_cache_stats,
)
from .iptmnet import query_iptmnet, query_human_ortholog_iptmnet
from .pmc import fetch_fulltext_by_pmid, fetch_fulltext_batch
from .expression import query_hpa, query_gtex, query_biogrid
from .kea3 import query_kea3
from .reactome import query_reactome
from .enrichr import query_enrichr, query_enrichr_string_enrichment
from .string_enrichment import query_string_indirect_pathways
from .tf_targets import query_tf_targets, infer_tf_activity, infer_tf_activity_batch

__all__ = [
    "query_uniprot", "query_kegg", "query_stringdb", "query_interpro",
    "search_ptm_pubmed", "fetch_articles_by_pmids", "get_gene_aliases",
    "list_cached_articles", "get_cached_article", "delete_cached_article",
    "clear_all_cached_articles", "get_cache_stats",
    # v2: External API clients (ported from ptm-rag-backend)
    "query_iptmnet", "query_human_ortholog_iptmnet",
    "fetch_fulltext_by_pmid", "fetch_fulltext_batch",
    "query_hpa", "query_gtex", "query_biogrid",
    "query_kea3",
    # v8.10: 3-Layer Pathway Enrichment
    "query_reactome",
    "query_enrichr", "query_enrichr_string_enrichment",
    "query_string_indirect_pathways",
    # v11.8: TF Activity Inference (DoRothEA + TRRUST)
    "query_tf_targets", "infer_tf_activity", "infer_tf_activity_batch",
]
