"""PTM Analysis configuration constants — ported from original."""

UNIMOD_MAPPING = {
    "1": "Acetylation",
    "21": "Phosphorylation",
    "34": "Monomethylation",
    "35": "Dimethylation",
    "36": "Trimethylation",
    "4": "Carbamidomethyl",
}

FIXED_MODIFICATIONS = {
    "4": "Carbamidomethylation",
}

VARIABLE_MODIFICATIONS = {
    "21": {"name": "Phosphorylation", "residues": ["S", "T", "Y"]},
    "121": {"name": "Ubiquitylation", "residues": ["K"]},
    "35": {"name": "Oxidation", "residues": ["M"]},
}

PTM_MODES = {
    "phospho": {
        "unimod_id": "21",
        "name": "Phosphorylation",
        "residues": ["S", "T", "Y"],
        "file_suffix": "_phospho",
    },
    "ubi": {
        "unimod_id": "121",
        "name": "Ubiquitylation",
        "residues": ["K"],
        "file_suffix": "_ubi",
    },
}
