import pytest

from report_generation.core.measured_feature_cards import build_quantitation_comparison_cards
from report_generation.core.reader_authoring import format_authoring_packet_for_llm, validate_and_repair_sections
from test_report_review_quantitation import raw_row


def packet():
    cards = build_quantitation_comparison_cards({"vector_plot_raw_data": [
        raw_row(), raw_row(condition="5min", precursor="charge3", PTM_Unadjusted_Log2FC=-.296,
                           PTM_Relative_Log2FC=-.103)]})
    return {"reader_cards": cards, "section_claim_budget": {"results": ["O1"]},
            "figure_cards": [{"figure_key": "heatmap", "figure_label": "Figure 1",
                              "selected_reader_feature_ids": [cards[0]["feature_identity"]["reader_feature_id"]]}]}


def first_id(p):
    return next(c["feature_identity"]["reader_feature_id"] for c in p["reader_cards"] if c["condition"] == "1min")


@pytest.mark.parametrize("claim", [
    "The same AARSD1 S88 feature changed from +0.141 at 1min to -0.296 at 5min.",
    "AARSD1 S88 {id} at 1min had an unadjusted PTM contrast of +9.999.",
    "AARSD1 S88 {id} at 5min had an unadjusted PTM contrast of +0.141.",
    "AARSD1 S88 {id} at 1min had a protein-adjusted PTM contrast of +0.141.",
])
def test_invalid_identity_condition_axis_and_number_are_blocked(claim):
    p = packet()
    text = claim.format(id=first_id(p))
    result, audit = validate_and_repair_sections({"results": text}, p)
    assert text != result["results"]
    assert any("quantitative" in reason or "precursor" in reason
               for entry in audit["entries"] for reason in entry["reason_code"])


def test_explicitly_distinct_precursors_and_exact_values_are_allowed():
    p = packet()
    other = next(c["feature_identity"]["reader_feature_id"] for c in p["reader_cards"] if c["condition"] == "5min")
    text = (f"Two distinct AARSD1 S88 precursors were measured: {first_id(p)} at 1min had an unadjusted PTM contrast of +0.141; "
            f"{other} at 5min had an unadjusted PTM contrast of -0.296.")
    result, audit = validate_and_repair_sections({"results": text}, p)
    assert result["results"] == text
    assert audit["removed_sentence_count"] == 0


def test_prompt_contains_axis_statistics_identity_and_figure_membership():
    p = packet()
    text = format_authoring_packet_for_llm(p, "results")
    assert first_id(p) in text
    for field in ("condition", "axis", "measurement_unit", "localization", '"q": 0.001', '"p": 0.0002'):
        assert field in text
    assert "selected_reader_feature_ids" in text


def test_measured_feature_must_belong_to_cited_figure():
    p = packet()
    p["figure_cards"][0]["selected_reader_feature_ids"] = []
    text = f"Figure 1 shows AARSD1 S88 {first_id(p)} at 1min with unadjusted PTM contrast +0.141."
    result, audit = validate_and_repair_sections({"results": text}, p)
    assert not result["results"]
    assert "quantitative_figure_membership_mismatch" in audit["entries"][0]["reason_code"]


def test_structured_tokens_resolve_exact_source_and_reject_rebinding():
    import json
    from report_generation.core.quantitative_claims import decode_sentence_draft, value_token_catalog
    p = packet()
    key, ref = next((k, v) for k, v in value_token_catalog(p).items() if v["axis"] == "adjusted")
    item = {"text": "{{" + key + "}}.", "scope": "observation", "paragraph": 1,
            "value_tokens": [key], "evidence_ids": [ref["evidence_id"]], "figure_keys": []}
    text, audit = decode_sentence_draft(json.dumps({"sentences": [item]}), p)
    assert f"{ref['value']:+.3f}" in text
    assert audit[0]["references"][0]["q"] == .001
    assert audit[0]["references"][0]["p"] == .0002
    for bad in ("At 99min, ", "Unadjusted PTM: ", "Value +9.999: "):
        result, audit = decode_sentence_draft(json.dumps({"sentences": [{**item, "text": bad + item["text"]}]}), p)
        assert not result


def test_structured_figure_citation_allows_only_its_selected_feature():
    import json
    from report_generation.core.quantitative_claims import decode_sentence_draft, value_token_catalog
    p = packet()
    key, ref = next(iter(value_token_catalog(p).items()))
    p["figure_cards"][0]["selected_reader_feature_ids"] = [ref["feature_id"]]
    item = {"text": "Figure 1 shows that {{" + key + "}}.", "scope": "observation", "paragraph": 1,
            "value_tokens": [key], "evidence_ids": [ref["evidence_id"]], "figure_keys": ["heatmap"]}
    draft = json.dumps({"sentences": [item]})
    assert decode_sentence_draft(draft, p)[0]
    p["figure_cards"][0]["selected_reader_feature_ids"] = []
    assert not decode_sentence_draft(draft, p)[0]


def test_unadjusted_significance_cannot_borrow_adjusted_q():
    p = packet()
    text = f"AARSD1 S88 {first_id(p)} at 1min had a significant unadjusted PTM contrast of +0.141."
    result, audit = validate_and_repair_sections({"results": text}, p)
    assert not result["results"]


def test_descriptive_adjustment_difference_is_not_a_statistical_test():
    p = packet()
    text = f"AARSD1 S88 {first_id(p)} at 1min changed significantly after protein adjustment beyond the ±0.15 descriptive tolerance."
    result, audit = validate_and_repair_sections({"results": text}, p)
    assert not result["results"]


@pytest.mark.parametrize("text", [
    "At 1min the unadjusted PTM contrast was +9.999.",
    "At 1min the unadjusted PTM contrast was 999.",
    "At 1min the unadjusted PTM contrast was +9.999 [EVID:quantitation.comparison.2].",
])
def test_omitting_identity_does_not_bypass_numeric_validation(text):
    result, _ = validate_and_repair_sections({"results": text}, packet())
    assert not result["results"]
