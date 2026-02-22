"""
Regulation Extractor — pattern-based extraction of regulatory relationships from text.
Ported from ptm-rag-backend/src/regulationExtractor.ts and pattern_screening_engine.py.

Extracts upstream/downstream regulators, kinase-substrate relationships,
and disease associations from PubMed abstracts using regex patterns.
No LLM dependency.
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
    "activation": [
        (r"(\w+)\s+(?:activates?|activated|activation of)\s+(\w+)", "activator", "target"),
        (r"(\w+)\s+(?:induces?|induced|promotes?)\s+(?:the\s+)?(?:phosphorylation|activation)\s+of\s+(\w+)", "activator", "target"),
        (r"(\w+)\s+(?:signaling|pathway)\s+(?:activates?|promotes?)\s+(\w+)", "activator", "target"),
    ],
    "inhibition": [
        (r"(\w+)\s+(?:inhibits?|suppresses?|blocks?|attenuates?)\s+(?:the\s+)?(?:phosphorylation|activity|expression)?\s*(?:of\s+)?(\w+)", "inhibitor", "target"),
        (r"(?:inhibition|suppression)\s+of\s+(\w+)\s+by\s+(\w+)", "target", "inhibitor"),
    ],
    "upstream": [
        (r"(?:upstream)\s+(?:kinase|regulator|effector)\s+(\w+)", None, "upstream"),
        (r"(\w+)\s+(?:is|acts?\s+as)\s+(?:an?\s+)?upstream\s+(?:kinase|regulator)", None, "upstream"),
    ],
    "downstream": [
        (r"(?:downstream)\s+(?:target|effector|substrate)\s+(\w+)", None, "downstream"),
        (r"(\w+)\s+(?:is|acts?\s+as)\s+(?:an?\s+)?downstream\s+(?:target|effector)", None, "downstream"),
    ],
}

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
                "diseases": [...],
                "regulation_evidence": [...],
            }
        """
        upstream = []
        downstream = []
        kinase_substrate = []
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
                elif reg["type"] == "upstream":
                    upstream.append(reg["regulator"])
                elif reg["type"] == "downstream":
                    downstream.append(reg["target"])
                elif reg["type"] == "activator":
                    upstream.append(reg["regulator"])
                elif reg["type"] == "inhibitor":
                    upstream.append(reg["regulator"])

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

    def _extract_diseases(self, text: str) -> List[str]:
        found = set()
        text_lower = text.lower()
        for category, keywords in DISEASE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    found.add(category)
                    break
        return list(found)
