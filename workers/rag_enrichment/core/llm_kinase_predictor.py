"""
LLM Kinase Predictor — predicts upstream kinases for PTM sites using LLM.

Ported from ptm-rag-backend/src/llmKinasePredictor.ts (v2.0).

Features:
  - Context-aware kinase prediction using LLM
  - Integrates PubMed evidence and KEA3 enrichment data
  - Confidence scoring and evidence grading
  - Multi-PTM type support (kinase, E3 ligase, acetyltransferase, etc.)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class KinasePrediction:
    kinase: str = ""
    confidence: str = ""  # "high" | "medium" | "low"
    evidence_type: str = ""  # "direct" | "indirect" | "predicted" | "computational"
    mechanism: str = ""
    evidence_sources: List[str] = field(default_factory=list)
    consensus_motif: str = ""
    known_substrates: List[str] = field(default_factory=list)
    biological_context: str = ""
    score: float = 0.0


@dataclass
class KinasePredictionResult:
    gene: str = ""
    position: str = ""
    ptm_type: str = ""
    predicted_kinases: List[KinasePrediction] = field(default_factory=list)
    signaling_context: str = ""
    prediction_rationale: str = ""
    alternative_regulators: List[str] = field(default_factory=list)


def _build_kinase_prompt(
    gene: str,
    position: str,
    ptm_type: str,
    pubmed_evidence: List[dict],
    kea3_results: Optional[dict],
    experimental_context: Optional[dict],
) -> str:
    """Build prompt for kinase prediction."""

    # Determine regulator type based on PTM type
    ptm_lower = (ptm_type or "phosphorylation").lower()
    if "ubiquityl" in ptm_lower or "ubiquitin" in ptm_lower:
        regulator_type = "E3 ubiquitin ligase"
        regulator_examples = "MDM2, NEDD4, CHIP, SCF complex, APC/C"
    elif "acetyl" in ptm_lower:
        regulator_type = "acetyltransferase (HAT/KAT)"
        regulator_examples = "p300/CBP, GCN5, TIP60, PCAF, MOF"
    elif "methyl" in ptm_lower:
        regulator_type = "methyltransferase"
        regulator_examples = "SET7/9, PRMT1, EZH2, DOT1L, G9a"
    else:
        regulator_type = "kinase"
        regulator_examples = "AMPK, PKA, PKC, AKT, mTOR, ERK1/2, CaMKII"

    # PubMed evidence summary
    evidence_text = "No PubMed evidence available."
    if pubmed_evidence:
        lines = [f"PubMed Evidence ({len(pubmed_evidence)} articles):"]
        for a in pubmed_evidence[:8]:
            lines.append(
                f"- PMID {a.get('pmid', '?')}: {a.get('title', '')[:120]}\n"
                f"  Abstract: {(a.get('abstract') or '')[:200]}..."
            )
        evidence_text = "\n".join(lines)

    # KEA3 results
    kea3_text = "No KEA3 enrichment data."
    if kea3_results and kea3_results.get("top_kinases"):
        lines = ["KEA3 Kinase Enrichment Results:"]
        for k in kea3_results["top_kinases"][:5]:
            lines.append(f"- {k.get('kinase', '?')} (rank: {k.get('rank')}, score: {k.get('score', 0):.2f})")
        kea3_text = "\n".join(lines)

    # Experimental context
    context_text = "No experimental context."
    if experimental_context:
        parts = []
        for key in ("cell_type", "tissue", "treatment", "organism", "biological_question"):
            val = experimental_context.get(key)
            if val:
                parts.append(f"- {key.replace('_', ' ').title()}: {val}")
        if parts:
            context_text = "Experimental Context:\n" + "\n".join(parts)

    return f"""You are an expert in cellular signaling and post-translational modifications.

TASK: Predict the most likely {regulator_type}(s) responsible for the {ptm_type} of {gene} at position {position}.

{context_text}

{evidence_text}

{kea3_text}

Based on the evidence above, predict the top {regulator_type}(s) for {gene} {position}.
Consider: known {regulator_type} examples include {regulator_examples}.

Return a JSON object:
{{
  "predictedKinases": [
    {{
      "kinase": "name",
      "confidence": "high|medium|low",
      "evidenceType": "direct|indirect|predicted|computational",
      "mechanism": "brief mechanism description",
      "evidenceSources": ["PMID:xxx", "KEA3", ...],
      "consensusMotif": "if applicable",
      "knownSubstrates": ["other known substrates"],
      "biologicalContext": "when/where this regulation occurs",
      "score": 0.0-1.0
    }}
  ],
  "signalingContext": "overall signaling context description",
  "predictionRationale": "reasoning for the predictions",
  "alternativeRegulators": ["other possible regulators"]
}}

Output JSON only, no markdown code blocks."""


class LLMKinasePredictor:
    """Predicts upstream kinases/regulators using LLM with evidence integration."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def predict(
        self,
        gene: str,
        position: str,
        ptm_type: str = "Phosphorylation",
        pubmed_articles: Optional[List[dict]] = None,
        kea3_results: Optional[dict] = None,
        experimental_context: Optional[dict] = None,
    ) -> KinasePredictionResult:
        """
        Predict upstream kinases/regulators for a PTM site.

        Args:
            gene: Gene name (e.g., "ACC1")
            position: PTM position (e.g., "S79")
            ptm_type: PTM type (e.g., "Phosphorylation", "Ubiquitylation")
            pubmed_articles: List of PubMed article dicts
            kea3_results: KEA3 enrichment results
            experimental_context: Experimental context dict

        Returns:
            KinasePredictionResult with predicted kinases.
        """
        result = KinasePredictionResult(gene=gene, position=position, ptm_type=ptm_type)

        prompt = _build_kinase_prompt(
            gene, position, ptm_type,
            pubmed_articles or [], kea3_results, experimental_context,
        )

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an expert in kinase-substrate relationships and PTM biology. Output valid JSON only.",
                temperature=0.3,
                max_tokens=2000,
            )
            parsed = self._parse_response(response)
            if parsed:
                result = self._build_result(gene, position, ptm_type, parsed)

        except Exception as e:
            logger.error(f"[LLMKinasePredictor] Failed for {gene} {position}: {e}")

        return result

    def _parse_response(self, response: str) -> Optional[dict]:
        text = response.strip()
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _build_result(self, gene: str, position: str, ptm_type: str, data: dict) -> KinasePredictionResult:
        result = KinasePredictionResult(gene=gene, position=position, ptm_type=ptm_type)

        for k in data.get("predictedKinases", []):
            pred = KinasePrediction(
                kinase=k.get("kinase", ""),
                confidence=k.get("confidence", "low"),
                evidence_type=k.get("evidenceType", "predicted"),
                mechanism=k.get("mechanism", ""),
                evidence_sources=k.get("evidenceSources", []),
                consensus_motif=k.get("consensusMotif", ""),
                known_substrates=k.get("knownSubstrates", []),
                biological_context=k.get("biologicalContext", ""),
                score=float(k.get("score", 0)),
            )
            result.predicted_kinases.append(pred)

        result.signaling_context = data.get("signalingContext", "")
        result.prediction_rationale = data.get("predictionRationale", "")
        result.alternative_regulators = data.get("alternativeRegulators", [])

        return result
