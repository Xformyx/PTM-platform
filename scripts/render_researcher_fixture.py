"""Export a synthetic researcher-report fixture via production assembly/export.

This does not call Gemini or reproduce Order 74. --input-state can point to a
saved synthetic state for a before/after comparison using the same data.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from common.section_budgets import word_count
from common.markdown_to_docx import convert_markdown_to_docx
from common.markdown_to_html import convert_report_to_html
from report_generation.core.figure_manifest import prepare_reader_figure_manifest
from report_generation.core.graph import format_citations
from report_generation.core.reader_authoring import build_authoring_packet, deterministic_authoring_plan, render_reader_section_fallback, validate_and_repair_sections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--input-state', type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.input_state:
        state = json.loads(args.input_state.read_text())
    else:
        from test_flow_researcher_report import researcher_state
        state = researcher_state(16)
        for r in state['vector_plot_raw_data']:
            r['FASTA_Taxonomy_ID'] = '10116'
    source = json.dumps(state, sort_keys=True, indent=2)
    (args.output_dir / 'fixture_input.json').write_text(source)
    state.update(output_dir=str(args.output_dir), reader_authoring_mode='shadow',
                 report_config={'reader_authoring_mode': 'shadow'}, ptm_type='phosphorylation',
                 report_title='Synthetic researcher-report regression fixture', collected_references=[])
    state['figure_manifest'] = prepare_reader_figure_manifest(state, citation_complete=False)
    packet = build_authoring_packet(state)
    plan = deterministic_authoring_plan(packet)
    sections = {s: render_reader_section_fallback(s, packet, questions=state.get('research_questions')) for s in ('abstract', 'introduction', 'methods', 'results', 'discussion', 'conclusion')}
    sections, validator = validate_and_repair_sections(sections, packet)
    final = format_citations({**state, 'sections': sections, 'authoring_packet': packet,
                              'reader_authoring_plan': plan, 'reader_authoring_fallback_sections': list(sections)})
    body = final['final_report']
    markdown = args.output_dir / 'researcher_fixture.md'
    markdown.write_text(body)
    docx = args.output_dir / 'researcher_fixture.docx'
    convert_markdown_to_docx(body, str(docx))
    html = Path(convert_report_to_html(str(markdown), output_dir=str(args.output_dir)))
    metrics = {'input_sha256': hashlib.sha256(source.encode()).hexdigest(), 'synthetic_only': True, 'gemini_called': False,
               'section_words': {}, 'reference_count': len(state['collected_references']),
               'qa_heading_count': len(re.findall(r'^## (?:Supplementary )?Research Question Answers', body, re.M)),
               'correctness': final['report_output_correctness'],
               'figures': [{'key': f['figure_key'], 'placement': f['placement'], 'bindings': len(f.get('quantitative_bindings') or []),
                            'readability': f.get('readability_audit'), 'feature_ids': f.get('selected_reader_feature_ids')} for f in state['figure_manifest']['figures']]}
    for m in re.finditer(r'(?ms)^## (Abstract|Introduction|Methods|Results|Discussion|Conclusion)\s*\n(.*?)(?=^## |\Z)', body):
        metrics['section_words'][m[1].lower()] = word_count(re.split(r'(?m)^### (?:Supplementary )?Figure', m[2])[0])
    try:
        from report_generation.core.report_artifact_manifest import report_runtime_provenance, persist_report_packets
        metrics['runtime'] = report_runtime_provenance()
        persist_report_packets({**state, 'authoring_packet': packet, 'reader_authoring_plan': plan}, args.output_dir)
    except ImportError:
        pass  # Pinned pre-change fixture comparison, no new provenance helper.
    files = [('authoring_packet', packet), ('authoring_plan', plan), ('figure_manifest', state['figure_manifest']), ('validator', validator), ('metrics', metrics)]
    for name, obj in files:
        (args.output_dir / (name + '.json')).write_text(json.dumps(obj, indent=2, default=str))
    metrics['export_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [markdown, docx, html]}
    (args.output_dir / 'metrics.json').write_text(json.dumps(metrics, indent=2, default=str))
    print(json.dumps({'output_dir': str(args.output_dir), 'words': metrics['section_words'], 'qa_headings': metrics['qa_heading_count'], 'correctness': metrics['correctness']['status']}))


if __name__ == '__main__':
    main()
