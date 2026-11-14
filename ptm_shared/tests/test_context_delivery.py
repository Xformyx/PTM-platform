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


@pytest.mark.parametrize('mutation', ['pointer', 'canonical', 'manifest_missing', 'stale_design'])
def test_file_boundary_faults(delivered, mutation):
    root, _, _ = delivered
    path = root/'study/input_field_manifest.csv'; frame = pd.read_csv(path, keep_default_na=False)
    if mutation == 'pointer': frame.loc[0, 'original_value_ref'] = 'study/user_input_snapshot.json#/original/report_options'
    elif mutation == 'canonical': frame.loc[0, 'canonical_value_ref'] = 'study/study_design.json#/nonexistent'
    elif mutation == 'manifest_missing': frame = frame.iloc[1:]
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
    (root/'reader').mkdir()
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
    root, _, _ = delivered; (root/'reader').mkdir()
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
