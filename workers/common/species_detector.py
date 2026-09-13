"""
Species Auto-Detector (v2.1)
Ported from ptm-vector-ai/src/fileUtils.ts.

Resolves explicit FASTA taxonomy when unambiguous. Prior KEGG annotations and
gene capitalization are hints only, not evidence resolving the host organism.
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
    # FASTA-native provenance can identify supplied reference entries. Do not
    # resolve a mixed protein group by majority vote or its first accession.
    from ptm_shared.annotation_species import normalize_species, NAMES
    for column in ("FASTA_Taxonomy_ID", "fasta_taxonomy_id", "FASTA_Organism"):
        if column in df:
            taxa = {normalize_species(part) for value in df[column].dropna()
                    for part in re.split(r"[;,]", str(value)) if part.strip()}
            if len(taxa) == 1 and None not in taxa:
                return NAMES[next(iter(taxa))][0], "high", "Explicit FASTA-native taxonomy"
            if taxa:
                return "unknown", "low", "Mixed or unresolved FASTA-native taxonomy; retain per-feature scope"
    # Existing annotations are not independent evidence of the study organism.
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
                logger.info(f"Prior KEGG species hint: {best}; host taxonomy remains unresolved (counts={counts})")
                return "unknown", "low", f"Prior KEGG annotation hint only: {counts}; explicit host or FASTA taxonomy required"

    # Capitalization cannot resolve host taxonomy (rat and mouse overlap).
    return "unknown", "low", "No explicit species evidence; gene capitalization is only a naming hint"


def detect_species_from_file(tsv_path: str) -> Tuple[str, str, str]:
    """Convenience: detect species from a TSV file path."""
    try:
        df = pd.read_csv(tsv_path, sep="\t", nrows=500, low_memory=False)
        return detect_species_from_tsv(df)
    except Exception as e:
        logger.warning(f"Species detection failed for {tsv_path}: {e}")
        return "unknown", "low", f"Error: {e}"
