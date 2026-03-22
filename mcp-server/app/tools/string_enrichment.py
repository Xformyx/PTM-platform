"""STRING-DB Indirect Pathway Inference Tool.

For genes with no/few direct KEGG pathways, this tool:
1. Gets top STRING interaction partners
2. Runs KEGG enrichment on the gene + its partners
3. Returns inferred signaling pathways with confidence scores

This is Layer 3 of the 3-Layer Pathway Enrichment strategy.
"""

import asyncio
import logging
from typing import List, Optional

import httpx

logger = logging.getLogger("mcp-server.string_enrichment")

STRING_BASE = "https://string-db.org/api/json"


async def query_string_indirect_pathways(
    gene_name: str,
    species: int = 10090,
    top_partners: int = 10,
    redis=None,
    timeout: float = 25.0,
) -> dict:
    """
    Infer signaling pathways for a gene via its STRING interaction partners.

    Strategy:
      1. Get top N STRING interaction partners
      2. Run STRING functional enrichment on gene + partners
      3. Filter for signaling-related KEGG pathways
      4. Tag whether the target gene itself appears in each enriched pathway

    Args:
        gene_name: Gene symbol
        species: NCBI taxonomy ID (10090=mouse)
        top_partners: Number of STRING partners to include
        redis: Optional Redis connection
        timeout: HTTP timeout

    Returns:
        Dict with inferred pathways, partner list, and confidence info.
    """
    cache_key = f"string_indirect:{gene_name}:{species}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

    result = await _infer_pathways(gene_name, species, top_partners, timeout)

    if redis:
        import json
        await redis.set(cache_key, json.dumps(result), ex=86400)

    return result


async def _infer_pathways(
    gene_name: str, species: int, top_partners: int, timeout: float
) -> dict:
    empty = {
        "gene_name": gene_name,
        "species": species,
        "partners": [],
        "inferred_pathways": [],
        "signaling_pathways": [],
        "method": "string_indirect",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Step 1: Get STRING interaction partners
            params = {
                "identifiers": gene_name,
                "species": species,
                "limit": top_partners,
                "caller_identity": "PTM-Platform",
            }
            resp = await client.get(
                f"{STRING_BASE}/interaction_partners", params=params
            )
            if resp.status_code != 200:
                logger.debug(f"STRING partners failed for {gene_name}: {resp.status_code}")
                return empty

            partner_data = resp.json()
            partners = []
            for p in partner_data:
                name = p.get("preferredName_B", p.get("preferredName_A", ""))
                score = p.get("score", 0)
                if name and name.lower() != gene_name.lower():
                    partners.append({"name": name, "score": round(score, 3)})

            partners.sort(key=lambda x: -x["score"])
            partners = partners[:top_partners]

            if not partners:
                logger.debug(f"No STRING partners for {gene_name}")
                return empty

            # Step 2: Run enrichment on gene + partners
            all_genes = [gene_name] + [p["name"] for p in partners]
            await asyncio.sleep(0.3)  # Rate limit

            params2 = {
                "identifiers": "%0d".join(all_genes),
                "species": species,
                "caller_identity": "PTM-Platform",
            }
            resp2 = await client.get(
                f"{STRING_BASE}/enrichment", params=params2
            )
            if resp2.status_code != 200:
                logger.debug(f"STRING enrichment failed: {resp2.status_code}")
                return {**empty, "partners": partners}

            enrichments = resp2.json()
            if not isinstance(enrichments, list):
                return {**empty, "partners": partners}

            # Step 3: Parse and filter KEGG pathways
            SIG_KW = [
                "signal", "pi3k", "akt", "mapk", "mtor", "ras", "wnt",
                "notch", "jak", "stat", "nfkb", "tgf", "vegf", "erbb",
                "insulin", "integrin", "focal", "adhesion", "autophagy",
                "apoptosis", "kinase", "phosphat", "calcium", "camp",
                "raf", "mek", "erk", "hedgehog", "hippo", "receptor",
                "chemokine", "cytokine", "growth factor", "cell cycle",
                "immune", "inflamm", "toll",
            ]

            # Disease pathway keywords to exclude
            DISEASE_KW = [
                "infection", "virus", "cancer", "carcinoma", "leukemia",
                "melanoma", "glioma", "hepatitis", "tuberculosis",
                "amoebiasis", "lupus", "diabetes", "cardiomyopathy",
                "neurodegenerat", "alzheimer", "parkinson", "huntington",
                "amyotrophic", "spinocerebellar",
            ]

            inferred_pathways = []
            signaling_pathways = []

            for item in enrichments:
                category = item.get("category", "")
                if category != "KEGG":
                    continue

                desc = item.get("description", "")
                fdr = item.get("fdr", 1.0)
                input_genes = item.get("inputGenes", "")
                gene_count = item.get("number_of_genes", 0)

                # Check if target gene is in the enriched set
                gene_in_set = gene_name.lower() in input_genes.lower() if isinstance(input_genes, str) else False

                # Skip disease pathways
                desc_lower = desc.lower()
                is_disease = any(kw in desc_lower for kw in DISEASE_KW)
                if is_disease:
                    continue

                is_signaling = any(kw in desc_lower for kw in SIG_KW)

                pathway = {
                    "name": desc,
                    "fdr": fdr,
                    "gene_count": gene_count,
                    "input_genes": input_genes,
                    "target_gene_in_set": gene_in_set,
                    "is_signaling": is_signaling,
                    "inference_type": "direct" if gene_in_set else "indirect",
                    "source": "STRING+KEGG",
                }

                inferred_pathways.append(pathway)
                if is_signaling:
                    signaling_pathways.append(pathway)

            # Sort by FDR
            inferred_pathways.sort(key=lambda x: x["fdr"])
            signaling_pathways.sort(key=lambda x: x["fdr"])

            return {
                "gene_name": gene_name,
                "species": species,
                "partners": partners,
                "partner_count": len(partners),
                "inferred_pathways": inferred_pathways[:20],
                "signaling_pathways": signaling_pathways[:15],
                "method": "string_indirect",
                "total_kegg_terms": len(inferred_pathways),
                "signaling_count": len(signaling_pathways),
            }

    except Exception as e:
        logger.warning(f"STRING indirect inference failed for {gene_name}: {e}")
        return empty
