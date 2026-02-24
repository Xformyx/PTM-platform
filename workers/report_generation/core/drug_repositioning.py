"""
Drug Repositioning Pipeline for PTM Analysis System (v3.2)

This module extends the existing PTM analysis with Drug Repositioning capabilities.
It integrates with the existing LLM infrastructure (call_llm from ptm_nonptm_network_command)
and external free APIs (ChEMBL, PubChem, ClinicalTrials.gov).

v3.2 IMPROVEMENTS (over v3.1):
  1. CRITICAL FIX: PTM type detection now uses 3-tier priority:
     - Priority 1: summary['ptm_type'] from ptm_nonptm_network_command.py detect_ptm_type()
     - Priority 2: md_content-based detection (Modification Type markers, site patterns K/S/T/Y)
     - Priority 3: Network node scanning (fallback)
  2. All internal dict keys renamed: 'kinases' → 'regulators', 'upstream_kinase' → 'upstream_regulator'
  3. Eliminated ALL hardcoded 'phosphorylation'/'kinase' references in report generation
  4. ptm_nonptm_network_command.py now stores ptm_type in results['summary']['ptm_type']

  Preserved from v3.1:
  - PTM_TYPE_CONFIG for phosphorylation, ubiquitylation, acetylation, sumoylation
  - E3_LIGASE_PATHWAY_DB, ACETYLTRANSFERASE_PATHWAY_DB
  - LLM prompts with correct PTM type + anti-hallucination instructions
  - Dynamic report text and Methods section

  Preserved from v3.0:
  - Percentile-based magnitude scoring
  - Part I network data integration
  - Relative tier classification
  - ChEMBL drug name resolution
  - Pathway text cleanup
  - All SSE logging

Pipeline Steps:
  Step 1: PTM Scoring (7-dimensional) - Score PTM targets for druggability
  Step 2: Upstream Inference - Identify upstream regulators (kinases/E3 ligases/etc.)
  Step 3: Target Selection - Prioritize drug targets
  Step 4: Drug Search - Query ChEMBL/PubChem for drug candidates
  Step 5: Clinical Trials Search - Query ClinicalTrials.gov
  Step 6: Repositioning Evaluation - LLM-based evaluation
  Step 7: Extended Report Sections - Generate Drug Repositioning report sections

Usage:
  Called from api_wrapper.py with command: drug_repositioning
  Input: analysis results JSON from ptm_nonptm_network_command + report_type=extended
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

_logger = logging.getLogger("ptm-workers.drug-repositioning")


def sse_log(message, level="INFO"):
    if level == "WARNING":
        _logger.warning(message)
    elif level == "ERROR":
        _logger.error(message)
    else:
        _logger.info(message)


# ============================================================================
# PTM Type Configuration - v3.1 NEW
# ============================================================================

PTM_TYPE_CONFIG = {
    'phosphorylation': {
        'upstream_label': 'Upstream Kinase',
        'upstream_label_plural': 'Upstream Kinase(s)',
        'upstream_type': 'kinase',
        'upstream_types_plural': 'kinases',
        'regulator_label': 'Kinase',
        'substrate_label': 'Kinase-Substrate',
        'evidence_keywords': ['kea3', 'kinase', 'substrate', 'phosphorylat'],
        'node_type_keywords': ['Kinase', 'kinase'],
        'modification_verb': 'phosphorylation',
        'modification_site_prefix': 'S/T/Y',  # Serine, Threonine, Tyrosine
        'pathway_db_key': 'KINASE',
        'description': 'phosphorylation (addition of phosphate groups to serine, threonine, or tyrosine residues)',
    },
    'ubiquitylation': {
        'upstream_label': 'Upstream E3 Ligase',
        'upstream_label_plural': 'Upstream E3 Ligase(s)',
        'upstream_type': 'E3 ligase',
        'upstream_types_plural': 'E3 ligases',
        'regulator_label': 'E3 Ligase',
        'substrate_label': 'E3 Ligase-Substrate',
        'evidence_keywords': ['e3', 'ligase', 'ubiquitin', 'ubiquitylat', 'proteasom', 'deubiquitin', 'dub'],
        'node_type_keywords': ['E3 Ligase', 'E3_Ligase', 'Ligase', 'Kinase', 'kinase'],  # Also check kinase nodes as they may regulate ubi
        'modification_verb': 'ubiquitylation',
        'modification_site_prefix': 'K',  # Lysine
        'pathway_db_key': 'E3_LIGASE',
        'description': 'ubiquitylation (covalent attachment of ubiquitin to lysine residues)',
    },
    'acetylation': {
        'upstream_label': 'Upstream Acetyltransferase',
        'upstream_label_plural': 'Upstream Acetyltransferase(s)',
        'upstream_type': 'acetyltransferase',
        'upstream_types_plural': 'acetyltransferases',
        'regulator_label': 'HAT/HDAC',
        'substrate_label': 'Acetyltransferase-Substrate',
        'evidence_keywords': ['acetyl', 'hat', 'hdac', 'acetyltransferase', 'deacetylase'],
        'node_type_keywords': ['Acetyltransferase', 'HAT', 'HDAC', 'Kinase', 'kinase'],
        'modification_verb': 'acetylation',
        'modification_site_prefix': 'K',  # Lysine
        'pathway_db_key': 'ACETYLTRANSFERASE',
        'description': 'acetylation (addition of acetyl groups to lysine residues)',
    },
    'sumoylation': {
        'upstream_label': 'Upstream SUMO E3 Ligase',
        'upstream_label_plural': 'Upstream SUMO E3 Ligase(s)',
        'upstream_type': 'SUMO E3 ligase',
        'upstream_types_plural': 'SUMO E3 ligases',
        'regulator_label': 'SUMO E3 Ligase',
        'substrate_label': 'SUMO E3 Ligase-Substrate',
        'evidence_keywords': ['sumo', 'sumoylat', 'ubc9', 'pias'],
        'node_type_keywords': ['SUMO E3 Ligase', 'Ligase', 'Kinase', 'kinase'],
        'modification_verb': 'sumoylation',
        'modification_site_prefix': 'K',  # Lysine
        'pathway_db_key': 'SUMO_LIGASE',
        'description': 'sumoylation (conjugation of SUMO proteins to lysine residues)',
    },
}

# Default config for unknown PTM types
DEFAULT_PTM_CONFIG = {
    'upstream_label': 'Upstream Regulator',
    'upstream_label_plural': 'Upstream Regulator(s)',
    'upstream_type': 'regulator',
    'upstream_types_plural': 'regulators',
    'regulator_label': 'Regulator',
    'substrate_label': 'Regulator-Substrate',
    'evidence_keywords': ['kea3', 'kinase', 'substrate', 'regulator', 'e3', 'ligase', 'ubiquitin'],
    'node_type_keywords': ['Kinase', 'kinase', 'E3 Ligase', 'Ligase'],
    'modification_verb': 'post-translational modification',
    'modification_site_prefix': '',
    'pathway_db_key': 'KINASE',
    'description': 'post-translational modification',
}


def get_ptm_config(ptm_type: str) -> Dict:
    """Get PTM type configuration. Handles various naming conventions."""
    if not ptm_type:
        return DEFAULT_PTM_CONFIG
    
    ptm_lower = ptm_type.lower().strip()
    
    # Direct match
    if ptm_lower in PTM_TYPE_CONFIG:
        return PTM_TYPE_CONFIG[ptm_lower]
    
    # Partial match
    for key, config in PTM_TYPE_CONFIG.items():
        if key in ptm_lower or ptm_lower in key:
            return config
    
    # Check for common aliases
    aliases = {
        'phospho': 'phosphorylation',
        'ubiquitin': 'ubiquitylation',
        'ub': 'ubiquitylation',
        'ubiq': 'ubiquitylation',
        'acetyl': 'acetylation',
        'ac': 'acetylation',
        'sumo': 'sumoylation',
    }
    for alias, canonical in aliases.items():
        if alias in ptm_lower:
            return PTM_TYPE_CONFIG.get(canonical, DEFAULT_PTM_CONFIG)
    
    return DEFAULT_PTM_CONFIG


def detect_ptm_type_from_data(analysis_results: Dict, md_content: str = "") -> str:
    """Detect the dominant PTM type from the analysis results data.
    
    v3.2: Enhanced detection with 3-tier priority:
      Priority 1: summary['ptm_type'] (set by ptm_nonptm_network_command.py detect_ptm_type)
      Priority 2: md_content-based detection (site patterns + keyword analysis)
      Priority 3: Network node scanning (fallback)
    Falls back to 'phosphorylation' only if ALL detection methods fail.
    """
    # === Priority 1: Check summary ptm_type (most reliable - set by detect_ptm_type in main module) ===
    summary = analysis_results.get('summary', {})
    if isinstance(summary, dict):
        ptm_type_from_summary = summary.get('ptm_type', '')
        if ptm_type_from_summary:
            pt_lower = ptm_type_from_summary.lower().strip()
            # Direct match
            if pt_lower in PTM_TYPE_CONFIG:
                sse_log(f"[DR] PTM type detected from summary: {pt_lower}", "INFO")
                return pt_lower
            # Partial match
            for canonical in PTM_TYPE_CONFIG:
                if canonical in pt_lower or pt_lower in canonical:
                    sse_log(f"[DR] PTM type detected from summary (partial): {canonical}", "INFO")
                    return canonical
    
    # === Priority 2: md_content-based detection (same logic as ptm_nonptm_network_command.detect_ptm_type) ===
    if md_content:
        content_lower = md_content.lower()
        
        # Check "Modification Type: XXX" markers first
        import re as _re
        mod_type_pattern = r'\*{0,2}modification\s+type\*{0,2}:\*{0,2}\s*'
        mod_counts = {
            'phosphorylation': len(_re.findall(mod_type_pattern + r'phosphorylation', content_lower)),
            'ubiquitylation': len(_re.findall(mod_type_pattern + r'ubiquitylation', content_lower)),
            'acetylation': len(_re.findall(mod_type_pattern + r'acetylation', content_lower)),
        }
        max_mod = max(mod_counts.values())
        if max_mod > 0:
            detected = max(mod_counts, key=mod_counts.get)
            sse_log(f"[DR] PTM type detected from md_content markers: {detected} (count={max_mod})", "INFO")
            return detected
        
        # Check site patterns: S/T/Y = phosphorylation, K = ubiquitylation/acetylation
        sty_sites = len(_re.findall(r'[A-Z][a-z0-9]+-[STY]\d+', md_content))
        k_sites = len(_re.findall(r'[A-Z][a-z0-9]+-K\d+', md_content))
        
        if sty_sites > k_sites and sty_sites > 5:
            sse_log(f"[DR] PTM type detected from site patterns: phosphorylation (S/T/Y={sty_sites}, K={k_sites})", "INFO")
            return 'phosphorylation'
        elif k_sites > sty_sites and k_sites > 5:
            # K sites: distinguish ubiquitylation vs acetylation by context
            ubi_score = content_lower.count('ubiquitin') + content_lower.count('ubiquitylation') * 2
            acet_score = content_lower.count('acetyl') + content_lower.count('acetylation') * 2
            if ubi_score > acet_score:
                sse_log(f"[DR] PTM type detected from site patterns + context: ubiquitylation (K={k_sites}, ubi={ubi_score}, acet={acet_score})", "INFO")
                return 'ubiquitylation'
            elif acet_score > ubi_score:
                sse_log(f"[DR] PTM type detected from site patterns + context: acetylation (K={k_sites}, acet={acet_score}, ubi={ubi_score})", "INFO")
                return 'acetylation'
            else:
                sse_log(f"[DR] PTM type detected from site patterns: ubiquitylation (K={k_sites}, default for K sites)", "INFO")
                return 'ubiquitylation'
    
    # === Priority 3: Network node scanning (least reliable - node 'type' is usually just 'PTM') ===
    ptm_type_counts = {}
    networks = analysis_results.get('networks', {})
    for tp, net in networks.items():
        if not isinstance(net, dict):
            continue
        for node_list_key in ['active_nodes', 'inhibited_nodes']:
            for node in net.get(node_list_key, []):
                pt = node.get('ptm_type', node.get('type', ''))
                if pt and pt.lower() not in ('ptm', 'non-ptm', 'non_ptm', 'kinase', 'interactor', ''):
                    pt_lower = pt.lower().strip()
                    ptm_type_counts[pt_lower] = ptm_type_counts.get(pt_lower, 0) + 1
    
    if ptm_type_counts:
        dominant = max(ptm_type_counts, key=ptm_type_counts.get)
        for canonical in PTM_TYPE_CONFIG:
            if canonical in dominant or dominant in canonical:
                sse_log(f"[DR] PTM type detected from network nodes: {canonical}", "INFO")
                return canonical
        # Check aliases
        aliases = {
            'phospho': 'phosphorylation', 'ubiquitin': 'ubiquitylation',
            'ub': 'ubiquitylation', 'acetyl': 'acetylation', 'sumo': 'sumoylation',
        }
        for alias, canonical in aliases.items():
            if alias in dominant:
                sse_log(f"[DR] PTM type detected from network nodes (alias): {canonical}", "INFO")
                return canonical
    
    sse_log("[DR] WARNING: Could not detect PTM type, defaulting to phosphorylation", "WARNING")
    return 'phosphorylation'


# ============================================================================
# Utility: Clean pathway text (remove species names)
# ============================================================================

def clean_pathway_text(pathway: str) -> str:
    """Remove species names and clean up pathway text."""
    if not pathway:
        return pathway
    cleaned = re.sub(r'\s*-\s*(Mus musculus|Homo sapiens|Rattus norvegicus|Danio rerio|Drosophila melanogaster)(\s*\([^)]*\))?', '', pathway)
    cleaned = re.sub(r'\s*(Mus musculus|Homo sapiens|Rattus norvegicus)(\s*\([^)]*\))?', '', cleaned)
    return cleaned.strip()


# ============================================================================
# Known Kinase-Pathway Database (for phosphorylation)
# ============================================================================

KINASE_PATHWAY_DB = {
    # MAPK/ERK pathway
    'MAPK1': ['MAPK signaling pathway', 'ErbB signaling pathway'],
    'MAPK3': ['MAPK signaling pathway', 'ErbB signaling pathway'],
    'MAPK8': ['MAPK signaling pathway', 'JNK signaling'],
    'MAPK14': ['MAPK signaling pathway', 'p38 MAPK signaling'],
    'MAP2K1': ['MAPK signaling pathway', 'Ras signaling pathway'],
    'MAP2K2': ['MAPK signaling pathway', 'Ras signaling pathway'],
    'MAP3K1': ['MAPK signaling pathway'],
    'BRAF': ['MAPK signaling pathway', 'Ras signaling pathway'],
    'RAF1': ['MAPK signaling pathway', 'Ras signaling pathway'],
    'ERK1': ['MAPK signaling pathway'],
    'ERK2': ['MAPK signaling pathway'],
    # PI3K/AKT/mTOR pathway
    'AKT1': ['PI3K-Akt signaling pathway', 'mTOR signaling pathway'],
    'AKT2': ['PI3K-Akt signaling pathway', 'mTOR signaling pathway'],
    'AKT3': ['PI3K-Akt signaling pathway'],
    'PIK3CA': ['PI3K-Akt signaling pathway'],
    'PIK3CB': ['PI3K-Akt signaling pathway'],
    'MTOR': ['mTOR signaling pathway', 'PI3K-Akt signaling pathway', 'Autophagy'],
    'RPS6KB1': ['mTOR signaling pathway'],
    'EIF4EBP1': ['mTOR signaling pathway'],
    # JAK/STAT pathway
    'JAK1': ['JAK-STAT signaling pathway', 'Cytokine signaling'],
    'JAK2': ['JAK-STAT signaling pathway', 'Cytokine signaling'],
    'JAK3': ['JAK-STAT signaling pathway'],
    'STAT1': ['JAK-STAT signaling pathway'],
    'STAT3': ['JAK-STAT signaling pathway', 'IL-6 signaling'],
    'STAT5A': ['JAK-STAT signaling pathway'],
    'STAT5B': ['JAK-STAT signaling pathway'],
    # Src family kinases
    'SRC': ['Focal adhesion', 'Adherens junction', 'VEGF signaling pathway'],
    'FYN': ['T cell receptor signaling', 'Focal adhesion'],
    'LCK': ['T cell receptor signaling pathway'],
    'YES1': ['Focal adhesion'],
    'LYN': ['B cell receptor signaling pathway', 'Fc epsilon RI signaling'],
    # Receptor tyrosine kinases
    'EGFR': ['ErbB signaling pathway', 'MAPK signaling pathway', 'PI3K-Akt signaling pathway'],
    'ERBB2': ['ErbB signaling pathway', 'Breast cancer pathway'],
    'FGFR1': ['MAPK signaling pathway', 'PI3K-Akt signaling pathway'],
    'FGFR2': ['MAPK signaling pathway', 'PI3K-Akt signaling pathway'],
    'MET': ['HGF signaling', 'PI3K-Akt signaling pathway', 'Ras signaling pathway'],
    'KIT': ['PI3K-Akt signaling pathway', 'Ras signaling pathway'],
    'PDGFRA': ['PI3K-Akt signaling pathway', 'Ras signaling pathway'],
    'VEGFR2': ['VEGF signaling pathway'],
    'FLT3': ['PI3K-Akt signaling pathway', 'MAPK signaling pathway'],
    'ALK': ['PI3K-Akt signaling pathway', 'MAPK signaling pathway'],
    'RET': ['PI3K-Akt signaling pathway', 'MAPK signaling pathway'],
    'IGF1R': ['PI3K-Akt signaling pathway', 'MAPK signaling pathway', 'Insulin signaling'],
    # Cell cycle kinases
    'CDK1': ['Cell cycle', 'p53 signaling pathway'],
    'CDK2': ['Cell cycle', 'p53 signaling pathway'],
    'CDK4': ['Cell cycle', 'PI3K-Akt signaling pathway'],
    'CDK6': ['Cell cycle'],
    'PLK1': ['Cell cycle', 'Mitotic regulation'],
    'AURKA': ['Cell cycle', 'Mitotic regulation'],
    'AURKB': ['Cell cycle', 'Mitotic regulation'],
    'CHEK1': ['Cell cycle', 'p53 signaling pathway', 'DNA damage response'],
    'CHEK2': ['Cell cycle', 'p53 signaling pathway', 'DNA damage response'],
    # NF-kB pathway
    'IKBKB': ['NF-kappa B signaling pathway', 'TNF signaling pathway'],
    'IKBKG': ['NF-kappa B signaling pathway'],
    'NFKB1': ['NF-kappa B signaling pathway'],
    'RELA': ['NF-kappa B signaling pathway'],
    # Other important kinases
    'GSK3B': ['Wnt signaling pathway', 'PI3K-Akt signaling pathway', 'Insulin signaling'],
    'GSK3A': ['Wnt signaling pathway', 'PI3K-Akt signaling pathway'],
    'CSNK1E': ['Wnt signaling pathway', 'Circadian rhythm'],
    'CSNK2A1': ['Wnt signaling pathway', 'NF-kappa B signaling pathway'],
    'CSNK2A2': ['Wnt signaling pathway'],
    'PRKCA': ['Calcium signaling pathway', 'MAPK signaling pathway'],
    'PRKCB': ['Calcium signaling pathway'],
    'PRKCD': ['Apoptosis', 'MAPK signaling pathway'],
    'PRKACA': ['cAMP signaling pathway', 'Insulin signaling'],
    'ROCK1': ['Regulation of actin cytoskeleton', 'Focal adhesion'],
    'ROCK2': ['Regulation of actin cytoskeleton', 'Focal adhesion'],
    'PAK1': ['Regulation of actin cytoskeleton', 'MAPK signaling pathway'],
    'CAMK2A': ['Calcium signaling pathway', 'Long-term potentiation'],
    'CAMK2B': ['Calcium signaling pathway'],
    'AMPK': ['AMPK signaling pathway', 'mTOR signaling pathway'],
    'PRKAA1': ['AMPK signaling pathway', 'mTOR signaling pathway'],
    'PRKAA2': ['AMPK signaling pathway'],
    'ATM': ['p53 signaling pathway', 'DNA damage response', 'Cell cycle'],
    'ATR': ['DNA damage response', 'Cell cycle'],
    'PARP1': ['Base excision repair', 'DNA damage response'],
    'BTK': ['B cell receptor signaling pathway', 'NF-kappa B signaling pathway'],
    'SYK': ['B cell receptor signaling pathway', 'Fc gamma R-mediated phagocytosis'],
    # Cytoskeletal / structural proteins
    'VIM': ['Cytoskeleton organization', 'Intermediate filament'],
    'PLEC': ['Cytoskeleton organization', 'Focal adhesion'],
    'MARCKS': ['Calcium signaling', 'Actin cytoskeleton regulation'],
    'ANXA2': ['Membrane trafficking', 'Fibrinolysis'],
    'ENO1': ['Glycolysis', 'HIF-1 signaling pathway'],
    'SEPTIN9': ['Cytokinesis', 'Cell division'],
    'WIPI2': ['Autophagy', 'PI3K-Akt signaling pathway'],
    'LMNA': ['Nuclear envelope', 'Apoptosis'],
}


# ============================================================================
# E3 Ligase-Pathway Database (for ubiquitylation) - v3.1 NEW
# ============================================================================

E3_LIGASE_PATHWAY_DB = {
    # RING-type E3 ligases
    'MDM2': ['p53 signaling pathway', 'Cell cycle', 'Apoptosis'],
    'RNF8': ['DNA damage response', 'NF-kappa B signaling pathway'],
    'RNF168': ['DNA damage response', 'Chromatin remodeling'],
    'RNF20': ['Chromatin remodeling', 'Transcription regulation'],
    'RNF40': ['Chromatin remodeling', 'Transcription regulation'],
    'TRIM25': ['RIG-I signaling', 'Innate immunity', 'Antiviral response'],
    'TRIM32': ['NF-kappa B signaling pathway', 'Innate immunity'],
    'TRIM63': ['Muscle atrophy', 'Proteasomal degradation'],  # MuRF1
    'TRAF6': ['NF-kappa B signaling pathway', 'TNF signaling', 'Toll-like receptor signaling'],
    'TRAF2': ['NF-kappa B signaling pathway', 'TNF signaling', 'Apoptosis'],
    'BIRC2': ['NF-kappa B signaling pathway', 'Apoptosis'],  # cIAP1
    'BIRC3': ['NF-kappa B signaling pathway', 'Apoptosis'],  # cIAP2
    'XIAP': ['Apoptosis', 'NF-kappa B signaling pathway'],
    'SIAH1': ['Wnt signaling pathway', 'Hypoxia response', 'p53 signaling'],
    'SIAH2': ['Hypoxia response', 'MAPK signaling pathway'],
    'CBL': ['Receptor tyrosine kinase signaling', 'EGFR signaling', 'T cell receptor signaling'],
    'CBLB': ['T cell receptor signaling', 'Immune regulation'],
    'CHIP': ['Protein quality control', 'Heat shock response', 'Proteasomal degradation'],  # STUB1
    'STUB1': ['Protein quality control', 'Heat shock response', 'Proteasomal degradation'],
    'PARKIN': ['Mitophagy', 'Parkinson disease pathway', 'Ubiquitin-proteasome system'],  # PRKN
    'PRKN': ['Mitophagy', 'Parkinson disease pathway', 'Ubiquitin-proteasome system'],
    # HECT-type E3 ligases
    'NEDD4': ['Endocytosis', 'EGFR signaling', 'Wnt signaling pathway'],
    'NEDD4L': ['TGF-beta signaling', 'Wnt signaling pathway', 'Ion channel regulation'],
    'ITCH': ['T cell signaling', 'NF-kappa B signaling pathway', 'Apoptosis'],
    'SMURF1': ['TGF-beta signaling', 'BMP signaling', 'Wnt signaling pathway'],
    'SMURF2': ['TGF-beta signaling', 'BMP signaling'],
    'HUWE1': ['p53 signaling pathway', 'Apoptosis', 'DNA damage response'],
    'UBE3A': ['Proteasomal degradation', 'Angelman syndrome'],  # E6AP
    'WWP1': ['TGF-beta signaling', 'p53 signaling pathway'],
    'WWP2': ['TGF-beta signaling', 'Notch signaling'],
    # SCF complex components
    'SKP2': ['Cell cycle', 'p27 degradation', 'PI3K-Akt signaling pathway'],
    'FBXW7': ['Cell cycle', 'Notch signaling', 'Myc degradation', 'mTOR signaling'],
    'BTRC': ['Wnt signaling pathway', 'NF-kappa B signaling pathway', 'Cell cycle'],  # beta-TrCP
    'FBXO3': ['NF-kappa B signaling pathway', 'Inflammation'],
    # APC/C complex
    'CDC20': ['Cell cycle', 'Mitotic regulation', 'APC/C-mediated degradation'],
    'FZR1': ['Cell cycle', 'APC/C-mediated degradation'],  # CDH1
    # CRL complexes
    'CUL1': ['SCF complex', 'Cell cycle', 'Signal transduction'],
    'CUL3': ['BTB-CUL3 complex', 'NRF2 signaling', 'Oxidative stress response'],
    'CUL4A': ['DNA damage response', 'Chromatin remodeling'],
    'CUL4B': ['DNA damage response', 'Chromatin remodeling'],
    'VHL': ['HIF signaling', 'Hypoxia response', 'Renal cell carcinoma pathway'],
    'KEAP1': ['NRF2 signaling', 'Oxidative stress response', 'Antioxidant pathway'],
    # DUBs (deubiquitinases - also relevant for ubi regulation)
    'USP7': ['p53 signaling pathway', 'DNA damage response', 'Epigenetics'],
    'USP14': ['Proteasomal degradation', 'Autophagy'],
    'USP28': ['DNA damage response', 'Myc signaling'],
    'UCHL1': ['Parkinson disease pathway', 'Proteasomal degradation'],
    'UCHL5': ['Proteasomal degradation', 'TGF-beta signaling'],
    'BAP1': ['DNA damage response', 'Chromatin remodeling', 'Tumor suppression'],
    'OTUB1': ['DNA damage response', 'NF-kappa B signaling pathway'],
    'CYLD': ['NF-kappa B signaling pathway', 'TNF signaling', 'Innate immunity'],
    # Common proteins found in ubiquitylation data
    'VIM': ['Cytoskeleton organization', 'Intermediate filament', 'Proteasomal degradation'],
    'PLEC': ['Cytoskeleton organization', 'Focal adhesion'],
    'ANXA2': ['Membrane trafficking', 'Fibrinolysis'],
    'ENO1': ['Glycolysis', 'HIF-1 signaling pathway'],
    'LMNA': ['Nuclear envelope', 'Apoptosis'],
    'RAB21': ['Endocytosis', 'Vesicle trafficking', 'Integrin recycling'],
    'PGM1': ['Glycolysis', 'Metabolic pathways', 'Gluconeogenesis'],
    'ACO1': ['Iron homeostasis', 'TCA cycle', 'Metabolic pathways'],
    'SMC2': ['Chromosome condensation', 'Cell division', 'Mitotic regulation'],
    'RPS27A': ['Ribosome', 'Ubiquitin-proteasome system', 'Translation'],
}


# ============================================================================
# Acetyltransferase-Pathway Database (for acetylation)
# ============================================================================

ACETYLTRANSFERASE_PATHWAY_DB = {
    'EP300': ['Chromatin remodeling', 'Transcription regulation', 'Wnt signaling pathway'],
    'CREBBP': ['Chromatin remodeling', 'Transcription regulation', 'cAMP signaling'],
    'KAT2A': ['Chromatin remodeling', 'Transcription regulation'],  # GCN5
    'KAT2B': ['Chromatin remodeling', 'Transcription regulation'],  # PCAF
    'KAT5': ['DNA damage response', 'Chromatin remodeling'],  # TIP60
    'KAT6A': ['Chromatin remodeling', 'Hematopoiesis'],  # MOZ
    'KAT8': ['Chromatin remodeling', 'DNA damage response'],  # MOF
    'HDAC1': ['Chromatin remodeling', 'Cell cycle', 'Transcription regulation'],
    'HDAC2': ['Chromatin remodeling', 'Cell cycle'],
    'HDAC3': ['NF-kappa B signaling pathway', 'Chromatin remodeling'],
    'HDAC6': ['Autophagy', 'Protein quality control', 'Cytoskeleton organization'],
    'SIRT1': ['Chromatin remodeling', 'Metabolic regulation', 'Aging'],
    'SIRT2': ['Cell cycle', 'Metabolic regulation'],
    'SIRT3': ['Mitochondrial function', 'Metabolic regulation'],
    'SIRT6': ['DNA damage response', 'Metabolic regulation', 'Aging'],
}


def get_pathway_db(ptm_type: str) -> Dict:
    """Get the appropriate pathway database for the PTM type."""
    config = get_ptm_config(ptm_type)
    db_key = config.get('pathway_db_key', 'KINASE')
    
    if db_key == 'E3_LIGASE':
        # Merge both databases for ubiquitylation (E3 ligases + kinases that regulate ubi)
        merged = dict(E3_LIGASE_PATHWAY_DB)
        # Add kinase entries that are not already in E3 ligase DB
        for k, v in KINASE_PATHWAY_DB.items():
            if k not in merged:
                merged[k] = v
        return merged
    elif db_key == 'ACETYLTRANSFERASE':
        merged = dict(ACETYLTRANSFERASE_PATHWAY_DB)
        for k, v in KINASE_PATHWAY_DB.items():
            if k not in merged:
                merged[k] = v
        return merged
    else:
        return KINASE_PATHWAY_DB


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PTMScore:
    """7-dimensional PTM druggability score"""
    gene: str
    site: str
    ptm_type: str
    frequency: float = 0.0
    magnitude: float = 0.0
    temporal: float = 0.0
    functional: float = 0.0
    network: float = 0.0
    conservation: float = 0.0
    clinical: float = 0.0
    composite: float = 0.0
    raw_log2fc: float = 0.0
    
    def to_dict(self):
        return asdict(self)


@dataclass
class DrugCandidate:
    """Drug candidate from ChEMBL/PubChem search"""
    drug_name: str
    drug_id: str
    source: str
    target_gene: str
    mechanism_of_action: str = ""
    activity_type: str = ""
    activity_value: str = ""
    approval_status: str = ""
    original_indication: str = ""
    molecular_formula: str = ""
    
    def to_dict(self):
        return asdict(self)


@dataclass
class ClinicalTrial:
    """Clinical trial from ClinicalTrials.gov"""
    trial_id: str
    title: str
    phase: str
    status: str
    drug_name: str = ""
    target_gene: str = ""
    conditions: str = ""
    start_date: str = ""
    
    def to_dict(self):
        return asdict(self)


@dataclass
class RepositioningCandidate:
    """Final repositioning candidate with evaluation"""
    target_gene: str
    target_site: str
    ptm_type: str
    ptm_score: float
    upstream_regulator: str  # v3.2: renamed from upstream_kinase to upstream_regulator
    signaling_pathway: str
    drug: DrugCandidate
    clinical_trials: List[ClinicalTrial]
    repositioning_score: float = 0.0
    llm_evaluation: str = ""
    
    def to_dict(self):
        d = asdict(self)
        return d


# ============================================================================
# Step 1: PTM Scoring (7-dimensional) - v3.1 PTM-type-aware
# ============================================================================

class PTMScorer:
    """
    Score PTM targets for druggability using 7 dimensions.
    
    v3.1: Detects PTM type from data and passes it through the pipeline.
    v3.0: Percentile-based magnitude scoring for unique scores per PTM.
    
    Dimensions:
    1. Frequency (10%): Detection frequency across timepoints
    2. Magnitude (20%): Percentile-ranked |Log2FC| among all PTMs
    3. Temporal (15%): Temporal consistency
    4. Functional (15%): Functional annotation
    5. Network (20%): Network centrality from Part I
    6. Conservation (10%): Conservation score
    7. Clinical (10%): Clinical relevance
    """
    
    def __init__(self, analysis_results: Dict, md_context: str = ""):
        self.results = analysis_results
        self.md_context = md_context
        self.networks = analysis_results.get('networks', {})
        self.timepoints = sorted(self.networks.keys()) if self.networks else []
        # v3.2: Detect PTM type from data + md_content
        self.detected_ptm_type = detect_ptm_type_from_data(analysis_results, md_context)
        self.ptm_config = get_ptm_config(self.detected_ptm_type)
        sse_log(f"[DR] Detected PTM type: {self.detected_ptm_type}", "INFO")
    
    def score_all_ptms(self) -> List[PTMScore]:
        """Score all PTM targets and return sorted list"""
        sse_log(f"[DR-5%] Scoring PTM targets across {len(self.timepoints)} timepoints...", "INFO")
        
        # Collect all PTM sites across timepoints
        ptm_data = {}  # gene -> {site, values, timepoints, edges, ptm_type}
        
        for tp in self.timepoints:
            net = self.networks.get(tp, {})
            if not isinstance(net, dict):
                continue
            
            for node_list_key in ['active_nodes', 'inhibited_nodes']:
                for node in net.get(node_list_key, []):
                    gene = node.get('gene', node.get('name', ''))
                    if not gene:
                        continue
                    
                    site = node.get('site', '')
                    key = f"{gene}_{site}" if site else gene
                    
                    if key not in ptm_data:
                        ptm_data[key] = {
                            'gene': gene,
                            'site': site,
                            'values': [],
                            'timepoints': [],
                            'edge_count': 0,
                            'ptm_type': self._resolve_ptm_type(node),
                        }
                    
                    # Use 'value' field (from NetworkNode.to_dict())
                    value = node.get('value', node.get('log2fc', node.get('log2FC', 0)))
                    try:
                        value = float(value) if value else 0.0
                    except (ValueError, TypeError):
                        value = 0.0
                    
                    ptm_data[key]['values'].append(value)
                    ptm_data[key]['timepoints'].append(tp)
            
            # Count edges per node for network centrality
            for edge in net.get('active_edges', []) + net.get('inhibited_edges', []):
                source = edge.get('source', '')
                target = edge.get('target', '')
                for key in ptm_data:
                    if ptm_data[key]['gene'] in (source, target):
                        ptm_data[key]['edge_count'] += 1
        
        if not ptm_data:
            sse_log("[DR] No PTM data found in networks", "WARNING")
            return []
        
        # v3.0: Collect all absolute values for percentile-based magnitude scoring
        all_abs_values = []
        for data in ptm_data.values():
            if data['values']:
                max_abs = max(abs(v) for v in data['values'])
                all_abs_values.append(max_abs)
        
        all_abs_values_sorted = sorted(all_abs_values)
        n_total = len(all_abs_values_sorted)
        
        # Score each PTM
        scores = []
        for key, data in ptm_data.items():
            score = self._score_ptm(data, all_abs_values_sorted, n_total)
            scores.append(score)
        
        # Sort by composite score (descending)
        scores.sort(key=lambda s: s.composite, reverse=True)
        
        sse_log(f"[DR-15%] Scored {len(scores)} PTM targets. Top: {scores[0].gene} ({scores[0].composite:.1f})" if scores else "[DR-15%] No scores", "INFO")
        return scores
    
    def _resolve_ptm_type(self, node: Dict) -> str:
        """Resolve PTM type from node data, filtering out generic values like 'PTM'.
        
        The network nodes often have type='PTM' which is too generic.
        We prefer the detected_ptm_type (e.g., 'ubiquitylation') over generic labels.
        """
        generic_types = {'ptm', 'non-ptm', 'non_ptm', 'kinase', 'interactor', ''}
        
        # Try ptm_type field first
        pt = node.get('ptm_type', '')
        if pt and pt.lower().strip() not in generic_types:
            # Check if it's a known PTM type
            pt_lower = pt.lower().strip()
            for canonical in PTM_TYPE_CONFIG:
                if canonical in pt_lower or pt_lower in canonical:
                    return canonical
        
        # Try type field
        pt = node.get('type', '')
        if pt and pt.lower().strip() not in generic_types:
            pt_lower = pt.lower().strip()
            for canonical in PTM_TYPE_CONFIG:
                if canonical in pt_lower or pt_lower in canonical:
                    return canonical
        
        # Fall back to the detected PTM type (from summary/md_content/site patterns)
        return self.detected_ptm_type
    
    def _score_ptm(self, data: Dict, all_abs_sorted: List[float], n_total: int) -> PTMScore:
        """Score a single PTM target across 7 dimensions"""
        gene = data['gene']
        site = data['site']
        values = data['values']
        timepoints = data['timepoints']
        edge_count = data['edge_count']
        ptm_type = data.get('ptm_type', self.detected_ptm_type)
        
        # 1. Frequency (10%): fraction of timepoints detected
        n_tp = len(self.timepoints) if self.timepoints else 1
        frequency = len(set(timepoints)) / n_tp
        
        # 2. Magnitude (20%): v3.0 percentile-based
        max_abs = max(abs(v) for v in values) if values else 0
        magnitude = self._score_magnitude_percentile(max_abs, all_abs_sorted, n_total)
        
        # 3. Temporal (15%): consistency across timepoints
        temporal = self._score_temporal(values, timepoints)
        
        # 4. Functional (15%): based on known function
        functional = self._score_functional(gene)
        
        # 5. Network (20%): centrality from Part I
        network = self._score_network(gene, edge_count)
        
        # 6. Conservation (10%): placeholder
        conservation = 0.5
        
        # 7. Clinical (10%): placeholder
        clinical = self._score_clinical(gene)
        
        # Weighted composite
        composite = (
            frequency * 10 +
            magnitude * 20 +
            temporal * 15 +
            functional * 15 +
            network * 20 +
            conservation * 10 +
            clinical * 10
        )
        
        raw_log2fc = max(values, key=abs) if values else 0
        
        return PTMScore(
            gene=gene,
            site=site,
            ptm_type=ptm_type,
            frequency=frequency,
            magnitude=magnitude,
            temporal=temporal,
            functional=functional,
            network=network,
            conservation=conservation,
            clinical=clinical,
            composite=composite,
            raw_log2fc=raw_log2fc,
        )
    
    def _score_magnitude_percentile(self, max_abs: float, all_abs_sorted: List[float], n_total: int) -> float:
        """v3.0: Percentile-based magnitude scoring for unique values per PTM.
        
        Each PTM gets a score based on its rank among all PTMs' |Log2FC| values.
        This avoids the saturation problem where all high values get 1.0.
        """
        if n_total <= 1:
            return 0.5
        
        # Find rank (number of values strictly less than this value)
        rank = 0
        for v in all_abs_sorted:
            if v < max_abs:
                rank += 1
            else:
                break
        
        # Percentile: 0 to 1 (1 = highest)
        percentile = rank / (n_total - 1) if n_total > 1 else 0.5
        return percentile
    
    def _score_temporal(self, values: List[float], timepoints: List[str]) -> float:
        """Score temporal consistency"""
        if len(values) < 2:
            return 0.3
        
        # Check direction consistency
        directions = [1 if v > 0 else -1 for v in values if v != 0]
        if not directions:
            return 0.3
        
        consistent = sum(1 for d in directions if d == directions[0]) / len(directions)
        
        # Check magnitude trend
        abs_values = [abs(v) for v in values]
        increasing = all(abs_values[i] <= abs_values[i+1] for i in range(len(abs_values)-1))
        
        score = consistent * 0.7
        if increasing:
            score += 0.3
        
        return min(score, 1.0)
    
    def _score_functional(self, gene: str) -> float:
        """Score functional annotation"""
        # Check if gene is in known pathway databases
        pathway_db = get_pathway_db(self.detected_ptm_type)
        gene_upper = gene.upper()
        
        if gene_upper in pathway_db:
            return 0.8
        
        # Check in md_context
        if self.md_context and gene.lower() in self.md_context.lower():
            return 0.6
        
        return 0.4
    
    def _score_network(self, gene: str, edge_count: int) -> float:
        """Score network centrality from Part I data"""
        if edge_count == 0:
            return 0.2
        
        # Normalize: more edges = higher score
        # Typical range: 1-20 edges
        score = min(edge_count / 15.0, 1.0)
        return max(score, 0.2)
    
    def _score_clinical(self, gene: str) -> float:
        """Score clinical relevance"""
        # Check if gene has known clinical associations
        clinical_genes = {
            'EGFR', 'ERBB2', 'BRAF', 'ALK', 'MET', 'KIT', 'PDGFRA', 'FGFR1', 'FGFR2',
            'AKT1', 'MTOR', 'PIK3CA', 'CDK4', 'CDK6', 'BTK', 'JAK2', 'FLT3', 'RET',
            'MDM2', 'VHL', 'BRCA1', 'BRCA2', 'TP53', 'RB1', 'PTEN', 'KRAS', 'NRAS',
            'PARKIN', 'PRKN', 'UCHL1', 'BAP1', 'FBXW7', 'KEAP1',
        }
        
        if gene.upper() in clinical_genes:
            return 0.9
        
        return 0.4


# ============================================================================
# Step 2: Upstream Inference - v3.1 PTM-type-aware
# ============================================================================

class UpstreamInferrer:
    """
    Infer upstream regulators from Part I network data.
    
    v3.1: Adapts terminology and search logic based on PTM type:
    - phosphorylation: looks for kinases, kinase-substrate edges
    - ubiquitylation: looks for E3 ligases, ubiquitin-related edges
    - acetylation: looks for acetyltransferases, HATs/HDACs
    
    Uses multiple strategies:
    1. Network edges with relevant evidence_type
    2. Non-PTM nodes that are known regulators
    3. Pathway summary data from Part I
    4. Node pathway annotations
    5. PTM-type-specific pathway DB fallback
    """
    
    def __init__(self, analysis_results: Dict, ptm_type: str = ""):
        self.results = analysis_results
        self.networks = analysis_results.get('networks', {})
        self.ptm_type = ptm_type or detect_ptm_type_from_data(analysis_results)
        self.ptm_config = get_ptm_config(self.ptm_type)
        self.pathway_db = get_pathway_db(self.ptm_type)
    
    def infer_upstream(self, ptm_scores: List[PTMScore]) -> Dict[str, Dict]:
        """Infer upstream regulators for each PTM target"""
        sse_log(f"[DR-20%] Inferring upstream {self.ptm_config['upstream_types_plural']} from Part I network data...", "INFO")
        
        upstream_map = {}  # gene -> {regulators: [], pathways: [], evidence: []}
        
        for tp, net in self.networks.items():
            if not isinstance(net, dict):
                continue
            
            # === Strategy 1: Network edges with relevant evidence_type ===
            for edge in net.get('active_edges', []) + net.get('inhibited_edges', []):
                source = edge.get('source', '')
                target_node = edge.get('target', '')
                evidence_type = edge.get('evidence_type', edge.get('type', ''))
                
                # v3.1: Check against PTM-type-specific keywords
                evidence_lower = evidence_type.lower() if evidence_type else ''
                is_relevant_edge = any(kw in evidence_lower for kw in self.ptm_config['evidence_keywords'])
                
                # Also accept generic edge types
                if not is_relevant_edge:
                    is_relevant_edge = any(kw in evidence_lower for kw in ['ppi', 'interaction', 'regulation', 'substrate'])
                
                if is_relevant_edge:
                    if target_node not in upstream_map:
                        upstream_map[target_node] = {'regulators': [], 'pathways': [], 'evidence': []}
                    if source and source not in upstream_map[target_node]['regulators']:
                        upstream_map[target_node]['regulators'].append(source)
                        upstream_map[target_node]['evidence'].append({
                            'source': source,
                            'target': target_node,
                            'type': evidence_type,
                            'timepoint': tp,
                        })
                    
                    if source not in upstream_map:
                        upstream_map[source] = {'regulators': [], 'pathways': [], 'evidence': []}
                    if target_node and target_node not in upstream_map[source]['regulators']:
                        upstream_map[source]['regulators'].append(target_node)
            
            # === Strategy 2: Non-PTM nodes that are known regulators ===
            for node in net.get('active_nodes', []) + net.get('inhibited_nodes', []):
                node_type = node.get('type', node.get('node_type', ''))
                gene = node.get('gene', node.get('name', ''))
                
                # v3.1: Check against PTM-type-specific node type keywords
                is_regulator_node = any(kw in str(node_type) for kw in self.ptm_config['node_type_keywords'])
                
                if is_regulator_node and gene:
                    # This node is a potential upstream regulator
                    # Find which PTM targets it connects to via edges
                    for edge in net.get('active_edges', []) + net.get('inhibited_edges', []):
                        if edge.get('source', '') == gene:
                            target_node = edge.get('target', '')
                            if target_node:
                                if target_node not in upstream_map:
                                    upstream_map[target_node] = {'regulators': [], 'pathways': [], 'evidence': []}
                                if gene not in upstream_map[target_node]['regulators']:
                                    upstream_map[target_node]['regulators'].append(gene)
        
        # === Strategy 3: Pathway summary from Part I ===
        summary = self.results.get('summary', {})
        if isinstance(summary, dict):
            pathway_summary = summary.get('pathway_summary', '')
            if pathway_summary:
                for gene in upstream_map:
                    gene_name = gene.upper()
                    ptm_ref_str = pathway_summary.upper() if isinstance(pathway_summary, str) else str(pathway_summary).upper()
                    
                    # Extract pathway names that mention this gene
                    pathway_lines = pathway_summary.split('\n') if isinstance(pathway_summary, str) else []
                    for line in pathway_lines:
                        if gene_name in line.upper():
                            # Clean pathway text
                            cleaned_pathway = clean_pathway_text(line.strip())
                            if cleaned_pathway and len(cleaned_pathway) > 3:
                                if cleaned_pathway not in upstream_map[gene]['pathways']:
                                    upstream_map[gene]['pathways'].append(cleaned_pathway)
        
        # === Strategy 4: Map pathways from node data ===
        for tp, net in self.networks.items():
            if not isinstance(net, dict):
                continue
            for node in net.get('active_nodes', []) + net.get('inhibited_nodes', []):
                gene = node.get('gene', node.get('name', ''))
                if gene in upstream_map:
                    pathways = node.get('pathways', [])
                    for pw in pathways:
                        cleaned = clean_pathway_text(pw)
                        if cleaned and cleaned not in upstream_map[gene]['pathways']:
                            upstream_map[gene]['pathways'].append(cleaned)
        
        # === Strategy 5: PTM-type-specific pathway DB fallback ===
        for gene, data in upstream_map.items():
            for regulator in data['regulators']:
                regulator_upper = regulator.upper()
                if regulator_upper in self.pathway_db:
                    for pw in self.pathway_db[regulator_upper]:
                        if pw not in data['pathways']:
                            data['pathways'].append(pw)
            
            gene_upper = gene.upper()
            if gene_upper in self.pathway_db and not data['pathways']:
                data['pathways'] = list(self.pathway_db[gene_upper])
        
        # === Strategy 6: For PTMs without upstream regulators, add from pathway DB ===
        scored_genes = {s.gene for s in ptm_scores}
        for gene in scored_genes:
            if gene not in upstream_map:
                gene_upper = gene.upper()
                if gene_upper in self.pathway_db:
                    upstream_map[gene] = {
                        'regulators': [],
                        'pathways': list(self.pathway_db[gene_upper]),
                        'evidence': [],
                    }
                else:
                    upstream_map[gene] = {
                        'regulators': [],
                        'pathways': [],
                        'evidence': [],
                    }
        
        # === Strategy 7: Known regulator DB matching ===
        # For ubiquitylation: check if any non-PTM node in the network is a known E3 ligase/DUB
        # For phosphorylation: check if any non-PTM node is a known kinase
        # This helps when edge evidence_types don't contain PTM-specific keywords
        known_regulators = self._get_known_regulator_set()
        if known_regulators:
            for tp, net in self.networks.items():
                if not isinstance(net, dict):
                    continue
                
                # Find known regulators among non-PTM nodes
                network_regulators = set()
                for node in net.get('non_ptm_nodes', []):
                    gene = node.get('gene', node.get('name', node.get('id', '')))
                    if gene and gene.upper() in known_regulators:
                        network_regulators.add(gene)
                
                # Also check active/inhibited nodes that might be regulators
                for node in net.get('active_nodes', []) + net.get('inhibited_nodes', []):
                    gene = node.get('gene', node.get('name', node.get('id', '')))
                    if gene and gene.upper() in known_regulators:
                        network_regulators.add(gene)
                
                # For each known regulator found in the network, find its targets via edges
                if network_regulators:
                    for edge in net.get('active_edges', []) + net.get('inhibited_edges', []) + net.get('all_edges', []):
                        source = edge.get('source', '')
                        target_node = edge.get('target', '')
                        
                        # Check if source is a known regulator connecting to a scored gene
                        source_gene = source.split('-')[0] if '-' in source else source
                        target_gene = target_node.split('-')[0] if '-' in target_node else target_node
                        
                        if source_gene in network_regulators and target_gene in scored_genes:
                            if target_gene not in upstream_map:
                                upstream_map[target_gene] = {'regulators': [], 'pathways': [], 'evidence': []}
                            if source_gene not in upstream_map[target_gene]['regulators']:
                                upstream_map[target_gene]['regulators'].append(source_gene)
                                upstream_map[target_gene]['evidence'].append({
                                    'source': source_gene,
                                    'target': target_gene,
                                    'type': f'Known-{self.ptm_config["upstream_type"]}-DB',
                                    'timepoint': tp,
                                })
                        
                        # Also check reverse direction
                        if target_gene in network_regulators and source_gene in scored_genes:
                            if source_gene not in upstream_map:
                                upstream_map[source_gene] = {'regulators': [], 'pathways': [], 'evidence': []}
                            if target_gene not in upstream_map[source_gene]['regulators']:
                                upstream_map[source_gene]['regulators'].append(target_gene)
                                upstream_map[source_gene]['evidence'].append({
                                    'source': target_gene,
                                    'target': source_gene,
                                    'type': f'Known-{self.ptm_config["upstream_type"]}-DB',
                                    'timepoint': tp,
                                })
        
        # === Strategy 8: Assign known regulators from network even without direct edges ===
        # If a known regulator appears in the network and a scored gene has no regulators,
        # check if they share pathways (indirect evidence)
        if known_regulators:
            genes_without_regulators = [g for g in scored_genes if g in upstream_map and not upstream_map[g]['regulators']]
            if genes_without_regulators:
                # Collect all known regulators found anywhere in the network
                all_network_regulators = set()
                for tp, net in self.networks.items():
                    if not isinstance(net, dict):
                        continue
                    for node_list_key in ['non_ptm_nodes', 'active_nodes', 'inhibited_nodes']:
                        for node in net.get(node_list_key, []):
                            gene = node.get('gene', node.get('name', node.get('id', '')))
                            if gene and gene.upper() in known_regulators:
                                all_network_regulators.add(gene)
                
                # For genes without regulators, check if they share pathways with known regulators
                for gene in genes_without_regulators:
                    gene_pathways = set(upstream_map[gene].get('pathways', []))
                    if not gene_pathways:
                        continue
                    
                    for reg in all_network_regulators:
                        reg_upper = reg.upper()
                        reg_pathways = set(self.pathway_db.get(reg_upper, []))
                        shared = gene_pathways & reg_pathways
                        if shared:
                            if reg not in upstream_map[gene]['regulators']:
                                upstream_map[gene]['regulators'].append(reg)
                                upstream_map[gene]['evidence'].append({
                                    'source': reg,
                                    'target': gene,
                                    'type': f'Shared-Pathway-{self.ptm_config["upstream_type"]}',
                                    'timepoint': 'inferred',
                                })
                                break  # One regulator is enough per gene
        
        regulator_count = sum(1 for v in upstream_map.values() if v['regulators'])
        pathway_count = sum(1 for v in upstream_map.values() if v['pathways'])
        sse_log(f"[DR-25%] Mapped upstream {self.ptm_config['upstream_types_plural']} for {len(upstream_map)} targets ({regulator_count} with {self.ptm_config['upstream_types_plural']}, {pathway_count} with pathways)", "INFO")
        return upstream_map
    
    def _get_known_regulator_set(self) -> set:
        """Get set of known regulator gene names (uppercase) based on PTM type.
        
        For ubiquitylation: returns known E3 ligases and DUBs
        For phosphorylation: returns known kinases
        For acetylation: returns known acetyltransferases/HDACs
        """
        config = self.ptm_config
        db_key = config.get('pathway_db_key', 'KINASE')
        
        if db_key == 'E3_LIGASE':
            return set(E3_LIGASE_PATHWAY_DB.keys())
        elif db_key == 'ACETYLTRANSFERASE':
            return set(ACETYLTRANSFERASE_PATHWAY_DB.keys())
        else:
            return set(KINASE_PATHWAY_DB.keys())


# ============================================================================
# Step 3: Target Selection - v3.1 PTM-type-aware
# ============================================================================

class TargetSelector:
    """
    Prioritize drug targets based on PTM scores and upstream information.
    
    v3.0: Tier classification uses relative ranking:
    - Tier 1: Top 20% of targets
    - Tier 2: Next 30% (20-50%)
    - Tier 3: Next 30% (50-80%)
    - Tier 4: Bottom 20%
    """
    
    def __init__(self, ptm_scores: List[PTMScore], upstream_map: Dict[str, Dict], 
                 top_n: int = 10, ptm_type: str = ""):
        self.ptm_scores = ptm_scores
        self.upstream_map = upstream_map
        self.top_n = top_n
        self.ptm_type = ptm_type
        self.ptm_config = get_ptm_config(ptm_type)
    
    def select_targets(self) -> List[Dict]:
        """Select top drug targets"""
        sse_log(f"[DR-30%] Selecting top {self.top_n} drug targets...", "INFO")
        
        # v3.0: Calculate effective scores for all PTMs first (for relative ranking)
        all_effective_scores = []
        for score in self.ptm_scores:
            upstream = self.upstream_map.get(score.gene, {})
            regulators = upstream.get('regulators', [])
            pathways = upstream.get('pathways', [])
            effective = score.composite
            if regulators:
                effective += 5
            if pathways:
                effective += 3
            all_effective_scores.append(effective)
        
        # Sort for percentile thresholds
        sorted_effective = sorted(all_effective_scores, reverse=True)
        n = len(sorted_effective)
        
        targets = []
        for i, score in enumerate(self.ptm_scores[:self.top_n]):
            upstream = self.upstream_map.get(score.gene, {})
            regulators = upstream.get('regulators', [])
            pathways = upstream.get('pathways', [])
            
            effective = score.composite
            if regulators:
                effective += 5
            if pathways:
                effective += 3
            
            target = {
                'gene': score.gene,
                'site': score.site,
                'ptm_type': score.ptm_type,
                'composite_score': score.composite,
                'effective_score': effective,
                'raw_log2fc': score.raw_log2fc,
                'ptm_score': score.to_dict(),
                'upstream_regulator': regulators[0] if regulators else '',
                'all_upstream_regulators': regulators,
                'signaling_pathways': pathways,
                'druggability_tier': self._classify_tier_relative(effective, sorted_effective, n),
            }
            targets.append(target)
        
        if targets:
            tiers = {}
            for t in targets:
                tier = t['druggability_tier'].split(' - ')[0]
                tiers[tier] = tiers.get(tier, 0) + 1
            tier_summary = ', '.join(f"{k}: {v}" for k, v in sorted(tiers.items()))
            sse_log(f"[DR-32%] Selected {len(targets)} targets. Tier distribution: {tier_summary}", "INFO")
        
        return targets
    
    def _classify_tier_relative(self, effective_score: float, sorted_scores: List[float], n: int) -> str:
        """Classify target tier using relative ranking among all PTMs."""
        if n < 4:
            if effective_score >= 60:
                return "Tier 1 - High Priority"
            elif effective_score >= 40:
                return "Tier 2 - Moderate Priority"
            elif effective_score >= 20:
                return "Tier 3 - Exploratory"
            else:
                return "Tier 4 - Low Priority"
        
        rank = sum(1 for s in sorted_scores if s > effective_score)
        percentile = rank / n
        
        if percentile < 0.20:
            return "Tier 1 - High Priority"
        elif percentile < 0.50:
            return "Tier 2 - Moderate Priority"
        elif percentile < 0.80:
            return "Tier 3 - Exploratory"
        else:
            return "Tier 4 - Low Priority"


# ============================================================================
# Step 4: Drug Search (ChEMBL + PubChem) - v3.0 with Drug Name Resolution
# ============================================================================

class DrugSearcher:
    """
    Search for drug candidates targeting selected proteins.
    Uses free APIs: ChEMBL and PubChem.
    
    v3.0: Resolves ChEMBL IDs to actual drug names via molecule API.
    """
    
    CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
    PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'PTM-DrugRepositioning/3.2',
        })
        self._molecule_name_cache = {}
    
    def search_drugs(self, targets: List[Dict]) -> Dict[str, List[DrugCandidate]]:
        """Search for drugs targeting each selected protein"""
        sse_log(f"[DR-35%] Searching drug databases for {len(targets)} targets...", "INFO")
        
        all_drugs = {}
        
        for i, target in enumerate(targets):
            gene = target['gene']
            sse_log(f"[DR-{35 + (i * 10 // max(len(targets), 1))}%] Searching drugs for {gene}...", "INFO")
            
            candidates = []
            
            # Search ChEMBL
            chembl_results = self._search_chembl(gene)
            candidates.extend(chembl_results)
            
            # Search PubChem (if ChEMBL returns few results)
            if len(chembl_results) < 3:
                pubchem_results = self._search_pubchem(gene)
                candidates.extend(pubchem_results)
            
            # Also search for upstream regulator drugs
            upstream_regulator = target.get('upstream_regulator', '')
            if upstream_regulator and upstream_regulator != gene:
                regulator_drugs = self._search_chembl(upstream_regulator)
                for d in regulator_drugs:
                    d.target_gene = f"{upstream_regulator} (upstream of {gene})"
                candidates.extend(regulator_drugs)
            
            all_drugs[gene] = candidates
            sse_log(f"  Found {len(candidates)} drug candidates for {gene}", "INFO")
        
        total = sum(len(v) for v in all_drugs.values())
        sse_log(f"[DR-45%] Drug search complete. Total candidates: {total}", "INFO")
        return all_drugs
    
    def _resolve_molecule_name(self, chembl_id: str) -> str:
        """Resolve a ChEMBL molecule ID to its preferred name."""
        if chembl_id in self._molecule_name_cache:
            return self._molecule_name_cache[chembl_id]
        
        try:
            url = f"{self.CHEMBL_BASE}/molecule/{chembl_id}.json"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                pref_name = data.get('pref_name', '')
                if pref_name:
                    self._molecule_name_cache[chembl_id] = pref_name
                    return pref_name
                
                synonyms = data.get('molecule_synonyms', [])
                if synonyms:
                    for syn in synonyms:
                        if syn.get('syn_type') in ['TRADE_NAME', 'INN', 'USAN', 'BAN']:
                            name = syn.get('molecule_synonym', '')
                            if name:
                                self._molecule_name_cache[chembl_id] = name
                                return name
                    first_syn = synonyms[0].get('molecule_synonym', '')
                    if first_syn:
                        self._molecule_name_cache[chembl_id] = first_syn
                        return first_syn
        except Exception:
            pass
        
        self._molecule_name_cache[chembl_id] = chembl_id
        return chembl_id
    
    def _search_chembl(self, gene: str) -> List[DrugCandidate]:
        """Search ChEMBL for drugs targeting a gene"""
        candidates = []
        
        try:
            # Step 1: Find target in ChEMBL
            url = f"{self.CHEMBL_BASE}/target/search.json"
            params = {'q': gene, 'limit': 5, 'format': 'json'}
            
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return candidates
            
            data = resp.json()
            targets = data.get('targets', [])
            if not targets:
                return candidates
            
            target_chembl_id = targets[0].get('target_chembl_id', '')
            if not target_chembl_id:
                return candidates
            
            # Step 2: Find approved drugs for this target
            url = f"{self.CHEMBL_BASE}/mechanism.json"
            params = {'target_chembl_id': target_chembl_id, 'limit': 10, 'format': 'json'}
            
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return candidates
            
            data = resp.json()
            mechanisms = data.get('mechanisms', [])
            
            for mech in mechanisms:
                molecule_chembl_id = mech.get('molecule_chembl_id', '')
                raw_name = mech.get('molecule_name', '') or ''
                moa = mech.get('mechanism_of_action', '')
                
                if not raw_name or raw_name.startswith('CHEMBL'):
                    drug_name = self._resolve_molecule_name(molecule_chembl_id) if molecule_chembl_id else raw_name
                else:
                    drug_name = raw_name
                
                if drug_name or molecule_chembl_id:
                    candidates.append(DrugCandidate(
                        drug_name=drug_name or molecule_chembl_id,
                        drug_id=molecule_chembl_id,
                        source='ChEMBL',
                        target_gene=gene,
                        mechanism_of_action=moa,
                        approval_status=str(mech.get('max_phase', '')),
                    ))
            
            # Step 3: Also search for bioactivities
            if len(candidates) < 3:
                url = f"{self.CHEMBL_BASE}/activity.json"
                params = {
                    'target_chembl_id': target_chembl_id,
                    'pchembl_value__gte': 6,
                    'limit': 5,
                    'format': 'json',
                }
                
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    activities = data.get('activities', [])
                    
                    seen_molecules = {c.drug_id for c in candidates}
                    for act in activities:
                        mol_id = act.get('molecule_chembl_id', '')
                        if mol_id and mol_id not in seen_molecules:
                            raw_name = act.get('molecule_name', '') or ''
                            if not raw_name or raw_name.startswith('CHEMBL'):
                                drug_name = self._resolve_molecule_name(mol_id)
                            else:
                                drug_name = raw_name
                            
                            candidates.append(DrugCandidate(
                                drug_name=drug_name or mol_id,
                                drug_id=mol_id,
                                source='ChEMBL',
                                target_gene=gene,
                                activity_type=act.get('standard_type', ''),
                                activity_value=f"{act.get('standard_value', '')} {act.get('standard_units', '')}".strip(),
                            ))
                            seen_molecules.add(mol_id)
        
        except requests.exceptions.RequestException as e:
            sse_log(f"  ChEMBL search failed for {gene}: {e}", "WARNING")
        except Exception as e:
            sse_log(f"  ChEMBL parsing error for {gene}: {e}", "WARNING")
        
        return candidates[:10]
    
    def _search_pubchem(self, gene: str) -> List[DrugCandidate]:
        """Search PubChem for compounds targeting a gene"""
        candidates = []
        
        try:
            url = f"{self.PUBCHEM_BASE}/compound/name/{gene}/JSON"
            
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{gene} inhibitor/JSON"
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    return candidates
            
            data = resp.json()
            compounds = data.get('PC_Compounds', [])
            
            for comp in compounds[:5]:
                cid = comp.get('id', {}).get('id', {}).get('cid', '')
                props = {}
                for prop in comp.get('props', []):
                    label = prop.get('urn', {}).get('label', '')
                    value = prop.get('value', {})
                    if label == 'IUPAC Name':
                        props['name'] = value.get('sval', '')
                    elif label == 'Molecular Formula':
                        props['formula'] = value.get('sval', '')
                
                if cid:
                    candidates.append(DrugCandidate(
                        drug_name=props.get('name', f'CID-{cid}'),
                        drug_id=f'CID-{cid}',
                        source='PubChem',
                        target_gene=gene,
                        molecular_formula=props.get('formula', ''),
                    ))
        
        except requests.exceptions.RequestException as e:
            sse_log(f"  PubChem search failed for {gene}: {e}", "WARNING")
        except Exception as e:
            sse_log(f"  PubChem parsing error for {gene}: {e}", "WARNING")
        
        return candidates[:5]


# ============================================================================
# Step 5: Clinical Trials Search - v3.0
# ============================================================================

class ClinicalTrialSearcher:
    """
    Search ClinicalTrials.gov for relevant clinical trials.
    Uses the free ClinicalTrials.gov API v2.
    """
    
    BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
    
    def search_trials(self, targets: List[Dict], drugs: Dict[str, List[DrugCandidate]]) -> Dict[str, List[ClinicalTrial]]:
        """Search clinical trials for targets and their drug candidates"""
        sse_log(f"[DR-50%] Searching ClinicalTrials.gov...", "INFO")
        
        all_trials = {}
        
        for target in targets:
            gene = target['gene']
            gene_drugs = drugs.get(gene, [])
            
            trials = []
            
            # Search by gene name
            gene_trials = self._search_by_query(gene)
            for t in gene_trials:
                t.target_gene = gene
                if not t.drug_name and gene_drugs:
                    t.drug_name = gene_drugs[0].drug_name
            trials.extend(gene_trials)
            
            # Search by drug names (top 3)
            for drug in gene_drugs[:3]:
                if drug.drug_name and drug.drug_name != drug.drug_id and not drug.drug_name.startswith('CHEMBL'):
                    drug_trials = self._search_by_query(drug.drug_name)
                    for t in drug_trials:
                        t.drug_name = drug.drug_name
                        t.target_gene = gene
                    trials.extend(drug_trials)
            
            # Deduplicate by trial ID
            seen = set()
            unique_trials = []
            for t in trials:
                if t.trial_id not in seen:
                    seen.add(t.trial_id)
                    unique_trials.append(t)
            
            all_trials[gene] = unique_trials[:10]
            if unique_trials:
                sse_log(f"  Found {len(unique_trials)} clinical trials for {gene}", "INFO")
        
        total = sum(len(v) for v in all_trials.values())
        sse_log(f"[DR-55%] Clinical trials search complete. Total: {total}", "INFO")
        return all_trials
    
    def _search_by_query(self, query: str) -> List[ClinicalTrial]:
        """Search ClinicalTrials.gov by query string"""
        trials = []
        
        try:
            params = {
                'query.term': query,
                'pageSize': 5,
                'format': 'json',
            }
            
            resp = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return trials
            
            data = resp.json()
            studies = data.get('studies', [])
            
            for study in studies:
                protocol = study.get('protocolSection', {})
                id_module = protocol.get('identificationModule', {})
                status_module = protocol.get('statusModule', {})
                design_module = protocol.get('designModule', {})
                conditions_module = protocol.get('conditionsModule', {})
                
                arms_module = protocol.get('armsInterventionsModule', {})
                interventions = arms_module.get('interventions', [])
                drug_name = ''
                for intervention in interventions:
                    if intervention.get('type', '').upper() in ['DRUG', 'BIOLOGICAL']:
                        drug_name = intervention.get('name', '')
                        break
                
                nct_id = id_module.get('nctId', '')
                title = id_module.get('briefTitle', '')
                status = status_module.get('overallStatus', '')
                
                phases = design_module.get('phases', [])
                phase = ', '.join(phases) if phases else 'N/A'
                
                conditions = conditions_module.get('conditions', [])
                conditions_str = ', '.join(conditions[:3]) if conditions else ''
                
                start_date_struct = status_module.get('startDateStruct', {})
                start_date = start_date_struct.get('date', '')
                
                if nct_id:
                    trials.append(ClinicalTrial(
                        trial_id=nct_id,
                        title=title,
                        phase=phase,
                        status=status,
                        drug_name=drug_name,
                        conditions=conditions_str,
                        start_date=start_date,
                        target_gene=query,
                    ))
        
        except requests.exceptions.RequestException as e:
            sse_log(f"  ClinicalTrials.gov search failed for {query}: {e}", "WARNING")
        except Exception as e:
            sse_log(f"  ClinicalTrials.gov parsing error for {query}: {e}", "WARNING")
        
        return trials


# ============================================================================
# Step 6: Repositioning Evaluation (LLM-based) - v3.1 PTM-type-aware
# ============================================================================

class RepositioningEvaluator:
    """
    Evaluate repositioning candidates using LLM.
    
    v3.1: Passes correct PTM type to LLM prompts.
    v3.0: Increased max_tokens, better prompts with Part I context.
    """
    
    def __init__(self, call_llm_func, model: str = "gemma3:27b", ptm_type: str = ""):
        self.call_llm = call_llm_func
        self.model = model
        self.ptm_type = ptm_type
        self.ptm_config = get_ptm_config(ptm_type)
    
    def evaluate_candidates(self, candidates: List[RepositioningCandidate], 
                          ptm_context: str = "") -> List[RepositioningCandidate]:
        """Evaluate each repositioning candidate using LLM"""
        sse_log(f"[DR-60%] Evaluating {len(candidates)} repositioning candidates with LLM...", "INFO")
        
        for i, candidate in enumerate(candidates):
            sse_log(f"[DR-{60 + (i * 15 // max(len(candidates), 1))}%] Evaluating {candidate.target_gene} + {candidate.drug.drug_name}...", "INFO")
            
            prompt = self._build_evaluation_prompt(candidate, ptm_context)
            
            try:
                response = self.call_llm(
                    prompt=prompt,
                    model=self.model,
                    max_tokens=1500,
                    temperature=0.3,
                )
                
                if response:
                    candidate.llm_evaluation = response.strip()
                    candidate.repositioning_score = self._extract_score(response)
                else:
                    candidate.llm_evaluation = "Evaluation not available."
                    candidate.repositioning_score = 50
                    
            except Exception as e:
                sse_log(f"  LLM evaluation failed for {candidate.target_gene}: {e}", "WARNING")
                candidate.llm_evaluation = f"Evaluation failed: {str(e)[:100]}"
                candidate.repositioning_score = 50
        
        sse_log(f"[DR-75%] LLM evaluation complete for {len(candidates)} candidates", "INFO")
        return candidates
    
    def _build_evaluation_prompt(self, candidate: RepositioningCandidate, ptm_context: str) -> str:
        """Build evaluation prompt for LLM - v3.1: correct PTM type"""
        trials_info = ""
        if candidate.clinical_trials:
            trials_info = "\n".join([
                f"  - {t.trial_id}: {t.title} (Phase: {t.phase}, Status: {t.status})"
                for t in candidate.clinical_trials[:5]
            ])
        else:
            trials_info = "  No clinical trials found."
        
        # v3.1: Use correct PTM type terminology
        ptm_type_desc = self.ptm_config['description']
        upstream_label = self.ptm_config['upstream_label']
        
        prompt = f"""You are an expert in drug repositioning and post-translational modification (PTM) biology.

Evaluate the following drug repositioning candidate based on the {candidate.ptm_type} analysis data:

**Target Information:**
- Gene: {candidate.target_gene}
- PTM Site: {candidate.target_site}
- PTM Type: {candidate.ptm_type} ({ptm_type_desc})
- PTM Druggability Score: {candidate.ptm_score:.1f}/100
- {upstream_label}: {candidate.upstream_regulator or 'Not identified'}
- Signaling Pathway: {candidate.signaling_pathway or 'Not determined'}

**Drug Candidate:**
- Drug Name: {candidate.drug.drug_name}
- Drug ID: {candidate.drug.drug_id}
- Source: {candidate.drug.source}
- Mechanism of Action: {candidate.drug.mechanism_of_action or 'Not specified'}
- Approval Status: {candidate.drug.approval_status or 'Unknown'}
- Original Indication: {candidate.drug.original_indication or 'Not specified'}

**Clinical Trials:**
{trials_info}

**PTM Analysis Context (from Part I Network Analysis):**
{ptm_context[:1500] if ptm_context else 'Not available'}

IMPORTANT: The PTM type in this analysis is **{candidate.ptm_type}**, NOT phosphorylation (unless the data is actually phosphorylation data). Please ensure your evaluation correctly references {candidate.ptm_type} biology and mechanisms.

Please provide:
1. **Biological Rationale** (2-3 sentences): Why this drug-target combination is scientifically plausible based on the {candidate.ptm_type} and network analysis data.
2. **Repositioning Potential** (1-2 sentences): Assessment of the drug's potential for repositioning.
3. **Key Considerations** (2-3 bullet points): Important factors for further investigation.
4. **Repositioning Score**: A score from 0-100 indicating repositioning potential.

Format your response as a concise scientific assessment. End with "Score: XX/100"."""
        
        return prompt
    
    def _extract_score(self, response: str) -> float:
        """Extract repositioning score from LLM response"""
        patterns = [
            r'Score:\s*(\d+)\s*/\s*100',
            r'Score:\s*(\d+)',
            r'(\d+)\s*/\s*100',
            r'repositioning score[:\s]*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                score = float(match.group(1))
                return min(max(score, 0), 100)
        
        return 50


# ============================================================================
# Step 7: Report Section Generation - v3.1 PTM-type-aware
# ============================================================================

class ReportGenerator:
    """
    Generate Drug Repositioning report sections for the extended report.
    
    v3.1: 
    - All terminology adapts to detected PTM type
    - Methods section dynamically generated based on PTM type
    - "Upstream Kinase" → PTM-type-appropriate label
    
    v3.0:
    - Methods section added
    - Part I cross-references in narrative
    - Clean pathway text
    - Proper drug names
    """
    
    def __init__(self, call_llm_func=None, model: str = "gemma3:27b", ptm_type: str = ""):
        self.call_llm = call_llm_func
        self.model = model
        self.ptm_type = ptm_type
        self.ptm_config = get_ptm_config(ptm_type)
    
    def generate_sections(self, targets: List[Dict], drugs: Dict[str, List[DrugCandidate]],
                         trials: Dict[str, List[ClinicalTrial]], 
                         candidates: List[RepositioningCandidate],
                         ptm_scores: List[PTMScore],
                         upstream_map: Dict[str, Dict]) -> str:
        """Generate all Drug Repositioning report sections"""
        sse_log("[DR-80%] Generating Drug Repositioning report sections...", "INFO")
        
        sections = []
        
        # Methods section
        sections.append(self._generate_methods_section())
        
        # Section 1: Drug Target Prioritization
        sections.append(self._generate_target_section(targets, ptm_scores, upstream_map))
        
        # Section 2: Drug Repositioning Candidates
        sections.append(self._generate_drug_section(candidates, drugs))
        
        # Section 3: Clinical Trials
        sections.append(self._generate_clinical_section(candidates, trials))
        
        # Section 4: LLM Evaluation
        sections.append(self._generate_evaluation_section(candidates))
        
        # Section 5: Summary
        sections.append(self._generate_summary_section(candidates, targets))
        
        sse_log("[DR-95%] Report sections generated", "SUCCESS")
        return "\n\n".join(sections)
    
    def _generate_methods_section(self) -> str:
        """Generate the Methods section - v3.1: PTM-type-aware"""
        ptm_desc = self.ptm_config['description']
        upstream_label = self.ptm_config['upstream_label']
        upstream_label_plural = self.ptm_config['upstream_label_plural']
        upstream_types = self.ptm_config['upstream_types_plural']
        regulator_label = self.ptm_config['regulator_label']
        mod_verb = self.ptm_config['modification_verb']
        
        return f"""## Methods: Drug Repositioning Analysis

### Overview

The Drug Repositioning Analysis (Part II) extends the PTM-NonPTM Network Analysis (Part I) by systematically evaluating the therapeutic potential of identified {mod_verb} targets. This analysis integrates network-derived insights with external pharmacological databases to identify drug repositioning opportunities.

### 7-Dimensional PTM Druggability Scoring

Each {mod_verb} site identified in Part I was scored across seven dimensions to assess druggability potential:

1. **Frequency Score (10%)**: Proportion of timepoints in which the {mod_verb} site was detected as significantly modified. Higher frequency indicates robust and reproducible modification.
2. **Magnitude Score (20%)**: Percentile-based ranking of the absolute Log2 fold-change (abs(Log2FC)) among all detected {mod_verb} sites. This approach ensures each PTM receives a unique score reflecting its relative effect size, avoiding the saturation problem of threshold-based normalization.
3. **Temporal Consistency Score (15%)**: Evaluates the consistency of modification direction (up/down) across timepoints and whether the effect magnitude increases over time.
4. **Functional Annotation Score (15%)**: Based on whether the target gene is present in curated pathway databases relevant to {mod_verb} biology.
5. **Network Centrality Score (20%)**: Derived from Part I interaction data, measuring the number of edges (interactions) per node. Higher connectivity suggests greater biological importance.
6. **Conservation Score (10%)**: Baseline score reflecting general protein conservation (placeholder for future cross-species analysis).
7. **Clinical Relevance Score (10%)**: Based on whether the target gene has known clinical associations in cancer, metabolic, or neurodegenerative disease pathways.

### Upstream Regulator Inference

{upstream_label_plural} were identified using a multi-strategy approach:

1. **Part I Network Edges**: Edges with {mod_verb}-relevant evidence types (e.g., {regulator_label}-substrate relationships) from the Part I network analysis.
2. **Non-PTM Regulator Nodes**: Non-PTM nodes identified as {upstream_types} in the Part I network that connect to {mod_verb} targets.
3. **Pathway Summary Integration**: Pathway annotations from the Part I summary data were mapped to target genes.
4. **Node Pathway Annotations**: Direct pathway annotations from network nodes.
5. **Curated Database Fallback**: A curated database of known {upstream_types} and their associated signaling pathways was used as a fallback for targets without network-derived upstream information.

### Target Prioritization

Targets were ranked by composite druggability score and classified into tiers using percentile-based ranking:
- **Tier 1 (High Priority)**: Top 20% of targets by effective score
- **Tier 2 (Moderate Priority)**: 20th-50th percentile
- **Tier 3 (Exploratory)**: 50th-80th percentile
- **Tier 4 (Low Priority)**: Bottom 20%

### Drug Candidate Identification

Drug candidates were identified from two sources:
1. **ChEMBL**: Searched for approved drugs and bioactive compounds targeting each gene. Drug names were resolved via the ChEMBL molecule API to replace ChEMBL IDs with preferred drug names.
2. **PubChem**: Supplementary search for compounds when ChEMBL returned fewer than 3 candidates.

### Clinical Trial Search

ClinicalTrials.gov API v2 was queried for each target gene and its associated drug candidates to identify relevant ongoing or completed clinical trials.

### LLM-Based Repositioning Evaluation

Each drug-target pair was evaluated by a large language model (LLM) to assess biological rationale, repositioning potential, and key considerations. The LLM was provided with the {mod_verb} analysis context from Part I to ensure integrated assessment. The LLM was explicitly informed of the correct PTM type ({mod_verb}) to ensure accurate biological reasoning.

---
"""
    
    def _generate_target_section(self, targets: List[Dict], ptm_scores: List[PTMScore],
                                upstream_map: Dict[str, Dict]) -> str:
        """Generate Drug Target Prioritization section - v3.1: PTM-type-aware labels"""
        upstream_label_plural = self.ptm_config['upstream_label_plural']
        mod_verb = self.ptm_config['modification_verb']
        
        lines = []
        lines.append("## Drug Target Prioritization")
        lines.append("")
        lines.append(f"The following {mod_verb} targets were prioritized based on the 7-dimensional druggability scoring system, ")
        lines.append("integrating data from the Part I PTM-NonPTM Network Analysis. Targets are ranked by composite score ")
        lines.append("and classified into tiers using percentile-based ranking.")
        lines.append("")
        
        # Summary table
        lines.append("### Target Ranking Summary")
        lines.append("")
        lines.append(f"| Rank | Gene | Site | Composite Score | Log2FC | Tier | {upstream_label_plural} | Signaling Pathway |")
        lines.append("|------|------|------|----------------|--------|------|-------------------|-------------------|")
        
        for i, target in enumerate(targets, 1):
            gene = target['gene']
            site = target.get('site', '')
            score = target.get('composite_score', 0)
            raw_log2fc = target.get('raw_log2fc', 0)
            tier = target.get('druggability_tier', 'N/A')
            tier_short = tier.split(' - ')[0] if ' - ' in tier else tier
            
            regulators = target.get('all_upstream_regulators', [])
            regulator_str = ', '.join(str(r) for r in regulators[:3]) if regulators else 'N/A'
            
            pathways = target.get('signaling_pathways', [])
            pathway_str = ', '.join(
                p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in pathways[:2]
            ) if pathways else 'N/A'
            
            lines.append(f"| {i} | {gene} | {site} | {score:.1f} | {raw_log2fc:.2f} | {tier_short} | {regulator_str} | {pathway_str} |")
        
        lines.append("")
        
        # Detailed scoring breakdown
        lines.append("### Detailed Scoring Breakdown")
        lines.append("")
        lines.append("| Gene | Site | Frequency | Magnitude | Temporal | Functional | Network | Conservation | Clinical |")
        lines.append("|------|------|-----------|-----------|----------|------------|---------|-------------|----------|")
        
        for target in targets:
            gene = target['gene']
            ptm_score = target.get('ptm_score', {})
            lines.append(
                f"| {gene} | {target.get('site', '')} "
                f"| {ptm_score.get('frequency', 0):.2f} "
                f"| {ptm_score.get('magnitude', 0):.2f} "
                f"| {ptm_score.get('temporal', 0):.2f} "
                f"| {ptm_score.get('functional', 0):.2f} "
                f"| {ptm_score.get('network', 0):.2f} "
                f"| {ptm_score.get('conservation', 0):.2f} "
                f"| {ptm_score.get('clinical', 0):.2f} |"
            )
        
        lines.append("")
        
        # Upstream regulator details
        upstream_label = self.ptm_config['upstream_label']
        upstream_types = self.ptm_config['upstream_types_plural']
        
        lines.append(f"### {upstream_label} Mapping")
        lines.append("")
        lines.append(f"Upstream {upstream_types} were identified from the Part I network analysis ")
        lines.append(f"and supplemented with curated {upstream_types}-pathway databases.")
        lines.append("")
        
        for target in targets:
            gene = target['gene']
            upstream = upstream_map.get(gene, {})
            regulators = upstream.get('regulators', [])
            pathways = upstream.get('pathways', [])
            evidence = upstream.get('evidence', [])
            
            if regulators or pathways:
                lines.append(f"**{gene}** ({target.get('site', '')})")
                if regulators:
                    lines.append(f"- {upstream_label_plural}: {', '.join(str(r) for r in regulators)}")
                if pathways:
                    lines.append(f"- Signaling Pathway(s): {', '.join(p.get('name', str(p)) if isinstance(p, dict) else str(p) for p in pathways[:5])}")
                if evidence:
                    for ev in evidence[:2]:
                        lines.append(f"  - Evidence: {ev.get('source', '')} → {ev.get('target', '')} ({ev.get('type', '')}, {ev.get('timepoint', '')})")
                lines.append("")
        
        return "\n".join(lines)
    
    def _generate_drug_section(self, candidates: List[RepositioningCandidate], 
                              drugs: Dict[str, List[DrugCandidate]]) -> str:
        """Generate Drug Repositioning Candidates section"""
        lines = []
        lines.append("## Drug Repositioning Candidates")
        lines.append("")
        lines.append("Drug candidates were identified from ChEMBL and PubChem databases. ")
        lines.append("The ChEMBL molecule API was used to resolve drug identifiers to their preferred names.")
        lines.append("")
        
        # ChEMBL results table
        lines.append("### ChEMBL Drug Candidates")
        lines.append("")
        lines.append("| Target Gene | Drug Name | Drug ID | Mechanism of Action | Approval Status |")
        lines.append("|-------------|-----------|---------|--------------------|-----------------| ")
        
        seen_pairs = set()
        for gene, drug_list in drugs.items():
            for drug in drug_list:
                if drug.source == 'ChEMBL':
                    pair = (gene, drug.drug_id)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        moa = drug.mechanism_of_action[:80] if drug.mechanism_of_action else 'N/A'
                        approval = drug.approval_status if drug.approval_status else 'N/A'
                        lines.append(f"| {gene} | {drug.drug_name} | {drug.drug_id} | {moa} | {approval} |")
        
        lines.append("")
        
        # PubChem results (if any)
        pubchem_drugs = [(gene, d) for gene, dlist in drugs.items() for d in dlist if d.source == 'PubChem']
        if pubchem_drugs:
            lines.append("### PubChem Compound Candidates")
            lines.append("")
            lines.append("| Target Gene | Compound Name | Compound ID | Molecular Formula |")
            lines.append("|-------------|---------------|-------------|-------------------|")
            for gene, drug in pubchem_drugs:
                lines.append(f"| {gene} | {drug.drug_name} | {drug.drug_id} | {drug.molecular_formula or 'N/A'} |")
            lines.append("")
        
        return "\n".join(lines)
    
    def _generate_clinical_section(self, candidates: List[RepositioningCandidate],
                                  trials: Dict[str, List[ClinicalTrial]]) -> str:
        """Generate Clinical Trials section"""
        lines = []
        lines.append("## Clinical Translation Potential")
        lines.append("")
        lines.append("Clinical trials were identified from ClinicalTrials.gov for each target gene and associated drug candidates.")
        lines.append("")
        
        lines.append("| Target Gene | Drug | Trial ID | Phase | Status | Conditions |")
        lines.append("|-------------|------|----------|-------|--------|------------|")
        
        has_trials = False
        for gene, trial_list in trials.items():
            for trial in trial_list[:5]:
                has_trials = True
                drug_name = trial.drug_name if trial.drug_name else 'N/A'
                conditions = trial.conditions[:60] if trial.conditions else 'N/A'
                lines.append(f"| {gene} | {drug_name} | {trial.trial_id} | {trial.phase} | {trial.status} | {conditions} |")
        
        if not has_trials:
            lines.append("| - | - | No clinical trials found | - | - | - |")
        
        lines.append("")
        return "\n".join(lines)
    
    def _generate_evaluation_section(self, candidates: List[RepositioningCandidate]) -> str:
        """Generate LLM Evaluation section - v3.1: PTM-type-aware labels"""
        upstream_label = self.ptm_config['upstream_label']
        
        lines = []
        lines.append("## LLM-Based Repositioning Evaluation")
        lines.append("")
        lines.append(f"Each drug-target pair was evaluated by a large language model to assess biological rationale ")
        lines.append(f"and repositioning potential, incorporating context from the Part I {self.ptm_config['modification_verb']} network analysis.")
        lines.append("")
        
        for i, candidate in enumerate(candidates, 1):
            lines.append(f"### {i}. {candidate.target_gene} ({candidate.target_site}) + {candidate.drug.drug_name}")
            lines.append("")
            lines.append(f"- **PTM Type**: {candidate.ptm_type}")
            lines.append(f"- **Repositioning Score**: {candidate.repositioning_score:.0f}/100")
            lines.append(f"- **{upstream_label}**: {candidate.upstream_regulator or 'Not identified'}")
            lines.append(f"- **Signaling Pathway**: {candidate.signaling_pathway or 'Not determined'}")
            lines.append("")
            
            if candidate.llm_evaluation:
                lines.append(candidate.llm_evaluation)
            else:
                lines.append("*Evaluation not available.*")
            lines.append("")
        
        return "\n".join(lines)
    
    def _generate_summary_section(self, candidates: List[RepositioningCandidate], 
                                 targets: List[Dict]) -> str:
        """Generate summary section - v3.1: PTM-type-aware"""
        upstream_label_plural = self.ptm_config['upstream_label_plural']
        upstream_types = self.ptm_config['upstream_types_plural']
        mod_verb = self.ptm_config['modification_verb']
        
        lines = []
        lines.append("## Drug Repositioning Summary")
        lines.append("")
        
        if candidates:
            sorted_candidates = sorted(candidates, key=lambda c: c.repositioning_score, reverse=True)
            top = sorted_candidates[0]
            
            lines.append(f"This analysis identified **{len(candidates)} drug repositioning candidates** across ")
            lines.append(f"**{len(targets)} prioritized {mod_verb} targets** from the Part I network analysis. ")
            lines.append(f"The highest-scoring candidate is **{top.drug.drug_name}** targeting **{top.target_gene}** ")
            lines.append(f"(Repositioning Score: {top.repositioning_score:.0f}/100).")
            lines.append("")
            
            # Integration with Part I
            lines.append("### Integration with Part I Network Analysis")
            lines.append("")
            lines.append(f"The Drug Repositioning analysis leveraged the following data from Part I:")
            lines.append("")
            
            regulator_targets = [t for t in targets if t.get('all_upstream_regulators')]
            pathway_targets = [t for t in targets if t.get('signaling_pathways')]
            
            lines.append(f"- **{len(regulator_targets)}/{len(targets)}** targets had upstream {upstream_types} identified from the Part I network analysis")
            lines.append(f"- **{len(pathway_targets)}/{len(targets)}** targets were mapped to signaling pathways from the Part I network")
            lines.append(f"- Network centrality scores were derived from Part I interaction data (edge counts per node)")
            lines.append(f"- Temporal dynamics from Part I informed the temporal consistency scoring dimension")
            lines.append("")
            
            # Tier distribution
            tier_counts = {}
            for t in targets:
                tier = t.get('druggability_tier', 'Unknown')
                tier_short = tier.split(' - ')[0]
                tier_counts[tier_short] = tier_counts.get(tier_short, 0) + 1
            
            lines.append("### Tier Distribution")
            lines.append("")
            for tier, count in sorted(tier_counts.items()):
                lines.append(f"- **{tier}**: {count} target(s)")
            lines.append("")
            
            # Top candidates table
            lines.append("### Top Repositioning Candidates")
            lines.append("")
            lines.append("| Rank | Target | Drug | Repositioning Score | Tier |")
            lines.append("|------|--------|------|--------------------|----- |")
            
            for i, cand in enumerate(sorted_candidates[:5], 1):
                tier = 'N/A'
                for t in targets:
                    if t['gene'] == cand.target_gene:
                        tier = t.get('druggability_tier', 'N/A').split(' - ')[0]
                        break
                lines.append(f"| {i} | {cand.target_gene} ({cand.target_site}) | {cand.drug.drug_name} | {cand.repositioning_score:.0f}/100 | {tier} |")
            
            lines.append("")
        else:
            lines.append("No drug repositioning candidates were identified in this analysis.")
            lines.append("")
        
        return "\n".join(lines)
    
    def generate_llm_summary(self, candidates: List[RepositioningCandidate], 
                            ptm_context: str = "") -> str:
        """Generate an overall LLM summary of the Drug Repositioning analysis"""
        if not self.call_llm or not candidates:
            return ""
        
        sse_log("[DR-90%] Generating LLM summary of Drug Repositioning analysis...", "INFO")
        
        upstream_label = self.ptm_config['upstream_label']
        mod_verb = self.ptm_config['modification_verb']
        
        candidate_summaries = []
        for c in candidates[:5]:
            candidate_summaries.append(
                f"- {c.target_gene} ({c.target_site}): {c.drug.drug_name} "
                f"(Score: {c.repositioning_score:.0f}/100, "
                f"{upstream_label}: {c.upstream_regulator or 'N/A'}, "
                f"Pathway: {c.signaling_pathway or 'N/A'})"
            )
        
        prompt = f"""You are an expert in drug repositioning and PTM biology.

Based on the following drug repositioning analysis results for **{mod_verb}** data, provide a concise overall summary (3-4 paragraphs) that:
1. Highlights the most promising repositioning opportunities
2. Discusses the biological rationale connecting {mod_verb} modifications to drug targets
3. Notes any limitations and suggests next steps for experimental validation

IMPORTANT: This analysis is based on **{mod_verb}** data, NOT phosphorylation (unless it actually is phosphorylation). Please ensure your summary correctly references {mod_verb} biology.

**Top Drug Repositioning Candidates:**
{chr(10).join(candidate_summaries)}

**PTM Analysis Context:**
{ptm_context[:2000] if ptm_context else 'Not available'}

Write a professional scientific summary suitable for inclusion in a research report."""
        
        try:
            response = self.call_llm(
                prompt=prompt,
                model=self.model,
                max_tokens=3000,
                temperature=0.3,
            )
            return response.strip() if response else ""
        except Exception as e:
            sse_log(f"LLM summary generation failed: {e}", "WARNING")
            return ""


# ============================================================================
# Main Pipeline Class - v3.1 PTM-type-aware
# ============================================================================

class DrugRepositioningPipeline:
    """
    Main pipeline orchestrator for Drug Repositioning analysis.
    
    v3.2: Fixed PTM type detection + renamed all 'kinase' internal keys to 'regulator'.
    v3.1: Full PTM-type awareness throughout the pipeline.
    v3.0: Full Part I integration, percentile-based scoring, methods section.
    """
    
    def __init__(self, model: str = "gemma3:27b", top_targets: int = 10):
        self.model = model
        self.top_targets = top_targets
    
    def run(self, analysis_results: Dict, md_context: str = "", 
            output_dir: str = "") -> Dict:
        """
        Run the full Drug Repositioning pipeline.
        
        Args:
            analysis_results: Results from PTMNonPTMNetworkAnalyzer.analyze()
                Contains: networks, timepoints, summary, legends, etc.
            md_context: Original MD content for context
            output_dir: Output directory for files
        
        Returns:
            Dict with success, report_sections, candidates, etc.
        """
        sse_log("=" * 60, "INFO")
        sse_log("[DR] Starting Drug Repositioning Pipeline v3.2", "INFO")
        sse_log("=" * 60, "INFO")
        
        try:
            # Use platform's LLM client
            call_llm = None
            try:
                from common.llm_client import LLMClient
                _llm = LLMClient()

                def call_llm(prompt, **kwargs):
                    return _llm.generate(prompt)
            except Exception:
                sse_log("Warning: Could not init LLMClient, LLM features disabled", "WARNING")
            
            # v3.2: Detect PTM type from data + md_content
            detected_ptm_type = detect_ptm_type_from_data(analysis_results, md_context)
            ptm_config = get_ptm_config(detected_ptm_type)
            sse_log(f"[DR] Detected PTM type: {detected_ptm_type} ({ptm_config['description']})", "INFO")
            
            # Step 1: PTM Scoring
            scorer = PTMScorer(analysis_results, md_context)
            ptm_scores = scorer.score_all_ptms()
            
            if not ptm_scores:
                sse_log("[DR] No PTM targets found for scoring", "WARNING")
                return {
                    'success': False,
                    'error': 'No PTM targets found',
                    'report_sections': '',
                    'candidates': [],
                }
            
            # Step 2: Upstream Inference (v3.1: PTM-type-aware)
            inferrer = UpstreamInferrer(analysis_results, detected_ptm_type)
            upstream_map = inferrer.infer_upstream(ptm_scores)
            
            # Step 3: Target Selection (v3.1: PTM-type-aware)
            selector = TargetSelector(ptm_scores, upstream_map, self.top_targets, detected_ptm_type)
            targets = selector.select_targets()
            
            if not targets:
                sse_log("[DR] No targets selected", "WARNING")
                return {
                    'success': False,
                    'error': 'No targets selected',
                    'report_sections': '',
                    'candidates': [],
                }
            
            # Step 4: Drug Search
            searcher = DrugSearcher()
            drugs = searcher.search_drugs(targets)
            
            # Step 5: Clinical Trials
            trial_searcher = ClinicalTrialSearcher()
            trials = trial_searcher.search_trials(targets, drugs)
            
            # Step 6: Build Repositioning Candidates (v3.1: correct PTM type)
            candidates = []
            for target in targets:
                gene = target['gene']
                gene_drugs = drugs.get(gene, [])
                gene_trials = trials.get(gene, [])
                
                regulators = target.get('all_upstream_regulators', [])
                regulator_str = ', '.join(str(r) for r in regulators[:3]) if regulators else ''
                pathways = target.get('signaling_pathways', [])
                pathway_str = ', '.join(
                    p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in pathways[:3]
                ) if pathways else ''
                
                # v3.1: Use the actual PTM type from the target, not hardcoded
                actual_ptm_type = target.get('ptm_type', detected_ptm_type)
                
                if gene_drugs:
                    for drug in gene_drugs[:3]:
                        candidates.append(RepositioningCandidate(
                            target_gene=gene,
                            target_site=target.get('site', ''),
                            ptm_type=actual_ptm_type,
                            ptm_score=target.get('composite_score', 0),
                            upstream_regulator=regulator_str,
                            signaling_pathway=pathway_str,
                            drug=drug,
                            clinical_trials=gene_trials,
                        ))
                else:
                    candidates.append(RepositioningCandidate(
                        target_gene=gene,
                        target_site=target.get('site', ''),
                        ptm_type=actual_ptm_type,
                        ptm_score=target.get('composite_score', 0),
                        upstream_regulator=regulator_str,
                        signaling_pathway=pathway_str,
                        drug=DrugCandidate(
                            drug_name='No drug found',
                            drug_id='N/A',
                            source='N/A',
                            target_gene=gene,
                        ),
                        clinical_trials=gene_trials,
                    ))
            
            # Step 7: LLM Evaluation (v3.1: PTM-type-aware)
            evaluatable = [c for c in candidates if c.drug.drug_name != 'No drug found']
            if call_llm and evaluatable:
                evaluator = RepositioningEvaluator(call_llm, self.model, detected_ptm_type)
                evaluator.evaluate_candidates(evaluatable[:10], md_context)
            
            # Step 8: Generate Report Sections (v3.1: PTM-type-aware)
            report_gen = ReportGenerator(call_llm, self.model, detected_ptm_type)
            report_sections = report_gen.generate_sections(
                targets, drugs, trials, candidates, ptm_scores, upstream_map
            )
            
            # Generate LLM summary
            if call_llm and evaluatable:
                llm_summary = report_gen.generate_llm_summary(evaluatable[:5], md_context)
                if llm_summary:
                    report_sections += f"\n\n## Overall Assessment\n\n{llm_summary}\n"
            
            # Save results to JSON
            if output_dir:
                try:
                    dr_results_file = os.path.join(output_dir, "drug_repositioning_results.json")
                    dr_data = {
                        'pipeline_version': '3.2',
                        'ptm_type': detected_ptm_type,
                        'timestamp': datetime.now().isoformat(),
                        'targets': targets,
                        'candidates': [c.to_dict() for c in candidates],
                        'ptm_scores': [s.to_dict() for s in ptm_scores[:self.top_targets]],
                    }
                    with open(dr_results_file, 'w', encoding='utf-8') as f:
                        json.dump(dr_data, f, indent=2)
                    sse_log(f"[DR] Results saved to {dr_results_file}", "INFO")
                except Exception as e:
                    sse_log(f"[DR] Failed to save results JSON: {e}", "WARNING")
            
            sse_log(f"[DR-100%] Drug Repositioning Pipeline v3.2 complete. {len(candidates)} candidates. PTM type: {detected_ptm_type}", "SUCCESS")
            
            return {
                'success': True,
                'report_sections': report_sections,
                'candidates': [c.to_dict() for c in candidates],
                'targets': targets,
                'ptm_scores': [s.to_dict() for s in ptm_scores[:self.top_targets]],
                'ptm_type': detected_ptm_type,
            }
            
        except Exception as e:
            import traceback
            error_msg = f"Drug Repositioning Pipeline failed: {str(e)}"
            sse_log(error_msg, "ERROR")
            sse_log(f"Traceback: {traceback.format_exc()[:1000]}", "DEBUG")
            return {
                'success': False,
                'error': error_msg,
                'report_sections': '',
                'candidates': [],
            }


# ============================================================================
# Standalone execution (for testing via api_wrapper.py)
# ============================================================================

if __name__ == "__main__":
    """
    Standalone execution for testing.
    Reads analysis results JSON from stdin or file argument.
    """
    import sys
    
    if len(sys.argv) > 1:
        results_file = sys.argv[1]
        with open(results_file, 'r') as f:
            results = json.load(f)
        
        md_context = ""
        if len(sys.argv) > 2:
            with open(sys.argv[2], 'r') as f:
                md_context = f.read()
        
        output_dir = os.path.dirname(results_file)
        
        pipeline = DrugRepositioningPipeline(model="gemma3:27b", top_targets=10)
        result = pipeline.run(results, md_context, output_dir)
        
        print(json.dumps({
            "type": "result",
            "success": result['success'],
            "candidates_count": len(result.get('candidates', [])),
            "ptm_type": result.get('ptm_type', 'unknown'),
        }))
    else:
        print("Usage: python drug_repositioning_pipeline.py <results.json> [md_context.md]")
