"""Whole-evidence access to saved rows. No scoring, selection or review is run.

The data dictionary is the source-key registry. CSVs remain authoritative; this
module stores only locators and searchable metadata, not cards or value arrays.
"""
import argparse
import base64
from collections import defaultdict
import json
from pathlib import Path

import pandas as pd

from .annotation_registry import digest
from .astra_card_inputs import clean, encode, ids
from .astra_inputs import stable_id
from .astra_reader_temporal import source_row, SOURCE_TABLES
from .generic_workflow import json_write, object_hash

VERSION = 'astra_evidence_access.v1'
CATALOG = 'reader/evidence_catalog.json'
INDEX = 'reader/evidence_index.csv'
LINKS = 'reader/evidence_links.csv'
GUIDE = 'reader/EVIDENCE_ACCESS.md'
ARTIFACTS = [CATALOG, INDEX, LINKS, GUIDE]
TABLE_KEYS = {'reader/evidence_index': ['evidence_id'], 'reader/evidence_links': ['link_id']}
REQUIRED = {
    'reader/cards.csv': 'card', 'reader/coverage.csv': 'disposition',
    'reader_adapter/form_contrasts.csv': 'raw_ptm',
    'quant/summary.csv': 'form', 'quant/comparisons.csv': 'ptm_contrast',
    'quant/protein_contrasts.csv': 'protein', 'quant/detection.csv': 'detection',
    'evidence/emergence_evidence.csv': 'emergence',
    'kinase/method_scores.csv': 'method_result', 'science/inference_results.csv': 'inference',
}
SCOPE = ['arm_id', 'reference_condition_id', 'pairing', 'series_id', 'method_id', 'method_version', 'track', 'call_scope']
IDS = ['form_id', 'card_id', 'candidate_id', 'contrast_id', 'condition_id', 'consumer_state_id',
       'measurement_group_id', 'site_id', 'entity_id', 'proposed_entity_id']
STATES = ['status', 'included', 'card_status', 'consumer_state_status', 'card_input_eligible',
          'mapping_status', 'localization_status', 'baseline_status', 'primary_mapping_eligible',
          'primary_adjustment_eligible', 'inference_status', 'resolution', 'calibration_status',
          'execution_status', 'measurement_status', 'independent_validation_status', 'coverage_adequate']
RESTRICTIONS = ['restriction_reasons', 'exclusion_reasons', 'no_call_reasons', 'use_restriction',
                'adapter_restrictions', 'interpretation_limits']
COLUMNS = ['evidence_id', 'evidence_type', 'source_table', 'source_key_json', *IDS,
           'scope_json', 'status_json', 'restrictions_json', 'entity_tokens_json', 'taxa_json',
           'display_label', 'time_min', 'reference_time_min', 'selected_for_summary', 'review_status']
LINK_COLUMNS = ['link_id', 'relation_type', 'from_table', 'from_key_json', 'to_table', 'to_key_json', 'status', 'reason']


def safe_path(root, name):
    relative = Path(name)
    path = (Path(root) / relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Unsafe catalog source path: ' + str(name))
    return path


def read_source(root, name, descriptor, *, columns=None, chunksize=None):
    """Same round-trip/dtype contract as read_tables, with column/chunk projection."""
    return pd.read_csv(safe_path(root, name), low_memory=False, float_precision='round_trip',
        dtype={k: 'str' for k, v in descriptor['dtypes'].items()
               if v in {'str', 'object'} and (columns is None or k in columns)},
        usecols=columns, chunksize=chunksize)


def access_contract():
    return {'catalog_available': True, 'schema_version': VERSION, 'catalog': CATALOG,
            'index': INDEX, 'links': LINKS, 'query_guide': GUIDE,
            'source_scope': 'all registered analysis tables; indexed sources listed in catalog',
            'reader_cards_scope': 'summary preview, not complete evidence',
            'review_status': 'not_recorded',
            'limits': 'M1 access only. Existing downstream question/temporal/literature selection scope is unchanged.'}


def attach_access(tables):
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    packet['evidence_access'] = access_contract()
    if packet.get('whole_evidence'):
        packet['evidence_access']['limits'] = 'Whole question/module/temporal access is available. Literature review execution remains the frozen original scope (M3/M4 deferred).'
    packet['authoring_rules']['whole_evidence_access'] = (
        'reader_cards and selected_findings are a summary preview. Query the evidence catalog for '
        'unselected, withheld and no-call evidence; resolve exact source keys before citing values. '
        'Index availability is not evidence of reading, literature comparison or biological review.')
    tables['reader/packet'].loc[tables['reader/packet'].index[0], 'packet_json'] = json.dumps(packet, ensure_ascii=False, sort_keys=True)


def evidence_id_for(name, key):
    """Shared typed identity for indexed and catalog-only canonical rows."""
    keys = list(key)
    if name != 'reader/coverage.csv' and len(keys) == 1 and keys[0].endswith('_id') and key[keys[0]] is not None:
        return str(key[keys[0]])
    return stable_id('evidence', [name, key])


def _key(row, keys):
    return {k: row[k] for k in keys}


def _tokens(*values):
    result = set()
    for v in values:
        if isinstance(v, (list, tuple, set)):
            result.update(_tokens(*v))
        elif v is not None:
            result.update(ids(v))
    return sorted(result)


def _source_catalog(root, dictionary):
    missing = set(REQUIRED) - set(dictionary)
    if missing:
        raise ValueError('Missing required evidence sources: ' + ', '.join(sorted(missing)))
    catalog = {}
    for name, meta in sorted(dictionary.items()):
        if name in {INDEX, LINKS}: continue
        keys = meta.get('unique_key')
        if not keys or not set(keys) <= set(meta['columns']):
            raise ValueError('Missing canonical source key: ' + name)
        path = safe_path(root, name)
        seen = set(); count = 0
        for chunk in read_source(root, name, meta, columns=keys, chunksize=50000):
            for values in chunk[keys].itertuples(index=False, name=None):
                key = encode(dict(zip(keys, values)))
                if key in seen: raise ValueError('Duplicate source key: ' + name + ' ' + key)
                seen.add(key)
            count += len(chunk)
        if count != meta['rows']: raise ValueError('Source row count mismatch: ' + name)
        catalog[name] = {**meta, 'sha256': digest(path), 'descriptor_schema_version': VERSION,
            'availability': 'available' if count else 'available_empty',
            'role': REQUIRED.get(name, 'registered_source'), 'indexed': name in REQUIRED,
            'access': 'evidence_id' if name in REQUIRED else 'registered_source_and_canonical_key',
            'independent_observation_count': None}
    return catalog


def build_evidence_index(root, dictionary):
    """Build against persisted bytes after the existing CSV writer, before sealing.

    Source keys/dtypes/units come from the existing dictionary. No row number,
    label, summary rank, or numeric measurement contributes to an evidence ID.
    """
    sources = _source_catalog(root, dictionary)
    frames = {name: read_source(root, name, sources[name]) for name in REQUIRED}
    identity_name = 'reader_adapter/form_identity.csv'
    if identity_name not in sources: raise ValueError('Missing form identity source')
    identities = {r.form_id: json.loads(r.identity_json) for r in read_source(root, identity_name, sources[identity_name]).itertuples()}
    summaries = {r['form_id']: r for r in frames['quant/summary.csv'].to_dict('records')}
    contrasts = {}
    for r in frames['quant/comparisons.csv'].drop_duplicates(['contrast_id']).to_dict('records'):
        contrasts[r['contrast_id']] = source_row(r)
    # Stored canonical ContrastEstimator metadata; ensure a contrast never mixes scopes.
    meta_fields = ['contrast_id', *[k for k in SCOPE + ['time_min', 'reference_time_min'] if k in frames['quant/comparisons.csv']]]
    if frames['quant/comparisons.csv'][meta_fields].drop_duplicates().contrast_id.duplicated().any():
        raise ValueError('Conflicting canonical contrast metadata')
    candidates = defaultdict(lambda: {'tokens': set(), 'taxa': set()})
    edge_name = 'kinase/kinase_candidate_edges.csv'
    if edge_name in sources:
        cols = [k for k in ['candidate_id', 'candidate_gene', 'candidate_accession', 'kinase_taxon'] if k in sources[edge_name]['columns']]
        for r in read_source(root, edge_name, sources[edge_name], columns=cols).drop_duplicates().to_dict('records'):
            r = source_row(r); entry = candidates[r['candidate_id']]
            entry['tokens'].update(_tokens(r.get('candidate_gene'), r.get('candidate_accession')))
            entry['taxa'].update(_tokens(r.get('kinase_taxon')))
    coverage = {r['adapter_row_id']: source_row(r) for r in frames['reader/coverage.csv'].to_dict('records')}
    if set(coverage) != set(frames['reader_adapter/form_contrasts.csv'].adapter_row_id):
        raise ValueError('Coverage/adapter canonical key population mismatch')
    selected_rows = {k for k, v in coverage.items() if v['summary_disposition'] == 'selected'}
    selected_pairs = {(v['form_id'], v['contrast_id']) for k, v in coverage.items() if k in selected_rows}
    parent_keys = set(frames['quant/protein_contrasts.csv'][['protein_group', 'contrast_id']].itertuples(index=False, name=None))
    index = []; links = {}

    def link(ft, fk, tt, tk, relation, status='resolved', reason=None):
        if tt not in sources: raise ValueError('Unregistered link target: ' + tt)
        if set(fk) != set(sources[ft]['unique_key']) or set(tk) != set(sources[tt]['unique_key']):
            raise ValueError('Link canonical key mismatch')
        lid = stable_id('evidence_link', [ft, fk, tt, tk, relation])
        links[lid] = dict(zip(LINK_COLUMNS, [lid, relation, ft, encode(fk), tt, encode(tk), status, reason]))

    for name, frame in frames.items():
        keys = sources[name]['unique_key']
        for raw in frame.to_dict('records'):
            row = source_row(raw); key = _key(row, keys)
            details = json.loads(row['card_json']) if name == 'reader/cards.csv' else json.loads(row['row_json']) if name == 'reader_adapter/form_contrasts.csv' else {}
            r = {**details, **row}
            fid = r.get('form_id'); identity = identities.get(fid, {})
            if fid is not None and fid not in summaries: raise ValueError('Unknown form FK: ' + fid)
            cid = r.get('contrast_id', r.get('contrast_or_window_id'))
            metadata = contrasts.get(cid, {})
            scope = {k: r.get(k, metadata.get(k)) for k in SCOPE}
            if name == 'reader/cards.csv' and details.get('source_bindings'):
                bindings = details['source_bindings']
                for k in SCOPE:
                    values = {encode(b.get(k)) for b in bindings}
                    if len(values) == 1 and scope[k] is None: scope[k] = bindings[0].get(k)
            candidate = candidates.get(r.get('candidate_id') or r.get('proposed_entity_id'), {})
            tokens = _tokens(identity.get('gene'), identity.get('protein_group'), r.get('gene'), r.get('Genes'),
                r.get('protein_group'), r.get('Protein.Group'), candidate.get('tokens', []))
            taxa = _tokens(identity.get('taxa', []), candidate.get('taxa', []))
            eid = evidence_id_for(name, key)
            state = {k: r.get(k, identity.get(k)) for k in STATES if k in r or k in identity}
            if name == 'reader_adapter/form_contrasts.csv': state['card_status'] = coverage[row['adapter_row_id']]['card_status']
            selected = (r.get('selected') is True) if name == 'reader/cards.csv' else (fid, cid) in selected_pairs
            index.append({**{k: r.get(k) for k in IDS}, 'evidence_id': eid,
                'evidence_type': {'measured_feature_observation': 'observation', 'quantitation_comparison': 'comparison'}.get(r.get('category'), REQUIRED[name]),
                'source_table': name, 'source_key_json': encode(key), 'scope_json': encode(scope),
                'status_json': encode(state), 'restrictions_json': encode({k: r[k] for k in RESTRICTIONS if k in r}),
                'entity_tokens_json': encode(tokens), 'taxa_json': encode(taxa),
                'display_label': identity.get('display_label') or r.get('feature_label') or ';'.join(tokens) or eid,
                'time_min': r.get('time_min', metadata.get('time_min')),
                'reference_time_min': r.get('reference_time_min', metadata.get('reference_time_min')),
                'selected_for_summary': selected, 'review_status': 'not_recorded'})
            if fid and name != 'quant/summary.csv':
                link(name, key, 'quant/summary.csv', {'form_id': fid}, 'form_representation')
            if name == 'reader/cards.csv':
                for b in details['source_bindings']:
                    link(name, key, 'reader_adapter/form_contrasts.csv', {'adapter_row_id': b['adapter_row_id']}, 'card_source')
            if name == 'reader/coverage.csv':
                link(name, key, 'reader_adapter/form_contrasts.csv', key, 'disposition_of')
            if name == 'reader_adapter/form_contrasts.csv':
                link(name, key, 'quant/comparisons.csv', {'form_id': fid, 'contrast_id': cid}, 'projection_of')
            if name == 'quant/comparisons.csv':
                parent = summaries[fid].get('parent_pg')
                if parent is not None and not pd.isna(parent):
                    target = {'protein_group': parent, 'contrast_id': cid}
                    # The recorded PG parent can be unavailable; never silently choose an alias.
                    exists = (parent, cid) in parent_keys
                    if exists: link(name, key, 'quant/protein_contrasts.csv', target, 'same_experiment_parent_context')

    for name, relation, target in [
        ('reader_adapter/precursor_membership.csv', 'precursor_member_of', 'quant/summary.csv'),
        ('kinase/substrate_contributions.csv', 'substrate_contribution_from', 'quant/comparisons.csv')]:
        if name not in sources: continue
        cols = list(dict.fromkeys(sources[name]['unique_key'] + (['form_id'] if 'precursor' in name else ['form_ids', 'contrast_id'])))
        for row in read_source(root, name, sources[name], columns=cols).to_dict('records'):
            row = source_row(row)
            for fid in _tokens(row.get('form_id'), row.get('form_ids')):
                tk = {'form_id': fid}
                if target.endswith('comparisons.csv'): tk['contrast_id'] = row['contrast_id']
                link(name, _key(row, sources[name]['unique_key']), target, tk, relation)

    index = pd.DataFrame(index, columns=COLUMNS)
    if index.evidence_id.duplicated().any(): raise ValueError('Duplicate typed evidence ID')
    # Scope first, then numeric time, then stable identity. NA sorts last, never at zero.
    index = index.sort_values(['scope_json', 'reference_time_min', 'time_min', 'evidence_id'], na_position='last', kind='stable').reset_index(drop=True)
    links = pd.DataFrame([links[k] for k in sorted(links)], columns=LINK_COLUMNS)
    # Check actual endpoint key sets, including catalog-only sources and normal N:M links.
    for side in ['from', 'to']:
        for name, group in links.groupby(side + '_table'):
            keys = sources[name]['unique_key']
            known = {encode(dict(zip(keys, values))) for chunk in read_source(root, name, sources[name], columns=keys, chunksize=50000)
                     for values in chunk[keys].itertuples(index=False, name=None)}
            if not set(group[side + '_key_json']) <= known: raise ValueError('Broken evidence link FK: ' + name)
    catalog = {'schema_version': VERSION, 'catalog_available': True, 'sources': sources,
        'optional_sources': {name+'.csv': {'availability': 'not_available', 'reason': 'not_generated_in_source_package'}
                             for name in SOURCE_TABLES if name+'.csv' not in sources},
        'indexed_rows': len(index), 'links': len(links), 'review_status': 'not_recorded',
        'counts_are_representations_not_independent_observations': True,
        'query': {'default_exclusions': [], 'sort': ['scope_json', 'reference_time_min', 'time_min', 'evidence_id'],
                  'filters': ['entity', 'evidence_type', 'source_table', 'status', *IDS, *SCOPE, 'taxon', 'selected_for_summary']}}
    return index, catalog, links


def write_evidence_access(directory, *, source_root=None):
    directory = Path(directory); root = Path(source_root or directory)
    dictionary = json.loads((root/'reproducibility/data_dictionary.json').read_text())
    index, catalog, links = build_evidence_index(root, dictionary)
    from .astra_package import write_tables
    entries = write_tables({'reader/evidence_index': index, 'reader/evidence_links': links}, directory)
    for name, meta in entries.items():
        meta.update(unique_key=TABLE_KEYS[name[:-4]], row_grain=TABLE_KEYS[name[:-4]],
                    units='source locators and metadata only; quantities remain in source tables')
    if source_root is None:
        dictionary.update(entries)
        json_write(directory/'reproducibility/data_dictionary.json', dictionary)
    catalog['artifacts'] = {name: {'sha256': digest(directory/name), **entries[name]} for name in [INDEX, LINKS]}
    catalog['catalog_id'] = object_hash(catalog)
    json_write(directory/CATALOG, catalog)
    (directory/GUIDE).write_text(GUIDANCE, encoding='utf-8')
    return ARTIFACTS


GUIDANCE = '''# 전체 근거 접근 (M1)

선정 findings와 authoring packet의 reader_cards는 요약 preview입니다. 전체 분석 범위가 아닙니다.
[catalog](evidence_catalog.json) · [전체 인덱스](evidence_index.csv) · [기존 관계](evidence_links.csv).
원본 값·NA·mask는 복제하지 않습니다. resolve의 source_row/card를 읽고 source_table과 source_key를 함께 인용하세요.
보류·미선정·no-call은 기본 조회에 포함됩니다. 인덱스의 행 수는 독립 관측 수가 아닙니다.
review_status=not_recorded: 접근 가능하다는 뜻이며 AI가 읽거나 생물학적으로 검토했다는 뜻이 아닙니다.

패키지 루트에서 (pandas가 있는 Python):
```sh
PYTHONPATH=reproducibility/code python -m ptm_shared.astra_evidence_catalog --package . query --filters '{"entity":"MAPK1"}' --page-size 5
PYTHONPATH=reproducibility/code python -m ptm_shared.astra_evidence_catalog --package . query --filters '{"form_id":"form_97aa4b58cee5c391","source_table":"quant/comparisons.csv"}'
```
query의 evidence_id로 `resolve ID ...`, `links ID ...`를 실행합니다. 다음 페이지는 같은 filters에 `--cursor TOKEN`을 전달합니다.
카탈로그 전용 표는 `source TABLE --key '{"키":"값"}'`로 직접 해석합니다. table과 key는 catalog 정의를 사용하세요.
필터·catalog가 바뀐 cursor, 미등록 ID/경로/키, hash 불일치는 오류입니다. 모든 페이지를 순회하면 필터 범위 전체에 접근합니다.
기존 문헌·질문·시간 후속 경로의 selected 의존성 확장은 M2–M4입니다. M1은 그 실행·검토 범위를 변경하지 않습니다.
precursor_member_of는 측정 precursor 구성이고 substrate_contribution_from는 후보 footprint 기여입니다. 서로 대체하거나 독립 검증으로 세지 않습니다.
'''


class EvidenceCatalog:
    """Package-local query/resolve session; no network, inference or external paths."""
    def __init__(self, root):
        self.root = Path(root).resolve(); path = self.root/CATALOG
        self._verified = {}
        self.catalog_available = path.is_file()
        if not self.catalog_available:
            self.catalog = {'catalog_available': False, 'reason': 'legacy_package_without_catalog',
                            'source_registry': 'reproducibility/data_dictionary.json'}
            return
        self.catalog = json.loads(path.read_text())
        self._catalog_sha256 = digest(path)
        if self.catalog['catalog_id'] != object_hash({k: v for k, v in self.catalog.items() if k != 'catalog_id'}):
            raise ValueError('Catalog hash mismatch')
        for name, meta in self.catalog['artifacts'].items(): self._verify(name, meta)
        for name, meta in self.catalog['sources'].items(): self._verify(name, meta)
        self.index = read_source(self.root, INDEX, self.catalog['artifacts'][INDEX])
        self.links = read_source(self.root, LINKS, self.catalog['artifacts'][LINKS])
        if self.index.evidence_id.duplicated().any(): raise ValueError('Duplicate evidence ID')
        if self.links.link_id.duplicated().any(): raise ValueError('Duplicate evidence link ID')

    def _require(self):
        if not self.catalog_available: raise ValueError('catalog_available=false; use reproducibility/data_dictionary.json and original tables')
        if digest(self.root/CATALOG) != self._catalog_sha256: raise ValueError('Catalog changed; open a new query session')
        # A cursor may not silently continue over modified source bytes. Initial
        # open hashes every source; subsequent calls rehash files whose filesystem
        # identity/size/timestamps changed. This is session-local, not a new cache.
        for name, (signature, meta) in list(self._verified.items()):
            if self._signature(name) != signature: self._verify(name, meta)

    def _signature(self, name):
        stat = safe_path(self.root, name).stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def _verify(self, name, meta):
        if digest(safe_path(self.root, name)) != meta['sha256']: raise ValueError('Source hash mismatch: ' + name)
        self._verified[name] = (self._signature(name), meta)

    def query(self, filters=None, cursor=None, page_size=100):
        self._require(); filters = filters or {}
        if not isinstance(page_size, int) or not 1 <= page_size <= 10000: raise ValueError('page_size must be 1..10000')
        if not set(filters) <= set(self.catalog['query']['filters']): raise ValueError('Unknown filter')
        fingerprint = object_hash([self.catalog['catalog_id'], filters]); offset = 0
        if cursor:
            try:
                parsed = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if parsed['binding'] != fingerprint: raise ValueError('Cursor catalog/filter mismatch')
                offset = parsed['offset']
                if not isinstance(offset, int) or offset < 0: raise ValueError('Invalid cursor offset')
            except (KeyError, TypeError, json.JSONDecodeError) as exc: raise ValueError('Invalid cursor') from exc
        f = self.index
        for key, value in filters.items():
            values = value if isinstance(value, list) else [value]
            if key == 'entity':
                wanted = {str(v).casefold() for v in values}
                mask = f.entity_tokens_json.map(lambda v: bool(wanted & {str(x).casefold() for x in json.loads(v)}))
            elif key == 'taxon': mask = f.taxa_json.map(lambda v: bool({str(x) for x in json.loads(v)} & {str(x) for x in values}))
            elif key == 'status': mask = f.status_json.map(lambda v: any(x in values for x in json.loads(v).values() if not isinstance(x, (list, dict))))
            elif key in SCOPE: mask = f.scope_json.map(lambda v: json.loads(v).get(key) in values)
            else: mask = f[key].isin(values)
            f = f.loc[mask]
        total = len(f)
        if offset > total: raise ValueError('Cursor outside result set')
        page = f.iloc[offset:offset+page_size]; following = offset + len(page)
        cursor = base64.urlsafe_b64encode(encode({'binding': fingerprint, 'offset': following}).encode()).decode() if following < total else None
        return {'items': [source_row(r) for r in page.to_dict('records')], 'total_count': total,
                'returned_count': len(page), 'next_cursor': cursor, 'applied_filters': filters, 'review_status': 'not_recorded'}

    def source_rows(self, name, keys):
        self._require()
        if name not in self.catalog['sources']: raise ValueError('Unregistered source: ' + name)
        meta = self.catalog['sources'][name]; self._verify(name, meta)
        if any(set(k) != set(meta['unique_key']) for k in keys): raise ValueError('Invalid canonical source key')
        wanted = {encode(k) for k in keys}; found = {}
        for chunk in read_source(self.root, name, meta, chunksize=20000):
            # Match only key columns before materializing potentially large card JSON.
            for ix, values in zip(chunk.index, chunk[meta['unique_key']].itertuples(index=False, name=None)):
                key = encode(dict(zip(meta['unique_key'], values)))
                if key in wanted:
                    if key in found: raise ValueError('Duplicate resolved source key')
                    found[key] = source_row(chunk.loc[ix].to_dict())
        if set(found) != wanted: raise ValueError('Unknown source key: ' + name)
        return [found[encode(k)] for k in keys]

    def resolve(self, evidence_ids):
        self._require(); by_id = self.index.set_index('evidence_id')
        if set(evidence_ids) - set(by_id.index): raise ValueError('Unknown evidence ID')
        results = {}
        chosen = by_id.loc[list(dict.fromkeys(evidence_ids))].reset_index()
        for name, group in chosen.groupby('source_table'):
            keys = [json.loads(v) for v in group.source_key_json]
            for item, row in zip(group.to_dict('records'), self.source_rows(name, keys)):
                results[item['evidence_id']] = {'evidence': source_row(item), 'source_row': row,
                    'card': json.loads(row['card_json']) if 'card_json' in row else None,
                    'source_ref': {'table': name, 'key': json.loads(item['source_key_json'])}, 'review_status': 'not_recorded'}
        return [results[i] for i in evidence_ids]

    def resolve_links(self, evidence_ids, relation_types=None):
        resolved = self.resolve(evidence_ids)
        refs = {(r['source_ref']['table'], encode(r['source_ref']['key'])) for r in resolved}
        links = self.links
        mask = [((r.from_table, r.from_key_json) in refs or (r.to_table, r.to_key_json) in refs) for r in links.itertuples()]
        links = links.loc[mask]
        if relation_types is not None: links = links.loc[links.relation_type.isin(relation_types)]
        for side in ['from', 'to']:
            for name, group in links.groupby(side+'_table'):
                self.source_rows(name, [json.loads(v) for v in group[side+'_key_json'].drop_duplicates()])
        return {'links': [source_row(r) for r in links.to_dict('records')],
                'status': 'resolved' if len(links) else 'no_stored_relationship',
                'review_status': 'not_recorded'}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--package', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    q = commands.add_parser('query'); q.add_argument('--filters', default='{}'); q.add_argument('--cursor'); q.add_argument('--page-size', type=int, default=100)
    for name in ['resolve', 'links']:
        p = commands.add_parser(name); p.add_argument('ids', nargs='+')
    p = commands.add_parser('source'); p.add_argument('table'); p.add_argument('--key', required=True)
    args = parser.parse_args(); catalog = EvidenceCatalog(args.package)
    if not catalog.catalog_available: result = catalog.catalog
    elif args.command == 'query': result = catalog.query(json.loads(args.filters), args.cursor, args.page_size)
    elif args.command == 'resolve': result = catalog.resolve(args.ids)
    elif args.command == 'links': result = catalog.resolve_links(args.ids)
    else: result = catalog.source_rows(args.table, [json.loads(args.key)])
    print(encode(result))


if __name__ == '__main__': main()
