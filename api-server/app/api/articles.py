"""Article Cache management — proxies to MCP server cache endpoints."""

import logging

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["articles"])

settings = get_settings()
MCP_URL = settings.MCP_SERVER_URL


@router.get("/articles")
async def list_articles(
    cursor: int = Query(0, ge=0),
    count: int = Query(50, ge=1, le=200),
    search: str = Query(""),
):
    """List cached PubMed articles with optional search."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{MCP_URL}/cache/articles",
                params={"cursor": cursor, "count": count, "search": search},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"MCP cache list failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch article cache")


@router.get("/articles/stats")
async def article_stats():
    """Get article cache statistics."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{MCP_URL}/cache/articles/stats")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"MCP cache stats failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch cache stats")


@router.get("/articles/{pmid}")
async def get_article(pmid: str):
    """Get a single cached article by PMID."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{MCP_URL}/cache/articles/{pmid}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Article {pmid} not found")
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.error(f"MCP cache get failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch article")


@router.delete("/articles/{pmid}")
async def delete_article(pmid: str):
    """Delete a single cached article."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(f"{MCP_URL}/cache/articles/{pmid}")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"MCP cache delete failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to delete article")


@router.delete("/articles")
async def clear_all_articles():
    """Clear all cached articles."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(f"{MCP_URL}/cache/articles")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"MCP cache clear failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to clear article cache")
