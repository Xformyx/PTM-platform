"""Independently rebuild primary forms and kinase footprints from raw matrices."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from ptm_shared.report_compatible_quantification import quantify_forms, read_fasta
from ptm_shared.report_compatible_kinase import frozen_edges, score_footprints
from compare_hircb_reference import compare_frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pr_path, pg_path, fasta_path = [args.inputs / p for p in ('report.pr_matrix.tsv', 'report.pg_matrix.tsv', 'uniprotkb_proteome_Rat_add_human_INSR.fasta')]
    snapshot_path = args.reference / 'kinase/omnipath_rat_enzsub.tsv'
    expected = '80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07'
    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == expected
    samples = pd.read_csv(args.reference / 'analysis/sample_manifest.csv').to_dict('records')
    print('Independent raw form calculation', flush=True)
    analysis = quantify_forms(pd.read_csv(pr_path, sep='\t'), pd.read_csv(pg_path, sep='\t'), read_fasta(fasta_path), samples)
    results = {}

    def compare(name, actual, reference_name, keys):
        ref_path = args.reference / reference_name
        ref = pd.read_csv(ref_path, sep='\t' if ref_path.suffix == '.tsv' else ',')
        cols = [c for c in actual if c in ref]
        result = compare_frames(ref[cols], actual[cols], keys)
        result['compared_columns'] = cols
        results[name] = result
        actual.to_csv(args.output / f'{name}.csv', index=False)
        print(name, result['passed'], result['column_differences'], flush=True)

    compare('forms', analysis['summary'], 'analysis/phosphoform_summary.csv', ['Protein.Group', 'Modified.Sequence'])
    compare('runlevel', analysis['runlevel'], 'analysis/phosphoform_runlevel.csv', ['form_id', 'run'])
    # Explicitly audit inclusion membership and the same joint observation masks,
    # including excluded comparisons. This comparison does not use regenerated CSVs.
    ref_summary = pd.read_csv(args.reference / 'analysis/phosphoform_summary.csv').set_index('form_id')
    ref_runs = pd.read_csv(args.reference / 'analysis/phosphoform_runlevel.csv')
    ref_comparisons = []
    for form_id, rows in ref_runs.groupby('form_id'):
        baseline = rows[(rows.time_min == 0) & rows.adjusted_log2_ratio.notna()]
        for time in sorted(set(rows.time_min) - {0}):
            treated = rows[(rows.time_min == time) & rows.adjusted_log2_ratio.notna()]
            evaluable = len(baseline) >= 2 and len(treated) >= 2
            ref_comparisons.append({'form_id': form_id, 'time_min': time,
                'included': bool(ref_summary.loc[form_id,'primary_adjustment_eligible'] and evaluable),
                'baseline_joint_n':len(baseline), 'treated_joint_n':len(treated),
                'baseline_joint_runs':';'.join(baseline.run), 'treated_joint_runs':';'.join(treated.run),
                'U_joint': treated.phospho_log2.mean()-baseline.phospho_log2.mean() if evaluable else float('nan'),
                'P_joint': treated.parent_log2.mean()-baseline.parent_log2.mean() if evaluable else float('nan'),
                'A': treated.adjusted_log2_ratio.mean()-baseline.adjusted_log2_ratio.mean() if evaluable else float('nan')})
    reference_comparisons = pd.DataFrame(ref_comparisons)
    results['primary_membership_masks_joint_values'] = compare_frames(reference_comparisons,
        analysis['comparisons'][reference_comparisons.columns], ['form_id','time_min'])
    analysis['comparisons'].to_csv(args.output / 'parent_counterfactual.csv', index=False)
    analysis['detection'].to_csv(args.output / 'detection.csv', index=False)
    print('Independent frozen edge mapping and scoring', flush=True)
    mappings, edges = frozen_edges(analysis, pd.read_csv(snapshot_path, sep='\t'))
    edge_keys = ['Protein.Group', 'Modified.Sequence', 'mapped_accession', 'residue_offset', 'residue_type']
    compare('site_mappings', mappings, 'kinase/observed_fasta_site_mappings.tsv', edge_keys)
    compare('primary_edges', edges[edges.primary_edge_eligible], 'kinase/observed_curated_edges_primary.tsv', edge_keys + ['enzyme'])
    edges.to_csv(args.output / 'all_edges_with_exclusions.csv', index=False)
    kinase = score_footprints(analysis, edges)
    for name, frame, file, keys in [
        ('kinase_profiles', kinase['profiles'], 'kinase_time_profiles.csv', ['entity', 'mode', 'time_min']),
        ('site_contributions', kinase['site_scores'], 'primary_site_scores.csv', ['entity', 'time_min', 'substrate_gene', 'site_key']),
        ('gene_contributions', kinase['gene_scores'], 'primary_gene_scores.csv', ['entity', 'time_min', 'substrate_gene']),
        ('run_omissions', kinase['omissions'], 'run_omission_scores.csv', ['entity', 'time_min', 'omit_baseline_run', 'omit_treatment_run']),
    ]:
        compare(name, frame, 'scores/' + file, keys)
    for name in ['sensitivities', 'strict', 'overlap']:
        kinase[name].to_csv(args.output / f'kinase_{name}.csv', index=False)
    caution = kinase['sensitivities'].query("mode == 'S6K_source_caution'").drop(columns='mode')
    compare('S6K_source_caution', caution, 'scores/S6K_source_caution_sensitivity.csv', ['entity', 'time_min'])
    fm = analysis['summary']
    counts = {'all_forms': len(fm), 'mapping_eligible': int(fm.primary_mapping_eligible.sum()),
              'parent_eligible': int(fm.primary_adjustment_eligible.sum()),
              'parent_eligible_evaluable_forms': int((fm.primary_adjustment_eligible & fm.A_evaluable_time_count.gt(0)).sum()),
              'eligible_form_time_comparisons': int(analysis['comparisons'].included.sum()),
              'baseline_undetected': int(fm.baseline_undetected_all_runs.sum()),
              'baseline_undetected_post_ge2': int(fm.post_only_detected_ge2_any_time.sum())}
    report = {'schema_version': 'hircb_independent_validation.v1', 'counts': counts,
              'comparisons': results, 'snapshot_sha256': expected,
              'scope': 'Raw matrices and FASTA to mapping, masks, primary eligibility, contrasts, frozen edges and gene-balanced modes; reference CSVs used only for comparison.'}
    (args.output / 'independent_validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(counts, indent=2), flush=True)
    # Subsequent extension outputs deliberately have their own contract and are
    # not claimed as a reproduction of absent article/extension package files.
    from ptm_shared.report_compatible_extensions import extend_and_export
    source_inputs = {'PR': pr_path, 'PG': pg_path, 'FASTA': fasta_path, 'snapshot': snapshot_path}
    for name, filename in [('article', 'HIRcB_Insulin_Full_Article (2).docx'), ('review', 'PTM_platform_review_KO.md')]:
        if (args.inputs / filename).exists():
            source_inputs[name] = args.inputs / filename
    extend_and_export(analysis, mappings, edges, kinase, args.output / 'astra_handoff', source_inputs,
                      reference_dir=args.reference)


if __name__ == '__main__':
    main()
