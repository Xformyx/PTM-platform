"""Operational memory path for Order 80-scale preprocessing. Scores unchanged."""

try:
    from workers.preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer
    from workers.tests.test_observation_denominator_contract import analyzer_for, quantify
    from workers.tests.test_dual_track_ptm_quantification import _analyzer, _pair_matrix
except ImportError:  # container PYTHONPATH=/app:/opt
    from preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer
    from test_observation_denominator_contract import analyzer_for, quantify
    from test_dual_track_ptm_quantification import _analyzer, _pair_matrix


def test_mapping_assertion_reuses_cache_and_candidate_index():
    analyzer = PTMQuantificationAnalyzer.__new__(PTMQuantificationAnalyzer)
    analyzer.target_ptms = {"21": "Phosphorylation"}
    analyzer.ptm_mode_config = {"unimod_id": "21"}
    analyzer.fasta_dict = {"P1": "MASKASK"}
    analyzer.fasta_reference_candidates = {"P1": ["MASKASK"]}
    analyzer._mapping_cache = {}
    first = analyzer._mapping_assertion("P1", "AS(UniMod:21)K", "Phosphorylation")
    second = analyzer._mapping_assertion("P1", "AS(UniMod:21)K", "Phosphorylation")
    assert first is second
    assert first["candidates"]
    assert analyzer._mapping_references() is analyzer.fasta_reference_candidates


def test_unadjusted_and_site_level_still_match_existing_contract():
    observations, adjusted, vector = quantify(analyzer_for([100, 200, 400], [1000, 1000, 1000]))
    assert len(observations) == 3
    assert vector.iloc[0]["PTM_Unadjusted_Log2FC"] > 0
    assert adjusted.iloc[0]["Log2FC"] == vector.iloc[0]["PTM_ProteinAdjusted_Log2FC"]


def test_gene_map_does_not_use_iterrows_on_duplicate_groups():
    analyzer = PTMQuantificationAnalyzer.__new__(PTMQuantificationAnalyzer)
    analyzer.pg_matrix = _pair_matrix().assign(Genes="GENE1")
    analyzer.pr_matrix = analyzer.pg_matrix.copy()
    analyzer._build_diann_gene_map()
    assert analyzer.diann_genes["P12345"] == "GENE1"


def test_gene_map_skips_float_nan_genes_like_iterrows():
    import numpy as np
    import pandas as pd

    analyzer = PTMQuantificationAnalyzer.__new__(PTMQuantificationAnalyzer)
    analyzer.pg_matrix = pd.DataFrame({
        "Protein.Group": ["P1", "P2"],
        "Genes": pd.array(["GENE1", np.nan], dtype="string"),
    })
    analyzer.pr_matrix = analyzer.pg_matrix.copy()
    analyzer._build_diann_gene_map()
    assert analyzer.diann_genes == {"P1": "GENE1"}


def test_paired_occupancy_still_qualified_after_lookup_helpers():
    matrix = _pair_matrix()
    analyzer = _analyzer(matrix)
    occupancy, audit = analyzer.calculate_paired_occupancy(matrix.iloc[[0]])
    assert len(occupancy) == 4
    assert audit.iloc[0]["Pair_Status"] == "qualified_apparent_paired_occupancy"
