import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, Query
from pydantic import BaseModel

from .tools import (
    query_uniprot, query_kegg, query_stringdb, query_interpro,
    search_ptm_pubmed, fetch_articles_by_pmids, get_gene_aliases,
    list_cached_articles, get_cached_article, delete_cached_article,
    clear_all_cached_articles, get_cache_stats,
    # v2: External API clients (ported from ptm-rag-backend)
    query_iptmnet,
    fetch_fulltext_by_pmid, fetch_fulltext_batch,
    query_hpa, query_gtex, query_biogrid,
    query_kea3,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ptm-mcp-server")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/3")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    logger.info("MCP Server (Bio-Database Gateway) started")
    yield
    await app.state.redis.close()
    logger.info("MCP Server shutting down")


app = FastAPI(
    title="PTM MCP Server",
    description="Bio-Database Gateway — unified external API access with caching",
    version="0.3.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health & Discovery
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ptm-mcp-server"}


@app.get("/tools")
async def list_tools():
    return {
        "tools": [
            {"name": "query_uniprot", "description": "Get UniProt protein info (GO, localization, function)", "status": "active"},
            {"name": "query_kegg", "description": "Get KEGG pathway information", "status": "active"},
            {"name": "query_stringdb", "description": "Get STRING-DB protein interactions", "status": "active"},
            {"name": "query_interpro", "description": "Get InterPro domain annotations", "status": "active"},
            {"name": "search_ptm_pubmed", "description": "Multi-tier PubMed search for PTM literature", "status": "active"},
            {"name": "fetch_articles", "description": "Fetch PubMed article details by PMIDs", "status": "active"},
            {"name": "get_gene_aliases", "description": "Get gene aliases from MyGene.info", "status": "active"},
            # v2 tools
            {"name": "query_iptmnet", "description": "iPTMnet PTM novelty assessment via web scraping", "status": "active"},
            {"name": "fetch_fulltext", "description": "Fetch PMC/EuropePMC full-text by PMID", "status": "active"},
            {"name": "query_hpa", "description": "Human Protein Atlas subcellular localization", "status": "active"},
            {"name": "query_gtex", "description": "GTEx tissue expression data", "status": "active"},
            {"name": "query_biogrid", "description": "BioGRID protein-protein interactions", "status": "active"},
            {"name": "query_kea3", "description": "KEA3 kinase enrichment analysis", "status": "active"},
        ]
    }


# ---------------------------------------------------------------------------
# UniProt
# ---------------------------------------------------------------------------

@app.get("/tools/uniprot/{protein_id}")
async def tool_uniprot(protein_id: str):
    return await query_uniprot(protein_id, redis=app.state.redis)


class UniprotBatchRequest(BaseModel):
    protein_ids: list[str]


@app.post("/tools/uniprot/batch")
async def tool_uniprot_batch(req: UniprotBatchRequest):
    import asyncio
    sem = asyncio.Semaphore(5)

    async def _fetch(pid):
        async with sem:
            return await query_uniprot(pid, redis=app.state.redis)

    results = await asyncio.gather(*[_fetch(pid) for pid in req.protein_ids])
    return {"results": results}


# ---------------------------------------------------------------------------
# KEGG
# ---------------------------------------------------------------------------

@app.get("/tools/kegg/{gene_name}")
async def tool_kegg(
    gene_name: str,
    organism: str = Query("mmu", description="KEGG organism code"),
):
    return await query_kegg(gene_name, organism=organism, redis=app.state.redis)


class KeggBatchRequest(BaseModel):
    gene_names: list[str]
    organism: str = "mmu"


@app.post("/tools/kegg/batch")
async def tool_kegg_batch(req: KeggBatchRequest):
    import asyncio
    sem = asyncio.Semaphore(3)

    async def _fetch(g):
        async with sem:
            return await query_kegg(g, organism=req.organism, redis=app.state.redis)

    results = await asyncio.gather(*[_fetch(g) for g in req.gene_names])
    return {"results": results}


# ---------------------------------------------------------------------------
# STRING-DB
# ---------------------------------------------------------------------------

@app.get("/tools/stringdb/{gene_name}")
async def tool_stringdb(
    gene_name: str,
    species: str = Query("10090", description="NCBI taxonomy ID"),
):
    return await query_stringdb(gene_name, species=species, redis=app.state.redis)


class StringBatchRequest(BaseModel):
    gene_names: list[str]
    species: str = "10090"


@app.post("/tools/stringdb/batch")
async def tool_stringdb_batch(req: StringBatchRequest):
    import asyncio
    sem = asyncio.Semaphore(5)

    async def _fetch(g):
        async with sem:
            return await query_stringdb(g, species=req.species, redis=app.state.redis)

    results = await asyncio.gather(*[_fetch(g) for g in req.gene_names])
    return {"results": results}


# ---------------------------------------------------------------------------
# InterPro
# ---------------------------------------------------------------------------

@app.get("/tools/interpro/{protein_id}")
async def tool_interpro(protein_id: str):
    return await query_interpro(protein_id, redis=app.state.redis)


class InterproBatchRequest(BaseModel):
    protein_ids: list[str]


@app.post("/tools/interpro/batch")
async def tool_interpro_batch(req: InterproBatchRequest):
    import asyncio
    sem = asyncio.Semaphore(4)

    async def _fetch(pid):
        async with sem:
            return await query_interpro(pid, redis=app.state.redis)

    results = await asyncio.gather(*[_fetch(pid) for pid in req.protein_ids])
    return {"results": results}


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

class PubMedSearchRequest(BaseModel):
    gene: str
    position: str
    ptm_type: str = "Phosphorylation"
    context_keywords: list[str] = []
    max_results: int = 15


@app.post("/tools/pubmed/search")
async def tool_pubmed_search(req: PubMedSearchRequest):
    return await search_ptm_pubmed(
        gene=req.gene, position=req.position, ptm_type=req.ptm_type,
        context_keywords=req.context_keywords, max_results=req.max_results,
        redis=app.state.redis,
    )


class PubMedFetchRequest(BaseModel):
    pmids: list[str]


@app.post("/tools/pubmed/fetch")
async def tool_pubmed_fetch(req: PubMedFetchRequest):
    return await fetch_articles_by_pmids(req.pmids, redis=app.state.redis)


@app.get("/tools/pubmed/aliases/{gene_name}")
async def tool_gene_aliases(gene_name: str):
    return await get_gene_aliases(gene_name, redis=app.state.redis)


class PubMedBatchSearchRequest(BaseModel):
    queries: list[PubMedSearchRequest]


@app.post("/tools/pubmed/search/batch")
async def tool_pubmed_search_batch(req: PubMedBatchSearchRequest):
    import asyncio
    sem = asyncio.Semaphore(3)

    async def _search(q):
        async with sem:
            return await search_ptm_pubmed(
                gene=q.gene, position=q.position, ptm_type=q.ptm_type,
                context_keywords=q.context_keywords, max_results=q.max_results,
                redis=app.state.redis,
            )

    results = await asyncio.gather(*[_search(q) for q in req.queries])
    return {"results": results}


# ---------------------------------------------------------------------------
# iPTMnet — PTM novelty assessment
# ---------------------------------------------------------------------------

class IPTMnetRequest(BaseModel):
    gene: str
    position: str = ""
    organism: str = "Mouse"


@app.post("/tools/iptmnet/search")
async def tool_iptmnet_search(req: IPTMnetRequest):
    return await query_iptmnet(
        gene=req.gene, position=req.position,
        organism=req.organism, redis=app.state.redis,
    )


@app.get("/tools/iptmnet/{gene}")
async def tool_iptmnet_get(
    gene: str,
    position: str = Query("", description="PTM position e.g. S79"),
    organism: str = Query("Mouse", description="Organism name"),
):
    return await query_iptmnet(
        gene=gene, position=position,
        organism=organism, redis=app.state.redis,
    )


# ---------------------------------------------------------------------------
# PMC Full-Text
# ---------------------------------------------------------------------------

@app.get("/tools/pmc/fulltext/{pmid}")
async def tool_pmc_fulltext(pmid: str):
    return await fetch_fulltext_by_pmid(pmid, redis=app.state.redis)


class PMCBatchRequest(BaseModel):
    pmids: list[str]


@app.post("/tools/pmc/fulltext/batch")
async def tool_pmc_fulltext_batch(req: PMCBatchRequest):
    return {"results": await fetch_fulltext_batch(req.pmids, redis=app.state.redis)}


# ---------------------------------------------------------------------------
# HPA — Human Protein Atlas
# ---------------------------------------------------------------------------

@app.get("/tools/hpa/{gene_name}")
async def tool_hpa(gene_name: str):
    return await query_hpa(gene_name, redis=app.state.redis)


# ---------------------------------------------------------------------------
# GTEx — Tissue Expression
# ---------------------------------------------------------------------------

@app.get("/tools/gtex/{gene_name}")
async def tool_gtex(gene_name: str):
    return await query_gtex(gene_name, redis=app.state.redis)


# ---------------------------------------------------------------------------
# BioGRID — Protein-Protein Interactions
# ---------------------------------------------------------------------------

@app.get("/tools/biogrid/{gene_name}")
async def tool_biogrid(
    gene_name: str,
    organism: int = Query(10090, description="NCBI taxonomy ID (10090=mouse, 9606=human)"),
):
    return await query_biogrid(gene_name, organism=organism, redis=app.state.redis)


# ---------------------------------------------------------------------------
# KEA3 — Kinase Enrichment Analysis
# ---------------------------------------------------------------------------

class KEA3Request(BaseModel):
    gene_list: list[str]
    top_n: int = 10


@app.post("/tools/kea3/enrich")
async def tool_kea3_enrich(req: KEA3Request):
    return await query_kea3(
        gene_list=req.gene_list, top_n=req.top_n,
        redis=app.state.redis,
    )


# ===========================================================================
# Article Cache Management Endpoints
# ===========================================================================

@app.get("/cache/articles")
async def cache_list_articles(
    cursor: int = Query(0, ge=0),
    count: int = Query(50, ge=1, le=200),
    search: str = Query(""),
):
    """List cached PubMed articles with optional text search."""
    return await list_cached_articles(
        app.state.redis, cursor=cursor, count=count, search=search,
    )


@app.get("/cache/articles/stats")
async def cache_article_stats():
    """Get article cache statistics."""
    return await get_cache_stats(app.state.redis)


@app.get("/cache/articles/{pmid}")
async def cache_get_article(pmid: str):
    """Get a single cached article by PMID."""
    article = await get_cached_article(app.state.redis, pmid)
    if article is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Article {pmid} not found in cache")
    return article


@app.delete("/cache/articles/{pmid}")
async def cache_delete_article(pmid: str):
    """Delete a single cached article by PMID."""
    deleted = await delete_cached_article(app.state.redis, pmid)
    return {"deleted": deleted, "pmid": pmid}


@app.delete("/cache/articles")
async def cache_clear_all_articles():
    """Clear all cached articles and search results."""
    count = await clear_all_cached_articles(app.state.redis)
    return {"deleted_count": count}
