import json,hashlib,urllib.request,sys
from pathlib import Path
import pandas as pd
from ptm_shared.annotation_registry import digest
from ptm_shared.astra_package import validate_package,order_method_scores
from ptm_shared.effect_series import resolve_series
from ptm_shared.astra_evidence_catalog import EvidenceCatalog
if len(sys.argv)!=2:raise SystemExit('usage: validate_control_actual_package.py VALIDATION_DIRECTORY')
OUT=Path(sys.argv[1]);ROOT=OUT/'delivery/C05A_ACTUAL'
def read(p):return json.loads(p.read_text())
pointer=read(ROOT/'enrichment_free_current.json');base=ROOT/'enrichment_free_runs'/pointer['run_id']
excluded=OUT/'FIRST_RUN_NOT_ACCEPTED.json'
if excluded.is_file():assert pointer['run_id']!=read(excluded)['run_id'],'Corrected validation run is not yet published'
validate_package(base)
design=read(base/'study/study_design.json');snapshot=read(base/'study/user_input_snapshot.json');context=read(base/'study/study_context.json');policy=read(base/'study/control_comparison.json');saved=read(OUT/'UI_SAVED_ORDER.json');generation=pointer['run_id'].split('-')[0][1:];dispatch=read(OUT/f'DISPATCH_{generation}.json')
for source in [saved['analysis_context']['study_design'],dispatch['experimental_context']['study_design'],snapshot['original']['analysis_context']['study_design']]:
 for key in ['injections','materials','contrasts','conditions']:assert design[key]==source[key],key
assert policy['effective_policy']['strategy']=='shared_reference'
assert context['control_comparison']==dispatch['experimental_context']['control_comparison']
for field in ['biological_question','cell_type','treatment','time_points','special_conditions']:
 assert snapshot['original']['analysis_context'].get(field)==saved['analysis_context'].get(field)
assert snapshot['original']['report_options']['research_questions']==saved['report_options']['research_questions']
comp=pd.read_csv(base/'quant/comparisons.csv',float_precision='round_trip');conds={c['condition_id']:c for c in design['conditions']}
meta=comp[['contrast_id','target_condition_id','reference_condition_id','time_min','reference_time_min','pairing']].drop_duplicates()
assert len(meta)==len(design['contrasts'])
for c in design['contrasts']:
 r=meta.set_index('contrast_id').loc[c['contrast_id']]
 for k in ['target_condition_id','reference_condition_id','pairing']:assert r[k]==c[k]
 assert r.time_min==conds[c['target_condition_id']]['time']['minutes']
 assert r.reference_time_min==conds[c['reference_condition_id']]['time']['minutes']
assert comp.biological_p_value.isna().all() and comp.biological_q_value.isna().all()
series,lookup=resolve_series(design);temporal=pd.read_csv(base/'temporal/temporal_series.csv')
assert set(temporal.series_id)==set(series)
methods=pd.read_csv(base/'kinase/method_scores.csv',float_precision='round_trip');ordered,audit=order_method_scores(methods,design=design)
pd.testing.assert_frame_equal(methods,ordered,check_dtype=False,check_exact=True)
figures=[]
for entry in read(base/'figures/figure_legends.json'):
 if 'plotted_data' not in entry:continue
 assert entry['control_comparison_labels']==['공통 Control 기준']
 points=pd.read_csv(base/'figures'/entry['plotted_data'])
 indexed=meta.set_index('contrast_id')
 for row in points[['contrast_id','reference_condition_id','time_min']].drop_duplicates().itertuples():
  assert row.reference_condition_id==indexed.loc[row.contrast_id,'reference_condition_id']
  assert row.time_min==indexed.loc[row.contrast_id,'time_min']
 for _,group in points.groupby('plot_series_key',sort=False):assert group.time_min.is_monotonic_increasing
 figures.append({'figure':entry['figure_id'],'label':entry['control_comparison_labels'],
     'point_rows':len(points),'scope_and_numeric_time_order':True})
assert len(figures)==2
# All actual sources, including unselected and withheld/no-call rows, are indexed.
catalog=EvidenceCatalog(base);counts={name:int(meta['rows']) for name,meta in catalog.catalog['sources'].items()}
assert counts['quant/comparisons.csv']==len(comp)
not_selected=catalog.query({'source_table':'reader/cards.csv','selected_for_summary':False},page_size=1)
resolved=[]
assert not_selected['total_count']>0
if not_selected['items']:resolved=catalog.resolve([not_selected['items'][0]['evidence_id']])
no_call=catalog.query({'status':'no_call'},page_size=1)
assert no_call['total_count']>0
if no_call['items']:assert catalog.resolve([no_call['items'][0]['evidence_id']])[0]['source_row']
wire=json.load(urllib.request.urlopen('http://127.0.0.1:8027/api/orders/1/enrichment-free-evidence',timeout=120))
assert wire['run_id']==pointer['run_id']
sha=hashlib.sha256();size=0
with urllib.request.urlopen('http://127.0.0.1:8027/api/orders/1/enrichment-free-evidence?artifact=astra',timeout=120) as response:
 while True:
  block=response.read(2**20)
  if not block:break
  sha.update(block);size+=len(block)
assert sha.hexdigest()==pointer['artifacts']['astra']['sha256']==digest(ROOT/pointer['artifacts']['astra']['path'])
result={'passed':True,'run_id':pointer['run_id'],'archive_sha256':sha.hexdigest(),'download_bytes':size,'download_stored_second_copy':False,'trace_equal':['UI saved','API dispatch','worker design','execution snapshot','package','quant contrasts'],'policy':policy,'temporal_series':len(series),'points_per_series':{s:len(v['points']) for s,v in series.items()},'method_order':audit,'catalog_source_rows':counts,'unselected_catalog_rows':not_selected['total_count'],'no_call_catalog_rows':no_call['total_count'],'biological_pq':'not_computed','actual_time_matched_data':'unavailable','production':'not_verified'}
result['figures']=figures
(OUT/'PACKAGE_VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['policy','catalog_source_rows','method_order']},ensure_ascii=False))
