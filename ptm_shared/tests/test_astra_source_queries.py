from io import BytesIO
from unittest.mock import patch
import urllib.error

from ptm_shared.astra_discovery import _blank
from ptm_shared.astra_inputs import stable_id
from ptm_shared.astra_sources import (
    STRING_IDENTIFIER_BATCH, PROVIDER_BUDGETS, SourceClient, accession_query_order,
    iptmnet_entry_absent, resolve_sources, retain_unreplaced_prior_successes,
)


def test_missing_gene_is_blank_and_does_not_enter_the_stable_id():
    assert _blank(float('nan')) == ''
    assert _blank(None) == ''
    assert _blank('Insr') == 'Insr'
    gene = _blank(float('nan')) or ''
    site = 'Q63010:S100'
    assert stable_id('shared_site', ['unresolved', site] if not gene else [gene, 'ACDEFGHIKLMNPQR'])


def test_provider_budgets_are_separate_and_a_reactome_404_stays_no_hit(tmp_path):
    assert PROVIDER_BUDGETS['STRING']['requests'] >= 49
    assert PROVIDER_BUDGETS['Reactome']['requests'] == 3
    assert PROVIDER_BUDGETS['PubMed']['requests'] == 1
    mapping = [
        {'mapped_accession': 'A0A096MIS3', 'fasta_taxonomy_id': '10116', 'fasta_gene': 'Trembl'},
        {'mapped_accession': 'P06213', 'fasta_taxonomy_id': '9606', 'fasta_gene': 'INSR'},
    ]
    snapshot = 'enzyme\tsubstrate\tresidue_type\tresidue_offset\tmodification\tsources\treferences\nKIN\tP06213\tY\t1185\tphosphorylation\tSIGNOR\t12345678\n'
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, n):
            return self.body

    def open_request(req, timeout=0):
        calls.append(req.full_url)
        if 'omnipathdb.org' in req.full_url:
            return Response(snapshot.encode())
        if 'string-db.org' in req.full_url:
            return Response(b'[]')
        if 'reactome.org' in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, 'missing', hdrs=None, fp=BytesIO(b''))
        if 'eutils.ncbi.nlm.nih.gov' in req.full_url:
            return Response(b'{"result":{"uids":["12345678"],"12345678":{"title":"t","authors":[],"pubdate":"2020","articleids":[]}}}')
        if 'iptmnet' in req.full_url:
            return Response(b'<html>iPTMnet Report for X Not found.</html>')
        raise AssertionError(req.full_url)

    with patch.dict('ptm_shared.astra_sources.PROVIDER_BUDGETS', {'iPTMnet': {'seconds': 90, 'requests': 0}}, clear=False):
        with patch('urllib.request.urlopen', side_effect=open_request):
            sources = resolve_sources(tmp_path, mapping, [], 'phosphorylation', fixtures=None, prior_pins=[{
                'queries': [{'query_id': 'prior-string', 'provider': 'STRING', 'status': 'hit', 'query': {'accessions': ['Q9Z0W4'], 'taxon': '10116'}}],
                'context': [{'provider': 'STRING', 'query_id': 'prior-string', 'record': {'preferredName_A': 'INSR'}}],
                'bibliography': [], 'relations': [],
            }])
    assert not any('iptmnet' in url for url in calls)
    assert sum('string-db.org' in url for url in calls) == 2
    reactome = [q for q in sources['queries'] if q['provider'] == 'Reactome' and q.get('query', {}).get('accession')]
    assert [q['status'] for q in reactome] == ['no_hit', 'no_hit']
    assert all(q['reason'] == 'identifier_absent_HTTP_404' and q['payload'] == [] for q in reactome)
    assert any(q['provider'] == 'PubMed' and q['status'] == 'hit' for q in sources['queries'])
    retained = [q for q in sources['queries'] if q.get('query_id') == 'prior-string']
    assert retained and retained[0]['retained_from_prior_pin'] is True
    string = [q for q in sources['queries'] if q['provider'] == 'STRING' and q.get('query', {}).get('transport') == 'post_form']
    assert all(q['network_scope'] == 'within_posted_identifiers_only' and q['cross_batch_edges'] == 'not_requested' for q in string)


def test_a_string_timeout_keeps_later_batches_in_the_same_taxon(tmp_path):
    mapping = [
        {'mapped_accession': 'P00001', 'fasta_taxonomy_id': '10116', 'fasta_gene': 'A'},
        {'mapped_accession': 'P00002', 'fasta_taxonomy_id': '10116', 'fasta_gene': 'B'},
        {'mapped_accession': 'P00003', 'fasta_taxonomy_id': '10116', 'fasta_gene': 'C'},
    ]
    snapshot = 'enzyme\tsubstrate\tresidue_type\tresidue_offset\tmodification\tsources\treferences\n'
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, n):
            return self.body

    def open_request(req, timeout=0):
        if 'string-db.org' in req.full_url:
            calls.append(req.full_url)
            if len(calls) == 2:
                raise TimeoutError('slow')
            return Response(b'[]')
        if 'omnipathdb.org' in req.full_url:
            return Response(snapshot.encode())
        if 'reactome.org' in req.full_url:
            return Response(b'[]')
        if 'iptmnet' in req.full_url:
            return Response(b'<html>iPTMnet Report for X Not found.</html>')
        raise AssertionError(req.full_url)

    with patch('ptm_shared.astra_sources.STRING_IDENTIFIER_BATCH', 1):
        with patch('urllib.request.urlopen', side_effect=open_request):
            sources = resolve_sources(tmp_path, mapping, [], 'phosphorylation', fixtures=None)
    posted = [q for q in sources['queries'] if q['provider'] == 'STRING' and q.get('query', {}).get('transport') == 'post_form']
    assert [q['status'] for q in posted] == ['no_hit', 'timeout', 'no_hit']
    assert [q['query']['accessions'] for q in posted] == [['P00001'], ['P00002'], ['P00003']]
    assert not any(q['provider'] == 'STRING' and q['status'] == 'not_run_budget' for q in sources['queries'])


def test_a_replaced_prior_string_batch_is_not_duplicated():
    result = {'queries': [{'query_id': 'new', 'provider': 'STRING', 'status': 'hit', 'query': {'accessions': ['P06213']}}],
              'context': [], 'relations': [], 'bibliography': []}
    prior = {'queries': [{'query_id': 'old', 'provider': 'STRING', 'status': 'hit', 'query': {'accessions': ['P06213']}}],
             'context': [{'query_id': 'old', 'record': {}}], 'bibliography': [], 'relations': []}
    retain_unreplaced_prior_successes([prior], result)
    assert [q['query_id'] for q in result['queries']] == ['new']


def test_provider_calls_prefer_human_and_curated_substrates_over_alphabetical_trembl():
    rows = {
        'A0A096MIS3': {'mapped_accession': 'A0A096MIS3', 'fasta_taxonomy_id': '10116'},
        'P06213': {'mapped_accession': 'P06213', 'fasta_taxonomy_id': '9606'},
        'P12345': {'mapped_accession': 'P12345', 'fasta_taxonomy_id': '10116'},
        'Q1': {'mapped_accession': 'Q1', 'fasta_taxonomy_id': '10116'},
    }
    assert accession_query_order(rows, {'A0A096MIS3'}) == ['P06213', 'A0A096MIS3', 'P12345', 'Q1']


def test_iptmnet_not_found_page_is_distinguished_from_a_real_entry():
    absent = '<html><title>iPTMnet Report A0A096MIS3</title>iPTMnet Report for A0A096MIS3 Not found.</html>'
    present = '<html>Organism Rattus norvegicus (Rat) Phosphorylation</html>'
    assert iptmnet_entry_absent(absent)
    assert not iptmnet_entry_absent(present)


def test_reactome_404_is_an_absent_identifier_and_520_stays_unavailable(tmp_path):
    client = SourceClient(tmp_path, fixtures=None)

    def raise_status(code):
        def _open(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, 'status', hdrs=None, fp=BytesIO(b''))
        return _open

    with patch('urllib.request.urlopen', side_effect=raise_status(404)):
        missing = client.query('Reactome', {'accession': 'A0A096MIS3'}, 'https://reactome.example/a', empty_http_codes={404})
    assert missing['status'] == 'no_hit' and missing['reason'] == 'identifier_absent_HTTP_404'
    with patch('urllib.request.urlopen', side_effect=raise_status(520)):
        down = client.query('STRING', {'taxon': '10116'}, 'https://string.example/network', form='identifiers=P06213&species=9606')
    assert down['status'] == 'access_unavailable' and down['reason'] == 'HTTP_520'
    assert 'parsed_rows' not in down


def test_string_request_is_a_bounded_post_and_human_accession_is_asked_first(tmp_path):
    root = tmp_path / 'reference'
    (root / 'frozen_annotations').mkdir(parents=True)
    snapshot = 'enzyme\tsubstrate\tresidue_type\tresidue_offset\tmodification\tsources\treferences\nKIN\tP06213\tY\t1185\tphosphorylation\tSIGNOR\t12345678\n'
    absent = '<html>iPTMnet Report for ACC Not found.</html>'
    mapping = [
        {'mapped_accession': 'A0A096MIS3', 'fasta_taxonomy_id': '10116', 'fasta_gene': 'Trembl'},
        {'mapped_accession': 'P06213', 'fasta_taxonomy_id': '9606', 'fasta_gene': 'INSR'},
    ]
    captured = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, n): return b'[{"preferredName_A":"INSR","preferredName_B":"IRS1"}]'

    def open_request(req, timeout=0):
        captured.append((req.full_url, req.data, req.get_header('Content-type')))
        return Response()

    client = SourceClient(root, fixtures=None, budget_seconds=30, max_requests=4)
    with patch('urllib.request.urlopen', side_effect=open_request):
        rec = client.query('STRING', {'accessions': ['P06213'], 'taxon': '9606', 'transport': 'post_form'},
            'https://string-db.org/api/json/network', form='identifiers=P06213&species=9606')
    assert rec['status'] == 'hit'
    assert captured[0][0] == 'https://string-db.org/api/json/network'
    assert captured[0][1] == b'identifiers=P06213&species=9606'
    assert captured[0][2] == 'application/x-www-form-urlencoded'

    fixtures = {'OmniPath': {'raw': snapshot}, 'iPTMnet': {'raw': absent}, 'STRING': {'payload': []}}
    with patch('urllib.request.urlopen', side_effect=open_request):
        sources = resolve_sources(root, mapping, [], 'phosphorylation', fixtures=fixtures)
    iptm = [q for q in sources['queries'] if q['provider'] == 'iPTMnet' and q.get('query', {}).get('accession')]
    reactome = [q for q in sources['queries'] if q['provider'] == 'Reactome' and q.get('query', {}).get('accession')]
    string = [q for q in sources['queries'] if q['provider'] == 'STRING' and q.get('query', {}).get('transport') == 'post_form']
    assert iptm[0]['query']['accession'] == 'P06213'
    assert {q['status'] for q in iptm} == {'no_hit'}
    assert reactome[0]['query']['accession'] == 'P06213'
    by_tax = {q['query']['taxon']: q['query']['accessions'] for q in string}
    assert by_tax['9606'] == ['P06213']
    assert by_tax['10116'] == ['A0A096MIS3']
    assert all(q['endpoint'] == 'https://string-db.org/api/json/network' and 'identifiers=' not in q['endpoint'] for q in string)
    kea = next(q for q in sources['queries'] if q['provider'] == 'KEA3')
    assert kea['status'] == 'not_supported'
    assert kea['query']['native_human_genes'] == ['INSR']
