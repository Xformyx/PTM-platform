import numpy as np
import pandas as pd
import pytest

from ptm_shared.report_compatible_quantification import quantify_forms, map_form, samples_from_manifest
from ptm_shared.report_compatible_kinase import footprint_statistics, aggregate_rows, frozen_edges, score_footprints
from ptm_shared.report_compatible_extensions import strict_unmodified_parent


def fixture():
    columns = ['b1','b2','b3','t1','t2','t3']
    base = {'Protein.Group': 'ISO', 'Protein.Ids': 'ISO;CAN', 'Genes': 'GENE',
            'Stripped.Sequence': 'ASK', 'Modified.Sequence': 'AS(UniMod:21)K', 'Proteotypic': 1}
    pr = pd.DataFrame([{**base, 'Precursor.Id': 'p2', 'Precursor.Charge': 2, **dict(zip(columns,[1,3,100,2,6,200]))},
                       {**base, 'Precursor.Id': 'p3', 'Precursor.Charge': 3, **dict(zip(columns,[1,np.nan,np.nan,2,np.nan,np.nan]))}])
    pg = pd.DataFrame([{'Protein.Group':'ISO', 'Genes':'GENE', **dict(zip(columns,[1,1,np.nan,1,1,1]))}])
    fasta = {'ISO': {'sequence':'XXASKZZ', 'gene':'Gene', 'reviewed':False},
             'CAN': {'sequence':'ASKZZ', 'gene':'Gene', 'reviewed':True}}
    samples = [{'original_column': c,'run':c,'time_min': 0 if c[0]=='b' else 5,'run_suffix':i%3+1} for i,c in enumerate(columns)]
    return pr, pg, fasta, samples


def test_charge_collapse_missingness_and_exact_joint_decomposition():
    analysis = quantify_forms(*fixture())
    row = analysis['comparisons'].iloc[0]
    assert analysis['summary'].iloc[0].primary_adjustment_eligible
    assert analysis['runlevel'].iloc[1].phospho_intensity == 3
    assert analysis['runlevel'].iloc[0].phospho_intensity == 2
    assert row.baseline_joint_n == 2
    assert row.baseline_joint_runs == 'b1;b2'
    assert row.A == pytest.approx(row.U_joint-row.P_joint)
    assert row.U_all != pytest.approx(row.U_joint)
    assert pd.isna(row.biological_p_value)


def test_canonical_coordinates_keep_isoform_crosswalk():
    pr, _, fasta, _ = fixture()
    result = map_form(pr.iloc[0], fasta)
    assert result['representative_accession'] == 'CAN'
    assert result['representative_sites'] == 'S2'
    assert 'ISO:S4' in result['sites_all']
    assert result['mapping_status'] == 'single_gene_isoform_coordinates'
    assert result['localization_probability'] is None


def test_multiple_parent_groups_do_not_gain_eligibility():
    pr, pg, fasta, samples = fixture()
    pg = pd.concat([pg.assign(**{'Protein.Group':'ISO;X'}), pg.assign(**{'Protein.Group':'ISO;Y'})], ignore_index=True)
    result = quantify_forms(pr,pg,fasta,samples)
    assert result['summary'].iloc[0].parent_match == 'ambiguous_group_overlap'
    assert not result['comparisons'].included.any()


def test_baseline_absent_uses_post_reference_without_pseudocount():
    pr,pg,fasta,samples = fixture()
    pr[['b1','b2','b3']] = np.nan
    result = quantify_forms(pr,pg,fasta,samples)
    assert np.isnan(result['comparisons'].iloc[0].A)
    assert result['detection'].iloc[0].baseline_status == 'undetected'
    assert result['detection'].iloc[0].first_ge2_time == 5
    assert result['detection'].iloc[0].post_reference_U == 0


def test_gene_balancing_and_coverage_do_not_count_forms_as_sites():
    rows = [{'form_id': f, 'substrate_gene':g, 'site_key':s} for f,g,s in
            [('f1','A','A:S1'),('f2','A','A:S1'),('f3','A','A:S2'),('f4','B','B:S1')]]
    sites, genes, _ = aggregate_rows(rows, {'f1':1,'f2':3,'f3':4,'f4':-1})
    stats = footprint_statistics(sites, genes)
    assert sites['A','A:S1'] == 2
    assert genes['A'] == 3
    assert stats['gene_balanced_mean'] == 1
    assert stats['n_sites_or_units'] == 3
    assert stats['descriptive_pattern'] == 'no_call_insufficient_coverage'


def test_strict_parent_excludes_backbones_seen_modified_and_requires_two_sequences():
    pr,pg,fasta,samples = fixture()
    extra = []
    for seq in ['PEP','AAA','ASK']:
        extra.append({**pr.iloc[0].to_dict(), 'Stripped.Sequence':seq, 'Modified.Sequence':seq,
                      'Precursor.Id':seq, **dict(zip(['b1','b2','b3','t1','t2','t3'],[1,1,1,2,2,2]))})
    analysis = quantify_forms(pd.concat([pr, pd.DataFrame(extra)], ignore_index=True),pg,fasta,samples)
    strict = strict_unmodified_parent(analysis)
    assert set(strict['selected_sequences']['Stripped.Sequence']) == {'PEP','AAA'}
    assert strict['proteins'].iloc[0].strict_log2_change == 1
    assert strict['joint_sensitivity'].iloc[0].strict_peptide_n == 2


def test_export_requires_explicit_complete_time_design():
    manifest = {'samples':[{'sample_id':'a','condition':'Control','biological_unit':'one'},
                           {'sample_id':'b','condition':'5min','biological_unit':'two'}],
                'conditions':[{'condition':'Control','time_minutes':0},{'condition':'5min','time_minutes':5}]}
    assert samples_from_manifest(manifest, {'a':'Control','b':'5min'})[1]['time_min'] == 5
    del manifest['conditions'][1]['time_minutes']
    with pytest.raises(ValueError, match='declared condition times'):
        samples_from_manifest(manifest, {'a':'Control','b':'5min'})


def test_empty_annotation_does_not_invent_a_kinase_score():
    analysis = quantify_forms(*fixture())
    snapshot = pd.DataFrame(columns=['enzyme','substrate','residue_type','residue_offset','modification','sources','references'])
    snapshot['residue_offset'] = snapshot.residue_offset.astype('int64')
    _, edges = frozen_edges(analysis, snapshot)
    results = score_footprints(analysis, edges)
    assert results['profiles'].gene_balanced_mean.isna().all()
    assert not results['profiles'].coverage_adequate.any()
    assert results['site_scores'].empty
