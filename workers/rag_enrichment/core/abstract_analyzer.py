"""
Abstract Analyzer — LLM-based analysis of PubMed abstracts for PTM signaling.

Ported from ptm-rag-backend/src/abstractAnalyzer.ts (v2.0 — PTM Signaling Optimized).

Uses LLM to extract:
  - PTM type and site information
  - Signaling network (upstream regulators, downstream effects)
  - Functional consequences (activity, interactions, localization)
  - Biological context (pathways, processes, disease relevance)
  - Experimental evidence and quantitative data
  - Relevance assessment with context alignment
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.llm_client import LLMClient
from .fulltext_analyzer import FullTextAnalysis, PatternMatch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AbstractAnalysis:
    pmid: str = ""
    gene: str = ""
    position: str = ""

    # Signaling network
    upstream_regulators: List[dict] = field(default_factory=list)
    downstream_effects: List[dict] = field(default_factory=list)
    co_regulators: List[dict] = field(default_factory=list)

    # Functional consequences
    functional_consequences: dict = field(default_factory=dict)

    # Biological context
    signaling_pathways: List[dict] = field(default_factory=list)
    cellular_processes: List[dict] = field(default_factory=list)
    disease_relevance: List[dict] = field(default_factory=list)

    # Experimental evidence
    experimental_methods: List[dict] = field(default_factory=list)
    mutations: List[dict] = field(default_factory=list)
    quantitative_data: dict = field(default_factory=dict)

    # Relevance
    relevance_score: int = 0
    relevance_reasons: List[str] = field(default_factory=list)
    context_alignment: dict = field(default_factory=dict)
    evidence_quality: str = ""
    novelty: str = ""

    key_findings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_analysis_prompt(
    abstract: str,
    gene: str,
    position: str,
    pattern_matches: Optional[Dict[str, List[PatternMatch]]] = None,
    experimental_context: Optional[dict] = None,
) -> str:
    """Build the LLM prompt for abstract analysis."""

    # Context info
    context_info = "No experimental context provided."
    if experimental_context:
        parts = []
        for key in ("cell_type", "treatment", "time_points", "biological_question"):
            val = experimental_context.get(key)
            if val:
                parts.append(f"- {key.replace('_', ' ').title()}: {val}")
        if parts:
            context_info = "Experimental Context:\n" + "\n".join(parts)

    # Pattern match summary
    pattern_summary = "No pattern matches found."
    if pattern_matches:
        all_matches: List[PatternMatch] = []
        for cat_matches in pattern_matches.values():
            all_matches.extend(cat_matches)
        if all_matches:
            lines = [f"Pattern Matches Found ({len(all_matches)}):"]
            for m in all_matches[:8]:
                lines.append(
                    f'- [{m.category}] "{m.matched_text}" (confidence: {m.confidence}%)\n'
                    f"  Context: {m.sentence[:150]}..."
                )
            pattern_summary = "\n".join(lines)

    prompt = f"""You are an expert in cellular signaling and post-translational modifications (PTMs).

Analyze the following PubMed abstract to extract PTM-related signaling information about {gene} {position}.

EXPERIMENTAL CONTEXT:
{context_info}

PATTERN MATCHES (from regex analysis):
{pattern_summary}

ABSTRACT:
\"\"\"{abstract}\"\"\"

EXTRACTION TASK:
Extract comprehensive PTM signaling information. If information is not available, use null or empty arrays.
Be precise and extract ONLY information explicitly stated in the abstract.

Return a JSON object with these keys:
{{
  "signalingNetwork": {{
    "upstreamRegulators": [
      {{"name": "...", "type": "kinase|phosphatase|...", "evidence": "direct|indirect|predicted",
        "mechanism": "...", "conditions": "...", "quantitativeData": "..."}}
    ],
    "downstreamEffects": [
      {{"target": "...", "effect": "activation|inhibition|...", "mechanism": "...",
        "magnitude": "...", "biologicalOutcome": "..."}}
    ],
    "coRegulators": [
      {{"name": "...", "relationship": "cooperative|antagonistic|sequential", "site": "..."}}
    ]
  }},
  "functionalConsequences": {{
    "enzymaticActivity": {{"affected": true/false, "direction": "...", "magnitude": "...", "mechanism": "..."}},
    "proteinInteractions": [{{"partner": "...", "effect": "...", "functionalImpact": "..."}}],
    "subcellularLocalization": {{"changed": true/false, "from": "...", "to": "...", "mechanism": "..."}},
    "proteinStability": {{"affected": true/false, "direction": "...", "mechanism": "..."}}
  }},
  "biologicalContext": {{
    "signalingPathways": [{{"pathway": "...", "role": "...", "regulation": "..."}}],
    "cellularProcesses": [{{"process": "...", "role": "...", "impact": "..."}}],
    "diseaseRelevance": [{{"disease": "...", "role": "...", "therapeuticImplication": "..."}}]
  }},
  "experimentalEvidence": {{
    "methods": [{{"technique": "...", "purpose": "...", "finding": "..."}}],
    "mutations": [{{"mutation": "...", "effect": "...", "phenotype": "..."}}],
    "quantitativeData": {{
      "foldChanges": ["..."], "pValues": ["..."], "kinetics": ["..."]
    }}
  }},
  "relevanceAssessment": {{
    "relevanceScore": 0-100,
    "relevanceReasons": ["..."],
    "contextAlignment": {{
      "cellTypeMatch": true/false,
      "treatmentMatch": true/false,
      "biologicalQuestionMatch": true/false
    }},
    "evidenceQuality": "direct experimental evidence|indirect evidence|...",
    "novelty": "novel finding|confirmation of known|..."
  }},
  "keyFindings": ["3-5 most important findings"]
}}

Output JSON only, no markdown code blocks."""

    return prompt


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------

class AbstractAnalyzer:
    """LLM-based abstract analyzer for PTM signaling information."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def analyze(
        self,
        pmid: str,
        abstract: str,
        gene: str,
        position: str,
        pattern_analysis: Optional[FullTextAnalysis] = None,
        experimental_context: Optional[dict] = None,
    ) -> AbstractAnalysis:
        """
        Analyze a PubMed abstract using LLM.

        Args:
            pmid: PubMed ID
            abstract: Abstract text
            gene: Gene name
            position: PTM position (e.g., S79)
            pattern_analysis: Optional pre-computed pattern analysis
            experimental_context: Optional experimental context dict

        Returns:
            AbstractAnalysis with extracted signaling information.
        """
        result = AbstractAnalysis(pmid=pmid, gene=gene, position=position)

        if not abstract or len(abstract.strip()) < 50:
            logger.warning(f"[AbstractAnalyzer] Skipping {pmid}: abstract too short")
            return result

        # Build prompt
        pattern_matches = pattern_analysis.pattern_matches if pattern_analysis else None
        prompt = _build_analysis_prompt(
            abstract, gene, position, pattern_matches, experimental_context,
        )

        # Call LLM with retry
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                response = self.llm.generate(
                    prompt=prompt,
                    system_prompt="You are an expert in cellular signaling and PTM biology. Output valid JSON only.",
                    temperature=0.3,
                    max_tokens=3000,
                )
                parsed = self._parse_response(response)
                if parsed:
                    result = self._build_result(pmid, gene, position, parsed)
                    logger.info(f"[AbstractAnalyzer] {pmid}: score={result.relevance_score}, "
                                f"findings={len(result.key_findings)}")
                    return result

            except Exception as e:
                logger.warning(f"[AbstractAnalyzer] Attempt {attempt} failed for {pmid}: {e}")

        return result

    def _parse_response(self, response: str) -> Optional[dict]:
        """Parse JSON from LLM response."""
        text = response.strip()
        # Remove markdown code blocks
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)

        # Find JSON object
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            logger.error("[AbstractAnalyzer] No JSON found in response")
            return None

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"[AbstractAnalyzer] JSON parse error: {e}")
            return None

    def _build_result(self, pmid: str, gene: str, position: str, data: dict) -> AbstractAnalysis:
        """Build AbstractAnalysis from parsed LLM response."""
        result = AbstractAnalysis(pmid=pmid, gene=gene, position=position)

        # Signaling network
        network = data.get("signalingNetwork", {})
        result.upstream_regulators = network.get("upstreamRegulators", [])
        result.downstream_effects = network.get("downstreamEffects", [])
        result.co_regulators = network.get("coRegulators", [])

        # Functional consequences
        result.functional_consequences = data.get("functionalConsequences", {})

        # Biological context
        bio = data.get("biologicalContext", {})
        result.signaling_pathways = bio.get("signalingPathways", [])
        result.cellular_processes = bio.get("cellularProcesses", [])
        result.disease_relevance = bio.get("diseaseRelevance", [])

        # Experimental evidence
        exp = data.get("experimentalEvidence", {})
        result.experimental_methods = exp.get("methods", [])
        result.mutations = exp.get("mutations", [])
        result.quantitative_data = exp.get("quantitativeData", {})

        # Relevance
        rel = data.get("relevanceAssessment", {})
        result.relevance_score = rel.get("relevanceScore", 0)
        result.relevance_reasons = rel.get("relevanceReasons", [])
        result.context_alignment = rel.get("contextAlignment", {})
        result.evidence_quality = rel.get("evidenceQuality", "")
        result.novelty = rel.get("novelty", "")

        result.key_findings = data.get("keyFindings", [])

        return result
