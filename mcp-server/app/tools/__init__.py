from .uniprot import query_uniprot
from .kegg import query_kegg
from .stringdb import query_stringdb
from .interpro import query_interpro
from .pubmed import search_ptm_pubmed, fetch_articles_by_pmids, get_gene_aliases
from .iptmnet import query_iptmnet
from .pmc import fetch_fulltext_by_pmid, fetch_fulltext_batch
from .expression import query_hpa, query_gtex, query_biogrid
from .kea3 import query_kea3

__all__ = [
    "query_uniprot", "query_kegg", "query_stringdb", "query_interpro",
    "search_ptm_pubmed", "fetch_articles_by_pmids", "get_gene_aliases",
    # v2: External API clients (ported from ptm-rag-backend)
    "query_iptmnet",
    "fetch_fulltext_by_pmid", "fetch_fulltext_batch",
    "query_hpa", "query_gtex", "query_biogrid",
    "query_kea3",
]
