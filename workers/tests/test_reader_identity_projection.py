import re

from report_generation.core.measured_feature_cards import build_feature_observation_cards
from report_generation.core.quantitative_claims import decode_sentence_draft, render_value_record, value_token_catalog
from report_generation.core.reader_authoring import (
    audit_named_feature_ceiling,
    audit_report_output_correctness,
    build_authoring_packet,
    deterministic_authoring_plan,
    focus_authoring_packet,
    render_reader_section_fallback,
)
from report_generation.core.report_release import resolve_report_release
from report_generation.core.section_model_packet import compose_compacted_section_prompt
from common.report_display_policy import effective_display_policy


def _vector_state(n=4):
    rows = []
    for index in range(n):
        for condition, value in (("1min", 0.4 + index * 0.1), ("15min", -0.2 + index * 0.05)):
            rows.append({
                "gene": f"GENE{index}",
                "position": f"S{index + 1}",
                "condition": condition,
                "Precursor.Id": f"PRECURSOR{index}",
                "Modified.Sequence": f"AA(UniMod:21)SEQ{index}",
                "Precursor.Charge": 2,
                "ptm_unadjusted_log2fc": value,
                "ptm_protein_adjusted_log2fc": value - 0.1,
                "protein_log2fc": 0.1,
                "ptm_unadjusted_conventional_log2fc_na": False,
            })
    return {"vector_plot_raw_data": rows}


def test_reader_summaries_and_value_tokens_do_not_leak_pf_ids():
    cards = build_feature_observation_cards(_vector_state(), maximum=4)
    packet = {"reader_cards": cards}
    catalog = value_token_catalog(packet)
    assert cards
    assert all("PF-" not in card["reader_summary"] for card in cards)
    assert all(card["feature_identity"]["reader_feature_id"].startswith("PF-") for card in cards)
    for record in catalog.values():
        rendered = render_value_record(record)
        assert "PF-" not in rendered
        assert "FEATURE-" not in rendered
        assert record["feature_id"].startswith("PF-")


def test_duplicate_display_identity_forms_are_not_merged():
    state = {
        "vector_plot_raw_data": [
            {
                "gene": "IRS1", "position": "S307", "condition": condition,
                "Precursor.Id": "FORM-A", "Modified.Sequence": "AA(UniMod:21)A",
                "Precursor.Charge": 2, "ptm_unadjusted_log2fc": value,
                "ptm_protein_adjusted_log2fc": value - 0.3, "protein_log2fc": 0.2,
                "ptm_unadjusted_conventional_log2fc_na": False,
            }
            for condition, value in (("1min", 0.8), ("15min", 0.4))
        ] + [
            {
                "gene": "IRS1", "position": "S307", "condition": condition,
                "Precursor.Id": "FORM-B", "Modified.Sequence": "AA(UniMod:21)B",
                "Precursor.Charge": 3, "ptm_unadjusted_log2fc": value,
                "ptm_protein_adjusted_log2fc": value + 0.2, "protein_log2fc": 0.2,
                "ptm_unadjusted_conventional_log2fc_na": False,
            }
            for condition, value in (("1min", -0.6), ("15min", -0.2))
        ]
    }
    cards = build_feature_observation_cards(state, maximum=4)
    assert len(cards) >= 2
    displays = [card["feature_identity"]["reader_display_identity"] for card in cards]
    assert any("form A" in label or "form B" in label for label in displays)
    assert {card["feature_identity"]["reader_feature_id"] for card in cards}


def test_oversized_audit_compacts_and_leaves_audit_unchanged():
    packet = build_authoring_packet(_vector_state(16))
    plan = deterministic_authoring_plan(packet)
    focused = focus_authoring_packet(packet, plan)
    bloated = dict(focused)
    bloated["identity_audit"] = {"rows": ["x" * 5000 for _ in range(200)]}
    bloated["exclusion_audit"] = {"rows": ["y" * 5000 for _ in range(200)]}
    prompt, trace = compose_compacted_section_prompt(bloated, "results", plan, max_chars=20_000)
    assert not re.search(r"\bPF-[A-F0-9]{8}\b", prompt)
    assert not re.search(r"\bFEATURE-[A-F0-9]{8,}\b", prompt)
    assert "xxxxx" not in prompt
    assert bloated["identity_audit"]["rows"][0].startswith("x")
    assert trace["retained_evidence_ids"]
    assert "section_model_packet" in trace
    assert trace["prompt_compaction_stage"] >= 0


def test_malformed_sibling_sentence_is_dropped_without_section_blanking():
    packet = build_authoring_packet(_vector_state(3))
    draft = (
        '{"sentences":['
        '{"text":"The recorded study frame remains the interpretation boundary.","paragraph":1,"scope":"study_rationale",'
        '"evidence_ids":[],"value_tokens":[],"figure_keys":[]},'
        '{"text":123,"paragraph":1,"scope":"observation","evidence_ids":[],"value_tokens":[],"figure_keys":[]},'
        '{"text":"These measurements remain descriptive rather than causal.","paragraph":2,"scope":"study_rationale",'
        '"evidence_ids":[],"value_tokens":[],"figure_keys":[]}'
        ']}'
    )
    prose, audit = decode_sentence_draft(draft, packet)
    assert prose
    assert any(item.get("reason_code") == "invalid_sentence_record" for item in audit)
    assert any(item.get("retained") for item in audit)


def test_role_based_fallback_avoids_not_evaluable_loops_and_pf_ids():
    packet = build_authoring_packet(_vector_state(6))
    results = render_reader_section_fallback("results", packet)
    discussion = render_reader_section_fallback("discussion", packet)
    assert "PF-" not in results and "FEATURE-" not in results
    assert "PF-" not in discussion
    assert results.lower().count("not evaluable") <= 1
    assert "next" in discussion.lower()
    assert audit_named_feature_ceiling(results, packet["reader_cards"]) == []


def test_generation_degraded_blocks_final_but_keeps_review_artifacts():
    release = resolve_report_release(
        reader_authoring_shadow=True,
        output_correctness={"status": "draft_review_required", "generation_degraded": True, "reason_codes": [], "review_reason_codes": ["generation_degraded"]},
        artifact_manifest={"status": "validated", "report_eligible": True, "artifacts": [{"role": "markdown", "exists": True}], "render_status": "recorded"},
        phase="pre_export",
    )
    assert release["generation_degraded"] is True
    assert release["publish_as_final"] is False
    assert release["review_artifact_available"] is True


def test_shadow_display_policy_is_isolated_from_standard():
    shadow = effective_display_policy("shadow")
    standard = effective_display_policy("standard")
    assert shadow["compaction_stage_count"] == 6
    assert standard["shadow_compaction_enabled"] is False
    assert shadow["policy_sha256"] != standard["policy_sha256"]


def test_main_body_pf_leak_is_a_correctness_violation():
    body = (
        "## Abstract\n\nObserved precursor contrasts were retained for comparison.\n\n"
        "## Introduction\n\nThe study asks which recorded PTM and protein contrasts change together.\n\n"
        "## Methods\n\nIndependent unadjusted, protein, and adjusted contrasts were kept separate.\n\n"
        "## Results\n\nPF-ABCDEF12 showed a recorded contrast of +0.20 on the unadjusted PTM contrast.\n\n"
        "## Discussion\n\nThe observed contrast remained near the reference level.\n\n"
        "## Conclusion\n\nMeasured contrasts describe the sampled window and do not establish the next validation.\n"
    )
    result = audit_report_output_correctness(body, {"figures": []})
    assert "reader_technical_identifier_leak" in result["reason_codes"]
