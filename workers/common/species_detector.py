"""
Species Auto-Detector (v2.1)
Ported from ptm-vector-ai/src/fileUtils.ts.

Detects species from TSV data using two strategies:
  1. KEGG Pathway identifiers (mmu/hsa/rno) — high confidence
  2. Gene name format analysis (Title Case = Mouse, UPPERCASE = Human) — medium confidence
"""

import logging
import re
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger("ptm-workers.species-detector")

KEGG_SPECIES_MAP = {
    "mmu": "mouse",
    "hsa": "human",
    "rno": "rat",
}

SPECIES_NAME_MAP = {
    "mus musculus": "mouse",
    "homo sapiens": "human",
    "rattus norvegicus": "rat",
}


def detect_species_from_tsv(df: pd.DataFrame) -> Tuple[str, str, str]:
    """
    Detect species from a PTM TSV DataFrame.

    Returns:
        (species, confidence, details)
        species: 'mouse' | 'human' | 'rat' | 'unknown'
        confidence: 'high' | 'medium' | 'low'
        details: human-readable explanation
    """
    # Strategy 1: KEGG Pathway identifiers
    kegg_col = None
    for col in df.columns:
        if "kegg" in col.lower():
            kegg_col = col
            break

    if kegg_col and not df[kegg_col].dropna().empty:
        counts = {"mouse": 0, "human": 0, "rat": 0}
        kegg_text = " ".join(df[kegg_col].dropna().astype(str).tolist())

        for code, species in KEGG_SPECIES_MAP.items():
            counts[species] += len(re.findall(rf"\({code}\)", kegg_text, re.IGNORECASE))
        for name, species in SPECIES_NAME_MAP.items():
            counts[species] += len(re.findall(name, kegg_text, re.IGNORECASE))

        if any(counts.values()):
            best = max(counts, key=counts.get)  # type: ignore[arg-type]
            if counts[best] > 0:
                logger.info(f"Species detected via KEGG: {best} (counts={counts})")
                return best, "high", f"KEGG pathway analysis: {counts}"

    # Strategy 2: Gene name format
    gene_col = None
    for col in df.columns:
        if col.lower() in ("gene.name", "gene_name", "gene", "genename"):
            gene_col = col
            break

    if gene_col and not df[gene_col].dropna().empty:
        genes = df[gene_col].dropna().astype(str).tolist()
        total = len(genes)
        if total == 0:
            return "unknown", "low", "No gene names found"

        title_case = sum(1 for g in genes if re.match(r"^[A-Z][a-z]", g))
        upper_case = sum(1 for g in genes if re.match(r"^[A-Z]{2,}$", g))

        title_ratio = title_case / total
        upper_ratio = upper_case / total

        if title_ratio > 0.7:
            logger.info(f"Species detected via gene format: mouse (title_case={title_ratio:.1%})")
            return "mouse", "medium", f"Gene name format: {title_ratio:.0%} Title Case (Mouse pattern)"
        elif upper_ratio > 0.7:
            logger.info(f"Species detected via gene format: human (upper_case={upper_ratio:.1%})")
            return "human", "medium", f"Gene name format: {upper_ratio:.0%} UPPERCASE (Human pattern)"

    return "unknown", "low", "Could not auto-detect species"


def detect_species_from_file(tsv_path: str) -> Tuple[str, str, str]:
    """Convenience: detect species from a TSV file path."""
    try:
        df = pd.read_csv(tsv_path, sep="\t", nrows=500, low_memory=False)
        return detect_species_from_tsv(df)
    except Exception as e:
        logger.warning(f"Species detection failed for {tsv_path}: {e}")
        return "unknown", "low", f"Error: {e}"
