"""
E3 Ligase Module — v9.14

Module 2 of the Ubiquitylation Analysis Suite.

Builds E3 Ligase-centric substrate modules analogous to the Kinase Module
in phosphorylation mode. For each identified E3 Ligase, groups its substrates,
classifies the E3 family (RING/HECT/RBR), identifies degron motifs, infers
E2 conjugating enzyme partners, and builds a temporal E3 activity cascade.

Key differences from Kinase Module:
  - E3 Ligase family classification: RING / HECT / RBR / APC-RING / CRL-RING
  - Degron motif analysis: phosphodegron, D-box, KEN-box, PY-motif, VHL-degron, etc.
  - E2 conjugating enzyme inference: each E3 family has preferred E2 partners
  - Chain type preference per E3 (from ubiquitin_chain_classifier.py)
  - DUB counterpart identification

Output structure (analogous to kinase_modules in phosphorylation):
  {
    "e3_modules": [
      {
        "e3_ligase": "MDM2",
        "canonical": "MDM2",
        "family": "RING",
        "subfamily": "single-subunit RING",
        "preferred_chain_types": ["K48"],
        "functional_category": "degradation",
        "e2_partners": ["UBE2D1", "UBE2D2", "UBE2D3"],
        "degron_motifs": ["MDM2_box"],
        "confirmed_substrates": [...],
        "inferred_substrates": [...],
        "confirmed_count": N,
        "inferred_count": N,
        "total_count": N,
        "sources": ["literature", "llm_prediction"],
        "source_count": 2,
        "dub_counterparts": ["USP7", "USP10"],
      }
    ],
    "temporal_e3_cascade": {...},
    "degron_analysis": {...},
    "summary": {...},
    "llm_context": str,
  }
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── E3 Ligase Family Database ─────────────────────────────────────────────────
E3_FAMILY_DB: Dict[str, Dict] = {
    # ── RING E3s ──────────────────────────────────────────────────────────
    # Single-subunit RING
    "MDM2":    {"family": "RING", "subfamily": "single-subunit", "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2", "UBE2D3", "UBE2L3"],
                "dub_counterparts": ["USP7", "USP10", "USP2"],
                "substrates_known": ["TP53", "PTEN", "RB1"],
                "functional_category": "degradation",
                "description": "Primary p53 E3 ligase; targets p53 for proteasomal degradation"},
    "CHIP":    {"family": "RING", "subfamily": "U-box",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2", "UBE2D3"],
                "dub_counterparts": ["USP19"],
                "substrates_known": ["HSP70", "HSP90", "misfolded proteins"],
                "functional_category": "degradation",
                "description": "Chaperone-associated E3; protein quality control"},
    "RNF4":    {"family": "RING", "subfamily": "tandem RING",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2"],
                "dub_counterparts": [],
                "substrates_known": ["PML", "SUMO-modified proteins"],
                "functional_category": "degradation",
                "description": "SUMO-targeted ubiquitin ligase (STUbL)"},
    "RNF8":    {"family": "RING", "subfamily": "single-subunit",
                "preferred_chain": ["K48", "K63"],
                "e2_partners": ["UBE2N", "UBE2V2"],
                "dub_counterparts": ["USP3", "OTUB1"],
                "substrates_known": ["H1", "H2A", "MDC1"],
                "functional_category": "dna_repair",
                "description": "DNA damage response E3; H1/H2A ubiquitylation at DSBs"},
    "RNF168":  {"family": "RING", "subfamily": "single-subunit",
                "preferred_chain": ["K63"],
                "e2_partners": ["UBE2N", "UBE2V1"],
                "dub_counterparts": ["USP3", "OTUB2", "BRCC3"],
                "substrates_known": ["H2A-K13", "H2A-K15"],
                "functional_category": "dna_repair",
                "description": "Amplifies DSB ubiquitylation signal; H2A-K13/K15 K63 ubiquitylation"},
    "BRCA1":   {"family": "RING", "subfamily": "heterodimeric RING (BRCA1/BARD1)",
                "preferred_chain": ["K6", "K63"],
                "e2_partners": ["UBE2K", "UBE2E1"],
                "dub_counterparts": ["BAP1"],
                "substrates_known": ["H2A", "CtIP", "PALB2"],
                "functional_category": "dna_repair",
                "description": "Tumor suppressor E3; DNA repair and replication fork protection"},
    "TRAF2":   {"family": "RING", "subfamily": "TRAF-RING",
                "preferred_chain": ["K63"],
                "e2_partners": ["UBE2N", "UBE2V1"],
                "dub_counterparts": ["CYLD", "A20"],
                "substrates_known": ["RIPK1", "NIK"],
                "functional_category": "signaling",
                "description": "TNF receptor signaling; K63 ubiquitylation activates NF-κB"},
    "TRAF6":   {"family": "RING", "subfamily": "TRAF-RING",
                "preferred_chain": ["K63"],
                "e2_partners": ["UBE2N", "UBE2V1"],
                "dub_counterparts": ["CYLD", "A20", "USP25"],
                "substrates_known": ["IRAK1", "AKT", "BECN1"],
                "functional_category": "signaling",
                "description": "IL-1R/TLR signaling; K63 ubiquitylation activates NF-κB and autophagy"},
    "BIRC2":   {"family": "RING", "subfamily": "IAP-RING",
                "preferred_chain": ["K63"],
                "e2_partners": ["UBE2L3", "UBE2D1"],
                "dub_counterparts": [],
                "substrates_known": ["RIPK1", "RIPK3"],
                "functional_category": "signaling",
                "description": "cIAP1; TNF signaling and apoptosis regulation"},
    # CRL (Cullin-RING Ligase) complexes
    "FBXW7":   {"family": "RING", "subfamily": "SCF/CRL1",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2", "UBE2D3", "UBE2G1"],
                "dub_counterparts": ["USP28"],
                "substrates_known": ["CCNE1", "MYC", "NOTCH1", "JUN", "MCL1"],
                "functional_category": "degradation",
                "description": "SCF-FBXW7; targets phosphorylated substrates (phosphodegron)"},
    "BTRC":    {"family": "RING", "subfamily": "SCF/CRL1",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2", "UBE2D3"],
                "dub_counterparts": [],
                "substrates_known": ["CTNNB1", "NFKBIA", "CDC25A", "REST"],
                "functional_category": "degradation",
                "description": "β-TrCP; Wnt/β-catenin and NF-κB pathway regulation"},
    "SKP2":    {"family": "RING", "subfamily": "SCF/CRL1",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2"],
                "dub_counterparts": ["USP28"],
                "substrates_known": ["CDKN1B", "CDKN1A", "MYC", "RB1"],
                "functional_category": "degradation",
                "description": "SCF-SKP2; targets CDK inhibitors for cell cycle progression"},
    "VHL":     {"family": "RING", "subfamily": "CRL2",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2", "UBE2D3"],
                "dub_counterparts": [],
                "substrates_known": ["HIF1A", "HIF2A"],
                "functional_category": "degradation",
                "description": "Oxygen-sensing E3; HIF-α degradation under normoxia"},
    "KEAP1":   {"family": "RING", "subfamily": "CRL3",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2"],
                "dub_counterparts": [],
                "substrates_known": ["NFE2L2", "PGAM5"],
                "functional_category": "degradation",
                "description": "Oxidative stress sensor; NRF2 degradation under basal conditions"},
    "SPOP":    {"family": "RING", "subfamily": "CRL3",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2"],
                "dub_counterparts": [],
                "substrates_known": ["AR", "BRD4", "DAXX", "DEK"],
                "functional_category": "degradation",
                "description": "Prostate cancer-associated E3; AR and BRD4 degradation"},
    # APC/C
    "APC/C":   {"family": "RING", "subfamily": "APC/C multi-subunit",
                "preferred_chain": ["K11", "K48"],
                "e2_partners": ["UBE2C", "UBE2S"],
                "dub_counterparts": ["USP44"],
                "substrates_known": ["CCNB1", "CCNA2", "CDC20", "SECURIN", "PLK1"],
                "functional_category": "cell_cycle",
                "description": "Anaphase-promoting complex; mitotic exit and G1 maintenance"},
    # TRIM family
    "TRIM25":  {"family": "RING", "subfamily": "TRIM/RBCC",
                "preferred_chain": ["K48", "K63"],
                "e2_partners": ["UBE2D1", "UBE2N"],
                "dub_counterparts": ["USP15"],
                "substrates_known": ["MAVS", "RIG-I"],
                "functional_category": "signaling",
                "description": "Innate immunity; RIG-I K63 ubiquitylation activates antiviral signaling"},
    "TRIM21":  {"family": "RING", "subfamily": "TRIM/RBCC",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2"],
                "dub_counterparts": [],
                "substrates_known": ["IRF3", "IRF7", "antibody-coated pathogens"],
                "functional_category": "immune",
                "description": "Intracellular antibody receptor; innate immune defense"},
    # ── HECT E3s ──────────────────────────────────────────────────────────
    "NEDD4":   {"family": "HECT", "subfamily": "NEDD4/NEDD4L",
                "preferred_chain": ["K63", "Mono"],
                "e2_partners": ["UBE2D1", "UBE2L3"],
                "dub_counterparts": ["USP8"],
                "substrates_known": ["PTEN", "SMAD2", "EGFR"],
                "functional_category": "trafficking",
                "description": "Receptor trafficking and endosomal sorting; PY-motif recognition"},
    "NEDD4L":  {"family": "HECT", "subfamily": "NEDD4/NEDD4L",
                "preferred_chain": ["K63", "Mono"],
                "e2_partners": ["UBE2D1", "UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["SMAD2", "SMAD3", "TGF-βR", "ENaC"],
                "functional_category": "trafficking",
                "description": "TGF-β receptor trafficking; sodium channel regulation"},
    "ITCH":    {"family": "HECT", "subfamily": "NEDD4/NEDD4L",
                "preferred_chain": ["K29", "K63"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["NOTCH1", "JUNB", "p63"],
                "functional_category": "signaling",
                "description": "Wnt/Notch signaling regulation; T cell activation"},
    "HUWE1":   {"family": "HECT", "subfamily": "HUWE1",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": ["USP7"],
                "substrates_known": ["MYC", "MCL1", "TP53"],
                "functional_category": "degradation",
                "description": "Large HECT E3; MYC and MCL1 degradation"},
    "UBR5":    {"family": "HECT", "subfamily": "UBR5",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["ATMIN", "DYRK2"],
                "functional_category": "degradation",
                "description": "DNA damage response; replication stress"},
    "HERC2":   {"family": "HECT", "subfamily": "HERC",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["XPA", "BRCA1"],
                "functional_category": "dna_repair",
                "description": "DNA repair regulation; nucleotide excision repair"},
    "WWP1":    {"family": "HECT", "subfamily": "NEDD4/NEDD4L",
                "preferred_chain": ["K63"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["PTEN", "KLF2"],
                "functional_category": "signaling",
                "description": "PTEN K63 ubiquitylation; PI3K/AKT pathway regulation"},
    "SMURF1":  {"family": "HECT", "subfamily": "NEDD4/NEDD4L",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["SMAD1", "SMAD5", "RHOA"],
                "functional_category": "degradation",
                "description": "BMP/TGF-β pathway; SMAD1/5 degradation"},
    "SMURF2":  {"family": "HECT", "subfamily": "NEDD4/NEDD4L",
                "preferred_chain": ["K48"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": [],
                "substrates_known": ["SMAD2", "SMAD3", "TGF-βR"],
                "functional_category": "degradation",
                "description": "TGF-β pathway; SMAD2/3 and receptor degradation"},
    # ── RBR E3s ───────────────────────────────────────────────────────────
    "PARKIN":  {"family": "RBR", "subfamily": "PARKIN/ARIH",
                "preferred_chain": ["K6", "K48", "K63"],
                "e2_partners": ["UBE2L3", "UBE2D1"],
                "dub_counterparts": ["USP8", "USP15"],
                "substrates_known": ["VDAC1", "MFNS2", "MFN1", "TOMM20"],
                "functional_category": "autophagy",
                "description": "Mitophagy E3; PINK1-activated; Parkinson's disease"},
    "HOIP":    {"family": "RBR", "subfamily": "LUBAC",
                "preferred_chain": ["M1"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": ["OTULIN", "CYLD"],
                "substrates_known": ["NEMO", "RIPK1", "RIPK2"],
                "functional_category": "immune",
                "description": "LUBAC catalytic subunit; linear (M1) ubiquitin chain synthesis"},
    "RNF31":   {"family": "RBR", "subfamily": "LUBAC",
                "preferred_chain": ["M1"],
                "e2_partners": ["UBE2L3"],
                "dub_counterparts": ["OTULIN"],
                "substrates_known": ["NEMO", "RIPK1"],
                "functional_category": "immune",
                "description": "HOIP; LUBAC component; NF-κB activation"},
    # Histone E3s
    "RNF2":    {"family": "RING", "subfamily": "PRC1-RING",
                "preferred_chain": ["Mono"],
                "e2_partners": ["UBE2D1"],
                "dub_counterparts": ["BAP1", "USP16"],
                "substrates_known": ["H2A-K119"],
                "functional_category": "transcription",
                "description": "PRC1 catalytic subunit; H2A-K119 monoubiquitylation; gene silencing"},
    "RNF20":   {"family": "RING", "subfamily": "single-subunit",
                "preferred_chain": ["Mono"],
                "e2_partners": ["UBE2A", "UBE2B"],
                "dub_counterparts": ["USP22"],
                "substrates_known": ["H2B-K120"],
                "functional_category": "transcription",
                "description": "H2B-K120 monoubiquitylation; transcription elongation"},
    "RNF40":   {"family": "RING", "subfamily": "single-subunit",
                "preferred_chain": ["Mono"],
                "e2_partners": ["UBE2A", "UBE2B"],
                "dub_counterparts": ["USP22"],
                "substrates_known": ["H2B-K120"],
                "functional_category": "transcription",
                "description": "RNF20/RNF40 heterodimer; H2B-K120 monoubiquitylation"},
}

# ── Degron Motif Database ─────────────────────────────────────────────────────
DEGRON_DB: Dict[str, Dict] = {
    "phosphodegron_FBXW7": {
        "pattern": r"[ST]P.{0,3}[ST]",
        "e3_ligase": "FBXW7",
        "description": "Phospho-degron recognized by SCF-FBXW7 (requires dual phosphorylation)",
        "chain_type": "K48",
        "examples": ["CCNE1-T380/T384", "MYC-T58/S62", "NOTCH1-T2512/S2516"],
    },
    "phosphodegron_BTRC": {
        "pattern": r"DS[GA].{1,3}S",
        "e3_ligase": "BTRC",
        "description": "DSGxxS phospho-degron for β-TrCP/BTRC recognition",
        "chain_type": "K48",
        "examples": ["CTNNB1-S33/S37/T41/S45", "NFKBIA-S32/S36"],
    },
    "D-box": {
        "pattern": r"R..L.{2,4}[ILVM]",
        "e3_ligase": "APC/C-CDC20",
        "description": "Destruction box (D-box) for APC/C-CDC20 recognition",
        "chain_type": "K11/K48",
        "examples": ["CCNB1-R42xxL", "CDC20-R70xxL"],
    },
    "KEN-box": {
        "pattern": r"KEN",
        "e3_ligase": "APC/C-CDH1",
        "description": "KEN-box for APC/C-CDH1 recognition",
        "chain_type": "K11/K48",
        "examples": ["CDC20-K51EN", "BUBR1-K152EN"],
    },
    "PY-motif": {
        "pattern": r"[LP]P.Y",
        "e3_ligase": "NEDD4/ITCH/WWP",
        "description": "PY-motif (PPxY) for HECT E3 WW domain recognition",
        "chain_type": "K63/Mono",
        "examples": ["SMAD2-PPSY", "NEDD4 substrates"],
    },
    "VHL_oxygen_degron": {
        "pattern": r"LA.{1,2}[ILVM]P",
        "e3_ligase": "VHL",
        "description": "Hydroxylated proline degron for VHL recognition (HIF-α)",
        "chain_type": "K48",
        "examples": ["HIF1A-P402/P564", "HIF2A-P405/P531"],
    },
    "MDM2_box": {
        "pattern": r"F..W..L",
        "e3_ligase": "MDM2",
        "description": "MDM2-binding motif on TP53 transactivation domain",
        "chain_type": "K48",
        "examples": ["TP53-F19/W23/L26"],
    },
    "KEAP1_ETGE": {
        "pattern": r"ETGE",
        "e3_ligase": "KEAP1",
        "description": "High-affinity ETGE degron for KEAP1/CRL3 recognition (NRF2)",
        "chain_type": "K48",
        "examples": ["NFE2L2-E79TGE82"],
    },
    "KEAP1_DLG": {
        "pattern": r"DLG",
        "e3_ligase": "KEAP1",
        "description": "Low-affinity DLG degron for KEAP1 recognition",
        "chain_type": "K48",
        "examples": ["NFE2L2-D29LG31"],
    },
    "SPOP_SBC": {
        "pattern": r"[ST][ST][ST].{1,3}[ST][ST]",
        "e3_ligase": "SPOP",
        "description": "SPOP-binding consensus (SBC) motif",
        "chain_type": "K48",
        "examples": ["AR-S213/S217", "BRD4-S492/S496"],
    },
    "CRL4_PIP_box": {
        "pattern": r"Q..[ILVM].{2}[FY][FY]",
        "e3_ligase": "CRL4-CDT2",
        "description": "PIP-box for CRL4-CDT2 recognition (PCNA-dependent)",
        "chain_type": "K48",
        "examples": ["CDT1-Q1", "p21-Q144"],
    },
    "IAP_BIR_binding": {
        "pattern": r"[AVTS][VILF][PILV][DEAS]",
        "e3_ligase": "BIRC2/BIRC3",
        "description": "IAP-binding motif (IBM) for cIAP1/2 recognition",
        "chain_type": "K63",
        "examples": ["SMAC/DIABLO-AVPI"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def build_e3_ligase_modules(
    enriched_data: List[dict],
    chain_classifications: Dict[str, dict],
    clusters: List[dict],
    ptm_type: str = "ubiquitylation",
) -> dict:
    """
    Build E3 Ligase-centric substrate modules from enriched_ptm_data.

    Args:
        enriched_data: Full enriched_ptm_data from state
        chain_classifications: Output of classify_ubiquitin_chain_types()
        clusters: Co-wave cluster list (for temporal cascade)
        ptm_type: Should be 'ubiquitylation'

    Returns:
        Dict with e3_modules, temporal_e3_cascade, degron_analysis, summary, llm_context
    """
    if ptm_type != "ubiquitylation":
        return {"e3_modules": [], "summary": {}, "llm_context": ""}

    # ── Step A: Collect E3 ligase → substrate relationships ──────────────
    e3_members: Dict[str, dict] = {}  # canonical_e3 → module data

    for entry in enriched_data:
        gene = (entry.get("gene") or entry.get("Gene.Name", "")).strip().upper()
        pos = str(entry.get("position") or entry.get("PTM_Position", "")).strip()
        if not gene or not pos:
            continue

        ptm_key = f"{gene}_{pos}"
        rag = entry.get("rag_enrichment", {}) or {}
        regulation = rag.get("regulation", {}) or {}
        kp = rag.get("kinase_prediction", {}) or {}

        # Source 1: Literature E3-substrate pairs
        for e3s in regulation.get("e3_substrate", []):
            e3_name = (e3s.get("e3_ligase") or "").strip()
            if not e3_name or len(e3_name) < 2:
                continue
            canon = _normalize_e3_name(e3_name)
            _add_substrate_to_module(
                e3_members, canon, e3_name, ptm_key, gene, pos,
                "confirmed", "literature", chain_classifications
            )

        # Source 2: LLM-predicted E3 ligases
        if isinstance(kp, dict):
            for pk in kp.get("predictedKinases", kp.get("predicted_kinases", [])):
                if isinstance(pk, dict):
                    e3_name = (pk.get("kinase") or "").strip()
                    if not e3_name or len(e3_name) < 2:
                        continue
                    # Only include if it looks like an E3 ligase
                    if _is_e3_ligase_name(e3_name):
                        canon = _normalize_e3_name(e3_name)
                        _add_substrate_to_module(
                            e3_members, canon, e3_name, ptm_key, gene, pos,
                            "inferred", "llm_prediction", chain_classifications
                        )

        # Source 3: Upstream regulators that are known E3 ligases
        for reg in regulation.get("upstream_regulators", []):
            reg_name = (reg if isinstance(reg, str) else reg.get("name", "")).strip()
            if not reg_name or len(reg_name) < 2:
                continue
            if _is_e3_ligase_name(reg_name):
                canon = _normalize_e3_name(reg_name)
                _add_substrate_to_module(
                    e3_members, canon, reg_name, ptm_key, gene, pos,
                    "inferred", "upstream_regulator", chain_classifications
                )

        # Source 4: Chain classification → infer E3 ligase
        cls = chain_classifications.get(ptm_key, {})
        for e3_name in cls.get("e3_ligases", []):
            if not e3_name or len(e3_name) < 2:
                continue
            canon = _normalize_e3_name(e3_name)
            _add_substrate_to_module(
                e3_members, canon, e3_name, ptm_key, gene, pos,
                "inferred", "chain_type_inference", chain_classifications
            )

    # ── Step B: Degron motif analysis ────────────────────────────────────
    degron_hits = _analyze_degron_motifs(enriched_data)

    # Add degron-inferred E3 ligases
    for ptm_key, degrons in degron_hits.items():
        parts = ptm_key.split("_", 1)
        if len(parts) != 2:
            continue
        gene, pos = parts[0], parts[1]

        for degron in degrons:
            e3_name = degron.get("e3_ligase", "")
            if not e3_name:
                continue
            # Handle compound names like "NEDD4/ITCH/WWP"
            for e3_part in e3_name.split("/"):
                e3_part = e3_part.strip()
                if not e3_part or len(e3_part) < 2:
                    continue
                canon = _normalize_e3_name(e3_part)
                _add_substrate_to_module(
                    e3_members, canon, e3_part, ptm_key, gene, pos,
                    "inferred", f"degron_{degron['motif_name'].lower()}", chain_classifications
                )

    # ── Step C: Enrich modules with family info ───────────────────────────
    e3_module_list = []
    for canon, info in e3_members.items():
        db_info = _get_e3_db_info(canon)
        members = info["confirmed"] + info["inferred"]

        module = {
            "e3_ligase": info["display_name"],
            "canonical": canon,
            "family": db_info.get("family", "unknown"),
            "subfamily": db_info.get("subfamily", "unknown"),
            "preferred_chain_types": db_info.get("preferred_chain", []),
            "functional_category": db_info.get("functional_category", "unknown"),
            "e2_partners": db_info.get("e2_partners", []),
            "dub_counterparts": db_info.get("dub_counterparts", []),
            "description": db_info.get("description", ""),
            "sources": sorted(info["sources"]),
            "source_count": len(info["sources"]),
            "confirmed_substrates": info["confirmed"],
            "inferred_substrates": info["inferred"],
            "confirmed_count": len(info["confirmed"]),
            "inferred_count": len(info["inferred"]),
            "total_count": len(members),
        }
        e3_module_list.append(module)

    e3_module_list.sort(key=lambda x: x["total_count"], reverse=True)

    # ── Step D: Temporal E3 cascade ───────────────────────────────────────
    temporal_e3_cascade = _build_temporal_e3_cascade(e3_module_list, clusters)

    # ── Step E: Summary ───────────────────────────────────────────────────
    family_counts: Dict[str, int] = {}
    for mod in e3_module_list:
        fam = mod["family"]
        family_counts[fam] = family_counts.get(fam, 0) + 1

    cat_counts: Dict[str, int] = {}
    for mod in e3_module_list:
        cat = mod["functional_category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    summary = {
        "total_e3_modules": len(e3_module_list),
        "total_confirmed": sum(m["confirmed_count"] for m in e3_module_list),
        "total_inferred": sum(m["inferred_count"] for m in e3_module_list),
        "by_family": family_counts,
        "by_functional_category": cat_counts,
        "top_e3_ligases": [
            {"e3": m["e3_ligase"], "canonical": m["canonical"],
             "family": m["family"], "total": m["total_count"]}
            for m in e3_module_list[:10]
        ],
        "total_degron_hits": sum(len(v) for v in degron_hits.values()),
    }

    llm_context = _build_e3_llm_context(e3_module_list, temporal_e3_cascade, degron_hits, summary)

    return {
        "e3_modules": e3_module_list,
        "temporal_e3_cascade": temporal_e3_cascade,
        "degron_analysis": {
            "hits_by_ptm": degron_hits,
            "total_hits": summary["total_degron_hits"],
        },
        "summary": summary,
        "llm_context": llm_context,
    }


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_e3_name(name: str) -> str:
    """Normalize E3 ligase name to canonical form."""
    name = name.strip().upper()
    aliases = {
        "BETA-TRCP": "BTRC", "BETA_TRCP": "BTRC", "BTRCP": "BTRC",
        "FBXW1": "BTRC", "FBXW11": "FBXW11",
        "CBLB": "CBL", "CBL-B": "CBL",
        "CIAP1": "BIRC2", "CIAP2": "BIRC3", "XIAP": "BIRC4",
        "MDM2": "MDM2", "HDM2": "MDM2",
        "PARKIN": "PARKIN", "PARK2": "PARKIN",
        "HOIP": "RNF31", "HOIL-1L": "RBCK1",
        "RING1B": "RNF2", "BMI1": "PCGF4",
    }
    return aliases.get(name, name)


def _is_e3_ligase_name(name: str) -> bool:
    """Check if a name looks like an E3 ligase."""
    name_upper = name.upper()
    # Check against known E3 DB
    if _normalize_e3_name(name_upper) in E3_FAMILY_DB:
        return True
    # Pattern-based heuristics
    e3_patterns = [
        r"^RNF\d+",   # RNF family
        r"^TRIM\d+",  # TRIM family
        r"^FBXW?\d*", # F-box proteins
        r"^HERC\d+",  # HERC family
        r"^BIRC\d+",  # IAP family
        r"^TRAF\d+",  # TRAF family
        r"^WWP\d+",   # WWP family
        r"^SMURF\d+", # SMURF family
        r"LIGASE",    # contains "ligase"
        r"E3.*UBIQ",  # E3 ubiquitin
    ]
    for pat in e3_patterns:
        if re.search(pat, name_upper):
            return True
    return False


def _get_e3_db_info(canon: str) -> dict:
    """Get E3 family info from database."""
    # Direct lookup
    if canon in E3_FAMILY_DB:
        return E3_FAMILY_DB[canon]
    # Partial match
    for key, info in E3_FAMILY_DB.items():
        if key in canon or canon in key:
            return info
    # Family-based inference
    if canon.startswith("RNF"):
        return {"family": "RING", "subfamily": "single-subunit", "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1"], "dub_counterparts": [], "functional_category": "unknown",
                "description": f"RING finger protein {canon}"}
    if canon.startswith("TRIM"):
        return {"family": "RING", "subfamily": "TRIM/RBCC", "preferred_chain": ["K48", "K63"],
                "e2_partners": ["UBE2D1"], "dub_counterparts": [], "functional_category": "signaling",
                "description": f"TRIM family E3 ligase {canon}"}
    if canon.startswith("HERC"):
        return {"family": "HECT", "subfamily": "HERC", "preferred_chain": ["K48"],
                "e2_partners": ["UBE2L3"], "dub_counterparts": [], "functional_category": "degradation",
                "description": f"HERC family HECT E3 ligase {canon}"}
    if canon.startswith("FBXW") or canon.startswith("FBXL") or canon.startswith("FBXO"):
        return {"family": "RING", "subfamily": "SCF/CRL1", "preferred_chain": ["K48"],
                "e2_partners": ["UBE2D1", "UBE2D2"], "dub_counterparts": [], "functional_category": "degradation",
                "description": f"SCF complex F-box protein {canon}"}
    return {"family": "unknown", "subfamily": "unknown", "preferred_chain": [],
            "e2_partners": [], "dub_counterparts": [], "functional_category": "unknown",
            "description": f"E3 ligase {canon} (family unknown)"}


def _add_substrate_to_module(
    e3_members: dict,
    canon: str,
    display_name: str,
    ptm_key: str,
    gene: str,
    pos: str,
    membership: str,
    evidence: str,
    chain_classifications: dict,
) -> None:
    """Add a substrate to an E3 module."""
    if not canon or len(canon) < 2:
        return

    if canon not in e3_members:
        e3_members[canon] = {
            "display_name": display_name,
            "sources": set(),
            "confirmed": [],
            "inferred": [],
        }

    e3_members[canon]["sources"].add(evidence)

    # Get chain type from classification
    cls = chain_classifications.get(ptm_key, {})
    chain_types = cls.get("inferred_chain_types", [])

    substrate_entry = {
        "key": ptm_key,
        "gene": gene,
        "position": pos,
        "membership": membership,
        "evidence": evidence,
        "chain_types": chain_types,
    }

    target_list = e3_members[canon]["confirmed"] if membership == "confirmed" else e3_members[canon]["inferred"]
    if ptm_key not in [m["key"] for m in target_list]:
        target_list.append(substrate_entry)


def _analyze_degron_motifs(enriched_data: List[dict]) -> Dict[str, List[dict]]:
    """Scan all PTM sequences for known degron motifs."""
    hits: Dict[str, List[dict]] = {}

    for entry in enriched_data:
        gene = (entry.get("gene") or entry.get("Gene.Name", "")).strip().upper()
        pos = str(entry.get("position") or entry.get("PTM_Position", "")).strip()
        if not gene or not pos:
            continue

        ptm_key = f"{gene}_{pos}"

        # Get sequence context (surrounding amino acids)
        seq_context = (
            entry.get("sequence_context")
            or entry.get("Sequence_Context")
            or entry.get("flanking_sequence")
            or ""
        )
        if not seq_context:
            # Try to get from rag_enrichment
            rag = entry.get("rag_enrichment", {}) or {}
            seq_context = rag.get("sequence_context", "") or ""

        if not seq_context:
            continue

        seq_upper = seq_context.upper()
        site_hits = []

        for motif_name, motif_info in DEGRON_DB.items():
            pattern = motif_info["pattern"]
            if re.search(pattern, seq_upper, re.IGNORECASE):
                site_hits.append({
                    "motif_name": motif_name,
                    "e3_ligase": motif_info["e3_ligase"],
                    "description": motif_info["description"],
                    "chain_type": motif_info["chain_type"],
                    "examples": motif_info.get("examples", []),
                })

        if site_hits:
            hits[ptm_key] = site_hits

    return hits


def _build_temporal_e3_cascade(
    e3_module_list: List[dict],
    clusters: List[dict],
) -> dict:
    """Build temporal E3 activity cascade from cluster peak timepoints."""
    from common.temporal_utils import tp_to_minutes

    cascade = {"timepoints": [], "e3_activity": [], "cascade_flow": []}

    if not clusters:
        return cascade

    tp_e3_map: Dict[str, dict] = {}

    for cluster in clusters:
        peak_tp = cluster.get("peak_timepoint", "")
        if not peak_tp:
            continue

        member_keys = set(
            md.get("key", "") for md in cluster.get("member_details", [])
        )

        if peak_tp not in tp_e3_map:
            tp_e3_map[peak_tp] = {"e3s": {}, "ptm_count": 0}

        tp_e3_map[peak_tp]["ptm_count"] += len(member_keys)

        for mod in e3_module_list:
            mod_keys = set(
                m["key"] for m in mod["confirmed_substrates"] + mod["inferred_substrates"]
            )
            shared = member_keys & mod_keys
            if shared:
                canon = mod["canonical"]
                if canon not in tp_e3_map[peak_tp]["e3s"]:
                    tp_e3_map[peak_tp]["e3s"][canon] = {
                        "e3_ligase": mod["e3_ligase"],
                        "canonical": canon,
                        "family": mod["family"],
                        "functional_category": mod["functional_category"],
                        "preferred_chain_types": mod["preferred_chain_types"],
                        "substrate_count": len(shared),
                    }
                else:
                    tp_e3_map[peak_tp]["e3s"][canon]["substrate_count"] += len(shared)

    sorted_tps = sorted(tp_e3_map.keys(), key=lambda t: tp_to_minutes(t))

    cascade["timepoints"] = [
        {
            "timepoint": tp,
            "minutes": tp_to_minutes(tp),
            "ptm_count": tp_e3_map[tp]["ptm_count"],
            "active_e3s": sorted(
                tp_e3_map[tp]["e3s"].values(),
                key=lambda e: e["substrate_count"],
                reverse=True,
            ),
        }
        for tp in sorted_tps
    ]

    # E3 activity swimlane
    all_e3_tps: Dict[str, dict] = {}
    for tp_data in cascade["timepoints"]:
        for e3 in tp_data["active_e3s"]:
            canon = e3["canonical"]
            if canon not in all_e3_tps:
                all_e3_tps[canon] = {
                    "e3_ligase": e3["e3_ligase"],
                    "canonical": canon,
                    "family": e3["family"],
                    "timepoints": [],
                }
            all_e3_tps[canon]["timepoints"].append({
                "timepoint": tp_data["timepoint"],
                "substrate_count": e3["substrate_count"],
            })

    cascade["e3_activity"] = sorted(
        all_e3_tps.values(),
        key=lambda x: len(x["timepoints"]),
        reverse=True,
    )

    # Cascade flow between adjacent timepoints
    for i in range(len(sorted_tps) - 1):
        tp_a, tp_b = sorted_tps[i], sorted_tps[i + 1]
        e3s_a = set(tp_e3_map[tp_a]["e3s"].keys())
        e3s_b = set(tp_e3_map[tp_b]["e3s"].keys())
        cascade["cascade_flow"].append({
            "from_timepoint": tp_a,
            "to_timepoint": tp_b,
            "persistent_e3s": sorted(e3s_a & e3s_b),
            "newly_active_e3s": sorted(e3s_b - e3s_a),
            "deactivated_e3s": sorted(e3s_a - e3s_b),
        })

    return cascade


def _build_e3_llm_context(
    e3_module_list: List[dict],
    temporal_cascade: dict,
    degron_hits: Dict[str, List[dict]],
    summary: dict,
) -> str:
    """Build LLM context string for E3 ligase module analysis."""
    lines = [
        "═══════════════════════════════════════════════════════════════",
        "E3 LIGASE MODULE ANALYSIS (Module 2 — v9.14)",
        "═══════════════════════════════════════════════════════════════",
        "",
        f"Total E3 Ligase modules identified: {summary['total_e3_modules']}",
        f"  Confirmed substrates: {summary['total_confirmed']}",
        f"  Inferred substrates:  {summary['total_inferred']}",
        f"  Degron motif hits:    {summary['total_degron_hits']}",
        "",
        "── Section A: E3 Family Distribution ───────────────────────",
    ]
    for fam, cnt in sorted(summary.get("by_family", {}).items(), key=lambda x: -x[1]):
        lines.append(f"  {fam:15s}: {cnt} E3 ligases")

    lines += [
        "",
        "── Section B: Functional Category Distribution ──────────────",
    ]
    for cat, cnt in sorted(summary.get("by_functional_category", {}).items(), key=lambda x: -x[1]):
        lines.append(f"  {cat:20s}: {cnt} E3 ligases")

    lines += [
        "",
        "── Section C: Top E3 Ligase Modules ─────────────────────────",
    ]
    for mod in e3_module_list[:12]:
        chain_str = "/".join(mod["preferred_chain_types"]) or "?"
        e2_str = ", ".join(mod["e2_partners"][:3]) if mod["e2_partners"] else "unknown"
        dub_str = ", ".join(mod["dub_counterparts"][:2]) if mod["dub_counterparts"] else "none"
        lines.append(
            f"  {mod['e3_ligase']:15s} [{mod['family']:5s}] "
            f"chain:{chain_str:12s} "
            f"substrates:{mod['total_count']:3d} "
            f"(confirmed:{mod['confirmed_count']}, inferred:{mod['inferred_count']})"
        )
        lines.append(f"    E2: {e2_str} | DUB: {dub_str}")
        if mod["description"]:
            lines.append(f"    → {mod['description'][:100]}")

    lines += [
        "",
        "── Section D: Degron Motif Analysis ─────────────────────────",
    ]
    # Summarize degron hits by motif type
    motif_counts: Dict[str, int] = {}
    for site_hits in degron_hits.values():
        for h in site_hits:
            mn = h["motif_name"]
            motif_counts[mn] = motif_counts.get(mn, 0) + 1

    for motif, cnt in sorted(motif_counts.items(), key=lambda x: -x[1])[:10]:
        db = DEGRON_DB.get(motif, {})
        desc = db.get("description", "")
        e3 = db.get("e3_ligase", "?")
        lines.append(f"  {motif:25s}: {cnt:3d} sites | E3: {e3}")
        if desc:
            lines.append(f"    → {desc[:100]}")

    lines += [
        "",
        "── Section E: Temporal E3 Cascade ───────────────────────────",
    ]
    for tp_data in temporal_cascade.get("timepoints", []):
        tp = tp_data["timepoint"]
        active = tp_data.get("active_e3s", [])
        e3_names = ", ".join(e["e3_ligase"] for e in active[:5])
        lines.append(f"  {tp:8s}: {len(active)} active E3s — {e3_names}")

    for flow in temporal_cascade.get("cascade_flow", []):
        from_tp = flow["from_timepoint"]
        to_tp = flow["to_timepoint"]
        new = flow.get("newly_active_e3s", [])
        lost = flow.get("deactivated_e3s", [])
        if new or lost:
            lines.append(f"  {from_tp} → {to_tp}: +{len(new)} new ({', '.join(new[:3])}), -{len(lost)} lost ({', '.join(lost[:3])})")

    lines += [
        "",
        "── LLM Instructions ─────────────────────────────────────────",
        "Use E3 Ligase Module data to:",
        "1. Identify the dominant E3 ligase families (RING/HECT/RBR) and their functional roles",
        "2. Discuss E3-E2 conjugating enzyme pairs for mechanistic accuracy",
        "3. Highlight phosphodegron-mediated ubiquitylation (cross-talk with phosphorylation)",
        "4. Discuss DUB counterparts and the reversibility of ubiquitylation events",
        "5. Integrate temporal E3 activity with signaling pathway activation/termination",
        "6. Note APC/C-mediated cell cycle regulation if K11/K48 patterns are detected",
        "═══════════════════════════════════════════════════════════════",
    ]

    return "\n".join(lines)
