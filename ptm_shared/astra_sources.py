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

VERSION = 'astra_sources.v1'
PARSER_VERSION = 'typed_provider_parsers.v1'
SUCCESS = {'hit', 'no_hit'}


def _write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '-' + uuid4().hex)
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
    tmp.replace(path)


class SourceClient:
    def __init__(self, root, fixtures=None, budget_seconds=45, max_requests=24, checkpoint=lambda: None, refresh=False):
        self.refresh=refresh
        self.root = Path(root); self.fixtures = fixtures
        self.deadline = time.monotonic() + budget_seconds
        self.max_requests = max_requests; self.requests = 0; self.records = []; self.checkpoint = checkpoint

    def query(self, provider, query, url, *, body=None, parser='json', license_scope='public_endpoint_terms'):
        self.checkpoint()
        key = stable_id('query', [provider, PARSER_VERSION, license_scope, query, url, body])
        cache = self.root / 'source_cache' / (key + '.json')
        base = {'query_id': key, 'provider': provider, 'provider_version': 'response_content_addressed',
                'parser_version': PARSER_VERSION, 'query': query, 'endpoint': url,
                'license_scope': license_scope, 'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                'status': None, 'cache_hit': False, 'response_sha256': None, 'payload': None,
                'original_resources': [], 'reason': None}
        if cache.exists() and not self.refresh:
            candidate = json.loads(cache.read_text())
            if candidate['status'] in SUCCESS and time.time() - cache.stat().st_mtime < 7 * 86400:
                raw = candidate.get('raw_response', '').encode()
                if hashlib.sha256(raw).hexdigest() == candidate.get('response_sha256'):
                    base = {**candidate, 'cache_hit': True}; self.records.append(base); return base
        fixture = (self.fixtures or {}).get(key, (self.fixtures or {}).get(provider))
        if self.fixtures is not None and fixture is None:
            base.update(status='access_unavailable', reason='fixture_provider_not_supplied')
        elif self.requests >= self.max_requests or time.monotonic() >= self.deadline:
            base.update(status='not_run_budget', reason='bounded_unique_query_budget_exhausted')
        else:
            self.requests += 1
            try:
                if fixture is not None:
                    if fixture.get('status') not in (None, 'hit', 'no_hit'):
                        base.update(status=fixture['status'], reason=fixture.get('reason', 'frozen_response_fixture'))
                        self.records.append(base); return base
                    raw = fixture.get('raw', json.dumps(fixture.get('payload', {}), ensure_ascii=False))
                else:
                    headers = {'User-Agent': 'PTM-Platform-Astra/4', 'Accept': 'application/json,text/tab-separated-values,text/html'}
                    data = json.dumps(body).encode() if body is not None else None
                    if data is not None: headers['Content-Type'] = 'application/json'
                    req = urllib.request.Request(url, data=data, headers=headers)
                    # One retry with bounded backoff. Never turn HTTP failures into an empty answer.
                    for attempt in range(2):
                        try:
                            with urllib.request.urlopen(req, timeout=max(.1, min(10, self.deadline-time.monotonic()))) as response:
                                raw = response.read(64 * 1024 * 1024 + 1)
                                if len(raw) > 64 * 1024 * 1024: raise ValueError('response_size_limit')
                                raw = raw.decode('utf-8'); break
                        except urllib.error.HTTPError as error:
                            if attempt == 0 and error.code in {429, 502, 503} and time.monotonic()+1 < self.deadline:
                                time.sleep(.25); continue
                            raise
                base['raw_response'] = raw; base['response_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
                payload = json.loads(raw) if parser == 'json' else raw
                base.update(payload=payload, status='hit' if payload else 'no_hit')
            except urllib.error.HTTPError as error:
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


def resolve_sources(root, mapping, fasta_genes, ptm_type, *, pin_sha=None, refresh=False, fixtures=None, checkpoint=lambda: None):
    root = Path(root)
    if pin_sha and not refresh:
        path = root/'source_pins'/(pin_sha+'.json')
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == pin_sha:
            return {**json.loads(path.read_text()), 'pin_sha256': pin_sha}
        raise ValueError('Pinned source bytes missing/corrupt; do not silently refresh an immutable source pin')
    client = SourceClient(root, fixtures, checkpoint=checkpoint, refresh=refresh)
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
    by_accession = {r['mapped_accession']:r for r in mapping}
    parser_module = None
    for accession, row in sorted(by_accession.items()):
        if client.requests >= client.max_requests - 6 or time.monotonic() >= client.deadline - 15:
            remaining = sorted(set(by_accession)-{r['query'].get('accession') for r in client.records if r['provider']=='iPTMnet'})
            client.records.append({'query_id':stable_id('query',['iPTMnet_deferred',remaining]), 'provider':'iPTMnet', 'status':'not_run_budget',
                'query':{'accessions':remaining}, 'reason':'unique_accession_request_budget', 'cache_hit':False}); break
        rec = client.query('iPTMnet', {'accession':accession,'taxon':row.get('fasta_taxonomy_id'),'ptm':ptm_type},
                           'https://research.bioinformatics.udel.edu/iptmnet/entry/'+urllib.parse.quote(accession), parser='text')
        if rec['status'] not in SUCCESS: continue
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
        accessions=sorted({r['mapped_accession'] for r in mapping if str(r.get('fasta_taxonomy_id'))==tax})
        rec=client.query('STRING',{'accessions':accessions,'taxon':tax},'https://string-db.org/api/json/network?'+urllib.parse.urlencode({'identifiers':'\r'.join(accessions),'species':tax,'caller_identity':'PTM-Platform'}))
        if rec['status'] in SUCCESS:
            if not isinstance(rec['payload'],list):rec.update(status='parse_failure',reason='expected_network_rows')
            else:
                client.accept(rec,rec['payload']);result['context'].extend({'provider':'STRING','query_id':rec['query_id'],'edge_type':'network_pathway_context','record':r} for r in rec['payload'])
    # Reuse the existing Reactome accession endpoint without its gene-uppercase fallback.
    for accession,row in sorted(by_accession.items())[:3]:
        rec=client.query('Reactome',{'accession':accession,'taxon':row.get('fasta_taxonomy_id')},
            'https://reactome.org/ContentService/data/mapping/UniProt/'+urllib.parse.quote(accession)+'/pathways')
        if rec['status'] in SUCCESS:
            if not isinstance(rec['payload'],list):rec.update(status='parse_failure',reason='expected_pathway_rows')
            else:
                expected={'9606':'Homo sapiens','10116':'Rattus norvegicus','10090':'Mus musculus'}.get(str(row.get('fasta_taxonomy_id')))
                parsed=[r for r in rec['payload'] if r.get('speciesName')==expected and r.get('stId')]
                if len(parsed)!=len(rec['payload']):rec.update(status='partial',reason='species_or_identifier_mismatch_quarantined',parsed_rows=parsed)
                else:client.accept(rec,parsed)
                result['context'].extend({'provider':'Reactome','query_id':rec['query_id'],'edge_type':'network_pathway_context','accession':accession,'record':r} for r in parsed)
    if len(by_accession)>3:
        client.records.append({'query_id':stable_id('query',['Reactome_deferred',sorted(by_accession)[3:]]),'provider':'Reactome','status':'not_run_budget',
            'query':{'accessions':sorted(by_accession)[3:]},'reason':'three_unique_accessions_per_run_operational_budget','cache_hit':False})
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
    result['status']='completed_with_limitations' if any(r['status'] not in SUCCESS for r in client.records) else 'completed'
    return pin_sources(root,result)


def pin_sources(root,result):
    # Source pin itself is content-addressed and contains no runtime/server paths.
    data=json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False,default=str).encode()
    sha=hashlib.sha256(data).hexdigest();path=Path(root)/'source_pins'/(sha+'.json')
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name('.'+sha+'-'+uuid4().hex);tmp.write_bytes(data);tmp.replace(path)
    return {**result,'pin_sha256':sha}
