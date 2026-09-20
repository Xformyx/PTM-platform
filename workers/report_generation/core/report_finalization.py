"""Export a current revision and resolve release only after sealing its files."""
from pathlib import Path
from .report_release import resolve_report_release, report_artifact_export_allowed
from .report_artifact_manifest import finalize_rendered_artifacts


def finalize_report_revision(*, source_paths, output_dir, correctness, manifest, figure_manifest,
                             reader_mode, requested_formats=("docx", "html"), references=(), exporters=None,
                             report_mode_contract=None, writer_effective_mode=None, graph_effective_mode=None,
                             register_immutable=False, source_revisions=()):
    release_kwargs = dict(
        report_mode_contract=report_mode_contract,
        writer_effective_mode=writer_effective_mode,
        graph_effective_mode=graph_effective_mode,
    )
    pre = resolve_report_release(reader_authoring_shadow=reader_mode, output_correctness=correctness,
                                 artifact_manifest=manifest, phase="pre_export", **release_kwargs)
    rendered, failures = [], []
    requested = sorted(set(requested_formats))
    sources = sorted(set(str(p) for p in source_paths if p and Path(p).suffix == ".md" and Path(p).is_file()))
    export_dir = Path(output_dir)
    if register_immutable:
        import copy
        import tempfile
        from ptm_shared.report_revision import file_sha256
        from .report_artifact_manifest import _artifact
        manifest = copy.deepcopy(manifest or {})
        for item in manifest.get('artifacts') or []:
            if item.get('sha256') and (not Path(item['path']).is_file() or file_sha256(item['path']) != item['sha256']):
                raise ValueError('source_changed_before_staging')
        attempts = export_dir / '.report_attempts'
        attempts.mkdir(exist_ok=True)
        export_dir = Path(tempfile.mkdtemp(prefix='render_', dir=attempts))
        import shutil
        for figure in (figure_manifest or {}).get('figures') or []:
            image = Path(figure.get('image_path') or '')
            if image.is_file() and figure.get('insertion_verified'):
                copied = export_dir / image.name
                shutil.copyfile(image, copied)
                if figure.get('sha256') and file_sha256(copied) != figure['sha256']:
                    raise ValueError('figure_changed_before_staging')
        staged = []
        for source in sources:
            target = export_dir / Path(source).name
            target.write_bytes(Path(source).read_bytes())
            staged.append(str(target))
            for item in manifest.get('artifacts') or []:
                if str(item.get('path')) == source:
                    item.update(_artifact(item['role'], target, required=item.get('required', True)))
        sources = staged
        manifest['manifest_path'] = str(export_dir / 'report_artifact_manifest.json')

    def mark_review_draft():
        from .report_artifact_manifest import _artifact
        for source in sources:
            path = Path(source)
            content = path.read_text()
            if '> Review draft —' not in content:
                content = '> Review draft — Evidence or output checks remain unresolved. Interpret this document within its stated limitations.\n\n' + content
                path.write_text(content)
            for item in (manifest or {}).get('artifacts') or []:
                if str(item.get('path')) == source:
                    item.update(_artifact(item['role'], path, required=item.get('required', True)))

    if register_immutable and pre['status'] == 'draft_review_required':
        mark_review_draft()
    if exporters is None:
        from common.markdown_to_docx import convert_report_to_docx
        from common.markdown_to_html import convert_report_to_html
        exporters = {"docx": lambda path: convert_report_to_docx(path, str(export_dir)),
                     "html": lambda path: convert_report_to_html(path, output_dir=str(export_dir), references=list(references), api_base_url="/api")}
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
    if register_immutable and final['status'] == 'draft_review_required' and pre['status'] != 'draft_review_required':
        mark_review_draft()
        rendered = []
        for fmt in requested:
            for source in sources:
                if fmt not in exporters:
                    continue
                try:
                    path = exporters[fmt](source)
                    if path and Path(path).is_file() and Path(path).suffix == '.' + fmt:
                        rendered.append(str(path))
                except Exception as error:
                    failures.append({'format': fmt, 'source': source, 'reason': type(error).__name__})
        sealed = finalize_rendered_artifacts(manifest or {}, rendered, figure_manifest or {},
            requested_formats=requested, export_failures=failures)
        final = resolve_report_release(reader_authoring_shadow=reader_mode, output_correctness=correctness, artifact_manifest=sealed, **release_kwargs)
    # Only this invocation's returned exports are downloadable. Old exports in
    # the directory or in a previous state's report_files never enter this list.
    files = sources + [str(p) for p in source_paths if p and Path(p).suffix not in {".md", ".docx", ".html"} and Path(p).is_file()] + rendered
    if register_immutable:
        from ptm_shared.report_revision import register_revision
        revision = register_revision(output_dir, files=files, manifest=sealed, release=final, references=references, source_revisions=source_revisions)
        files = [str(Path(output_dir) / a['filename']) for a in revision['artifacts'] if a['role'] == 'report']
        sealed['revision_id'] = revision['revision_id']
        final['revision_id'] = revision['revision_id']
    return {"pre_export_release": pre, "release": final, "manifest": sealed, "rendered_paths": rendered,
            "files": sorted(set(files)) if report_artifact_export_allowed(final) else []}
