"""Keyed frozen-reference comparisons; never modify either input tree."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TABLE_KEYS = {
    'analysis/phosphoform_summary.csv': ['Protein.Group', 'Modified.Sequence'],
    'analysis/mapping_exclusions.csv': ['Protein.Group', 'Modified.Sequence'],
    'analysis/phosphoform_runlevel.csv': ['form_id', 'run'],
    'analysis/sample_manifest.csv': ['run'],
    'kinase/observed_fasta_site_mappings.tsv': ['Protein.Group', 'Modified.Sequence', 'mapped_accession', 'residue_offset', 'residue_type'],
    'kinase/observed_omnipath_edges.tsv': ['Protein.Group', 'Modified.Sequence', 'mapped_accession', 'residue_offset', 'residue_type', 'enzyme'],
    'kinase/observed_omnipath_edges_classified.tsv': ['Protein.Group', 'Modified.Sequence', 'mapped_accession', 'residue_offset', 'residue_type', 'enzyme'],
    'kinase/observed_curated_edges.tsv': ['Protein.Group', 'Modified.Sequence', 'mapped_accession', 'residue_offset', 'residue_type', 'enzyme'],
    'kinase/observed_curated_edges_primary.tsv': ['Protein.Group', 'Modified.Sequence', 'mapped_accession', 'residue_offset', 'residue_type', 'enzyme'],
    'kinase/curated_primary_coverage.tsv': ['kinase_gene', 'enzyme'],
    'kinase/omnipath_coverage.tsv': ['kinase_gene', 'enzyme'],
    'scores/annotated_form_edges.csv': ['entity', 'site_key', 'form_id'],
    'scores/background_context.csv': ['time_min'],
    'scores/kinase_time_profiles.csv': ['entity', 'mode', 'time_min'],
    'scores/insulin_family_profiles.csv': ['entity', 'mode', 'time_min'],
    'scores/kinase_coverage.csv': ['entity'],
    'scores/primary_site_scores.csv': ['entity', 'time_min', 'substrate_gene', 'site_key'],
    'scores/primary_gene_scores.csv': ['entity', 'time_min', 'substrate_gene'],
    'scores/run_omission_scores.csv': ['entity', 'time_min', 'omit_baseline_run', 'omit_treatment_run'],
    'scores/fixed_site_set_profiles.csv': ['entity', 'time_min'],
    'scores/S6K_source_caution_sensitivity.csv': ['entity', 'mode', 'time_min'],
    'scores/S6K_source_caution_sites.csv': ['entity', 'time_min', 'substrate_gene', 'site_key'],
    'scores/substrate_set_overlap.csv': ['entity_a', 'entity_b'],
    'scores/temporal_summary.csv': ['entity'],
}


def compare_frames(reference, actual, keys, atol=1e-10, rtol=1e-10):
    result = {'reference_rows': len(reference), 'actual_rows': len(actual), 'keys': keys,
              'atol': atol, 'rtol': rtol, 'column_differences': {}, 'max_absolute_error': 0.0}
    # NA has its own key representation; it is never converted to zero.
    # CSV represents an absent text field as an empty cell. Normalize only that
    # serialization difference; a numeric zero remains a distinct observation.
    a, b = [df.astype('string').replace('', pd.NA).fillna('<NA>').set_index(keys).sort_index() for df in (reference, actual)]
    if a.index.has_duplicates or b.index.has_duplicates:
        result['duplicate_keys'] = True
        return result
    result['missing_keys'] = len(a.index.difference(b.index))
    result['extra_keys'] = len(b.index.difference(a.index))
    result['missing_columns'] = sorted(set(a) - set(b))
    result['extra_columns'] = sorted(set(b) - set(a))
    common = a.index.intersection(b.index)
    a, b = a.loc[common], b.loc[common]
    for col in a.columns.intersection(b.columns):
        av, bv = a[col], b[col]
        missing_a, missing_b = av.eq('<NA>'), bv.eq('<NA>')
        mismatch = missing_a.ne(missing_b)
        present = ~(missing_a | missing_b)
        ax, bx = [pd.to_numeric(v[present], errors='coerce') for v in (av, bv)]
        if len(ax) and ax.notna().all() and bx.notna().all():
            x, y = ax.to_numpy(float), bx.to_numpy(float)
            integral = np.equal(x, np.floor(x)).all() and np.equal(y, np.floor(y)).all()
            mismatch.loc[present] = (x != y) if integral else ~np.isclose(x, y, atol=atol, rtol=rtol)
            error = float(np.max(np.abs(x - y)))
            result['max_absolute_error'] = max(error, result['max_absolute_error'])
        else:
            mismatch.loc[present] = av[present].ne(bv[present])
        if mismatch.any():
            result['column_differences'][col] = {'count': int(mismatch.sum()),
                'example_keys': [str(v) for v in mismatch[mismatch].index[:3]]}
    result['passed'] = not any(result[k] for k in ('missing_keys', 'extra_keys', 'missing_columns', 'column_differences'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--actual', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = {}
    for name, keys in TABLE_KEYS.items():
        paths = [root / name for root in (args.reference, args.actual)]
        if not all(p.exists() for p in paths):
            results[name] = {'passed': False, 'missing_file': True}
            continue
        frames = [pd.read_csv(p, sep='\t' if p.suffix == '.tsv' else ',', dtype=str) for p in paths]
        results[name] = compare_frames(*frames, keys)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))
    print(json.dumps({k: v for k, v in results.items() if not v.get('passed')}, indent=2))
    print(f"Compared {len(results)} tables; passed {sum(bool(v.get('passed')) for v in results.values())}")


if __name__ == '__main__':
    main()
