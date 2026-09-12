"""Export the deterministic TASK-10 fixture using the production report path.

Run with PYTHONPATH=workers:workers/tests:. and the test environment. Output goes
outside the repository by default. These are synthetic values, not study data.
"""
import argparse
import hashlib
import json
from pathlib import Path

from report_generation.core.figure_manifest import prepare_reader_figure_manifest
from report_generation.core.graph import format_citations
from report_generation.core.reader_authoring import (
    build_authoring_packet, deterministic_authoring_plan, render_reader_section_fallback,
    validate_and_repair_sections,
)
from common.markdown_to_docx import convert_markdown_to_docx
from common.markdown_to_html import convert_report_to_html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/ptm-task10-render"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (gene, levels) in enumerate((
        ("KNOWN_FIXTURE", (1., 1., 0.)), ("UNEXPLAINED_FIXTURE", (0., -1., 1.)),
        ("UNEXPLAINED_FIXTURE", (-2., -1., -1.)),
    )):
        for time in (5, 40, 180):
            u, p, a = levels
            rows.append({"gene": gene, "position": f"S{index + 1}", "precursor_id": f"synthetic-form-{index}",
                         "protein_group": gene, "condition": f"{time}min", "ptm_unadjusted_log2fc": u,
                         "protein_log2fc": p, "ptm_protein_adjusted_log2fc": a,
                         "ptm_unadjusted_control_n": 3, "ptm_unadjusted_treatment_n": 3,
                         "ptm_unadjusted_q_value": .001, "ptm_protein_adjusted_control_n": 3,
                         "ptm_protein_adjusted_treatment_n": 3, "ptm_protein_adjusted_q_value": None})
    state = {"vector_plot_raw_data": rows, "output_dir": str(args.output_dir),
             "reader_authoring_mode": "shadow", "report_config": {"reader_authoring_mode": "shadow"},
             "ptm_type": "phosphorylation", "experimental_context": {"cell_type": "synthetic fixture", "treatment": "synthetic contrasts"},
             "report_title": "Synthetic PTM protein report validation", "collected_references": []}
    state["figure_manifest"] = prepare_reader_figure_manifest(state, citation_complete=False)
    packet = build_authoring_packet(state)
    plan = deterministic_authoring_plan(packet)
    sections = {section: render_reader_section_fallback(section, packet) for section in (
        "abstract", "introduction", "methods", "results", "discussion", "conclusion", "research_question_answers")}
    sections, validator = validate_and_repair_sections(sections, packet)
    final = format_citations({**state, "sections": sections, "authoring_packet": packet, "reader_authoring_plan": plan})
    markdown = args.output_dir / "task10_fixture.md"
    markdown.write_text(final["final_report"], encoding="utf-8")
    docx = args.output_dir / "task10_fixture.docx"
    convert_markdown_to_docx(final["final_report"], str(docx))
    html = convert_report_to_html(str(markdown), output_dir=str(args.output_dir))
    for name, content in (("authoring_packet", packet), ("authoring_plan", plan), ("figure_manifest", state["figure_manifest"]),
                          ("validator", validator), ("output_correctness", final["report_output_correctness"])):
        (args.output_dir / f"{name}.json").write_text(json.dumps(content, indent=2, default=str))
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (markdown, docx, Path(html))}
    (args.output_dir / "export_hashes.json").write_text(json.dumps(hashes, indent=2))
    print(json.dumps({"output_dir": str(args.output_dir), "hashes": hashes, "finding_coverage": validator["finding_coverage"]["status"],
                      "correctness": final["report_output_correctness"]["status"], "issues": final["report_output_correctness"]["reason_codes"]}, indent=2))


if __name__ == "__main__":
    main()
