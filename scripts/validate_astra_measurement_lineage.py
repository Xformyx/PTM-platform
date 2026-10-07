"""Read-only Round 05 audit of a completed local run and its recorded input paths.

This consumes existing input manifests/capabilities/lineage. It does not discover
unrelated files, invent a DIA-NN version, query providers, or run quantification.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd
from ptm_shared.annotation_registry import digest
from ptm_shared.astra_package import validate_package
from scripts.validate_astra_activation import compare_quant


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution',type=Path,required=True)
    parser.add_argument('--baseline-archive',type=Path,required=True)
    parser.add_argument('--g1-archive',type=Path,required=True)
    parser.add_argument('--order-record',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    read=lambda path:json.loads(path.read_text())
    result=read(args.execution/'reuse_result.json');run=args.execution/'output/enrichment_free_runs'/result['run_id']
    config=read(args.execution/'config.json');saved=read(run/'reproducibility/replay_config.json')
    order=read(args.order_record);capabilities=read(run/'study/input_capabilities.json')
    exported=pd.read_csv(run/'study/input_lineage.csv').set_index('input_id')
    validate_package(run)
    archive=args.execution/'output'/result['artifacts']['astra']['path']
    quant=compare_quant(args.baseline_archive,archive)
    assert len(quant)==22 and all(c['byte_equal'] for c in quant)
    assert not config['experimental_context'].get('refresh_references',False)
    assert config['experimental_context'].get('science',{}).get('observation_policy',{}).get('mode','audit_only')=='audit_only'
    assert result['source_pin_sha256']==config['source_pin_sha256']
    with zipfile.ZipFile(args.g1_archive) as g1:
        original=read_json_zip(g1,'reproducibility/replay_config.json')
        snapshot=read_json_zip(g1,'study/user_input_snapshot.json')
        g1_hashes={key:hashlib.sha256(g1.read(original['inputs'][key])).hexdigest() for key in ['PR','PG','FASTA']}
    scientific={key:pd.read_csv(run/(key+'.csv')) for key in ['science/measurement_observations','science/observation_sites',
        'science/site_report_observations','science/localization_by_contrast','science/site_identity_audit','quant/comparisons']}
    observations=scientific['science/measurement_observations'];site_report=scientific['science/site_report_observations']
    identities=scientific['science/site_identity_audit'];loc=scientific['science/localization_by_contrast']
    rows=[]
    roles={'PR':'pr_matrix_path','PG':'pg_matrix_path','FASTA':'fasta_path',
           'DIANN':'diann_report_path','DIANN_SITE':'diann_site_report_path','CROSSWALK':'run_crosswalk_path','SEARCH_FASTA':'search_fasta_path'}
    for key,field in roles.items():
        path=order.get(field);runtime=config.get(field)
        packaged=run/saved['inputs'][key] if key in saved['inputs'] else None
        sha=digest(path) if path else None
        if path:
            assert packaged is not None and sha==digest(runtime)==digest(packaged)==exported.loc[key,'sha256']
            if key in g1_hashes:assert sha==g1_hashes[key]
        else:assert not runtime and packaged is None
        row={'input_role':key,'order_field':field,'actual_file':path,'sha256':sha,
             'stored':'verified_local_Order70' if path else 'missing_input',
             'dispatch':'local_config_to_engine_hash_verified; worker_boundary_separately_fixture_tested' if path else 'not_dispatched_missing_input',
             'parser':exported.loc[key,'consumer'] if path else 'not_run_missing_input',
             'matched_unmatched_conflict':'not_applicable_matrix_or_sequence_input' if path else 'not_evaluable_missing_input',
             'export_location':exported.loc[key,'export_location'],'disposition':exported.loc[key,'disposition'],
             'restriction':'production_Order88_current_DB_not_inspected'}
        if path and key in {'PR','PG'}:
            with Path(path).open() as handle:columns=next(csv.reader(handle,delimiter='\t'));n=sum(1 for _ in handle)
            row['input_rows']=n;row['schema_columns_json']=json.dumps(columns,ensure_ascii=False)
            row['restriction']+=';no_run_confidence_site_probability_or_q_columns' if not any('Confidence' in c or 'Probabilit' in c or 'Q.Value' in c for c in columns) else ''
        if key=='FASTA':row['restriction']+=';analysis_reference.fasta_is_derivative_not_another_uploaded_input;search_FASTA_identity_unverified'
        rows.append(row)
    version=(order.get('science') or {}).get('diann_version')
    rows.append({'input_role':'DIA-NN version','order_field':'analysis_context.science.diann_version','actual_file':None,'sha256':None,
                 'stored':version or 'not_recorded','dispatch':version or 'not_recorded','parser':'not_run_missing_input',
                 'matched_unmatched_conflict':'not_applicable','export_location':'study/user_input_snapshot.json',
                 'restriction':'no_version_inferred_from_filename_or_matrix'})
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (args.output/'INPUT_LINEAGE.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    if not config.get('diann_report_path'):
        assert observations.empty and scientific['science/observation_sites'].empty
        assert not capabilities['measured_localization_available'] and not capabilities['run_confidence_available']
        assert not loc.localized_eligible.any()
        assert pd.read_csv(run/'kinase/kinase_candidate_edges.csv',usecols=['localization_probability']).localization_probability.isna().all()
    validation={'scope':'actual_HIRcB_inputs_local_Order70_and_g1_Order88_archive; production_DB_not_inspected',
        'run_id':result['run_id'],'archive':str(archive),'archive_sha256':digest(archive),'g1_archive_sha256':digest(args.g1_archive),
        'g1_source_record_id':snapshot['source_record_id'],'local_order_id':order['id'],
        'source_pin_sha256':result['source_pin_sha256'],'observation_policy':'audit_only','input_hashes':g1_hashes,
        'capabilities':capabilities,'measurement_readiness':result['analysis_readiness']['measurement_evidence'],
        'report_match_counts':observations.match_status.value_counts().to_dict(),'report_rows':len(observations),'site_report_rows':len(site_report),
        'mapping_rows':len(identities),'mapping_status_counts':identities.mapping_status.value_counts().to_dict(),
        'localization_by_contrast_rows':len(loc),'localized_eligible':int(loc.localized_eligible.sum()),
        'quant_preservation':quant,'stage_reuse':result['provenance']['stage_reuse'],
        'real_report_validation':'not_run_missing_main_report_site_report_crosswalk_declared_version',
        'raw_MS_search':'not_performed','source_network_requests':read(args.execution/'reuse_validation.json')['network_attempts']}
    (args.output/'ACTUAL_VALIDATION.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:validation[key] for key in ['run_id','report_rows','mapping_rows','localized_eligible','source_network_requests']}))


def read_json_zip(archive,name):return json.loads(archive.read(name))


if __name__=='__main__':main()
