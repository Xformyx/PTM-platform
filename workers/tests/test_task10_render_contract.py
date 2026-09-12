import pytest
from report_generation.core import reader_authoring as reader
from report_generation.core.figure_manifest import _generate_joint_trajectory_entry, _assign_reader_figure_labels
from report_generation.core.quantitative_claims import render_value_record, quantitative_records, validate_quantitative_sentence
from test_task10_findings import finding_state


def packet_with_figure(tmp_path, count=1):
    state = {**finding_state(count), "output_dir": str(tmp_path)}
    figure = _generate_joint_trajectory_entry(state, str(tmp_path))
    state["figure_manifest"] = _assign_reader_figure_labels({"figures": [figure]})
    return reader.build_authoring_packet(state), state["figure_manifest"]


@pytest.mark.parametrize("count", [1, 3])
def test_t10_12_frozen_findings_bind_to_three_axis_render(tmp_path, count):
    packet, manifest = packet_with_figure(tmp_path, count)
    plan = reader.deterministic_authoring_plan(packet)
    figure = manifest["figures"][0]
    assert figure["placement"] == "main" and figure["insertion_verified"]
    assert len(plan["key_findings"]) == count
    assert all(f["figure_keys"] == ["reader_joint_trajectories"] for f in plan["key_findings"])
    prose = {s: reader.render_reader_section_fallback(s, packet) for s in ("results", "discussion", "conclusion")}
    validated, audit = reader.validate_and_repair_sections(prose, packet)
    assert audit["finding_coverage"]["missing_finding_ids"] == []
    assert audit["finding_coverage"]["status"] == "covered"
    assert all(f["reader_feature_id"] in validated["results"] for f in plan["key_findings"])
    assert "next" in validated["conclusion"].lower()


def test_t10_12_numeric_withholding_cannot_silently_delete_discovery(tmp_path):
    packet, _ = packet_with_figure(tmp_path)
    card = next(c for c in packet["reader_cards"] if c.get("trajectory"))
    record = quantitative_records(card)[0]
    wrong = render_value_record({**record, "value": 9.999}) + "."
    _, audit = reader.validate_and_repair_sections({"results": wrong}, packet)
    assert audit["finding_coverage"]["status"] == "review_required"
    assert audit["finding_coverage"]["missing_finding_ids"]


def test_figure_binding_checks_actual_condition_axis_not_only_feature(tmp_path):
    packet, _ = packet_with_figure(tmp_path)
    card = next(c for c in packet["reader_cards"] if c.get("trajectory"))
    record = quantitative_records(card)[0]
    packet["figure_cards"][0]["quantitative_bindings"] = [r for r in packet["figure_cards"][0]["quantitative_bindings"] if r["condition"] != record["condition"]]
    sentence = render_value_record(record) + " (Figure 1)."
    assert "quantitative_figure_condition_axis_mismatch" in validate_quantitative_sentence(sentence, packet)


@pytest.mark.parametrize("finish_reason", ["length", "MAX_TOKENS", "content_filter"])
def test_t10_12_truncated_or_filtered_gemini_response_is_not_success(monkeypatch, finish_reason):
    from common.llm_client import LLMClient
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"sentences": []}'}, "finish_reason": finish_reason}]}
    monkeypatch.setattr("common.llm_client.requests.post", lambda *a, **kw: Response())
    monkeypatch.setattr("common.llm_client._cloud_rate_limiter.wait", lambda: None)
    client = LLMClient(provider="gemini", model="gemini-2.5-pro", api_key="synthetic-test-only")
    assert client.generate("fixture").startswith("[LLM Error")


def test_t10_12_timeout_preserves_quantitation_but_requires_interpretation_review(monkeypatch, tmp_path):
    import requests
    from common.llm_client import LLMClient
    packet, manifest = packet_with_figure(tmp_path)
    def timeout(*args, **kwargs):
        raise requests.Timeout("synthetic timeout")
    monkeypatch.setattr("common.llm_client.requests.post", timeout)
    monkeypatch.setattr("common.llm_client.time.sleep", lambda _: None)
    monkeypatch.setattr("common.llm_client._cloud_rate_limiter.wait", lambda: None)
    client = LLMClient(provider="gemini", model="gemini-2.5-pro", api_key="synthetic-test-only")
    assert client.generate_with_retry("fixture", max_retries=1) is None
    body = reader.render_data_only_reader_report({"figure_manifest": manifest}, packet, title="Synthetic", generated_at="fixture")
    audit = reader.audit_report_output_correctness(body, manifest, reader_cards=packet["reader_cards"],
                authoring_plan=reader.deterministic_authoring_plan(packet), generation_failures=["results"])
    assert "interpretation_generation_incomplete" in audit["review_reason_codes"]
    assert audit["status"] != "release_candidate"
    assert packet["reader_cards"][2]["reader_summary"]  # Evidence packet remains available.


def test_t10_export_hash_detects_docx_change(tmp_path):
    from report_generation.core import report_artifact_manifest as artifacts
    markdown = tmp_path / "report.md"
    markdown.write_text("# Synthetic fixture\n")
    docx = tmp_path / "report.docx"
    docx.write_bytes(b"synthetic file for checksum fixture only")
    manifest = {"manifest_path": str(tmp_path / "manifest.json"), "artifacts": [], "status": "validated", "report_eligible": True}
    finalized = artifacts.finalize_rendered_artifacts(manifest, [str(docx)], {})
    assert artifacts.verify_rendered_artifacts(finalized)["status"] == "verified"
    docx.write_bytes(b"changed fixture")
    assert artifacts.verify_rendered_artifacts(finalized)["status"] == "mismatch"


def test_no_export_is_incomplete_even_when_a_figure_exists(tmp_path):
    from report_generation.core.report_artifact_manifest import finalize_rendered_artifacts
    packet, manifest = packet_with_figure(tmp_path)
    sealed = finalize_rendered_artifacts({"artifacts": []}, [], manifest)
    assert sealed["render_status"] == "incomplete"


def test_final_caption_boundary_is_not_rewritten_into_another_quantity():
    from report_generation.core.citation_formatter import ReportPostProcessor
    sentence = "The measured contrasts do not establish absolute occupancy or direct kinase activity."
    result = ReportPostProcessor().process("## Results\n\n" + sentence)
    assert sentence in result
