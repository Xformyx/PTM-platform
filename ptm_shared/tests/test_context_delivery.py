"""Saved values → production metadata writer → actual ZIP, without science."""
import csv
import json
from copy import deepcopy
import zipfile
import pandas as pd
import pytest
from ptm_shared.astra_inputs import (capture_order, transfer_contract, verify_order_capture,
    verify_snapshot, validate_delivery, resolve_pointer)
from ptm_shared.astra_package import write_study_inputs
from ptm_shared.study_design import resolve_study_design


@pytest.fixture
def delivered(tmp_path):
    context = {'biological_question': '실험 설계 α\n' * 1000,
               'cell_type': 'microglia', 'custom': {'a/b~c': [None, False, 0, '', []]},
               'apiToken': 'NEVER_EXPORT'}
    samples = [{'sample_id': c+str(i), 'condition': c, 'group': g, 'replicate': i}
               for c,g in [('Control','Control'),('1h','Treatment')] for i in [1,2]]
    order = {'id': 41, 'analysis_context': context, 'sample_config': {'samples': samples},
             'report_options': {'research_questions': []}, 'rag_collections': []}
    snapshot = capture_order(order)
    verify_order_capture(order, snapshot)
    clean = snapshot['original']['analysis_context']
    design = resolve_study_design(clean, samples)
    fields, inventory, brief = transfer_contract(snapshot, design, clean, {'collections': []})
    assert inventory['unexpected_missing'] is None  # inventory is not transfer proof
    (tmp_path/'study').mkdir(); (tmp_path/'references').mkdir()
    pd.DataFrame(fields).to_csv(tmp_path/'study/input_field_manifest.csv', index=False)
    (tmp_path/'references/literature_pin.json').write_text('{"collections":[]}')
    (tmp_path/'provenance.json').write_text('{"run_id":"run-a"}')
    write_study_inputs(tmp_path, snapshot, clean, design)
    (tmp_path/'study/STUDY_BRIEF.md').write_text(brief)
    from ptm_shared.astra_package import start_here
    (tmp_path/'START_HERE_ASTRA.md').write_text(start_here(snapshot, {}, {}))
    return tmp_path, order, snapshot


def test_independent_source_values_and_written_zip(delivered):
    root, order, snapshot = delivered
    assert snapshot['original']['analysis_context']['custom']['a/b~c'] == [None, False, 0, '', []]
    assert snapshot['original']['report_options']['research_questions'] == []
    assert snapshot['original']['analysis_context']['biological_question'] == '실험 설계 α\n' * 1000
    assert 'NEVER_EXPORT' not in json.dumps(snapshot)
    assert resolve_pointer(snapshot, '/original/analysis_context/custom/a~1b~0c/1') is False
    assert validate_delivery(root)['unexpected_missing'] == 0
    archive = root/'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for p in root.rglob('*'):
            if p.is_file() and p != archive: z.write(p, p.relative_to(root))
    with zipfile.ZipFile(archive) as z:
        assert validate_delivery(root, z)['validation_scope'] == 'zip'
    order['analysis_context']['cell_type'] = 'draft changed'
    with pytest.raises(ValueError, match='saved_order /analysis_context'):
        verify_order_capture(order, snapshot)
    assert validate_delivery(root)['status'] == 'verified'  # frozen run unaffected


@pytest.mark.parametrize('mutation,reason', [('delete','missing'),('type','type_changed'),('value','value_changed'),('record','stale_source')])
def test_dispatch_snapshot_mutation(delivered, mutation, reason):
    root, order, snapshot = delivered
    bad = deepcopy(snapshot)
    if mutation == 'delete': del bad['original']['analysis_context']['cell_type']
    elif mutation == 'type': bad['original']['analysis_context']['custom']['a/b~c'][1] = 0
    elif mutation == 'value': bad['original']['analysis_context']['cell_type'] = 'wrong'
    else: bad['source_record_id'] = 'other-order'
    with pytest.raises(ValueError, match=reason):
        verify_snapshot(bad, snapshot['source_receipt'], stage='dispatch')
    (root/'study/user_input_snapshot.json').write_text(json.dumps(bad))
    with pytest.raises(ValueError, match='package_json'):
        validate_delivery(root)


@pytest.mark.parametrize('mutation', ['pointer', 'canonical', 'manifest_missing', 'manifest_role', 'stale_design'])
def test_file_boundary_faults(delivered, mutation):
    root, _, _ = delivered
    path = root/'study/input_field_manifest.csv'; frame = pd.read_csv(path, keep_default_na=False)
    if mutation == 'pointer': frame.loc[0, 'original_value_ref'] = 'study/user_input_snapshot.json#/original/report_options'
    elif mutation == 'canonical': frame.loc[0, 'canonical_value_ref'] = 'study/study_design.json#/nonexistent'
    elif mutation == 'manifest_missing': frame = frame.iloc[1:]
    elif mutation == 'manifest_role': frame.loc[0, 'semantic_role'] = 'measured_result'
    else:
        design = json.loads((root/'study/study_design.json').read_text()); design['study']['species'] = 'wrong'
        (root/'study/study_design.json').write_text(json.dumps(design))
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match='Research input delivery:.*field_path'):
        validate_delivery(root)


def test_absent_legacy_receipt_is_not_end_to_end_proof(tmp_path):
    assert validate_delivery(tmp_path)['status'] == 'legacy_unverified'


def test_seal_failure_preserves_previous_archive_and_pointer(delivered, monkeypatch):
    from ptm_shared import astra_package
    root, _, _ = delivered
    publication = root/'publication'; publication.mkdir()
    old = publication/'enrichment_free_current.json'; old.write_bytes(b'previous success')
    archive = publication/'astra_analysis_package_existing.zip'; archive.write_bytes(b'previous ZIP')
    # Scientific validation is outside this metadata-only fixture; real seal/hash/CRC run.
    monkeypatch.setattr(astra_package, 'validate_package', lambda directory: None)
    result, _ = astra_package.seal_archive(root, publication, 'new', 'fixture')
    with zipfile.ZipFile(result) as z: assert validate_delivery(root, z)['status'] == 'verified'
    snapshot = root/'study/user_input_snapshot.json'; value = json.loads(snapshot.read_text())
    value['original']['report_options']['research_questions'] = ['fabricated']
    snapshot.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Research input delivery'):
        astra_package.seal_archive(root, publication, 'failed', 'fixture')
    assert not (publication/'astra_analysis_package_failed.zip').exists()
    assert old.read_bytes() == b'previous success' and archive.read_bytes() == b'previous ZIP'


def test_common_context_long_preview_original_and_report_binding(delivered):
    from ptm_shared.study_context_delivery import write_context, verify_context_binding, format_report_context
    root, order, snapshot = delivered
    (root/'reader').mkdir(exist_ok=True)
    artifacts, binding = write_context(root)
    projection = verify_context_binding(root, binding)
    design_text = projection['roles']['study_design_context']['fields']['biological_question']
    assert design_text['preview_truncated'] and len(design_text['preview']) == 1200
    ref = design_text['source_ref']
    original = resolve_pointer(json.loads((root/ref['file']).read_text()), ref['pointer'])
    assert original == order['analysis_context']['biological_question']
    assert projection['roles']['research_question']['values'] == []
    assert projection['roles']['execution_design']['display']['replication']
    packet = {'study_context_delivery': binding}
    (root/'reader/authoring_packet.json').write_text(json.dumps(packet))
    assert validate_delivery(root)['status'] == 'verified'
    report = format_report_context({'status': 'connected_to_report_input', 'context': projection, 'binding': binding})
    assert 'not measured results' in report and ref['sha256'] in report
    # A reader's stale or missing binding must prevent publication too.
    packet['study_context_delivery']['sha256'] = 'bad'
    (root/'reader/authoring_packet.json').write_text(json.dumps(packet))
    with pytest.raises(ValueError, match='consumer stale'):
        validate_delivery(root)
    (root/'reader/authoring_packet.json').write_text('{"reader":true}')
    with pytest.raises(ValueError, match='consumer_binding_missing'):
        validate_delivery(root)


def test_published_report_input_uses_same_context_and_source(delivered):
    import hashlib
    from ptm_shared.study_context_delivery import write_context, load_report_context
    from report_generation.core.dynamic_prompt_generator import format_temporal_evidence_packet_for_llm
    from report_generation.core.biological_synthesis import format_biological_synthesis_packet_for_llm
    root, _, _ = delivered; (root/'reader').mkdir(exist_ok=True)
    _, binding = write_context(root)
    (root/'reader/authoring_packet.json').write_text(json.dumps({'study_context_delivery': binding}))
    files = {str(p.relative_to(root)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in root.rglob('*') if p.is_file()}
    (root/'manifest.json').write_text(json.dumps({'files':files}))
    (root/'enrichment_free_current.json').write_text(json.dumps({'run_id':'run-a', 'artifacts':{
        'provenance': {'path':'provenance.json', 'sha256': files['provenance.json']['sha256']}}}))
    packet = load_report_context(root)
    assert packet['binding'] == binding and packet['semantic_review_status'] == 'not_performed'
    for text in [format_temporal_evidence_packet_for_llm({'study_context_delivery':packet}),
                 format_biological_synthesis_packet_for_llm({'study_context_delivery':packet},section_type='results')]:
        assert binding['sha256'] in text and '실험 설계 α' in text
    assert load_report_context(root/'nonexistent')['status'] == 'unavailable'


@pytest.mark.parametrize('design_text', ['insulin response in adipocytes', 'amyloid-treated microglia 시간 반응',
                                       '약물 A 10 nM; 약물 B 2 µM, 서로 다른 노출 조건'])
def test_neutral_guidance_and_report_draft_isolation(delivered, design_text):
    from ptm_shared.study_context_delivery import write_context, context_markdown, bind_report_state
    from ptm_shared.astra_package import start_here
    from ptm_shared import astra_reader
    from report_generation.core.reader_authoring import build_authoring_packet, format_authoring_packet_for_llm
    from ptm_shared.astra_inputs import source_receipt
    root, _, snapshot = delivered
    snapshot['original']['analysis_context']['biological_question'] = design_text
    snapshot['source_receipt'] = source_receipt(snapshot)
    (root/'study/user_input_snapshot.json').write_text(json.dumps(snapshot))
    (root/'reader').mkdir(exist_ok=True); _, binding = write_context(root)
    context = json.loads((root/'reader/STUDY_CONTEXT.json').read_text())
    saved = {'status':'connected_to_report_input', 'context':context, 'binding':binding,
             'recorded_context':snapshot['original']['analysis_context'], 'recorded_questions':[]}
    draft = {'experimental_context':{'biological_question':'WRONG CURRENT DRAFT','cell_type':'WRONG CELL'},
             'research_questions':['WRONG QUESTION'], 'original_research_questions':['WRONG QUESTION']}
    report_state = bind_report_state(draft, saved)
    packet = build_authoring_packet(report_state)
    text = format_authoring_packet_for_llm(packet, 'introduction')
    assert design_text in text and 'WRONG CURRENT DRAFT' not in text and 'WRONG CELL' not in text
    assert packet['research_question_evidence_map']['questions'] == []
    assert draft['experimental_context']['biological_question']=='WRONG CURRENT DRAFT'
    assert design_text in context_markdown(context)
    guide = start_here(snapshot, {}, {})
    assert 'expected insulin pathway' not in guide and 'insulin cascade' not in guide
    from inspect import getsource
    assert 'expected insulin pathway' not in getsource(astra_reader.attach_reading_guidance)
    assert 'insulin cascade' not in getsource(astra_reader.write_reader)


def test_provided_context_loss_detected_before_write(delivered):
    from ptm_shared.astra_inputs import verify_execution_context
    root, _, snapshot = delivered
    context=json.loads((root/'study/study_context.json').read_text())
    design=json.loads((root/'study/study_design.json').read_text())
    altered=deepcopy(context);del altered['cell_type']
    with pytest.raises(ValueError,match='worker_context /analysis_context/cell_type'):
        verify_execution_context(snapshot,altered,design)
    altered=deepcopy(design);altered['study']['biological_question']=None
    with pytest.raises(ValueError,match='canonical_study /analysis_context/biological_question'):
        verify_execution_context(snapshot,context,altered)
    altered=deepcopy(design);altered['injections']=altered['injections'][1:]
    with pytest.raises(ValueError,match='injection_mapping_changed'):
        verify_execution_context(snapshot,context,altered)
    altered=deepcopy(design);altered['injections'][0]['legacy_replicate']=99
    with pytest.raises(ValueError,match='legacy_replicate_changed'):
        verify_execution_context(snapshot,context,altered)


def test_two_arms_recorded_dose_unit_and_statistical_units(tmp_path):
    from ptm_shared.study_context_delivery import context_projection
    from ptm_shared.study_execution import resolve_context
    samples=[];manifest=[]
    for label,arm,role in [('Control 0min','vehicle','Control'),('A 30min','a','Treatment'),('B 30min','b','Treatment')]:
        for unit in [1,2]:
            for tech in [1,2,3]:
                sid=f'{arm}-{unit}-{tech}'
                samples.append({'sample_id':sid,'condition':label,'arm_id':arm,'group':role,'replicate':unit})
                manifest.append({'sample_id':sid,'condition':label,'biological_unit':f'{arm}-unit-{unit}','technical_injection':str(tech)})
    context={'biological_question':'rat host / human INSR; ambiguous dose only in this prose stays prose',
             'transgene':{'gene':'INSR','taxon':'9606'}, 'treatment_arms':[
                 {'arm_id':'a','name':'A','treatments':[{'name':'compound A','dose':10,'unit':'nM','vehicle':'DMSO','exposure':{'value':30,'unit':'min'}}]},
                 {'arm_id':'b','name':'B','treatments':[{'name':'compound B','dose':2,'unit':'µM','vehicle':'water','exposure':{'value':0.5,'unit':'h'}}]}],
             'replication_plan':{'default_replicates_per_condition':3},
             'sample_manifest':{'pairing':'unpaired','samples':manifest}}
    resolved=resolve_context(context,samples,taxonomy_id='10116',species='rat');design=resolved['study_design']
    snapshot=capture_order({'id':1,'species':'rat','organism_code':10116,'analysis_context':context,'sample_config':{'samples':samples}})
    (tmp_path/'study').mkdir();write_study_inputs(tmp_path,snapshot,resolved,design)
    projection=context_projection(tmp_path);execution=projection['roles']['execution_design']
    arms={a['arm_id']:a for a in execution['arms']}
    for arm in context['treatment_arms']: assert arms[arm['arm_id']]['treatments']==arm['treatments']
    replication=execution['display']['replication']
    assert replication['injection_count']==18 and replication['biological_unit_count']==6
    assert all(c['registered_replicate_count']==2 and c['injection_count']==6 for c in replication['conditions'])
    assert '3' in replication['planned_summary']
    assert {c['pairing'] for c in execution['contrasts']}=={'unpaired'}
    assert projection['roles']['study_design_context']['study_species']=='rat'
    assert snapshot['original']['analysis_context']['transgene']['taxon']=='9606'
    assert design['materials']==resolved['study_design']['materials']


@pytest.mark.parametrize('strategy',['shared_reference','time_matched','explicit_custom'])
def test_control_scope_projection_preserves_exact_mapping_and_unknowns(tmp_path,strategy):
    from ptm_shared.tests.test_control_comparison import inputs, resolved
    from ptm_shared.study_context_delivery import context_projection
    context,samples=inputs('time_matched');context.pop('replication_declaration');context.pop('pairing_policy')
    first=resolved(context,samples);before=deepcopy(first['study_design'])
    policy=first['control_comparison']
    if strategy=='shared_reference':
        zero=next(c['condition_id'] for c in before['conditions'] if c['time']['minutes']==0)
        first['control_comparison']={'strategy':strategy,'reference_condition_id':zero,'source':'user_input'}
    elif strategy=='explicit_custom':
        first['control_comparison']={'strategy':strategy,'source':'user_input','mappings':{
            c['target_condition_id']:c['reference_condition_id'] for c in before['contrasts']}}
    latest=resolved(first,samples);design=latest['study_design']
    from ptm_shared.study_design import require_resolved
    require_resolved(design)
    assert len(design['contrasts'])==len(before['contrasts'])==2
    snapshot=capture_order({'id':2,'analysis_context':latest,'sample_config':samples})
    (tmp_path/'study').mkdir();write_study_inputs(tmp_path,snapshot,latest,design)
    view=context_projection(tmp_path)['roles']['execution_design']
    assert view['contrasts']==design['contrasts'] and view['conditions']==design['conditions']
    assert view['control_comparison']['effective_policy']['strategy']==strategy
    assert design['materials']==before['materials']==[]
    assert design['injections']==before['injections']
    assert all(c['pairing']=='unknown' for c in design['contrasts'])


def test_capture_receipt_cannot_replace_source_identity_or_exclusion_proof(delivered):
    from ptm_shared.astra_inputs import source_receipt
    _,order,snapshot=delivered
    bad=deepcopy(snapshot);bad['source_record_id']='wrong-order';bad['source_receipt']=source_receipt(bad)
    with pytest.raises(ValueError,match='source_record_id'):verify_order_capture(order,bad)
    bad=deepcopy(snapshot);bad['excluded_fields']=[]
    with pytest.raises(ValueError,match='excluded_fields'):verify_order_capture(order,bad)


def test_contract_marker_is_bound_before_dispatch(delivered):
    _,_,snapshot=delivered;bad=deepcopy(snapshot);bad.pop('context_contract')
    with pytest.raises(ValueError,match='context_contract'):verify_snapshot(bad,snapshot['source_receipt'])


def test_saved_host_taxonomy_cannot_be_replaced_by_transgene_taxonomy(delivered):
    from ptm_shared.astra_inputs import verify_execution_context
    root,order,_=delivered
    snapshot=capture_order({**order,'species':'rat','organism_code':10116})
    context=snapshot['original']['analysis_context']
    design=json.loads((root/'study/study_design.json').read_text())
    design['study'].update(species='human',taxonomy_id='9606')
    with pytest.raises(ValueError,match='taxonomy_id'):verify_execution_context(snapshot,context,design)


def test_consumer_value_type_and_record_identity_are_verified(delivered):
    import hashlib
    from ptm_shared.study_context_delivery import write_context, verify_context_binding
    root,_,_=delivered
    _,binding=write_context(root)
    wrong=deepcopy(binding);wrong['source_record_id']='other-order'
    with pytest.raises(ValueError,match='source_record_id'):verify_context_binding(root,wrong)
    path=root/'reader/STUDY_CONTEXT.json';projection=json.loads(path.read_text())
    projection['whole_evidence']['selected_findings_is_scope_limit']=0  # false and zero differ
    path.write_text(json.dumps(projection));binding['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='selected_findings_is_scope_limit'):
        verify_context_binding(root,binding)
