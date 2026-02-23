"""
Collection Selector — auto-selects ChromaDB collections based on experimental context.

Ported from ptm-chromadb-web/python_backend/collection_selector.py.

Features:
  - 4-tier collection hierarchy (Tissue, PTM type, Pathway, General)
  - Context-aware cell-type classification
  - Treatment keyword extraction and pathway inference
  - Weighted collection scoring for retrieval ranking
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ExperimentalContext:
    """Experimental context for collection selection."""
    cell_type: str = ""
    treatment: str = ""
    time_points: str = ""
    control: str = ""
    special_conditions: str = ""
    biological_question: str = ""


@dataclass
class ContextAnalysis:
    """Analysis result of experimental context."""
    cell_type_category: str = ""
    cell_type_confidence: float = 0.0
    treatment_keywords: List[str] = field(default_factory=list)
    inferred_pathways: List[str] = field(default_factory=list)
    ptm_types: List[str] = field(default_factory=list)


@dataclass
class CollectionSelection:
    """Selected collections with tier grouping and weights."""
    tier1: List[str] = field(default_factory=list)   # Tissue/Cell type
    tier2: List[str] = field(default_factory=list)   # PTM type
    tier3: List[str] = field(default_factory=list)   # Pathway
    tier4: List[str] = field(default_factory=list)   # General knowledge
    weights: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mapping Tables
# ---------------------------------------------------------------------------

CELL_TYPE_MAPPING = {
    "muscle": {
        "keywords": [
            "muscle", "myocyte", "myoblast", "myotube", "fiber",
            "skeletal muscle", "cardiac muscle", "c2c12",
        ],
        "collection": "muscle_biology",
        "weight": 1.0,
    },
    "neuron": {
        "keywords": [
            "neuron", "neural", "brain", "synapse", "axon", "dendrite",
            "neuronal", "cortical", "hippocampal",
        ],
        "collection": "neuroscience",
        "weight": 1.0,
    },
    "cancer": {
        "keywords": [
            "cancer", "tumor", "oncogene", "malignant", "carcinoma",
            "leukemia", "lymphoma", "melanoma",
        ],
        "collection": "cancer_biology",
        "weight": 1.0,
    },
    "immune": {
        "keywords": [
            "immune", "t cell", "b cell", "lymphocyte", "macrophage",
            "dendritic cell", "nk cell",
        ],
        "collection": "immunology",
        "weight": 1.0,
    },
    "stem": {
        "keywords": [
            "stem cell", "pluripotent", "ipsc", "esc", "progenitor",
            "hematopoietic stem",
        ],
        "collection": "stem_cell",
        "weight": 1.0,
    },
    "cardiac": {
        "keywords": [
            "heart", "cardiac", "cardiomyocyte", "myocardial",
            "ventricular", "atrial",
        ],
        "collection": "cardiovascular",
        "weight": 1.0,
    },
    "metabolic": {
        "keywords": ["adipocyte", "hepatocyte", "pancreatic", "beta cell", "islet"],
        "collection": "metabolism",
        "weight": 1.0,
    },
    "liver": {
        "keywords": ["liver", "hepatocyte", "hepatic", "hepg2"],
        "collection": "liver_biology",
        "weight": 1.0,
    },
}

PATHWAY_MAPPING = {
    "mapk": {
        "keywords": ["mapk", "erk", "jnk", "p38", "mek", "raf", "ras"],
        "collection": "mapk_signaling",
        "weight": 0.8,
    },
    "pi3k": {
        "keywords": ["pi3k", "akt", "mtor", "insulin", "growth factor", "igf"],
        "collection": "pi3k_akt",
        "weight": 0.8,
    },
    "wnt": {
        "keywords": ["wnt", "beta-catenin", "β-catenin", "gsk3", "tcf", "lef"],
        "collection": "wnt_signaling",
        "weight": 0.7,
    },
    "tgfb": {
        "keywords": ["tgf-β", "tgfb", "smad", "emt", "fibrosis"],
        "collection": "tgfb_signaling",
        "weight": 0.7,
    },
    "nfkb": {
        "keywords": ["nf-κb", "nfkb", "ikb", "tnf", "inflammation"],
        "collection": "nfkb_signaling",
        "weight": 0.7,
    },
    "calcium": {
        "keywords": ["calcium", "ca2+", "calmodulin", "camk", "calcium channel"],
        "collection": "calcium_signaling",
        "weight": 0.7,
    },
    "cell_cycle": {
        "keywords": ["cell cycle", "cdk", "cyclin", "checkpoint", "mitosis"],
        "collection": "cell_cycle",
        "weight": 0.7,
    },
    "apoptosis": {
        "keywords": ["apoptosis", "caspase", "bcl-2", "death receptor", "programmed cell death"],
        "collection": "apoptosis",
        "weight": 0.7,
    },
}

PTM_TYPE_MAPPING = {
    "phosphorylation": {
        "keywords": [
            "phosphorylation", "kinase", "phosphatase", "serine", "threonine",
            "tyrosine", "phospho",
        ],
        "collection": "phosphorylation",
        "weight": 1.0,
    },
    "acetylation": {
        "keywords": ["acetylation", "hat", "hdac", "histone", "chromatin"],
        "collection": "acetylation",
        "weight": 0.9,
    },
    "ubiquitination": {
        "keywords": ["ubiquitination", "e3 ligase", "proteasome", "degradation", "ubiquitin"],
        "collection": "ubiquitination",
        "weight": 0.9,
    },
    "methylation": {
        "keywords": ["methylation", "methyltransferase", "demethylase", "epigenetic"],
        "collection": "methylation",
        "weight": 0.9,
    },
}

GENERAL_COLLECTIONS = ["textbooks", "reviews", "pathway_databases", "ptm_databases"]


# ---------------------------------------------------------------------------
# Context Analyzer
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """Analyzes experimental context to determine relevant domains."""

    def analyze(self, context: ExperimentalContext) -> ContextAnalysis:
        cell_category, confidence = self._classify_cell_type(context.cell_type)
        treatment_keywords = self._extract_treatment_keywords(context.treatment)
        inferred_pathways = self._infer_pathways(
            context.treatment, context.biological_question,
        )
        ptm_types = self._detect_ptm_types(
            context.biological_question, context.treatment,
        )

        return ContextAnalysis(
            cell_type_category=cell_category,
            cell_type_confidence=confidence,
            treatment_keywords=treatment_keywords,
            inferred_pathways=inferred_pathways,
            ptm_types=ptm_types,
        )

    def _classify_cell_type(self, cell_type: str) -> Tuple[str, float]:
        cell_lower = cell_type.lower()
        best_match = ("unknown", 0.0)

        for category, info in CELL_TYPE_MAPPING.items():
            for kw in info["keywords"]:
                if kw in cell_lower:
                    score = len(kw) / max(len(cell_lower), 1)
                    if score > best_match[1]:
                        best_match = (category, min(score + 0.5, 1.0))

        return best_match

    def _extract_treatment_keywords(self, treatment: str) -> List[str]:
        if not treatment:
            return []
        words = re.findall(r"[A-Za-z0-9-]+", treatment)
        stopwords = {"and", "or", "the", "with", "for", "in", "on", "at", "to", "of"}
        return [w for w in words if w.lower() not in stopwords and len(w) > 2]

    def _infer_pathways(self, treatment: str, question: str) -> List[str]:
        combined = f"{treatment} {question}".lower()
        pathways = []
        for pw_name, info in PATHWAY_MAPPING.items():
            for kw in info["keywords"]:
                if kw in combined:
                    pathways.append(pw_name)
                    break
        return pathways

    def _detect_ptm_types(self, question: str, treatment: str) -> List[str]:
        combined = f"{question} {treatment}".lower()
        ptm_types = []
        for ptm_name, info in PTM_TYPE_MAPPING.items():
            for kw in info["keywords"]:
                if kw in combined:
                    ptm_types.append(ptm_name)
                    break

        if not ptm_types:
            ptm_types = ["phosphorylation"]  # Default

        return ptm_types


# ---------------------------------------------------------------------------
# Collection Selector
# ---------------------------------------------------------------------------

class CollectionSelector:
    """Selects ChromaDB collections based on experimental context."""

    def __init__(self):
        self.analyzer = ContextAnalyzer()

    def select(self, context: ExperimentalContext) -> CollectionSelection:
        """
        Select collections based on experimental context.

        Returns:
            CollectionSelection with tier-grouped collections and weights.
        """
        analysis = self.analyzer.analyze(context)
        selection = CollectionSelection()

        # Tier 1: Cell type / tissue
        if analysis.cell_type_category != "unknown":
            mapping = CELL_TYPE_MAPPING.get(analysis.cell_type_category)
            if mapping:
                coll = mapping["collection"]
                selection.tier1.append(coll)
                selection.weights[coll] = mapping["weight"] * analysis.cell_type_confidence

        # Tier 2: PTM type
        for ptm_type in analysis.ptm_types:
            mapping = PTM_TYPE_MAPPING.get(ptm_type)
            if mapping:
                coll = mapping["collection"]
                selection.tier2.append(coll)
                selection.weights[coll] = mapping["weight"]

        # Tier 3: Pathways
        for pathway in analysis.inferred_pathways:
            mapping = PATHWAY_MAPPING.get(pathway)
            if mapping:
                coll = mapping["collection"]
                selection.tier3.append(coll)
                selection.weights[coll] = mapping["weight"]

        # Tier 4: General knowledge (always included)
        selection.tier4 = GENERAL_COLLECTIONS.copy()
        for coll in GENERAL_COLLECTIONS:
            selection.weights[coll] = 0.5

        logger.info(
            f"Collection selection: "
            f"tier1={selection.tier1}, tier2={selection.tier2}, "
            f"tier3={selection.tier3}, tier4={selection.tier4}"
        )

        return selection

    def get_all_collections(self, context: ExperimentalContext) -> List[str]:
        """Get flat list of all selected collections."""
        selection = self.select(context)
        return selection.tier1 + selection.tier2 + selection.tier3 + selection.tier4

    def get_weighted_collections(self, context: ExperimentalContext) -> List[Tuple[str, float]]:
        """Get collections with their weights, sorted by weight descending."""
        selection = self.select(context)
        all_colls = self.get_all_collections(context)
        weighted = [(c, selection.weights.get(c, 0.5)) for c in all_colls]
        weighted.sort(key=lambda x: x[1], reverse=True)
        return weighted
