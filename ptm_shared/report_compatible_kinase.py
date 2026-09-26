"""Frozen-snapshot exploratory footprints; strict attribution remains separate."""
from collections import defaultdict
from itertools import product
from statistics import mean, median

import numpy as np
import pandas as pd

from .report_compatible_quantification import tokens, assigned_positions, contrast

VERSION = 'gene_balanced_frozen_substrate_footprint.v1'
CURATED = {'PhosphoSite', 'SIGNOR', 'HPRD', 'phosphoELM'}
NONCATALYTIC = {'Ccnb1', 'Ccne2', 'Csnk2b', 'Prkab1', 'Prkab2', 'Prkag1', 'Prkag2', 'Prkag3'}
FAMILIES = {'AKT_family': ['Akt1', 'Akt2', 'Akt3'], 'ERK1_2_family': ['Mapk1', 'Mapk3'],
            'MEK1_2_family': ['Map2k1', 'Map2k2'], 'mTOR': ['Mtor'],
            'S6K_family': ['Rps6kb1', 'Rps6kb2'], 'RSK_family': ['Rps6ka1', 'Rps6ka2', 'Rps6ka3', 'Rps6ka6'],
            'GSK3_family': ['Gsk3a', 'Gsk3b']}
# Frozen before discovery scoring. The internal same-experiment validation is
# descriptive and does not constitute inhibitor or biological replication.
HELD_OUT_GENES = frozenset({'FOSL1', 'FOSL2', 'JUN', 'JUNB', 'CCND1', 'IRS1'})


def frozen_edges(analysis, snapshot):
    """Exact accession/residue joins from raw form sequences, with excluded edges."""
    fasta = analysis['fasta']
    sites = []
    for form in analysis['summary'].to_dict('records'):
        sequence = form['Stripped.Sequence']
        for accession in tokens(form['Protein.Ids']):
            entry = fasta.get(accession)
            if not entry:
                continue
            protein = entry['sequence']
            start = protein.find(sequence)
            while start >= 0:
                for position in assigned_positions(form['Modified.Sequence']):
                    offset = start + position
                    window = protein[max(0, offset-8):offset-1] + protein[offset-1].lower() + protein[offset:offset+7]
                    sites.append({k: form[k] for k in ['form_id', 'Protein.Group', 'Modified.Sequence', 'Stripped.Sequence', 'Genes']} | {
                        'mapped_accession': accession, 'residue_offset': offset, 'residue_type': protein[offset-1],
                        'fasta_gene': entry['gene'], 'site_window': window})
                start = protein.find(sequence, start + 1)
    mapping_columns = ['form_id', 'Protein.Group', 'Modified.Sequence', 'Stripped.Sequence', 'Genes',
                       'mapped_accession', 'residue_offset', 'residue_type', 'fasta_gene', 'site_window']
    mapped = pd.DataFrame(sites, columns=mapping_columns)
    mapped['residue_offset'] = mapped.residue_offset.astype('int64')
    annotations = snapshot[snapshot.modification.eq('phosphorylation')]
    edges = mapped.merge(annotations, left_on=['mapped_accession', 'residue_offset', 'residue_type'],
                         right_on=['substrate', 'residue_offset', 'residue_type'], how='inner')
    all_genes = mapped.groupby('form_id').fasta_gene.agg(lambda s: set(s) - {''})
    records = []
    for row in edges.to_dict('records'):
        kinase = 'Stk38l' if row['enzyme'] == 'A4GW50' else fasta.get(row['enzyme'], {}).get('gene') or row['enzyme']
        resources = CURATED.intersection(tokens(row['sources']))
        excluded = ('noncatalytic' if kinase in NONCATALYTIC else 'no_curated_resource' if not resources
                    else 'GSK3_priming_site_not_direct_substrate_PMID16611631' if
                    (kinase, row['fasta_gene'], row['residue_type'], row['residue_offset']) == ('Gsk3b', 'Dpysl3', 'S', 522)
                    else 'multiple_mapped_genes' if len(all_genes[row['form_id']]) > 1 else '')
        row.update(kinase_gene=kinase, site_key=row['fasta_gene'].upper() + ':' + row['site_window'],
                   site_id=row['fasta_gene'] + ':' + row['residue_type'] + str(row['residue_offset']),
                   substrate_gene=row['fasta_gene'].upper(), curated_resources=';'.join(sorted(resources)),
                   curated_references=';'.join(sorted(r for r in set(tokens(row['references'])) if r.split(':')[0] in CURATED)),
                   exclusion_reason=excluded, primary_edge_eligible=not excluded,
                   source_caution='HNRNPA1_S6K_PMID16914728_PMID42644392' if kinase in FAMILIES['S6K_family'] and row['fasta_gene'].upper() == 'HNRNPA1' and row['residue_offset'] == 6 else '',
                   localization_probability=None, strict_eligible=False,
                   strict_status='no_call_localization_unavailable',
                   orthology_status='human_to_rat_translated_not_rat_experimental_validation')
        records.append(row)
    if records:
        return mapped, pd.DataFrame(records)
    return mapped, pd.DataFrame(columns=list(edges.columns) + ['kinase_gene', 'site_key', 'site_id',
        'substrate_gene', 'curated_resources', 'curated_references', 'exclusion_reason', 'primary_edge_eligible',
        'source_caution', 'localization_probability', 'strict_eligible', 'strict_status', 'orthology_status'])


def aggregate_rows(rows, values):
    contributions = defaultdict(list)
    supporting = defaultdict(list)
    for row in rows:
        value = values.get(row['form_id'], np.nan)
        if np.isfinite(value):
            key = (row['substrate_gene'], row.get('feature_key', row['site_key']))
            contributions[key].append(float(value))
            supporting[key].append(row)
    sites = {k: median(v) for k, v in contributions.items()}
    per_gene = defaultdict(list)
    for (gene, _), value in sites.items():
        per_gene[gene].append(value)
    genes = {gene: median(v) for gene, v in sorted(per_gene.items())}
    return sites, genes, supporting


def footprint_statistics(sites, genes):
    values = list(genes.values())
    n = len(values)
    score = mean(values) if values else np.nan
    leave_one_out = [mean(values[:i] + values[i+1:]) for i in range(n)] if n > 1 else []
    positive = sum(v > 0 for v in values) / n if n else np.nan
    negative = sum(v < 0 for v in values) / n if n else np.nan
    adequate = len(sites) >= 5 and n >= 3
    pattern = 'no_call_insufficient_coverage' if not adequate else 'mixed_or_small'
    if adequate and score >= .25 and positive >= 2/3 and all(v > 0 for v in leave_one_out):
        pattern = 'coherent_increase'
    elif adequate and score <= -.25 and negative >= 2/3 and all(v < 0 for v in leave_one_out):
        pattern = 'coherent_decrease'
    return {'n_sites_or_units': len(sites), 'n_substrate_genes': n, 'gene_balanced_mean': score,
            'gene_balanced_median': median(values) if n else np.nan,
            'gene_direction_positive_fraction': positive, 'gene_direction_negative_fraction': negative,
            'site_positive_fraction': sum(v > 0 for v in sites.values()) / len(sites) if sites else np.nan,
            'loo_gene_min': min(leave_one_out, default=np.nan), 'loo_gene_max': max(leave_one_out, default=np.nan),
            'loo_gene_sign_stable': bool(leave_one_out and (all(v > 0 for v in leave_one_out) or all(v < 0 for v in leave_one_out))),
            'coverage_adequate': adequate, 'descriptive_pattern': pattern, 'substrate_genes': ';'.join(genes)}


def score_footprints(analysis, all_edges, run_omissions=True):
    summary = analysis['summary'].set_index('form_id')
    times = sorted({s['time_min'] for s in analysis['samples']} - {analysis['baseline_time']})
    primary_edges = all_edges.loc[all_edges.primary_edge_eligible.astype(bool)]
    entities = {k: [k] for k in sorted(primary_edges.kinase_gene.unique())} | FAMILIES
    expanded = {}
    for row in primary_edges.to_dict('records'):
        for entity, members in entities.items():
            if row['kinase_gene'] not in members:
                continue
            key = (entity, row['site_key'], row['form_id'])
            if key not in expanded:
                expanded[key] = {**row, 'entity': entity, 'supporting_members': set(), 'site_aliases': set(), 'resources': set()}
            expanded[key]['supporting_members'].add(row['kinase_gene'])
            expanded[key]['site_aliases'].add(row['site_id'])
            expanded[key]['resources'].update(tokens(row['curated_resources']))
    selection = [r for r in expanded.values() if summary.loc[r['form_id'], 'primary_adjustment_eligible']]
    primary = [r for r in selection if summary.loc[r['form_id'], 'n_phosphates'] == 1]
    by_entity = {e: [r for r in primary if r['entity'] == e] for e in entities}
    all_by_entity = {e: [r for r in selection if r['entity'] == e] for e in entities}
    scores, sites_export, genes_export, omission_export, sensitivities, strict = [], [], [], [], [], []
    mode_membership, gene_omissions = [], []
    modes = {'primary_A': 'A', 'singlecharge_A': 'A_singlecharge', 'complete3_A': 'A',
             'fixed_site_panel_A': 'A', 'unadjusted_U': 'U', 'parent_P': 'P', 'multisite_component_A': 'A'}
    values = {(axis, t): summary[f'{axis}_log2FC_{t}'].to_dict() for axis in set(modes.values()) for t in times}
    for entity in entities:
        rows = by_entity[entity]
        fixed = set.intersection(*[{r['site_key'] for r in rows if np.isfinite(values['A',t][r['form_id']])} for t in times])
        # Connected components do not turn a multisite peptide into independent evidence.
        links = defaultdict(set)
        for r in all_by_entity[entity]:
            links[r['form_id']].add(r['site_key'])
        components = {r['site_key']: {r['site_key']} for r in all_by_entity[entity]}
        for connected in links.values():
            union = set().union(*(components[s] for s in connected))
            for site in union:
                components[site] = union
        multi = [{**r, 'feature_key': min(components[r['site_key']])} for r in all_by_entity[entity]]
        for time in times:
            for mode, axis in modes.items():
                selected = multi if mode == 'multisite_component_A' else rows
                if mode == 'fixed_site_panel_A':
                    selected = [r for r in selected if r['site_key'] in fixed]
                elif mode == 'complete3_A':
                    selected = [r for r in selected if summary.loc[r['form_id'], 'A_n_0'] == 3 and summary.loc[r['form_id'], f'A_n_{time}'] == 3]
                elif mode in {'unadjusted_U', 'parent_P'}:
                    selected = [r for r in selected if np.isfinite(values['A',time][r['form_id']])]
                sites, genes, supporting = aggregate_rows(selected, values[axis,time])
                scores.append({'entity': entity, 'mode': mode, 'time_min': time, **footprint_statistics(sites, genes),
                               'evidence_tier': 'exploratory_footprint', 'biological_p_value': None})
                for (gene, site), value in sites.items():
                    mode_membership.append({'entity':entity, 'mode':mode, 'time_min':time,
                        'substrate_gene':gene, 'feature_key':site, 'contribution':value,
                        'form_ids':';'.join(sorted({r['form_id'] for r in supporting[gene,site]}))})
                if mode == 'primary_A':
                    for omitted in genes:
                        gene_omissions.append({'entity':entity, 'time_min':time, 'omitted_gene':omitted,
                            **footprint_statistics({k:v for k,v in sites.items() if k[0] != omitted},
                                                   {g:v for g,v in genes.items() if g != omitted})})
                    for (gene, site), value in sites.items():
                        support = supporting[gene, site]
                        forms = sorted({r['form_id'] for r in support})
                        sites_export.append({'entity': entity, 'time_min': time, 'substrate_gene': gene, 'site_key': site,
                            'A_log2FC': value, 'n_forms': len(forms), 'form_ids': ';'.join(forms),
                            'site_aliases': ';'.join(sorted(set().union(*(r['site_aliases'] for r in support)))),
                            'supporting_kinases': ';'.join(sorted(set().union(*(r['supporting_members'] for r in support))))})
                    genes_export.extend({'entity': entity, 'time_min': time, 'substrate_gene': g, 'A_log2FC': v,
                                         'site_count': sum(k[0] == g for k in sites)} for g,v in genes.items())
            # Source omission and held-out discovery are separate analyses, never tuning primary.
            selections = {'held_out_discovery_A': [r for r in rows if r['substrate_gene'] not in HELD_OUT_GENES],
                          'S6K_source_caution': [r for r in rows if not r['source_caution']]}
            selections.update({'omit_source_' + source: [r for r in rows if r['resources'] - {source}] for source in sorted(CURATED)})
            for mode, selected in selections.items():
                if mode == 'S6K_source_caution' and entity != 'S6K_family':
                    continue
                sites, genes, _ = aggregate_rows(selected, values['A',time])
                sensitivities.append({'entity': entity, 'mode': mode, 'time_min': time, **footprint_statistics(sites, genes)})
            strict.append({'entity': entity, 'time_min': time, 'evidence_tier': 'strict', 'score': None,
                           'status': 'no_call_localization_unavailable', 'eligible_sites': 0})
    if run_omissions:
        arr = analysis['arrays']['A']
        samples = analysis['samples']
        base = [i for i,s in enumerate(samples) if s['time_min'] == analysis['baseline_time']]
        form_ids = analysis['summary'].form_id.tolist()
        for time in times:
            treatment = [i for i,s in enumerate(samples) if s['time_min'] == time]
            for db, dt in product([None] + base, [None] + treatment):
                if db is None and dt is None:
                    continue
                delta = contrast(arr, [i for i in base if i != db], [i for i in treatment if i != dt])[0]
                delta_by_form = dict(zip(form_ids, delta))
                for entity, rows in by_entity.items():
                    sites, genes, _ = aggregate_rows(rows, delta_by_form)
                    omission_export.append({'entity': entity, 'time_min': time,
                        'omit_baseline_run': samples[db]['run_suffix'] if db is not None else None,
                        'omit_treatment_run': samples[dt]['run_suffix'] if dt is not None else None,
                        **footprint_statistics(sites, genes)})
    site_sets = {entity: {r['site_key'] for r in sites_export if r['entity'] == entity} for entity in entities}
    overlap = []
    names = sorted(entities)
    for i, left in enumerate(names):
        for right in names[i+1:]:
            shared = site_sets[left] & site_sets[right]
            if shared:
                overlap.append({'entity_a': left, 'entity_b': right, 'n_a': len(site_sets[left]), 'n_b': len(site_sets[right]),
                                'n_shared': len(shared), 'shared_site_keys': ';'.join(sorted(shared)),
                                'jaccard': len(shared) / len(site_sets[left] | site_sets[right])})
    return {'profiles': pd.DataFrame(scores), 'site_scores': pd.DataFrame(sites_export,
                columns=['entity','time_min','substrate_gene','site_key','A_log2FC','n_forms','form_ids','site_aliases','supporting_kinases']),
            'gene_scores': pd.DataFrame(genes_export, columns=['entity','time_min','substrate_gene','A_log2FC','site_count']),
            'omissions': pd.DataFrame(omission_export, columns=['entity','time_min','omit_baseline_run','omit_treatment_run'] + list(footprint_statistics({},{}))),
            'sensitivities': pd.DataFrame(sensitivities), 'strict': pd.DataFrame(strict), 'overlap': pd.DataFrame(overlap),
            'mode_membership':pd.DataFrame(mode_membership, columns=['entity','mode','time_min','substrate_gene','feature_key','contribution','form_ids']),
            'gene_omissions':pd.DataFrame(gene_omissions, columns=['entity','time_min','omitted_gene'] + list(footprint_statistics({},{})))}
