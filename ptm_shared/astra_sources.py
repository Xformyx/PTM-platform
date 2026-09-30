"""Bounded, content-addressed source acquisition; valid empty != unavailable.

Raw responses and parsed records are pinned together. Replay never calls this
network client. Failed requests are not negative-cached.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import re
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

import pandas as pd

from .annotation_registry import public_registry, require_compatible
from .astra_inputs import stable_id
from .kea3_evidence import parse_kea3, mapped_human_genes

VERSION = 'astra_sources.v1.4'
PARSER_VERSION = 'typed_provider_parsers.v1'
SUCCESS = {'hit', 'no_hit'}
STRING_IDENTIFIER_BATCH = 100
"""STRING network POST에 넣는 identifier 수.

docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산»에서
2026-09-30 선언. run g4-06669a45084949bca50a20ebe097190c의 rat GET
(URL 55,549자, HTTP 520)을 본 뒤이며 탐색적이다. primary 귀속에 쓰지 않는다.
한 요청의 상한일 뿐 그 배치의 상호작용이 관찰됐다는 뜻이 아니다.
STRING 문맥으로 site-resolved kinase 귀속을 주장하지 않는다.
"""
REACTOME_ACCESSION_BUDGET = 3
"""한 run에서 Reactome에 묻는 고유 accession 수.

docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산».
2026-09-30. 순서는 accession_query_order. 이름순 첫 3개가 아니다.
탐색적. 이 상한으로 pathway 완전성을 주장하지 않는다.
"""
STRING_CONTEXT_RESERVE = 4
"""이전 공유 시계에서 Reactome·PubMed에 남기던 요청 수.

2026-09-30 g7 이후 공급원별 예산으로 대체했다. 호출 상한으로 쓰지 않는다.
탐색적. 이 상수가 남아 있다고 공유 시계가 아직 쓰인다는 뜻이 아니다.
"""
PROVIDER_BUDGETS = {
    'OmniPath': {'seconds': 60, 'requests': 4},
    'iPTMnet': {'seconds': 90, 'requests': 20},
    'STRING': {'seconds': 240, 'requests': 60},
    'Reactome': {'seconds': 45, 'requests': 3},
    'PubMed': {'seconds': 45, 'requests': 1},
    'KEA3': {'seconds': 30, 'requests': 1},
}
"""공급원마다 따로 가는 시계와 요청 수.

docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산».
2026-09-30 run g7을 본 뒤. 탐색적. primary 승격 금지.
해석 한계: 한 공급원의 소요는 다른 공급원 예산을 줄이지 않는다.
4,749개 accession의 STRING 배치를 담되 iPTMnet 전체 페이지를 담지 않는다.
주장 금지: 이 예산으로 site-resolved kinase edge가 늘었다고 말하지 않는다.
STRING 배치 성공을 전체 단백질 network 조회로 말하지 않는다.
"""
STRING_NETWORK_SCOPE = 'within_posted_identifiers_only'
STRING_CROSS_BATCH = 'not_requested'


def string_batch_failure_continues(status):
    """One finished STRING batch failure does not cancel later batches of that taxon.

    구현 대상: docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산»
    사전등록: 2026-09-30. run g8-71a26a7a0ac34f3e97350dc72d4d5bf4에서
    TimeoutError 한 배치 뒤 rat accession 3548개가 미실행으로 남은 것을 본 뒤. 탐색적.
    해석 한계: 실패한 배치는 timeout 등으로 남는다. 다음 배치 호출이 그 실패를 메우지 않는다.
    주장 금지: 이후 배치를 호출했다고 전체 단백질 network나 kinase edge를 말하지 않는다.
    """
    return status != 'not_run_budget'


def _write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '-' + uuid4().hex)
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
    tmp.replace(path)


class SourceClient:
    def __init__(self, root, fixtures=None, budget_seconds=None, max_requests=None, checkpoint=lambda: None, refresh=False):
        self.refresh=refresh
        self.root = Path(root); self.fixtures = fixtures
        self.checkpoint = checkpoint
        self.requests = 0; self.records = []
        self.provider_started = {}; self.provider_requests = {}
        # Explicit overrides exist for tests. Production uses PROVIDER_BUDGETS.
        self.budget_override = None if budget_seconds is None and max_requests is None else {'seconds': budget_seconds if budget_seconds is not None else 45, 'requests': max_requests if max_requests is not None else 24}

    def _spec(self, provider):
        if self.budget_override is not None:
            return self.budget_override
        return PROVIDER_BUDGETS.get(provider, {'seconds': 30, 'requests': 1})

    def within_budget(self, provider):
        spec = self._spec(provider)
        started = self.provider_started.setdefault(provider, time.monotonic())
        return self.provider_requests.get(provider, 0) < spec['requests'] and time.monotonic() < started + spec['seconds']

    def query(self, provider, query, url, *, body=None, form=None, parser='json', license_scope='public_endpoint_terms', empty_http_codes=()):
        self.checkpoint()
        key = stable_id('query', [provider, PARSER_VERSION, license_scope, query, url, body, form])
        cache = self.root / 'source_cache' / (key + '.json')
        base = {'query_id': key, 'provider': provider, 'provider_version': 'response_content_addressed',
                'parser_version': PARSER_VERSION, 'query': query, 'endpoint': url,
                'license_scope': license_scope, 'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                'status': None, 'cache_hit': False, 'response_sha256': None, 'payload': None,
                'original_resources': [], 'reason': None}
        if cache.exists():
            candidate = json.loads(cache.read_text())
            if candidate['status'] in SUCCESS and time.time() - cache.stat().st_mtime < 7 * 86400:
                raw = candidate.get('raw_response', '').encode()
                if hashlib.sha256(raw).hexdigest() == candidate.get('response_sha256'):
                    base = {**candidate, 'cache_hit': True}; self.records.append(base); return base
        fixture = (self.fixtures or {}).get(key, (self.fixtures or {}).get(provider))
        if self.fixtures is not None and fixture is None:
            base.update(status='access_unavailable', reason='fixture_provider_not_supplied')
        elif not self.within_budget(provider):
            base.update(status='not_run_budget', reason='provider_budget_exhausted')
        else:
            self.requests += 1
            self.provider_requests[provider] = self.provider_requests.get(provider, 0) + 1
            try:
                if fixture is not None:
                    if fixture.get('status') not in (None, 'hit', 'no_hit'):
                        base.update(status=fixture['status'], reason=fixture.get('reason', 'frozen_response_fixture'))
                        self.records.append(base); return base
                    raw = fixture.get('raw', json.dumps(fixture.get('payload', {}), ensure_ascii=False))
                else:
                    headers = {'User-Agent': 'PTM-Platform-Astra/4', 'Accept': 'application/json,text/tab-separated-values,text/html'}
                    if form is not None:
                        data = form.encode() if isinstance(form, str) else urllib.parse.urlencode(form).encode()
                        headers['Content-Type'] = 'application/x-www-form-urlencoded'
                    elif body is not None:
                        data = json.dumps(body).encode()
                        headers['Content-Type'] = 'application/json'
                    else:
                        data = None
                    req = urllib.request.Request(url, data=data, headers=headers)
                    # One retry with bounded backoff. Never turn HTTP failures into an empty answer.
                    for attempt in range(2):
                        try:
                            with urllib.request.urlopen(req, timeout=max(.1, min(10, self._spec(provider)['seconds']))) as response:
                                raw = response.read(64 * 1024 * 1024 + 1)
                                if len(raw) > 64 * 1024 * 1024: raise ValueError('response_size_limit')
                                raw = raw.decode('utf-8'); break
                        except urllib.error.HTTPError as error:
                            if attempt == 0 and error.code in {429, 502, 503} and self.within_budget(provider):
                                time.sleep(.25); continue
                            raise
                base['raw_response'] = raw; base['response_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
                payload = json.loads(raw) if parser == 'json' else raw
                base.update(payload=payload, status='hit' if payload else 'no_hit')
            except urllib.error.HTTPError as error:
                if error.code in set(empty_http_codes):
                    # A completed 404 is an empty identifier answer, not a transport failure.
                    base.update(status='no_hit', reason=f'identifier_absent_HTTP_{error.code}',
                                raw_response='', response_sha256=hashlib.sha256(b'').hexdigest(), payload=[])
                    self.accept(base, [])
                else:
                    base.update(status='rate_limited' if error.code == 429 else 'access_unavailable', reason=f'HTTP_{error.code}')
            except (TimeoutError, urllib.error.URLError) as error:
                base.update(status='timeout' if isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError) else 'access_unavailable', reason=type(error).__name__)
            except (ValueError, UnicodeError) as error:
                base.update(status='parse_failure', reason=str(error))
        self.records.append(base)
        return base  # Cache only after provider-specific schema validation.

    def accept(self, record, rows):
        record['status'] = 'hit' if rows else 'no_hit'
        record['parsed_rows'] = rows
        _write_atomic(self.root/'source_cache'/(record['query_id']+'.json'), record)


def _iptm_parser():
    path = Path(__file__).resolve().parents[1]/'mcp-server/app/tools/iptmnet.py'
    spec = importlib.util.spec_from_file_location('astra_iptmnet_client', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def accession_query_order(by_accession, substrates):
    """Order observed accessions for the bounded provider calls.

    구현 대상: docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산»
    사전등록: 2026-09-30. run g4-06669a45084949bca50a20ebe097190c을 본 뒤. 탐색적.
    해석 한계: 사람 taxon, 이번 OmniPath substrate, 비-A0A, 나머지 순이다.
    인슐린 경로의 생물학적 순위가 아니다.
    주장 금지: 이 순서로 kinase 귀속 정확도가 올랐다고 말하지 않는다.
    """
    substrates = set(substrates or ())

    def key(accession):
        row = by_accession[accession]
        tax = str(row.get('fasta_taxonomy_id') or '')
        if tax == '9606': tier = 0
        elif accession in substrates: tier = 1
        elif not str(accession).startswith('A0A'): tier = 2
        else: tier = 3
        return (tier, str(accession))

    return sorted(by_accession, key=key)


def iptmnet_entry_absent(html):
    """True when the entry page says that accession is not in iPTMnet.

    구현 대상: docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산»
    사전등록: 2026-09-30. 탐색적. 종 문자열이 없는 Not found 페이지를
    entry_taxonomy_unverified_or_mismatched로 적지 않기 위한 구분이다.
    해석 한계: 항목이 없다는 응답이며 인산화가 없다는 증거가 아니다.
    주장 금지: 이 구분으로 kinase 귀속을 넓히거나 좁혔다고 말하지 않는다.
    """
    text = ' '.join(re.sub(r'<[^>]+>', ' ', html or '').split())
    return re.search(r'iPTMnet Report for \S+ Not found\.', text) is not None


def _defer(client, provider, reason, query):
    client.records.append({'query_id': stable_id('query', [provider, reason, query]), 'provider': provider,
        'status': 'not_run_budget', 'query': query, 'reason': reason, 'cache_hit': False})


def _query_accessions(record):
    query = record.get('query') if isinstance(record, dict) else None
    if not isinstance(query, dict):
        return set()
    if isinstance(query.get('accessions'), list):
        return {str(item) for item in query['accessions']}
    if query.get('accession'):
        return {str(query['accession'])}
    return set()


def retain_unreplaced_prior_successes(priors, result):
    """Copy successful provider records that this run did not replace.

    구현 대상: docs/collaboration/astra_package_operations_KO.md «Provider 조회 예산»
    사전등록: 2026-09-30. run g7이 g4의 human STRING과 PubMed를 뺀 뒤. 탐색적.
    해석 한계: 이전 pin의 성공 조회를 새 pin에 남기는 것이다. 새 실험 결과가 아니다.
    주장 금지: 보존된 STRING 배치를 전체 network나 kinase edge로 말하지 않는다.
    """
    current = {record.get('query_id') for record in result['queries']}
    covered = set()
    for record in result['queries']:
        if record.get('provider') == 'STRING' and record.get('status') in SUCCESS:
            covered |= _query_accessions(record)
    pubmed_done = any(record.get('provider') == 'PubMed' and record.get('status') in SUCCESS for record in result['queries'])
    for prior in priors or []:
        for record in prior.get('queries') or []:
            if record.get('status') not in SUCCESS or record.get('query_id') in current:
                continue
            if record.get('provider') not in {'STRING', 'Reactome', 'PubMed', 'iPTMnet'}:
                continue
            accessions = _query_accessions(record)
            if record.get('provider') == 'STRING' and accessions and accessions <= covered:
                continue
            if record.get('provider') == 'PubMed' and pubmed_done:
                continue
            copied = {**record, 'cache_hit': True, 'retained_from_prior_pin': True}
            result['queries'].append(copied)
            current.add(record.get('query_id'))
            query_id = record.get('query_id')
            if record.get('provider') in {'STRING', 'Reactome'}:
                result['context'].extend(item for item in prior.get('context') or [] if item.get('query_id') == query_id)
                if record.get('provider') == 'STRING':
                    covered |= accessions
            elif record.get('provider') == 'iPTMnet':
                result['relations'].extend(item for item in prior.get('relations') or [] if item.get('query_id') == query_id)
            elif record.get('provider') == 'PubMed' and not result.get('bibliography'):
                result['bibliography'] = [item for item in prior.get('bibliography') or [] if item.get('query_id') == query_id] or list(prior.get('bibliography') or [])
                pubmed_done = True


def resolve_sources(root, mapping, fasta_genes, ptm_type, *, pin_sha=None, refresh=False, fixtures=None, checkpoint=lambda: None, budget_seconds=None, max_requests=None, prior_pins=None):
    root = Path(root)
    if pin_sha and not refresh:
        path = root/'source_pins'/(pin_sha+'.json')
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == pin_sha:
            return {**json.loads(path.read_text()), 'pin_sha256': pin_sha}
        raise ValueError('Pinned source bytes missing/corrupt; do not silently refresh an immutable source pin')
    client = SourceClient(root, fixtures, budget_seconds=budget_seconds, max_requests=max_requests, checkpoint=checkpoint, refresh=refresh)
    result = {'schema_version': VERSION, 'queries': client.records, 'snapshots': [], 'relations': [], 'kea': [], 'context': [], 'bibliography': []}
    if ptm_type not in {'phosphorylation', 'phospho'}:
        result['status'] = 'not_applicable_nonphosphorylation'; return pin_sources(root, result)
    taxa = sorted({str(r['fasta_taxonomy_id']) for r in mapping if r.get('fasta_taxonomy_id')})
    for tax in taxa:
        checkpoint(); registered = None
        if not refresh:
            for item in public_registry(root/'frozen_annotations', tax, 'phosphorylation')['snapshots']:
                if item.get('status') == 'ready':
                    candidate = require_compatible(root/'frozen_annotations', item['sha256'], tax, 'phosphorylation')
                    observed={r['mapped_accession'] for r in mapping if str(r.get('fasta_taxonomy_id'))==tax}
                    available=set(pd.read_csv(candidate['snapshot_path'],sep='\t',usecols=['substrate']).substrate)
                    if available & observed:
                        registered=candidate;break
        if registered:
            data = Path(registered['snapshot_path']).read_text()
            record = {'query_id': stable_id('query', ['registered', registered['sha256'], tax]), 'provider': 'OmniPath_registered',
                      'status': 'hit', 'query': {'taxon': tax}, 'retrieved_utc': registered['retrieved_utc'],
                      'response_sha256': registered['sha256'], 'cache_hit': True, 'license_scope': 'registered_snapshot_terms',
                      'endpoint': None, 'parser_version': PARSER_VERSION, 'raw_response': data,
                      'original_resources': [], 'payload': data}
            client.records.append(record)
        else:
            url = 'https://omnipathdb.org/enzsub?' + urllib.parse.urlencode({'organisms': tax, 'format': 'tsv', 'genesymbols': '1', 'fields':'sources,references', 'license': 'commercial'})
            record = client.query('OmniPath', {'taxon': tax, 'ptm': ptm_type}, url, parser='text', license_scope='commercial_filter_no_license_bypass')
            data = record.get('payload')
        if record['status'] in SUCCESS:
            try:
                table = pd.read_csv(io.StringIO(data), sep='\t', dtype=str).fillna('')
                required = {'enzyme','substrate','residue_type','residue_offset','modification','sources','references'}
                if not required <= set(table): raise ValueError('enzsub_required_columns_absent')
                table['residue_offset'] = pd.to_numeric(table.residue_offset, errors='raise').astype(int)
                if (table.residue_offset < 1).any(): raise ValueError('invalid_site_coordinate')
                meta = (registered or {}).get('metadata') or {'taxonomy_ids':[tax], 'orthology_translation': tax!='9606', 'source_taxonomy_ids':['9606']}
                aliases = dict(meta.get('accession_aliases', {}))
                if 'enzyme_genesymbol' in table:
                    aliases.update({r.enzyme: r.enzyme_genesymbol for r in table.itertuples() if r.enzyme_genesymbol})
                meta['accession_aliases'] = aliases
                audits={}
                if registered:
                    for name in set(meta.get('required_files',[]))|set(meta.get('file_sha256',{})):
                        if Path(name).name==name:audits[name]=Path(registered['reference_dir'],name).read_text()
                result['snapshots'].append({'query_id':record['query_id'], 'sha256':record['response_sha256'], 'metadata':meta, 'audit_files':audits,
                    'rows':table.loc[table.substrate.isin({r['mapped_accession'] for r in mapping})].to_dict('records')})
                client.accept(record, [{'validated_snapshot_rows':len(table)}])
            except (ValueError, KeyError, TypeError) as error:
                record.update(status='parse_failure', reason=str(error))
    # Query unique accessions once, reusing the existing native entry parser.
    # Priority spends the bounded calls on human, OmniPath substrates, then non-A0A accessions.
    by_accession = {r['mapped_accession']:r for r in mapping}
    substrates=set()
    for source in result['snapshots']:
        substrates.update(str(row.get('substrate')) for row in source.get('rows') or [] if row.get('substrate'))
    ordered = accession_query_order(by_accession, substrates)
    parser_module = None
    queried=set()
    for accession in ordered:
        if not client.within_budget('iPTMnet'):
            _defer(client, 'iPTMnet', 'iptmnet_provider_budget', {'accessions':[a for a in ordered if a not in queried]})
            break
        row = by_accession[accession]
        queried.add(accession)
        rec = client.query('iPTMnet', {'accession':accession,'taxon':row.get('fasta_taxonomy_id'),'ptm':ptm_type},
                           'https://research.bioinformatics.udel.edu/iptmnet/entry/'+urllib.parse.quote(accession), parser='text')
        if rec['status']=='not_run_budget':
            queried.discard(accession)
            _defer(client, 'iPTMnet', 'iptmnet_provider_budget', {'accessions':[a for a in ordered if a not in queried]})
            break
        if rec['status'] not in SUCCESS: continue
        if iptmnet_entry_absent(rec.get('payload') or ''):
            client.accept(rec, [])
            continue
        try:
            parser_module = parser_module or _iptm_parser()
            organism = parser_module._entry_organism(rec['payload'])
            expected = {'9606':'Human','10116':'Rat','10090':'Mouse'}.get(str(row.get('fasta_taxonomy_id')))
            if not expected or not organism or organism.lower()!=expected.lower(): raise ValueError('entry_taxonomy_unverified_or_mismatched')
            if parser_module._entry_schema_status(rec['payload']) != 'ok': raise ValueError('unrecognized_entry_schema')
            sites = parser_module._parse_sites_from_html(rec['payload'],'',target_ptm_type='phosphorylation',all_sites=True)
            parsed = [{key:getattr(s,key) for key in ('site','ptm_type','sources','pmids','enzyme_id','enzyme_name')} for s in sites]
            client.accept(rec, parsed)
            for site in parsed:
                result['relations'].append({'provider':'iPTMnet','query_id':rec['query_id'],'accession':accession,'taxon':row['fasta_taxonomy_id'],**site})
        except (ValueError, TypeError, ImportError, AttributeError) as error:
            rec.update(status='parse_failure',reason=str(error))
    # Secondary views use bounded batch queries, never an all-vs-all network.
    human = sorted({r['fasta_gene'] for r in mapping if str(r.get('fasta_taxonomy_id'))=='9606'})
    if len(human)>=2:
        rec=client.query('KEA3',{'genes':human,'taxon':'9606','mapping':'native_FASTA_OX'},'https://maayanlab.cloud/kea3/api/enrich/',body={'gene_set':human,'query_name':'PTM observed substrates'})
        if rec['status'] in SUCCESS:
            try:
                parsed=parse_kea3(rec['payload']); client.accept(rec,parsed)
                result['kea']=[{**r,'query_id':rec['query_id']} for r in parsed]
            except ValueError as error:rec.update(status='parse_failure',reason=str(error))
    else:
        client.records.append({'query_id':stable_id('query',['KEA3',human,taxa]),'provider':'KEA3','status':'not_supported',
            'query':{'native_human_genes':human},'reason':'insufficient_native_human_genes; nonhuman_uppercase_is_not_orthology','cache_hit':False})
    for tax in taxa:
        accessions=[a for a in ordered if str(by_accession[a].get('fasta_taxonomy_id'))==tax]
        sent=[]
        for start in range(0, len(accessions), STRING_IDENTIFIER_BATCH):
            if not client.within_budget('STRING'):
                break
            batch=accessions[start:start+STRING_IDENTIFIER_BATCH]
            form=urllib.parse.urlencode({'identifiers':'\r'.join(batch),'species':tax,'caller_identity':'PTM-Platform'})
            rec=client.query('STRING',{'accessions':batch,'taxon':tax,'transport':'post_form'},
                'https://string-db.org/api/json/network', form=form)
            rec['network_scope']=STRING_NETWORK_SCOPE
            rec['cross_batch_edges']=STRING_CROSS_BATCH
            if not string_batch_failure_continues(rec['status']):
                break
            sent.extend(batch)
            if rec['status'] not in SUCCESS:
                continue
            if not isinstance(rec['payload'],list):rec.update(status='parse_failure',reason='expected_network_rows')
            else:
                client.accept(rec,rec['payload']);result['context'].extend({'provider':'STRING','query_id':rec['query_id'],'edge_type':'network_pathway_context','record':r} for r in rec['payload'])
        pending=[a for a in accessions if a not in set(sent)]
        if pending:
            _defer(client,'STRING','string_batch_request_budget',{'accessions':pending,'taxon':tax,'network_scope':STRING_NETWORK_SCOPE,'cross_batch_edges':STRING_CROSS_BATCH})
    ran=set()
    for accession in ordered[:REACTOME_ACCESSION_BUDGET]:
        if not client.within_budget('Reactome'):
            break
        row=by_accession[accession]
        rec=client.query('Reactome',{'accession':accession,'taxon':row.get('fasta_taxonomy_id')},
            'https://reactome.org/ContentService/data/mapping/UniProt/'+urllib.parse.quote(accession)+'/pathways',
            empty_http_codes={404})
        if rec['status']=='not_run_budget':
            break
        ran.add(accession)
        if rec['status']=='no_hit' or rec['status'] not in SUCCESS: continue
        if not isinstance(rec['payload'],list):rec.update(status='parse_failure',reason='expected_pathway_rows')
        else:
            expected={'9606':'Homo sapiens','10116':'Rattus norvegicus','10090':'Mus musculus'}.get(str(row.get('fasta_taxonomy_id')))
            parsed=[r for r in rec['payload'] if r.get('speciesName')==expected and r.get('stId')]
            if len(parsed)!=len(rec['payload']):rec.update(status='partial',reason='species_or_identifier_mismatch_quarantined',parsed_rows=parsed)
            else:client.accept(rec,parsed)
            result['context'].extend({'provider':'Reactome','query_id':rec['query_id'],'edge_type':'network_pathway_context','accession':accession,'record':r} for r in parsed)
    unrun=[a for a in ordered if a not in ran]
    if unrun:
        head=set(ordered[:REACTOME_ACCESSION_BUDGET])
        reason='reactome_provider_budget' if head-ran else 'three_unique_accessions_per_run_operational_budget'
        _defer(client,'Reactome',reason,{'accessions':unrun})
    pmids=sorted({p for source in result['snapshots'] for r in source['rows'] for p in re.findall(r'\b\d{5,9}\b',r.get('references',''))})
    if pmids:
        rec=client.query('PubMed',{'PMIDs':pmids[:200],'selection':'all_observed_edge_PMIDs_first_200_sorted_budget'},
            'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?'+urllib.parse.urlencode({'db':'pubmed','id':','.join(pmids[:200]),'retmode':'json'}))
        if rec['status'] in SUCCESS:
            payload=rec['payload'].get('result') if isinstance(rec['payload'],dict) else None
            if not isinstance(payload,dict) or 'uids' not in payload:rec.update(status='parse_failure',reason='expected_pubmed_summary_result')
            else:
                parsed=[{'PMID':uid,'title':payload[uid].get('title'),'authors':payload[uid].get('authors'),
                    'publication_date':payload[uid].get('pubdate'),'identifiers':payload[uid].get('articleids'),
                    'content_status':'metadata_only','query_id':rec['query_id']} for uid in payload['uids'] if uid in payload]
                client.accept(rec,parsed);result['bibliography']=parsed
    else:
        client.records.append({'query_id':stable_id('query',['PubMed',pmids]),'provider':'PubMed','status':'not_supported',
            'query':{'PMIDs':pmids},'reason':'no_observed_relation_publication_identifiers','cache_hit':False})
    retain_unreplaced_prior_successes(prior_pins, result)
    result['status']='completed_with_limitations' if any(r['status'] not in SUCCESS for r in client.records) else 'completed'
    return pin_sources(root,result)


def pin_sources(root,result):
    # Source pin itself is content-addressed and contains no runtime/server paths.
    data=json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False,default=str).encode()
    sha=hashlib.sha256(data).hexdigest();path=Path(root)/'source_pins'/(sha+'.json')
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name('.'+sha+'-'+uuid4().hex);tmp.write_bytes(data);tmp.replace(path)
    return {**result,'pin_sha256':sha}
