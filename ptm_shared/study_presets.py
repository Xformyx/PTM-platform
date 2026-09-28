"""Study presets are explicit opt-ins. Generic analysis inherits none of these."""
HIRCB_PRESET = 'hircb_insulin_reference.v1'
HIRCB_SNAPSHOT = '80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07'
HIRCB_PANEL = frozenset({'FOSL1','FOSL2','JUN','JUNB','CCND1','IRS1'})
HIRCB_WINDOWS = {'early': {'maximum_minutes':30}, 'late': {'minimum_minutes':60}}
HIRCB_HOLDOUT_POLICY = 'retrospective_panel_fixed_before_reanalysis_discovery_after_original_report_review'


def legacy_manifest(design):
    """Explicit adapter for reference reproduction, never a generic estimator."""
    from .study_design import require_resolved
    require_resolved(design)
    conditions={c['condition_id']:c for c in design['conditions']}
    references={c['reference_condition_id'] for c in design['contrasts']}
    arms={conditions[c['target_condition_id']]['arm_id'] for c in design['contrasts']}
    if len(references)!=1 or len(arms)!=1:
        raise ValueError('HIRc-B reference preset requires one treatment arm and one shared baseline')
    reference=conditions[next(iter(references))]
    if reference['time']['minutes']!=0 or sorted(c['time']['minutes'] for c in conditions.values())!=[0,1,5,15,30,60,180]:
        raise ValueError('HIRc-B reference preset requires its original 0,1,5,15,30,60,180 minute design')
    materials={m['material_id']:m for m in design['materials']}
    labels={cid:('Control' if cid==reference['condition_id'] else c['label']) for cid,c in conditions.items()}
    samples=[]
    for cid in conditions:
        rows=[s for s in design['injections'] if s['condition_id']==cid]
        if len(rows)!=3 or len({s.get('material_id') for s in rows})!=1 or not rows[0].get('material_id'):
            raise ValueError('HIRc-B reference preset requires three technical injections of one declared material per condition')
        for s in rows:
            samples.append({'sample_id':s['input_column'],'condition':labels[cid],
                'biological_unit':materials[s['material_id']].get('biological_unit_id') or s['material_id'],
                'technical_injection':s.get('technical_injection_id') or s['injection_id']})
    return {'schema_version':'sample_manifest.v1','pairing':'unpaired','samples':samples,
            'conditions':[{'condition':labels[cid],'time_minutes':c['time']['minutes']} for cid,c in conditions.items()]}
