"""
PubMed/NCBI E-utilities Tool — multi-tier PTM literature search.
Ported from ptm-rag-backend/src/pubmedClient.ts.

Features:
  - Multi-tier search strategy (general → context-enhanced → alias)
  - Europe PMC fallback
  - Relevance scoring
  - Position variant generation
  - Article detail fetching
"""

import asyncio
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger("mcp-server.pubmed")

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
MYGENE_BASE = "https://mygene.info/v3"

NCBI_EMAIL = os.getenv("NCBI_EMAIL", "user@example.com")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_TOOL = os.getenv("NCBI_TOOL", "PTM-Platform")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_ptm_pubmed(
    gene: str,
    position: str,
    ptm_type: str = "Phosphorylation",
    context_keywords: list[str] | None = None,
    max_results: int = 15,
    redis=None,
) -> dict:
    """Multi-tier PubMed search for a specific PTM site.

    Results are cached permanently in Redis (no TTL) so that once fetched,
    articles are always available without re-querying PubMed.
    """
    cache_key = f"pubmed:search:{gene}:{position}:{ptm_type}"
    if redis:
        import json
        cached = await redis.get(cache_key)
        if cached:
            logger.debug(f"PubMed search cache hit: {cache_key}")
            return json.loads(cached)

    result = await _multi_tier_search(gene, position, ptm_type, context_keywords or [], max_results)

    if redis and result.get("articles"):
        import json
        # Permanent cache — articles don't change once published
        await redis.set(cache_key, json.dumps(result))
        logger.info(f"PubMed search cached permanently: {cache_key} ({result.get('total_found', 0)} articles)")

    return result


async def fetch_articles_by_pmids(pmids: list[str], redis=None) -> dict:
    """Fetch article details by PMIDs.

    Individual articles are cached permanently by PMID for maximum reuse.
    """
    if not pmids:
        return {"articles": []}

    # Check per-article cache first
    cached_articles = []
    uncached_pmids = []
    if redis:
        import json
        for pmid in pmids:
            article_key = f"pubmed:article:{pmid}"
            cached = await redis.get(article_key)
            if cached:
                cached_articles.append(json.loads(cached))
            else:
                uncached_pmids.append(pmid)
    else:
        uncached_pmids = list(pmids)

    # Fetch only uncached articles
    new_articles = []
    if uncached_pmids:
        new_articles = await _fetch_article_details(uncached_pmids)
        # Cache each article individually and permanently
        if redis and new_articles:
            import json
            for article in new_articles:
                pmid = article.get("pmid")
                if pmid:
                    article_key = f"pubmed:article:{pmid}"
                    await redis.set(article_key, json.dumps(article))
            logger.info(f"Cached {len(new_articles)} new articles permanently")

    all_articles = cached_articles + new_articles
    return {"articles": all_articles}


async def get_gene_aliases(gene: str, redis=None) -> dict:
    """Get gene aliases from MyGene.info API.

    Gene aliases are stable data — cached permanently.
    """
    cache_key = f"pubmed:aliases:{gene}"
    if redis:
        import json
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    aliases = await _fetch_gene_aliases(gene)
    result = {"gene": gene, "aliases": aliases}

    if redis and aliases:
        import json
        await redis.set(cache_key, json.dumps(result))

    return result


# ---------------------------------------------------------------------------
# Multi-tier search
# ---------------------------------------------------------------------------

async def _multi_tier_search(
    gene: str, position: str, ptm_type: str,
    context_keywords: list[str], max_results: int,
) -> dict:
    variants = _generate_position_variants(position)
    aliases_data = await _fetch_gene_aliases(gene)
    all_names = [gene] + aliases_data

    # Tier 1: General phosphorylation query
    tier1_query = _build_general_query(gene, variants, ptm_type)
    tier1_pmids = await _esearch(tier1_query, max_results)

    # Tier 2: Context-enhanced query (if context keywords available)
    tier2_pmids = []
    if context_keywords:
        tier2_query = _build_context_query(gene, variants, ptm_type, context_keywords)
        tier2_pmids = await _esearch(tier2_query, max_results)

    # Tier 3: Alias query (if aliases exist and results are low)
    tier3_pmids = []
    if len(all_names) > 1 and len(tier1_pmids) < 3:
        tier3_query = _build_alias_query(all_names, variants, ptm_type)
        tier3_pmids = await _esearch(tier3_query, max_results)

    # Europe PMC fallback
    epmc_pmids = []
    if len(tier1_pmids) + len(tier2_pmids) < 3:
        epmc_pmids = await _search_europe_pmc(gene, position, ptm_type, max_results)

    # Merge and deduplicate
    seen = set()
    merged = []
    for pmid in tier1_pmids + tier2_pmids + tier3_pmids + epmc_pmids:
        if pmid not in seen:
            seen.add(pmid)
            merged.append(pmid)

    merged = merged[:max_results]

    # Fetch article details
    articles = await _fetch_article_details(merged) if merged else []

    # Score relevance
    scored = []
    for article in articles:
        score = _calculate_relevance(article, gene, position, ptm_type, context_keywords, all_names)
        article["relevance_score"] = score
        scored.append(article)

    scored.sort(key=lambda a: a["relevance_score"], reverse=True)

    return {
        "gene": gene,
        "position": position,
        "ptm_type": ptm_type,
        "total_found": len(scored),
        "search_tiers_used": {
            "tier1_general": len(tier1_pmids),
            "tier2_context": len(tier2_pmids),
            "tier3_alias": len(tier3_pmids),
            "europe_pmc": len(epmc_pmids),
        },
        "articles": scored,
    }


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

def _build_general_query(gene: str, variants: list[str], ptm_type: str) -> str:
    ptm_terms = {
        "Phosphorylation": "phosphorylation",
        "Ubiquitylation": "ubiquitination OR ubiquitylation",
        "Acetylation": "acetylation",
    }
    ptm_term = ptm_terms.get(ptm_type, "post-translational modification")
    variant_str = " OR ".join(f'"{v}"' for v in variants[:5])
    return f'({gene}[Title/Abstract]) AND ({ptm_term}[Title/Abstract]) AND ({variant_str})'


def _build_context_query(gene: str, variants: list[str], ptm_type: str, keywords: list[str]) -> str:
    base = _build_general_query(gene, variants, ptm_type)
    kw_str = " OR ".join(f'"{k}"' for k in keywords[:3])
    return f"({base}) AND ({kw_str})"


def _build_alias_query(aliases: list[str], variants: list[str], ptm_type: str) -> str:
    ptm_terms = {
        "Phosphorylation": "phosphorylation",
        "Ubiquitylation": "ubiquitination",
    }
    ptm_term = ptm_terms.get(ptm_type, "post-translational modification")
    gene_str = " OR ".join(f'"{a}"[Title/Abstract]' for a in aliases[:5])
    variant_str = " OR ".join(f'"{v}"' for v in variants[:3])
    return f"({gene_str}) AND ({ptm_term}[Title/Abstract]) AND ({variant_str})"


def _generate_position_variants(position: str) -> list[str]:
    """Generate position search variants: S165 → Ser165, pS165, etc."""
    if not position or position in ("Unknown", "N-term", "N/A"):
        return [position] if position else []

    residue_map = {"S": "Ser", "T": "Thr", "Y": "Tyr", "K": "Lys"}

    m = re.match(r"([A-Z])(\d+)", position)
    if not m:
        return [position]

    aa, num = m.group(1), m.group(2)
    full_name = residue_map.get(aa, aa)

    return [
        position,                    # S165
        f"{full_name}{num}",         # Ser165
        f"{full_name}-{num}",        # Ser-165
        f"{full_name} {num}",        # Ser 165
        f"p{aa}{num}",              # pS165
        f"phospho-{aa}{num}",       # phospho-S165
    ]


# ---------------------------------------------------------------------------
# NCBI E-utilities
# ---------------------------------------------------------------------------

async def _esearch(query: str, max_results: int = 15) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "xml",
        "sort": "relevance",
        "email": NCBI_EMAIL,
        "tool": NCBI_TOOL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{NCBI_BASE}/esearch.fcgi", params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            return [el.text for el in root.findall(".//Id") if el.text]
    except Exception as e:
        logger.warning(f"PubMed esearch failed: {e}")
        return []


async def _fetch_article_details(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids[:50]),
        "retmode": "xml",
        "email": NCBI_EMAIL,
        "tool": NCBI_TOOL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(f"{NCBI_BASE}/efetch.fcgi", params=params)
            resp.raise_for_status()
            return _parse_pubmed_xml(resp.text)
    except Exception as e:
        logger.warning(f"PubMed efetch failed: {e}")
        return []


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    articles = []
    try:
        root = ET.fromstring(xml_text)
        for pa in root.findall(".//PubmedArticle"):
            article = _parse_single_article(pa)
            if article:
                articles.append(article)
    except ET.ParseError as e:
        logger.warning(f"XML parse error: {e}")
    return articles


def _parse_single_article(pa) -> dict | None:
    try:
        mc = pa.find(".//MedlineCitation")
        if mc is None:
            return None

        pmid_el = mc.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        article_el = mc.find("Article")
        if article_el is None:
            return None

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

        # Authors
        authors = []
        for author in article_el.findall(".//Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {fore}".strip())

        # Date
        pub_date = ""
        pd_el = article_el.find(".//PubDate")
        if pd_el is not None:
            year = pd_el.findtext("Year", "")
            month = pd_el.findtext("Month", "")
            pub_date = f"{year} {month}".strip()

        # DOI
        doi = ""
        for aid in article_el.findall(".//ArticleId"):
            if aid.get("IdType") == "doi":
                doi = aid.text or ""
                break
        if not doi:
            pd_el2 = pa.find(".//PubmedData")
            if pd_el2:
                for aid in pd_el2.findall(".//ArticleId"):
                    if aid.get("IdType") == "doi":
                        doi = aid.text or ""
                        break

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors[:5],
            "journal": journal,
            "pub_date": pub_date,
            "doi": doi,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Europe PMC fallback
# ---------------------------------------------------------------------------

async def _search_europe_pmc(gene: str, position: str, ptm_type: str, max_results: int) -> list[str]:
    ptm_terms = {"Phosphorylation": "phosphorylation", "Ubiquitylation": "ubiquitination"}
    ptm = ptm_terms.get(ptm_type, "modification")
    query = f'"{gene}" AND "{ptm}" AND ("{position}")'

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{EUROPEPMC_BASE}/search",
                params={"query": query, "format": "json", "resultType": "lite", "pageSize": str(max_results)},
            )
            resp.raise_for_status()
            data = resp.json()
            pmids = []
            for r in data.get("resultList", {}).get("result", []):
                pmid = r.get("pmid")
                if pmid:
                    pmids.append(str(pmid))
            return pmids
    except Exception as e:
        logger.warning(f"Europe PMC search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------

def _calculate_relevance(
    article: dict, gene: str, position: str, ptm_type: str,
    context_keywords: list[str], aliases: list[str],
) -> int:
    score = 0
    title = (article.get("title") or "").lower()
    abstract = (article.get("abstract") or "").lower()

    gene_lower = gene.lower()
    for name in [gene_lower] + [a.lower() for a in aliases]:
        if name in title:
            score += 30
            break
        elif name in abstract:
            score += 20
            break

    pos_lower = position.lower() if position else ""
    if pos_lower and pos_lower != "unknown":
        if pos_lower in title:
            score += 25
        elif pos_lower in abstract:
            score += 15

    ptm_keywords = ["phosphorylation", "phospho", "kinase", "ubiquitin", "ubiquitylation"]
    for kw in ptm_keywords:
        if kw in title:
            score += 10
            break
        elif kw in abstract:
            score += 5
            break

    if context_keywords:
        for kw in context_keywords:
            if kw.lower() in title:
                score += 5
            elif kw.lower() in abstract:
                score += 2

    return min(max(score, 0), 100)


# ---------------------------------------------------------------------------
# Gene aliases
# ---------------------------------------------------------------------------

async def _fetch_gene_aliases(gene: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{MYGENE_BASE}/query",
                params={"q": gene, "fields": "alias,symbol", "size": "1"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            hits = data.get("hits", [])
            if not hits:
                return []
            hit = hits[0]
            aliases = hit.get("alias", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            symbol = hit.get("symbol", "")
            if symbol and symbol != gene:
                aliases.append(symbol)
            return [a for a in aliases if a and a != gene][:5]
    except Exception:
        return []
