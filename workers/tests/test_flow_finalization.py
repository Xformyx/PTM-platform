import pytest
from report_generation.core.report_artifact_manifest import _artifact, finalize_rendered_artifacts
from report_generation.core.report_finalization import finalize_report_revision
from report_generation.core.report_release import resolve_report_release
from ptm_shared.report_mode import is_reader_mode, resolve_report_mode_contract


@pytest.mark.parametrize("mode", ["shadow", "opt_in_shadow"])
def test_partial_export_does_not_return_previous_docx(tmp_path, mode):
    md = tmp_path / "current.md"
    md.write_text("A measured observation.")
    previous = tmp_path / "previous.docx"
    previous.write_bytes(b"old revision")
    html = tmp_path / "current.html"
    def html_export(_):
        html.write_text("<p>A measured observation.</p>")
        return html
    def failed_docx(_):
        raise RuntimeError("synthetic converter failure")
    manifest = {"status": "validated", "report_eligible": True, "artifacts": [_artifact("markdown", md, required=True)]}
    kwargs = dict(source_paths=[str(md), str(previous)], output_dir=tmp_path,
                  correctness={"status": "release_candidate"}, manifest=manifest, figure_manifest={},
                  reader_mode=is_reader_mode({"reader_authoring_mode": mode}),
                  exporters={"html": html_export, "docx": failed_docx})
    partial = finalize_report_revision(**kwargs)
    assert not partial["release"]["publish_as_final"]
    assert partial["manifest"]["missing_formats"] == ["docx"]
    assert str(previous) not in partial["files"]
    assert str(html) in partial["files"]
    only_html = finalize_report_revision(**kwargs, requested_formats=["html"])
    assert only_html["release"]["publish_as_final"]
    assert not only_html["pre_export_release"]["publish_as_final"]
    html.write_text("tampered after seal")
    assert not resolve_report_release(reader_authoring_shadow=True, output_correctness=kwargs["correctness"],
                                      artifact_manifest=only_html["manifest"])["publish_as_final"]


def test_source_changed_during_export_is_withheld(tmp_path):
    md = tmp_path / "current.md"
    md.write_text("source")
    manifest = {"status": "validated", "report_eligible": True, "artifacts": [_artifact("markdown", md, required=True)]}
    html = tmp_path / "current.html"
    html.write_text("render")
    md.write_text("changed source")
    sealed = finalize_rendered_artifacts(manifest, [html], {}, requested_formats=["html"])
    final = resolve_report_release(reader_authoring_shadow=True, output_correctness={"status": "release_candidate"}, artifact_manifest=sealed)
    assert final["status"] == "blocked_final"
    assert "source_changed_before_export" in final["reason_codes"]
    assert not final["review_artifact_available"]


def test_missing_audience_contract_never_calls_exporter_or_returns_stale_technical_file(tmp_path):
    source = tmp_path / "researcher_source.md"
    source.write_text("A measured PTM observation.")
    stale_technical = tmp_path / "legacy_technical_report.docx"
    stale_technical.write_bytes(b"technical audit")
    called = {"html": 0, "docx": 0}

    def exporter(fmt):
        def _run(_source):
            called[fmt] += 1
            target = tmp_path / f"new.{fmt}"
            target.write_bytes(b"new") if fmt == "docx" else target.write_text("new")
            return target
        return _run

    contract = dict(resolve_report_mode_contract({}))
    result = finalize_report_revision(
        source_paths=[str(source), str(stale_technical)],
        output_dir=tmp_path,
        correctness={"status": "release_candidate"},
        manifest={"status": "validated", "report_eligible": True, "artifacts": [_artifact("markdown", source, required=True)]},
        figure_manifest={},
        reader_mode=False,
        requested_formats=["html", "docx"],
        exporters={"html": exporter("html"), "docx": exporter("docx")},
        report_mode_contract=contract,
    )
    assert called == {"html": 0, "docx": 0}
    assert result["release"]["status"] == "blocked_final"
    assert result["files"] == []
    assert str(stale_technical) not in result["files"]
