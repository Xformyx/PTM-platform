from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from test_generic_study import generic_fixture
from test_control_comparison import resolved
from ptm_shared.contrast_quantification import quantify_contrasts
from ptm_shared.astra_plan import resolve_plan


def inputs(declaration='independent_biological_units', pairing='unpaired'):
    pr,pg,fasta,_,ctx,old=generic_fixture()
    pr=pr.drop(columns=[s['sample_id'] for s in old]);pg=pg.drop(columns=[s['sample_id'] for s in old]);samples=[]
    for t,control,target in [(30,2,3),(60,3,5)]:
        for role,log in [('Control',control),('Treatment',target)]:
            for rep in [1,2,3]:
                sid=f'{role}_{t}_{rep}';pr[sid]=2.**log;pg[sid]=1.
                samples.append({'sample_id':sid,'condition':f'{role} {t}min','group':role,'replicate':rep,'control_family':'vehicle'})
    ctx.update(quantitation_export_mode='astra_analysis.v6',replication_declaration=declaration,
               pairing_policy=pairing,control_comparison={'strategy':'time_matched'})
    ctx=resolved(ctx,samples)
    return pr,pg,fasta,ctx


def test_matched_quantities_do_not_self_reference_every_point():
    pr,pg,fasta,ctx=inputs();a=quantify_contrasts(pr,pg,fasta,ctx['study_design'])
    main=a['comparisons'].sort_values('time_min');det=a['detection'].sort_values('time_min')
    np.testing.assert_allclose(main.A,[1,2],atol=1e-12)
    np.testing.assert_allclose(det.eligible_A,[0,2],atol=1e-12)
    assert main.A.diff().iloc[1]==pytest.approx(1) # different quantity, not the post-reference field
    assert det.post_reference_time_min.eq(30).all()
    assert det.reference_time_min.tolist()==[30,60]
    assert det.detection_count_unit.eq('finite_injection_observation').all()
    assert main.biological_p_value.isna().all()


@pytest.mark.parametrize('declaration,pairing', [('unknown','unknown'),('technical_per_condition','unpaired')])
def test_unsupported_cross_time_keeps_main_and_counts(declaration,pairing):
    pr,pg,fasta,ctx=inputs(declaration,pairing);a=quantify_contrasts(pr,pg,fasta,ctx['study_design'])
    d=a['detection'];assert d.eligible_A.isna().all() and d.post_reference_U.isna().all()
    assert not d.inference_use_allowed.any()
    assert d.post_reference_status.eq('ambiguous_unit_relationship').all()
    assert d.detected_n.eq(3).all() and len(a['runlevel'])==12
    np.testing.assert_allclose(a['comparisons'].sort_values('time_min').A,[1,2],atol=1e-12)


def test_matched_missing_parent_delayed_detection_and_mixed_pairing():
    pr,pg,fasta,ctx=inputs()
    pg[[c for c in pg if c.startswith('Treatment_60')]]=np.nan
    pr[[c for c in pr if c.startswith('Treatment_30')]]=np.nan
    a=quantify_contrasts(pr,pg,fasta,ctx['study_design']);d=a['detection']
    assert d.eligible_A.isna().all() and not d.inference_use_allowed.any()
    assert d.first_repeated_time_min.eq(60).all() and d.post_reference_time_min.isna().all()
    assert d.reference_detected_n.eq(3).all()
    pr,pg,fasta,ctx=inputs();ctx['study_design']['contrasts'][0]['pairing']='unknown'
    d=quantify_contrasts(pr,pg,fasta,ctx['study_design'])['detection']
    assert d.eligible_A.isna().all() and d.post_reference_status.eq('ambiguous_unit_relationship').all()


def test_strategy_and_detection_code_are_quant_dependencies():
    *_,ctx=inputs();original=resolve_plan(ctx)
    changed=deepcopy(ctx)
    for c in changed['study_design']['contrasts']:c['reference_strategy']='explicit_custom'
    assert resolve_plan(changed)['fingerprints']['quant']!=original['fingerprints']['quant']
    assert 'contrast_quantification.py' in original['code_dependencies']['quant']
    assert 'effect_series.py' in original['code_dependencies']['quant']


def test_control_target_pairs_are_not_cross_time_pairs():
    pr,pg,fasta,ctx=inputs();design=ctx['study_design'];materials={m['material_id']:m for m in design['materials']}
    for s in design['injections']:
        _,t,rep=s['input_column'].split('_')
        materials[s['material_id']]['pair_id']=t+'_'+rep
    for c in design['contrasts']:c['pairing']='paired'
    a=quantify_contrasts(pr,pg,fasta,design)
    np.testing.assert_allclose(a['comparisons'].sort_values('time_min').A,[1,2],atol=1e-12)
    assert a['comparisons'].pairing.eq('paired').all()
    assert a['detection'].eligible_A.isna().all()
    assert a['detection'].post_reference_pairing.isna().all()
    assert a['detection'].post_reference_status.eq('ambiguous_unit_relationship').all()
