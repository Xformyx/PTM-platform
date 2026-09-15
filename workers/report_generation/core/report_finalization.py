"""Export a current revision and resolve release only after sealing its files."""
from pathlib import Path
from .report_release import resolve_report_release, report_artifact_export_allowed
from .report_artifact_manifest import finalize_rendered_artifacts


def finalize_report_revision(*, source_paths, output_dir, correctness, manifest, figure_manifest,
                             reader_mode, requested_formats=("docx", "html"), references=(), exporters=None,
                             report_mode_contract=None, writer_effective_mode=None, graph_effective_mode=None):
    release_kwargs = dict(
        report_mode_contract=report_mode_contract,
        writer_effective_mode=writer_effective_mode,
        graph_effective_mode=graph_effective_mode,
    )
    pre = resolve_report_release(reader_authoring_shadow=reader_mode, output_correctness=correctness,
                                 artifact_manifest=manifest, phase="pre_export", **release_kwargs)
    rendered, failures = [], []
    requested = sorted(set(requested_formats))
    if exporters is None:
        from common.markdown_to_docx import convert_report_to_docx
        from common.markdown_to_html import convert_report_to_html
        exporters = {"docx": lambda path: convert_report_to_docx(path, str(output_dir)),
                     "html": lambda path: convert_report_to_html(path, output_dir=str(output_dir), references=list(references), api_base_url="/api")}
    sources = sorted(set(str(p) for p in source_paths if p and Path(p).suffix == ".md" and Path(p).is_file()))
    if report_artifact_export_allowed(pre):
        for fmt in requested:
            if fmt not in exporters or not sources:
                failures.append({"format": fmt, "reason": "unsupported_format_or_missing_source"})
                continue
            for source in sources:
                try:
                    path = exporters[fmt](source)
                    if not path or not Path(path).is_file() or Path(path).suffix != "." + fmt:
                        raise ValueError("export_did_not_return_requested_file")
                    rendered.append(str(path))
                except Exception as error:
                    failures.append({"format": fmt, "source": source, "reason": type(error).__name__})
    sealed = finalize_rendered_artifacts(manifest or {}, rendered, figure_manifest or {},
                                        requested_formats=requested, export_failures=failures)
    final = resolve_report_release(reader_authoring_shadow=reader_mode, output_correctness=correctness, artifact_manifest=sealed, **release_kwargs)
    # Only this invocation's returned exports are downloadable. Old exports in
    # the directory or in a previous state's report_files never enter this list.
    files = [str(p) for p in source_paths if p and Path(p).suffix not in {".docx", ".html"} and Path(p).is_file()] + rendered
    return {"pre_export_release": pre, "release": final, "manifest": sealed, "rendered_paths": rendered,
            "files": sorted(set(files)) if report_artifact_export_allowed(final) else []}
