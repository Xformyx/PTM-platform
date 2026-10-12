"""API resource hand-off tests; synthetic bytes do not establish scorer parity."""
import copy
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from app.services.astra_input_capture import _attach_registered_specificity, prepare_astra_inputs
from app.api.orders import _attach_enrichment_free_profile
from ptm_shared.annotation_registry import digest
from ptm_shared.tests.test_astra_science import config


def registration(tmp_path, monkeypatch, context):
    root=tmp_path/'registered';root.mkdir()
    (root/'matrix.h5').write_bytes(b'synthetic hand-off matrix')
    (root/'background.h5').write_bytes(b'synthetic hand-off background')
    resource={'adapter':'phosx_official.v1','local_use_permission':'permitted','derived_export_permission':'permitted',
              'redistribution_status':'not_permitted','matrix_file':'matrix.h5','background_file':'background.h5',
              'matrix_sha256':digest(root/'matrix.h5'),'background_sha256':digest(root/'background.h5')}
    path=root/'manifest.json';path.write_text(json.dumps(resource))
    settings=SimpleNamespace(ASTRA_SPECIFICITY_MANIFEST_PATH=str(path),ASTRA_SPECIFICITY_MANIFEST_SHA256=digest(path),
                             OUTPUT_DIR=str(tmp_path/'output'),REFERENCE_DIR=str(tmp_path/'reference'))
    monkeypatch.setattr('app.config.get_settings',lambda:settings)
    monkeypatch.setattr('app.api.orders.get_settings',lambda:settings)
    context=copy.deepcopy(context);context['quantitation_export_mode']='astra_analysis.v6'
    order=SimpleNamespace(id=1,order_code='registered',analysis_context=context,specificity_manifest_path=None,
                          rag_collections=[],ptm_type='phosphorylation',species='human',
                          pr_matrix_path=None,pg_matrix_path=None,fasta_path=None)
    return order,settings,path,resource


def test_registered_resource_reaches_snapshot_and_existing_dispatch(config,tmp_path,monkeypatch):
    import asyncio
    class EmptyDB:
        async def execute(self,query):return self
        def scalars(self):return self
        def all(self):return []
    order,settings,path,resource=registration(tmp_path,monkeypatch,config['experimental_context'])
    order.pr_matrix_path=config['pr_matrix_path'];order.pg_matrix_path=config['pg_matrix_path'];order.fasta_path=config['fasta_path']
    snapshot,pin=asyncio.run(prepare_astra_inputs(order,EmptyDB(),settings.REFERENCE_DIR))
    target=Path(order.specificity_manifest_path)
    assert digest(target)==digest(path)
    assert digest(target.parent/resource['matrix_file'])==resource['matrix_sha256']
    assert snapshot['original']['input_files']['specificity_manifest_path']['status']=='provided'
    order.sample_config=json.loads(Path(config['pr_matrix_path']).with_name('fixture.json').read_text())['sample_config']
    order.analysis_options={}
    dispatch={k:getattr(order,k) for k in ('pr_matrix_path','pg_matrix_path','fasta_path')}
    dispatch['species_tax_id']='9606'
    _attach_enrichment_free_profile(order,dispatch)
    assert dispatch['specificity_manifest_path']==str(target)
    method=dispatch['experimental_context']['science']['official_methods']['PhosX']
    assert set(method['contrast_ids'])=={r['contrast_id'] for r in order.analysis_context['study_design']['contrasts']}
    assert method['permutations']==10000 and method['seed']==1729
    # Stable persisted path/config survive a later server setting change.
    frozen=copy.deepcopy(order.analysis_context);settings.ASTRA_SPECIFICITY_MANIFEST_SHA256='changed'
    _attach_registered_specificity(order,settings.REFERENCE_DIR)
    assert order.analysis_context==frozen and order.specificity_manifest_path==str(target)


def test_registration_never_overrides_explicit_scope_or_legacy(config,tmp_path,monkeypatch):
    order,settings,path,_=registration(tmp_path,monkeypatch,config['experimental_context'])
    order.analysis_context['quantitation_export_mode']='astra_analysis.v5'
    _attach_registered_specificity(order,settings.REFERENCE_DIR)
    assert order.specificity_manifest_path is None
    order.analysis_context['quantitation_export_mode']='astra_analysis.v6'
    selected=[order.analysis_context['study_design']['contrasts'][1]['contrast_id']]
    order.analysis_context.setdefault('science',{})['official_methods']={'PhosX':{'contrast_ids':selected,'seed':32}}
    _attach_registered_specificity(order,settings.REFERENCE_DIR)
    actual=order.analysis_context['science']['official_methods']['PhosX']
    assert actual['contrast_ids']==selected and actual['seed']==32


@pytest.mark.parametrize('damage',['manifest','matrix','permission'])
def test_invalid_registration_is_not_dispatched(config,tmp_path,monkeypatch,damage):
    order,settings,path,resource=registration(tmp_path,monkeypatch,config['experimental_context'])
    if damage=='manifest':settings.ASTRA_SPECIFICITY_MANIFEST_SHA256='wrong'
    elif damage=='matrix':(path.parent/'matrix.h5').write_bytes(b'changed')
    else:
        resource['local_use_permission']='unknown';path.write_text(json.dumps(resource));settings.ASTRA_SPECIFICITY_MANIFEST_SHA256=digest(path)
    with pytest.raises(ValueError,match='registered_specificity'):_attach_registered_specificity(order,settings.REFERENCE_DIR)
    assert order.specificity_manifest_path is None
