from ptm_shared.quantitation_estimator_contract import (
    CONTRACT_VERSION,
    DETERMINISTIC_METHODS_PARAGRAPH,
    build_quantitation_estimator_contract,
)
from report_generation.core.reader_authoring import validate_and_repair_sections


def test_estimator_contract_distinguishes_mean_of_ratios_from_difference_of_contrasts() -> None:
    contract = build_quantitation_estimator_contract()
    assert contract["contract_version"] == CONTRACT_VERSION
    assert contract["estimators"]["protein_adjusted"]["estimator_id"].startswith(
        "protein_adjusted_mean_of_sample_ptm_to_protein_ratios"
    )
    assert "not generally identical" in contract["non_equivalence"]
    assert "sample's normalized PTM-to-linked-protein ratio" in DETERMINISTIC_METHODS_PARAGRAPH


def test_methods_validator_replaces_subtraction_formula_with_immutable_contract() -> None:
    packet = {
        "contract_version": "test",
        "section_claim_budget": {"methods": ["O1", "O2"]},
        "reader_cards": [],
        "study_metadata_contract": {},
    }
    sections, audit = validate_and_repair_sections(
        {
            "methods": (
                "The protein-adjusted contrast was calculated by subtracting the linked protein Log2FC "
                "from the independent unadjusted PTM Log2FC."
            )
        },
        packet,
    )
    assert DETERMINISTIC_METHODS_PARAGRAPH in sections["methods"]
    assert "subtracting the linked protein Log2FC" not in sections["methods"]
    assert any(
        "replace_quantitation_estimator_with_immutable_contract" in entry["validator_action"]
        for entry in audit["entries"]
    )
