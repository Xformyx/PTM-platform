"""Canonical experimental design, with conservative, traceable legacy migration.

This is the only input resolver used by the API, UI preview and generic worker.
Times use decimal unit conversion, never positional file/time matching. Materials,
biological units and pairs have distinct identities. Unresolved replication is
allowed for descriptive output; unresolved contrasts/times block only those uses.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

VERSION = 'study_design.v3'
SCIENCE_VERSION = 'study_design.v4'
MIGRATION_VERSION = 'legacy_to_study_design.v1'
PROFILE = 'enrichment_free_timecourse.v3'
TIME_ABS_TOL_MINUTES = 1e-8
UNITS = {'s':Decimal(1)/60, 'sec':Decimal(1)/60, 'second':Decimal(1)/60, 'seconds':Decimal(1)/60,
         'm':Decimal(1),'min':Decimal(1),'minute':Decimal(1),'minutes':Decimal(1),
         'h':Decimal(60),'hr':Decimal(60),'hour':Decimal(60),'hours':Decimal(60),
         'd':Decimal(1440),'day':Decimal(1440),'days':Decimal(1440)}
TIME_RE = re.compile(r'(?<![\w.])(-?\d+(?:\.\d+)?)\s*(minutes?|min|m|hours?|hr|h|days?|d|seconds?|sec|s)(?![a-z])', re.I)
CONTEXT_FIELDS = ('cell_type','tissue','treatment','biological_question','special_conditions','time_points')
SECRET_KEYS = re.compile(r'(?:^|_)(?:password|passwd|secret|token|api.?key|authorization|credential|server_path|internal_path)(?:_|$)',re.I)


def stable_id(prefix, value):
    return prefix+'_'+hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:16]


def clean_context(value):
    """Keep experimental structure/Unicode; reject authentication material recursively."""
    if isinstance(value,dict):
        return {str(k):clean_context(v) for k,v in value.items() if not SECRET_KEYS.search(str(k))}
    if isinstance(value,list):return [clean_context(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):return None
    return deepcopy(value)


def same_time(left, right):
    return left is not None and right is not None and math.isclose(float(left),float(right),abs_tol=TIME_ABS_TOL_MINUTES,rel_tol=1e-12)


def time_value(value, unit, original=None):
    try:
        multiplier=UNITS[str(unit).strip().lower()]
        number=Decimal(str(value)); minutes=number*multiplier
        if not number.is_finite() or not minutes.is_finite():raise ValueError('nonfinite_time')
        return {'value':float(number),'unit':str(unit),'minutes':float(minutes),
                'original':original if original is not None else f'{value}{unit}'}
    except (KeyError,InvalidOperation,TypeError,ValueError):
        raise ValueError('time_unit_or_value_unresolved') from None


def label_time(label):
    matches=list(TIME_RE.finditer(str(label).replace('_',' ')))
    if len(matches)!=1:return None
    match=matches[0]
    return time_value(match[1],match[2],str(label))


def time_list(raw):
    """Shared final unit is valid; bare values never acquire an arbitrary unit."""
    if not isinstance(raw,str) or not raw.strip():return []
    parts=[p.strip() for p in re.split(r'[,;]',raw) if p.strip()]
    last=label_time(parts[-1]) if parts else None
    result=[]
    for part in parts:
        parsed=label_time(part)
        if parsed is None and last and re.fullmatch(r'-?\d+(?:\.\d+)?',part):
            parsed=time_value(part,last['unit'],part)
        if parsed is None:return []
        result.append(parsed)
    return result


def legacy_samples(config):
    if config is not None and not isinstance(config,(list,dict)):raise ValueError('sample_config must be an object or sample list')
    rows=config if isinstance(config,list) else (config or {}).get('samples',[])
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError('sample_config.samples must be a list of objects')
    result=[]
    for row in rows:
        sid=row.get('sample_id') or row.get('file_name') or row.get('File_Name') or row.get('filename')
        if not sid:continue
        group=str(row.get('group',row.get('Group',''))).strip()
        condition=str(row.get('source_condition',row.get('condition',row.get('Condition','')))).strip()
        rep=row.get('replicate',row.get('Replicate',row.get('technical_injection')))
        raw_condition=condition
        # Preserve the platform's existing explicitly classified Control group.
        if group.lower()=='control' and not row.get('condition_id') and not label_time(condition):
            condition='Control'
        elif rep is not None and condition.endswith('_'+str(rep)):
            condition=condition[:-len(str(rep))-1]
        result.append({**deepcopy(row),'sample_id':str(sid),'condition':condition or group or 'Unknown',
                       'group':group,'legacy_replicate':rep,'raw_condition':raw_condition})
    return result


def issue(code, path, message, severity='error', **details):
    return {'code':code,'path':path,'message':message,'severity':severity,**details}


def _origin(source, original, status='imported', rule=None):
    return {'source':source,'original_value':deepcopy(original),'confirmation_status':status,'conversion_rule':rule}


def _metadata(context):
    original={k:deepcopy(context.get(k)) for k in CONTEXT_FIELDS}
    acquisition=clean_context(context.get('acquisition') or {})
    processing=clean_context(context.get('processing') or {})
    legacy=context.get('acquisition_metadata') or {}
    for old,new in [('injection_amount','injection_description'),('acquisition_conditions','description')]:
        if old in legacy and new not in acquisition:
            acquisition[new]={'value':legacy[old],'status':'unknown' if legacy[old] in (None,'','unknown') else 'provided',
                              'source':'analysis_context.acquisition_metadata.'+old}
    for old,new in [('diann_version','software_version'),('diann_processing','settings'),('diann_normalization','upstream_normalization')]:
        if old in legacy and new not in processing:
            processing[new]={'value':legacy[old],'source':'analysis_context.acquisition_metadata.'+old}
    return {'original_context':original,'cell_type':context.get('cell_type'),'tissue':context.get('tissue'),
            'treatment':context.get('treatment'),'biological_question':context.get('biological_question'),
            'special_conditions':context.get('special_conditions'),'time_points':context.get('time_points'),
            'enrichment_status':context.get('enrichment_status','unknown'),
            'pre_treatment':clean_context(context.get('pre_treatment') or legacy.get('starvation_duration')),
            'acquisition':acquisition,'processing':processing}


def resolve_study_design(context, sample_config, *, taxonomy_id=None, species=None, ptm_type='phosphorylation'):
    if context is not None and not isinstance(context,dict):raise ValueError('analysis_context must be an object')
    context=clean_context(context or {})
    for key in ['study_design','sample_manifest','acquisition','processing','acquisition_metadata','validation_panel','temporal_windows']:
        if context.get(key) is not None and not isinstance(context[key],dict):raise ValueError(key+' must be an object')
    rows=legacy_samples(sample_config)
    explicit=deepcopy(context.get('study_design') or {})
    if explicit and explicit.get('schema_version') not in {VERSION,SCIENCE_VERSION}:raise DesignError([issue('schema_version','study_design.schema_version','Unsupported study design schema; explicit migration is required')])
    previous=explicit if explicit.get('schema_version') in {VERSION,SCIENCE_VERSION} else {}
    science=context.get('quantitation_export_mode') in {'astra_analysis.v5','astra_analysis.v6'} or previous.get('schema_version')==SCIENCE_VERSION
    axis=context.get('design_axis',previous.get('study',{}).get('design_axis','time_course')) if science else 'time_course'
    structural=validate_structure(previous) if previous else []
    if structural:
        return {**previous,'issues':structural,'status':'draft'}
    if previous:
        for key in CONTEXT_FIELDS:
            if key not in context:context[key]=previous.get('study',{}).get('original_context',{}).get(key)
    conditions=deepcopy(previous.get('conditions') or [])
    arms=deepcopy(previous.get('arms') or context.get('treatment_arms') or [])
    manifest=context.get('sample_manifest') or {}
    manifest_conditions={s.get('condition'):s for s in manifest.get('conditions',[])}
    declared_samples={s.get('sample_id'):s for s in manifest.get('samples',[])}
    for row in rows:
        legacy=declared_samples.get(row['sample_id'])
        if legacy and legacy.get('condition')=='Control' and row['group'].lower()=='control' and not row.get('condition_id'):
            row['condition']='Control'  # confirmed v1 grouping takes precedence over draft raw time labels
    provenance=deepcopy(previous.get('field_provenance') or {})
    errors=[]; candidates=time_list(context.get('time_points'))
    if explicit and not previous:errors.append(issue('schema_version','study_design.schema_version','Unsupported study design schema'))
    old_treatment=previous.get('study',{}).get('original_context',{}).get('treatment')
    pending_conflicts=deepcopy(previous.get('metadata_conflicts') or [])
    if context.get('treatment_conflict_resolution')=='reviewed_structured_arms':pending_conflicts=[]
    if old_treatment and context.get('treatment')!=old_treatment and context.get('treatment_conflict_resolution')!='reviewed_structured_arms':
        if any(t.get('dose') is not None for arm in arms for t in arm.get('treatments',[])):
            pending_conflicts=[issue('treatment_context_conflict','arms','Treatment description changed while structured doses remain; review their assignment',original_value=old_treatment)]
    errors.extend(pending_conflicts)
    labels=list(dict.fromkeys(r['condition'] for r in rows))
    existing_labels={c.get('label'):c for c in conditions}
    for label in labels:
        if label not in existing_labels:
            group=[r for r in rows if r['condition']==label]
            condition_id=str(group[0].get('condition_id') or stable_id('condition',label))
            roles={str(r.get('role') or ('reference' if r['group'].lower()=='control' else 'target')) for r in group}
            parsed=label_time(label)
            arm_name=group[0].get('arm_id') or group[0].get('arm')
            if not arm_name:
                stripped=TIME_RE.sub('',label.replace('_',' ')).strip(' -_') if parsed else ''
                arm_name=('reference' if roles=={'reference'} else stripped or context.get('treatment') or 'treatment')
            arm_id=next((a['arm_id'] for a in arms if a.get('name')==arm_name or a.get('arm_id')==arm_name),stable_id('arm',arm_name))
            if not any(a['arm_id']==arm_id for a in arms):
                arms.append({'arm_id':arm_id,'name':arm_name,'treatments':[],
                             'source':'sample_config.arm' if group[0].get('arm_id') or group[0].get('arm') else 'legacy_condition_or_treatment_description'})
            c={'condition_id':condition_id,'arm_id':arm_id,'label':label,'role':next(iter(roles)) if len(roles)==1 else 'unknown'}
            if len(roles)>1:errors.append(issue('condition_role_conflict',f'conditions.{condition_id}.role','Conflicting condition roles'))
            conditions.append(c);existing_labels[label]=c
    for c in conditions:
        cid=c.get('condition_id'); path=f'conditions.{cid}.time'
        source_labels=sorted({r['raw_condition'] for r in rows if r['condition']==c.get('label')})
        c['source_labels']=source_labels
        if axis=='cross_sectional':
            c.setdefault('time',None)
            continue
        explicit_time=c.get('time')
        parsed=label_time(c.get('label',''))
        m=manifest_conditions.get(c.get('label'),{})
        imported=None
        if m.get('time_minutes') is not None:
            try:imported=time_value(m['time_minutes'],'min')
            except ValueError:errors.append(issue('invalid_manifest_time',path,'Invalid manifest time'))
        chosen=None
        if explicit_time and explicit_time.get('value') is not None:
            try:chosen=time_value(explicit_time['value'],explicit_time.get('unit'),explicit_time.get('original'))
            except ValueError:errors.append(issue('invalid_time',path,'A finite value and explicit time unit are required'))
        if chosen is None and imported:
            chosen=imported; provenance[path]=_origin('sample_manifest.conditions',m,'confirmed','time_minutes → min')
        if chosen is None and parsed:
            chosen=parsed; provenance[path]=_origin('sample_config.condition',c.get('label'),'derived','explicit unit label → minutes')
        if chosen is None and re.fullmatch(r'-?\d+(?:\.\d+)?',str(c.get('label',''))):
            matches=[t for t in candidates if t['value']==float(c['label'])]
            if len(matches)==1:chosen=matches[0];provenance[path]=_origin('time_points',context.get('time_points'),'derived','match numeric label; never positional zip')
        if chosen is None and c.get('label')=='Control' and c.get('role')=='reference':
            matches=[t for t in candidates if t['minutes']==0]
            if len(matches)==1:chosen=matches[0];provenance[path]=_origin('legacy_Control_and_time_points',context.get('time_points'),'derived','explicit zero candidate for existing Control group')
        if chosen:
            c['time']=chosen
            raw_candidates=[('original_condition_label',label_time(raw)) for raw in source_labels]
            for source,other in [('condition_label',parsed),('legacy_manifest',imported),*raw_candidates]:
                if other and not same_time(chosen['minutes'],other['minutes']) and c.get('time_conflict_resolution')!='use_confirmed_structured':
                    errors.append(issue('time_conflict',path,'Structured time conflicts with imported time',source=source,structured=chosen,candidate=other))
            if candidates and not any(same_time(chosen['minutes'],t['minutes']) for t in candidates) and c.get('time_conflict_resolution')!='use_confirmed_structured':
                errors.append(issue('time_points_conflict',path,'Condition time is absent from the declared time_points list',original_time_points=context.get('time_points')))
        else:
            c['time']=None;errors.append(issue('time_unresolved',path,'Confirm a numerical time and its unit'))
    known_ids={c.get('condition_id') for c in conditions}
    condition_by_label={c['label']:c for c in conditions}
    materials=deepcopy(previous.get('materials') or [])
    injections=deepcopy(previous.get('injections') or [])
    material_map={m['material_id']:m for m in materials}
    old_injections={i['input_column']:i for i in injections}
    injections=[]
    declaration=context.get('replication_declaration') or previous.get('replication_declaration') or 'unknown'
    if declaration not in {'technical_per_condition','independent_biological_units','mixed','unknown'}:
        errors.append(issue('replication_declaration_invalid','replication_declaration','Unsupported replication declaration'))
    for row in rows:
        sid=row['sample_id']; c=condition_by_label[row['condition']]; cid=c['condition_id']
        old=old_injections.get(sid)
        redeclare=declaration!=previous.get('replication_declaration',declaration)
        if old and old.get('condition_id')==cid and not redeclare:
            injections.append(old);continue
        legacy=declared_samples.get(sid)
        item={'injection_id':stable_id('injection',sid),'input_column':sid,'condition_id':cid,'material_id':None,
              'technical_injection_id':None,'legacy_replicate':row.get('legacy_replicate')}
        source='unresolved'; biological=None; pair=None
        if legacy and legacy.get('condition')==row['condition'] and legacy.get('biological_unit'):
            biological=legacy['biological_unit']; mid=stable_id('material',cid+'|'+biological)
            pair=biological if manifest.get('pairing')=='paired' else None
            item['technical_injection_id']=legacy.get('technical_injection')
            source='sample_manifest.v1.biological_unit'
            provenance[f'materials.{mid}']=_origin(source,legacy,'confirmed',
                'v1 grouping/statistical ID → biological_unit_id; material scoped to condition; pairing copied, never inferred')
        elif declaration=='technical_per_condition':
            mid=stable_id('material',cid); source='user_replication_declaration'
            # One sampled material is known; no donor identity is invented.
            biological=stable_id('sampled_unit',cid)
            item['technical_injection_id']=str(row.get('legacy_replicate') or item['injection_id'])
        elif declaration=='independent_biological_units':
            mid=stable_id('material',sid);biological=stable_id('unit',sid);source='user_replication_declaration'
        else:
            mid=None
        if mid:
            item['material_id']=mid
            material_map.setdefault(mid,{'material_id':mid,'biological_unit_id':biological,'pair_id':pair,'source':source})
        injections.append(item)
    used_materials={i['material_id'] for i in injections if i.get('material_id')}
    materials=[m for key,m in material_map.items() if key in used_materials]
    contrasts=deepcopy(previous.get('contrasts') or [])
    if not contrasts:
        references=[c for c in conditions if c.get('role')=='reference']
        for c in conditions:
            if c.get('role')=='reference':continue
            reference=c.get('reference_condition_id') or (references[0]['condition_id'] if len(references)==1 else None)
            if reference:
                contrasts.append({'contrast_id':stable_id('contrast',c['condition_id']+'|'+reference),
                    'target_condition_id':c['condition_id'],'reference_condition_id':reference,
                    'pairing':manifest.get('pairing') if declared_samples else context.get('pairing_policy','unknown'),
                    'purpose':'target_vs_declared_reference','source':'declared_condition_reference' if c.get('reference_condition_id') else 'single_existing_reference_group'})
            else:errors.append(issue('reference_unresolved',f'conditions.{c["condition_id"]}.reference_condition_id','Select the reference condition; multiple/absent controls cannot be resolved silently'))
    for arm in arms:
        if not arm.get('treatments') and arm.get('name')==context.get('treatment'):
            arm['treatments']=[{'name':context.get('treatment'),'dose':None,'unit':None,'dose_status':'unknown'}]
    legacy_dose=(context.get('acquisition_metadata') or {}).get('insulin_concentration')
    if legacy_dose not in (None,'','unknown'):
        if str(context.get('treatment','')).strip().casefold()=='insulin':
            for arm in arms:
                if str(arm.get('name','')).casefold()=='insulin' and not any(t.get('dose') for t in arm.get('treatments',[])):
                    match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(\S+)\s*',str(legacy_dose))
                    arm['treatments']=[{'name':'insulin','dose':float(match[1]) if match else None,'unit':match[2] if match else None,
                        'original':legacy_dose,'dose_status':'provided' if match else 'unresolved','source':'legacy.insulin_concentration'}]
        else:errors.append(issue('legacy_insulin_dose_conflict','arms','Legacy insulin dose is not assigned to a different treatment','warning',original_value=legacy_dose))
    study={**previous.get('study',{}),**_metadata(context),'taxonomy_id':str(taxonomy_id) if taxonomy_id is not None else previous.get('study',{}).get('taxonomy_id'),
           'species':species or previous.get('study',{}).get('species'),'ptm_type':ptm_type}
    if science:study.update(design_axis=axis,analysis_target=context.get('analysis_target',previous.get('study',{}).get('analysis_target','proteomics' if ptm_type=='proteomics' else 'phosphoproteomics' if ptm_type in {'phospho','phosphorylation'} else 'other_ptm')))
    design={'schema_version':SCIENCE_VERSION if science else VERSION,'migration_version':MIGRATION_VERSION,'study':study,
        'arms':arms,'conditions':conditions,'materials':materials,'injections':injections,'contrasts':contrasts,
        'replication_declaration':declaration,'field_provenance':provenance,'metadata_conflicts':pending_conflicts,
        'time_policy':{'internal_unit':'min','absolute_tolerance_minutes':TIME_ABS_TOL_MINUTES,'relative_tolerance':1e-12,
                       'interpolation':'not_performed','mapping':'condition_id_and_contrast_id_never_time_only'},
        'validation_panel':clean_context(context.get('validation_panel') or previous.get('validation_panel') or {}),
        'temporal_windows':clean_context(context.get('temporal_windows') or previous.get('temporal_windows') or {})}
    for key,value in study['original_context'].items():
        provenance['study.'+key]=_origin('analysis_context.'+key,value,'provided' if value is not None else 'unknown')
    errors.extend(validate_study_design(design,rows=rows))
    # Retain unresolved materials as explicit descriptive-only observations.
    if any(not i.get('material_id') for i in injections):
        errors.append(issue('replication_unresolved','materials','Rep numbers do not establish material or biological relationships','warning'))
    design['issues']=errors
    design['status']='draft' if any(e['severity']=='error' for e in errors) else 'resolved'
    return design


def validate_study_design(design, rows=None):
    errors=validate_structure(design)
    if errors:return errors
    if design.get('schema_version') not in {VERSION,SCIENCE_VERSION}:return [issue('schema_version','schema_version','Unsupported study design schema')]
    for collection,key in [('arms','arm_id'),('conditions','condition_id'),('materials','material_id'),('injections','injection_id'),('contrasts','contrast_id')]:
        ids=[r.get(key) for r in design.get(collection,[])]
        if any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):
            errors.append(issue('duplicate_or_missing_id',collection,'Stable unique IDs are required'))
    arms={a['arm_id'] for a in design.get('arms',[])}
    conditions={c['condition_id']:c for c in design.get('conditions',[])}
    materials={m['material_id']:m for m in design.get('materials',[])}
    columns=[]
    cross_sectional=design.get('schema_version')==SCIENCE_VERSION and design.get('study',{}).get('design_axis')=='cross_sectional'
    if design.get('schema_version')==SCIENCE_VERSION and design.get('study',{}).get('design_axis') not in {'time_course','cross_sectional'}:
        errors.append(issue('design_axis_invalid','study.design_axis','Choose time_course or cross_sectional'))
    for c in conditions.values():
        if c.get('arm_id') not in arms:errors.append(issue('arm_missing',f'conditions.{c["condition_id"]}.arm_id','Arm does not exist'))
        if cross_sectional and c.get('time') is None:continue
        try:
            t=c.get('time') or {}; converted=time_value(t.get('value'),t.get('unit'))
            if not same_time(converted['minutes'],t.get('minutes')):raise ValueError()
        except (ValueError,TypeError):errors.append(issue('invalid_time',f'conditions.{c["condition_id"]}.time','Finite time with matching normalized minutes is required'))
    for i in design.get('injections',[]):
        columns.append(i.get('input_column'))
        if not isinstance(i.get('input_column'),str) or not i['input_column']:errors.append(issue('input_column_missing',f'injections.{i["injection_id"]}.input_column','Raw input column must be a nonempty string'))
        if i.get('condition_id') not in conditions:errors.append(issue('condition_missing',f'injections.{i["injection_id"]}','Condition does not exist'))
        if i.get('material_id') is not None and i['material_id'] not in materials:errors.append(issue('material_missing',f'injections.{i["injection_id"]}','Material mapping is missing'))
    if len(columns)!=len(set(columns)):errors.append(issue('duplicate_input_column','injections','Each raw column must occur once'))
    if rows is not None and set(columns)!={r['sample_id'] for r in rows}:errors.append(issue('input_mapping_mismatch','injections','Design must cover configured raw columns exactly'))
    for m in materials:
        assigned={i['condition_id'] for i in design['injections'] if i.get('material_id')==m}
        if len(assigned)>1:errors.append(issue('material_across_conditions',f'materials.{m}','Different measured samples across conditions need distinct material IDs; biological/pair IDs may link them'))
    by_unit=defaultdict(set)
    for m in materials.values():
        if m.get('biological_unit_id'):by_unit[m['biological_unit_id']].add(m.get('pair_id'))
    for unit,pairs in by_unit.items():
        if len(pairs)>1:errors.append(issue('unit_pair_conflict',f'materials.{unit}.pair_id','One declared biological unit has conflicting pair IDs'))
    for c in design.get('contrasts',[]):
        target,reference=c.get('target_condition_id'),c.get('reference_condition_id')
        if target not in conditions or reference not in conditions or target==reference:
            errors.append(issue('contrast_reference_invalid',f'contrasts.{c["contrast_id"]}','Distinct existing target and reference conditions are required'))
        if any(not any(i.get('condition_id')==cid for i in design['injections']) for cid in (target,reference)):
            errors.append(issue('condition_injections_missing',f'contrasts.{c["contrast_id"]}','Each contrast condition needs measured injections'))
        if c.get('pairing') not in {'paired','unpaired','unknown'}:
            errors.append(issue('pairing_invalid',f'contrasts.{c["contrast_id"]}.pairing','Declare paired, unpaired or unknown'))
        if c.get('pairing')=='paired':
            needed=[i for i in design['injections'] if i['condition_id'] in (target,reference)]
            if any(not materials.get(i.get('material_id'),{}).get('pair_id') for i in needed):
                errors.append(issue('pair_mapping_required',f'contrasts.{c["contrast_id"]}.pairing','Paired contrasts require explicit pair IDs; injection numbers do not establish pairs'))
    if not design.get('contrasts'):errors.append(issue('contrasts_missing','contrasts','At least one declared contrast is required for execution'))
    windows=design.get('temporal_windows') or {}
    if not isinstance(windows,dict):errors.append(issue('invalid_temporal_windows','temporal_windows','Use a named object of time bounds in minutes'))
    else:
        for name,window in windows.items():
            if not isinstance(window,dict) or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in window.values()) or window.get('minimum_minutes',-math.inf)>window.get('maximum_minutes',math.inf):
                errors.append(issue('invalid_temporal_window','temporal_windows.'+name,'Finite numeric time bounds with minimum <= maximum are required'))
    panel=design.get('validation_panel') or {}
    if not isinstance(panel,dict) or not isinstance(panel.get('genes',[]),list):errors.append(issue('invalid_validation_panel','validation_panel','Panel genes must be a list with an explicit selection timing'))
    return errors


def validate_structure(design):
    if not isinstance(design,dict):return [issue('design_object_required','study_design','Design must be an object')]
    errors=[]
    if not isinstance(design.get('study',{}),dict):errors.append(issue('invalid_study','study','Study must be an object'))
    for collection,key in [('arms','arm_id'),('conditions','condition_id'),('materials','material_id'),('injections','injection_id'),('contrasts','contrast_id')]:
        rows=design.get(collection,[])
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get(key),str) or not r[key] for r in rows):
            errors.append(issue('invalid_collection',collection,'Expected objects with nonempty stable IDs'))
    return errors


def require_resolved(design, pr_columns=None, pg_columns=None):
    errors=[e for e in design.get('issues',[]) if e.get('severity')=='error']+validate_study_design(design)
    for layer,columns in [('PR',pr_columns),('PG',pg_columns)]:
        if columns is not None:
            for i in design['injections']:
                if i['input_column'] not in columns:errors.append(issue('input_column_missing',f'injections.{i["injection_id"]}',f'Column absent from {layer}'))
    if errors:raise DesignError(errors)
    return design


class DesignError(ValueError):
    def __init__(self,issues):
        self.issues=issues
        super().__init__('; '.join(f'{e["code"]}: {e["path"]}' for e in issues))
