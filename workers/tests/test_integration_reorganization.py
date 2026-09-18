"""Importable contract regressions for the 2026-09 integration audit.

Synthetic inputs only; frozen scientific truth and historical artifacts are not
used as discovery inputs or modified by these tests.
"""
import json

import numpy as np
import pandas as pd
import pytest

from test_observation_denominator_contract import analyzer_for, quantify
from ptm_shared.vector_projection import project_report_vector_row
from ptm_shared.site_form_provenance import peptide_mapping_assertion


def test_det01_loss_reaches_reader_without_fold_change_or_significance():
    _, _, vector = quantify(analyzer_for([10, 12, np.nan], [100, 100, 100]))
    assert len(vector) == 1
    row = vector.iloc[0]
    assert row['Detection_Control'] == '2/2'
    assert row['Detection_Treatment'] == '0/1'
    assert row['PTM_ProteinAdjusted_Missing_Reason'] == 'treatment_not_detected'
    for key in ('PTM_Unadjusted_Log2FC', 'PTM_ProteinAdjusted_Log2FC', 'p_value', 'q_value'):
        assert pd.isna(row[key])
    reader = project_report_vector_row(row.to_dict())
    assert reader['detection_context_only']
    assert reader['ptm_unadjusted_log2fc'] is None


def test_obs02_multisite_form_keeps_all_modifications_without_duplicate_n():
    analyzer = analyzer_for([10, 12, 20], [100, 100, 100])
    analyzer.pr_matrix_normalized['Modified.Sequence'] = 'AAS(UniMod:21)T(UniMod:21)YK'
    analyzer.pr_matrix_normalized['Precursor.Charge'] = 3
    analyzer.pr_matrix_normalized['Localization.Probability'] = 0.6
    analyzer.fasta_dict = {'P1': 'MAASTYKASTYK'}
    _, _, vector = quantify(analyzer)
    assert len(vector) == 1
    row = vector.iloc[0]
    assert row['PTM_Position'] == 'S4;T5'
    assert row['Precursor.Charge'] == 3
    assert row['PTM_Unadjusted_Control_N'] == 2
    provenance = project_report_vector_row(row.to_dict())['measurement_provenance']
    assert provenance['modification_form']['target_modification_count'] == 2
    assert provenance['localization_evidence']['status'] == 'recorded_below_class_I_threshold'
    assert not provenance['site_mapping_assertion']['independent_site_observations']


def test_obs03_every_occurrence_and_accession_is_preserved():
    mapping = peptide_mapping_assertion('P2;P1', 'AS(UniMod:21)K', {'P1': 'ASKASK', 'P2': 'MASK'}, ['21'])
    assert mapping['status'] == 'ambiguous'
    assert [(c['accession'], c['peptide_start']) for c in mapping['candidates']] == [('P1', 1), ('P1', 4), ('P2', 2)]
    assert mapping == peptide_mapping_assertion('P1;P2', 'AS(UniMod:21)K', {'P2': 'MASK', 'P1': 'ASKASK'}, ['21'])


def test_obs01_charge_stays_distinct_even_with_reused_precursor_label():
    analyzer = analyzer_for([10, 12, 20], [100, 100, 100])
    first = analyzer.pr_matrix_normalized.iloc[0].to_dict()
    analyzer.pr_matrix_normalized = pd.DataFrame([{**first, 'Precursor.Charge': 2}, {**first, 'Precursor.Charge': 3, 't1': 40}])
    _, _, vector = quantify(analyzer)
    assert len(vector) == 2
    assert sorted(vector['PTM_Unadjusted_Control_N']) == [2, 2]
    assert len({project_report_vector_row(r)['feature_id'] for r in vector.to_dict('records')}) == 2
    assert vector['PTM_Unadjusted_Log2FC'].max() - vector['PTM_Unadjusted_Log2FC'].min() == pytest.approx(1)


def test_obs05_conflict_quarantine_is_order_invariant(tmp_path):
    analyzer = analyzer_for([10, 12, 20], [100, 100, 100])
    analyzer.output_dir = tmp_path
    row = analyzer.pr_matrix_normalized.iloc[0].to_dict()
    analyzer.pr_matrix_normalized = pd.DataFrame([row, row, {**row, 't1': 99}])
    assert analyzer.filter_target_ptms().empty
    assert len(json.loads((tmp_path / 'conflicting_precursors.json').read_text())) == 2
    analyzer.pr_matrix_normalized = analyzer.pr_matrix_normalized.iloc[::-1]
    assert analyzer.filter_target_ptms().empty


def test_det03_loss_does_not_change_valid_bh_family():
    analyzer = analyzer_for([10, 12, 20], [100, 100, 100])
    analyzer.sample_columns.append('t2')
    analyzer.condition_map['t2'] = '5min'
    analyzer.pr_matrix_normalized['t2'] = 23
    analyzer.pg_matrix_normalized['t2'] = 100
    _, _, baseline = quantify(analyzer)
    loss = analyzer.pr_matrix_normalized.iloc[0].to_dict()
    analyzer.pr_matrix_normalized = pd.concat([analyzer.pr_matrix_normalized, pd.DataFrame([{**loss, 'Precursor.Id': 'loss', 't1': np.nan, 't2': np.nan}])], ignore_index=True)
    _, _, after = quantify(analyzer)
    assert len(after) == 2
    assert after.loc[after['Precursor.Id'] == 'form1', 'q_value'].iloc[0] == baseline['q_value'].iloc[0]
    assert pd.isna(after.loc[after['Precursor.Id'] == 'loss', 'q_value'].iloc[0])


def test_rel01_active_and_passive_have_same_ordered_kinase_role():
    from rag_enrichment.core.regulation_extractor import RegulationExtractor
    extractor = RegulationExtractor()
    for text in ('AKT1 phosphorylates FOXO3.', 'FOXO3 is phosphorylated by AKT1.'):
        result = extractor.extract_from_articles([{'abstract': text, 'pmid': '12345'}], 'FOXO3', 'S253')
        assert [(r['kinase'], r['substrate']) for r in result['kinase_substrate']] == [('AKT1', 'FOXO3')]
        assert {r['regulator'] for r in result['regulation_evidence']} == {'AKT1'}


@pytest.mark.parametrize('text', ['FOXO3 is not phosphorylated by AKT1.', 'AKT1 does not phosphorylate FOXO3.', 'AKT1 indirectly phosphorylates FOXO3.'])
def test_rel02_negation_and_indirectness_remain_assertions_not_positive_edges(text):
    from rag_enrichment.core.regulation_extractor import RegulationExtractor
    result = RegulationExtractor().extract_from_articles([{'abstract': text}], 'FOXO3', 'S253')
    assert not result['kinase_substrate']
    assert result['regulation_evidence']
    assert all(r['polarity'] != 'positive' or r['directness'] != 'direct_wording' for r in result['regulation_evidence'])


def test_motif01_hit_must_anchor_modified_residue(tmp_path):
    from preprocessing.core.enhanced_motif_analyzer_v2 import EnhancedMotifAnalyzerV2
    analyzer = EnhancedMotifAnalyzerV2(cache_dir=str(tmp_path))
    # The proline-directed motif is at S1, while the measured modification is S5.
    wrong = analyzer.predict_regulator('SPAGSAA', 'Phosphorylation', ptm_indices=[4])
    right = analyzer.predict_regulator('SPAGSAA', 'Phosphorylation', ptm_indices=[0])
    assert 'Proline' not in wrong[0] and 'CDK' not in wrong[1]
    assert right != wrong
    absent = analyzer.predict_regulator('AAAAAAA', 'Phosphorylation', ptm_indices=[])
    assert 'PP1' not in absent[1] and 'PP2A' not in absent[1]


@pytest.mark.parametrize('review_count', [4, 5])
def test_rag01_exact_site_quota_reserves_primary_and_obeys_requested_size(review_count):
    from report_generation.core.rag_retriever import apply_source_quota
    reviews = [{'document': f'review{i}', 'is_review': True, 'source_type': 'review'} for i in range(review_count)]
    primary = [{'document': f'primary{i}', 'is_review': False, 'source_type': 'research_article'} for i in range(10)]
    selected = apply_source_quota(reviews + primary, n_results=4, purpose='exact_site', background_slots=5)
    assert len(selected) <= 4
    assert any(not r['is_review'] for r in selected)
    assert apply_source_quota(reviews, n_results=0, purpose='exact_site', background_slots=5) == []


def test_src04_full_entity_context_and_coverage_keys_differ():
    from ptm_shared.evidence_contracts import source_cache_key
    prefix = [f'G{i}' for i in range(20)]
    key = source_cache_key('kea3', genes=prefix + ['A'], budget=4, context='human')
    assert key != source_cache_key('kea3', genes=prefix + ['B'], budget=4, context='human')
    assert key != source_cache_key('kea3', genes=prefix + ['A'], budget=5, context='human')
    assert key != source_cache_key('kea3', genes=prefix + ['A'], budget=4, context='mouse')


def _revision(tmp_path, text='Bound observation [1]', release=None):
    from ptm_shared.report_revision import register_revision, file_sha256
    source = tmp_path / 'report.md'
    source.write_text(text)
    return register_revision(tmp_path, files=[str(source)],
        manifest={'artifacts': [{'role': 'report_markdown_1', 'path': str(source), 'sha256': file_sha256(source)}]},
        release=release or {'status': 'review_draft', 'review_artifact_available': True, 'publish_as_final': False},
        references=[{'reference_id': 'pmid:22222', 'pmid': '22222', 'number': 1}])


def test_rev02_immutable_idempotent_snapshot_and_rollback(tmp_path):
    from ptm_shared.report_revision import read_revision, verify_revision, revision_download_path, select_current_revision
    first = _revision(tmp_path)
    assert _revision(tmp_path)['revision_id'] == first['revision_id']
    later = _revision(tmp_path, 'Changed observation')
    assert later['revision_id'] != first['revision_id']
    assert revision_download_path(tmp_path, first['artifacts'][0]['filename'], first).read_text() == 'Bound observation [1]'
    assert verify_revision(tmp_path, first)
    select_current_revision(tmp_path, first['revision_id'])
    assert read_revision(tmp_path)['revision_id'] == first['revision_id']
    assert len(list((tmp_path / '.report_revisions/history').glob('*.json'))) == 3


def test_rev01_blocked_and_tampered_artifacts_cannot_download(tmp_path):
    from ptm_shared.report_revision import revision_download_path, verify_revision
    blocked = _revision(tmp_path, release={'status': 'blocked_final', 'review_artifact_available': False})
    with pytest.raises(ValueError, match='release_withheld'):
        revision_download_path(tmp_path, blocked['artifacts'][0]['filename'])
    blocked['release']['review_artifact_available'] = True
    with pytest.raises(ValueError, match='registry_integrity'):
        verify_revision(tmp_path, blocked)
    available = _revision(tmp_path, text='next')
    (tmp_path / available['artifacts'][0]['filename']).write_text('tampered')
    with pytest.raises(ValueError, match='artifact_integrity'):
        revision_download_path(tmp_path, available['artifacts'][0]['filename'])


def test_find01_inventory_exceeds_main_scope_and_redundancy_does_not_inflate():
    from test_task10_findings import finding_state
    from report_generation.core.reader_authoring import build_authoring_packet
    from report_generation.core.measured_feature_cards import select_finding_cards
    packet = build_authoring_packet(finding_state(12))
    cards = packet['reader_cards']
    selected, audit = select_finding_cards(cards)
    assert len(selected) > 4
    duplicate_selected, _ = select_finding_cards(cards + cards)
    assert len(selected) == len(duplicate_selected)
    assert packet['coverage_inventory']['accounted_count'] == packet['coverage_inventory']['input_count']
    assert audit['contract_version'] == 'report_finding_selection.v4'


def _source_module(name):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[2] / 'mcp-server' / 'app' / 'tools' / f'{name}.py'
    spec = importlib.util.spec_from_file_location('fixture_source_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('status, expected', [(200, 'no_hit'), (429, 'rate_limited'), (500, 'api_error')])
def test_src03_source_no_hit_and_http_failures_are_distinct(monkeypatch, status, expected):
    import asyncio
    import httpx
    module = _source_module('stringdb')
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=[]))
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: client(transport=transport))
    result = asyncio.run(module.query_stringdb('TEST', species='9606'))
    assert result['query_status'] == expected
    assert result['source_record']['status'] == expected
    assert result['source_record']['novelty_established'] is False


def test_src01_actual_kea3_response_keys_reach_legacy_consumer():
    from common.mcp_client import MCPClient
    from types import SimpleNamespace
    response = {'top_kinases': [{'kinase': 'AKT1', 'rank': 1, 'score': 2.1}],
                'integrated_ranking': [{'kinase': 'AKT1', 'rank': 1, 'score': 2.1}]}
    client = MCPClient(base_url="https://fixture.invalid", timeout=1)
    client.base_url, client.timeout = 'https://fixture.invalid', 1
    client._local.session = SimpleNamespace(post=lambda *args, **kwargs: SimpleNamespace(json=lambda: response, raise_for_status=lambda: None))
    assert client.query_kea3(['FOXO3', 'BAD'])['kinases'][0]['kinase'] == 'AKT1'


def test_rag02_later_tier_primary_source_participates_before_quota(monkeypatch):
    import asyncio
    module = _source_module('pubmed')
    async def aliases(*args): return []
    calls = []
    async def search(query, budget):
        calls.append(query)
        return ['9'] if len(calls) == 2 else ['1', '2', '3', '4']
    async def europe(*args): return []
    async def details(pmids):
        return [{'pmid': p, 'title': 'AKT1 S473 phosphorylation insulin' if p == '9' else 'General review', 'abstract': ''} for p in pmids]
    monkeypatch.setattr(module, '_fetch_gene_aliases', aliases)
    monkeypatch.setattr(module, '_esearch', search)
    monkeypatch.setattr(module, '_search_europe_pmc', europe)
    monkeypatch.setattr(module, '_fetch_article_details', details)
    result = asyncio.run(module._multi_tier_search('AKT1', 'S473', 'Phosphorylation', ['insulin'], 4))
    assert result['articles'][0]['pmid'] == '9'
    assert result['candidate_count_before_quota'] == 5
    assert len(result['articles']) == 4


def test_ref01_uniprot_ptm_features_and_full_go_survive_display_projection(monkeypatch):
    import asyncio
    import httpx
    module = _source_module('uniprot')
    payload = {'features': [{'type': 'Modified residue', 'description': 'Phosphoserine', 'location': {'start': {'value': 4}, 'end': {'value': 4}}, 'evidences': [{'source': 'PubMed', 'id': '22222'}]}],
               'uniProtKBCrossReferences': [{'database': 'GO', 'id': f'GO:{i}', 'properties': [{'key': 'GoTerm', 'value': 'P:biological process'}]} for i in range(30)]}
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload, headers={'X-UniProt-Release': 'fixture-release'}))
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: client(transport=transport))
    result = asyncio.run(module.query_uniprot('P12345'))
    assert result['ptm_features'] == payload['features']
    assert len(result['go_terms_bp']) == 30
    assert result['source_record']['snapshot'] == 'fixture-release'
    assert result['full_source_evidence']['uniProtKBCrossReferences'] == payload['uniProtKBCrossReferences']


def test_net01_ppi_level_and_reciprocal_candidate_edges_are_preserved():
    from report_generation.core.nodes.network_node import _scoped_relation_view
    nodes = [{'id': 'A-S1', 'gene': 'A', 'site': 'S1'}, {'id': 'A-S2', 'gene': 'A', 'site': 'S2'}, {'id': 'B-T3', 'gene': 'B', 'site': 'T3'}]
    edges = [{'source': a, 'target': b, 'evidence_type': kind, 'confidence': .8} for a, b, kind in [
        ('A-S1', 'B-T3', 'STRING'), ('A-S2', 'B-T3', 'STRING'),
        ('A-S1', 'B-T3', 'Kinase-Substrate'), ('B-T3', 'A-S1', 'Kinase-Substrate')]]
    context, relations = _scoped_relation_view(nodes, edges)
    assert len(relations) == 3
    ppi = next(r for r in relations if r['evidence_type'] == 'STRING')
    assert (ppi['source'], ppi['target'], ppi['subject_level']) == ('A', 'B', 'gene')
    assert {'A-S1', 'A-S2', 'B-T3'} == set(ppi['observation_node_ids'])
    assert not any(r['current_experiment_direct_relation'] for r in relations)
    assert {(r['source'], r['target']) for r in relations if r['evidence_type'] == 'Kinase-Substrate'} == {('A', 'B'), ('B', 'A')}


def test_time01_explicit_units_drive_matrix_not_condition_means(tmp_path):
    from ptm_shared.feature_identity import canonical_feature_identity
    from ptm_shared.temporal_input_reconstruction import load_biological_replicate_series
    base = {'Protein.Group': 'P1', 'Gene.Name': 'GENE', 'PTM_Position': 'S2', 'Modified.Sequence': 'AS(UniMod:21)K', 'Precursor.Id': 'z2', 'Precursor.Charge': 2}
    rows, samples = [], []
    for unit in range(3):
        for condition, value in [('Control', 1), ('1min', 2 ** unit), ('5min', 2 ** (2-unit))]:
            for repeat in range(2):
                sid = f'{unit}_{condition}_{repeat}'
                rows.append({**base, 'Sample': sid, 'Condition': condition, 'PTM_Relative_Abundance': value})
                samples.append({'sample_id': sid, 'condition': condition, 'biological_unit': str(unit)})
    pd.DataFrame(rows).to_csv(tmp_path / 'site_level_relative_quantification_normalized_phospho.tsv', sep='\t', index=False)
    manifest = {'samples': samples, 'pairing': 'paired'}
    fid = canonical_feature_identity(base)['feature_id']
    result, audit = load_biological_replicate_series(tmp_path, file_suffix='_phospho', conditions=['1min', '5min'], sample_manifest=manifest, feature_identities={fid: {}})
    assert result[fid]['matrix'] == [[0, 2], [1, 1], [2, 0]]
    assert audit['features'][fid]['biological_n'] == 3
    unavailable, status = load_biological_replicate_series(tmp_path, file_suffix='_phospho', conditions=['1min', '5min'], sample_manifest=None, feature_identities={fid: {}})
    assert unavailable == {} and status['status'] == 'not_evaluable'


def test_mig01_backfill_keeps_bytes_unverified_and_reversible(tmp_path):
    from ptm_shared.report_revision import backfill_legacy_revision, revision_download_path
    original = tmp_path / 'old.md'
    original.write_bytes(b'Historical bytes')
    revision = backfill_legacy_revision(tmp_path, ['old.md'])
    assert revision['release']['status'] == 'legacy_not_gated'
    assert revision['release']['publish_as_final'] is False
    assert revision_download_path(tmp_path, revision['artifacts'][0]['filename']).read_bytes() == original.read_bytes()


def test_review01_model_approval_cannot_close_major_issue():
    from report_generation.core.nodes.report_copilot_node import review_issue_ledger
    from report_generation.core.report_release import resolve_report_release
    ledger = review_issue_ledger({'overall_quality': 'good', 'section_reviews': [{'severity': 'high', 'section': 'Results', 'description': 'Unbound causal claim'}]})
    release = resolve_report_release(reader_authoring_shadow=True,
        output_correctness={'status': 'release_candidate', 'review_issue_ledger': ledger}, artifact_manifest=None)
    assert not release['publish_as_final']
    assert 'major_review_issue_unresolved' in release['reason_codes']


def test_src04_stage_cache_tracks_content_policy_and_preserves_history(tmp_path):
    from common.phase_b_cache import stage_fingerprint, stage_cache_valid, record_stage_completion, preserve_stage_outputs
    source, output = tmp_path / 'input.tsv', tmp_path / 'result.tsv'
    source.write_text('1\n')
    output.write_text('computed\n')
    key = stage_fingerprint({'raw': source}, {'normalization': 'legacy_median.v1'})
    record_stage_completion(tmp_path, 'quantification', key, [output.name])
    assert stage_cache_valid(tmp_path, 'quantification', key, [output.name])
    source.write_text('2\n')
    changed = stage_fingerprint({'raw': source}, {'normalization': 'legacy_median.v1'})
    assert changed != key and not stage_cache_valid(tmp_path, 'quantification', changed, [output.name])
    assert changed != stage_fingerprint({'raw': source}, {'normalization': 'already_normalized.v1'})
    preserve_stage_outputs(tmp_path, [output.name])
    assert not output.exists()
    assert next((tmp_path / '.preprocessing_history').rglob('result.tsv')).read_text() == 'computed\n'


def test_unit01_secondary_crosswalk_requires_declared_units():
    from ptm_shared.sample_manifest import biological_unit_crosswalk
    def manifest(prefix):
        return {'pairing': 'paired', 'samples': [
            {'sample_id': f'{prefix}-{u}-{t}', 'biological_unit': f'{prefix}{u}', 'condition': 'Control'}
            for u in range(3) for t in range(2)]}
    p, s = manifest('primary'), manifest('secondary')
    assert biological_unit_crosswalk(p, s)['status'] == 'pairing_not_declared'
    links = [{'primary_biological_unit': f'primary{u}', 'secondary_biological_unit': f'secondary{u}'} for u in range(3)]
    result = biological_unit_crosswalk(p, s, links)
    assert len(result['pairs']) == 3 and not result['unpaired_secondary_units']
    assert len(result['pairs'][0]['secondary_sample_ids']) == 2
    with pytest.raises(ValueError):
        biological_unit_crosswalk(p, s, links + [links[0]])


def test_rag_review_budget_accounts_for_every_unreviewed_candidate(monkeypatch):
    from report_generation.core import finding_literature as mod
    monkeypatch.setattr(mod, 'FINDING_RETRIEVAL_BACKOFF_SECONDS', 0)
    class Retriever:
        collection_names = ['fixture']
        def query(self, *args, **kwargs):
            return []
    cards = [{'feature_identity': {'reader_feature_id': str(i), 'gene': f'G{i}'}} for i in range(12)]
    result = mod.retrieve_finding_literature(cards, Retriever(), {}, policy={'max_queries': 1, 'max_model_calls': 0})
    assert len(result['records']) == 12
    assert result['cost']['queries'] == 1
    assert all(row['status'] in {'budget_exhausted', 'not_explained_by_retrieved_evidence'} for row in result['records'].values())


def test_pptx01_plan_uses_bound_observation_and_keeps_trailing_limitations():
    from common.pptx_generator import slide_plan_from_revision
    finding = {'finding_id': 'f1', 'observation': 'Detection only. ' * 100 + 'Protein denominator unavailable.',
               'evidence_ids': ['e1'], 'alternative_explanation': 'No conventional fold change is estimable.'}
    packet = {'reader_cards': [{'card_id': 'c1', 'evidence_ids': ['e1']}]}
    plan = slide_plan_from_revision({'key_findings': [finding]}, packet, {'revision_id': 'source', 'references': []})
    text = json.dumps(plan)
    assert len(plan['slides']) > 1
    assert 'Protein denominator unavailable' in text
    assert 'No conventional fold change' in text
    assert '99' not in text
    with pytest.raises(ValueError, match='evidence_unbound'):
        slide_plan_from_revision({'key_findings': [{**finding, 'evidence_ids': ['other']}]}, packet, {'revision_id': 'source'})


@pytest.mark.parametrize('policy,expected', [('legacy_median.v1', 0), ('already_normalized.v1', 1)])
def test_norm02_global_shift_is_explicitly_policy_dependent(tmp_path, policy, expected):
    from preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer
    analyzer = PTMQuantificationAnalyzer(str(tmp_path / 'fixture.fasta'), str(tmp_path), normalization_policy=policy)
    values = pd.DataFrame({'c': [10, 20, 30], 't': [20, 40, 60]})
    analyzer._normalize_matrix(values, ['c', 't'], 'PR')
    assert np.log2(values.t / values.c).tolist() == pytest.approx([expected] * 3)


def test_det03_complete_all_loss_import_retains_inventory_and_reader(tmp_path):
    from preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer
    fasta = tmp_path / 'fixture.fasta'
    fasta.write_text('>sp|P1|GENE Protein GN=GENE\nMASK\n')
    pr, pg = tmp_path / 'pr.tsv', tmp_path / 'pg.tsv'
    row = {'Protein.Group': 'P1', 'Precursor.Id': 'form1', 'Modified.Sequence': 'AS(UniMod:21)K',
           'Precursor.Charge': 2, 'c1': 10, 'c2': 12, 't1': np.nan, 't2': np.nan}
    pd.DataFrame([row]).to_csv(pr, sep='\t', index=False)
    pd.DataFrame([{'Protein.Group': 'P1', 'c1': 100, 'c2': 100, 't1': 100, 't2': 100}]).to_csv(pg, sep='\t', index=False)
    output = tmp_path / 'output'
    analyzer = PTMQuantificationAnalyzer(str(fasta), str(output), condition_map={'c1': 'Control', 'c2': 'Control', 't1': '5min', 't2': '5min'})
    assert analyzer.run_analysis(str(pr), str(pg))
    pointer = json.loads((output / 'observation_inventory_current.json').read_text())
    inventory = json.loads((output / pointer['filename']).read_text())
    assert inventory['analysis_completed']
    assert inventory['records'][0]['analysis_status'] == 'processed'
    assert inventory['input_sample_observations'] == 4
    vector = pd.read_csv(output / 'ptm_vector_data_normalized_phospho.tsv', sep='\t')
    assert len(vector) == 1
    projected = project_report_vector_row(vector.iloc[0].to_dict())
    assert projected['detection_context_only'] and projected['ptm_unadjusted_log2fc'] is None


def test_review01_repair_revalidates_transitive_summaries_and_keeps_valid_sibling():
    from report_generation.core.nodes.report_copilot_node import apply_bounded_review_repairs
    from report_generation.core.reader_authoring import build_authoring_packet
    from test_task10_findings import finding_state
    packet = build_authoring_packet(finding_state())
    state = {'authoring_packet': packet, 'sections': {
        'results': 'The measured pattern varies over time. AKT1 directly causes this response.',
        'discussion': 'The interpretation remains uncertain.', 'abstract': 'A temporal pattern was observed.',
        'title': 'Observed PTM patterns', 'methods': 'Measurements were compared.'}}
    sections, trace = apply_bounded_review_repairs(state, {'section_reviews': [{'section': 'Results'}]})
    assert trace['attempts'] == 1
    assert trace['affected_sections'] == ['abstract', 'discussion', 'results', 'title']
    assert 'The measured pattern varies over time.' in sections['results']
    assert 'directly causes' not in sections['results']
    assert trace['status'] == 'specific_issue_verification_pending'


def test_cite01_graph_to_actual_html_and_docx_keeps_first_cited_identity(tmp_path):
    import re
    from report_generation.core.graph import format_citations
    from common.markdown_to_html import convert_report_to_html
    from common.markdown_to_docx import convert_report_to_docx
    from docx import Document
    refs = [{'pmid': p, 'title': 'Shared title', 'authors': 'Fixture author', 'year': '2026', 'journal': 'Fixture journal'} for p in ['11111', '22222']]
    state = {'report_config': {'report_audience': 'technical_audit', 'reader_authoring_mode': 'legacy',
        'technical_audit_explicit': True, 'technical_audit_delivery': 'embedded_technical_report'},
        'sections': {'title': 'Synthetic citation integration fixture',
                     'results': 'Measured signal increased by 1.0 log2 units [REF:pmid:22222].',
                     'discussion': 'The temporal pattern alone does not establish direct causality [REF:pmid:11111].'},
        'network_analysis': {}, 'signal_flow_figures': [], 'collected_references': refs}
    result = format_citations(state)
    assert [r['pmid'] for r in result['resolved_references']] == ['22222', '11111']
    md = tmp_path / 'citation_fixture.md'
    md.write_text(result['final_report'])
    # Even a legacy caller supplying collection order must not corrupt the popup.
    html_path = convert_report_to_html(str(md), references=refs)
    html = __import__('pathlib').Path(html_path).read_text()
    registry = json.loads(re.search(r'const articlesData = (.*?);', html).group(1))
    assert registry['1']['pmid'] == '22222' and registry['2']['pmid'] == '11111'
    assert 'data-ref="1"' in html and 'https://pubmed.ncbi.nlm.nih.gov/22222/' in html
    docx = convert_report_to_docx(str(md))
    text = '\n'.join(p.text for p in Document(docx).paragraphs)
    assert 'direct causality' in text and '22222' in text
    assert text.index('22222') < text.index('11111')


def test_rev01_partial_export_registers_immutable_draft_bytes_without_mutating_source(tmp_path):
    from report_generation.core.report_finalization import finalize_report_revision
    from report_generation.core.report_artifact_manifest import _artifact
    from ptm_shared.report_revision import read_revision, verify_revision
    source = tmp_path / 'source.md'
    source.write_text('# Observed pattern\n\nAn observation with a stated limitation.')
    def html(path):
        target = __import__('pathlib').Path(path).with_suffix('.html')
        target.write_text(__import__('pathlib').Path(path).read_text())
        return target
    def failed_docx(path):
        raise RuntimeError('fixture missing converter')
    result = finalize_report_revision(source_paths=[source], output_dir=tmp_path,
        correctness={'status': 'release_candidate'},
        manifest={'status': 'validated', 'report_eligible': True, 'artifacts': [_artifact('markdown', source, required=True)]},
        figure_manifest={}, reader_mode=True, exporters={'html': html, 'docx': failed_docx}, register_immutable=True)
    revision = verify_revision(tmp_path, read_revision(tmp_path))
    assert not result['release']['publish_as_final']
    assert result['release']['status'] == 'draft_review_required'
    assert 'Review draft' not in source.read_text()
    for artifact in revision['artifacts']:
        if artifact['role'] == 'report':
            assert 'Review draft' in (tmp_path / artifact['filename']).read_text()


@pytest.mark.parametrize('mode,report_type', [('cross_talk', 'extended'), ('ptm_only', 'co_scientist')])
def test_dag01_compiled_state_preserves_requested_analysis_before_writer(monkeypatch, mode, report_type):
    from report_generation.core import graph as mod
    from report_generation.core.reader_authoring import build_authoring_packet, deterministic_authoring_plan
    from report_generation.core.section_model_packet import build_section_model_packet
    from report_generation.core.nodes import crosstalk_node
    calls = []
    def node(name):
        def run(state):
            calls.append(name)
            return {}
        return run
    names = ['load_context', 'generate_questions', 'research', 'hypothesize', 'validate_hypotheses',
             'data_verification', 'network_analysis', 'temporal_comovement', 'kinase_annotation',
             'atlas_claim_ledger', 'generate_atlas_report', 'rq_refinement', 'external_coscientist_context',
             'report_copilot', 'cascade_mediator', 'generate_qa_report', 'format_citations', 'edit_report']
    names.append('prepare_cascade_context')
    for name in names:
        monkeypatch.setattr(mod, name, node(name))
    def cross(state, *, analysis_only=False):
        assert analysis_only
        calls.append('crosstalk_analysis')
        return {'cross_talk_data': {'evaluation_status': 'computed', 'dual_ptm_proteins': [{'gene': 'G', 'evidence_role': 'observation'}]}}
    monkeypatch.setattr(crosstalk_node, 'run_crosstalk_analysis', cross)
    def drug(state):
        calls.append('drug_repositioning')
        return {'drug_repositioning_results': {'evaluation_status': 'computed' if state['report_type'] == 'extended' else 'not_requested'}}
    monkeypatch.setattr(mod, 'drug_repositioning', drug)
    def write(state):
        calls.append('write_sections')
        packet = build_authoring_packet(state)
        projected = build_section_model_packet(packet, deterministic_authoring_plan(packet), 'results')
        assert projected['module_evidence']['cross_talk']['evaluation_status'] == ('computed' if mode == 'cross_talk' else 'not_requested')
        assert projected['module_evidence']['drug_repositioning']['analysis']['evaluation_status'] == ('computed' if report_type == 'extended' else 'not_requested')
        return {'authoring_packet': packet}
    monkeypatch.setattr(mod, 'write_sections', write)
    mod.build_report_graph().invoke({'analysis_mode': mode, 'report_type': report_type}, {'recursion_limit': 40})
    assert calls.index('drug_repositioning') < calls.index('write_sections')
    assert calls.index('prepare_cascade_context') < calls.index('write_sections')
    if mode == 'cross_talk':
        assert calls.index('crosstalk_analysis') < calls.index('write_sections')
    if report_type == 'co_scientist':
        assert calls.index('data_verification') < calls.index('write_sections')


def test_llm01_indivisible_packet_is_not_truncated_to_fit_budget():
    from report_generation.core.reader_authoring import build_authoring_packet, deterministic_authoring_plan
    from report_generation.core.section_model_packet import partition_section_prompts
    from test_task10_findings import finding_state
    packet = build_authoring_packet(finding_state())
    plan = deterministic_authoring_plan(packet)
    parts = partition_section_prompts(packet, 'results', plan, input_token_budget=200000, output_reserve=8000)
    prompt, trace = parts[0]
    assert trace['resolved_prompt'] == prompt
    assert trace['token_count_method'] == 'utf8_byte_upper_bound_fallback'
    assert trace['input_token_budget'] == 192000
    assert '"axis"' in prompt and 'estimator' in prompt
    with pytest.raises(ValueError, match='exceeds_section_budget'):
        partition_section_prompts(packet, 'results', plan, input_token_budget=40, output_reserve=20)


def test_rel03_same_lysine_ptm_type_is_not_shared_and_all_sites_is_explicit():
    from pathlib import Path
    import importlib.util
    path = Path(__file__).resolve().parents[2] / 'mcp-server/app/tools/iptmnet.py'
    spec = importlib.util.spec_from_file_location('fixture_iptmnet', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = '<table><tr><th>Site</th><th>PTM Type</th><th>Source</th></tr><tr><td>K12</td><td>Acetylation</td><td>PSP</td></tr><tr><td>K12</td><td>Ubiquitination</td><td>UniProt</td></tr></table>'
    rows = mod._parse_sites_from_html(source, 'K12', target_ptm_type='acetylation')
    assert len(rows) == 1 and rows[0].ptm_type == 'Acetylation'
    assert mod._parse_sites_from_html(source, '') == []
    assert len(mod._parse_sites_from_html(source, '', all_sites=True)) == 2


def test_dag01_generated_prose_cannot_recalculate_frozen_context_figures(monkeypatch, tmp_path):
    from report_generation.core.graph import prepare_cascade_context, cascade_mediator
    from report_generation.core.nodes import cascade_mediator_node
    figure = tmp_path / 'context.png'
    figure.write_bytes(b'fixed fixture diagram')
    seen = []
    def prepare(state):
        seen.append(state['sections'])
        return {'cascade_diagrams': {'combined': str(figure)}, 'cascade_pathway_names': {'combined': ['Pathway A']}}
    monkeypatch.setattr(cascade_mediator_node, 'run_cascade_mediator', prepare)
    state = {'pathway_candidates': {'candidates': [{'name': 'Pathway A'}, {'name': 'Pathway B'}]},
             'sections': {'results': 'Invented protein X activates Y.'}}
    frozen = prepare_cascade_context(state)
    assert 'Invented' not in json.dumps(seen)
    result = cascade_mediator({**state, **frozen, 'sections': {'results': 'Different invented causal edge.'}})
    assert len(seen) == 1 and result['cascade_diagrams'] == frozen['cascade_diagrams']
    assert frozen['cascade_context_snapshot']['display_exclusions'][0]['pathway'] == 'Pathway B'
    figure.write_bytes(b'modified figure')
    with pytest.raises(ValueError, match='frozen_cascade_figure_changed'):
        cascade_mediator(frozen)


def test_src02_kinase_aliases_preserve_hypothesis_role_and_qualitative_confidence():
    from dataclasses import asdict
    from rag_enrichment.core.llm_kinase_predictor import LLMKinasePredictor
    predictor = object.__new__(LLMKinasePredictor)
    results = []
    for key, envelope in (("kinase", "predictedKinases"), ("kinase_name", "predicted_kinases")):
        result = predictor._build_result("FOXO3", "S253", "phosphorylation", {
            envelope: [{key: "AKT1", "confidence": "very confident", "score": "unknown",
                        "evidenceType": "direct", "source": "KEA3"}]})
        results.append(asdict(result.predicted_kinases[0]))
    assert results[0] == results[1]
    assert results[0]["kinase"] == "AKT1"
    assert results[0]["confidence"] == "unknown"
    assert results[0]["source"] == "LLM"
    assert results[0]["evidence_type"] == "model_hypothesis"
    assert results[0]["source_assertion_status"] == "not_verified"


def test_dag01_crosstalk_retains_opposing_forms_missingness_and_unknown_mechanism(tmp_path):
    from report_generation.core.nodes.crosstalk_node import build_crosstalk_data
    primary = pd.DataFrame([
        {"Gene.Name": "AKT1", "PTM_Position": "S1", "Condition": "5min", "PTM_Relative_Log2FC": 1},
        {"Gene.Name": "AKT1", "PTM_Position": "S2", "Condition": "5min", "PTM_Relative_Log2FC": -1},
        {"Gene.Name": "LOSS", "PTM_Position": "S1", "Condition": "5min", "PTM_Relative_Log2FC": np.nan},
        {"Gene.Name": "NEW", "PTM_Position": "S1", "Condition": "5min", "PTM_Relative_Log2FC": 99, "Conventional_Log2FC_NA": True},
        {"Gene.Name": "TIMED", "PTM_Position": "S1", "Condition": "5min", "PTM_Relative_Log2FC": 1},
    ])
    secondary = pd.DataFrame([
        {"Gene.Name": gene, "PTM_Position": "K1", "Condition": "15min" if gene == "TIMED" else "5min", "PTM_Relative_Log2FC": 2}
        for gene in ("AKT1", "LOSS", "NEW", "TIMED")])
    secondary.to_csv(tmp_path / "secondary.tsv", sep="\t", index=False)
    outputs = []
    for rows in (primary, primary.iloc[::-1]):
        rows.to_csv(tmp_path / "primary.tsv", sep="\t", index=False)
        output = build_crosstalk_data({}, "phosphorylation", "", {}, "ubiquitylation", "",
            str(tmp_path / "primary.tsv"), str(tmp_path / "secondary.tsv"))
        outputs.append(output)
        assert len(output["source_inventory"]["primary"]) == 5
        assert not output["concordant_pairs"] and not output["discordant_pairs"]
        assert len(output["sequential_gating"]) == 1
        ordering = output["sequential_gating"][0]
        assert ordering["gene"] == "TIMED" and ordering["time_lag_minutes"] == 10
        assert ordering["causal_status"] == "not_evaluated"
        assert "Mechanism unknown" in ordering["mechanism_hint"]
        assert output["ptm_protein_timelags"] == []
    assert outputs[0]["dual_ptm_proteins"] == outputs[1]["dual_ptm_proteins"]


def test_rev02_stale_explicit_enrichment_never_falls_back_to_newest_file(tmp_path):
    from report_generation.tasks import _resolve_enriched_json_path
    other = tmp_path / "enriched_ptm_data_phospho.json"
    other.write_text("[]")
    with pytest.raises(FileNotFoundError, match="explicit enriched_json_path"):
        _resolve_enriched_json_path(7, tmp_path, str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        _resolve_enriched_json_path(7, tmp_path, None)
    assert _resolve_enriched_json_path(7, tmp_path, str(other)) == str(other.resolve())


def test_dag01_required_unevaluable_module_prevents_final_ready():
    from report_generation.core.reader_authoring import audit_report_output_correctness
    from report_generation.core.report_release import resolve_report_release
    audit = audit_report_output_correctness("", required_module_status={"cross_talk": "not_evaluable"})
    assert audit["incomplete_required_modules"] == ["cross_talk"]
    assert "required_module_analysis_incomplete" in audit["review_reason_codes"]
    release = resolve_report_release(reader_authoring_shadow=True, output_correctness={
        "status": "release_candidate", "review_reason_codes": ["required_module_analysis_incomplete"]},
        artifact_manifest={"status": "validated", "report_eligible": True}, phase="pre_export")
    assert release["status"] == "draft_review_required"
    assert release["publish_as_final"] is False


def test_rag_quality_gate_uses_claim_scope_not_a_twenty_reference_minimum():
    from report_generation.core.reader_authoring import audit_report_output_correctness
    audit = audit_report_output_correctness("", reader_cards=[
        {"citation_ids": [f"pmid:{number}"]} for number in range(10000, 10030)])
    assert audit["literature_coverage"]["distinct_references"] == 30
    assert not audit["literature_coverage"]["count_is_quality_gate"]
    assert "literature_coverage_below_product_target" not in audit["review_reason_codes"]


def test_motif01_legacy_unified_consumer_uses_modified_residue_and_versioned_cache(tmp_path):
    from preprocessing.core.unified_enricher import UnifiedProteinEnricher
    enricher = UnifiedProteinEnricher(str(tmp_path / "unused.fasta"), str(tmp_path), str(tmp_path))
    enricher.fasta_dict = {"P1": "RRSTA"}
    # The PKA motif ends at T4, while S3 lies inside the same regex match.
    assert "PKA_motif" not in enricher.analyze_motif_patterns("P1", "RRS(UniMod:21)TA", "S3")["motifs"]
    assert "PKA_motif" in enricher.analyze_motif_patterns("P1", "RRST(UniMod:21)A", "T4")["motifs"]
    old_key = enricher._motif_cache_key("P1", "RRST(UniMod:21)A", "T4")
    enricher.fasta_dict["P1"] = "AASTA"
    assert old_key != enricher._motif_cache_key("P1", "RRST(UniMod:21)A", "T4")
    assert not enricher.analyze_motif_patterns("P1;P2", "RRST(UniMod:21)A", "T4")["motifs"]


def test_obs03_duplicate_fasta_accession_retains_all_reference_candidates(tmp_path):
    analyzer = analyzer_for([10, 12, 20], [100, 100, 100])
    analyzer.protein_names = {}
    analyzer.gene_names = {}
    records = [">sp|P1|A GN=ONE\nMASK\n", ">sp|P1|A GN=TWO\nAASK\n"]
    mappings = []
    for index, source in enumerate((records, records[::-1])):
        path = tmp_path / f"refs{index}.fasta"
        path.write_text("".join(source))
        analyzer.fasta_path = str(path)
        assert analyzer.load_fasta()
        mapping = analyzer._mapping_assertion("P1", "AS(UniMod:21)K", "Phosphorylation")
        assert mapping["status"] == "ambiguous"
        assert len(mapping["reference_sequence_conflicts"]["P1"]) == 2
        assert len(mapping["candidates"]) == 2
        assert analyzer.gene_names["P1"] == "Unknown"
        mappings.append(mapping)
    assert mappings[0] == mappings[1]


@pytest.mark.parametrize("status, expected", [(429, "rate_limited"), (500, "api_error"), (200, "parse_failure"), (404, "no_hit")])
def test_ref01_interpro_errors_never_become_permanent_success_cache(monkeypatch, status, expected):
    import asyncio
    import httpx
    from unittest.mock import AsyncMock
    module = _source_module("interpro")
    client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"wrong": "schema"}))))
    redis = type("Cache", (), {"get": AsyncMock(return_value=None), "set": AsyncMock()})()
    result = asyncio.run(module.query_interpro("P1", redis=redis, max_retries=1))
    assert result["query_status"] == result["source_record"]["status"] == expected
    assert redis.set.call_count == (1 if expected == "no_hit" else 0)
    if expected == "no_hit":
        assert redis.set.call_args.kwargs["ex"] == 3600


def test_ref01_interpro_display_cap_keeps_full_source_through_enricher(monkeypatch, tmp_path):
    import asyncio
    import httpx
    from preprocessing.core.unified_enricher import UnifiedProteinEnricher
    module = _source_module("interpro")
    records = [{"metadata": {"accession": f"IPR{i}", "name": "Same name", "type": "domain"},
                "proteins": [{"entry_protein_locations": [{"fragments": [{"start": i, "end": i + 2}]}]}]}
               for i in range(7)]
    client = httpx.AsyncClient
    def respond(request):
        second = "page=2" in str(request.url)
        return httpx.Response(200, json={"results": records[4:] if second else records[:4],
            "next": None if second else "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P1?page=2"})
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond)))
    response = asyncio.run(module.query_interpro("P1"))
    assert len(response["domains"]) == 5
    assert len(response["full_domains"]) == 7
    assert len(response["source_pages"]) == 2
    assert response["retrieval_complete"]
    class MCP:
        def fetch_interpro_parallel(self, *args, **kwargs):
            return {"P1": response}
    enricher = UnifiedProteinEnricher("unused.fasta", str(tmp_path), str(tmp_path), mcp_client=MCP())
    assert len(enricher.fetch_domains_via_mcp(["P1"])["P1"]) == 7
    assert enricher.domain_source_records["P1"]["source_record"]["payload_sha256"]


def test_llm01_cross_ptm_module_resolves_values_without_inlining_raw_inventory():
    from report_generation.core.reader_authoring import build_authoring_packet
    from report_generation.core.section_model_packet import build_section_model_packet
    from test_task10_findings import finding_state
    state = finding_state(1)
    state["analysis_mode"] = "cross_talk"
    state["cross_talk_data"] = {"evaluation_status": "computed", "primary_ptm_type": "phosphorylation",
        "secondary_ptm_type": "ubiquitylation", "source_inventory": {"raw_secret_marker": "raw row"},
        "dual_ptm_proteins": [{"gene": "AKT1", "pattern": "discordant", "primary_sites": ["S1"], "secondary_sites": ["K2"],
            "temporal_comparison": {"5min": {"primary_ptm_log2fc": 1, "secondary_ptm_log2fc": -2}}}]}
    audit = build_authoring_packet(state)
    packet = build_section_model_packet(audit, None, "results", compaction_stage=3)
    assert "raw_secret_marker" not in json.dumps(packet)
    cards = [c for c in packet["reader_cards"] if c.get("feature_label") == "AKT1"]
    values = [record for card in cards for record in card.get("value_records") or []]
    assert sorted(record["value"] for record in values) == [-2, 1]
    assert {record["axis"] for record in values} == {"protein_adjusted"}
    assert all(record["source"]["sites"] for record in values)


def test_review01_full_section_and_bound_evidence_survive_review_budget():
    from report_generation.core.nodes.report_copilot_node import _review_bound_sections, review_issue_ledger
    from report_generation.core.reader_authoring import build_authoring_packet
    from test_task10_findings import finding_state
    state = finding_state(1)
    state["authoring_packet"] = build_authoring_packet(state)
    state["sections"] = {"results": "Observed scope. " * 420 + "ESSENTIAL_FINAL_LIMITATION", "discussion": "A second section."}
    state["report_config"] = {"review_policy": {"max_model_calls": 1, "context_tokens": 100000}}
    calls = []
    class Model:
        def generate(self, **kwargs):
            calls.append(kwargs["prompt"])
            return json.dumps({"overall_quality": "good", "section_reviews": []})
    review = _review_bound_sections(state, Model())
    assert len(calls) == 1
    assert "ESSENTIAL_FINAL_LIMITATION" in calls[0]
    assert "evidence_packet" in calls[0]
    assert review["review_trace"]["section_status"]["discussion"] == "review_model_budget_exhausted"
    assert review_issue_ledger(review)[0]["state"] == "unresolved_with_reason"


def test_review01_resolution_requires_an_executed_specific_rule():
    from report_generation.core.nodes.report_copilot_node import review_issue_ledger
    review = {"section_reviews": [{"section": "Results", "severity": "high", "description": "Wrong value",
        "verification_rule": "no_unbound_quantitative_claims"}], "overall_quality": "good"}
    assert review_issue_ledger(review)[0]["state"] != "verified_resolved"
    review["repair_attempt"] = {"verified_rules_by_section": {"results": {"no_unbound_quantitative_claims": True}}}
    assert review_issue_ledger(review)[0]["state"] == "verified_resolved"


def test_det02_requested_drug_module_retains_missing_rows_without_ranking_sentinel():
    from report_generation.core.nodes.drug_repositioning_node import _build_analysis_results
    result = _build_analysis_results([
        {"gene": "LOSS", "ptm_relative_log2fc": None},
        {"gene": "ONSET", "ptm_relative_log2fc": 99, "Conventional_Log2FC_NA": True},
        {"gene": "OBS", "ptm_relative_log2fc": -1}], {}, {})
    assert len(result["input_inventory"]) == 3
    assert [node["gene"] for node in result["networks"]["combined"]["nodes"]] == ["OBS"]
    assert result["summary"]["negative_magnitude_count"] == 1
    assert "significant_down" not in result["summary"]
