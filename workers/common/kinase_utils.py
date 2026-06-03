"""
Kinase Name Normalization & Family Matching Utilities.

Shared between:
  - api-server/app/api/orders.py (motif-kinase-annotation API)
  - workers/report_generation/core/nodes/kinase_annotation_node.py (temporal cascade)

v9.11: Extracted from orders.py for reuse across modules.
"""

import re
from typing import Dict, Set, Tuple

# ── Kinase Alias Map ──────────────────────────────────────────────────────────
# Maps variant names (uppercase) → canonical HGNC gene symbol or family name.

KINASE_ALIAS_MAP: Dict[str, str] = {
    # CDK family
    "CDK": "CDK",
    "CDK1/CDK2": "CDK1/CDK2",
    "CDK/MAPK": "CDK/MAPK",
    "CDC2": "CDK1", "CDK1": "CDK1", "CDC28": "CDK1",
    "CDK2": "CDK2",
    "CDK4": "CDK4", "CDK6": "CDK6",
    "CDK5": "CDK5", "CDK5R1": "CDK5",
    "CDK7": "CDK7", "CDK9": "CDK9",
    # CK (Casein Kinase) family
    "CK1": "CSNK1",
    "CK1_CANONICAL": "CSNK1",
    "CSNK1A1": "CSNK1A1", "CSNK1D": "CSNK1D", "CSNK1E": "CSNK1E",
    "CK2": "CSNK2",
    "CK2_EXTENDED": "CSNK2",
    "CKII_LIKE": "CSNK2",
    "CSNK2A1": "CSNK2A1", "CSNK2A2": "CSNK2A2", "CSNK2B": "CSNK2B",
    "CASEIN KINASE II": "CSNK2", "CASEIN KINASE 2": "CSNK2",
    "CASEIN KINASE I": "CSNK1", "CASEIN KINASE 1": "CSNK1",
    # MAPK family
    "MAPK": "MAPK",
    "ERK1": "MAPK3", "MAPK3": "MAPK3",
    "ERK2": "MAPK1", "MAPK1": "MAPK1",
    "ERK1/ERK2": "MAPK3/MAPK1",
    "JNK": "MAPK8", "JNK1": "MAPK8", "MAPK8": "MAPK8",
    "JNK2": "MAPK9", "MAPK9": "MAPK9",
    "JNK3": "MAPK10", "MAPK10": "MAPK10",
    "P38": "MAPK14", "P38A": "MAPK14", "P38ALPHA": "MAPK14", "MAPK14": "MAPK14",
    "P38B": "MAPK11", "P38BETA": "MAPK11",
    # PKA / PKC / AKT
    "PKA": "PRKACA", "PRKACA": "PRKACA", "PRKACB": "PRKACB",
    "PKC": "PKC",
    "PKCA": "PRKCA", "PRKCA": "PRKCA",
    "PKCB": "PRKCB", "PRKCB": "PRKCB",
    "PKCD": "PRKCD", "PRKCD": "PRKCD",
    "AKT": "AKT1", "AKT/PKB": "AKT1",
    "AKT1": "AKT1", "AKT2": "AKT2", "AKT3": "AKT3",
    "PKB": "AKT1",
    # GSK3
    "GSK3": "GSK3B", "GSK3_MINIMAL": "GSK3B",
    "GSK3A": "GSK3A", "GSK3B": "GSK3B",
    "GSK-3": "GSK3B", "GSK-3BETA": "GSK3B", "GSK-3ALPHA": "GSK3A",
    "GSK3BETA": "GSK3B", "GSK3ALPHA": "GSK3A",
    "GSK-3B": "GSK3B", "GSK-3A": "GSK3A",
    # PLK family
    "PLK1": "PLK1", "PLK1_EXTENDED": "PLK1",
    "PLK2": "PLK2", "PLK3": "PLK3", "PLK4": "PLK4",
    # Aurora family
    "AURORA": "AURKA",
    "AURORA_A/B": "AURKA/AURKB",
    "AURKA": "AURKA", "AURORA A": "AURKA", "AURORA-A": "AURKA",
    "AURKB": "AURKB", "AURORA B": "AURKB", "AURORA-B": "AURKB",
    "AURKC": "AURKC",
    # ATM/ATR/DNA-PK
    "ATM": "ATM", "ATR": "ATR", "ATM/ATR": "ATM/ATR",
    "DNA-PK": "PRKDC", "DNAPK": "PRKDC", "PRKDC": "PRKDC",
    # NEK family
    "NEK": "NEK",
    "NEK2": "NEK2", "NEK6": "NEK6", "NEK2/NEK6": "NEK2/NEK6",
    # CAMK family
    "CAMK": "CAMK",
    "CAMK2": "CAMK2",
    "CAMK2A": "CAMK2A", "CAMK2B": "CAMK2B", "CAMK2D": "CAMK2D", "CAMK2G": "CAMK2G",
    "CAMKII": "CAMK2",
    # AMPK
    "AMPK": "PRKAA1", "PRKAA1": "PRKAA1", "PRKAA2": "PRKAA2",
    # mTOR
    "MTOR": "MTOR", "FRAP1": "MTOR",
    # Src family
    "SRC": "SRC", "SRC-FAMILY": "SRC",
    "SRC/FYN/YES": "SRC",
    "FYN": "FYN", "YES": "YES1", "YES1": "YES1",
    "LYN": "LYN", "LCK": "LCK", "HCK": "HCK",
    # Other tyrosine kinases
    "ABL": "ABL1", "ABL1": "ABL1", "ABL2": "ABL2",
    "JAK1": "JAK1", "JAK2": "JAK2", "JAK1/JAK2": "JAK1/JAK2",
    "JAK3": "JAK3", "TYK2": "TYK2",
    "SYK": "SYK", "ZAP70": "ZAP70", "SYK/ZAP70": "SYK/ZAP70",
    "BTK": "BTK",
    "FAK": "PTK2", "PTK2": "PTK2",
    "FLT3": "FLT3",
    # Receptor TKs
    "EGFR": "EGFR", "ERBB1": "EGFR", "HER1": "EGFR",
    "ERBB2": "ERBB2", "HER2": "ERBB2",
    "PDGFR": "PDGFRA", "PDGFRA": "PDGFRA", "PDGFRB": "PDGFRB",
    "PDGFR/FGFR": "PDGFRA",
    "FGFR": "FGFR1", "FGFR1": "FGFR1", "FGFR2": "FGFR2",
    "VEGFR": "KDR", "KDR": "KDR", "VEGFR2": "KDR",
    "INSR": "INSR", "IGF1R": "IGF1R", "INSR/IGF1R": "INSR/IGF1R",
    # Other kinases
    "RSK": "RPS6KA1", "RSK1": "RPS6KA1", "RSK2": "RPS6KA3",
    "SGK": "SGK1", "SGK1": "SGK1",
    "PIM1": "PIM1", "PIM2": "PIM2", "PIM1/PIM2": "PIM1/PIM2",
    "PKD": "PRKD1", "PRKD1": "PRKD1",
    "MARK": "MARK2", "MARK/PAR1": "MARK2",
    "CHK1": "CHEK1", "CHEK1": "CHEK1",
    "CHK2": "CHEK2", "CHEK2": "CHEK2",
    "CHK1/CHK2": "CHEK1/CHEK2",
    "PAK1": "PAK1", "PAK2": "PAK2", "PAK1/PAK2": "PAK1/PAK2",
    "DYRK1A": "DYRK1A", "DYRK1B": "DYRK1B", "DYRK1A/DYRK1B": "DYRK1A/DYRK1B",
    "CLK1": "CLK1", "CLK1-4": "CLK",
    "SRPK1": "SRPK1", "SRPK2": "SRPK2", "SRPK1/SRPK2": "SRPK1/SRPK2",
    "S6K": "RPS6KB1", "RPS6KB1": "RPS6KB1",
    "ROCK1": "ROCK1", "ROCK2": "ROCK2", "ROCK1/ROCK2": "ROCK1/ROCK2",
    "LATS1": "LATS1", "LATS2": "LATS2", "LATS1/LATS2": "LATS1/LATS2",
    "MST1": "STK4", "MST2": "STK3", "MST1/MST2": "STK4/STK3",
    "HIPK2": "HIPK2",
    "BUB1": "BUB1",
    "TBK1": "TBK1", "IKKE": "IKBKE", "TBK1/IKKE": "TBK1/IKBKE",
    "IKKA": "CHUK", "IKKB": "IKBKB", "IKKA/IKKB": "CHUK/IKBKB",
    "GRK": "GRK",
    "MRCK": "CDC42BPA",
    # Ubiquitin E3 ligases
    "SCF_COMPLEX": "SCF", "APC/C_D-BOX": "APC/C", "APC/C_KEN-BOX": "APC/C",
    "HECT_E3": "HECT", "VHL": "VHL", "MDM2": "MDM2",
    "CHIP/STUB1": "STUB1", "NEDD4/ITCH": "NEDD4",
    "TRAF6": "TRAF6", "KEAP1/CUL3": "KEAP1",
    "BTRC/FBXW": "BTRC", "SMURF1/2": "SMURF1",
}

# Build reverse lookup: canonical → set of aliases (for family-level matching)
KINASE_FAMILY_MEMBERS: Dict[str, Set[str]] = {}
for _alias, _canonical in KINASE_ALIAS_MAP.items():
    _canonical_upper = _canonical.upper()
    if _canonical_upper not in KINASE_FAMILY_MEMBERS:
        KINASE_FAMILY_MEMBERS[_canonical_upper] = set()
    KINASE_FAMILY_MEMBERS[_canonical_upper].add(_alias.upper())


# Greek letter → single-letter suffix mapping for kinase name normalization
_GREEK_SUFFIX_MAP = {
    "ALPHA": "A", "BETA": "B", "GAMMA": "G", "DELTA": "D",
    "EPSILON": "E", "ZETA": "Z", "ETA": "H", "THETA": "T",
    "IOTA": "I", "KAPPA": "K", "LAMBDA": "L",
}


def normalize_kinase_name(raw_name: str) -> Tuple[str, str]:
    """Normalize a kinase name to its canonical form.

    Returns (canonical_name, display_name):
      - canonical_name: HGNC gene symbol or standardized family name (uppercase)
      - display_name: human-readable form for UI display

    Strategy:
      1. Exact match in alias map (case-insensitive)
      2. Strip common suffixes (" kinase", " family") and retry
      3. Handle hyphenated/spaced variants (e.g., "CDK-1" → "CDK1")
      3b. Greek letter suffix normalization (e.g., "GSK3beta" → "GSK3B")
      4. Fallback: uppercase the raw name
    """
    if not raw_name or not raw_name.strip():
        return ("", "")

    name = raw_name.strip()
    name_upper = name.upper()

    # 1. Exact match
    if name_upper in KINASE_ALIAS_MAP:
        canonical = KINASE_ALIAS_MAP[name_upper]
        return (canonical.upper(), canonical)

    # 2. Strip common suffixes and retry
    cleaned = re.sub(
        r'\s*(kinase|family|protein|enzyme)\s*$', '', name_upper, flags=re.IGNORECASE
    ).strip()
    if cleaned and cleaned != name_upper and cleaned in KINASE_ALIAS_MAP:
        canonical = KINASE_ALIAS_MAP[cleaned]
        return (canonical.upper(), canonical)

    # 3. Handle hyphenated/spaced variants (e.g., "CDK-1" → "CDK1")
    no_sep = re.sub(r'[-\s]+', '', name_upper)
    if no_sep != name_upper and no_sep in KINASE_ALIAS_MAP:
        canonical = KINASE_ALIAS_MAP[no_sep]
        return (canonical.upper(), canonical)

    # 3b. Greek letter suffix normalization (e.g., "GSK3BETA" → "GSK3B", "PKCDELTA" → "PKCD")
    for greek, letter in _GREEK_SUFFIX_MAP.items():
        if name_upper.endswith(greek):
            greek_normalized = name_upper[:-len(greek)] + letter
            if greek_normalized in KINASE_ALIAS_MAP:
                canonical = KINASE_ALIAS_MAP[greek_normalized]
                return (canonical.upper(), canonical)
            # Also try without separators in the prefix
            no_sep_greek = re.sub(r'[-\s]+', '', greek_normalized)
            if no_sep_greek in KINASE_ALIAS_MAP:
                canonical = KINASE_ALIAS_MAP[no_sep_greek]
                return (canonical.upper(), canonical)
            break  # Only one Greek suffix possible

    # 4. Fallback: return uppercase
    return (name_upper, name)


def are_kinases_same_family(name_a: str, name_b: str) -> bool:
    """Check if two kinase names belong to the same family.

    Handles cases like:
      - 'CDK' (family) vs 'CDK1' (isoform) → True
      - 'CK2' vs 'CSNK2A1' → True (both normalize to CSNK2 family)
      - 'MAPK' vs 'ERK2' → True (ERK2 = MAPK1)
    """
    canon_a, _ = normalize_kinase_name(name_a)
    canon_b, _ = normalize_kinase_name(name_b)

    if not canon_a or not canon_b:
        return False

    # Exact match after normalization
    if canon_a == canon_b:
        return True

    # Check if one is a prefix of the other (family vs isoform)
    if canon_a.startswith(canon_b) or canon_b.startswith(canon_a):
        return True

    # Check composite names (e.g., "CDK1/CDK2" contains "CDK1")
    parts_a = set(canon_a.split('/'))
    parts_b = set(canon_b.split('/'))
    if parts_a & parts_b:
        return True

    # Check if either is contained in the other's composite
    for pa in parts_a:
        for pb in parts_b:
            if pa and pb and len(pa) >= 3 and len(pb) >= 3:
                if pa.startswith(pb) or pb.startswith(pa):
                    return True

    return False
