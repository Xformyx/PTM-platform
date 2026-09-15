from pathlib import Path

from app.core.report_output_files import list_report_output_files, merge_result_files_with_disk


def test_lists_stamped_report_trio(tmp_path: Path):
    (tmp_path / "Order_report_260915_1133.md").write_text("new")
    (tmp_path / "Order_report_260915_1133.html").write_text("<p>new</p>")
    (tmp_path / "Order_report_260915_1133.docx").write_bytes(b"PK")
    (tmp_path / "Order_report_260915_0058.md").write_text("old")
    (tmp_path / "notes.txt").write_text("ignore")
    names = list_report_output_files(tmp_path)
    assert "Order_report_260915_1133.md" in names
    assert "Order_report_260915_0058.md" in names
    assert "notes.txt" not in names


def test_merge_does_not_promote_stale_disk_history_to_active_report(tmp_path: Path):
    (tmp_path / "Order_report_260915_1133.md").write_text("new")
    (tmp_path / "Order_report_260915_0058.docx").write_bytes(b"PK")
    merged = merge_result_files_with_disk(
        {"report_files": ["Order_report_260915_1133.md"], "all_files": ["data.json"]},
        tmp_path,
        report_options={"report_config": {
            "report_audience": "researcher_manuscript",
            "reader_authoring_mode": "shadow",
            "technical_audit_delivery": "separate_sidecar",
        }},
    )
    assert "Order_report_260915_0058.docx" not in merged["report_files"]
    assert "Order_report_260915_1133.md" in merged["report_files"]
    assert "data.json" in merged["all_files"]


def test_explicit_technical_audit_is_kept_out_of_researcher_report_files(tmp_path: Path):
    name = "Order_report_260915_1133.docx"
    (tmp_path / name).write_bytes(b"PK")
    merged = merge_result_files_with_disk(
        {"report_files": [name], "all_files": [name]},
        tmp_path,
        report_options={"report_config": {
            "report_audience": "technical_audit",
            "reader_authoring_mode": "legacy",
        }},
    )
    assert merged["report_files"] == []
    assert merged["technical_audit_files"] == [name]
    assert name not in merged["all_files"]


def test_missing_contract_hides_stale_report_trio_and_sets_typed_status(tmp_path: Path):
    names = [
        "Order_report_260915_1133.md",
        "Order_report_260915_1133.html",
        "Order_report_260915_1133.docx",
    ]
    for name in names:
        target = tmp_path / name
        target.write_bytes(b"PK") if target.suffix == ".docx" else target.write_text("stale")
    merged = merge_result_files_with_disk(
        {"report_files": names, "current_report_files": names, "all_files": [*names, "audit.json"]},
        tmp_path,
        report_options={"report_config": {}},
    )
    assert merged["report_files"] == []
    assert merged["current_report_files"] == []
    assert merged["technical_audit_files"] == []
    assert merged["report_file_visibility"]["status"] == "blocked_report_mode_contract"
    assert merged["all_files"] == ["audit.json"]


def test_researcher_request_hides_stored_technical_release(tmp_path: Path):
    name = "Order_report_260915_1133.docx"
    (tmp_path / name).write_bytes(b"PK")
    merged = merge_result_files_with_disk(
        {
            "report_files": [name],
            "current_report_files": [name],
            "report_release": {"report_audience": "technical_audit"},
        },
        tmp_path,
        report_options={"report_config": {
            "report_audience": "researcher_manuscript",
            "reader_authoring_mode": "shadow",
            "technical_audit_delivery": "separate_sidecar",
        }},
    )
    assert merged["report_files"] == []
    assert merged["current_report_files"] == []
    assert merged["technical_audit_files"] == [name]
    assert merged["report_file_visibility"]["status"] == "blocked_stale_artifact_audience_mismatch"
