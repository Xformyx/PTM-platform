from ptm_shared.temporal_feature_input import build_temporal_feature_inputs, bind_modules_to_features


def row(precursor, value, condition="5min", **kwargs):
    return dict(gene="G", position="S1", precursor_id=precursor,
                condition=condition, log2fc=value, q_value=.01, **kwargs)


def test_opposing_forms_and_statistics_survive_row_order_change():
    rows = [row("P1", 1), row("P2", -3)]
    forward = build_temporal_feature_inputs(rows)
    assert forward == build_temporal_feature_inputs(rows[::-1])
    assert len(forward["ptm_timeseries"]) == 2
    assert sorted(ts["5min"] for ts in forward["ptm_timeseries"].values()) == [-3, 1]
    site = forward["sites"]["G_S1"]
    assert site["aggregation_rule"] == "none_feature_level_only"
    assert site["opposite_form_conditions"] == ["5min"]
    assert all(q["5min"] == .01 for q in forward["ptm_qvalues"].values())
    modules = bind_modules_to_features([{"kinase": "K", "ptms": [{"gene": "G", "position": "S1"}]}], forward)
    assert {m["temporal_feature_key"] for m in modules[0]["ptms"]} == set(forward["features"])


def test_same_precursor_across_times_and_zero_vs_missing():
    packet = build_temporal_feature_inputs([row("P1", 1, "1min"), row("P1", None), row("P1", 0, "15min")])
    assert len(packet["features"]) == 1
    key = next(iter(packet["features"]))
    assert packet["ptm_timeseries"][key] == {"1min": 1., "15min": 0.}
    assert packet["features"][key]["missing_conditions"] == ["5min"]


def test_occupancy_not_lost_when_adjusted_axis_unavailable():
    packet = build_temporal_feature_inputs([row("P1", None, occupancy_logit_delta=2., occupancy_q_value=None, pair_quality_tier="O2")])
    key = next(iter(packet["features"]))
    assert packet["ptm_timeseries"][key] == {}
    assert packet["occupancy_timeseries"][key] == {"5min": 2.}
    assert packet["occupancy_qvalues"][key] == {"5min": None}


def test_conflicting_duplicate_is_withheld_instead_of_arbitrary_first_or_last():
    rows = [row("P1", 1), row("P1", 3)]
    packet = build_temporal_feature_inputs(rows)
    assert packet == build_temporal_feature_inputs(rows[::-1])
    key = next(iter(packet["features"]))
    assert packet["ptm_timeseries"][key] == {}
    assert packet["features"][key]["measurements"]["5min"]["status"] == "conflicting_duplicate_feature_condition"


def test_duplicate_export_rows_do_not_multiply_feature_support():
    packet = build_temporal_feature_inputs([row("P1", 1)] * 3)
    assert len(packet["features"]) == 1
    assert len(packet["ptm_timeseries"]) == 1


def test_de_novo_representation_boundary_is_per_feature():
    rows = [row("P1", 1, "1min", is_de_novo_representation=False),
            row("P1", 2, is_de_novo_representation=True),
            row("P2", -3, is_de_novo_representation=False)]
    packet = build_temporal_feature_inputs(rows)
    by_precursor = {feature["precursor_id"]: key for key, feature in packet["features"].items()}
    assert packet["ptm_timeseries"][by_precursor["P1"]] == {"5min": 2.}
    assert packet["ptm_timeseries"][by_precursor["P2"]] == {"5min": -3.}
    assert not packet["ptm_is_denovo"][by_precursor["P2"]]


def test_legacy_missing_identity_is_audited_not_assumed_unique():
    packet = build_temporal_feature_inputs([row("", 1)])
    assert not packet["ptm_timeseries"]
    assert packet["rejected_rows"][0]["reason"] == "precursor_identity_unavailable"


def test_ledger_wave_membership_does_not_transfer_between_precursors():
    from ptm_shared.kinase_evidence_ledger import build_feature_provenance_ledger, attach_temporal_context
    rows = [row("P1", 1), row("P2", -3)]
    packet = build_temporal_feature_inputs(rows)
    selected = next(key for key, identity in packet["features"].items() if identity["precursor_id"] == "P1")
    ledger = attach_temporal_context(build_feature_provenance_ledger(rows, ["5min"]),
                                    {"waves": [{"members": [selected]}]}, {}, packet["features"])
    by_precursor = {r["identity_provenance"]["precursor_id"]: r for r in ledger["feature_records"]}
    assert by_precursor["P1"]["temporal_feature_key"] == selected
    assert by_precursor["P1"]["temporal_evidence"]["status"] == "static_wave_member_observational_context"
    assert by_precursor["P2"]["temporal_evidence"]["status"] == "not_qualified_for_static_wave_context"
