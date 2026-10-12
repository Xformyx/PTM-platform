"""Freeze selected research inputs and the actual literature inventory at dispatch."""
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4
from sqlalchemy import select

from app.models.rag_collection import RagCollection, RagDocument
from ptm_shared.astra_inputs import capture_order


def _attach_registered_specificity(order, reference_root):
    """Connect an explicitly configured local resource to the existing Order field.

    No scoring or resource acquisition occurs here. Content-addressed copies are
    shared by API and worker; an uploaded/persisted manifest always takes priority.
    """
    from copy import deepcopy
    from app.config import get_settings
    from ptm_shared.annotation_registry import digest
    from ptm_shared.contrast_quantification import ContrastEstimator
    from ptm_shared.official_specificity import PHOSX_VERSION, PHOSX_COMMIT
    settings = get_settings()
    context = deepcopy(order.analysis_context or {})
    configured = getattr(settings, 'ASTRA_SPECIFICITY_MANIFEST_PATH', '')
    if (not configured or getattr(order, 'specificity_manifest_path', None) or
            context.get('quantitation_export_mode') != 'astra_analysis.v6'):
        return
    design = context.get('study_design') or {}
    if design.get('study', {}).get('ptm_type') not in {'phosphorylation', 'phospho'}:
        return
    path = Path(configured)
    expected = getattr(settings, 'ASTRA_SPECIFICITY_MANIFEST_SHA256', '')
    if not expected or not path.is_file() or digest(path) != expected:
        raise ValueError('registered_specificity_manifest_checksum_mismatch')
    resource = json.loads(path.read_text())
    if (resource.get('adapter') != 'phosx_official.v1' or
            resource.get('local_use_permission') != 'permitted' or
            resource.get('derived_export_permission') != 'permitted'):
        raise ValueError('registered_specificity_requires_official_adapter_and_recorded_permissions')
    destination = Path(reference_root) / 'specificity_objects' / expected
    files = [(path, Path(path.name), expected)]
    for name in ('matrix', 'background'):
        relative = Path(resource[name + '_file'])
        source = path.parent / relative
        if (relative.is_absolute() or '..' in relative.parts or relative == Path(path.name) or
                not source.is_file() or digest(source) != resource[name + '_sha256']):
            raise ValueError('registered_specificity_resource_checksum_mismatch:' + name)
        files.append((source, relative, resource[name + '_sha256']))
    for source, relative, sha in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name('.' + target.name + '-' + uuid4().hex)
            shutil.copyfile(source, temporary)
            if digest(temporary) != sha:
                raise ValueError('registered_specificity_changed_during_capture')
            temporary.replace(target)
        if digest(target) != sha:
            raise ValueError('registered_specificity_stored_checksum_mismatch')
    estimator = ContrastEstimator(design)
    metadata = [estimator.metadata(c) for c in design['contrasts']]
    metadata.sort(key=lambda r: (r['arm_id'], r['reference_condition_id'], r['pairing'],
                                r['time_min'] is None, r['time_min'] or 0, r['contrast_id']))
    science = context.setdefault('science', {})
    method = science.setdefault('official_methods', {}).setdefault('PhosX', {})
    method.setdefault('contrast_ids', [r['contrast_id'] for r in metadata])
    method.setdefault('permutations', 10000)
    method.setdefault('seed', 1729)
    science['resource_registration'] = {
        'source': 'configured_server_resource', 'manifest_sha256': expected,
        'matrix_sha256': resource['matrix_sha256'], 'background_sha256': resource['background_sha256'],
        'method_version': PHOSX_VERSION, 'method_commit': PHOSX_COMMIT,
        'scope_policy': 'declared_contrasts_existing_scope_preserved.v1',
    }
    order.specificity_manifest_path = str(destination / path.name)
    order.analysis_context = context


async def prepare_astra_inputs(order, db, reference_root):
    _attach_registered_specificity(order, reference_root)
    snapshot=capture_order(order)
    context=order.analysis_context or {}
    attachment_hashes=sorted(r.get('sha256','') for r in context.get('research_attachment_records',[]))
    prior=context.get('astra_literature_pin')
    if prior and prior.get('requested_ids')!=order.rag_collections:prior=None
    if prior is None and not context.get('refresh_references',False):
        from app.config import get_settings
        current=Path(get_settings().OUTPUT_DIR)/order.order_code/'enrichment_free_current.json'
        if current.is_file():
            recorded=json.loads(current.read_text())
            selected=recorded.get('study_preview',{}).get('snapshot',{}).get('original',{}).get('rag_collections','not_recorded')
            if selected==order.rag_collections:prior=recorded.get('literature_pin')
    if prior and prior.get('research_attachment_hashes',[])!=attachment_hashes:prior=None
    if prior is not None and not context.get('refresh_references',False):
        return snapshot, prior
    selection=order.rag_collections
    query=select(RagCollection).order_by(RagCollection.id)
    query=query.where(RagCollection.is_active.is_(True)) if selection is None else query.where(RagCollection.id.in_(selection))
    collections=(await db.execute(query)).scalars().all()
    pin={'schema_version':'selected_literature_pin.v1','selection':'all_active' if selection is None else 'explicit',
         'requested_ids':selection,'collections':[],'documents':[],'research_attachment_hashes':attachment_hashes,
         'content_policy':'include_only_recorded_redistribution_permission; otherwise metadata and reason'}
    permissions=context.get('literature_content_permissions',{})
    for collection in collections:
        pin['collections'].append({'id':collection.id,'name':collection.name,'version':str(collection.updated_at),
                                   'description':collection.description,
                                   'chromadb_name':getattr(collection,'chromadb_name',None),
                                   'version_scope':'catalog_updated_at'})
        docs=(await db.execute(select(RagDocument).where(RagDocument.collection_id==collection.id).order_by(RagDocument.id))).scalars().all()
        for doc in docs:
            path=Path(doc.file_path)
            item={'document_id':doc.id,'collection_id':collection.id,'filename':doc.filename,'title':None,
                  'PMID':None,'DOI':None,'bibliography_status':'lookup_required_not_in_source_catalog',
                  'content_status':'metadata_only','reason':'redistribution_permission_not_recorded',
                  'sha256':None,'package_file':None,'source_status':doc.status}
            if not path.is_file():item.update(content_status='unavailable',reason='stored_file_unavailable')
            elif permissions.get(str(doc.id)) is True:
                sha=hashlib.sha256(path.read_bytes()).hexdigest();target=Path(reference_root)/'literature_objects'/sha
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():
                    temp=target.with_name('.'+sha+'-'+uuid4().hex);shutil.copyfile(path,temp)
                    if hashlib.sha256(temp.read_bytes()).hexdigest()!=sha:raise ValueError('Literature changed while pinning')
                    temp.replace(target)
                item.update(content_status='full_text_included',reason=None,sha256=sha,package_file='references/documents/'+sha+'.'+doc.file_type)
            if path.is_file() and item['sha256'] is None:
                from ptm_shared.annotation_registry import digest
                item['sha256']=digest(path)
            item['evidence_export_permission']='permitted' if permissions.get(str(doc.id)) is True else 'unknown'
            item['internal_search_status']='indexed_catalog_record' if doc.status=='indexed' else doc.status
            pin['documents'].append(item)
    found={c['id'] for c in pin['collections']}
    pin['unavailable_selected_ids']=[] if selection is None else sorted(set(selection)-found)
    for role,value in [('uploaded_config',getattr(order,'config_xlsx_path',None)),('uploaded_protein_list',(getattr(order,'analysis_options',None) or {}).get('protein_list_path'))]:
        if not value:continue
        path=Path(value);item={'document_id':role,'filename':path.name,'role':'user_uploaded_supporting_research_input','content_status':'unavailable','reason':'stored_file_unavailable'}
        if path.is_file():
            sha=hashlib.sha256(path.read_bytes()).hexdigest();target=Path(reference_root)/'literature_objects'/sha
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():shutil.copyfile(path,target)
            if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('Supporting research input changed while pinning')
            item.update(content_status='full_text_included',reason=None,sha256=sha,package_file='study/supporting_inputs/'+sha+path.suffix)
        pin['documents'].append(item)
    for record in context.get('research_attachment_records',[]):
        # Order inputs are the only permitted upload scope; raw paths are absent from export.
        path=Path(record.get('stored_path','')).resolve()
        scope=Path(order.pr_matrix_path or order.pg_matrix_path).resolve().parent/'research_attachments'
        if not path.is_relative_to(scope) or not path.is_file():raise ValueError('Research attachment is outside this order upload scope or missing')
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=record.get('sha256'):raise ValueError('Uploaded research attachment checksum mismatch')
        target=Path(reference_root)/'literature_objects'/sha;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copyfile(path,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('Research attachment changed while pinning')
        pin['documents'].append({'document_id':'upload_'+sha,'filename':record.get('filename',path.name),
            'role':'user_supplied_research_attachment','content_status':'full_text_included','sha256':sha,
            'package_file':'references/documents/'+sha+path.suffix,'content_review_status':'provided_not_compared',
            'bibliography_status':'identifier_lookup_required','PMID':None,'DOI':None})
    return snapshot,pin
