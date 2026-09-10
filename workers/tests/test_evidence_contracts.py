import pytest

from ptm_shared.evidence_contracts import (
    EvaluationStatus,
    ObservationStatus,
    OutcomeClass,
    build_evidence_envelope,
    build_measurement_provenance,
)
from ptm_shared.kinase_evidence_ledger import build_feature_provenance_ledger


def test_observed_feature_can_remain_observed_when_statistical_evaluation_is_not_evaluable():
    envelope = build_evidence_envelope(
        observation_status=ObservationStatus.observed_complete,
        measurement_unit="modified_precursor_feature",
        value_ids=("feature_1",),
        evaluation_status=EvaluationStatus.not_evaluable,
        reason_codes=("insufficient_replication",),
        outcome_class=OutcomeClass.unavailable,
        maximum_tier="O1",
        allowed_predicates=("observed", "quantified"),
        forbidden_predicates=("significantly changed", "caused"),
    )

    assert envelope["observation"]["status"] == "observed_complete"
    assert envelope["evaluation"]["status"] == "not_evaluable"
    assert envelope["outcome"]["class"] == "unavailable"
    assert envelope["claim_scope"]["maximum_tier"] == "O1"


def test_unevaluated_evidence_cannot_carry_a_passed_outcome():
    with pytest.raises(ValueError, match="unevaluated_with_assertive_outcome"):
        build_evidence_envelope(
            observation_status="observed_complete",
            measurement_unit="modified_precursor_feature",
            evaluation_status="not_evaluable",
            reason_codes=("insufficient_replication",),
            outcome_class="passed",
            maximum_tier="O1",
        )


def test_measurement_provenance_keeps_multi_modification_and_localization_separate():
    provenance = build_measurement_provenance({
        "Protein.Group": "P12345;Q99999",
        "Precursor.Id": "precursor_1",
        "Modified.Sequence": "AS(UniMod:21)TY(UniMod:21)K",
        "PTM_Positions": "S2;Y4",
        "Localization.Probability": 0.92,
        "FASTA_Taxonomy_ID": "10116",
    })

    assert provenance["modification_form"]["target_modification_count"] == 2
    assert provenance["localization_evidence"]["status"] == "recorded_class_I_or_higher"
    assert provenance["protein_mapping"]["status"] == "ambiguous_group"
    assert provenance["reader_measurement_unit"] == "multi_modified_precursor_feature"
    assert provenance["aggregation_provenance"]["member_feature_ids"] == ["precursor_1"]


def test_localized_site_reader_unit_requires_single_modification_single_accession_and_class_i_localization():
    provenance = build_measurement_provenance({
        "Protein.Group": "P12345",
        "Precursor.Id": "precursor_2",
        "Modified.Sequence": "AS(UniMod:21)TYK",
        "PTM_Position": "S2",
        "Localization.Probability": 0.81,
    })

    assert provenance["reader_measurement_unit"] == "localized_ptm_site_feature"
    assert provenance["protein_mapping"]["status"] == "unique_accession"


def test_multiple_candidate_residues_do_not_inflate_explicit_modification_count():
    provenance = build_measurement_provenance({
        "Protein.Group": "P12345",
        "Precursor.Id": "precursor_ambiguous_site",
        "Modified.Sequence": "AS(UniMod:21)TYK",
        "PTM_Positions": "S2;T3",
    })

    assert provenance["modification_form"]["target_modification_count"] == 1
    assert provenance["localization_evidence"]["candidate_residue_count"] == 2
    assert provenance["reader_measurement_unit"] == "candidate_residue_modified_precursor_feature"


def test_feature_ledger_adds_measurement_and_evidence_contracts_without_removing_legacy_identity():
    ledger = build_feature_provenance_ledger(
        [{
            "gene": "GENE1",
            "PTM_Position": "S2",
            "Protein.Group": "P12345",
            "Precursor.Id": "precursor_3",
            "Modified.Sequence": "AS(UniMod:21)TYK",
            "Condition": "5min",
            "log2fc": 1.0,
        }],
        ["5min", "15min"],
    )
    record = ledger["feature_records"][0]

    assert record["feature_unit"] == "modified_precursor_feature_collapsed_across_declared_conditions"
    assert "identity_provenance" in record
    assert record["measurement_provenance"]["modification_form"]["target_modification_count"] == 1
    assert record["evidence_envelope"]["observation"]["status"] == "observed_partial"
    assert record["evidence_envelope"]["evaluation"]["status"] == "not_evaluable"
