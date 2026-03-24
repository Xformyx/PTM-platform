"""
PTM Vocabulary Dictionary v1.0

Single source of truth for PTM type-specific terminology.
Used by:
  - writer_node.py: Injects correct vocabulary into LLM prompts
  - report_postprocessor.py: Applies regex-based term corrections
  - temporal_comovement_node.py: Uses correct labels for cluster patterns

Design principle:
  Instead of relying on LLM prompt instructions alone (which LLMs often ignore),
  this module provides:
  1. A vocabulary dictionary that is injected into every prompt
  2. A comprehensive regex replacement table for post-processing
  3. Exception patterns for legitimate cross-PTM references

Adding a new PTM type:
  1. Add a new entry to PTM_VOCABULARY with all required keys
  2. Add a new entry to PTM_TERM_CORRECTIONS with wrong_terms and exceptions
  3. The rest of the system will automatically pick up the new PTM type
"""

from typing import Dict, List, Optional, Tuple
import re


# ============================================================================
# PTM VOCABULARY DICTIONARY
# ============================================================================
# Each PTM type defines its own complete vocabulary for:
#   - modification_name: The canonical name of the PTM
#   - modification_verb: Active verb form (e.g., "ubiquitylated")
#   - omics_name: The -omics study name (e.g., "Ubiquitylomics")
#   - target_residue: Primary target amino acid(s)
#   - site_prefix: Prefix for site nomenclature (e.g., "Lys" for K)
#   - enzyme_writer: The enzyme that writes/adds the modification
#   - enzyme_eraser: The enzyme that removes the modification
#   - enzyme_writer_generic: Generic term for the writer enzyme class
#   - enzyme_eraser_generic: Generic term for the eraser enzyme class
#   - enzyme_substrate_term: How to describe enzyme-substrate relationships
#   - chain_types: (ubiquitylation only) Ubiquitin chain type information
#   - degradation_pathway: Primary degradation pathway
#   - signaling_role: Non-degradative signaling description
#   - wrong_omics_terms: Terms from OTHER PTM types that should never appear
#   - system_prompt_addon: Additional system prompt text for this PTM type

PTM_VOCABULARY: Dict[str, Dict] = {
    "phosphorylation": {
        "modification_name": "phosphorylation",
        "modification_name_cap": "Phosphorylation",
        "modification_verb": "phosphorylated",
        "modification_verb_cap": "Phosphorylated",
        "de_modification": "dephosphorylation",
        "de_modification_cap": "Dephosphorylation",
        "omics_name": "Phosphoproteomic",
        "omics_name_lower": "phosphoproteomic",
        "omics_study": "Phosphoproteomics",
        "target_residues": ["Ser", "Thr", "Tyr"],
        "site_prefixes": ["Ser", "Thr", "Tyr", "S", "T", "Y"],
        "enzyme_writer_generic": "kinase",
        "enzyme_writer_generic_cap": "Kinase",
        "enzyme_writer_plural": "kinases",
        "enzyme_eraser_generic": "phosphatase",
        "enzyme_eraser_generic_cap": "Phosphatase",
        "enzyme_eraser_plural": "phosphatases",
        "enzyme_substrate_term": "kinase-substrate",
        "enzyme_substrate_term_cap": "Kinase-Substrate",
        "enrichment_term": "kinase enrichment",
        "enrichment_term_cap": "Kinase Enrichment",
        "degradation_pathway": None,  # phosphorylation doesn't directly cause degradation
        "signaling_role": "signal transduction, enzyme activation/inhibition, protein-protein interaction regulation",
        "binary_event_term": "binary phosphorylation event",
        "dynamics_term": "phosphorylation dynamics",
        "profiling_term": "phosphorylation profiling",
        "modification_at_site": "phosphorylation at {site} of {gene}",
        # Terms from OTHER PTM types that should NOT appear in this report
        "forbidden_substitutions": {
            # pattern → replacement (only when appearing in wrong context)
            r'\bubiquitylation sites?\b': 'phosphorylation sites',
            r'\bubiquitylation levels?\b': 'phosphorylation levels',
            r'\bubiquitylation changes?\b': 'phosphorylation changes',
            r'\bubiquitylation dynamics?\b': 'phosphorylation dynamics',
            r'\bubiquitylation patterns?\b': 'phosphorylation patterns',
            r'\bubiquitylation events?\b': 'phosphorylation events',
            r'\bubiquitylation status\b': 'phosphorylation status',
            r'\bubiquitylation state\b': 'phosphorylation state',
            r'\bubiquitylation data\b': 'phosphorylation data',
            r'\bE3 ligase-substrate\b': 'kinase-substrate',
            r'\bE3 ligase enrichment\b': 'kinase enrichment',
            r'\bUbiquitylomics\b': 'Phosphoproteomics',
            r'\bubiquitylomics\b': 'phosphoproteomics',
        },
        "exceptions": [
            r'ubiquitylation.{0,15}cross.?talk',
            r'cross.?talk.{0,15}(?:between|of).{0,15}ubiquitylation',
            r'(?:between|of)\s+phosphorylation\s+and\s+ubiquitylation',
            r'(?:between|of)\s+ubiquitylation\s+and\s+phosphorylation',
            r'ubiquitin-?dependent\s+degradation',
            r'proteasome',
            r'phospho-?degron',
        ],
    },

    "ubiquitylation": {
        "modification_name": "ubiquitylation",
        "modification_name_cap": "Ubiquitylation",
        "modification_verb": "ubiquitylated",
        "modification_verb_cap": "Ubiquitylated",
        "de_modification": "deubiquitylation",
        "de_modification_cap": "Deubiquitylation",
        "omics_name": "Ubiquitylomics",
        "omics_name_lower": "ubiquitylomics",
        "omics_study": "Ubiquitylomics",
        "target_residues": ["Lys"],
        "site_prefixes": ["Lys", "K"],
        "enzyme_writer_generic": "E3 ubiquitin ligase",
        "enzyme_writer_generic_cap": "E3 Ubiquitin Ligase",
        "enzyme_writer_plural": "E3 ubiquitin ligases",
        "enzyme_eraser_generic": "deubiquitylase (DUB)",
        "enzyme_eraser_generic_cap": "Deubiquitylase (DUB)",
        "enzyme_eraser_plural": "deubiquitylases (DUBs)",
        "enzyme_substrate_term": "E3 ligase-substrate",
        "enzyme_substrate_term_cap": "E3 Ligase-Substrate",
        "enrichment_term": "E3 ligase enrichment",
        "enrichment_term_cap": "E3 Ligase Enrichment",
        "degradation_pathway": "ubiquitin-proteasome system (UPS)",
        "signaling_role": "non-degradative signaling (K63), receptor trafficking (mono-Ub), DNA repair (K6/K63), immune signaling (M1/K27)",
        "binary_event_term": "binary ubiquitylation event",
        "dynamics_term": "ubiquitylation dynamics",
        "profiling_term": "ubiquitylation profiling",
        "modification_at_site": "ubiquitylation at {site} of {gene}",
        # Terms from OTHER PTM types that should NOT appear in this report
        "forbidden_substitutions": {
            # === Core term replacements ===
            r'\bphosphorylation sites?\b': 'ubiquitylation sites',
            r'\bphosphorylation levels?\b': 'ubiquitylation levels',
            r'\bphosphorylation changes?\b': 'ubiquitylation changes',
            r'\bphosphorylation dynamics?\b': 'ubiquitylation dynamics',
            r'\bphosphorylation patterns?\b': 'ubiquitylation patterns',
            r'\bphosphorylation events?\b': 'ubiquitylation events',
            r'\bphosphorylation status\b': 'ubiquitylation status',
            r'\bphosphorylation state\b': 'ubiquitylation state',
            r'\bphosphorylation data\b': 'ubiquitylation data',
            # === Compound phrase replacements ===
            r'\bbinary phosphorylation\b': 'binary ubiquitylation',
            r'\bswitch-like phosphorylation\b': 'switch-like ubiquitylation',
            r'\bmassive[,]?\s*binary phosphorylation\b': 'massive, binary ubiquitylation',
            r'\bmulti-site phosphorylation\b': 'multi-site ubiquitylation',
            r'\bsite-specific phosphorylation\b': 'site-specific ubiquitylation',
            r'\bglobal phosphorylation\b': 'global ubiquitylation',
            r'\btemporal phosphorylation\b': 'temporal ubiquitylation',
            r'\bdynamic phosphorylation\b': 'dynamic ubiquitylation',
            r'\brapid phosphorylation\b': 'rapid ubiquitylation',
            r'\btransient phosphorylation\b': 'transient ubiquitylation',
            r'\bsustained phosphorylation\b': 'sustained ubiquitylation',
            r'\baberrant phosphorylation\b': 'aberrant ubiquitylation',
            r'\bhyper-?phosphorylation\b': 'hyper-ubiquitylation',
            # === Enzyme term replacements ===
            r'\bkinase-substrate\b': 'E3 ligase-substrate',
            r'\bkinase enrichment\b': 'E3 ligase enrichment',
            r'\bkinase activity\b': 'E3 ligase activity',
            r'\bkinase cascade\b': 'ubiquitylation cascade',
            # === De-modification replacements ===
            r'\btargeted dephosphorylation\b': 'targeted deubiquitylation',
            r'\bdephosphorylation of\b': 'deubiquitylation of',
            # === Omics-level replacements ===
            r'\bPhosphoproteomic\b': 'Ubiquitylomics',
            r'\bphosphoproteomic\b': 'ubiquitylomics',
            r'\bPhosphoproteomics\b': 'Ubiquitylomics',
            r'\bphosphoproteomics\b': 'ubiquitylomics',
            r'\bPhosphorylation Dynamics\b': 'Ubiquitylation Dynamics',
            # === Site-specific replacements ===
            r'\bphosphorylation at (Lys\d+)\b': r'ubiquitylation at \1',
            r'\bphosphorylation at (K\d+)\b': r'ubiquitylation at \1',
            r'\bKey phosphorylation\b': 'Key ubiquitylation',
            # === Prefix replacements (careful - only standalone) ===
            r'\bphospho-?site\b': 'ubiquitylation site',
            r'\bphospho-?peptide\b': 'ubiquitylated peptide',
        },
        "exceptions": [
            r'oxidative\s+phosphorylation',                           # metabolic pathway
            r'phosphorylation.{0,15}cross.?talk',                     # cross-talk
            r'cross.?talk.{0,15}(?:between|of).{0,15}phosphorylation',
            r'(?:between|of)\s+phosphorylation\s+and\s+ubiquitylation',
            r'(?:between|of)\s+ubiquitylation\s+and\s+phosphorylation',
            r'phosphorylation-dependent\s+ubiquitylation',            # mechanistic
            r'phospho-?degron',                                        # specific term
            r'phosphorylation.{0,10}priming',                         # priming mechanism
            r'phosphorylation\s+(?:by|via|through)\s+\w+\s+kinase',   # explicit kinase mention
            r'(?:Ser|Thr|Tyr)\d+\s+phosphorylation',                  # Ser/Thr/Tyr phospho (different residue)
            r'phosphorylation\s+of\s+(?:Ser|Thr|Tyr)',                # phospho of Ser/Thr/Tyr
            r'(?:auto-?)?phosphorylation\s+of\s+\w+\s+(?:kinase|receptor)', # kinase autophosphorylation
        ],
    },

    "acetylation": {
        "modification_name": "acetylation",
        "modification_name_cap": "Acetylation",
        "modification_verb": "acetylated",
        "modification_verb_cap": "Acetylated",
        "de_modification": "deacetylation",
        "de_modification_cap": "Deacetylation",
        "omics_name": "Acetylomics",
        "omics_name_lower": "acetylomics",
        "omics_study": "Acetylomics",
        "target_residues": ["Lys"],
        "site_prefixes": ["Lys", "K"],
        "enzyme_writer_generic": "acetyltransferase (HAT/KAT)",
        "enzyme_writer_generic_cap": "Acetyltransferase (HAT/KAT)",
        "enzyme_writer_plural": "acetyltransferases",
        "enzyme_eraser_generic": "deacetylase (HDAC/SIRT)",
        "enzyme_eraser_generic_cap": "Deacetylase (HDAC/SIRT)",
        "enzyme_eraser_plural": "deacetylases",
        "enzyme_substrate_term": "acetyltransferase-substrate",
        "enzyme_substrate_term_cap": "Acetyltransferase-Substrate",
        "enrichment_term": "acetyltransferase enrichment",
        "enrichment_term_cap": "Acetyltransferase Enrichment",
        "degradation_pathway": None,
        "signaling_role": "transcription regulation, chromatin remodeling, metabolic enzyme regulation",
        "binary_event_term": "binary acetylation event",
        "dynamics_term": "acetylation dynamics",
        "profiling_term": "acetylation profiling",
        "modification_at_site": "acetylation at {site} of {gene}",
        "forbidden_substitutions": {
            r'\bphosphorylation sites?\b': 'acetylation sites',
            r'\bphosphorylation events?\b': 'acetylation events',
            r'\bkinase-substrate\b': 'acetyltransferase-substrate',
            r'\bPhosphoproteomic\b': 'Acetylomics',
            r'\bphosphoproteomic\b': 'acetylomics',
        },
        "exceptions": [
            r'phosphorylation.{0,15}cross.?talk',
            r'oxidative\s+phosphorylation',
        ],
    },

    "methylation": {
        "modification_name": "methylation",
        "modification_name_cap": "Methylation",
        "modification_verb": "methylated",
        "modification_verb_cap": "Methylated",
        "de_modification": "demethylation",
        "de_modification_cap": "Demethylation",
        "omics_name": "Methylomics",
        "omics_name_lower": "methylomics",
        "omics_study": "Methylomics",
        "target_residues": ["Lys", "Arg"],
        "site_prefixes": ["Lys", "Arg", "K", "R"],
        "enzyme_writer_generic": "methyltransferase",
        "enzyme_writer_generic_cap": "Methyltransferase",
        "enzyme_writer_plural": "methyltransferases",
        "enzyme_eraser_generic": "demethylase",
        "enzyme_eraser_generic_cap": "Demethylase",
        "enzyme_eraser_plural": "demethylases",
        "enzyme_substrate_term": "methyltransferase-substrate",
        "enzyme_substrate_term_cap": "Methyltransferase-Substrate",
        "enrichment_term": "methyltransferase enrichment",
        "enrichment_term_cap": "Methyltransferase Enrichment",
        "degradation_pathway": None,
        "signaling_role": "epigenetic regulation, transcription activation/repression, protein-protein interaction",
        "binary_event_term": "binary methylation event",
        "dynamics_term": "methylation dynamics",
        "profiling_term": "methylation profiling",
        "modification_at_site": "methylation at {site} of {gene}",
        "forbidden_substitutions": {
            r'\bphosphorylation sites?\b': 'methylation sites',
            r'\bphosphorylation events?\b': 'methylation events',
            r'\bkinase-substrate\b': 'methyltransferase-substrate',
            r'\bPhosphoproteomic\b': 'Methylomics',
            r'\bphosphoproteomic\b': 'methylomics',
        },
        "exceptions": [
            r'phosphorylation.{0,15}cross.?talk',
            r'oxidative\s+phosphorylation',
        ],
    },

    "sumoylation": {
        "modification_name": "SUMOylation",
        "modification_name_cap": "SUMOylation",
        "modification_verb": "SUMOylated",
        "modification_verb_cap": "SUMOylated",
        "de_modification": "deSUMOylation",
        "de_modification_cap": "DeSUMOylation",
        "omics_name": "SUMOylomics",
        "omics_name_lower": "sumoylomics",
        "omics_study": "SUMOylomics",
        "target_residues": ["Lys"],
        "site_prefixes": ["Lys", "K"],
        "enzyme_writer_generic": "SUMO E3 ligase",
        "enzyme_writer_generic_cap": "SUMO E3 Ligase",
        "enzyme_writer_plural": "SUMO E3 ligases",
        "enzyme_eraser_generic": "SENP (SUMO protease)",
        "enzyme_eraser_generic_cap": "SENP (SUMO Protease)",
        "enzyme_eraser_plural": "SENPs",
        "enzyme_substrate_term": "SUMO ligase-substrate",
        "enzyme_substrate_term_cap": "SUMO Ligase-Substrate",
        "enrichment_term": "SUMO ligase enrichment",
        "enrichment_term_cap": "SUMO Ligase Enrichment",
        "degradation_pathway": "SUMO-targeted ubiquitin ligase (STUbL) pathway",
        "signaling_role": "transcription regulation, DNA repair, nuclear transport, PML body formation",
        "binary_event_term": "binary SUMOylation event",
        "dynamics_term": "SUMOylation dynamics",
        "profiling_term": "SUMOylation profiling",
        "modification_at_site": "SUMOylation at {site} of {gene}",
        "forbidden_substitutions": {
            r'\bphosphorylation sites?\b': 'SUMOylation sites',
            r'\bphosphorylation events?\b': 'SUMOylation events',
            r'\bkinase-substrate\b': 'SUMO ligase-substrate',
            r'\bPhosphoproteomic\b': 'SUMOylomics',
            r'\bphosphoproteomic\b': 'sumoylomics',
        },
        "exceptions": [
            r'phosphorylation.{0,15}cross.?talk',
            r'oxidative\s+phosphorylation',
            r'phosphorylation-dependent\s+SUMOylation',
        ],
    },
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_vocabulary(ptm_type: str) -> Dict:
    """Get the vocabulary dictionary for a given PTM type.
    
    Falls back to phosphorylation if the PTM type is not found.
    Also handles common aliases (e.g., 'ubiquitination' → 'ubiquitylation').
    """
    # Normalize aliases
    normalized = ptm_type.lower().strip()
    _ALIASES = {
        "ubiquitination": "ubiquitylation",
        "ubiquitinylation": "ubiquitylation",
        "phospho": "phosphorylation",
        "ub": "ubiquitylation",
        "ac": "acetylation",
        "me": "methylation",
        "sumo": "sumoylation",
    }
    normalized = _ALIASES.get(normalized, normalized)
    
    if normalized in PTM_VOCABULARY:
        return PTM_VOCABULARY[normalized]
    
    # Fallback: return phosphorylation vocabulary
    return PTM_VOCABULARY["phosphorylation"]


def get_normalized_ptm_type(ptm_type: str) -> str:
    """Normalize PTM type string to canonical form."""
    normalized = ptm_type.lower().strip()
    _ALIASES = {
        "ubiquitination": "ubiquitylation",
        "ubiquitinylation": "ubiquitylation",
        "phospho": "phosphorylation",
        "ub": "ubiquitylation",
        "ac": "acetylation",
        "me": "methylation",
        "sumo": "sumoylation",
        "cross_talk": "cross_talk",
        "crosstalk": "cross_talk",
    }
    return _ALIASES.get(normalized, normalized)


def build_crosstalk_vocabulary_prompt_block(
    primary_ptm_type: str = "phosphorylation",
    secondary_ptm_type: str = "ubiquitylation",
) -> str:
    """Build a vocabulary block for cross-talk mode LLM prompts.
    
    In cross-talk mode, BOTH PTM types are legitimate and should be used.
    The vocabulary block instructs the LLM to use correct terminology for both.
    """
    p_vocab = get_vocabulary(primary_ptm_type)
    s_vocab = get_vocabulary(secondary_ptm_type)
    
    lines = [
        f"\n{'='*70}",
        f"PTM CROSS-TALK VOCABULARY REFERENCE (MANDATORY)",
        f"{'='*70}",
        f"",
        f"This is a **Cross-Talk Analysis** between {p_vocab['modification_name_cap']} and {s_vocab['modification_name_cap']}.",
        f"BOTH PTM types are legitimate in this report.",
        f"",
        f"PRIMARY PTM ({p_vocab['modification_name_cap']}):",
        f"  - Modification: {p_vocab['modification_name']}",
        f"  - Verb form: {p_vocab['modification_verb']}",
        f"  - Writer enzyme: {p_vocab['enzyme_writer_generic']}",
        f"  - Eraser enzyme: {p_vocab['enzyme_eraser_generic']}",
        f"  - Enzyme-substrate: {p_vocab['enzyme_substrate_term']}",
        f"  - Target residues: {', '.join(p_vocab['target_residues'])}",
        f"",
        f"SECONDARY PTM ({s_vocab['modification_name_cap']}):",
        f"  - Modification: {s_vocab['modification_name']}",
        f"  - Verb form: {s_vocab['modification_verb']}",
        f"  - Writer enzyme: {s_vocab['enzyme_writer_generic']}",
        f"  - Eraser enzyme: {s_vocab['enzyme_eraser_generic']}",
        f"  - Enzyme-substrate: {s_vocab['enzyme_substrate_term']}",
        f"  - Target residues: {', '.join(s_vocab['target_residues'])}",
        f"",
        f"CROSS-TALK SPECIFIC TERMS (USE THESE):",
        f"  - 'PTM cross-talk' or 'cross-talk between {p_vocab['modification_name']} and {s_vocab['modification_name']}'",
        f"  - 'dual-PTM protein' (protein bearing both modifications)",
        f"  - 'concordant regulation' (both PTMs change in same direction)",
        f"  - 'discordant regulation' (PTMs change in opposite directions)",
        f"  - 'sequential gating' (one PTM precedes and gates the other)",
        f"  - 'phosphodegron' (phosphorylation-dependent ubiquitylation)",
        f"  - 'shared non-PTM interactor' (protein interacting with both PTM networks)",
        f"",
        f"FORBIDDEN TERMS:",
        f"  - NEVER mention 'ChromaDB', 'knowledge base', 'database'",
        f"  - NEVER confuse which PTM type belongs to which dataset",
        f"  - NEVER use 'ubiquitination' (use 'ubiquitylation')",
        f"",
        f"{'='*70}",
    ]
    return "\n".join(lines)


def build_vocabulary_prompt_block(ptm_type: str) -> str:
    """Build a structured vocabulary block for LLM prompt injection.
    
    This block tells the LLM exactly which terms to use and which to avoid.
    It is injected into every section prompt to prevent cross-contamination.
    """
    vocab = get_vocabulary(ptm_type)
    normalized = get_normalized_ptm_type(ptm_type)
    
    lines = [
        f"\n{'='*70}",
        f"PTM VOCABULARY REFERENCE (MANDATORY — FOLLOW EXACTLY)",
        f"{'='*70}",
        f"",
        f"This is a **{vocab['modification_name_cap']}** analysis.",
        f"",
        f"CORRECT TERMS (USE THESE):",
        f"  - Modification: {vocab['modification_name']}",
        f"  - Verb form: {vocab['modification_verb']}",
        f"  - Reverse: {vocab['de_modification']}",
        f"  - Omics: {vocab['omics_name']}",
        f"  - Target residue(s): {', '.join(vocab['target_residues'])}",
        f"  - Writer enzyme: {vocab['enzyme_writer_generic']}",
        f"  - Eraser enzyme: {vocab['enzyme_eraser_generic']}",
        f"  - Enzyme-substrate: {vocab['enzyme_substrate_term']}",
        f"  - Site notation: '{vocab['modification_at_site'].format(site='Lys48', gene='GENE')}'",
        f"",
    ]
    
    # Add FORBIDDEN terms
    if normalized != "phosphorylation":
        lines.extend([
            f"FORBIDDEN TERMS (NEVER USE THESE for this {vocab['modification_name']} study):",
            f"  - NEVER write 'phosphorylation sites/dynamics/events/changes/patterns'",
            f"  - NEVER write 'Phosphoproteomic' or 'phosphoproteomics'",
            f"  - NEVER write 'kinase-substrate' (use '{vocab['enzyme_substrate_term']}')",
            f"  - NEVER write 'kinase enrichment' (use '{vocab['enrichment_term']}')",
            f"  - NEVER write 'kinase activity' (use '{vocab['enzyme_writer_generic']} activity')",
            f"  - NEVER write 'dephosphorylation' when meaning '{vocab['de_modification']}'",
            f"  - NEVER write 'binary phosphorylation' (use 'binary {vocab['modification_name']}')",
            f"  - NEVER write 'switch-like phosphorylation' (use 'switch-like {vocab['modification_name']}')",
            f"",
            f"EXCEPTIONS (phosphorylation IS allowed in these contexts ONLY):",
            f"  1. 'oxidative phosphorylation' (mitochondrial metabolic pathway)",
            f"  2. Explicit cross-talk: 'cross-talk between phosphorylation and {vocab['modification_name']}'",
            f"  3. Phospho-degron mechanisms (phosphorylation-dependent {vocab['modification_name']})",
            f"  4. Citing published literature that specifically studied phosphorylation",
            f"  5. Ser/Thr/Tyr phosphorylation on a DIFFERENT residue type than {', '.join(vocab['target_residues'])}",
        ])
    
    if normalized == "phosphorylation":
        lines.extend([
            f"FORBIDDEN TERMS (NEVER USE THESE for this phosphorylation study):",
            f"  - NEVER write 'ubiquitylation sites/dynamics/events' when describing this dataset",
            f"  - NEVER write 'E3 ligase-substrate' (use 'kinase-substrate')",
            f"  - NEVER write 'Ubiquitylomics'",
        ])
    
    lines.extend([
        f"",
        f"{'='*70}",
    ])
    
    return "\n".join(lines)


def build_postprocessor_corrections(ptm_type: str) -> Tuple[Dict[str, str], List[str]]:
    """Get the forbidden_substitutions and exceptions for postprocessor use.
    
    Returns:
        (wrong_terms_dict, exceptions_list)
    """
    vocab = get_vocabulary(ptm_type)
    return vocab.get("forbidden_substitutions", {}), vocab.get("exceptions", [])


def get_system_prompt_for_ptm(ptm_type: str) -> str:
    """Generate PTM-specific system prompt addition.
    
    This replaces the generic SYSTEM_PROMPT in writer_node.py with
    PTM-aware instructions.
    """
    vocab = get_vocabulary(ptm_type)
    normalized = get_normalized_ptm_type(ptm_type)
    
    base = (
        f"You are a scientific writer specializing in post-translational modification (PTM) analysis. "
        f"This study analyzes **{vocab['modification_name']}** modifications. "
        f"Write in formal academic English. Use flowing prose, not bullet points. "
        f"Cite references using numbered brackets (e.g., [1], [2]) matching the provided reference list. "
        f"Include as many relevant citations as possible to support your statements. "
        f"NEVER mention 'ChromaDB' or 'knowledge base'. "
    )
    
    # PTM-specific site nomenclature
    base += (
        f"Be precise with PTM site nomenclature. "
        f"Use '{vocab['modification_name']} at {vocab['site_prefixes'][0]}NNN of GENE_NAME' format. "
    )
    
    # Forbidden terms warning
    if normalized != "phosphorylation":
        base += (
            f"CRITICAL: This is a {vocab['modification_name_cap']} study. "
            f"NEVER use 'phosphorylation' when describing modifications in this dataset "
            f"(except for 'oxidative phosphorylation', cross-talk comparisons, or phospho-degron mechanisms). "
            f"Use '{vocab['enzyme_substrate_term']}' instead of 'kinase-substrate'. "
            f"Use '{vocab['omics_name']}' instead of 'Phosphoproteomic'. "
        )
    
    base += (
        f"CRITICAL: Use ONLY proteins and PTM sites from the actual data provided in the prompt. "
        f"Never use example or placeholder proteins from prompt templates — they are for illustration only. "
        f"Write detailed, comprehensive content that thoroughly covers the topic. "
        f"Do NOT include a top-level section heading (e.g., '## Results' or '## Discussion') — "
        f"the heading will be added automatically. You may use ### sub-headings within your text."
    )
    
    return base
