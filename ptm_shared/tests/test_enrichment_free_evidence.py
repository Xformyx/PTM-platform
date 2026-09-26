import json
import numpy as np
import pandas as pd
import pytest

from ptm_shared.report_compatible_quantification import quantify_forms
from ptm_shared.report_compatible_kinase import frozen_edges, score_footprints, emergent_kinase_evidence, aggregate_rows
from ptm_shared.evidence_metadata import form_evidence_status
from ptm_shared.enrichment_free_profile import annotation_snapshot, validate_profile, EXPORT_MODE
from ptm_shared.enrichment_free_workflow import recorded_run
from ptm_shared.report_compatible_extensions import file_digest
from test_report_compatible_quantification import fixture


def annotations():
    return pd.DataFrame([{'enzyme':'Akt1','substrate':'CAN','residue_type':'S','residue_offset':2,
        'modification':'phosphorylation','sources':'PhosphoSite','references':'PhosphoSite:123'}])


def test_joint_comparison_uses_joint_values_and_preserves_legacy_mode():
    analysis=quantify_forms(*fixture())
    _,edges=frozen_edges(analysis,annotations())
    result=score_footprints(analysis,edges,run_omissions=False)
    old=result['profiles'].query("entity == 'Akt1'").set_index('mode')
    new=result['comparison_profiles_v2'].query("entity == 'Akt1'").set_index('mode')
    form=analysis['comparisons'].iloc[0]
    assert old.loc['unadjusted_U','gene_balanced_mean']==pytest.approx(form.U_all)
    assert new.loc['unadjusted_U_all_observed','gene_balanced_mean']==pytest.approx(form.U_all)
    assert new.loc['unadjusted_U_joint','gene_balanced_mean']==pytest.approx(form.U_joint)
    assert new.loc['unadjusted_U_joint','gene_balanced_mean']!=pytest.approx(form.U_all)
    assert len(result['profiles']['mode'].unique())==7


def test_emergence_is_separate_and_ineligible_postreference_is_flagged():
    pr,pg,fasta,samples=fixture()
    pr[['b1','b2','b3']]=np.nan
    a=quantify_forms(pr,pg,fasta,samples)
    _,edges=frozen_edges(a,annotations())
    emergence=emergent_kinase_evidence(a,edges)
    assert set(emergence.entity)=={'Akt1','AKT_family'}
    assert not emergence.contributes_to_baseline_score.any()
    assert emergence.eligible_A.eq(0).all()
    assert not a['comparisons'].included.any()
    pr['Genes']='DISCORDANT'
    bad=quantify_forms(pr,pg,fasta,samples)
    assert bad['detection'].raw_candidate_A.notna().all()
    assert bad['detection'].eligible_A.isna().all()
    assert not bad['detection'].inference_use_allowed.any()
    _,edges=frozen_edges(bad,annotations())
    assert emergent_kinase_evidence(bad,edges).empty


def test_no_annotation_exports_reason_without_invented_activity():
    a=quantify_forms(*fixture())
    _,edges=frozen_edges(a,annotations().iloc[:0])
    kinase=score_footprints(a,edges,run_omissions=False)
    status=form_evidence_status(a,edges,kinase)
    assert status.curated_edge_count.eq(0).all()
    assert status.kinase_no_call_reason.eq('no_curated_observed_edge').all()


def test_gene_median_does_not_require_score_level_decomposition():
    rows=[{'form_id':str(i),'substrate_gene':'G','site_key':str(i)} for i in range(3)]
    u=dict(zip(['0','1','2'],[0,0,10])); p=dict(zip(['0','1','2'],[0,10,10]))
    a={i:u[i]-p[i] for i in u}
    scores=[aggregate_rows(rows,v)[1]['G'] for v in [a,u,p]]
    assert scores[0]!=scores[1]-scores[2]


def test_annotation_and_recorded_artifact_integrity(tmp_path):
    source=tmp_path/'source'; source.write_text('frozen content')
    sha=file_digest(source); d=tmp_path/sha; d.mkdir()
    (d/'snapshot.tsv').write_bytes(source.read_bytes())
    (d/'annotation_metadata.json').write_text(json.dumps({'database_sha256':sha,'retrieved_utc':'original'}))
    assert annotation_snapshot(tmp_path,sha)['retrieved_utc']=='original'
    (d/'snapshot.tsv').write_text('mutated')
    with pytest.raises(ValueError,match='checksum'):
        annotation_snapshot(tmp_path,sha)
    artifact=tmp_path/'result'; artifact.write_text('recorded run')
    record={'artifacts':{'report':{'path':'result','sha256':file_digest(artifact)}},'run_id':'old-run'}
    (tmp_path/'enrichment_free_current.json').write_text(json.dumps(record))
    assert recorded_run(tmp_path)['run_id']=='old-run'
    artifact.write_text('mutated')
    with pytest.raises(ValueError,match='integrity'):
        recorded_run(tmp_path)


def test_profile_rejects_quick_input_and_undeclared_normalization():
    context={'quantitation_export_mode':EXPORT_MODE,'enrichment_status':'enrichment_free'}
    with pytest.raises(ValueError,match='full PR/PG'):
        validate_profile(context,{},'phospho',10116,{'quick_analysis':True})
    with pytest.raises(ValueError,match='normalization_policy'):
        validate_profile(context,{},'phospho',10116)
    with pytest.raises(ValueError,match='full protein selection'):
        validate_profile(context,{},'phospho',10116,{'mode':'ptm_topn'})
