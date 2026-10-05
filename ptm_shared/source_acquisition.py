"""Research acquisition policies: explicit universe, mapping, no hidden first-N cutoff."""
import urllib.parse
from .astra_inputs import stable_id

STRING_RELEASE='12.5'
STRING_ENDPOINT='https://version-12-5.string-db.org/api/json'


def string_network(client,accessions,taxon):
    """Batch ID resolution, then ONE induced network query over all resolved IDs.

    If the provider refuses the full query, scope is partial/unavailable; never
    substitute disconnected within-batch networks and call the result complete.
    """
    mapped={};records=[];rows=[]
    for offset in range(0,len(accessions),100):
        batch=accessions[offset:offset+100]
        rec=client.query('STRING',{'step':'identifier_mapping','accessions':batch,'taxon':taxon,'release':STRING_RELEASE},
            STRING_ENDPOINT+'/get_string_ids',form={'identifiers':'\r'.join(batch),'species':taxon,'echo_query':1,'caller_identity':'PTM-Platform'})
        rec.update(provider_version=STRING_RELEASE,query_universe='recorded_observed_proteins')
        if rec['status'] not in {'hit','no_hit'}:continue
        if not isinstance(rec['payload'],list):rec.update(status='parse_failure',reason='expected_mapping_rows');continue
        valid=[];bad=False
        for r in rec['payload']:
            if str(r.get('ncbiTaxonId'))!=str(taxon) or r.get('queryItem') not in batch or not str(r.get('stringId','')).startswith(str(taxon)+'.'):
                bad=True;continue
            valid.append(r);mapped.setdefault(r['queryItem'],set()).add(r['stringId'])
        if bad:rec.update(status='partial',reason='taxonomy_or_query_mapping_quarantined',parsed_rows=valid)
        else:client.accept(rec,valid)
    for accession in accessions:
        ids=mapped.get(accession,set())
        records.append({'accession':accession,'taxon':taxon,'string_ids':sorted(ids),'status':'resolved' if len(ids)==1 else 'ambiguous' if ids else 'unresolved',
                        'mapping_semantics':'provider_mapping_not_sequence_identity'})
    identifiers=sorted({next(iter(v)) for v in mapped.values() if len(v)==1})
    if not identifiers:
        return rows,records,{'status':'not_evaluable','reason':'no_resolved_identifiers','queried_accessions':len(accessions),'mapped':0}
    rec=client.query('STRING',{'step':'induced_network','identifiers':identifiers,'taxon':taxon,'release':STRING_RELEASE,'required_score':400},
        STRING_ENDPOINT+'/network',form={'identifiers':'\r'.join(identifiers),'species':taxon,'add_nodes':0,'required_score':400,'network_type':'functional','caller_identity':'PTM-Platform'})
    rec.update(provider_version=STRING_RELEASE,network_scope='all_resolved_observed_identifiers_induced',cross_batch_edges='requested_together')
    status=rec['status']
    if status in {'hit','no_hit'}:
        payload=rec['payload'];valid=[];universe=set(identifiers)
        if not isinstance(payload,list):rec.update(status='parse_failure',reason='expected_network_rows')
        else:
            for r in payload:
                if str(r.get('ncbiTaxonId'))==str(taxon) and r.get('stringId_A') in universe and r.get('stringId_B') in universe:valid.append(r)
            if len(valid)!=len(payload):rec.update(status='partial',reason='unexpected_network_nodes_quarantined',parsed_rows=valid)
            else:client.accept(rec,valid)
            rows=[{'provider':'STRING','query_id':rec['query_id'],'edge_type':'network_pathway_context','record':r} for r in valid]
    return rows,records,{'status':rec['status'],'queried_accessions':len(accessions),'mapped':len(mapped),
        'unique_resolved_ids':len(identifiers),'unresolved':sum(r['status']!='resolved' for r in records),
        'scope':'induced_observed_universe','cross_batch_edges':'requested_together','required_score':400,
        'completeness':'resolved_subset_only' if len(mapped)<len(accessions) else 'see_network_query_status'}
