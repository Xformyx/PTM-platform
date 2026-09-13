"""Mock retrieval transport and Gemini; real retrieval adapter -> packet -> prose."""
import json
import pytest
from report_generation.core.finding_literature import retrieve_finding_literature
from report_generation.core.measured_feature_cards import build_feature_observation_cards
from report_generation.core.reader_authoring import build_authoring_packet, deterministic_authoring_plan, render_reader_section_fallback
from test_task10_findings import finding_state


class Retriever:
    collection_names = ["synthetic_collection"]
    def __init__(self, fail=False):
        self.fail = fail
    def query(self, query, *, n_results, strict):
        assert "CANDIDATE0" in query and strict
        if self.fail:
            raise RuntimeError("mock unavailable")
        return [{"title": "Synthetic source", "doi": "10.1000/fixture", "authors": "Fixture", "year": "2026",
                 "document": "CANDIDATE0 S7 increased in mouse cells after insulin at 5min.",
                 "collection": "synthetic_collection", "collection_version": "test-v1", "source_id": "doc-1"}]


class Model:
    def __init__(self, relation="known_agreement", quote=None):
        self.relation, self.quote = relation, quote
    def generate(self, prompt, **kwargs):
        assert kwargs["response_format"]["type"] == "json_schema"
        return json.dumps({"comparisons": [{"source_index": 0,
            "quote": self.quote or "CANDIDATE0 S7 increased in mouse cells after insulin at 5min.",
            "relationship": self.relation, "reference_scope": "site", "external_finding": "S7 increased",
            "species": "mouse", "cell_type": "mouse cells", "time": "5min", "insulin_dose": "", "readout": "", "perturbation": "insulin"}]})


@pytest.mark.parametrize("relation", ["known_agreement", "disagreement"])
def test_retrieved_comparison_reaches_packet_and_condition_aware_prose(relation):
    state = finding_state()
    cards = build_feature_observation_cards(state)
    retrieved = retrieve_finding_literature(cards, Retriever(), {"species": "human", "cell_type": "HIRc-B"}, llm=Model(relation))
    refs = retrieved.pop("references")
    packet = build_authoring_packet({**state, "finding_literature_retrieval": retrieved}, references=refs)
    finding = deterministic_authoring_plan(packet)["key_findings"][0]
    comparison = finding["literature_comparison"]
    assert comparison["status"] == relation
    assert comparison["comparisons"][0]["source_offset"] == 0
    assert not comparison["comparisons"][0]["measured_relation"]
    assert comparison["comparisons"][0]["reference_scope"] == "site"
    prose = render_reader_section_fallback("discussion", packet)
    assert "mouse" in prose and "human" in prose
    assert ("agreed with" if relation == "known_agreement" else "differed from") in prose


@pytest.mark.parametrize("mode,status,phrase", [("off", "not_searched", "not performed"),
    ("failed", "retrieval_failed", "search failed"), ("pending", "retrieved_comparison_pending", "remains incomplete")])
def test_missing_search_failure_and_pending_comparison_remain_distinct(mode, status, phrase):
    state = finding_state()
    retriever = Retriever(fail=mode == "failed")
    if mode == "off":
        retriever.collection_names = []
    result = retrieve_finding_literature(build_feature_observation_cards(state), retriever, {}, llm=None)
    refs = result.pop("references")
    packet = build_authoring_packet({**state, "finding_literature_retrieval": result}, references=refs)
    assert deterministic_authoring_plan(packet)["key_findings"][0]["literature_comparison"]["status"] == status
    assert phrase in render_reader_section_fallback("discussion", packet)


def test_fabricated_quote_cannot_become_a_literature_comparison():
    result = retrieve_finding_literature(build_feature_observation_cards(finding_state()), Retriever(), {}, llm=Model(quote="invented finding"))
    record = next(iter(result["records"].values()))
    assert not record["comparisons"]
    assert record["excluded_comparisons"][0]["reason"] == "unbound_quote_context_or_scope"
