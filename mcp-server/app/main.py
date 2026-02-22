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
    version="0.2.0",
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
