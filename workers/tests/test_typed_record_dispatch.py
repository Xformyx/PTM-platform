"""Typed kinase/pathway records bind without a fake PF identity."""
from report_generation.core.quantitative_claims import (
    quantitative_records,
    validate_quantitative_sentence,
    value_token_catalog,
)
from report_generation.core.research_questions import classify_question_intent, build_question_map
from report_generation.core.finding_literature import retrieve_finding_literature
from ptm_shared.evidence_record_contract import typed_record


def _kinase_packet(value=0.75, denominator=4):
    record = typed_record(
        record_type="kinase_trajectory",
        entity_id="MAPK1",
        metric_id="direction_concordance_fraction",
        value=value,
        unit="fraction",
        interval="1min->5min",
        numerator=3,
        denominator=denominator,
        estimator="kinase_trajectory_evidence.v1",
        support_status="computed",
        evidence_id="kinase.trajectory.MAPK1",
    )
    card = {
        "card_id": "kinase.1",
        "category": "kinase_context",
        "evidence_type": "kinase_candidate",
        "reader_summary": "MAPK1 family footprint provided candidate context.",
        "value_records": [record],
        "evidence_ids": ["kinase.trajectory.MAPK1"],
    }
    return {"reader_cards": [card], "figure_cards": []}


def test_typed_records_are_catalogued_without_feature_identity():
    packet = _kinase_packet()
    records = quantitative_records(packet["reader_cards"][0])
    assert records[0]["record_type"] == "kinase_trajectory"
    catalog = value_token_catalog(packet)
    assert catalog["V1"]["entity_id"] == "MAPK1"


def test_kinase_value_and_denominator_tampering_is_rejected():
    packet = _kinase_packet()
    ok = validate_quantitative_sentence(
        "MAPK1 direction concordance fraction was 0.75 at 1min->5min.",
        packet,
    )
    assert ok == []
    assert "typed_record_value_unbound" in validate_quantitative_sentence(
        "MAPK1 direction concordance fraction was 0.99 at 1min->5min.",
        packet,
    )
    assert "typed_record_denominator_mismatch" in validate_quantitative_sentence(
        "MAPK1 direction concordance fraction was 0.75 at 1min->5min as 3 / 9 intervals.",
        packet,
    )


def test_kinase_question_is_not_rewritten_and_keeps_separate_coverage():
    assert classify_question_intent("Which kinase candidates are supported?") == "kinase_context"
    mapping = build_question_map(
        [{"text": "Which kinase candidates are supported?", "origin": "user"}],
        [{"category": "kinase_context", "evidence_ids": ["kinase.footprint.MAPK1"], "feature_identity": {}}],
    )
    question = mapping["questions"][0]
    assert question["intent"] == "kinase_context"
    assert "protein" not in question["normalized_question"].lower() or "kinase" in question["normalized_question"].lower()
    assert question["answerability"] == "observational_only"
    assert question["coverage"] == "unanswered"


def test_literature_splits_neutral_and_opposing_queries():
    seen = []

    class Retriever:
        collection_names = ["fixture"]

        def query(self, query, **kwargs):
            seen.append(query)
            return []

    retrieve_finding_literature(
        [{"feature_identity": {"reader_feature_id": "PF-AAAAAAAA", "gene": "MAPK1", "candidate_residue_annotation": "Y187"}}],
        Retriever(),
        {"species": "human", "cell_type": "HIRc-B", "treatment": "insulin"},
        llm=None,
    )
    assert any("PTM protein time course" in query and "opposing" not in query for query in seen)
    assert any("opposing" in query or "conflicting" in query for query in seen)
    assert not any("trafficking translation cytoskeleton" in query for query in seen)
