"""C05A local services; real transport/quant/series projection/reader/publication.
Annotation, discovery, method, scientific-inference and temporal numerical
observations are supplied from a hash-checked archive with the same design.
Literature retrieval is explicitly unavailable; no prior approval is rebound.
"""
import os,json,sys,shutil,ctypes,uuid
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
if len(sys.argv)!=3 or sys.argv[1] not in {'api','worker'}:raise SystemExit('usage: validate_control_actual_runtime.py api|worker VALIDATION_DIRECTORY')
OUT=Path(sys.argv[2]).resolve();os.umask(0o077)
runtime=json.loads((OUT/'RUNTIME_ENV_PRIVATE.json').read_text())
from urllib.parse import urlparse
assert all(urlparse(runtime[k]).hostname=='127.0.0.1' for k in ['DATABASE_URL','REDIS_URL','CELERY_BROKER_URL','CELERY_RESULT_BACKEND']), 'Local isolated services only'
assert Path(runtime['OUTPUT_DIR']).resolve()==OUT/'delivery'
os.environ.update(runtime)
_original_copy=shutil.copyfile
_lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
def clone(src,dst,*,follow_symlinks=True):
 src,dst=Path(src),Path(dst);tmp=dst.with_name('.clone-'+uuid.uuid4().hex)
 if _lib.clonefile(os.fsencode(src),os.fsencode(tmp),0)==0:os.replace(tmp,dst);return str(dst)
 return _original_copy(src,dst,follow_symlinks=follow_symlinks)
shutil.copyfile=clone
if sys.argv[1]=='api':
 from fastapi import FastAPI
 from app.api.orders import router
 import uvicorn
 app=FastAPI();app.include_router(router,prefix='/api')
 uvicorn.run(app,host='127.0.0.1',port=8027,log_level='info')
else:
 import pandas as pd
 from contextlib import ExitStack
 from ptm_shared import astra_package as package,astra_evidence_v6 as engine
 from ptm_shared.astra_evidence_catalog import read_source
 from ptm_shared.annotation_registry import digest
 from ptm_shared.generic_workflow import object_hash
 from ptm_shared import enrichment_free_workflow as workflow
 from ptm_shared import astra_literature as lit
 req=json.loads((OUT/'PREDECLARED.json').read_text());source=Path(req['baseline']);cfg=json.loads((source/'reproducibility/replay_config.json').read_text());hashes=json.loads((OUT/'SOURCE_HASHES.json').read_text())
 assert all(digest(source/name)==sha for name,sha in hashes.items())
 regression=json.loads((OUT/'QUANT_REGRESSION.json').read_text());assert len(regression)==2
 dictionary=json.loads((source/'reproducibility/data_dictionary.json').read_text())
 names=[n for n in dictionary if n.startswith(('science/','kinase/','evidence/','references/','temporal/')) or n=='quant/site_mapping.csv']
 frozen={n[:-4]:read_source(source,n,dictionary[n]) for n in names}
 readiness=json.loads((source/'evidence/readiness.json').read_text());motif=json.loads((source/'methods/motif.json').read_text());sources=json.loads((source/'references/source_pin.json').read_text());counts=dict(zip(frozen['evidence/coverage_funnel'].metric,frozen['evidence/coverage_funnel']['count']))
 original_quant=package.quant_cached
 def quant(inputs,design,context,root,fingerprint,**kwargs):
  expected=json.loads((OUT/'RESOLVED_CONTEXT.json').read_text())['study_design']
  def projection(d):return {k:[{f:r.get(f) for f in fields} for r in d[k]] for k,fields in {'injections':['injection_id','condition_id','input_column','material_id','technical_injection_id'],'materials':['material_id','biological_unit_id','pair_id'],'contrasts':['contrast_id','target_condition_id','reference_condition_id','pairing']}.items()}
  assert projection(design)==projection(expected),'Worker numeric mapping differs from verified actual design'
  for key,record in json.loads((OUT/'ACTUAL_INPUT.json').read_text())['input_files'].items():assert digest(inputs[key])==record['sha256']
  value=original_quant(inputs,design,context,root,fingerprint,**kwargs)
  with (OUT/'WORKER_QUANT.jsonl').open('a') as f:f.write(json.dumps({'fingerprint':fingerprint,'reuse':value[1],'contrast_ids':[r['contrast_id'] for r in design['contrasts']],'actual_calculator':'astra_evidence_v6.calculate','tables':{k:len(v) for k,v in value[0][0].items()}})+'\n')
  return value
 def science(inputs,design,context,_sources,*,quant,alternative,snapshot,**kwargs):
  if (OUT/'FAIL_NEXT').exists():raise RuntimeError('C05A deliberate prepublication failure; no scientific result published')
  tables,norm,_=quant;alt,altnorm,_=alternative
  tables['site_mapping']=frozen['quant/site_mapping']
  scientific={k:v.copy(deep=True) for k,v in frozen.items() if k!='quant/site_mapping'}
  scientific.update({'quant/'+k:v for k,v in tables.items()})
  discovery={k.split('/',1)[1]:v for k,v in scientific.items() if k.startswith('kinase/')}
  # Same actual single-reference numeric design: reuse hash-bound temporal
  # observations, recomputing only the C03 series/point metadata projection.
  from ptm_shared.effect_series import resolve_series,POINT_COLUMNS
  from ptm_shared.evidence_temporal import effect_intervals
  scopes,lookup=resolve_series(design)
  assert set(scientific['temporal/temporal_series'].series_id)==set(scopes)
  for sid,scope in scopes.items():
   old=scientific['temporal/temporal_series'].set_index('series_id').loc[sid]
   assert set(str(old.contrast_ids).split(';'))==set(scope['contrast_ids'])
   assert old.reference_condition_id==scope['reference_condition_id']
  scientific['temporal/temporal_series']=pd.DataFrame([{**v,'contrast_ids':';'.join(v['contrast_ids'])} for v in scopes.values()],columns=scientific['temporal/temporal_series'].columns)
  scientific['temporal/effect_series_points']=pd.DataFrame([r for v in scopes.values() for r in v['points']],columns=POINT_COLUMNS)
  scientific['temporal/effect_interval_contrasts']=effect_intervals(tables,design)
  _,reference=engine.normalized_reference(inputs,context)
  context={**context,'_runtime_reference':reference,'_runtime_inputs':inputs}
  read=deepcopy(readiness)
  read['c05a_validation']={'actual_input':True,'frozen_stages':['annotation','kinase_discovery','native_method_scores','scientific_inference','temporal_numerical_observations'],'new_native_method_calls':0,'new_biological_tests':0,'quantification':'real_engine_and_content_checked_cache','temporal_reader':'current_series_point_projection_card_reader_figures_on_saved_real_observations','production_validation':False}
  scientific.update(engine.project_card_inputs(scientific,inputs,design,context,snapshot))
  scientific.update(engine.build_reader_tables(scientific,design,snapshot))
  read['reader']={'status':'generated','version':'astra_reader.v1','selected_findings':len(scientific['reader/findings']),'literature_comparison':'not_performed'}
  (OUT/'WORKER_SCIENCE.json').write_text(json.dumps({'tables':{k:len(v) for k,v in scientific.items()},'design':design,'snapshot':snapshot,'boundary':read['c05a_validation']},ensure_ascii=False,indent=2))
  return scientific,norm,altnorm,read,motif,counts
 class DisabledRetriever:
  def __init__(self,selection):self.collection_names=[c['chromadb_name'] for c in selection['collections'] if c.get('chromadb_name')]
  def query(self,*a,**kw):raise RuntimeError('C05A validation: new RAG retrieval deliberately disabled; prior approvals not rebound')
 original_collect=lit.collect
 def collect(tables,snapshot,literature,**kwargs):
  kwargs['retriever']=DisabledRetriever(literature);kwargs['llm']=None
  return original_collect(tables,snapshot,literature,**kwargs)
 original_primary=workflow.run_primary_analysis
 def primary(order_id,config,output_dir,**kwargs):
  gen=config['run_generation'];(OUT/f'DISPATCH_{gen}.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
  result=original_primary(order_id,config,output_dir,**kwargs)
  (OUT/f'BUILDER_RESULT_{gen}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str));return result
 with ExitStack() as stack:
  stack.enter_context(patch.object(package,'quant_cached',side_effect=quant));stack.enter_context(patch.object(package,'mapped_sites',return_value=(frozen['quant/site_mapping'],None,{})));stack.enter_context(patch.object(package,'resolve_sources',return_value=sources));stack.enter_context(patch.object(package,'compute_science',side_effect=science));stack.enter_context(patch.object(lit,'collect',side_effect=collect));stack.enter_context(patch.object(workflow,'run_primary_analysis',side_effect=primary))
  for name in ['ptm_shared.astra_literature._runtime','ptm_shared.astra_literature_review.execute_review','ptm_shared.official_method_tracks.execute_tracks','ptm_shared.kinase_specificity.score_sites','common.llm_client.LLMClient.generate']:
   stack.enter_context(patch(name,side_effect=AssertionError('Forbidden new external or native execution: '+name)))
  from celery_app import app
  import preprocessing.tasks
  (OUT/'WORKER_READY').write_text('hash-checked frozen stages loaded')
  app.worker_main(['worker','--pool=solo','--concurrency=1','--queues=preprocessing','--loglevel=INFO','--without-gossip','--without-mingle','--without-heartbeat'])
