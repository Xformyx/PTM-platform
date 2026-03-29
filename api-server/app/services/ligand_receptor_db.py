"""
Comprehensive ligand → receptor mapping database for Source C
(treatment-context-based receptor inference).

Each entry maps a ligand (treatment molecule) to its known receptor(s).
Matching is case-insensitive and supports aliases.

Structure:
    LIGAND_RECEPTOR_DB: list of dicts, each with:
        - ligand_aliases: list[str]  — names/aliases for the ligand (lowercase)
        - receptors: list[dict]      — each receptor with name, class, pathway, evidence

Categories covered:
    1. Myokines / Exercise factors
    2. Growth Factors (EGF, FGF, PDGF, VEGF, HGF, IGF, NGF, BDNF, etc.)
    3. Insulin / Metabolic hormones
    4. Cytokines (IL family, TNF, IFN, TGFβ, BMP)
    5. Wnt / Hedgehog / Notch (developmental)
    6. Steroid & Nuclear receptor ligands
    7. GPCR ligands (catecholamines, serotonin, histamine, etc.)
    8. Lipid mediators (PGE2, LPA, S1P, etc.)
    9. ECM / Integrin ligands
   10. Stress / Damage signals (ATP, HMGB1, etc.)
   11. Chemokines
   12. Ubiquitin-related ligands (RANKL, TRAIL, FasL, etc.)

Last updated: v9.19.4
"""

LIGAND_RECEPTOR_DB: list[dict] = [
    # ═══════════════════════════════════════════════════════════════════════
    # 1. MYOKINES / EXERCISE FACTORS
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["irisin", "fndc5", "iris"],
        "receptors": [
            {"name": "αV/β5 Integrin (ITGAV/ITGB5)", "class": "Integrin",
             "pathway": "Integrin → FAK → ERK/MAPK, Wnt/β-catenin",
             "evidence": "Kim et al. 2018 Cell; Colaianni et al. 2015"},
            {"name": "αV/β1 Integrin (ITGAV/ITGB1)", "class": "Integrin",
             "pathway": "Integrin → FAK → PI3K/AKT",
             "evidence": "Alternative integrin heterodimer in osteoblasts"},
        ],
    },
    {
        "ligand_aliases": ["il-6", "il6", "interleukin-6", "interleukin 6"],
        "receptors": [
            {"name": "IL-6R / gp130 (IL6R/IL6ST)", "class": "Cytokine/Immune",
             "pathway": "JAK/STAT3, MAPK/ERK, PI3K/AKT",
             "evidence": "Classic & trans-signaling"},
        ],
    },
    {
        "ligand_aliases": ["il-15", "il15", "interleukin-15", "interleukin 15"],
        "receptors": [
            {"name": "IL-15Rα/IL-2Rβ/γc (IL15RA/IL2RB/IL2RG)", "class": "Cytokine/Immune",
             "pathway": "JAK1/JAK3 → STAT3/STAT5",
             "evidence": "Shared γc receptor family"},
        ],
    },
    {
        "ligand_aliases": ["myostatin", "gdf-8", "gdf8", "mstn"],
        "receptors": [
            {"name": "ActRIIB (ACVR2B)", "class": "TGFβ",
             "pathway": "ActRIIB → ALK4/5 → SMAD2/3",
             "evidence": "Lee & McPherron 2001"},
            {"name": "ActRIIA (ACVR2A)", "class": "TGFβ",
             "pathway": "ActRIIA → ALK4/5 → SMAD2/3",
             "evidence": "Alternative type II receptor"},
        ],
    },
    {
        "ligand_aliases": ["fgf21", "fgf-21"],
        "receptors": [
            {"name": "FGFR1c/β-Klotho (FGFR1/KLB)", "class": "RTK",
             "pathway": "FGFR1 → FRS2 → MAPK/ERK, PI3K/AKT",
             "evidence": "Ogawa et al. 2007; β-Klotho as co-receptor"},
        ],
    },
    {
        "ligand_aliases": ["meteorin-like", "metrnl", "meteorin"],
        "receptors": [
            {"name": "KIT (CD117)", "class": "RTK",
             "pathway": "KIT → PI3K/AKT, MAPK/ERK",
             "evidence": "Rao et al. 2014 Cell"},
        ],
    },
    {
        "ligand_aliases": ["apelin", "apln"],
        "receptors": [
            {"name": "APJ (APLNR)", "class": "GPCR",
             "pathway": "Gαi → PI3K/AKT, MAPK/ERK",
             "evidence": "Tatemoto et al. 1998"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 2. GROWTH FACTORS
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["egf", "epidermal growth factor"],
        "receptors": [
            {"name": "EGFR (ErbB1/HER1)", "class": "RTK",
             "pathway": "EGFR → RAS/MAPK, PI3K/AKT, PLCγ, STAT3",
             "evidence": "Canonical RTK signaling"},
        ],
    },
    {
        "ligand_aliases": ["tgf-alpha", "tgfa", "tgfα", "tgf-α"],
        "receptors": [
            {"name": "EGFR (ErbB1/HER1)", "class": "RTK",
             "pathway": "EGFR → RAS/MAPK, PI3K/AKT",
             "evidence": "EGFR ligand family"},
        ],
    },
    {
        "ligand_aliases": ["heregulin", "neuregulin", "nrg1", "nrg-1", "hrg"],
        "receptors": [
            {"name": "ErbB3/ErbB4 (HER3/HER4)", "class": "RTK",
             "pathway": "ErbB3/4 → PI3K/AKT, MAPK/ERK",
             "evidence": "Neuregulin-ErbB signaling"},
        ],
    },
    {
        "ligand_aliases": ["fgf2", "fgf-2", "bfgf", "basic fgf", "fibroblast growth factor"],
        "receptors": [
            {"name": "FGFR1 (FGFR1)", "class": "RTK",
             "pathway": "FGFR → FRS2 → MAPK/ERK, PI3K/AKT, PLCγ",
             "evidence": "FGF/FGFR canonical signaling"},
            {"name": "FGFR2 (FGFR2)", "class": "RTK",
             "pathway": "FGFR → FRS2 → MAPK/ERK",
             "evidence": "Alternative FGFR"},
        ],
    },
    {
        "ligand_aliases": ["fgf1", "fgf-1", "afgf", "acidic fgf"],
        "receptors": [
            {"name": "FGFR1-4 (pan-FGFR)", "class": "RTK",
             "pathway": "FGFR → FRS2 → MAPK/ERK, PI3K/AKT",
             "evidence": "FGF1 binds all FGFRs"},
        ],
    },
    {
        "ligand_aliases": ["pdgf", "pdgf-bb", "pdgfbb", "pdgf-ab", "platelet-derived growth factor"],
        "receptors": [
            {"name": "PDGFRα/β (PDGFRA/PDGFRB)", "class": "RTK",
             "pathway": "PDGFR → PI3K/AKT, MAPK/ERK, PLCγ, Src",
             "evidence": "PDGF/PDGFR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["vegf", "vegf-a", "vegfa", "vascular endothelial growth factor"],
        "receptors": [
            {"name": "VEGFR2 (KDR/FLK1)", "class": "RTK",
             "pathway": "VEGFR2 → PLCγ/PKC, PI3K/AKT, MAPK/ERK",
             "evidence": "Primary VEGF signaling receptor"},
            {"name": "VEGFR1 (FLT1)", "class": "RTK",
             "pathway": "VEGFR1 → decoy/signaling",
             "evidence": "High affinity, lower signaling"},
        ],
    },
    {
        "ligand_aliases": ["hgf", "hepatocyte growth factor", "scatter factor"],
        "receptors": [
            {"name": "c-MET (MET)", "class": "RTK",
             "pathway": "MET → RAS/MAPK, PI3K/AKT, STAT3, β-catenin",
             "evidence": "HGF/MET canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["igf-1", "igf1", "insulin-like growth factor 1", "igf-i"],
        "receptors": [
            {"name": "IGF1R (IGF1R)", "class": "RTK",
             "pathway": "IGF1R → IRS → PI3K/AKT, MAPK/ERK",
             "evidence": "IGF/IGF1R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["igf-2", "igf2", "insulin-like growth factor 2", "igf-ii"],
        "receptors": [
            {"name": "IGF1R (IGF1R)", "class": "RTK",
             "pathway": "IGF1R → IRS → PI3K/AKT",
             "evidence": "IGF2 also binds IGF1R"},
            {"name": "IGF2R (IGF2R/M6PR)", "class": "Receptor",
             "pathway": "Clearance receptor / TGFβ activation",
             "evidence": "Mannose-6-phosphate receptor"},
        ],
    },
    {
        "ligand_aliases": ["ngf", "nerve growth factor"],
        "receptors": [
            {"name": "NTRK1 (TRKA)", "class": "RTK",
             "pathway": "TRKA → MAPK/ERK, PI3K/AKT, PLCγ",
             "evidence": "NGF/TRKA canonical signaling"},
            {"name": "p75NTR (NGFR)", "class": "Receptor",
             "pathway": "p75NTR → NF-κB, JNK, ceramide",
             "evidence": "Low-affinity neurotrophin receptor"},
        ],
    },
    {
        "ligand_aliases": ["bdnf", "brain-derived neurotrophic factor"],
        "receptors": [
            {"name": "NTRK2 (TRKB)", "class": "RTK",
             "pathway": "TRKB → MAPK/ERK, PI3K/AKT, PLCγ",
             "evidence": "BDNF/TRKB canonical signaling"},
            {"name": "p75NTR (NGFR)", "class": "Receptor",
             "pathway": "p75NTR → NF-κB, JNK",
             "evidence": "Low-affinity neurotrophin receptor"},
        ],
    },
    {
        "ligand_aliases": ["nt-3", "nt3", "neurotrophin-3"],
        "receptors": [
            {"name": "NTRK3 (TRKC)", "class": "RTK",
             "pathway": "TRKC → MAPK/ERK, PI3K/AKT",
             "evidence": "NT-3/TRKC canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["scf", "stem cell factor", "kit ligand", "kitl", "steel factor"],
        "receptors": [
            {"name": "KIT (CD117)", "class": "RTK",
             "pathway": "KIT → PI3K/AKT, MAPK/ERK, Src, JAK/STAT",
             "evidence": "SCF/KIT canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["csf1", "csf-1", "m-csf", "mcsf", "macrophage colony-stimulating factor"],
        "receptors": [
            {"name": "CSF1R (FMS/CD115)", "class": "RTK",
             "pathway": "CSF1R → PI3K/AKT, MAPK/ERK, PLCγ",
             "evidence": "CSF1/CSF1R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["erythropoietin", "epo"],
        "receptors": [
            {"name": "EPOR (EPOR)", "class": "Cytokine/Immune",
             "pathway": "EPOR → JAK2 → STAT5, PI3K/AKT, MAPK/ERK",
             "evidence": "EPO/EPOR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["thrombopoietin", "tpo"],
        "receptors": [
            {"name": "MPL (TPOR/CD110)", "class": "Cytokine/Immune",
             "pathway": "MPL → JAK2 → STAT3/STAT5",
             "evidence": "TPO/MPL canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["gm-csf", "gmcsf", "csf2"],
        "receptors": [
            {"name": "CSF2RA/CSF2RB (GM-CSFRα/βc)", "class": "Cytokine/Immune",
             "pathway": "JAK2 → STAT5, MAPK/ERK, PI3K/AKT",
             "evidence": "GM-CSF receptor complex"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 3. INSULIN / METABOLIC HORMONES
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["insulin", "ins"],
        "receptors": [
            {"name": "INSR (Insulin Receptor)", "class": "RTK",
             "pathway": "INSR → IRS1/2 → PI3K/AKT, MAPK/ERK",
             "evidence": "Insulin/INSR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["leptin", "lep", "ob"],
        "receptors": [
            {"name": "LEPR (Leptin Receptor/OB-R)", "class": "Cytokine/Immune",
             "pathway": "LEPR → JAK2 → STAT3, PI3K/AKT, MAPK/ERK",
             "evidence": "Leptin/LEPR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["adiponectin", "adipoq", "acrp30"],
        "receptors": [
            {"name": "AdipoR1 (ADIPOR1)", "class": "Receptor",
             "pathway": "AdipoR1 → AMPK, p38 MAPK, PPARα",
             "evidence": "Yamauchi et al. 2003 Nature"},
            {"name": "AdipoR2 (ADIPOR2)", "class": "Receptor",
             "pathway": "AdipoR2 → PPARα, AMPK",
             "evidence": "Yamauchi et al. 2003 Nature"},
        ],
    },
    {
        "ligand_aliases": ["glucagon", "gcg"],
        "receptors": [
            {"name": "GCGR (Glucagon Receptor)", "class": "GPCR",
             "pathway": "GCGR → Gαs → cAMP/PKA",
             "evidence": "Glucagon/GCGR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["glp-1", "glp1", "glucagon-like peptide 1", "exendin-4", "semaglutide", "liraglutide", "ozempic"],
        "receptors": [
            {"name": "GLP1R (GLP-1 Receptor)", "class": "GPCR",
             "pathway": "GLP1R → Gαs → cAMP/PKA/EPAC, PI3K/AKT",
             "evidence": "GLP-1/GLP1R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["ghrelin", "ghrl"],
        "receptors": [
            {"name": "GHSR (Growth Hormone Secretagogue Receptor)", "class": "GPCR",
             "pathway": "GHSR → Gαq → PLCβ/IP3/Ca2+, MAPK/ERK",
             "evidence": "Ghrelin/GHSR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["growth hormone", "gh", "somatotropin", "hgh"],
        "receptors": [
            {"name": "GHR (Growth Hormone Receptor)", "class": "Cytokine/Immune",
             "pathway": "GHR → JAK2 → STAT5, MAPK/ERK, PI3K/AKT",
             "evidence": "GH/GHR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["prolactin", "prl"],
        "receptors": [
            {"name": "PRLR (Prolactin Receptor)", "class": "Cytokine/Immune",
             "pathway": "PRLR → JAK2 → STAT5, MAPK/ERK",
             "evidence": "PRL/PRLR canonical signaling"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 4. CYTOKINES
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["tnf", "tnf-alpha", "tnfα", "tnf-α", "tumor necrosis factor"],
        "receptors": [
            {"name": "TNFR1 (TNFRSF1A)", "class": "Cytokine/Immune",
             "pathway": "TNFR1 → TRADD/TRAF2 → NF-κB, MAPK/JNK, apoptosis",
             "evidence": "TNF/TNFR1 canonical signaling"},
            {"name": "TNFR2 (TNFRSF1B)", "class": "Cytokine/Immune",
             "pathway": "TNFR2 → TRAF2 → NF-κB, PI3K/AKT",
             "evidence": "Pro-survival signaling"},
        ],
    },
    {
        "ligand_aliases": ["il-1", "il1", "il-1beta", "il-1β", "il1b", "interleukin-1"],
        "receptors": [
            {"name": "IL-1R1 (IL1R1)", "class": "Cytokine/Immune",
             "pathway": "IL-1R1 → MyD88 → IRAK → NF-κB, MAPK/JNK/p38",
             "evidence": "IL-1/IL-1R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["il-2", "il2", "interleukin-2"],
        "receptors": [
            {"name": "IL-2Rα/β/γc (IL2RA/IL2RB/IL2RG)", "class": "Cytokine/Immune",
             "pathway": "JAK1/JAK3 → STAT5, PI3K/AKT, MAPK/ERK",
             "evidence": "IL-2/IL-2R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["il-4", "il4", "interleukin-4"],
        "receptors": [
            {"name": "IL-4Rα/γc (IL4R/IL2RG)", "class": "Cytokine/Immune",
             "pathway": "JAK1/JAK3 → STAT6, IRS → PI3K/AKT",
             "evidence": "IL-4/IL-4R type I signaling"},
        ],
    },
    {
        "ligand_aliases": ["il-10", "il10", "interleukin-10"],
        "receptors": [
            {"name": "IL-10R1/IL-10R2 (IL10RA/IL10RB)", "class": "Cytokine/Immune",
             "pathway": "JAK1/TYK2 → STAT3",
             "evidence": "IL-10/IL-10R anti-inflammatory signaling"},
        ],
    },
    {
        "ligand_aliases": ["il-17", "il17", "il-17a", "interleukin-17"],
        "receptors": [
            {"name": "IL-17RA/IL-17RC (IL17RA/IL17RC)", "class": "Cytokine/Immune",
             "pathway": "IL-17R → Act1/TRAF6 → NF-κB, C/EBP",
             "evidence": "IL-17/IL-17R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["ifn-gamma", "ifnγ", "ifn-γ", "ifng", "interferon gamma"],
        "receptors": [
            {"name": "IFNGR1/IFNGR2 (IFNGR1/IFNGR2)", "class": "Cytokine/Immune",
             "pathway": "JAK1/JAK2 → STAT1",
             "evidence": "IFNγ/IFNGR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["ifn-alpha", "ifnα", "ifn-α", "ifna", "interferon alpha", "ifn-beta", "ifnβ", "ifn-β", "ifnb", "interferon beta", "type i interferon"],
        "receptors": [
            {"name": "IFNAR1/IFNAR2 (IFNAR1/IFNAR2)", "class": "Cytokine/Immune",
             "pathway": "JAK1/TYK2 → STAT1/STAT2 → ISGF3",
             "evidence": "Type I IFN canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["tgf-beta", "tgfβ", "tgf-β", "tgfb", "tgfb1", "tgf-beta1", "transforming growth factor beta"],
        "receptors": [
            {"name": "TGFβR2/TGFβR1 (TGFBR2/TGFBR1/ALK5)", "class": "TGFβ",
             "pathway": "TGFβR → SMAD2/3 → SMAD4, non-SMAD: MAPK, PI3K",
             "evidence": "TGFβ/TGFβR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["bmp2", "bmp-2", "bone morphogenetic protein 2"],
        "receptors": [
            {"name": "BMPR1A/BMPR2 (ALK3/BMPR2)", "class": "TGFβ",
             "pathway": "BMPR → SMAD1/5/8 → SMAD4",
             "evidence": "BMP/BMPR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["bmp4", "bmp-4", "bone morphogenetic protein 4"],
        "receptors": [
            {"name": "BMPR1A/BMPR2 (ALK3/BMPR2)", "class": "TGFβ",
             "pathway": "BMPR → SMAD1/5/8 → SMAD4",
             "evidence": "BMP/BMPR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["bmp7", "bmp-7", "bone morphogenetic protein 7", "op-1"],
        "receptors": [
            {"name": "BMPR1B/ACVR2A (ALK6/ActRIIA)", "class": "TGFβ",
             "pathway": "BMPR → SMAD1/5/8 → SMAD4",
             "evidence": "BMP7 preferential receptor"},
        ],
    },
    {
        "ligand_aliases": ["activin", "activin a", "inhba"],
        "receptors": [
            {"name": "ActRIIA/ActRIIB → ALK4 (ACVR2A/ACVR2B/ACVR1B)", "class": "TGFβ",
             "pathway": "Activin → SMAD2/3 → SMAD4",
             "evidence": "Activin/ActR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["rankl", "tnfsf11", "opgl", "trance", "receptor activator of nf-kb ligand"],
        "receptors": [
            {"name": "RANK (TNFRSF11A)", "class": "Cytokine/Immune",
             "pathway": "RANK → TRAF6 → NF-κB, MAPK/JNK/p38, NFATc1",
             "evidence": "RANKL/RANK osteoclast differentiation"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 5. WNT / HEDGEHOG / NOTCH (DEVELOPMENTAL)
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["wnt3a", "wnt-3a"],
        "receptors": [
            {"name": "FZD/LRP5/6 (Frizzled/LRP5/LRP6)", "class": "Developmental",
             "pathway": "Wnt → Dvl → β-catenin stabilization → TCF/LEF",
             "evidence": "Canonical Wnt signaling"},
        ],
    },
    {
        "ligand_aliases": ["wnt5a", "wnt-5a"],
        "receptors": [
            {"name": "FZD/ROR2 (Frizzled/ROR2)", "class": "Developmental",
             "pathway": "Wnt → PCP pathway, Ca2+/NFAT, JNK",
             "evidence": "Non-canonical Wnt signaling"},
        ],
    },
    {
        "ligand_aliases": ["wnt1", "wnt-1"],
        "receptors": [
            {"name": "FZD/LRP6 (Frizzled/LRP6)", "class": "Developmental",
             "pathway": "Wnt → β-catenin → TCF/LEF",
             "evidence": "Canonical Wnt signaling"},
        ],
    },
    {
        "ligand_aliases": ["shh", "sonic hedgehog", "hedgehog"],
        "receptors": [
            {"name": "PTCH1 → SMO (Patched1 → Smoothened)", "class": "Developmental",
             "pathway": "Hh → PTCH1 relief → SMO → GLI1/2/3",
             "evidence": "Hedgehog canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["dll4", "delta-like 4", "dll1", "delta-like 1", "jagged1", "jag1", "jagged2", "jag2"],
        "receptors": [
            {"name": "NOTCH1-4 (NOTCH1/2/3/4)", "class": "Developmental",
             "pathway": "Notch → γ-secretase → NICD → CSL/RBP-Jκ → HES/HEY",
             "evidence": "Notch canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["dkk1", "dickkopf-1", "dickkopf 1"],
        "receptors": [
            {"name": "LRP5/6 + Kremen (LRP5/LRP6/KREMEN)", "class": "Developmental",
             "pathway": "DKK1 antagonizes Wnt → LRP5/6 internalization",
             "evidence": "Wnt antagonist"},
        ],
    },
    {
        "ligand_aliases": ["sclerostin", "sost"],
        "receptors": [
            {"name": "LRP5/6 (LRP5/LRP6)", "class": "Developmental",
             "pathway": "SOST antagonizes Wnt → blocks LRP5/6 co-receptor",
             "evidence": "Bone-specific Wnt antagonist; Li et al. 2005 JBC"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 6. STEROID & NUCLEAR RECEPTOR LIGANDS
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["estradiol", "e2", "17β-estradiol", "estrogen"],
        "receptors": [
            {"name": "ERα/ERβ (ESR1/ESR2)", "class": "Nuclear Receptor",
             "pathway": "ER → ERE transcription, non-genomic: PI3K/AKT, MAPK",
             "evidence": "Estrogen/ER canonical signaling"},
            {"name": "GPER1 (GPR30)", "class": "GPCR",
             "pathway": "GPER1 → Gαs → cAMP, EGFR transactivation",
             "evidence": "Membrane estrogen receptor"},
        ],
    },
    {
        "ligand_aliases": ["testosterone", "dht", "dihydrotestosterone", "androgen"],
        "receptors": [
            {"name": "AR (Androgen Receptor)", "class": "Nuclear Receptor",
             "pathway": "AR → ARE transcription, non-genomic: Src/MAPK",
             "evidence": "Androgen/AR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["dexamethasone", "dex", "cortisol", "hydrocortisone", "glucocorticoid", "prednisolone"],
        "receptors": [
            {"name": "GR (NR3C1/Glucocorticoid Receptor)", "class": "Nuclear Receptor",
             "pathway": "GR → GRE transcription, anti-inflammatory: NF-κB/AP-1 suppression",
             "evidence": "Glucocorticoid/GR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["progesterone", "p4"],
        "receptors": [
            {"name": "PR (PGR/Progesterone Receptor)", "class": "Nuclear Receptor",
             "pathway": "PR → PRE transcription, non-genomic: Src/MAPK",
             "evidence": "Progesterone/PR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["vitamin d", "vitamin d3", "calcitriol", "1,25(oh)2d3", "cholecalciferol", "1,25-dihydroxyvitamin d"],
        "receptors": [
            {"name": "VDR (Vitamin D Receptor)", "class": "Nuclear Receptor",
             "pathway": "VDR/RXR → VDRE transcription, Ca2+ homeostasis",
             "evidence": "Vitamin D/VDR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["retinoic acid", "atra", "all-trans retinoic acid", "tretinoin", "vitamin a"],
        "receptors": [
            {"name": "RARα/β/γ (RARA/RARB/RARG)", "class": "Nuclear Receptor",
             "pathway": "RAR/RXR → RARE transcription",
             "evidence": "Retinoic acid/RAR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["thyroid hormone", "t3", "triiodothyronine", "t4", "thyroxine"],
        "receptors": [
            {"name": "TRα/TRβ (THRA/THRB)", "class": "Nuclear Receptor",
             "pathway": "TR/RXR → TRE transcription",
             "evidence": "Thyroid hormone/TR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["pth", "parathyroid hormone", "pth(1-34)", "teriparatide"],
        "receptors": [
            {"name": "PTH1R (PTHR1)", "class": "GPCR",
             "pathway": "PTH1R → Gαs/cAMP/PKA, Gαq/PLCβ/PKC",
             "evidence": "PTH/PTH1R bone & kidney signaling"},
        ],
    },
    {
        "ligand_aliases": ["calcitonin", "ct"],
        "receptors": [
            {"name": "CTR (CALCR/Calcitonin Receptor)", "class": "GPCR",
             "pathway": "CTR → Gαs/cAMP/PKA",
             "evidence": "Calcitonin/CTR osteoclast inhibition"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 7. GPCR LIGANDS (CATECHOLAMINES, SEROTONIN, HISTAMINE, etc.)
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["epinephrine", "adrenaline", "norepinephrine", "noradrenaline", "isoproterenol"],
        "receptors": [
            {"name": "β-Adrenergic Receptors (ADRB1/ADRB2)", "class": "GPCR",
             "pathway": "β-AR → Gαs → cAMP/PKA, β-arrestin → MAPK",
             "evidence": "Catecholamine/β-AR canonical signaling"},
            {"name": "α-Adrenergic Receptors (ADRA1/ADRA2)", "class": "GPCR",
             "pathway": "α1-AR → Gαq/PLCβ/Ca2+; α2-AR → Gαi/cAMP↓",
             "evidence": "Catecholamine/α-AR signaling"},
        ],
    },
    {
        "ligand_aliases": ["serotonin", "5-ht", "5ht"],
        "receptors": [
            {"name": "5-HT Receptors (HTR1-7)", "class": "GPCR",
             "pathway": "5-HT → Gαi/Gαs/Gαq depending on subtype",
             "evidence": "Serotonin/5-HTR signaling family"},
        ],
    },
    {
        "ligand_aliases": ["histamine"],
        "receptors": [
            {"name": "Histamine Receptors (HRH1-4)", "class": "GPCR",
             "pathway": "H1→Gαq/Ca2+; H2→Gαs/cAMP; H3/H4→Gαi",
             "evidence": "Histamine/HR signaling family"},
        ],
    },
    {
        "ligand_aliases": ["dopamine"],
        "receptors": [
            {"name": "Dopamine Receptors (DRD1-5)", "class": "GPCR",
             "pathway": "D1-like→Gαs/cAMP; D2-like→Gαi/cAMP↓",
             "evidence": "Dopamine/DR signaling family"},
        ],
    },
    {
        "ligand_aliases": ["acetylcholine", "ach", "carbachol"],
        "receptors": [
            {"name": "Muscarinic Receptors (CHRM1-5)", "class": "GPCR",
             "pathway": "M1/3/5→Gαq/PLCβ; M2/4→Gαi/cAMP↓",
             "evidence": "ACh/mAChR signaling"},
            {"name": "Nicotinic Receptors (CHRNA/CHRNB)", "class": "Ion Channel",
             "pathway": "nAChR → Na+/Ca2+ influx → depolarization",
             "evidence": "ACh/nAChR ligand-gated ion channel"},
        ],
    },
    {
        "ligand_aliases": ["angiotensin ii", "angiotensin 2", "ang ii", "angii"],
        "receptors": [
            {"name": "AT1R (AGTR1)", "class": "GPCR",
             "pathway": "AT1R → Gαq/PLCβ/Ca2+, β-arrestin → MAPK/ERK",
             "evidence": "AngII/AT1R canonical signaling"},
            {"name": "AT2R (AGTR2)", "class": "GPCR",
             "pathway": "AT2R → Gαi, phosphatases → vasodilation",
             "evidence": "AngII/AT2R counter-regulatory signaling"},
        ],
    },
    {
        "ligand_aliases": ["endothelin", "endothelin-1", "et-1", "et1"],
        "receptors": [
            {"name": "ETAR/ETBR (EDNRA/EDNRB)", "class": "GPCR",
             "pathway": "ETR → Gαq/PLCβ/Ca2+, Gα12/13/Rho",
             "evidence": "Endothelin/ETR canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["bradykinin", "bk"],
        "receptors": [
            {"name": "B2R (BDKRB2)", "class": "GPCR",
             "pathway": "B2R → Gαq/PLCβ/Ca2+, NO/cGMP",
             "evidence": "Bradykinin/B2R canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["thrombin"],
        "receptors": [
            {"name": "PAR1 (F2R)", "class": "GPCR",
             "pathway": "PAR1 → Gαq/Gα12/13 → PLCβ/Ca2+, Rho/ROCK",
             "evidence": "Thrombin/PAR1 protease-activated signaling"},
        ],
    },
    {
        "ligand_aliases": ["atp", "extracellular atp"],
        "receptors": [
            {"name": "P2X Receptors (P2RX1-7)", "class": "Ion Channel",
             "pathway": "P2X → Na+/Ca2+ influx → depolarization, NLRP3",
             "evidence": "ATP/P2X ligand-gated ion channels"},
            {"name": "P2Y Receptors (P2RY1/2/4/6/11-14)", "class": "GPCR",
             "pathway": "P2Y → Gαq/PLCβ/Ca2+ or Gαi/cAMP↓",
             "evidence": "ATP/ADP/UTP/UDP → P2Y GPCR signaling"},
        ],
    },
    {
        "ligand_aliases": ["adenosine"],
        "receptors": [
            {"name": "Adenosine Receptors (ADORA1/2A/2B/3)", "class": "GPCR",
             "pathway": "A1/A3→Gαi; A2A/A2B→Gαs/cAMP",
             "evidence": "Adenosine/ADORA signaling family"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 8. LIPID MEDIATORS
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["pge2", "prostaglandin e2", "dinoprostone"],
        "receptors": [
            {"name": "EP1-4 (PTGER1-4)", "class": "GPCR",
             "pathway": "EP2/4→Gαs/cAMP; EP1→Gαq/Ca2+; EP3→Gαi",
             "evidence": "PGE2/EP receptor signaling"},
        ],
    },
    {
        "ligand_aliases": ["lpa", "lysophosphatidic acid"],
        "receptors": [
            {"name": "LPAR1-6 (LPAR1-6)", "class": "GPCR",
             "pathway": "LPAR → Gαi/Gαq/Gα12/13 → MAPK, Rho, Ca2+",
             "evidence": "LPA/LPAR signaling family"},
        ],
    },
    {
        "ligand_aliases": ["s1p", "sphingosine-1-phosphate", "sphingosine 1 phosphate"],
        "receptors": [
            {"name": "S1PR1-5 (S1PR1-5)", "class": "GPCR",
             "pathway": "S1PR → Gαi/Gαq/Gα12/13 → PI3K, MAPK, Rho",
             "evidence": "S1P/S1PR signaling family"},
        ],
    },
    {
        "ligand_aliases": ["leukotriene b4", "ltb4"],
        "receptors": [
            {"name": "BLT1/BLT2 (LTB4R/LTB4R2)", "class": "GPCR",
             "pathway": "BLT → Gαi → MAPK, Ca2+, chemotaxis",
             "evidence": "LTB4/BLT canonical signaling"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 9. ECM / INTEGRIN LIGANDS
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["fibronectin", "fn1"],
        "receptors": [
            {"name": "α5β1 Integrin (ITGA5/ITGB1)", "class": "Integrin",
             "pathway": "Integrin → FAK/Src → MAPK/ERK, PI3K/AKT",
             "evidence": "Fibronectin/α5β1 canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["collagen", "collagen i", "collagen type i", "col1a1"],
        "receptors": [
            {"name": "α2β1 Integrin (ITGA2/ITGB1)", "class": "Integrin",
             "pathway": "Integrin → FAK → MAPK/ERK",
             "evidence": "Collagen/α2β1 canonical signaling"},
            {"name": "DDR1/DDR2 (DDR1/DDR2)", "class": "RTK",
             "pathway": "DDR → Src, MAPK, PI3K",
             "evidence": "Discoidin domain receptors for collagen"},
        ],
    },
    {
        "ligand_aliases": ["laminin", "lama", "lamb", "lamc"],
        "receptors": [
            {"name": "α6β1/α6β4 Integrin (ITGA6/ITGB1/ITGB4)", "class": "Integrin",
             "pathway": "Integrin → FAK → PI3K/AKT, MAPK",
             "evidence": "Laminin/integrin canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["vitronectin", "vtn"],
        "receptors": [
            {"name": "αVβ3 Integrin (ITGAV/ITGB3)", "class": "Integrin",
             "pathway": "Integrin → FAK/Src → PI3K/AKT, MAPK",
             "evidence": "Vitronectin/αVβ3 canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["osteopontin", "opn", "spp1"],
        "receptors": [
            {"name": "αVβ3 Integrin (ITGAV/ITGB3)", "class": "Integrin",
             "pathway": "Integrin → FAK → PI3K/AKT, NF-κB",
             "evidence": "OPN/αVβ3 signaling in bone"},
            {"name": "CD44 (CD44)", "class": "Receptor",
             "pathway": "CD44 → Src, MAPK/ERK",
             "evidence": "OPN/CD44 alternative receptor"},
        ],
    },
    {
        "ligand_aliases": ["hyaluronic acid", "hyaluronan", "ha"],
        "receptors": [
            {"name": "CD44 (CD44)", "class": "Receptor",
             "pathway": "CD44 → Src, MAPK/ERK, PI3K/AKT",
             "evidence": "HA/CD44 canonical signaling"},
            {"name": "RHAMM (HMMR)", "class": "Receptor",
             "pathway": "RHAMM → MAPK/ERK, Src",
             "evidence": "HA/RHAMM alternative receptor"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 10. STRESS / DAMAGE SIGNALS (DAMPs)
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["hmgb1", "high mobility group box 1", "amphoterin"],
        "receptors": [
            {"name": "RAGE (AGER)", "class": "Receptor",
             "pathway": "RAGE → NF-κB, MAPK/ERK, PI3K/AKT",
             "evidence": "HMGB1/RAGE danger signaling"},
            {"name": "TLR4 (TLR4)", "class": "Cytokine/Immune",
             "pathway": "TLR4 → MyD88/TRIF → NF-κB, IRF3",
             "evidence": "HMGB1/TLR4 innate immune signaling"},
        ],
    },
    {
        "ligand_aliases": ["lps", "lipopolysaccharide", "endotoxin"],
        "receptors": [
            {"name": "TLR4/MD-2/CD14 (TLR4)", "class": "Cytokine/Immune",
             "pathway": "TLR4 → MyD88 → NF-κB, MAPK; TRIF → IRF3, IFNβ",
             "evidence": "LPS/TLR4 canonical innate immune signaling"},
        ],
    },
    {
        "ligand_aliases": ["cpg", "cpg-dna", "cpg dna", "oligodeoxynucleotide"],
        "receptors": [
            {"name": "TLR9 (TLR9)", "class": "Cytokine/Immune",
             "pathway": "TLR9 → MyD88 → NF-κB, IRF7 → IFNα",
             "evidence": "CpG/TLR9 innate immune signaling"},
        ],
    },
    {
        "ligand_aliases": ["poly(i:c)", "polyic", "poly ic", "polyi:c", "dsrna"],
        "receptors": [
            {"name": "TLR3 (TLR3)", "class": "Cytokine/Immune",
             "pathway": "TLR3 → TRIF → IRF3, NF-κB → IFNβ",
             "evidence": "dsRNA/TLR3 antiviral signaling"},
        ],
    },
    {
        "ligand_aliases": ["flagellin"],
        "receptors": [
            {"name": "TLR5 (TLR5)", "class": "Cytokine/Immune",
             "pathway": "TLR5 → MyD88 → NF-κB, MAPK",
             "evidence": "Flagellin/TLR5 innate immune signaling"},
        ],
    },
    {
        "ligand_aliases": ["h2o2", "hydrogen peroxide", "ros", "reactive oxygen species"],
        "receptors": [
            {"name": "Multiple RTKs (EGFR, PDGFR transactivation)", "class": "RTK",
             "pathway": "ROS → PTP inhibition → RTK transactivation → MAPK, PI3K",
             "evidence": "ROS-mediated receptor transactivation"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 11. CHEMOKINES
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["cxcl12", "sdf-1", "sdf1", "stromal cell-derived factor 1"],
        "receptors": [
            {"name": "CXCR4 (CXCR4)", "class": "GPCR",
             "pathway": "CXCR4 → Gαi → PI3K/AKT, MAPK/ERK, Ca2+",
             "evidence": "CXCL12/CXCR4 canonical signaling"},
        ],
    },
    {
        "ligand_aliases": ["ccl2", "mcp-1", "mcp1", "monocyte chemoattractant protein 1"],
        "receptors": [
            {"name": "CCR2 (CCR2)", "class": "GPCR",
             "pathway": "CCR2 → Gαi → PI3K, MAPK, Ca2+",
             "evidence": "CCL2/CCR2 monocyte chemotaxis"},
        ],
    },
    {
        "ligand_aliases": ["cxcl8", "il-8", "il8", "interleukin-8"],
        "receptors": [
            {"name": "CXCR1/CXCR2 (CXCR1/CXCR2)", "class": "GPCR",
             "pathway": "CXCR1/2 → Gαi → PI3K, MAPK, Ca2+",
             "evidence": "IL-8/CXCR1/2 neutrophil chemotaxis"},
        ],
    },
    {
        "ligand_aliases": ["ccl5", "rantes"],
        "receptors": [
            {"name": "CCR5 (CCR5)", "class": "GPCR",
             "pathway": "CCR5 → Gαi → PI3K, MAPK, Ca2+",
             "evidence": "CCL5/CCR5 T-cell chemotaxis"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 12. DEATH LIGANDS / UBIQUITIN-RELATED
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["trail", "tnfsf10", "apo2l"],
        "receptors": [
            {"name": "DR4/DR5 (TNFRSF10A/TNFRSF10B)", "class": "Cytokine/Immune",
             "pathway": "DR4/5 → FADD/Caspase-8 → apoptosis; NF-κB",
             "evidence": "TRAIL/DR4/5 death receptor signaling"},
        ],
    },
    {
        "ligand_aliases": ["fasl", "fas ligand", "tnfsf6", "cd95l"],
        "receptors": [
            {"name": "FAS (TNFRSF6/CD95)", "class": "Cytokine/Immune",
             "pathway": "FAS → FADD → Caspase-8 → apoptosis",
             "evidence": "FasL/Fas death receptor signaling"},
        ],
    },
    {
        "ligand_aliases": ["cd40l", "cd40 ligand", "cd154", "tnfsf5"],
        "receptors": [
            {"name": "CD40 (TNFRSF5)", "class": "Cytokine/Immune",
             "pathway": "CD40 → TRAF2/6 → NF-κB, MAPK/JNK",
             "evidence": "CD40L/CD40 B-cell activation"},
        ],
    },

    # ═══════════════════════════════════════════════════════════════════════
    # 13. COMMON PHARMACOLOGICAL AGENTS
    # ═══════════════════════════════════════════════════════════════════════
    {
        "ligand_aliases": ["pma", "tpa", "phorbol 12-myristate 13-acetate", "phorbol ester"],
        "receptors": [
            {"name": "PKC (direct activation, no receptor)", "class": "Receptor",
             "pathway": "PMA → PKC → MAPK/ERK, NF-κB",
             "evidence": "PMA directly activates PKC (DAG mimetic)"},
        ],
    },
    {
        "ligand_aliases": ["ionomycin"],
        "receptors": [
            {"name": "Ca2+ ionophore (no receptor)", "class": "Ion Channel",
             "pathway": "Ca2+ influx → Calcineurin/NFAT, CaMK",
             "evidence": "Ionomycin is a Ca2+ ionophore, not receptor-mediated"},
        ],
    },
    {
        "ligand_aliases": ["rapamycin", "sirolimus", "everolimus", "temsirolimus"],
        "receptors": [
            {"name": "FKBP12 → mTORC1 (FKBP1A/MTOR)", "class": "Receptor",
             "pathway": "Rapamycin/FKBP12 → mTORC1 inhibition → S6K↓, 4E-BP1↓",
             "evidence": "Rapamycin/FKBP12/mTOR allosteric inhibition"},
        ],
    },
    {
        "ligand_aliases": ["forskolin", "fsk"],
        "receptors": [
            {"name": "Adenylyl Cyclase (direct activation)", "class": "Receptor",
             "pathway": "Forskolin → AC → cAMP↑ → PKA",
             "evidence": "Forskolin directly activates adenylyl cyclase"},
        ],
    },
]


def lookup_receptors_for_treatment(treatment_text: str) -> list[dict]:
    """
    Given a treatment text (e.g., "irisin 100ng/ml" or "EGF + TNFα"),
    find matching ligands and return their known receptors.

    Returns a list of dicts with keys:
        ligand, receptor_name, receptor_class, pathway, evidence, source
    """
    if not treatment_text or not isinstance(treatment_text, str):
        return []

    text_lower = treatment_text.lower().strip()
    results = []
    seen_receptors = set()

    for entry in LIGAND_RECEPTOR_DB:
        for alias in entry["ligand_aliases"]:
            # Match whole word or substring (for compound treatments like "irisin 100ng/ml")
            if alias in text_lower:
                for rec in entry["receptors"]:
                    rec_key = rec["name"]
                    if rec_key not in seen_receptors:
                        seen_receptors.add(rec_key)
                        results.append({
                            "ligand": alias,
                            "receptor_name": rec["name"],
                            "receptor_class": rec["class"],
                            "pathway": rec.get("pathway", ""),
                            "evidence": rec.get("evidence", ""),
                            "source": "treatment_context",
                        })
                break  # Found matching alias, no need to check others for this entry

    return results
