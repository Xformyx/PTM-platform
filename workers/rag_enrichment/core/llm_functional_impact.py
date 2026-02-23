"""
LLM Functional Impact Analyzer — predicts functional consequences of PTM events.

Ported from ptm-rag-backend/src/llmFunctionalImpact.ts (v2.0).

Features:
  - Predicts functional impact of PTM on protein activity, interactions, localization
  - Integrates PubMed evidence, UniProt data, pathway context
  - Cell signaling interpretation with biological meaning
  - Context-aware analysis aligned with experimental conditions
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class FunctionalImpactResult:
    gene: str = ""
    position: str = ""
    ptm_type: str = ""

    # Core predictions
    activity_impact: dict = field(default_factory=dict)
    interaction_changes: List[dict] = field(default_factory=list)
    localization_changes: dict = field(default_factory=dict)
    stability_impact: dict = field(default_factory=dict)

    # Signaling interpretation
    signaling_interpretation: str = ""
    pathway_effects: List[dict] = field(default_factory=list)
    biological_processes: List[dict] = field(default_factory=list)

    # Context-specific
    context_specific_effects: List[dict] = field(default_factory=list)
    therapeutic_implications: List[dict] = field(default_factory=list)

    # Confidence
    overall_confidence: str = ""
    evidence_summary: str = ""
    key_findings: List[str] = field(default_factory=list)


def _build_impact_prompt(
    gene: str,
    position: str,
    ptm_type: str,
    ptm_log2fc: float,
    protein_log2fc: float,
    pubmed_evidence: List[dict],
    uniprot_info: Optional[dict],
    kegg_pathways: List[str],
    string_interactions: List[str],
    experimental_context: Optional[dict],
) -> str:
    """Build prompt for functional impact prediction."""

    # PTM change description
    ptm_direction = "increased" if ptm_log2fc > 0 else "decreased" if ptm_log2fc < 0 else "unchanged"
    prot_direction = "increased" if protein_log2fc > 0 else "decreased" if protein_log2fc < 0 else "unchanged"

    # UniProt info
    uniprot_text = "No UniProt data."
    if uniprot_info:
        parts = []
        if uniprot_info.get("function_summary"):
            parts.append(f"Function: {uniprot_info['function_summary'][:300]}")
        if uniprot_info.get("subcellular_location"):
            parts.append(f"Localization: {', '.join(uniprot_info['subcellular_location'][:5])}")
        if parts:
            uniprot_text = "UniProt Info:\n" + "\n".join(parts)

    # PubMed evidence
    evidence_text = "No PubMed evidence."
    if pubmed_evidence:
        lines = [f"PubMed Evidence ({len(pubmed_evidence)} articles):"]
        for a in pubmed_evidence[:5]:
            lines.append(f"- PMID {a.get('pmid', '?')}: {(a.get('abstract') or '')[:200]}...")
        evidence_text = "\n".join(lines)

    # Pathways and interactions
    pathway_text = f"KEGG Pathways: {', '.join(kegg_pathways[:10])}" if kegg_pathways else "No pathway data."
    interaction_text = f"STRING Interactions: {', '.join(string_interactions[:10])}" if string_interactions else "No interaction data."

    # Context
    context_text = "No experimental context."
    if experimental_context:
        parts = []
        for key in ("cell_type", "tissue", "treatment", "organism", "biological_question", "time_points"):
            val = experimental_context.get(key)
            if val:
                parts.append(f"- {key.replace('_', ' ').title()}: {val}")
        if parts:
            context_text = "Experimental Context:\n" + "\n".join(parts)

    return f"""You are an expert in cellular signaling, PTM biology, and cell signaling networks.

TASK: Predict the functional impact of {ptm_type} change at {gene} {position}.

OBSERVATION:
- {ptm_type} at {position}: {ptm_direction} (log2FC = {ptm_log2fc:.2f})
- Protein expression: {prot_direction} (log2FC = {protein_log2fc:.2f})

{context_text}

{uniprot_text}

{pathway_text}

{interaction_text}

{evidence_text}

IMPORTANT: Focus on CELL SIGNALING biological meaning. Do not just describe the PTM itself.
Explain what this PTM change means for the signaling network, downstream effects, and biological outcomes.

Return a JSON object:
{{
  "activityImpact": {{
    "affected": true/false,
    "direction": "activation|inhibition|modulation",
    "mechanism": "...",
    "magnitude": "strong|moderate|mild",
    "evidence": "..."
  }},
  "interactionChanges": [
    {{"partner": "...", "effect": "enhanced|reduced|abolished|created", "mechanism": "...", "functionalOutcome": "..."}}
  ],
  "localizationChanges": {{
    "changed": true/false, "from": "...", "to": "...", "mechanism": "...", "functionalImpact": "..."
  }},
  "stabilityImpact": {{
    "affected": true/false, "direction": "stabilized|destabilized", "mechanism": "...", "halfLifeChange": "..."
  }},
  "signalingInterpretation": "2-3 sentence interpretation of what this PTM change means for cell signaling",
  "pathwayEffects": [
    {{"pathway": "...", "effect": "activation|inhibition|modulation", "mechanism": "...", "biologicalOutcome": "..."}}
  ],
  "biologicalProcesses": [
    {{"process": "...", "impact": "...", "mechanism": "..."}}
  ],
  "contextSpecificEffects": [
    {{"context": "...", "effect": "...", "significance": "..."}}
  ],
  "therapeuticImplications": [
    {{"target": "...", "approach": "...", "rationale": "..."}}
  ],
  "overallConfidence": "high|medium|low",
  "evidenceSummary": "brief summary of evidence quality",
  "keyFindings": ["3-5 most important findings about functional impact"]
}}

Output JSON only, no markdown code blocks."""


class LLMFunctionalImpact:
    """Predicts functional consequences of PTM events using LLM."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def analyze(
        self,
        gene: str,
        position: str,
        ptm_type: str = "Phosphorylation",
        ptm_log2fc: float = 0.0,
        protein_log2fc: float = 0.0,
        pubmed_articles: Optional[List[dict]] = None,
        uniprot_info: Optional[dict] = None,
        kegg_pathways: Optional[List[str]] = None,
        string_interactions: Optional[List[str]] = None,
        experimental_context: Optional[dict] = None,
    ) -> FunctionalImpactResult:
        """
        Predict functional impact of a PTM event.

        Returns:
            FunctionalImpactResult with predicted impacts.
        """
        result = FunctionalImpactResult(gene=gene, position=position, ptm_type=ptm_type)

        prompt = _build_impact_prompt(
            gene, position, ptm_type,
            ptm_log2fc, protein_log2fc,
            pubmed_articles or [], uniprot_info,
            kegg_pathways or [], string_interactions or [],
            experimental_context,
        )

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an expert in PTM functional biology and cell signaling. Output valid JSON only.",
                temperature=0.4,
                max_tokens=3000,
            )
            parsed = self._parse_response(response)
            if parsed:
                result = self._build_result(gene, position, ptm_type, parsed)

        except Exception as e:
            logger.error(f"[LLMFunctionalImpact] Failed for {gene} {position}: {e}")

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

    def _build_result(self, gene: str, position: str, ptm_type: str, data: dict) -> FunctionalImpactResult:
        result = FunctionalImpactResult(gene=gene, position=position, ptm_type=ptm_type)

        result.activity_impact = data.get("activityImpact", {})
        result.interaction_changes = data.get("interactionChanges", [])
        result.localization_changes = data.get("localizationChanges", {})
        result.stability_impact = data.get("stabilityImpact", {})
        result.signaling_interpretation = data.get("signalingInterpretation", "")
        result.pathway_effects = data.get("pathwayEffects", [])
        result.biological_processes = data.get("biologicalProcesses", [])
        result.context_specific_effects = data.get("contextSpecificEffects", [])
        result.therapeutic_implications = data.get("therapeuticImplications", [])
        result.overall_confidence = data.get("overallConfidence", "low")
        result.evidence_summary = data.get("evidenceSummary", "")
        result.key_findings = data.get("keyFindings", [])

        return result
