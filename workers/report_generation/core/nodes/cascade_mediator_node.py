"""
Cascade Mediator Node — Content-driven signaling cascade diagram generation.

v7.0 — Content-Driven Cascade Diagram:
  The mediator sits between write_sections and format_citations in the pipeline.
  It reads the LLM-written Results/Discussion text, extracts which canonical
  pathways were actually discussed, and generates cascade diagrams that match
  the text content.

  This replaces the old approach where cascade diagrams were generated before
  the text (in network_analysis) and the LLM was forced to mention specific
  pathways.

Flow:
  1. Receive LLM-written sections (Results, Discussion) from state
  2. Receive pathway_candidates from network_analysis (all scored pathways)
  3. Deterministically extract which pathways were discussed in the text
  4. Generate cascade diagrams using only the discussed pathways
  5. Store cascade_diagrams and cascade_pathway_names in state

Design Principles:
  - NO LLM calls — purely deterministic text matching
  - Reuses signaling_cascade.py rendering engine
  - Backward compatible: if no pathways found, no diagram generated
  - Configurable via report_config["cascade_mediator"]
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pathway name normalization and alias mapping
# ---------------------------------------------------------------------------

# Common abbreviations/aliases → canonical KEGG pathway name fragments
PATHWAY_ALIASES = {
    # MAPK family
    "mapk": "MAPK signaling",
    "erk": "MAPK signaling",
    "erk1/2": "MAPK signaling",
    "ras-mapk": "MAPK signaling",
    "ras/mapk": "MAPK signaling",
    "ras-raf-mek-erk": "MAPK signaling",
    "raf-mek-erk": "MAPK signaling",
    "mek-erk": "MAPK signaling",
    # PI3K-Akt
    "pi3k": "PI3K-Akt signaling",
    "pi3k/akt": "PI3K-Akt signaling",
    "pi3k-akt": "PI3K-Akt signaling",
    "akt": "PI3K-Akt signaling",
    "akt/mtor": "PI3K-Akt signaling",
    "pi3k/akt/mtor": "PI3K-Akt signaling",
    # mTOR
    "mtor": "mTOR signaling",
    "mtorc1": "mTOR signaling",
    "mtorc2": "mTOR signaling",
    # NF-kB
    "nf-kb": "NF-kappa B signaling",
    "nf-κb": "NF-kappa B signaling",
    "nfkb": "NF-kappa B signaling",
    "nf-kappab": "NF-kappa B signaling",
    "nuclear factor kappa": "NF-kappa B signaling",
    # JAK-STAT
    "jak-stat": "JAK-STAT signaling",
    "jak/stat": "JAK-STAT signaling",
    "stat3": "JAK-STAT signaling",
    # Wnt
    "wnt": "Wnt signaling",
    "wnt/beta-catenin": "Wnt signaling",
    "β-catenin": "Wnt signaling",
    "beta-catenin": "Wnt signaling",
    # p53
    "p53": "p53 signaling",
    "tp53": "p53 signaling",
    # Apoptosis
    "apoptosis": "Apoptosis",
    "apoptotic": "Apoptosis",
    "caspase": "Apoptosis",
    "programmed cell death": "Apoptosis",
    # ErbB
    "erbb": "ErbB signaling",
    "egfr": "ErbB signaling",
    "her2": "ErbB signaling",
    "epidermal growth factor": "ErbB signaling",
    # VEGF
    "vegf": "VEGF signaling",
    "angiogenesis": "VEGF signaling",
    # Ras
    "ras signaling": "Ras signaling",
    # HIF-1
    "hif-1": "HIF-1 signaling",
    "hif1": "HIF-1 signaling",
    "hypoxia": "HIF-1 signaling",
    # FoxO
    "foxo": "FoxO signaling",
    # AMPK
    "ampk": "AMPK signaling",
    # Calcium
    "calcium signaling": "Calcium signaling",
    "ca2+": "Calcium signaling",
    # cAMP
    "camp": "cAMP signaling",
    "cyclic amp": "cAMP signaling",
    # TLR
    "toll-like receptor": "Toll-like receptor signaling",
    "tlr": "Toll-like receptor signaling",
    # TNF
    "tnf": "TNF signaling",
    "tumor necrosis factor": "TNF signaling",
    # Insulin
    "insulin signaling": "Insulin signaling",
    "insulin receptor": "Insulin signaling",
    # TGF-beta
    "tgf-beta": "TGF-beta signaling",
    "tgf-β": "TGF-beta signaling",
    "tgfb": "TGF-beta signaling",
    "transforming growth factor": "TGF-beta signaling",
    "smad": "TGF-beta signaling",
    # Cell cycle
    "cell cycle": "Cell cycle",
    "cdk": "Cell cycle",
    "cyclin": "Cell cycle",
    # Neurotrophin
    "neurotrophin": "Neurotrophin signaling",
    "bdnf": "Neurotrophin signaling",
    "ngf": "Neurotrophin signaling",
    # Chemokine
    "chemokine": "Chemokine signaling",
    "cxcr": "Chemokine signaling",
    "ccr": "Chemokine signaling",
    # Rap1
    "rap1": "Rap1 signaling",
}

# Gene → pathway membership (for gene-cluster detection)
# Built from PATHWAY_SIGNAL_ORDER in signaling_cascade.py
GENE_TO_PATHWAYS = {
    "EGFR": ["MAPK signaling", "ErbB signaling", "JAK-STAT signaling"],
    "GRB2": ["MAPK signaling", "ErbB signaling", "Ras signaling"],
    "SOS1": ["MAPK signaling", "Ras signaling"],
    "HRAS": ["MAPK signaling", "Ras signaling"],
    "KRAS": ["MAPK signaling", "Ras signaling"],
    "RAF1": ["MAPK signaling", "Ras signaling", "ErbB signaling"],
    "BRAF": ["MAPK signaling", "Ras signaling"],
    "MAP2K1": ["MAPK signaling", "ErbB signaling", "Ras signaling"],
    "MAP2K2": ["MAPK signaling"],
    "MAPK1": ["MAPK signaling", "ErbB signaling", "Ras signaling", "VEGF signaling"],
    "MAPK3": ["MAPK signaling"],
    "ELK1": ["MAPK signaling"],
    "FOS": ["MAPK signaling"],
    "JUN": ["MAPK signaling"],
    "MYC": ["MAPK signaling", "Wnt signaling"],
    "IGF1R": ["PI3K-Akt signaling", "FoxO signaling"],
    "INSR": ["PI3K-Akt signaling", "Insulin signaling"],
    "IRS1": ["PI3K-Akt signaling", "Insulin signaling"],
    "PIK3CA": ["PI3K-Akt signaling", "mTOR signaling", "HIF-1 signaling", "VEGF signaling"],
    "PIK3R1": ["PI3K-Akt signaling", "mTOR signaling"],
    "AKT1": ["PI3K-Akt signaling", "mTOR signaling", "ErbB signaling", "VEGF signaling", "HIF-1 signaling", "FoxO signaling", "Insulin signaling"],
    "AKT2": ["PI3K-Akt signaling"],
    "MTOR": ["PI3K-Akt signaling", "mTOR signaling", "HIF-1 signaling", "Insulin signaling"],
    "RPS6KB1": ["PI3K-Akt signaling", "mTOR signaling"],
    "GSK3B": ["PI3K-Akt signaling", "Wnt signaling", "Insulin signaling"],
    "FOXO1": ["PI3K-Akt signaling", "FoxO signaling", "Insulin signaling"],
    "FOXO3": ["FoxO signaling", "AMPK signaling"],
    "TLR4": ["NF-kappa B signaling", "Toll-like receptor signaling"],
    "TNFR1": ["NF-kappa B signaling", "Apoptosis", "TNF signaling"],
    "IKBKB": ["NF-kappa B signaling", "Toll-like receptor signaling", "TNF signaling"],
    "NFKB1": ["NF-kappa B signaling", "Toll-like receptor signaling", "TNF signaling"],
    "RELA": ["NF-kappa B signaling", "Toll-like receptor signaling", "TNF signaling"],
    "JAK1": ["JAK-STAT signaling"],
    "JAK2": ["JAK-STAT signaling"],
    "STAT1": ["JAK-STAT signaling"],
    "STAT3": ["JAK-STAT signaling"],
    "STAT5A": ["JAK-STAT signaling"],
    "WNT1": ["Wnt signaling"],
    "CTNNB1": ["Wnt signaling"],
    "TP53": ["p53 signaling", "Cell cycle"],
    "CHEK1": ["p53 signaling"],
    "CHEK2": ["p53 signaling"],
    "CASP3": ["Apoptosis", "TNF signaling"],
    "CASP8": ["Apoptosis", "TNF signaling"],
    "CASP9": ["Apoptosis"],
    "BAX": ["Apoptosis", "p53 signaling"],
    "BCL2": ["Apoptosis"],
    "ERBB2": ["ErbB signaling"],
    "ERBB3": ["ErbB signaling"],
    "SHC1": ["ErbB signaling", "Neurotrophin signaling"],
    "SRC": ["VEGF signaling"],
    "HIF1A": ["HIF-1 signaling"],
    "VEGFA": ["VEGF signaling", "HIF-1 signaling"],
    "PRKAA1": ["AMPK signaling"],
    "PRKAA2": ["AMPK signaling"],
    "TSC2": ["mTOR signaling", "AMPK signaling"],
    "CREB1": ["cAMP signaling", "Calcium signaling", "Neurotrophin signaling"],
    "CAMK2A": ["Calcium signaling"],
    "MYD88": ["Toll-like receptor signaling"],
    "TRAF6": ["Toll-like receptor signaling"],
    "TNF": ["TNF signaling"],
    "TRAF2": ["TNF signaling"],
    "SMAD2": ["TGF-beta signaling"],
    "SMAD3": ["TGF-beta signaling"],
    "SMAD4": ["TGF-beta signaling"],
    "CDK1": ["Cell cycle"],
    "CDK2": ["Cell cycle"],
    "CDK4": ["Cell cycle"],
    "CDK6": ["Cell cycle"],
    "RB1": ["Cell cycle"],
    "E2F1": ["Cell cycle"],
    "CDKN1A": ["p53 signaling", "Cell cycle", "TGF-beta signaling", "FoxO signaling"],
    "NTRK1": ["Neurotrophin signaling"],
    "NTRK2": ["Neurotrophin signaling"],
    "CXCR4": ["Chemokine signaling"],
}


# ---------------------------------------------------------------------------
# Pathway extraction from text
# ---------------------------------------------------------------------------

def _normalize_pathway_name(name: str) -> str:
    """Normalize a pathway name for comparison."""
    return re.sub(r'\s+', ' ', name.strip().lower())


def _build_candidate_lookup(pathway_candidates: dict) -> Dict[str, dict]:
    """Build a normalized name → candidate mapping for fast lookup."""
    lookup = {}
    for cand in pathway_candidates.get("candidates", []):
        norm = _normalize_pathway_name(cand["name"])
        lookup[norm] = cand
        # Also index by short name (without "signaling pathway" suffix)
        short = re.sub(r'\s*(signaling\s+)?pathway$', '', norm).strip()
        if short and short != norm:
            lookup[short] = cand
    return lookup


def extract_discussed_pathways(
    sections: Dict[str, str],
    pathway_candidates: dict,
    min_gene_cluster: int = 3,
    top_n: int = 5,
) -> List[dict]:
    """
    Extract pathways that the LLM actually discussed in Results/Discussion.
    
    Strategy (deterministic, no LLM needed):
    1. Build pathway name → candidate mapping from pathway_candidates
    2. Scan Results + Discussion text for pathway name mentions
    3. Also scan for key gene names that belong to specific pathways
    4. Rank matched pathways by:
       a. Number of text mentions (pathway name + gene names)
       b. Original composite score from pathway_candidates
       c. Whether discussed in both Results AND Discussion
    5. Select top N pathways
    
    Args:
        sections: Dict of section_type → text (from write_sections)
        pathway_candidates: Dict with "candidates" list from network_analysis
        min_gene_cluster: Minimum gene mentions from a pathway to count as discussed
        top_n: Maximum number of pathways to select
    
    Returns:
        List of pathway candidate dicts, ranked by discussion relevance
    """
    # Combine Results + Discussion text for scanning
    results_text = sections.get("results", "")
    discussion_text = sections.get("discussion", "")
    combined_text = f"{results_text}\n\n{discussion_text}"
    combined_lower = combined_text.lower()
    
    if not combined_text.strip():
        logger.warning("[MEDIATOR] No Results/Discussion text available — cannot extract pathways")
        return []
    
    candidate_lookup = _build_candidate_lookup(pathway_candidates)
    all_candidates = pathway_candidates.get("candidates", [])
    
    if not all_candidates:
        logger.warning("[MEDIATOR] No pathway candidates available — cannot extract pathways")
        return []
    
    logger.info(
        f"[MEDIATOR] Extracting pathways from text: "
        f"{len(results_text)} chars Results, {len(discussion_text)} chars Discussion, "
        f"{len(all_candidates)} candidates"
    )
    
    # ---- Phase 1: Direct pathway name matching ----
    pathway_mention_scores: Dict[str, dict] = {}  # candidate_name → scoring info
    
    for cand in all_candidates:
        cand_name = cand["name"]
        cand_lower = cand_name.lower()
        
        # Count direct mentions of the full pathway name
        full_count = len(re.findall(re.escape(cand_lower), combined_lower))
        
        # Count mentions of shortened pathway name (e.g., "MAPK signaling" from "MAPK signaling pathway")
        short_name = re.sub(r'\s*(signaling\s+)?pathway$', '', cand_lower).strip()
        short_count = 0
        if short_name and short_name != cand_lower:
            short_count = len(re.findall(re.escape(short_name), combined_lower))
        
        # Check alias mentions
        alias_count = 0
        for alias, canonical_fragment in PATHWAY_ALIASES.items():
            if canonical_fragment.lower() in cand_lower or cand_lower in canonical_fragment.lower():
                # This alias maps to this candidate
                alias_pattern = re.escape(alias)
                # Word boundary matching for short aliases to avoid false positives
                if len(alias) <= 4:
                    alias_matches = len(re.findall(r'\b' + alias_pattern + r'\b', combined_lower))
                else:
                    alias_matches = len(re.findall(alias_pattern, combined_lower))
                alias_count += alias_matches
        
        total_name_mentions = full_count + short_count + alias_count
        
        # Check if mentioned in both Results AND Discussion
        in_results = bool(re.search(re.escape(short_name), results_text.lower())) if short_name else False
        in_discussion = bool(re.search(re.escape(short_name), discussion_text.lower())) if short_name else False
        in_both = in_results and in_discussion
        
        pathway_mention_scores[cand_name] = {
            "candidate": cand,
            "name_mentions": total_name_mentions,
            "gene_mentions": 0,
            "genes_mentioned": set(),
            "in_both_sections": in_both,
            "in_results": in_results,
            "in_discussion": in_discussion,
        }
    
    # ---- Phase 2: Gene cluster detection ----
    # Find all gene names mentioned in the text
    # Build a set of all genes in the data
    gene_data = pathway_candidates.get("gene_data", {})
    all_gene_names = set(gene_data.keys()) if gene_data else set()
    
    # Also collect genes from candidates
    for cand in all_candidates:
        for g in cand.get("genes", []):
            all_gene_names.add(g.upper())
    
    # Scan text for gene mentions
    genes_found_in_text: Set[str] = set()
    for gene in all_gene_names:
        if len(gene) < 2:
            continue
        # Use word boundary matching to avoid false positives
        # Gene names are typically uppercase, so search case-sensitively
        if re.search(r'\b' + re.escape(gene) + r'\b', combined_text):
            genes_found_in_text.add(gene)
    
    logger.info(f"[MEDIATOR] Found {len(genes_found_in_text)} gene names in text")
    
    # Map found genes to pathways
    for cand in all_candidates:
        cand_name = cand["name"]
        cand_genes = set(g.upper() for g in cand.get("genes", []))
        
        # Count how many of this pathway's genes appear in the text
        mentioned_genes = cand_genes & genes_found_in_text
        
        if cand_name in pathway_mention_scores:
            pathway_mention_scores[cand_name]["gene_mentions"] = len(mentioned_genes)
            pathway_mention_scores[cand_name]["genes_mentioned"] = mentioned_genes
    
    # Also use GENE_TO_PATHWAYS for additional gene→pathway mapping
    for gene in genes_found_in_text:
        gene_upper = gene.upper()
        if gene_upper in GENE_TO_PATHWAYS:
            for pw_fragment in GENE_TO_PATHWAYS[gene_upper]:
                # Find matching candidate
                for cand_name, score_info in pathway_mention_scores.items():
                    if pw_fragment.lower() in cand_name.lower():
                        score_info["genes_mentioned"].add(gene_upper)
                        score_info["gene_mentions"] = len(score_info["genes_mentioned"])
    
    # ---- Phase 3: Composite scoring ----
    scored_pathways: List[Tuple[str, float, dict]] = []
    
    for cand_name, score_info in pathway_mention_scores.items():
        cand = score_info["candidate"]
        
        # Skip pathways with zero text presence
        name_mentions = score_info["name_mentions"]
        gene_mentions = score_info["gene_mentions"]
        
        if name_mentions == 0 and gene_mentions < min_gene_cluster:
            continue
        
        # Composite relevance score
        # Weight: name mentions (high signal) > gene cluster > original score > both sections
        name_score = min(name_mentions * 3.0, 15.0)  # Cap at 5 mentions
        gene_score = min(gene_mentions * 1.0, 8.0)    # Cap at 8 genes
        original_score = cand.get("composite_score", 0) * 0.5  # Original scoring as tiebreaker
        both_bonus = 3.0 if score_info["in_both_sections"] else 0.0
        
        composite = name_score + gene_score + original_score + both_bonus
        
        scored_pathways.append((cand_name, composite, {
            **score_info,
            "composite_relevance": composite,
        }))
    
    # Sort by composite relevance
    scored_pathways.sort(key=lambda x: -x[1])

    # ---- v8.9.8: Filter out disease pathways (KEGG 05xxx) ----
    _DISEASE_KEYWORDS = {
        "infection", "virus", "viral", "carcinogenesis", "cancer",
        "amoebiasis", "lupus", "leishmaniasis", "tuberculosis",
        "malaria", "pertussis", "measles", "hepatitis", "influenza",
        "herpes", "hiv", "htlv", "epstein-barr", "kaposi",
        "shigellosis", "salmonella", "cholera", "diabetes",
        "cardiomyopathy", "alzheimer", "parkinson", "huntington",
        "prion", "asthma", "graft-versus-host",
    }
    filtered_pathways = []
    for name, score, info in scored_pathways:
        name_lower = name.lower()
        cand = info.get("candidate", {})
        kegg_id = cand.get("kegg_id", "") or ""
        is_disease = kegg_id.startswith("05") or any(kw in name_lower for kw in _DISEASE_KEYWORDS)
        if is_disease:
            logger.info(f"[MEDIATOR] Filtered disease pathway from cascade: {name} (kegg_id={kegg_id})")
        else:
            filtered_pathways.append((name, score, info))
    scored_pathways = filtered_pathways

    # Select top N
    selected = scored_pathways[:top_n]
    
    # Log results
    logger.info(f"[MEDIATOR] Pathway extraction results ({len(scored_pathways)} matched, {len(selected)} selected):")
    for name, score, info in selected:
        logger.info(
            f"  {name}: relevance={score:.1f} "
            f"(name_mentions={info['name_mentions']}, "
            f"gene_mentions={info['gene_mentions']}, "
            f"in_both={info['in_both_sections']}, "
            f"genes={sorted(info['genes_mentioned'])[:5]}{'...' if len(info['genes_mentioned']) > 5 else ''})"
        )
    
    if not selected:
        logger.warning("[MEDIATOR] No pathways found in text — will fall back to top candidates by score")
        # Fallback: use top candidates by original composite score
        fallback = sorted(all_candidates, key=lambda c: -c.get("composite_score", 0))[:top_n]
        logger.info(f"[MEDIATOR] Fallback: using top {len(fallback)} candidates by original score")
        return fallback
    
    return [info["candidate"] for _, _, info in selected]


# ---------------------------------------------------------------------------
# Main mediator node
# ---------------------------------------------------------------------------

def run_cascade_mediator(state: dict) -> dict:
    """
    LangGraph node: Extract discussed pathways from LLM text → generate cascade diagrams.
    
    Reads from state:
        - sections: Dict of section_type → text (from write_sections)
        - pathway_candidates: Dict with candidate pathways (from network_analysis)
        - enriched_ptm_data: List of enriched PTM data
        - parsed_ptms: List of parsed PTM data
        - network_analysis: Dict with network_data, output_dir, timepoints
        - report_config: Optional config overrides
    
    Writes to state:
        - cascade_diagrams: Dict of condition → path (diagram file paths)
        - cascade_pathway_names: Dict of condition → list of pathway names
    """
    cb = state.get("progress_callback")
    if cb:
        cb(78, "Analyzing text content for cascade diagram alignment")
    
    sections = state.get("sections", {})
    pathway_candidates = state.get("pathway_candidates", {})
    enriched_data = state.get("enriched_ptm_data", [])
    parsed_ptms = state.get("parsed_ptms", [])
    network_analysis = state.get("network_analysis", {})
    report_config = state.get("report_config", {})
    
    # Configuration
    mediator_config = report_config.get("cascade_mediator", {})
    top_n = mediator_config.get("top_n_pathways", 5)
    min_gene_cluster = mediator_config.get("min_gene_cluster", 3)
    
    output_dir = state.get("output_dir", "/tmp")
    network_data = network_analysis.get("network_data", {})
    timepoints = network_analysis.get("timepoints", [])
    
    cascade_diagrams: Dict[str, str] = {}
    cascade_pathway_names: Dict[str, list] = {}
    
    logger.info(
        f"[MEDIATOR] Starting cascade mediator: "
        f"sections={list(sections.keys())}, "
        f"candidates={len(pathway_candidates.get('candidates', []))}, "
        f"timepoints={timepoints}, top_n={top_n}"
    )
    
    if not pathway_candidates.get("candidates"):
        logger.warning("[MEDIATOR] No pathway candidates — skipping cascade diagram generation")
        return {
            "cascade_diagrams": {},
            "cascade_pathway_names": {},
        }
    
    # ---- Step 1: Extract discussed pathways from text ----
    discussed_pathways = extract_discussed_pathways(
        sections=sections,
        pathway_candidates=pathway_candidates,
        min_gene_cluster=min_gene_cluster,
        top_n=top_n,
    )
    
    if not discussed_pathways:
        logger.warning("[MEDIATOR] No discussed pathways extracted — no cascade diagrams")
        return {
            "cascade_diagrams": {},
            "cascade_pathway_names": {},
        }
    
    discussed_names = [p["name"] for p in discussed_pathways]
    discussed_genes_set = set()
    for p in discussed_pathways:
        discussed_genes_set.update(g.upper() for g in p.get("genes", []))
    
    logger.info(f"[MEDIATOR] Discussed pathways: {discussed_names}")
    logger.info(f"[MEDIATOR] Total genes in discussed pathways: {len(discussed_genes_set)}")
    
    if cb:
        cb(80, f"Generating cascade diagrams for {len(discussed_pathways)} discussed pathways")
    
    # ---- Step 2: Generate cascade diagrams ----
    # Import the rendering function
    try:
        try:
            from .signaling_cascade import generate_cascade_from_selected_pathways
        except ImportError:
            try:
                from report_generation.core.nodes.signaling_cascade import (
                    generate_cascade_from_selected_pathways,
                )
            except ImportError:
                from signaling_cascade import generate_cascade_from_selected_pathways
    except ImportError:
        logger.error("[MEDIATOR] Cannot import generate_cascade_from_selected_pathways — skipping")
        return {
            "cascade_diagrams": {},
            "cascade_pathway_names": {},
        }
    
    if len(timepoints) > 1:
        # Multi-condition: generate one diagram per condition
        for tp_idx, tp in enumerate(timepoints):
            logger.info(f"[MEDIATOR] Generating cascade diagram for condition: {tp}")
            result = generate_cascade_from_selected_pathways(
                selected_pathway_names=discussed_names,
                parsed_ptms=parsed_ptms,
                enriched_data=enriched_data,
                network_data=network_data,
                output_dir=output_dir,
                condition=tp,
            )
            if result:
                cascade_diagrams[tp] = result["path"]
                cascade_pathway_names[tp] = result.get("pathways", [])
                logger.info(f"[MEDIATOR] Cascade for '{tp}': {result['path']}")
            else:
                logger.info(f"[MEDIATOR] No cascade for '{tp}' — insufficient data")
        
        logger.info(
            f"[MEDIATOR] Per-condition cascades: "
            f"{len(cascade_diagrams)}/{len(timepoints)} generated"
        )
    else:
        # Single condition: generate combined diagram
        result = generate_cascade_from_selected_pathways(
            selected_pathway_names=discussed_names,
            parsed_ptms=parsed_ptms,
            enriched_data=enriched_data,
            network_data=network_data,
            output_dir=output_dir,
        )
        if result:
            cascade_diagrams["combined"] = result["path"]
            cascade_pathway_names["combined"] = result.get("pathways", [])
            logger.info(f"[MEDIATOR] Combined cascade: {result['path']}")
        else:
            logger.info("[MEDIATOR] No combined cascade — insufficient data")
    
    if cb:
        cb(82, f"Cascade diagrams generated: {len(cascade_diagrams)} diagrams")
    
    logger.info(
        f"[MEDIATOR] Cascade mediator complete: "
        f"diagrams={list(cascade_diagrams.keys())}, "
        f"pathway_names={cascade_pathway_names}"
    )
    
    return {
        "cascade_diagrams": cascade_diagrams,
        "cascade_pathway_names": cascade_pathway_names,
    }
