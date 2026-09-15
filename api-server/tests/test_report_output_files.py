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


def test_merge_restores_disk_history(tmp_path: Path):
    (tmp_path / "Order_report_260915_1133.md").write_text("new")
    (tmp_path / "Order_report_260915_0058.docx").write_bytes(b"PK")
    merged = merge_result_files_with_disk(
        {"report_files": ["Order_report_260915_1133.md"], "all_files": ["data.json"]},
        tmp_path,
    )
    assert "Order_report_260915_0058.docx" in merged["report_files"]
    assert "Order_report_260915_1133.md" in merged["report_files"]
    assert "data.json" in merged["all_files"]
