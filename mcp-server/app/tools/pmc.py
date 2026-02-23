"""
PMC Full-Text Client — fetch full-text articles from PubMed Central.

Ported from ptm-rag-backend/src/pmcClient.ts + pmcFullTextFetcher.ts (v6.2.1).

Features:
  - PMID → PMCID resolution via NCBI eLink
  - Full-text fetch via efetch XML
  - Europe PMC fallback
  - Exponential backoff retry
  - Redis caching
"""

import asyncio
import logging
import os
import re
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "ptm-platform@example.com")
NCBI_TOOL = os.getenv("NCBI_TOOL", "PTM-Platform")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")


async def _fetch_with_retry(
    session: aiohttp.ClientSession, url: str, max_retries: int = 5, timeout: int = 20,
) -> Optional[str]:
    """Fetch URL with exponential backoff."""
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.text()
                if resp.status == 429 or resp.status >= 500:
                    delay = 2 ** (attempt - 1)
                    logger.warning(f"PMC retry {attempt}/{max_retries} after {delay}s (status {resp.status})")
                    await asyncio.sleep(delay)
                    continue
                return None
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            if attempt < max_retries:
                delay = 2 ** (attempt - 1)
                logger.warning(f"PMC retry {attempt}/{max_retries} after {delay}s ({e})")
                await asyncio.sleep(delay)
            else:
                logger.error(f"PMC all {max_retries} attempts failed: {e}")
    return None


async def check_pmc_availability(
    session: aiohttp.ClientSession, pmid: str,
) -> Optional[str]:
    """Check if a PMID has full-text in PMC. Returns PMCID or None."""
    params = f"dbfrom=pubmed&db=pmc&id={pmid}&retmode=json"
    params += f"&email={NCBI_EMAIL}&tool={NCBI_TOOL}"
    if NCBI_API_KEY:
        params += f"&api_key={NCBI_API_KEY}"

    url = f"{EUTILS_BASE}/elink.fcgi?{params}"
    text = await _fetch_with_retry(session, url)
    if not text:
        return None

    try:
        import json
        data = json.loads(text)
        linksets = data.get("linksets", [{}])[0].get("linksetdbs", [])
        for ls in linksets:
            if ls.get("dbto") == "pmc" and ls.get("links"):
                pmcid = str(ls["links"][0])
                logger.info(f"PMID {pmid} → PMC{pmcid}")
                return pmcid
    except Exception:
        pass
    return None


async def fetch_pmc_fulltext(
    session: aiohttp.ClientSession, pmcid: str,
) -> Optional[str]:
    """Fetch full-text XML from PMC and extract body text."""
    params = f"db=pmc&id={pmcid}&rettype=xml&retmode=xml"
    params += f"&email={NCBI_EMAIL}&tool={NCBI_TOOL}"
    if NCBI_API_KEY:
        params += f"&api_key={NCBI_API_KEY}"

    url = f"{EUTILS_BASE}/efetch.fcgi?{params}"
    xml_text = await _fetch_with_retry(session, url, timeout=30)
    if not xml_text or len(xml_text) < 1000:
        return None

    # Extract body text from XML
    body_match = re.search(r"<body[^>]*>(.*?)</body>", xml_text, re.DOTALL)
    if body_match:
        text = re.sub(r"<[^>]+>", " ", body_match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 500:
            return text

    # Fallback: strip all tags
    text = re.sub(r"<[^>]+>", " ", xml_text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) > 500 else None


async def fetch_europe_pmc_fulltext(
    session: aiohttp.ClientSession, pmid: str,
) -> Optional[str]:
    """Fetch full-text from Europe PMC as fallback."""
    url = f"{EUROPE_PMC_BASE}/{pmid}/fullTextXML"
    xml_text = await _fetch_with_retry(session, url, timeout=30)
    if not xml_text or len(xml_text) < 1000 or "<error>" in xml_text.lower():
        return None

    text = re.sub(r"<[^>]+>", " ", xml_text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) > 500 else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_fulltext_by_pmid(pmid: str, redis=None) -> dict:
    """
    Fetch full-text for a PMID. Tries PMC first, then Europe PMC.

    Returns dict with keys: pmid, pmcid, has_fulltext, fulltext, source, char_count.
    """
    cache_key = f"pmc_fulltext:{pmid}"
    if redis:
        try:
            import json
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    result: Dict = {
        "pmid": pmid,
        "pmcid": None,
        "has_fulltext": False,
        "fulltext": None,
        "source": None,
        "char_count": 0,
    }

    async with aiohttp.ClientSession() as session:
        # Strategy 1: PMC via NCBI
        pmcid = await check_pmc_availability(session, pmid)
        if pmcid:
            result["pmcid"] = f"PMC{pmcid}"
            text = await fetch_pmc_fulltext(session, pmcid)
            if text:
                result["has_fulltext"] = True
                result["fulltext"] = text
                result["source"] = "pmc"
                result["char_count"] = len(text)

        # Strategy 2: Europe PMC fallback
        if not result["has_fulltext"]:
            text = await fetch_europe_pmc_fulltext(session, pmid)
            if text:
                result["has_fulltext"] = True
                result["fulltext"] = text
                result["source"] = "europe_pmc"
                result["char_count"] = len(text)

    if redis and result["has_fulltext"]:
        try:
            import json
            await redis.set(cache_key, json.dumps(result))  # permanent cache
        except Exception:
            pass

    return result


async def fetch_fulltext_batch(pmids: List[str], redis=None) -> List[dict]:
    """Fetch full-text for multiple PMIDs with rate limiting."""
    results = []
    sem = asyncio.Semaphore(3)

    async def _fetch(pmid: str):
        async with sem:
            r = await fetch_fulltext_by_pmid(pmid, redis=redis)
            await asyncio.sleep(0.5)  # rate limit
            return r

    tasks = [_fetch(pmid) for pmid in pmids]
    results = await asyncio.gather(*tasks)
    return list(results)
