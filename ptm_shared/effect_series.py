"""Canonical effect scopes. Point references remain real condition IDs.

v1 single-reference series IDs are retained. v2 matched scopes explicitly allow
varying reference/pairing at points; they never imply a longitudinal unit model.
"""
import math
from .astra_inputs import stable_id
from .control_comparison import LABELS, condition_order, reference_family
from .study_design import same_time

VERSION='effect_series.v2'
POINT_COLUMNS=['series_id','contrast_id','target_condition_id','reference_condition_id','arm_id',
               'time_min','reference_time_min','pairing','reference_strategy','effect_kind','control_family','schema_version']


def resolve_series(design):
    conditions={c['condition_id']:c for c in design['conditions']}
    series={};lookup={}
    for c in design['contrasts']:
        target=conditions[c['target_condition_id']];reference=conditions[c['reference_condition_id']]
        strategy=c.get('reference_strategy');matched=strategy=='time_matched'
        family=c.get('control_family');kind=c.get('effect_kind')
        if matched:
            if kind!='matched_treatment_effect' or not family or reference_family(reference)!=family or not same_time(target.get('time',{}).get('minutes'),reference.get('time',{}).get('minutes')):
                raise ValueError('Invalid time-matched effect scope: '+c['contrast_id'])
            sid=stable_id('effect_series',[VERSION,target['arm_id'],family,kind,c.get('design_scope','whole_study')])
        else:
            # Keep the archived key for legacy/shared/custom single references.
            sid=stable_id('series',[target['arm_id'],c['reference_condition_id'],c.get('pairing')])
        point={'series_id':sid,'contrast_id':c['contrast_id'],'target_condition_id':c['target_condition_id'],
               'reference_condition_id':c['reference_condition_id'],'arm_id':target['arm_id'],
               'time_min':target.get('time',{}).get('minutes'),'reference_time_min':reference.get('time',{}).get('minutes'),
               'pairing':c.get('pairing'),'reference_strategy':strategy or 'explicit_custom',
               'effect_kind':kind or 'custom_contrast','control_family':family,'schema_version':VERSION}
        s=series.setdefault(sid,{'series_id':sid,'arm_id':target['arm_id'],'points':[],
            'reference_strategy':strategy or 'one_declared_reference; matched_time_controls_remain_separate_series',
            'effect_kind':kind or 'custom_contrast','control_family':family,'series_schema_version':VERSION if matched else 'single_reference.v1'})
        s['points'].append(point);lookup[c['contrast_id']]=sid
    for s in series.values():
        s['points'].sort(key=lambda p:(condition_order(conditions[p['target_condition_id']]),p['contrast_id']))
        s['contrast_ids']=[p['contrast_id'] for p in s['points']]
        refs=sorted({p['reference_condition_id'] for p in s['points']});pairing={p['pairing'] for p in s['points']}
        s['reference_condition_ids']=refs
        s['reference_condition_id']=refs[0] if len(refs)==1 else None
        s['pairing']=next(iter(pairing)) if len(pairing)==1 else 'mixed'
        s['paired_biological_units']=s['pairing']=='paired' and design.get('replication_declaration')!='technical_per_condition'
        s['inference_status']='descriptive_only_mixed_pairing' if len(pairing)>1 else 'descriptive_only_no_biological_test_implemented'
    return series,lookup


def series_label(series, language='ko'):
    strategy=series['reference_strategy']
    label=LABELS.get(strategy,{}).get('english_label' if language=='en' else 'label','Custom controls' if language=='en' else 'Control 직접 연결')
    return label + ((' · '+str(series['control_family'])) if strategy=='time_matched' else '')


def has_matched(design):
    return any(c.get('reference_strategy')=='time_matched' for c in design.get('contrasts',[]))


def ordered_contrast_ids(*, design=None, points=None):
    """Shared numeric ordering for matched scopes and saved reader projections."""
    if design is not None:
        scopes,_=resolve_series(design)
        points=[p for s in scopes.values() for p in s['points']]
    rows=list(points or [])
    if len({p['contrast_id'] for p in rows})!=len(rows):raise ValueError('Duplicate effect point ordering key')
    def minute(p):
        value=p['time_min']
        return float(value) if value is not None and math.isfinite(float(value)) else float('inf')
    return [p['contrast_id'] for p in sorted(rows,key=lambda p:(p['arm_id'],p['series_id'],minute(p),p['contrast_id']))]
