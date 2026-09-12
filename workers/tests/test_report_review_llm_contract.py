import json

from common.llm_client import LLMClient
from report_generation.core.quantitative_claims import SENTENCE_RESPONSE_FORMAT, decode_sentence_draft
from test_report_review_claims import packet


def test_gemini_compatible_payload_sends_schema_with_resolved_model(monkeypatch):
    payloads = []
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"sentences": []}'}}]}
    def post(url, **kwargs):
        payloads.append((url, kwargs["json"]))
        return Response()
    monkeypatch.setattr("common.llm_client.requests.post", post)
    monkeypatch.setattr("common.llm_client._cloud_rate_limiter.wait", lambda: None)
    client = LLMClient(provider="gemini", model="gemini-2.5-pro", api_key="test-only", temperature=.2)
    assert client.generate("Draft", response_format=SENTENCE_RESPONSE_FORMAT) == '{"sentences": []}'
    assert payloads[0][1]["response_format"] == SENTENCE_RESPONSE_FORMAT
    assert payloads[0][1]["model"] == "gemini-2.5-pro"
    assert payloads[0][1]["temperature"] == .2


def test_malformed_structured_records_are_withheld_without_crashing():
    for data in ([], None, {"sentences": 1}, {"sentences": [None]}, {"sentences": [{"text": "x"}]}):
        prose, audit = decode_sentence_draft(json.dumps(data), packet())
        assert not prose
        assert all(not record["retained"] for record in audit)


def test_valid_sentences_survive_one_corrupt_structured_sentence():
    p = packet()
    eid = p["reader_cards"][0]["evidence_ids"][0]
    sentence = {"text": "The measured comparison remains descriptive.", "paragraph": 1,
                "scope": "observation", "evidence_ids": [eid], "value_tokens": [], "figure_keys": []}
    prose, audit = decode_sentence_draft(json.dumps({"sentences": [sentence, {**sentence, "value_tokens": ["V99999"]}]}), p)
    assert prose.count(sentence["text"]) == 1
    assert [record["retained"] for record in audit] == [True, False]
