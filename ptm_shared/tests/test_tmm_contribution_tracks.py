from ptm_shared.tmm_multikinase_integration import (
    build_tmm_site_contribution_matrix,
    canonical_ptm_key,
)


def test_canonical_ptm_key_collapses_legacy_display_alias() -> None:
    assert canonical_ptm_key("Akt1 s473") == "AKT1_S473"
    assert canonical_ptm_key("AKT1_S473") == "AKT1_S473"
    assert canonical_ptm_key("GENE_S12;T13") == "GENE_S12/T13"


def test_contribution_matrix_emits_one_canonical_record_per_site() -> None:
    scores = {
        "AKT1": {
            "contribution_details": [
                {"ptm_key": "FOXO1_S256", "contribution_ratio": 0.75},
                {"ptm_key": "FOXO1 S256", "contribution_ratio": 0.75},
            ]
        },
        "SGK1": {
            "contribution_details": [
                {"ptm_key": "FOXO1_S256", "contribution_ratio": 0.25},
            ]
        },
    }
    matrix = build_tmm_site_contribution_matrix(scores)
    assert list(matrix) == ["FOXO1_S256"]
    assert matrix["FOXO1_S256"] == {"AKT1": 0.75, "SGK1": 0.25}
