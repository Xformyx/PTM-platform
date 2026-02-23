#!/usr/bin/env python3
"""
Migrate article cache from ptm-rag-backend (file-based JSON) to ptm-platform (Redis).

Usage:
    # From the ptm-platform project root:
    python3 scripts/migrate_article_cache.py /path/to/ptm-rag-backend/cache/articles

    # Or with custom Redis URL:
    REDIS_URL=redis://localhost:6379/3 python3 scripts/migrate_article_cache.py /path/to/cache/articles

What this script does:
    1. Reads all PMID_*.json files from the old cache directory
    2. For each article, fetches title/abstract/authors/journal from PubMed API
       (since the old cache only stored fullText from PMC)
    3. Stores the fulltext in Redis as pmc:fulltext:{pmcid} (same format as pmc.py)
    4. Stores the article metadata in Redis as pubmed:article:{pmid}
    5. Skips articles that already exist in Redis

Requirements:
    pip install redis httpx
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import redis.asyncio as aioredis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrate-cache")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/3")
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "ptm-platform@example.com")
NCBI_TOOL = "ptm-platform-migration"
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

# Rate limiting: NCBI allows 10 req/sec with API key, 3 without
BATCH_SIZE = 50  # efetch supports up to 200 PMIDs per request
DELAY_BETWEEN_BATCHES = 0.5  # seconds


def parse_pubmed_xml(xml_text: str) -> dict[str, dict]:
    """Parse PubMed efetch XML and return {pmid: article_dict}."""
    articles = {}
    try:
        root = ET.fromstring(xml_text)
        for pa in root.findall(".//PubmedArticle"):
            mc = pa.find(".//MedlineCitation")
            if mc is None:
                continue
            pmid_el = mc.find("PMID")
            pmid = pmid_el.text if pmid_el is not None else ""
            if not pmid:
                continue

            article_el = mc.find("Article")
            if article_el is None:
                continue

            title_el = article_el.find("ArticleTitle")
            title = "".join(title_el.itertext()) if title_el is not None else ""

            abstract_parts = []
            for at in article_el.findall(".//AbstractText"):
                label = at.get("Label", "")
                text = "".join(at.itertext())
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = " ".join(abstract_parts)

            journal_el = article_el.find(".//Title")
            journal = journal_el.text if journal_el is not None else ""

            authors = []
            for author in article_el.findall(".//Author"):
                last = author.findtext("LastName", "")
                fore = author.findtext("ForeName", "")
                if last:
                    authors.append(f"{last} {fore}".strip())

            pub_date = ""
            year = ""
            pd_el = article_el.find(".//PubDate")
            if pd_el is not None:
                year = pd_el.findtext("Year", "")
                month = pd_el.findtext("Month", "")
                pub_date = f"{year} {month}".strip()

            doi = ""
            pd_el2 = pa.find(".//PubmedData")
            if pd_el2:
                for aid in pd_el2.findall(".//ArticleId"):
                    if aid.get("IdType") == "doi":
                        doi = aid.text or ""
                        break

            articles[pmid] = {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors[:5],
                "journal": journal,
                "pub_date": pub_date,
                "year": int(year) if year.isdigit() else None,
                "doi": doi,
            }
    except ET.ParseError as e:
        logger.warning(f"XML parse error: {e}")
    return articles


async def fetch_metadata_batch(pmids: list[str]) -> dict[str, dict]:
    """Fetch article metadata from PubMed for a batch of PMIDs."""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "email": NCBI_EMAIL,
        "tool": NCBI_TOOL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{NCBI_BASE}/efetch.fcgi", params=params)
            resp.raise_for_status()
            return parse_pubmed_xml(resp.text)
    except Exception as e:
        logger.error(f"PubMed efetch failed for batch: {e}")
        return {}


async def migrate(cache_dir: str, dry_run: bool = False):
    """Main migration function."""
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        logger.error(f"Cache directory not found: {cache_dir}")
        sys.exit(1)

    # Find all article files
    files = sorted(cache_path.glob("PMID_*.json"))
    logger.info(f"Found {len(files)} article files in {cache_dir}")

    if not files:
        logger.info("No articles to migrate")
        return

    # Connect to Redis
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await r.ping()
        logger.info(f"Connected to Redis: {REDIS_URL}")
    except Exception as e:
        logger.error(f"Cannot connect to Redis: {e}")
        sys.exit(1)

    # Load all old cache files
    old_articles = {}
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
            pmid = data.get("pmid", "")
            if pmid:
                old_articles[pmid] = data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read {f}: {e}")

    logger.info(f"Loaded {len(old_articles)} articles from files")

    # Check which articles already exist in Redis
    existing_articles = 0
    existing_fulltexts = 0
    to_migrate_pmids = []

    for pmid in old_articles:
        article_exists = await r.exists(f"pubmed:article:{pmid}")
        if article_exists:
            existing_articles += 1
        else:
            to_migrate_pmids.append(pmid)

        # Check fulltext separately
        pmcid = old_articles[pmid].get("pmcid", "")
        if pmcid:
            ft_exists = await r.exists(f"pmc:fulltext:{pmcid}")
            if ft_exists:
                existing_fulltexts += 1

    logger.info(f"Already in Redis: {existing_articles} articles, {existing_fulltexts} fulltexts")
    logger.info(f"To migrate: {len(to_migrate_pmids)} articles")

    if dry_run:
        logger.info("[DRY RUN] Would migrate the above articles. Exiting.")
        await r.aclose()
        return

    if not to_migrate_pmids:
        logger.info("Nothing to migrate — all articles already in Redis")
        await r.aclose()
        return

    # Step 1: Fetch metadata from PubMed API in batches
    logger.info("Step 1: Fetching article metadata from PubMed API...")
    metadata_map = {}
    batches = [to_migrate_pmids[i:i + BATCH_SIZE] for i in range(0, len(to_migrate_pmids), BATCH_SIZE)]

    for i, batch in enumerate(batches):
        logger.info(f"  Batch {i + 1}/{len(batches)} ({len(batch)} PMIDs)")
        batch_metadata = await fetch_metadata_batch(batch)
        metadata_map.update(batch_metadata)
        if i < len(batches) - 1:
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    logger.info(f"  Fetched metadata for {len(metadata_map)} articles")

    # Step 2: Store in Redis
    logger.info("Step 2: Storing articles in Redis...")
    articles_stored = 0
    fulltexts_stored = 0

    for pmid in to_migrate_pmids:
        old_data = old_articles[pmid]
        pmcid = old_data.get("pmcid", "")
        fulltext = old_data.get("fullText", "")

        # Build article record (metadata from PubMed API + old cache info)
        metadata = metadata_map.get(pmid, {})
        article_record = {
            "pmid": pmid,
            "title": metadata.get("title", ""),
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", []),
            "journal": metadata.get("journal", ""),
            "pub_date": metadata.get("pub_date", old_data.get("pubDate", "")),
            "year": metadata.get("year"),
            "doi": metadata.get("doi", ""),
            "pmcid": pmcid,
            "has_fulltext": bool(fulltext),
            "source": "migration",
            "migrated_at": old_data.get("fetchedAt", ""),
        }

        # Store article metadata
        await r.set(f"pubmed:article:{pmid}", json.dumps(article_record))
        articles_stored += 1

        # Store fulltext if available
        if fulltext and pmcid:
            ft_key = f"pmc:fulltext:{pmcid}"
            if not await r.exists(ft_key):
                await r.set(ft_key, json.dumps({
                    "pmcid": pmcid,
                    "pmid": pmid,
                    "fulltext": fulltext,
                    "source": "migration",
                }))
                fulltexts_stored += 1

        if articles_stored % 100 == 0:
            logger.info(f"  Progress: {articles_stored}/{len(to_migrate_pmids)} articles")

    logger.info(f"Migration complete!")
    logger.info(f"  Articles stored: {articles_stored}")
    logger.info(f"  Fulltexts stored: {fulltexts_stored}")
    logger.info(f"  Metadata not found (title will be empty): {len(to_migrate_pmids) - len(metadata_map)}")

    await r.aclose()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate article cache from ptm-rag-backend to ptm-platform Redis"
    )
    parser.add_argument(
        "cache_dir",
        help="Path to ptm-rag-backend/cache/articles directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check what would be migrated without actually writing to Redis",
    )
    args = parser.parse_args()

    asyncio.run(migrate(args.cache_dir, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
