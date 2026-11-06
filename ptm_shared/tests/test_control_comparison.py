"""Small canonical policy fixtures; no scientific providers or production orders."""
from copy import deepcopy
import pytest
from ptm_shared.study_execution import resolve_context
from ptm_shared.study_design import require_resolved, DesignError


def inputs(strategy=None):
    labels=['Control 0min','Control 30min','Control 60min','Drug 0.5h','Drug 60min']
    rows=[{'sample_id':f'f{i}_{rep}','condition':label,'group':'Control' if i<3 else 'Treatment',
           'replicate':rep,'control_family':'vehicle'} for i,label in enumerate(labels) for rep in [1,2,3]]
    context={'quantitation_export_mode':'astra_analysis.v6','normalization_policy':'already_normalized.v1',
             'replication_declaration':'independent_biological_units','pairing_policy':'unpaired'}
    if strategy:context['control_comparison']={'schema_version':'control_comparison.v1','strategy':strategy,'source':'user_input'}
    return context,rows


def resolved(context,rows):
    return resolve_context(context,rows,taxonomy_id=9606,species='human')


def test_matched_policy_uses_numeric_time_and_keeps_replicates():
    context,rows=inputs('time_matched'); result=resolved(context,rows);design=result['study_design']
    require_resolved(design)
    conditions={c['condition_id']:c for c in design['conditions']}
    assert len(design['injections'])==len(design['materials'])==15
    assert len(design['contrasts'])==2
    for c in design['contrasts']:
        assert conditions[c['target_condition_id']]['time']['minutes']==conditions[c['reference_condition_id']]['time']['minutes']
        assert c['reference_strategy']=='time_matched' and c['effect_kind']=='matched_treatment_effect'
        assert c['pairing']=='unpaired'
    assert resolved(result,rows)==result
    shuffled=resolved(context,list(reversed(rows)))['study_design']
    for key,id_key in [('conditions','condition_id'),('contrasts','contrast_id'),('materials','material_id'),('injections','injection_id')]:
        assert sorted(shuffled[key],key=lambda r:r[id_key])==sorted(design[key],key=lambda r:r[id_key])


def test_missing_and_ambiguous_are_local_without_fallback():
    context,rows=inputs('time_matched')
    design=resolved(context,[r for r in rows if r['condition']!='Control 30min'])['study_design']
    assert len(design['contrasts'])==1
    assert any(i['code']=='matched_reference_missing' for i in design['issues'])
    with pytest.raises(DesignError):require_resolved(design)
    duplicate=[{**r,'sample_id':'other_'+r['sample_id'],'condition':'Other control 30min'} for r in rows if r['condition']=='Control 30min']
    design=resolved(context,rows+duplicate)['study_design']
    assert any(i['code']=='matched_reference_ambiguous' and i['candidate_count']==2 for i in design['issues'])
    assert len(design['contrasts'])==1


def test_same_labels_different_roles_and_explicit_ids_stay_separate():
    context,rows=inputs('time_matched')
    for r in rows:
        r['condition']=r['condition'].split(' ',1)[1].replace('0.5h','30min')
    design=resolved(context,rows)['study_design'];require_resolved(design)
    assert len(design['conditions'])==5
    assert len({c['condition_id'] for c in design['conditions'] if c['label']=='30min'})==2
    for r in rows:r['condition_id']=r['group']+'_'+r['condition']
    explicit=resolved(context,rows)['study_design'];require_resolved(explicit)
    assert {c['condition_id'] for c in explicit['conditions']}=={r['condition_id'] for r in rows}


def test_shared_reference_selection_and_custom_restore_do_not_change_units():
    context,rows=inputs('time_matched'); before=resolved(context,rows)
    ref=next(c for c in before['study_design']['conditions'] if c['label']=='Control 30min')['condition_id']
    selected={**before,'control_comparison':{'schema_version':'control_comparison.v1','strategy':'shared_reference','source':'user_input','reference_condition_id':ref}}
    after=resolved(selected,rows);require_resolved(after['study_design'])
    assert {c['reference_condition_id'] for c in after['study_design']['contrasts']}=={ref}
    assert {c['effect_kind'] for c in after['study_design']['contrasts']}=={'reference_change'}
    for key in ['injections','materials','replication_declaration']:assert after['study_design'][key]==before['study_design'][key]
    old=deepcopy(before);old.pop('control_comparison');old['study_design'].pop('control_comparison')
    for c in old['study_design']['contrasts']:
        old['study_design']['field_provenance'].pop('contrasts.'+c['contrast_id'],None)
        for key in ['reference_strategy','effect_kind','reference_assignment_source','reference_policy_version','control_family','assignment_status']:c.pop(key,None)
    kept=resolved(old,rows)['study_design'];require_resolved(kept)
    assert kept['control_comparison']['effective_policy']['strategy']=='explicit_custom'
    assert [(c['contrast_id'],c['reference_condition_id']) for c in kept['contrasts']]==[(c['contrast_id'],c['reference_condition_id']) for c in old['study_design']['contrasts']]


def test_multiple_families_require_arm_assignment_and_do_not_cross_vehicle():
    context,rows=inputs('time_matched')
    rows += [{**r,'sample_id':'b_'+r['sample_id'],'condition':r['condition'].replace('Control','Vehicle B'),'control_family':'vehicle_b'} for r in rows if r['group']=='Control']
    for r in rows:
        if r['group']=='Treatment':r['control_family']='vehicle_b'
    design=resolved(context,rows)['study_design'];require_resolved(design)
    assert all(c['control_family']=='vehicle_b' for c in design['contrasts'])
    for r in rows:
        if r['group']=='Treatment':r.pop('control_family')
    design=resolved(context,rows)['study_design']
    assert any(i['code']=='control_family_unresolved' for i in design['issues'])


def test_new_input_suggests_only_unique_policies_and_does_not_invent_time_zero():
    context,rows=inputs();design=resolved(context,rows)['study_design'];require_resolved(design)
    assert design['control_comparison']['effective_policy']['strategy']=='time_matched'
    assert design['control_comparison']['effective_policy']['source']=='automatic_selection'
    rows=[r for r in rows if r['condition'] not in ['Control 0min','Control 60min']]
    design=resolved(context,rows)['study_design'];require_resolved(design)
    assert design['control_comparison']['effective_policy']['strategy']=='shared_reference'
    assert all(c['effect_kind']=='reference_change' for c in design['contrasts'])


def test_existing_lowercase_control_identity_and_confirmed_mapping_survive_policy_and_source_edits():
    from ptm_shared.tests.test_study_input_reuse import inputs as shared_inputs
    context,rows,_=shared_inputs()
    for r in rows:
        if r['group']=='Control':r['condition']='control_'+str(r['replicate'])
    before=resolved(context,rows);design=before['study_design']
    after=resolved({**before,'control_comparison':{'strategy':'shared_reference','source':'user_input'}},rows)['study_design']
    for key in ['conditions','materials','injections']:
        assert after[key]==design[key]
    assert [(c['contrast_id'],c['reference_condition_id']) for c in after['contrasts']]==[(c['contrast_id'],c['reference_condition_id']) for c in design['contrasts']]
    context,rows=inputs('time_matched');before=resolved(context,rows);design=before['study_design']
    confirmed=design['contrasts'][0];ref=confirmed['reference_condition_id']
    design['field_provenance']['contrasts.'+confirmed['contrast_id']]={'source':'user_input','confirmation_status':'user_confirmed'}
    for row in rows:
        if row['condition']=='Control 30min':row.update(condition_id=ref,condition='Control 45min')
    after=resolved(before,rows)['study_design']
    assert next(c for c in after['contrasts'] if c['contrast_id']==confirmed['contrast_id'])['reference_condition_id']==ref
    assert any(i['code']=='confirmed_reference_conflict' for i in after['issues'])


def test_legacy_support_rejects_pooling_but_not_three_replicates():
    from ptm_shared.control_comparison import legacy_support
    context,rows=inputs('time_matched')
    assert legacy_support(context,rows)['status']=='unsupported'
    shared=[r for r in rows if r['condition'] not in ['Control 30min','Control 60min']]
    assert legacy_support({},shared)['status']=='supported'
