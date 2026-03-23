"""
Regulation Extractor — pattern-based extraction of regulatory relationships from text.
Ported from ptm-rag-backend/src/regulationExtractor.ts and pattern_screening_engine.py.

Extracts upstream/downstream regulators, kinase-substrate relationships,
E3 ligase-substrate relationships (ubiquitylation), and disease associations
from PubMed abstracts using regex patterns.
No LLM dependency.

v8.10: Added ubiquitylation-specific patterns for E3 ligase, DUB, and chain type extraction.
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


REGULATION_PATTERNS = {
    "phosphorylation": [
        (r"(\w+)\s+(?:phosphorylates?|phosphorylated)\s+(\w+)", "kinase", "substrate"),
        (r"phosphorylation\s+(?:of|at)\s+(\w+)\s+(?:by|via|through)\s+(\w+)", "substrate", "kinase"),
        (r"(\w+)\s+kinase\s+(?:phosphorylates?|targets?)\s+(\w+)", "kinase", "substrate"),
        (r"(\w+)\s+(?:is|was|were)\s+phosphorylated\s+by\s+(\w+)", "substrate", "kinase"),
    ],
    # v8.10: Ubiquitylation-specific patterns
    "ubiquitylation": [
        (r"(\w+)\s+(?:ubiquitylates?|ubiquitinates?|ubiquitinated|ubiquitylated)\s+(\w+)", "e3_ligase", "substrate"),
        (r"(?:ubiquitylation|ubiquitination)\s+(?:of|at)\s+(\w+)\s+(?:by|via|through|mediated by)\s+(\w+)", "substrate", "e3_ligase"),
        (r"(\w+)\s+(?:E3|E3 ligase|ligase)\s+(?:ubiquitylates?|ubiquitinates?|targets?|mediates?)\s+(\w+)", "e3_ligase", "substrate"),
        (r"(\w+)\s+(?:is|was|were)\s+(?:ubiquitylated|ubiquitinated)\s+by\s+(\w+)", "substrate", "e3_ligase"),
        (r"(\w+)\s+(?:promotes?|mediates?|catalyzes?)\s+(?:the\s+)?(?:ubiquitylation|ubiquitination)\s+of\s+(\w+)", "e3_ligase", "substrate"),
        (r"(\w+)-(?:mediated|dependent|catalyzed)\s+(?:ubiquitylation|ubiquitination)\s+of\s+(\w+)", "e3_ligase", "substrate"),
    ],
    "deubiquitylation": [
        (r"(\w+)\s+(?:deubiquitylates?|deubiquitinates?|deubiquitinated|deubiquitylated)\s+(\w+)", "dub", "substrate"),
        (r"(?:deubiquitylation|deubiquitination)\s+(?:of|at)\s+(\w+)\s+(?:by|via|through)\s+(\w+)", "substrate", "dub"),
        (r"(\w+)\s+(?:DUB|deubiquitylase|deubiquitinase)\s+(?:removes?|cleaves?|targets?)\s+(\w+)", "dub", "substrate"),
        (r"(\w+)\s+(?:is|was|were)\s+(?:deubiquitylated|deubiquitinated)\s+by\s+(\w+)", "substrate", "dub"),
        (r"(\w+)\s+(?:stabilizes?|rescues?)\s+(\w+)\s+(?:from|by)\s+(?:removing|cleaving)\s+ubiquitin", "dub", "substrate"),
    ],
    "activation": [
        (r"(\w+)\s+(?:activates?|activated|activation of)\s+(\w+)", "activator", "target"),
        (r"(\w+)\s+(?:induces?|induced|promotes?)\s+(?:the\s+)?(?:phosphorylation|activation)\s+of\s+(\w+)", "activator", "target"),
        (r"(\w+)\s+(?:signaling|pathway)\s+(?:activates?|promotes?)\s+(\w+)", "activator", "target"),
    ],
    "inhibition": [
        (r"(\w+)\s+(?:inhibits?|suppresses?|blocks?|attenuates?)\s+(?:the\s+)?(?:phosphorylation|activity|expression)?\s*(?:of\s+)?(\w+)", "inhibitor", "target"),
        (r"(?:inhibition|suppression)\s+of\s+(\w+)\s+by\s+(\w+)", "target", "inhibitor"),
    ],
    "degradation": [
        (r"(\w+)\s+(?:promotes?|mediates?|induces?)\s+(?:the\s+)?(?:proteasomal\s+)?degradation\s+of\s+(\w+)", "e3_ligase", "substrate"),
        (r"(?:proteasomal\s+)?degradation\s+of\s+(\w+)\s+(?:by|via|through|mediated by)\s+(\w+)", "substrate", "e3_ligase"),
        (r"(\w+)\s+(?:targets?|marks?)\s+(\w+)\s+for\s+(?:proteasomal\s+)?degradation", "e3_ligase", "substrate"),
    ],
    "upstream": [
        (r"(?:upstream)\s+(?:kinase|regulator|effector|E3 ligase|ligase)\s+(\w+)", None, "upstream"),
        (r"(\w+)\s+(?:is|acts?\s+as)\s+(?:an?\s+)?upstream\s+(?:kinase|regulator|E3 ligase)", None, "upstream"),
    ],
    "downstream": [
        (r"(?:downstream)\s+(?:target|effector|substrate)\s+(\w+)", None, "downstream"),
        (r"(\w+)\s+(?:is|acts?\s+as)\s+(?:an?\s+)?downstream\s+(?:target|effector)", None, "downstream"),
    ],
}

# v8.10: Chain type patterns for ubiquitylation functional classification
CHAIN_TYPE_PATTERNS = [
    (r"K48[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K48"),
    (r"Lys48[- ]?(?:linked|polyubiquitin|chain)", "K48"),
    (r"K63[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K63"),
    (r"Lys63[- ]?(?:linked|polyubiquitin|chain)", "K63"),
    (r"K11[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K11"),
    (r"K27[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K27"),
    (r"K29[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K29"),
    (r"K33[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K33"),
    (r"K6[- ]?(?:linked|polyubiquitin|chain|ubiquitin)", "K6"),
    (r"M1[- ]?(?:linked|linear|ubiquitin|chain)", "M1"),
    (r"linear\s+(?:ubiquitin|polyubiquitin|chain)", "M1"),
    (r"mono[- ]?ubiquityl", "Mono"),
    (r"mono[- ]?ubiquitin", "Mono"),
    (r"multi[- ]?mono[- ]?ubiquityl", "Multi-mono"),
]

DISEASE_KEYWORDS = {
    "cancer": ["cancer", "carcinoma", "tumor", "tumour", "neoplasm", "malignant", "oncogenic", "leukemia", "lymphoma", "melanoma", "sarcoma", "glioma", "glioblastoma"],
    "cardiovascular": ["cardiac", "heart", "cardiovascular", "atherosclerosis", "hypertension", "cardiomyopathy", "ischemia", "arrhythmia"],
    "neurodegenerative": ["alzheimer", "parkinson", "neurodegeneration", "huntington", "dementia", "amyotrophic", "ALS", "prion"],
    "metabolic": ["diabetes", "obesity", "metabolic syndrome", "insulin resistance", "fatty liver", "NAFLD", "dyslipidemia"],
    "inflammatory": ["inflammation", "inflammatory", "autoimmune", "arthritis", "lupus", "colitis", "fibrosis"],
    "muscular": ["muscle", "muscular", "dystrophy", "myopathy", "atrophy", "sarcopenia"],
}


class RegulationExtractor:
    """Extracts regulation info and disease associations from text using patterns."""

    def extract_from_articles(
        self, articles: List[dict], gene: str, position: str
    ) -> dict:
        """
        Extract regulation information from a list of PubMed articles.

        Returns:
            {
                "upstream_regulators": [...],
                "downstream_targets": [...],
                "kinase_substrate": [...],
                "e3_substrate": [...],       # v8.10: E3 ligase-substrate pairs
                "dub_substrate": [...],      # v8.10: DUB-substrate pairs
                "chain_types": [...],        # v8.10: Detected ubiquitin chain types
                "diseases": [...],
                "regulation_evidence": [...],
            }
        """
        upstream = []
        downstream = []
        kinase_substrate = []
        e3_substrate = []
        dub_substrate = []
        chain_types_found = set()
        all_diseases = set()
        evidence = []

        for article in articles:
            text = f"{article.get('title', '')} {article.get('abstract', '')}"
            pmid = article.get("pmid", "")

            # Extract regulation patterns
            regs = self._extract_regulation(text, gene)
            for reg in regs:
                reg["pmid"] = pmid
                evidence.append(reg)

                if reg["type"] == "kinase":
                    kinase_substrate.append({
                        "kinase": reg["regulator"],
                        "substrate": reg["target"],
                        "pmid": pmid,
                        "evidence": reg["sentence"][:200],
                    })
                    upstream.append(reg["regulator"])
                elif reg["type"] == "e3_ligase":
                    e3_substrate.append({
                        "e3_ligase": reg["regulator"],
                        "substrate": reg["target"],
                        "pmid": pmid,
                        "evidence": reg["sentence"][:200],
                    })
                    upstream.append(reg["regulator"])
                elif reg["type"] == "dub":
                    dub_substrate.append({
                        "dub": reg["regulator"],
                        "substrate": reg["target"],
                        "pmid": pmid,
                        "evidence": reg["sentence"][:200],
                    })
                elif reg["type"] == "upstream":
                    upstream.append(reg["regulator"])
                elif reg["type"] == "downstream":
                    downstream.append(reg["target"])
                elif reg["type"] == "activator":
                    upstream.append(reg["regulator"])
                elif reg["type"] == "inhibitor":
                    upstream.append(reg["regulator"])

            # Extract chain types (v8.10)
            chain_types = self._extract_chain_types(text)
            chain_types_found.update(chain_types)

            # Extract diseases
            diseases = self._extract_diseases(text)
            all_diseases.update(diseases)

        # Deduplicate
        upstream = list(dict.fromkeys(u for u in upstream if u and u.lower() != gene.lower()))[:10]
        downstream = list(dict.fromkeys(d for d in downstream if d and d.lower() != gene.lower()))[:10]

        return {
            "upstream_regulators": upstream,
            "downstream_targets": downstream,
            "kinase_substrate": kinase_substrate[:5],
            "e3_substrate": e3_substrate[:5],
            "dub_substrate": dub_substrate[:5],
            "chain_types": sorted(chain_types_found),
            "diseases": sorted(all_diseases),
            "regulation_evidence": evidence[:20],
        }

    def _extract_regulation(self, text: str, gene: str) -> List[dict]:
        results = []
        sentences = re.split(r"[.!?]\s+", text)
        gene_lower = gene.lower()

        for sentence in sentences:
            if gene_lower not in sentence.lower():
                continue

            for category, patterns in REGULATION_PATTERNS.items():
                for pattern_tuple in patterns:
                    pattern = pattern_tuple[0]
                    for m in re.finditer(pattern, sentence, re.IGNORECASE):
                        groups = m.groups()
                        if len(groups) >= 2:
                            role1, role2 = pattern_tuple[1], pattern_tuple[2]
                            results.append({
                                "type": category,
                                "regulator": groups[0],
                                "target": groups[1],
                                "sentence": sentence.strip()[:300],
                            })
                        elif len(groups) == 1:
                            results.append({
                                "type": category,
                                "regulator": groups[0],
                                "target": gene,
                                "sentence": sentence.strip()[:300],
                            })
        return results

    def _extract_chain_types(self, text: str) -> List[str]:
        """v8.10: Extract ubiquitin chain types mentioned in text."""
        found = set()
        for pattern, chain_type in CHAIN_TYPE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                found.add(chain_type)
        return list(found)

    def _extract_diseases(self, text: str) -> List[str]:
        found = set()
        text_lower = text.lower()
        for category, keywords in DISEASE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    found.add(category)
                    break
        return list(found)
