"""Independent charge-collapsed, mean-log quantification with explicit masks.

This versioned evidence layer supplements the legacy precursor estimator. It
consumes matrices and declared sample columns, never precomputed form results.
Assigned UniMod positions do not establish localization confidence.
"""
from collections import Counter, defaultdict
import json
import re
import warnings

import numpy as np
import pandas as pd

VERSION = 'charge_collapsed_mean_log_joint_ratio.v1'


def samples_from_manifest(manifest, condition_map):
    """Require explicit time labels; never infer biological units from filenames."""
    from .sample_manifest import validate_sample_manifest
    manifest = validate_sample_manifest(manifest, condition_map)
    times = {}
    for row in manifest.get('conditions', []):
        time = row.get('time_minutes')
        if time is None or not np.isfinite(float(time)) or row['condition'] in times:
            raise ValueError('Report-compatible export requires unique, finite declared condition times')
        times[row['condition']] = float(time)
    if (len(times) < 2 or set(times) != set(condition_map.values()) or times.get('Control') != 0
            or len(set(times.values())) != len(times)):
        raise ValueError('Report-compatible export requires every condition time, unique times, and Control at 0 minutes')
    if any(t < 0 for t in times.values()):
        raise ValueError('Treatment times must follow baseline')
    counters = Counter()
    samples = []
    for sample in manifest['samples']:
        condition = sample['condition']
        counters[condition] += 1
        time = times[condition]
        samples.append({'original_column': sample['sample_id'], 'run': sample['sample_id'],
                        'time_min': int(time) if time.is_integer() else time,
                        'run_suffix': counters[condition], 'biological_unit': sample['biological_unit'],
                        'technical_injection': sample.get('technical_injection'), 'condition': condition})
    return samples


def tokens(value):
    return [v for v in str(value).split(';') if v and v != 'nan']


def read_fasta(path):
    records = {}
    accession = None
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line.startswith('>'):
                parts = line[1:].split('|')
                accession = parts[1] if len(parts) >= 3 else parts[0].split()[0]
                if accession in records:
                    raise ValueError('Duplicate FASTA accession: ' + accession)
                gene = re.search(r'\bGN=(\S+)', line)
                records[accession] = {'sequence': '', 'gene': gene[1] if gene else '',
                                      'reviewed': line.startswith('>sp|')}
            elif accession:
                records[accession]['sequence'] += line
    return records


def assigned_positions(sequence):
    # Count residues after removing each annotation, preserving assigned offsets.
    position, result = 0, []
    for token in re.findall(r'\([^)]*\)|[A-Z]', sequence):
        if token == '(UniMod:21)':
            result.append(position)
        elif len(token) == 1:
            position += 1
    return result


def map_form(row, fasta):
    positions = assigned_positions(row['Modified.Sequence'])
    accessions = list(dict.fromkeys(tokens(row['Protein.Ids']) + tokens(row['Protein.Group'])))
    backbone = row['Stripped.Sequence']
    if not positions or min(positions) < 1 or max(positions) > len(backbone):
        raise ValueError('Invalid assigned phosphoresidue offset')
    mappings = []
    for accession in accessions:
        entry = fasta.get(accession)
        if not entry:
            continue
        start = entry['sequence'].find(backbone)
        while start >= 0:
            mappings.append({'accession': accession, 'gene': entry['gene'], 'start': start + 1,
                             'sites': [f'{backbone[p-1]}{start+p}' for p in positions],
                             'reviewed': entry['reviewed']})
            start = entry['sequence'].find(backbone, start + 1)
    mapped_genes = {m['gene'].upper() for m in mappings if m['gene']}
    repeated = max(Counter(m['accession'] for m in mappings).values(), default=0) > 1
    coordinates = {tuple(m['sites']) for m in mappings}
    status = ('unmapped' if not mappings else 'multiple_genes' if len(mapped_genes) > 1
              else 'multiple_positions' if repeated else 'single_gene_isoform_coordinates'
              if len(coordinates) > 1 else 'single_gene_consistent_coordinates')
    group = tokens(row['Protein.Group'])
    mappings.sort(key=lambda m: (not (m['reviewed'] and '-' not in m['accession']),
                                m['accession'] not in group, not m['reviewed'],
                                accessions.index(m['accession']), m['start']))
    representative = mappings[0] if mappings else {}
    exported_genes = {g.upper() for g in tokens(row.get('Genes', ''))}
    discordant = bool(exported_genes and mapped_genes and exported_genes != mapped_genes)
    return {'n_phosphates': len(positions), 'mapping_status': status,
            'mapping_json': json.dumps(mappings, separators=(',', ':')),
            'mapped_genes': ';'.join(sorted(mapped_genes)), 'annotation_gene_discordant': discordant,
            'representative_accession': representative.get('accession', ''),
            'representative_gene': representative.get('gene', ''),
            'representative_sites': ';'.join(representative.get('sites', [])),
            'sites_all': '|'.join(m['accession'] + ':' + ','.join(m['sites']) for m in mappings),
            'primary_mapping_eligible': status.startswith('single_gene_') and not discordant,
            'localization_probability_available': False, 'localization_probability': None,
            'strict_attribution_status': 'no_call_localization_unavailable'}


def positive_matrix(frame, columns):
    values = frame[columns].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    return np.where(np.isfinite(values) & (values > 0), values, np.nan)


def mean_or_nan(values, axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.nanmean(values, axis=axis)


def contrast(values, baseline, treated, minimum=2):
    b, t = values[..., baseline], values[..., treated]
    bn, tn = np.isfinite(b).sum(axis=-1), np.isfinite(t).sum(axis=-1)
    return np.where((bn >= minimum) & (tn >= minimum), mean_or_nan(t, -1) - mean_or_nan(b, -1), np.nan), bn, tn


def quantify_forms(pr, pg, fasta, samples, baseline_time=0):
    """samples: explicit original_column/run/time_min/run_suffix records.

    Sample suffixes are observation IDs, not biological units. This descriptive
    layer never computes biological p/q, imputes, or scales its supplied values.
    """
    columns = [s['original_column'] for s in samples]
    if len(set(columns)) != len(columns) or len({s['run'] for s in samples}) != len(samples):
        raise ValueError('Sample and run identifiers must be unique')
    times = sorted({s['time_min'] for s in samples})
    if baseline_time not in times or len(times) < 2:
        raise ValueError('Declared baseline and at least one treatment time are required')
    indices = {t: np.array([i for i, s in enumerate(samples) if s['time_min'] == t]) for t in times}
    if pg['Protein.Group'].duplicated().any():
        raise ValueError('Parent protein group is not unique')
    pr, pg = pr.copy(), pg.copy()
    pr[columns], pg[columns] = positive_matrix(pr, columns), positive_matrix(pg, columns)
    parent_rows = dict(zip(pg['Protein.Group'].astype(str), range(len(pg))))
    accession_parents = defaultdict(set)
    for i, group in enumerate(pg['Protein.Group']):
        for accession in tokens(group):
            accession_parents[accession].add(i)
    forms, intensities, best_charges, observed, parents = [], [], [], [], []
    phospho = pr[pr['Modified.Sequence'].str.contains('(UniMod:21)', regex=False, na=False)]
    for (group, modified), rows in phospho.groupby(['Protein.Group', 'Modified.Sequence'], sort=False, dropna=False):
        row = rows.iloc[0]
        record = {k: row[k] for k in ['Protein.Group', 'Protein.Ids', 'Genes', 'Stripped.Sequence', 'Modified.Sequence']}
        for key in ['Protein.Ids', 'Genes', 'Stripped.Sequence']:
            if rows[key].fillna('').nunique() > 1:
                raise ValueError(f'Conflicting form metadata: {group}, {modified}, {key}')
        record.update(form_id=f'PF{len(forms)+1:05d}', **map_form(row, fasta))
        parent_index, match = parent_rows.get(str(group)), 'exact_protein_group'
        if parent_index is None:
            for field, label in [('Protein.Group', 'group_accession'), ('Protein.Ids', 'protein_ids')]:
                hits = set().union(*(accession_parents[a] for a in tokens(row[field])))
                if hits:
                    parent_index = next(iter(hits)) if len(hits) == 1 else None
                    match = ('unique_' + label + '_overlap') if len(hits) == 1 else ('ambiguous_group_overlap' if field == 'Protein.Group' else 'ambiguous_ids_overlap')
                    break
            else:
                match = 'not_found'
        parent_group = pg.iloc[parent_index]['Protein.Group'] if parent_index is not None else ''
        parent_genes = {fasta.get(a, {}).get('gene', '').upper() for a in tokens(parent_group)} - {''}
        mapped_genes = set(tokens(record['mapped_genes']))
        concordant = len(parent_genes) == 1 and parent_genes == mapped_genes
        record.update(parent_pg=parent_group, parent_match=match, parent_gene_concordant=concordant,
                      parent_pg_fasta_genes=';'.join(sorted(parent_genes)),
                      primary_adjustment_eligible=record['primary_mapping_eligible'] and concordant and parent_index is not None)
        values = rows[columns].to_numpy(float)
        counts = np.isfinite(values).sum(axis=0)
        sums = np.where(counts, np.nansum(values, axis=0), np.nan)
        medians = rows[columns].median(axis=1).to_numpy(float)
        chosen = min(range(len(rows)), key=lambda i: (-np.isfinite(values[i]).sum(),
                     -medians[i] if np.isfinite(medians[i]) else float('inf'), int(rows.iloc[i]['Precursor.Charge'])))
        record.update(precursor_count=len(rows), sensitivity_charge=int(rows.iloc[chosen]['Precursor.Charge']),
                      charge_coverage_varies=len(set(counts[counts > 0])) > 1)
        forms.append(record); intensities.append(sums); best_charges.append(values[chosen]); observed.append(counts)
        parents.append(pg.iloc[parent_index][columns].to_numpy(float) if parent_index is not None else np.full(len(columns), np.nan))
    if not forms:
        raise ValueError('No phosphoforms in supplied input')
    summary = pd.DataFrame(forms)
    intensity, parent, single = map(np.asarray, (intensities, parents, best_charges))
    u, p, sc = np.log2(intensity), np.log2(parent), np.log2(single)
    a = u - p
    arrays = {'U': u, 'P': p, 'A': a, 'U_singlecharge': sc, 'A_singlecharge': sc - p}
    base = indices[baseline_time]
    for name, values in arrays.items():
        summary[f'{name}_n_0'] = np.isfinite(values[:, base]).sum(axis=1)
        summary[f'{name}_meanlog2_0'] = mean_or_nan(values[:, base], 1)
        for time in times:
            if time == baseline_time:
                continue
            delta, _, n = contrast(values, base, indices[time])
            summary[f'{name}_n_{time}'] = n
            summary[f'{name}_log2FC_{time}'] = delta
    post = [t for t in times if t != baseline_time]
    summary['A_evaluable_time_count'] = summary[[f'A_log2FC_{t}' for t in post]].notna().sum(axis=1)
    summary['baseline_undetected_all_runs'] = summary.U_n_0.eq(0)
    summary['baseline_insufficient_lt2'] = summary.U_n_0.lt(2)
    summary['post_only_detected_ge2_any_time'] = summary.U_n_0.eq(0) & summary[[f'U_n_{t}' for t in post]].ge(2).any(axis=1)
    runlevel, comparisons, detection = [], [], []
    for i, form in enumerate(forms):
        for j, sample in enumerate(samples):
            runlevel.append({'form_id': form['form_id'], **sample, 'phospho_intensity': intensity[i,j],
                'parent_intensity': parent[i,j], 'phospho_log2': u[i,j], 'parent_log2': p[i,j],
                'adjusted_log2_ratio': a[i,j], 'singlecharge_intensity': single[i,j],
                'observed_charges': int(observed[i][j]), 'U_observed': bool(np.isfinite(u[i,j])),
                'P_observed': bool(np.isfinite(p[i,j])), 'joint_observed': bool(np.isfinite(a[i,j]))})
        joint = np.isfinite(a[i])
        first = next((t for t in post if np.isfinite(u[i, indices[t]]).sum() >= 2), None)
        first_joint = next((t for t in post if joint[indices[t]].sum() >= 2), None)
        for time in post:
            treated = indices[time]
            uj, bn, tn = contrast(np.where(joint, u[i], np.nan), base, treated)
            pj, _, _ = contrast(np.where(joint, p[i], np.nan), base, treated)
            av = summary.loc[i, f'A_log2FC_{time}']
            excluded = []
            if not form['primary_mapping_eligible']:
                excluded.append('mapping_or_gene_annotation_ineligible')
            if not form['parent_gene_concordant']:
                excluded.append('parent_gene_discordant_or_unavailable')
            if bn < 2:
                excluded.append('baseline_joint_observations_lt2')
            if tn < 2:
                excluded.append('treated_joint_observations_lt2')
            comparisons.append({'form_id': form['form_id'], 'time_min': time,
                'primary_adjustment_eligible': form['primary_adjustment_eligible'],
                'included': bool(form['primary_adjustment_eligible'] and np.isfinite(av)),
                'exclusion_reasons': ';'.join(excluded),
                'baseline_joint_n': int(bn), 'treated_joint_n': int(tn),
                'baseline_joint_runs': ';'.join(samples[j]['run'] for j in base if joint[j]),
                'treated_joint_runs': ';'.join(samples[j]['run'] for j in treated if joint[j]),
                'U_all': summary.loc[i, f'U_log2FC_{time}'], 'P_all': summary.loc[i, f'P_log2FC_{time}'],
                'U_joint': float(uj), 'P_joint': float(pj), 'A': av,
                'decomposition_residual': av - (uj - pj), 'parent_correction': -float(pj),
                'material_correction_ge_0p5': bool(np.isfinite(pj) and abs(pj) >= .5),
                'sign_reversal': bool(np.isfinite(av) and uj * av < 0),
                'threshold_crossing_0p5': bool(np.isfinite(av) and (abs(uj) >= .5) != (abs(av) >= .5)),
                'biological_p_value': None, 'biological_q_value': None})
            post_u = float(contrast(u[i], indices[first], treated)[0]) if first is not None and time >= first else np.nan
            post_a = float(contrast(a[i], indices[first_joint], treated)[0]) if first_joint is not None and time >= first_joint else np.nan
            detection.append({'form_id': form['form_id'], 'time_min': time,
                'baseline_n': int(np.isfinite(u[i,base]).sum()), 'detected_n': int(np.isfinite(u[i,treated]).sum()),
                'scheduled_n': len(treated), 'first_ge2_time': first, 'first_joint_ge2_time': first_joint,
                'baseline_status': 'undetected' if not np.isfinite(u[i,base]).any() else 'insufficient' if np.isfinite(u[i,base]).sum() < 2 else 'evaluable',
                'post_reference_U': post_u, 'post_reference_A': post_a,
                'interpretation': 'post_reference_change_is_not_baseline_fold_change'})
    return {'summary': summary, 'runlevel': pd.DataFrame(runlevel), 'comparisons': pd.DataFrame(comparisons),
            'detection': pd.DataFrame(detection), 'samples': samples, 'arrays': arrays, 'fasta': fasta,
            'pr': pr, 'pg': pg, 'baseline_time': baseline_time, 'version': VERSION}
