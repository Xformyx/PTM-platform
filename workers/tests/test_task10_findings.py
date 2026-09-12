"""Synthetic evidence comparisons, not retrieved scientific findings."""
from report_generation.core.reader_authoring import build_authoring_packet, deterministic_authoring_plan, render_reader_section_fallback, validate_and_repair_sections
from test_task10_joint_patterns import supported_row


def finding_state(count=1):
    return {"vector_plot_raw_data": [supported_row(precursor=f"form-{i}", gene=f"CANDIDATE{i}", condition=t)
                                    for i in range(count) for t in ("5min", "40min")]}


def test_t10_09_unknown_localization_and_no_call_preserve_observation():
    packet = build_authoring_packet(finding_state())
    finding = deterministic_authoring_plan(packet)["key_findings"][0]
    assert finding["claim_scope"] == "descriptive_pattern"
    assert finding["mechanistic_status"] == "not_evaluated"
    assert finding["literature_comparison"]["status"] == "retrieval_unavailable"
    assert finding["measurement_unit"] == "candidate_residue_modified_precursor_feature"
    assert finding["biological_reproducibility_claim_allowed"] is False
    assert finding["pattern_q_value"] is None


def test_t10_10_opposing_forms_remain_separate_and_order_invariant():
    state = finding_state(2)
    for row in state["vector_plot_raw_data"]:
        row["gene"] = "SAME_PARENT"
        if row["precursor_id"] == "form-1":
            row["ptm_protein_adjusted_log2fc"] = -1.
    first = deterministic_authoring_plan(build_authoring_packet(state))
    state["vector_plot_raw_data"].reverse()
    second = deterministic_authoring_plan(build_authoring_packet(state))
    assert first["key_findings"] == second["key_findings"]
    assert len(first["key_findings"]) == 2
    assert all(f["dependencies"]["parent_protein_ids"] == ["PG1"] for f in first["key_findings"])
    assert all(f["opposing_feature_ids"] for f in first["key_findings"])
    assert first["finding_selection_audit"]["independent_sample_count"] is None


def test_t10_11_literature_agreement_and_opposition_keep_source_and_conditions():
    state = finding_state()
    fid = deterministic_authoring_plan(build_authoring_packet(state))["key_findings"][0]["reader_feature_id"]
    refs = [{"title": "Synthetic fixture for literature comparison", "doi": "10.1000/task10-fixture", "authors": "Fixture", "year": "2026",
             "feature_comparisons": [{"reader_feature_id": fid, "relationship": relation,
                                      "observation": "A sustained adjusted contrast was measured.",
                                      "external_finding": "Synthetic comparison only.",
                                      "condition_differences": ["different cell model", "different sampling window"]}
                                     for relation in ("known_agreement", "disagreement")]}]
    packet = build_authoring_packet(state, references=refs)
    comparison = deterministic_authoring_plan(packet)["key_findings"][0]["literature_comparison"]
    assert {c["relationship"] for c in comparison["comparisons"]} == {"known_agreement", "disagreement"}
    assert all(c["claim_scope"] == "literature_context" and c["citation_id"] for c in comparison["comparisons"])
    assert all(c["condition_differences"] for c in comparison["comparisons"])
    prose, audit = validate_and_repair_sections({"discussion": render_reader_section_fallback("discussion", packet)}, packet)
    assert "agreed with" in prose["discussion"] and "differed from" in prose["discussion"]
    assert "different cell model" in prose["discussion"]
    assert not any("withhold_uncited_literature_sentence" in e["validator_action"] for e in audit["entries"])
    empty = build_authoring_packet({**state, "literature_retrieval_status": "completed"}, references=[])
    assert deterministic_authoring_plan(empty)["key_findings"][0]["literature_comparison"]["status"] == "not_explained_by_retrieved_evidence"


def test_t10_12_finding_count_follows_available_evidence():
    for n in (1, 3):
        plan = deterministic_authoring_plan(build_authoring_packet(finding_state(n)))
        assert len(plan["key_findings"]) == n
        assert len({f["reader_feature_id"] for f in plan["key_findings"]}) == n
