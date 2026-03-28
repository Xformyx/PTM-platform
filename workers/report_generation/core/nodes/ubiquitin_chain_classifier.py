"""
Ubiquitin Chain Type Classifier — v9.14

Module 1 of the Ubiquitylation Analysis Suite.

Infers the ubiquitin chain type (K48, K63, K11, K6, K27, K29, K33, M1, Mono, Multi-mono)
for each ubiquitylation site and classifies its functional category:
  - degradation       : K48, K11, K29 → proteasomal degradation
  - signaling         : K63, M1, K27  → NF-κB, DNA damage, immune signaling
  - dna_repair        : K6, K63       → DNA damage response
  - trafficking       : Mono, Multi-mono, K63 → endosomal sorting, receptor internalization
  - autophagy         : K63, K27      → selective autophagy (p62/SQSTM1 recruitment)
  - cell_cycle        : K11, K48      → APC/C-mediated mitotic regulation
  - immune            : M1, K63       → NF-κB, LUBAC, innate immunity
  - transcription     : Mono, K4      → histone ubiquitylation, epigenetic regulation
  - unknown           : insufficient evidence

Evidence sources (priority order):
  1. Literature chain type (regulation.chain_types from regulation_extractor)
  2. E3 ligase identity → known chain type preference
  3. Degron motif match → inferred chain type
  4. Protein function context (GO terms, pathways)
  5. LLM prediction (kinase_prediction field)
  6. Residue context fallback

Output per PTM site:
  {
    "gene": "TP53",
    "position": "K370",
    "inferred_chain_types": ["K48"],
    "functional_category": "degradation",
    "functional_subcategory": "proteasomal_degradation",
    "confidence": "high|medium|low",
    "evidence_sources": ["literature", "e3_ligase_mdm2"],
    "dub_candidates": ["USP7", "USP10"],
    "biological_interpretation": "MDM2-mediated K48 polyubiquitylation targets TP53 for proteasomal degradation",
  }
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── E3 Ligase → Chain Type Preference ────────────────────────────────────────
# Based on established biochemistry literature
E3_CHAIN_TYPE_MAP: Dict[str, Dict] = {
    # RING E3s — Degradation (K48)
    "MDM2":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING"},
    "CHIP":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING"},
    "FBXW7":   {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/SCF"},
    "FBXW11":  {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/SCF"},
    "BTRC":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/SCF"},
    "SKP2":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/SCF"},
    "VHL":     {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/CRL"},
    "KEAP1":   {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/CRL"},
    "SPOP":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/CRL"},
    "TRIM32":  {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/TRIM"},
    "TRIM21":  {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING/TRIM"},
    "TRIM25":  {"chain_types": ["K48", "K63"], "functional_category": "signaling", "family": "RING/TRIM"},
    "RNF4":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "RING"},
    "RNF8":    {"chain_types": ["K48", "K63"], "functional_category": "dna_repair", "family": "RING"},
    "RNF168":  {"chain_types": ["K63"], "functional_category": "dna_repair", "family": "RING"},
    "BRCA1":   {"chain_types": ["K6", "K63"], "functional_category": "dna_repair", "family": "RING"},
    "BARD1":   {"chain_types": ["K6", "K63"], "functional_category": "dna_repair", "family": "RING"},
    "BIRC2":   {"chain_types": ["K63"], "functional_category": "signaling", "family": "RING/IAP"},
    "BIRC3":   {"chain_types": ["K63"], "functional_category": "signaling", "family": "RING/IAP"},
    "TRAF2":   {"chain_types": ["K63"], "functional_category": "signaling", "family": "RING/TRAF"},
    "TRAF6":   {"chain_types": ["K63"], "functional_category": "signaling", "family": "RING/TRAF"},
    "TRAF3":   {"chain_types": ["K63"], "functional_category": "signaling", "family": "RING/TRAF"},
    "RIPK1":   {"chain_types": ["K63", "M1"], "functional_category": "signaling", "family": "RING"},
    "HOIP":    {"chain_types": ["M1"], "functional_category": "immune", "family": "RBR/LUBAC"},
    "HOIL1L":  {"chain_types": ["M1"], "functional_category": "immune", "family": "RBR/LUBAC"},
    "SHARPIN": {"chain_types": ["M1"], "functional_category": "immune", "family": "LUBAC"},
    # HECT E3s
    "NEDD4":   {"chain_types": ["K63", "Mono"], "functional_category": "trafficking", "family": "HECT/NEDD4"},
    "NEDD4L":  {"chain_types": ["K63", "Mono"], "functional_category": "trafficking", "family": "HECT/NEDD4"},
    "ITCH":    {"chain_types": ["K29", "K63"], "functional_category": "signaling", "family": "HECT/NEDD4"},
    "WWP1":    {"chain_types": ["K63"], "functional_category": "signaling", "family": "HECT/NEDD4"},
    "WWP2":    {"chain_types": ["K63"], "functional_category": "signaling", "family": "HECT/NEDD4"},
    "SMURF1":  {"chain_types": ["K48"], "functional_category": "degradation", "family": "HECT/NEDD4"},
    "SMURF2":  {"chain_types": ["K48"], "functional_category": "degradation", "family": "HECT/NEDD4"},
    "HUWE1":   {"chain_types": ["K48"], "functional_category": "degradation", "family": "HECT"},
    "UBR5":    {"chain_types": ["K48"], "functional_category": "degradation", "family": "HECT"},
    "HERC2":   {"chain_types": ["K48"], "functional_category": "degradation", "family": "HECT"},
    "TRIP12":  {"chain_types": ["K48"], "functional_category": "degradation", "family": "HECT"},
    # RBR E3s
    "PARKIN":  {"chain_types": ["K6", "K48", "K63"], "functional_category": "autophagy", "family": "RBR"},
    "HHARI":   {"chain_types": ["K48"], "functional_category": "degradation", "family": "RBR"},
    # APC/C
    "APC/C":   {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle", "family": "RING/APC"},
    "CDC20":   {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle", "family": "RING/APC"},
    "CDH1":    {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle", "family": "RING/APC"},
    "FZR1":    {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle", "family": "RING/APC"},
    # Histone E3s
    "RNF2":    {"chain_types": ["Mono"], "functional_category": "transcription", "family": "RING/PRC1"},
    "BMI1":    {"chain_types": ["Mono"], "functional_category": "transcription", "family": "RING/PRC1"},
    "RING1B":  {"chain_types": ["Mono"], "functional_category": "transcription", "family": "RING/PRC1"},
    "RNF20":   {"chain_types": ["Mono"], "functional_category": "transcription", "family": "RING"},
    "RNF40":   {"chain_types": ["Mono"], "functional_category": "transcription", "family": "RING"},
}

# ── Chain Type → Functional Category ─────────────────────────────────────────
CHAIN_FUNCTION_MAP: Dict[str, Dict] = {
    "K48": {
        "functional_category": "degradation",
        "functional_subcategory": "proteasomal_degradation",
        "description": "K48-linked polyubiquitin chain → 26S proteasomal degradation",
        "signaling_role": "Protein turnover, quality control, cell cycle regulation",
    },
    "K63": {
        "functional_category": "signaling",
        "functional_subcategory": "non_degradative_signaling",
        "description": "K63-linked polyubiquitin chain → non-degradative signaling scaffold",
        "signaling_role": "NF-κB activation, DNA damage response, endosomal sorting, kinase activation",
    },
    "K11": {
        "functional_category": "cell_cycle",
        "functional_subcategory": "mitotic_degradation",
        "description": "K11-linked polyubiquitin chain → APC/C-mediated mitotic degradation",
        "signaling_role": "Mitotic exit, ERAD, cell cycle progression",
    },
    "K27": {
        "functional_category": "autophagy",
        "functional_subcategory": "selective_autophagy",
        "description": "K27-linked polyubiquitin chain → selective autophagy signaling",
        "signaling_role": "Mitophagy, DNA damage signaling, innate immunity",
    },
    "K29": {
        "functional_category": "signaling",
        "functional_subcategory": "wnt_lysosomal",
        "description": "K29-linked polyubiquitin chain → Wnt signaling and lysosomal degradation",
        "signaling_role": "Wnt pathway regulation, proteasomal and lysosomal degradation",
    },
    "K33": {
        "functional_category": "signaling",
        "functional_subcategory": "post_golgi_trafficking",
        "description": "K33-linked polyubiquitin chain → post-Golgi trafficking",
        "signaling_role": "T cell receptor signaling, AMPK regulation",
    },
    "K6": {
        "functional_category": "dna_repair",
        "functional_subcategory": "dna_damage_response",
        "description": "K6-linked polyubiquitin chain → DNA damage response",
        "signaling_role": "BRCA1/BARD1-mediated DNA repair, mitophagy (PARKIN)",
    },
    "M1": {
        "functional_category": "immune",
        "functional_subcategory": "nfkb_innate_immunity",
        "description": "M1 (linear) polyubiquitin chain → LUBAC-mediated NF-κB activation",
        "signaling_role": "Innate immunity, NF-κB signaling, RIPK1 regulation",
    },
    "Mono": {
        "functional_category": "trafficking",
        "functional_subcategory": "receptor_trafficking",
        "description": "Monoubiquitylation → endosomal sorting, receptor internalization",
        "signaling_role": "EGFR/GPCR trafficking, histone modification (H2A-K119, H2B-K120), DNA repair",
    },
    "Multi-mono": {
        "functional_category": "trafficking",
        "functional_subcategory": "multivesicular_body",
        "description": "Multi-monoubiquitylation → MVB sorting, ESCRT pathway",
        "signaling_role": "Receptor downregulation, lysosomal degradation via MVB pathway",
    },
}

# ── Degron Motif → Inferred Chain Type ───────────────────────────────────────
DEGRON_CHAIN_MAP: Dict[str, Dict] = {
    "SCF_complex":      {"chain_types": ["K48"], "functional_category": "degradation"},
    "SCF_complex_degron": {"chain_types": ["K48"], "functional_category": "degradation"},
    "APC/C_D-box":      {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle"},
    "APC/C_D-box_degron": {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle"},
    "APC/C_KEN-box":    {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle"},
    "APC/C_KEN-box_degron": {"chain_types": ["K11", "K48"], "functional_category": "cell_cycle"},
    "HECT_E3":          {"chain_types": ["K63", "K48"], "functional_category": "signaling"},
    "HECT_E3_PY_motif": {"chain_types": ["K63", "K48"], "functional_category": "signaling"},
    "VHL":              {"chain_types": ["K48"], "functional_category": "degradation"},
    "VHL_oxygen_degron": {"chain_types": ["K48"], "functional_category": "degradation"},
    "MDM2":             {"chain_types": ["K48"], "functional_category": "degradation"},
    "BTRC/FBXW_degron": {"chain_types": ["K48"], "functional_category": "degradation"},
    "K48_polyubiquitin_linkage": {"chain_types": ["K48"], "functional_category": "degradation"},
    "K63_polyubiquitin_linkage": {"chain_types": ["K63"], "functional_category": "signaling"},
    "Lysine_ubiquitylation_general": {"chain_types": [], "functional_category": "unknown"},
}

# ── DUB Families and their substrates ────────────────────────────────────────
DUB_FAMILY_MAP: Dict[str, Dict] = {
    # USP family (largest DUB family)
    "USP7":   {"substrates": ["TP53", "MDM2", "PTEN"], "chain_pref": ["K48"], "function": "Stabilizes TP53 by removing K48 chains; also stabilizes MDM2"},
    "USP10":  {"substrates": ["TP53"], "chain_pref": ["K48"], "function": "Stabilizes TP53 in cytoplasm"},
    "USP2":   {"substrates": ["MDM2", "MDMX"], "chain_pref": ["K48"], "function": "Stabilizes MDM2"},
    "USP4":   {"substrates": ["TRAF2", "TRAF6"], "chain_pref": ["K63"], "function": "Removes K63 chains from TRAF proteins"},
    "USP8":   {"substrates": ["EGFR", "ERBB2"], "chain_pref": ["K63", "Mono"], "function": "Regulates EGFR trafficking"},
    "USP14":  {"substrates": ["proteasome"], "chain_pref": ["K48"], "function": "Proteasome-associated DUB"},
    "USP15":  {"substrates": ["SMAD1", "SMAD2"], "chain_pref": ["K48"], "function": "TGF-β pathway regulation"},
    "USP18":  {"substrates": ["ISG15"], "chain_pref": ["ISG15"], "function": "ISGylation reversal, IFN signaling"},
    "USP25":  {"substrates": ["TRAF3", "TRAF6"], "chain_pref": ["K63"], "function": "NF-κB negative regulation"},
    "USP28":  {"substrates": ["MYC", "NOTCH1"], "chain_pref": ["K48"], "function": "Stabilizes MYC"},
    "CYLD":   {"substrates": ["TRAF2", "TRAF6", "RIPK1"], "chain_pref": ["K63", "M1"], "function": "NF-κB negative regulator; removes K63/M1 chains"},
    "A20":    {"substrates": ["RIPK1", "TRAF6"], "chain_pref": ["K63"], "function": "NF-κB termination; K63 deubiquitylase + K48 E3 ligase"},
    "OTULIN": {"substrates": ["LUBAC", "RIPK1"], "chain_pref": ["M1"], "function": "Linear (M1) chain-specific DUB"},
    "OTUB1":  {"substrates": ["RAS", "SMAD2"], "chain_pref": ["K48"], "function": "K48-specific DUB; non-catalytic UBE2N inhibitor"},
    "OTUB2":  {"substrates": ["K63 substrates"], "chain_pref": ["K63"], "function": "K63-specific DUB"},
    "BAP1":   {"substrates": ["H2A-K119"], "chain_pref": ["Mono"], "function": "Histone H2A deubiquitylase; tumor suppressor"},
    "BRCC3":  {"substrates": ["K63 substrates"], "chain_pref": ["K63"], "function": "K63-specific DUB in BRCC complex"},
    "UCHL1":  {"substrates": ["alpha-synuclein"], "chain_pref": ["Mono"], "function": "Neuronal DUB; Parkinson's disease"},
    "UCHL3":  {"substrates": ["PCNA"], "chain_pref": ["Mono"], "function": "DNA repair"},
    "UCHL5":  {"substrates": ["proteasome"], "chain_pref": ["K48"], "function": "Proteasome-associated DUB"},
    "ATXN3":  {"substrates": ["K63 substrates"], "chain_pref": ["K63"], "function": "Spinocerebellar ataxia; K63 DUB"},
    "JOSD1":  {"substrates": ["K6 substrates"], "chain_pref": ["K6"], "function": "K6-specific DUB"},
    "MINDY1": {"substrates": ["K48 substrates"], "chain_pref": ["K48"], "function": "K48-specific DUB"},
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

def classify_ubiquitin_chain_types(
    enriched_data: List[dict],
) -> Dict[str, dict]:
    """
    Classify ubiquitin chain types for all ubiquitylation sites.

    Args:
        enriched_data: List of enriched PTM entries from state["enriched_ptm_data"]

    Returns:
        Dict keyed by "GENE_POSITION" → chain type classification result
    """
    results: Dict[str, dict] = {}

    for entry in enriched_data:
        gene = (entry.get("gene") or entry.get("Gene.Name", "")).strip().upper()
        pos = str(entry.get("position") or entry.get("PTM_Position", "")).strip()
        if not gene or not pos:
            continue

        ptm_key = f"{gene}_{pos}"
        classification = _classify_single_site(gene, pos, entry)
        results[ptm_key] = classification

    return results


def _classify_single_site(gene: str, position: str, entry: dict) -> dict:
    """Classify chain type for a single ubiquitylation site."""
    rag = entry.get("rag_enrichment", {}) or {}
    regulation = rag.get("regulation", {}) or {}

    evidence_sources: List[str] = []
    chain_types_found: Set[str] = set()
    e3_ligases_found: List[str] = []
    dub_candidates: List[str] = []
    confidence_score = 0

    # ── Source 1: Literature chain types (highest confidence) ────────────
    lit_chain_types = regulation.get("chain_types", [])
    if lit_chain_types:
        chain_types_found.update(lit_chain_types)
        evidence_sources.append("literature_chain_type")
        confidence_score += 40

    # ── Source 2: E3 ligase identity → chain type preference ─────────────
    # From regulation.e3_substrate
    e3_substrates = regulation.get("e3_substrate", [])
    for e3s in e3_substrates:
        e3_name = (e3s.get("e3_ligase") or "").strip().upper()
        if e3_name:
            e3_ligases_found.append(e3_name)
            for known_e3, info in E3_CHAIN_TYPE_MAP.items():
                if known_e3.upper() in e3_name or e3_name in known_e3.upper():
                    chain_types_found.update(info["chain_types"])
                    evidence_sources.append(f"e3_ligase_{known_e3.lower()}")
                    confidence_score += 30
                    break

    # From kinase_prediction (LLM predicted E3)
    kp = rag.get("kinase_prediction", {})
    if isinstance(kp, str):
        import ast
        try:
            kp = ast.literal_eval(kp) if kp.startswith("{") else {}
        except Exception:
            kp = {}
    if isinstance(kp, dict):
        for pk in kp.get("predictedKinases", kp.get("predicted_kinases", [])):
            if isinstance(pk, dict):
                e3_name = (pk.get("kinase") or "").strip().upper()
                if e3_name:
                    e3_ligases_found.append(e3_name)
                    for known_e3, info in E3_CHAIN_TYPE_MAP.items():
                        if known_e3.upper() in e3_name or e3_name in known_e3.upper():
                            chain_types_found.update(info["chain_types"])
                            evidence_sources.append(f"llm_e3_{known_e3.lower()}")
                            confidence_score += 20
                            break

    # ── Source 3: Degron motif match ─────────────────────────────────────
    # From enhanced_motif_analyzer results (stored in rag_enrichment or entry)
    motif_matches = (
        entry.get("motif_matches", [])
        or rag.get("motif_matches", [])
        or entry.get("ubi_motif_matches", [])
    )
    for motif in motif_matches:
        motif_name = motif if isinstance(motif, str) else motif.get("motif", "")
        for degron_key, degron_info in DEGRON_CHAIN_MAP.items():
            if degron_key.lower() in motif_name.lower():
                chain_types_found.update(degron_info["chain_types"])
                evidence_sources.append(f"degron_motif_{degron_key.lower()}")
                confidence_score += 15
                break

    # ── Source 4: GO terms / pathway context ─────────────────────────────
    go_bp = rag.get("go_terms", {}).get("biological_process", [])
    go_text = " ".join(go_bp).lower()
    pathways = [p.get("name", "") for p in rag.get("pathways", [])]
    pathway_text = " ".join(pathways).lower()
    context_text = go_text + " " + pathway_text

    if any(kw in context_text for kw in ["proteasom", "degradation", "ubiquitin-proteasome"]):
        if "K48" not in chain_types_found:
            chain_types_found.add("K48")
            evidence_sources.append("go_pathway_proteasome")
            confidence_score += 10
    if any(kw in context_text for kw in ["nf-kb", "nfkb", "innate immun", "inflammatory"]):
        if "K63" not in chain_types_found:
            chain_types_found.add("K63")
            evidence_sources.append("go_pathway_nfkb")
            confidence_score += 10
    if any(kw in context_text for kw in ["dna repair", "dna damage", "double-strand break"]):
        if "K63" not in chain_types_found:
            chain_types_found.add("K63")
            evidence_sources.append("go_pathway_dna_repair")
            confidence_score += 10
    if any(kw in context_text for kw in ["autophagy", "mitophagy", "selective autophagy"]):
        if "K63" not in chain_types_found:
            chain_types_found.add("K63")
            evidence_sources.append("go_pathway_autophagy")
            confidence_score += 10
    if any(kw in context_text for kw in ["endosom", "trafficking", "receptor internalization", "mvb"]):
        if "Mono" not in chain_types_found:
            chain_types_found.add("Mono")
            evidence_sources.append("go_pathway_trafficking")
            confidence_score += 10
    if any(kw in context_text for kw in ["cell cycle", "mitosis", "apc/c", "mitotic"]):
        if "K11" not in chain_types_found:
            chain_types_found.add("K11")
            evidence_sources.append("go_pathway_cell_cycle")
            confidence_score += 10

    # ── Source 5: DUB candidates from literature ─────────────────────────
    dub_substrates = regulation.get("dub_substrate", [])
    for ds in dub_substrates:
        dub_name = (ds.get("dub") or "").strip().upper()
        if dub_name:
            dub_candidates.append(dub_name)
            # DUB chain preference → infer chain type
            for known_dub, dub_info in DUB_FAMILY_MAP.items():
                if known_dub.upper() in dub_name or dub_name in known_dub.upper():
                    chain_types_found.update(dub_info["chain_pref"])
                    evidence_sources.append(f"dub_{known_dub.lower()}")
                    confidence_score += 10
                    break

    # Also check abstract_analysis for DUB mentions
    aa = rag.get("abstract_analysis", {}) or {}
    for item in aa.get("regulators", []) + aa.get("upstream_kinases", []):
        name = (item if isinstance(item, str) else item.get("name", "")).upper()
        for known_dub in DUB_FAMILY_MAP:
            if known_dub.upper() in name:
                if name not in dub_candidates:
                    dub_candidates.append(name)
                break

    # ── Determine functional category ────────────────────────────────────
    functional_category, functional_subcategory = _determine_functional_category(
        chain_types_found, e3_ligases_found, context_text
    )

    # ── Confidence level ──────────────────────────────────────────────────
    if confidence_score >= 40:
        confidence = "high"
    elif confidence_score >= 20:
        confidence = "medium"
    elif confidence_score > 0:
        confidence = "low"
    else:
        confidence = "unknown"
        functional_category = "unknown"
        functional_subcategory = "insufficient_evidence"

    # ── Build biological interpretation ──────────────────────────────────
    interpretation = _build_interpretation(
        gene, position, chain_types_found, functional_category,
        e3_ligases_found, dub_candidates
    )

    return {
        "gene": gene,
        "position": position,
        "inferred_chain_types": sorted(chain_types_found),
        "functional_category": functional_category,
        "functional_subcategory": functional_subcategory,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "evidence_sources": list(dict.fromkeys(evidence_sources)),  # deduplicated
        "e3_ligases": list(dict.fromkeys(e3_ligases_found)),
        "dub_candidates": list(dict.fromkeys(dub_candidates)),
        "biological_interpretation": interpretation,
    }


def _determine_functional_category(
    chain_types: Set[str],
    e3_ligases: List[str],
    context_text: str,
) -> Tuple[str, str]:
    """Determine the primary functional category from chain types and context."""

    if not chain_types:
        return "unknown", "insufficient_evidence"

    # Priority order: if multiple chain types, use the most specific/confident
    priority_order = ["K48", "K63", "K11", "M1", "K6", "K27", "K29", "K33", "Mono", "Multi-mono"]

    # Check E3 ligase for override
    for e3 in e3_ligases:
        for known_e3, info in E3_CHAIN_TYPE_MAP.items():
            if known_e3.upper() in e3.upper():
                cat = info["functional_category"]
                sub = CHAIN_FUNCTION_MAP.get(info["chain_types"][0], {}).get("functional_subcategory", cat)
                return cat, sub

    # Use chain type priority
    for chain in priority_order:
        if chain in chain_types:
            info = CHAIN_FUNCTION_MAP.get(chain, {})
            return (
                info.get("functional_category", "unknown"),
                info.get("functional_subcategory", "unknown"),
            )

    return "unknown", "insufficient_evidence"


def _build_interpretation(
    gene: str,
    position: str,
    chain_types: Set[str],
    functional_category: str,
    e3_ligases: List[str],
    dub_candidates: List[str],
) -> str:
    """Build a concise biological interpretation string."""
    parts = []

    chain_str = "/".join(sorted(chain_types)) if chain_types else "unknown chain type"
    e3_str = ", ".join(e3_ligases[:2]) if e3_ligases else "unknown E3 ligase"
    dub_str = ", ".join(dub_candidates[:2]) if dub_candidates else None

    cat_descriptions = {
        "degradation": f"targets {gene} {position} for proteasomal degradation via {chain_str} polyubiquitin chain",
        "signaling": f"creates non-degradative {chain_str} ubiquitin scaffold on {gene} {position} for signaling",
        "dna_repair": f"recruits DNA repair machinery to {gene} {position} via {chain_str} ubiquitin chain",
        "trafficking": f"marks {gene} {position} for endosomal sorting/receptor trafficking via {chain_str} ubiquitylation",
        "autophagy": f"targets {gene} {position} for selective autophagy via {chain_str} ubiquitin chain",
        "cell_cycle": f"regulates cell cycle progression by {chain_str}-mediated ubiquitylation of {gene} {position}",
        "immune": f"activates innate immune signaling via {chain_str} ubiquitylation of {gene} {position}",
        "transcription": f"regulates transcription via mono-ubiquitylation of {gene} {position}",
        "unknown": f"{chain_str} ubiquitylation at {gene} {position} (function unclear)",
    }

    desc = cat_descriptions.get(functional_category, cat_descriptions["unknown"])
    parts.append(f"{e3_str} {desc}")

    if dub_str:
        parts.append(f"Reversed by {dub_str}")

    return ". ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# AGGREGATE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def build_chain_type_summary(
    classifications: Dict[str, dict],
    ptm_type: str = "ubiquitylation",
) -> dict:
    """
    Build aggregate summary of chain type classifications across all sites.

    Returns:
        {
            "total_sites": int,
            "by_functional_category": {category: [sites]},
            "by_chain_type": {chain: [sites]},
            "degradation_fraction": float,
            "signaling_fraction": float,
            "high_confidence_count": int,
            "e3_ligase_frequency": {e3: count},
            "dub_frequency": {dub: count},
            "llm_context": str,
        }
    """
    if not classifications:
        return {"total_sites": 0, "llm_context": ""}

    by_category: Dict[str, List[str]] = {}
    by_chain: Dict[str, List[str]] = {}
    e3_freq: Dict[str, int] = {}
    dub_freq: Dict[str, int] = {}
    high_conf = 0

    for ptm_key, cls in classifications.items():
        cat = cls.get("functional_category", "unknown")
        by_category.setdefault(cat, []).append(ptm_key)

        for ct in cls.get("inferred_chain_types", []):
            by_chain.setdefault(ct, []).append(ptm_key)

        for e3 in cls.get("e3_ligases", []):
            e3_freq[e3] = e3_freq.get(e3, 0) + 1

        for dub in cls.get("dub_candidates", []):
            dub_freq[dub] = dub_freq.get(dub, 0) + 1

        if cls.get("confidence") == "high":
            high_conf += 1

    total = len(classifications)
    deg_count = len(by_category.get("degradation", []))
    sig_count = len(by_category.get("signaling", []))

    summary = {
        "total_sites": total,
        "by_functional_category": {k: v for k, v in sorted(by_category.items(), key=lambda x: -len(x[1]))},
        "by_chain_type": {k: v for k, v in sorted(by_chain.items(), key=lambda x: -len(x[1]))},
        "degradation_fraction": round(deg_count / total, 3) if total else 0,
        "signaling_fraction": round(sig_count / total, 3) if total else 0,
        "high_confidence_count": high_conf,
        "e3_ligase_frequency": dict(sorted(e3_freq.items(), key=lambda x: -x[1])[:10]),
        "dub_frequency": dict(sorted(dub_freq.items(), key=lambda x: -x[1])[:10]),
    }

    summary["llm_context"] = _build_chain_type_llm_context(summary, classifications)
    return summary


def _build_chain_type_llm_context(
    summary: dict,
    classifications: Dict[str, dict],
) -> str:
    """Build LLM context string for chain type analysis."""
    lines = [
        "═══════════════════════════════════════════════════════════════",
        "UBIQUITIN CHAIN TYPE ANALYSIS (Module 1 — v9.14)",
        "═══════════════════════════════════════════════════════════════",
        "",
        f"Total ubiquitylation sites analyzed: {summary['total_sites']}",
        f"High-confidence classifications: {summary['high_confidence_count']}",
        "",
        "── Section A: Functional Category Distribution ──────────────",
    ]

    for cat, sites in summary.get("by_functional_category", {}).items():
        pct = round(len(sites) / summary["total_sites"] * 100, 1) if summary["total_sites"] else 0
        lines.append(f"  {cat.upper():20s}: {len(sites):3d} sites ({pct}%)")

    lines += [
        "",
        "── Section B: Chain Type Distribution ───────────────────────",
    ]
    for chain, sites in summary.get("by_chain_type", {}).items():
        info = CHAIN_FUNCTION_MAP.get(chain, {})
        desc = info.get("description", "")
        lines.append(f"  {chain:12s}: {len(sites):3d} sites — {desc}")

    lines += [
        "",
        "── Section C: Top E3 Ligases Identified ─────────────────────",
    ]
    for e3, cnt in list(summary.get("e3_ligase_frequency", {}).items())[:8]:
        e3_info = E3_CHAIN_TYPE_MAP.get(e3.upper(), {})
        family = e3_info.get("family", "unknown family")
        chain_pref = "/".join(e3_info.get("chain_types", ["?"]))
        lines.append(f"  {e3:15s}: {cnt} substrates | {family} | preferred chain: {chain_pref}")

    lines += [
        "",
        "── Section D: DUB Candidates (Reversal Enzymes) ─────────────",
    ]
    for dub, cnt in list(summary.get("dub_frequency", {}).items())[:6]:
        dub_info = DUB_FAMILY_MAP.get(dub.upper(), {})
        func = dub_info.get("function", "")
        lines.append(f"  {dub:15s}: {cnt} substrates — {func}")

    lines += [
        "",
        "── Section E: High-Confidence Site Details ──────────────────",
    ]
    high_conf_sites = [
        (k, v) for k, v in classifications.items()
        if v.get("confidence") in ("high", "medium")
    ]
    high_conf_sites.sort(key=lambda x: x[1].get("confidence_score", 0), reverse=True)

    for ptm_key, cls in high_conf_sites[:15]:
        chain_str = "/".join(cls.get("inferred_chain_types", ["?"])) or "?"
        cat = cls.get("functional_category", "?")
        conf = cls.get("confidence", "?")
        interp = cls.get("biological_interpretation", "")
        lines.append(f"  {ptm_key:20s} [{chain_str:12s}] {cat:15s} ({conf})")
        if interp:
            lines.append(f"    → {interp[:120]}")

    lines += [
        "",
        "── LLM Instructions ─────────────────────────────────────────",
        "CRITICAL: Ubiquitylation is NOT solely a degradation signal.",
        "Use the chain type classifications above to:",
        "1. Distinguish degradative (K48/K11) vs non-degradative (K63/M1/Mono) ubiquitylation",
        "2. Identify signaling pathways activated by K63-linked ubiquitylation",
        "3. Discuss E3 ligase-substrate specificity and chain type preference",
        "4. Mention DUB-mediated reversal where evidence exists",
        "5. Integrate chain type data with temporal patterns (when/where each type is active)",
        "═══════════════════════════════════════════════════════════════",
    ]

    return "\n".join(lines)
