"""Strict parent sensitivity, held-out late layer, and portable evidence export."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from statistics import median
import zipfile

import numpy as np
import pandas as pd

from .report_compatible_quantification import contrast, positive_matrix, VERSION
from .report_compatible_kinase import HELD_OUT_GENES


def strict_unmodified_parent(analysis):
    pr = analysis['pr']
    columns = [s['original_column'] for s in analysis['samples']]
    modified_backbones = set(pr.loc[pr['Modified.Sequence'].ne(pr['Stripped.Sequence']), 'Stripped.Sequence'])
    # Ambiguous sequence-to-group assignment cannot provide an independent parent.
    group_counts = pr.groupby('Stripped.Sequence')['Protein.Group'].nunique()
    gene = pr.Genes.fillna('')
    eligible = (pr['Modified.Sequence'].eq(pr['Stripped.Sequence']) & pr.Proteotypic.eq(1)
                & pr['Protein.Group'].notna() & gene.str.strip().ne('') & ~gene.str.contains(';')
                & ~pr['Stripped.Sequence'].isin(modified_backbones)
                & pr['Stripped.Sequence'].map(group_counts).eq(1))
    selected = pr.loc[eligible].copy()
    selected['observed_n'] = selected[columns].notna().sum(axis=1)
    selected['median_intensity'] = selected[columns].median(axis=1)
    selected = selected.sort_values(['observed_n', 'median_intensity', 'Precursor.Charge', 'Precursor.Id'],
        ascending=[False, False, True, True], kind='stable').drop_duplicates(['Protein.Group', 'Stripped.Sequence'])
    sample_times = [s['time_min'] for s in analysis['samples']]
    base = [i for i,t in enumerate(sample_times) if t == analysis['baseline_time']]
    post = sorted(set(sample_times) - {analysis['baseline_time']})
    logs = np.log2(positive_matrix(selected, columns))
    sequence_records, protein_records = [], []
    for time in post:
        treatment = [i for i,t in enumerate(sample_times) if t == time]
        change, bn, tn = contrast(logs, base, treatment)
        genes = defaultdict(list)
        for i, row in enumerate(selected.to_dict('records')):
            if not np.isfinite(change[i]):
                continue
            record = {'protein_group': row['Protein.Group'], 'gene': row['Genes'],
                      'sequence': row['Stripped.Sequence'], 'precursor_id': row['Precursor.Id'],
                      'time_min': time, 'log2_change': change[i], 'baseline_n': int(bn[i]), 'treated_n': int(tn[i])}
            sequence_records.append(record)
            genes[row['Protein.Group'], row['Genes']].append(record)
        for (group, gene), contributions in genes.items():
            if len(contributions) < 2:
                continue
            vals = [r['log2_change'] for r in contributions]
            protein_records.append({'protein_group': group, 'gene': gene, 'time_min': time,
                'strict_log2_change': median(vals), 'peptide_n': len(vals),
                'positive_sequence_fraction': sum(v > 0 for v in vals) / len(vals),
                'sequences': ';'.join(sorted(r['sequence'] for r in contributions))})
    sequence_columns = ['protein_group', 'gene', 'sequence', 'precursor_id', 'time_min', 'log2_change', 'baseline_n', 'treated_n']
    protein_columns = ['protein_group', 'gene', 'time_min', 'strict_log2_change', 'peptide_n', 'positive_sequence_fraction', 'sequences']
    # Every phosphoform uses its OWN joint run mask; do not borrow all-run parent changes.
    selected_groups = {g: np.array(ix) for g, ix in selected.reset_index(drop=True).groupby('Protein.Group').indices.items()}
    joint_sensitivity = []
    forms = analysis['summary'].set_index('form_id')
    a = analysis['arrays']['A']
    form_index = {f:i for i,f in enumerate(analysis['summary'].form_id)}
    for row in analysis['comparisons'].query('included').to_dict('records'):
        group = forms.loc[row['form_id'], 'parent_pg']
        peptides = selected_groups.get(group, np.array([], dtype=int))
        joint = np.isfinite(a[form_index[row['form_id']]])
        b = [i for i in base if joint[i]]
        t = [i for i,x in enumerate(sample_times) if x == row['time_min'] and joint[i]]
        values = contrast(logs[peptides], b, t)[0]
        finite = values[np.isfinite(values)]
        parent = float(np.median(finite)) if len(finite) >= 2 else np.nan
        adjusted = row['U_joint'] - parent
        joint_sensitivity.append({'form_id': row['form_id'], 'time_min': row['time_min'],
            'strict_parent_joint_log2_change': parent, 'strict_peptide_n': len(finite),
            'strict_parent_A': adjusted, 'PG_parent_A': row['A'],
            'sign_retained': bool(adjusted * row['A'] > 0) if np.isfinite(adjusted) else None,
            'threshold_0p5_retained': bool((abs(adjusted) >= .5) == (abs(row['A']) >= .5)) if np.isfinite(adjusted) else None})
    return {'sequences': pd.DataFrame(sequence_records, columns=sequence_columns),
            'proteins': pd.DataFrame(protein_records, columns=protein_columns),
            'joint_sensitivity': pd.DataFrame(joint_sensitivity),
            'selected_sequences': selected[['Protein.Group', 'Genes', 'Stripped.Sequence', 'Precursor.Id', 'Precursor.Charge'] + columns]}


def late_layer(analysis, strict_proteins):
    samples = analysis['samples']
    columns = [s['original_column'] for s in samples]
    baseline = [i for i,s in enumerate(samples) if s['time_min'] == analysis['baseline_time']]
    protein = analysis['pg']
    values = np.log2(positive_matrix(protein, columns))
    records = []
    for time in sorted({s['time_min'] for s in samples} - {analysis['baseline_time']}):
        delta, bn, tn = contrast(values, baseline, [i for i,s in enumerate(samples) if s['time_min'] == time])
        for i, row in enumerate(protein.to_dict('records')):
            gene = str(row.get('Genes', '')).upper()
            if gene not in HELD_OUT_GENES:
                continue
            matched = strict_proteins[(strict_proteins.protein_group == row['Protein.Group']) & (strict_proteins.time_min == time)]
            strict = matched.iloc[0].strict_log2_change if len(matched) == 1 else np.nan
            records.append({'gene': gene, 'protein_group': row['Protein.Group'], 'time_min': time,
                'PG_log2_change': delta[i], 'strict_log2_change': strict, 'PG_baseline_n': int(bn[i]), 'PG_treated_n': int(tn[i]),
                'estimators_direction_agree': bool(delta[i] * strict > 0) if np.isfinite(delta[i]) and np.isfinite(strict) else None,
                'layer': 'late_validation' if time >= 60 else 'earlier_protein_context',
                'held_out_from_discovery': True, 'inference': 'same_experiment_descriptive_consistency_not_causality'})
    return pd.DataFrame(records)


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def held_out_temporal_context(kinase):
    frame = kinase['sensitivities']
    early = frame[frame['mode'].eq('held_out_discovery_A') & frame.time_min.le(30) & frame.coverage_adequate]
    records = []
    for entity, rows in early.groupby('entity'):
        for omitted in [None] + rows.time_min.tolist():
            retained = rows if omitted is None else rows[rows.time_min.ne(omitted)]
            if retained.empty:
                continue
            peak = retained.loc[retained.gene_balanced_mean.abs().idxmax()]
            records.append({'entity':entity, 'omitted_early_time_min':omitted,
                'early_times':';'.join(map(str, retained.time_min)),
                'early_mean_footprint':retained.gene_balanced_mean.mean(),
                'largest_absolute_sampled_response_time':peak.time_min,
                'interpretation':'sampled_time_sensitivity_not_estimated_causal_lag'})
    return pd.DataFrame(records)


def extend_and_export(analysis, mappings, edges, kinase, output, inputs, reference_dir=None):
    """A self-contained bundle with input bytes, masks, evidence, and runnable code."""
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new export directory; existing evidence must not be overwritten')
    output.mkdir(parents=True, exist_ok=True)
    strict = strict_unmodified_parent(analysis)
    tables = {name: analysis[name] for name in ['summary', 'runlevel', 'comparisons', 'detection']}
    tables.update({'site_mappings': mappings, 'all_edges': edges})
    tables.update({'kinase_' + k: v for k,v in kinase.items()})
    tables.update({'strict_parent_' + k: v for k,v in strict.items()})
    tables['held_out_protein_layer'] = late_layer(analysis, strict['proteins'])
    tables['held_out_early_time_omissions'] = held_out_temporal_context(kinase)
    for name, frame in tables.items():
        frame.to_csv(output / (name + '.csv'), index=False)
    (output / 'samples.json').write_text(json.dumps(analysis['samples'], indent=2))
    copied_inputs = {}
    (output / 'inputs').mkdir()
    for name, source in inputs.items():
        dest = output / 'inputs' / (name + Path(source).suffix)
        shutil.copyfile(source, dest)
        copied_inputs[name] = str(dest.relative_to(output))
    if reference_dir:
        provenance = output / 'frozen_source_audit'
        provenance.mkdir()
        for name in ['annotation_metadata.json', 'manual_primary_source_audit.tsv', 'pmid_16914728.json', 'pmid_42644392.json']:
            source = Path(reference_dir) / 'kinase' / name
            if not source.exists():
                source = Path(reference_dir) / name
            if source.exists():
                shutil.copyfile(source, provenance / name)
    (output / 'ptm_shared').mkdir()
    (output / 'ptm_shared/__init__.py').write_text('')
    for name in ['report_compatible_quantification.py', 'report_compatible_kinase.py', 'report_compatible_extensions.py']:
        shutil.copyfile(Path(__file__).parent / name, output / 'ptm_shared' / name)
    config = {'estimator_version': VERSION, 'baseline_time': analysis['baseline_time'], 'inputs': copied_inputs,
              'held_out_genes_before_discovery': sorted(HELD_OUT_GENES),
              'normalization': 'supplied_input_values_no_additional_scaling',
              'localization_probability': 'unknown_not_imputed',
              'strict_kinase_status': 'no_call_localization_unavailable',
              'replication': 'sample_metadata_required_for_biological_inference; this layer emits no p/q',
              'extensions_reference_status': 'new_implementation; original extension/ and counterfactual files absent from minimal bundle',
              'generated_utc': datetime.now(timezone.utc).isoformat()}
    (output / 'config.json').write_text(json.dumps(config, indent=2))
    (output / 'rerun.py').write_text('''import json, sys
from pathlib import Path
import pandas as pd
from ptm_shared.report_compatible_quantification import quantify_forms, read_fasta
from ptm_shared.report_compatible_kinase import frozen_edges, score_footprints
from ptm_shared.report_compatible_extensions import extend_and_export, file_digest
root = Path(__file__).resolve().parent
for name, record in json.loads((root / "manifest.json").read_text())["files"].items():
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path.stat().st_size != record["bytes"] or file_digest(path) != record["sha256"]:
        raise ValueError("Bundle integrity failure: " + name)
cfg = json.loads((root / "config.json").read_text())
inputs = {k: root / p for k, p in cfg["inputs"].items()}
a = quantify_forms(pd.read_csv(inputs["PR"], sep="\\t"), pd.read_csv(inputs["PG"], sep="\\t"),
                   read_fasta(inputs["FASTA"]), json.loads((root / "samples.json").read_text()), cfg["baseline_time"])
m, e = frozen_edges(a, pd.read_csv(inputs["snapshot"], sep="\\t"))
k = score_footprints(a, e)
extend_and_export(a, m, e, k, Path(sys.argv[1]), inputs, reference_dir=root / "frozen_source_audit")
''')
    (output / 'README.md').write_text('''# Astra evidence bundle

Install Python with numpy and pandas, then run `python rerun.py /path/to/new-output`.
The original PR/PG/FASTA and frozen annotation snapshot are in inputs/.
The manifest records file bytes and SHA-256. Reference retrieval time is preserved
in frozen_source_audit; generated_utc is only this export's execution time.

Read config.json, samples.json, summary.csv, runlevel.csv, comparisons.csv and
all_edges.csv before interpreting kinase_profiles.csv. Every comparison retains
observation masks; missing values are not zero. A = U_joint - P_joint on identical
injection masks. The legacy precursor mean-of-ratios estimator remains separate.

Kinase profiles are descriptive exploratory substrate footprints. Assigned sites
have unknown localization probability, so strict attribution is no-call. Rat
annotation is orthology translated; it is not evidence of direct rat validation.
Source, gene and injection omission are sensitivities, not confidence intervals.
The held-out gene list is fixed before scoring. Its late protein layer belongs
to the same experiment and does not prove causal direction or precise lag.

Original article extension files were not present in the minimal reference.
Strict parent and held-out results here are separately versioned calculations.
''')
    manifest = {str(p.relative_to(output)): {'bytes': p.stat().st_size, 'sha256': file_digest(p)}
                for p in sorted(output.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    (output / 'manifest.json').write_text(json.dumps({'schema_version': 'astra_evidence_bundle.v1', 'files': manifest}, indent=2))
    archive = output.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(output))
    return {'directory': str(output), 'zip': str(archive), 'sha256': file_digest(archive)}
