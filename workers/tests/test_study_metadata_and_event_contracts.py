from report_generation.core.study_metadata import build_study_metadata_contract, repair_unrecorded_metadata_claim
from report_generation.core.reader_authoring import build_authoring_packet, validate_and_repair_sections
from ptm_shared.temporal_precedence_output import build_temporal_precedence_output
from ptm_shared.replicate_event_adapter import EventRecord, EventStatus, StudyTemporalContext


def test_metadata_contract_does_not_infer_species_from_cell_model_label():
    contract = build_study_metadata_contract({"cell_type": "recorded-cell-model"})
    repaired, changed = repair_unrecorded_metadata_claim(
        "The CHO cell line recorded-cell-model was analysed.", contract
    )
    assert contract["lineage_or_species_inference_allowed"] is False
    assert changed is True
    assert "CHO" not in repaired


def test_event_specific_summary_keeps_right_censored_exit_distinct_from_onset():
    record = EventRecord(
        site_key="FEATURE_A",
        event_status=EventStatus.right_censored,
        onset_event={"observation_status": "observed", "censoring_type": "none"},
        peak_event={"observation_status": "observed", "censoring_type": "none"},
        exit_event={"observation_status": "not_resolved", "censoring_type": "right"},
    )
    context = StudyTemporalContext(
        study_id="generic",
        time_unit_label="minutes",
        nominal_grid_interval_minutes=5.0,
        gp_length_scale_min_minutes=10.0,
        synchrony_tau_minutes=5.0,
        gp_length_scale_source="synthetic test fixture",
        chemical_holdout_description="not applicable to contract fixture",
        pre_registered=True,
    )
    output = build_temporal_precedence_output(
        {"FEATURE_A": record}, {"waves": [{"wave_id": "cluster-1", "members": ["FEATURE_A"]}]}, context
    )
    summary = output["summary"]["event_specific_censoring"]
    assert summary["onset"]["observation_status"]["observed"] == 1
    assert summary["exit"]["censoring_type"]["right"] == 1


def test_validator_rewrites_candidate_residue_phosphosite_claim_without_localization_evidence():
    state = {
        "experimental_context": {"cell_type": "recorded-cell-model", "treatment": "compound"},
        "vector_plot_raw_data": [
            {
                "gene": "GENEA", "position": "S10", "condition": "5min",
                "Precursor.Id": "precursor-a", "Modified.Sequence": "AA(UniMod:21)BB",
                "ptm_unadjusted_log2fc": 0.7, "ptm_protein_adjusted_log2fc": 0.5,
                "protein_log2fc": 0.2,
            },
            {
                "gene": "GENEA", "position": "S10", "condition": "15min",
                "Precursor.Id": "precursor-a", "Modified.Sequence": "AA(UniMod:21)BB",
                "ptm_unadjusted_log2fc": 0.4, "ptm_protein_adjusted_log2fc": 0.3,
                "protein_log2fc": 0.1,
            },
        ],
    }
    packet = build_authoring_packet(state, temporal_evidence_packet={}, biological_synthesis_packet={})
    repaired, audit = validate_and_repair_sections(
        {"results": "GENEA S10 phosphosite increased in the recorded cell model."}, packet
    )
    assert "candidate residue annotation S10" in repaired["results"]
    assert "phosphosite" not in repaired["results"].lower()
    assert any("candidate_residue_not_localized_site" in entry["reason_code"] for entry in audit["entries"])
