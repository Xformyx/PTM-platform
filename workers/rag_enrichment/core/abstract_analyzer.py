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
    ptm_type: str = "phosphorylation",
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
      {{"name": "...", "type": "kinase|phosphatase|e3_ligase|dub|...", "evidence": "direct|indirect|predicted",
        "mechanism": "...", "conditions": "...", "quantitativeData": "..."}}
    ],
    "e3Ligases": [
      {{"name": "...", "family": "RING|HECT|RBR", "evidence": "direct|indirect|predicted",
        "chainType": "K48|K63|K11|K27|mono|...", "function": "degradation|signaling|DNA_repair|..."}}
    ],
    "dubs": [
      {{"name": "...", "family": "USP|OTU|UCH|JAMM|...", "evidence": "direct|indirect|predicted",
        "function": "stabilization|deubiquitylation|..."}}
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

    # Add ubiquitylation-specific instructions
    ptm_lower = (ptm_type or "").lower()
    if "ubiquityl" in ptm_lower or "ubiquitin" in ptm_lower:
        prompt = prompt.replace(
            "Output JSON only, no markdown code blocks.",
            """IMPORTANT for ubiquitylation analysis:
- In signalingNetwork.e3Ligases: list ALL E3 ubiquitin ligases mentioned (RING/HECT/RBR families, SCF complex, APC/C, MDM2, NEDD4, CHIP, PARKIN, TRAF6, TRIM proteins, FBXW proteins, RNF proteins, etc.)
- In signalingNetwork.dubs: list ALL deubiquitylases mentioned (USP, UCH, OTU, JAMM family members)
- In signalingNetwork.upstreamRegulators: include E3 ligases and DUBs with type='e3_ligase' or type='dub'
- Identify ubiquitin chain types (K48=degradation, K63=signaling, K11=cell cycle, mono=signaling)
- Note if ubiquitylation leads to proteasomal degradation or non-degradative signaling

Output JSON only, no markdown code blocks."""
        )

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
        pmid: str = "",
        abstract: str = "",
        gene: str = "",
        position: str = "",
        pattern_analysis: Optional[FullTextAnalysis] = None,
        experimental_context: Optional[dict] = None,
        ptm_type: str = "phosphorylation",
        articles: Optional[list] = None,
    ) -> AbstractAnalysis:
        """Analyze PTM signaling from abstract(s). Accepts either pmid+abstract or articles list."""
        # If articles list is provided, analyze each and return merged result
        if articles:
            merged = AbstractAnalysis(pmid="merged", gene=gene, position=position)
            for art in articles:
                if not isinstance(art, dict):
                    continue
                art_pmid = art.get("pmid", "")
                art_abstract = art.get("abstract", "") or art.get("text", "")
                if not art_abstract or len(art_abstract.strip()) < 50:
                    continue
                result = self._analyze_single(
                    pmid=art_pmid, abstract=art_abstract, gene=gene,
                    position=position, ptm_type=ptm_type,
                )
                # Merge results
                merged.upstream_regulators.extend(result.upstream_regulators)
                merged.downstream_effects.extend(result.downstream_effects)
                merged.key_findings.extend(result.key_findings)
                if result.relevance_score > merged.relevance_score:
                    merged.relevance_score = result.relevance_score
                    merged.signaling_pathways = result.signaling_pathways
                    merged.cellular_processes = result.cellular_processes
            return merged
        # Single abstract mode
        return self._analyze_single(
            pmid=pmid, abstract=abstract, gene=gene, position=position,
            pattern_analysis=pattern_analysis, experimental_context=experimental_context,
            ptm_type=ptm_type,
        )

    def _analyze_single(
        self,
        pmid: str,
        abstract: str,
        gene: str,
        position: str,
        pattern_analysis: Optional[FullTextAnalysis] = None,
        experimental_context: Optional[dict] = None,
        ptm_type: str = "phosphorylation",
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
            abstract, gene, position, pattern_matches, experimental_context, ptm_type,
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

        # Ubiquitylation-specific: merge E3 ligases and DUBs into upstream_regulators
        e3_ligases = network.get("e3Ligases", [])
        dubs = network.get("dubs", [])
        if e3_ligases:
            for e3 in e3_ligases:
                if isinstance(e3, dict) and e3.get("name"):
                    result.upstream_regulators.append({
                        "name": e3["name"],
                        "type": "e3_ligase",
                        "evidence": e3.get("evidence", "predicted"),
                        "mechanism": f"E3 ligase ({e3.get('family', 'unknown')} family), chain: {e3.get('chainType', 'unknown')}, function: {e3.get('function', 'unknown')}",
                    })
        if dubs:
            for dub in dubs:
                if isinstance(dub, dict) and dub.get("name"):
                    result.upstream_regulators.append({
                        "name": dub["name"],
                        "type": "dub",
                        "evidence": dub.get("evidence", "predicted"),
                        "mechanism": f"DUB ({dub.get('family', 'unknown')} family), function: {dub.get('function', 'unknown')}",
                    })

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
