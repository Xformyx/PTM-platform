from report_generation.core.reader_authoring import strip_authoring_anchors, validate_and_repair_sections
from report_generation.core.scientific_semantics import (
    audit_language_quality,
    enforce_report_word_budgets,
    repair_semantic_sentence,
)


def _packet():
    return {
        "contract_version": "test",
        "section_claim_budget": {"results": ["O1", "O2"], "discussion": ["O1", "O2"]},
        "reader_cards": [],
        "study_metadata_contract": {},
    }


def test_negated_directness_boundary_is_preserved_without_ungrammatical_substitution():
    sections, _ = validate_and_repair_sections(
        {"results": "The measured contrast does not prove kinase activation [EVID:missing]."},
        _packet(),
    )
    assert "does not prove kinase activation" in sections["results"]
    assert "does not is" not in sections["results"]


def test_anchor_removal_normalizes_dangling_and_repeated_punctuation():
    cleaned = strip_authoring_anchors(
        "The feature increased [EVID:feature.1],.. whereas the second sentence remained.,"
    )
    assert "EVID" not in cleaned
    assert "Whereas" not in cleaned
    audit = audit_language_quality("## Results\n\n" + cleaned)
    assert audit["doubled_punctuation_count"] == 0


def test_concordance_overreach_is_rewritten_to_pair_window_semantics():
    repaired, actions, _ = repair_semantic_sentence(
        "The significant rewiring showed rapid propagation and waves of signaling activity.",
        [],
    )
    assert "observed local concordance reorganization" in repaired
    assert "time-ordered measured pattern" in repaired
    assert "temporal profile patterns" in repaired
    assert "bound_concordance_interpretation" in actions


def test_conclusion_and_research_question_answers_are_compressed_before_release():
    long_sentence = "The measured feature remained descriptive and requires matched validation. "
    report = (
        "# Report\n\n## Conclusion\n\n" + long_sentence * 50
        + "\n\n## Supplementary Research Question Answers\n\n"
        + "### Q1. What was observed?\n\n" + long_sentence * 30
        + "\n\n## References\n\nNone."
    )
    compressed, audit = enforce_report_word_budgets(report)
    language = audit_language_quality(compressed)
    assert audit["all_within_budget"] is True
    assert language["section_word_budget_violation_count"] == 0
    assert "### Q1. What was observed?" in compressed


def test_multi_question_compression_preserves_all_question_headings():
    answer = "The measured feature was observed and requires matched validation. " * 20
    questions = "\n\n".join(
        f"### Q{index}. Question {index}?\n\n{answer}" for index in range(1, 5)
    )
    report = f"# Report\n\n## Supplementary Research Question Answers\n\n{questions}\n\n## References\n\nNone."
    compressed, audit = enforce_report_word_budgets(report)
    assert audit["all_within_budget"] is True
    for index in range(1, 5):
        assert f"### Q{index}. Question {index}?" in compressed
