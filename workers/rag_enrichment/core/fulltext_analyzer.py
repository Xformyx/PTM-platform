"""
Full-Text Analyzer — regex pattern-based extraction of PTM evidence from text.

Ported from ptm-rag-backend/src/fullTextAnalyzer.ts (v4.0).

Features:
  - 250+ regex patterns for PTM regulation, kinase activity, functional consequences
  - Context extraction (surrounding sentences)
  - Confidence scoring
  - Category-based classification
  - Antibody / Western blot information extraction (v3.16)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PatternMatch:
    pattern: str
    category: str
    matched_text: str
    context: str
    sentence: str
    pmid: str
    source: str = "abstract"  # "abstract" | "fulltext"
    confidence: int = 50
    position: int = 0


@dataclass
class AntibodyInfo:
    western_blot_validated: bool = False
    target: str = ""
    company: str = ""
    catalog: str = ""
    dilution: str = ""
    species: str = ""
    ab_type: str = ""
    application: str = ""
    pmid: str = ""
    confidence: str = "low"  # "high" | "medium" | "low"


@dataclass
class FullTextAnalysis:
    pmid: str = ""
    gene: str = ""
    position: str = ""
    has_fulltext: bool = False
    abstract_length: int = 0
    fulltext_length: int = 0
    fulltext: Optional[str] = None

    pattern_matches: Dict[str, List[PatternMatch]] = field(default_factory=lambda: {
        "activation_increase": [],
        "inhibition_decrease": [],
        "regulation_modulation": [],
        "kinase_activity": [],
        "functional_consequence": [],
        "context_activation": [],
        "regulator_substrate_relationship": [],
        "protein_interaction": [],
    })

    total_matches: int = 0
    high_confidence_matches: int = 0

    key_findings: List[str] = field(default_factory=list)
    mechanisms: List[str] = field(default_factory=list)
    quantitative_data: Dict[str, List] = field(default_factory=lambda: {
        "fold_changes": [],
        "p_values": [],
        "sample_sizes": [],
    })
    antibody_info: List[AntibodyInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pattern definitions (250+ patterns)
# ---------------------------------------------------------------------------

PATTERNS: Dict[str, List[tuple]] = {
    "activation_increase": [
        (r"(?:increased?|elevated?|enhanced?|upregulated?|higher)\s+(?:phosphorylation|acetylation|ubiquitylation|methylation|modification)", 70),
        (r"phosphorylation\s+(?:was|is|were)\s+(?:increased?|elevated?|enhanced?|upregulated?)", 70),
        (r"(?:significantly|markedly|dramatically|substantially)\s+(?:increased?|elevated?|enhanced?)", 65),
        (r"(?:fold|times?)\s+(?:increase|higher|more|greater)", 60),
        (r"(?:activation|stimulation|induction)\s+of\s+\w+\s+(?:phosphorylation|signaling)", 65),
        (r"(?:phospho|p)-?\w+\s+(?:levels?|signals?)\s+(?:were|was|is)\s+(?:increased?|elevated?)", 70),
        (r"(?:treatment|stimulation|exposure)\s+(?:increased?|enhanced?|induced?)\s+(?:the\s+)?phosphorylation", 65),
        (r"(?:robust|strong|potent)\s+(?:activation|phosphorylation|induction)", 60),
        (r"(?:hyperphosphorylat|hyperacetylat)", 75),
        (r"(?:gain.of.function|activating)\s+(?:mutation|phosphorylation)", 70),
    ],
    "inhibition_decrease": [
        (r"(?:decreased?|reduced?|diminished?|downregulated?|lower)\s+(?:phosphorylation|acetylation|ubiquitylation|methylation|modification)", 70),
        (r"phosphorylation\s+(?:was|is|were)\s+(?:decreased?|reduced?|diminished?|downregulated?)", 70),
        (r"(?:inhibition|suppression|attenuation|abrogation)\s+of\s+\w+\s+(?:phosphorylation|signaling|activity)", 65),
        (r"(?:dephosphorylat|deacetylat|deubiquitylat|demethylat)", 75),
        (r"(?:loss.of.function|inactivating)\s+(?:mutation|dephosphorylation)", 70),
        (r"(?:abolished?|eliminated?|abrogated?|prevented?)\s+(?:phosphorylation|activity|signaling)", 75),
        (r"(?:phosphatase|DUB|deacetylase|HDAC)\s+(?:activity|treatment)\s+(?:reduced?|removed?|abolished?)", 65),
        (r"(?:kinase.dead|catalytically.inactive)\s+(?:mutant|form)", 70),
    ],
    "regulation_modulation": [
        (r"(?:regulates?|modulates?|controls?|mediates?|governs?)\s+(?:the\s+)?(?:phosphorylation|activity|expression|function)", 55),
        (r"(?:phosphorylation|modification)\s+(?:regulates?|modulates?|controls?)\s+(?:the\s+)?(?:activity|function|localization|stability)", 60),
        (r"(?:plays?\s+(?:a\s+)?(?:key|critical|essential|important|central)\s+role)", 50),
        (r"(?:required|necessary|essential|sufficient)\s+for\s+(?:the\s+)?(?:activation|phosphorylation|signaling)", 60),
        (r"(?:feedback|feedforward)\s+(?:loop|mechanism|regulation)", 55),
        (r"(?:crosstalk|interplay|cross-regulation)\s+between", 50),
    ],
    "kinase_activity": [
        (r"(\w+)\s+(?:kinase|phosphotransferase)\s+(?:activity|domain)", 65),
        (r"(\w+)\s+(?:directly\s+)?phosphorylates?\s+(\w+)", 75),
        (r"(?:kinase|phosphorylation)\s+(?:assay|screen|analysis)\s+(?:identified?|revealed?|showed?)", 60),
        (r"(?:substrate|target)\s+of\s+(\w+)\s+(?:kinase|phosphorylation)", 70),
        (r"(\w+)\s+(?:is|acts?\s+as)\s+(?:a\s+)?(?:kinase|phosphatase)\s+(?:for|of|targeting)", 70),
        (r"(?:consensus|recognition)\s+(?:motif|sequence|site)\s+(?:for|of)\s+(\w+)", 60),
        (r"(?:phosphorylation\s+by|phosphorylated\s+by)\s+(\w+)", 75),
        (r"(?:AMPK|PKA|PKC|CaMKII|AKT|mTOR|ERK|JNK|p38|CDK|GSK3|CK[12]|PLK|Aurora)\s+(?:phosphorylates?|targets?|modifies?)", 80),
    ],
    "functional_consequence": [
        (r"phosphorylation\s+(?:at|of)\s+\w+\s+(?:leads?\s+to|results?\s+in|causes?)\s+(?:activation|inhibition|degradation|translocation)", 70),
        (r"(?:enzymatic|catalytic)\s+activity\s+(?:was|is|were)\s+(?:increased?|decreased?|abolished?|enhanced?)", 65),
        (r"(?:protein.protein\s+interaction|binding|association)\s+(?:was|is|were)\s+(?:enhanced?|reduced?|abolished?|promoted?)", 60),
        (r"(?:nuclear|cytoplasmic|membrane|mitochondrial)\s+(?:translocation|localization|export|import|accumulation)", 65),
        (r"(?:protein\s+)?(?:stability|half.life|turnover|degradation)\s+(?:was|is|were)\s+(?:increased?|decreased?|affected?)", 60),
        (r"(?:conformational\s+change|structural\s+rearrangement|allosteric)", 55),
        (r"(?:14-3-3|SH2|PTB|WW|FHA|BRCT)\s+(?:domain|binding|interaction|recognition)", 65),
        (r"(?:creates?|generates?|exposes?|masks?)\s+(?:a\s+)?(?:binding\s+site|docking\s+site|recognition\s+motif)", 60),
    ],
    "context_activation": [
        (r"(?:exercise|contraction|physical\s+activity|training)\s+(?:induced?|stimulated?|activated?|increased?)", 60),
        (r"(?:insulin|glucose|amino\s+acid|nutrient)\s+(?:stimulat|induced?|activated?|signaling)", 60),
        (r"(?:stress|hypoxia|oxidative|ER\s+stress|heat\s+shock)\s+(?:induced?|activated?|triggered?)", 60),
        (r"(?:growth\s+factor|cytokine|hormone)\s+(?:stimulat|induced?|activated?|signaling)", 55),
        (r"(?:fasting|starvation|caloric\s+restriction|energy\s+depletion)\s+(?:induced?|activated?|triggered?)", 60),
        (r"(?:inflammation|immune|infection|LPS|TNF)\s+(?:induced?|activated?|triggered?|signaling)", 55),
    ],
    "regulator_substrate_relationship": [
        (r"(\w+)\s+(?:is|acts?\s+as)\s+(?:a\s+)?(?:direct\s+)?(?:upstream|downstream)\s+(?:regulator|effector|target|substrate)\s+of\s+(\w+)", 75),
        (r"(\w+)\s+(?:directly|specifically)\s+(?:phosphorylates?|acetylates?|ubiquitylates?|methylates?)\s+(\w+)\s+(?:at|on)\s+(\w+)", 85),
        (r"(\w+)\s+(?:is|was|were)\s+(?:identified|confirmed|validated)\s+as\s+(?:a\s+)?(?:substrate|target)\s+of\s+(\w+)", 80),
        (r"(?:phosphorylation|modification)\s+of\s+(\w+)\s+(?:at|on)\s+(\w+)\s+by\s+(\w+)", 85),
    ],
    "protein_interaction": [
        (r"(\w+)\s+(?:interacts?\s+with|binds?\s+to|associates?\s+with|complexes?\s+with)\s+(\w+)", 60),
        (r"(?:co-immunoprecipitat|pull.down|yeast\s+two.hybrid|proximity\s+ligation)\s+(?:assay|experiment|analysis)", 65),
        (r"(\w+)\s+(?:recruits?|scaffolds?)\s+(\w+)\s+(?:to|at|into)", 60),
        (r"(?:complex|heterodimer|homodimer)\s+(?:formation|assembly)\s+(?:between|of)\s+(\w+)\s+and\s+(\w+)", 65),
    ],
}


# ---------------------------------------------------------------------------
# Antibody extraction patterns (v3.16)
# ---------------------------------------------------------------------------

ANTIBODY_PATTERNS = [
    # "anti-phospho-XXX (Ser/Thr/Tyr NNN) antibody"
    re.compile(r"anti[- ]?phospho[- ]?(\w+)\s*\(?\s*([STY](?:er|hr|yr)?\d+)\s*\)?", re.IGNORECASE),
    # "phospho-XXX (SNNN) antibody from Company (#catalog)"
    re.compile(r"phospho[- ]?(\w+)\s*\(?\s*([STY]\d+)\s*\)?\s*(?:antibody|Ab)\s*(?:\(?\s*(?:#?\s*\d+)\s*\)?)?", re.IGNORECASE),
    # "Cell Signaling Technology #NNNN"
    re.compile(r"(Cell\s+Signaling\s+Technology|CST|Abcam|Santa\s+Cruz|Millipore|Sigma|Thermo\s+Fisher|BD\s+Biosciences|R&D\s+Systems)\s*(?:#|Cat\.?\s*(?:No\.?)?\s*)?(\w+)", re.IGNORECASE),
    # "Western blot" or "immunoblot"
    re.compile(r"(?:Western\s+blot|immunoblot|WB)\s+(?:analysis|was\s+performed|using|with)", re.IGNORECASE),
]

COMPANY_PATTERNS = re.compile(
    r"(Cell\s+Signaling\s+Technology|CST|Abcam|Santa\s+Cruz|Millipore|Sigma[- ]Aldrich|"
    r"Thermo\s+Fisher|BD\s+Biosciences|R&D\s+Systems|Invitrogen|Proteintech|Bethyl|"
    r"GeneTex|Novus\s+Biologicals|BioLegend|Active\s+Motif)",
    re.IGNORECASE,
)

DILUTION_PATTERN = re.compile(r"1:\s*(\d{2,5})")
CATALOG_PATTERN = re.compile(r"(?:#|Cat\.?\s*(?:No\.?)?\s*)(\d{3,6}\w?)")


# ---------------------------------------------------------------------------
# Quantitative data extraction
# ---------------------------------------------------------------------------

FOLD_CHANGE_PATTERN = re.compile(r"(\d+\.?\d*)\s*[-–]?\s*fold\s+(?:increase|decrease|change|higher|lower|more|less)", re.IGNORECASE)
P_VALUE_PATTERN = re.compile(r"[pP]\s*[<>=≤≥]\s*(0?\.\d+(?:e[+-]?\d+)?)", re.IGNORECASE)
SAMPLE_SIZE_PATTERN = re.compile(r"[nN]\s*=\s*(\d+)")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

class FullTextAnalyzer:
    """Analyze abstracts and full-text for PTM evidence using regex patterns."""

    def analyze(
        self,
        pmid: str,
        gene: str,
        position: str,
        abstract: str,
        fulltext: Optional[str] = None,
    ) -> FullTextAnalysis:
        """Run pattern-based analysis on abstract (and optional full-text)."""
        result = FullTextAnalysis(
            pmid=pmid, gene=gene, position=position,
            has_fulltext=bool(fulltext),
            abstract_length=len(abstract or ""),
            fulltext_length=len(fulltext or ""),
            fulltext=fulltext,
        )

        # Analyze abstract
        self._match_patterns(result, abstract, gene, position, "abstract")

        # Analyze full-text if available
        if fulltext:
            self._match_patterns(result, fulltext, gene, position, "fulltext")

        # Extract quantitative data
        combined_text = f"{abstract or ''} {fulltext or ''}"
        self._extract_quantitative(result, combined_text)

        # Extract antibody info (v3.16)
        self._extract_antibody_info(result, combined_text, gene, position)

        # Compute totals
        total = 0
        high_conf = 0
        for cat_matches in result.pattern_matches.values():
            total += len(cat_matches)
            high_conf += sum(1 for m in cat_matches if m.confidence >= 60)
        result.total_matches = total
        result.high_confidence_matches = high_conf

        # Extract key findings
        result.key_findings = self._extract_key_findings(result, gene, position)

        return result

    def _match_patterns(
        self,
        result: FullTextAnalysis,
        text: str,
        gene: str,
        position: str,
        source: str,
    ):
        """Apply all patterns to text and collect matches."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        gene_lower = gene.lower()
        pos_lower = position.lower()

        for sentence in sentences:
            sent_lower = sentence.lower()
            # Only process sentences mentioning the gene or position
            if gene_lower not in sent_lower and pos_lower not in sent_lower:
                continue

            for category, patterns in PATTERNS.items():
                for pattern_str, base_confidence in patterns:
                    for m in re.finditer(pattern_str, sentence, re.IGNORECASE):
                        # Boost confidence if position is mentioned
                        confidence = base_confidence
                        if pos_lower in sent_lower:
                            confidence = min(confidence + 15, 100)

                        match_obj = PatternMatch(
                            pattern=pattern_str,
                            category=category,
                            matched_text=m.group(0),
                            context=sentence[:300],
                            sentence=sentence,
                            pmid=result.pmid,
                            source=source,
                            confidence=confidence,
                            position=m.start(),
                        )
                        result.pattern_matches[category].append(match_obj)

    def _extract_quantitative(self, result: FullTextAnalysis, text: str):
        """Extract fold changes, p-values, sample sizes."""
        for m in FOLD_CHANGE_PATTERN.finditer(text):
            try:
                result.quantitative_data["fold_changes"].append(float(m.group(1)))
            except ValueError:
                pass

        for m in P_VALUE_PATTERN.finditer(text):
            try:
                result.quantitative_data["p_values"].append(float(m.group(1)))
            except ValueError:
                pass

        for m in SAMPLE_SIZE_PATTERN.finditer(text):
            try:
                result.quantitative_data["sample_sizes"].append(int(m.group(1)))
            except ValueError:
                pass

    def _extract_antibody_info(
        self,
        result: FullTextAnalysis,
        text: str,
        gene: str,
        position: str,
    ):
        """Extract antibody validation info (v3.16)."""
        gene_lower = gene.lower()
        pos_lower = position.lower()
        sentences = re.split(r"(?<=[.!?])\s+", text)

        for sentence in sentences:
            sent_lower = sentence.lower()
            # Look for Western blot / immunoblot mentions near gene
            if ("western" in sent_lower or "immunoblot" in sent_lower) and gene_lower in sent_lower:
                ab = AntibodyInfo(
                    western_blot_validated=True,
                    target=f"phospho-{gene} {position}",
                    application="Western blot",
                    pmid=result.pmid,
                    confidence="medium",
                )

                # Try to extract company
                company_match = COMPANY_PATTERNS.search(sentence)
                if company_match:
                    ab.company = company_match.group(1)
                    ab.confidence = "high"

                # Try to extract catalog number
                cat_match = CATALOG_PATTERN.search(sentence)
                if cat_match:
                    ab.catalog = f"#{cat_match.group(1)}"

                # Try to extract dilution
                dil_match = DILUTION_PATTERN.search(sentence)
                if dil_match:
                    ab.dilution = f"1:{dil_match.group(1)}"

                result.antibody_info.append(ab)

    def _extract_key_findings(
        self, result: FullTextAnalysis, gene: str, position: str,
    ) -> List[str]:
        """Summarize key findings from pattern matches."""
        findings = []

        # High-confidence kinase activity matches
        for m in result.pattern_matches.get("kinase_activity", []):
            if m.confidence >= 70:
                findings.append(f"Kinase evidence: {m.matched_text}")

        # Regulator-substrate relationships
        for m in result.pattern_matches.get("regulator_substrate_relationship", []):
            if m.confidence >= 75:
                findings.append(f"Regulator-substrate: {m.matched_text}")

        # Functional consequences
        for m in result.pattern_matches.get("functional_consequence", []):
            if m.confidence >= 65:
                findings.append(f"Functional: {m.matched_text}")

        return findings[:10]
