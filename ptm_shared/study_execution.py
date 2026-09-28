"""Shared design preview, save and execution rules for API and worker."""
from .study_design import PROFILE,resolve_study_design,require_resolved
from .study_presets import HIRCB_PRESET,HIRCB_SNAPSHOT,legacy_manifest
from .contrast_quantification import PTM_CODES
from .annotation_registry import require_compatible


def resolve_context(context,sample_config,*,taxonomy_id=None,species=None,ptm_type='phosphorylation'):
    context=dict(context or {})
    context['study_design']=resolve_study_design(context,sample_config,taxonomy_id=taxonomy_id,species=species,ptm_type=ptm_type)
    return context


def validate_execution(context,ptm_type,taxonomy_id,options=None,registry_root=None,pr_columns=None,pg_columns=None):
    design=require_resolved(context.get('study_design') or {},pr_columns,pg_columns)
    if str(design['study'].get('taxonomy_id'))!=str(taxonomy_id) or design['study'].get('ptm_type')!=ptm_type:
        raise ValueError('Canonical study organism/PTM conflicts with execution settings')
    if ptm_type not in PTM_CODES:raise ValueError('Generic quantification does not support this PTM code')
    if context.get('enrichment_status')!='enrichment_free':raise ValueError('Declare enrichment-free acquisition for the generic primary-A profile')
    if (options or {}).get('quick_analysis') or (options or {}).get('mode','full')!='full':raise ValueError('Generic primary A requires full PR/PG input and full protein selection')
    if context.get('normalization_policy') not in {'already_normalized.v1','legacy_median.v1'}:raise ValueError('Select an explicit additional normalization policy')
    preset=context.get('analysis_preset')
    if preset not in {None,'',HIRCB_PRESET}:raise ValueError('Unsupported analysis preset')
    annotation_mode=context.get('annotation_mode')
    if annotation_mode not in {'required','quantification_only'}:raise ValueError('Choose required kinase annotation or quantification_only')
    sha=context.get('annotation_snapshot_sha256');registered=None
    if preset==HIRCB_PRESET:
        if str(taxonomy_id)!='10116' or ptm_type not in {'phosphorylation','phospho'}:raise ValueError('HIRc-B reference preset requires rat phosphorylation')
        if sha!=HIRCB_SNAPSHOT or annotation_mode!='required':raise ValueError('HIRc-B reference preset requires its fixed validated snapshot')
        if context['normalization_policy']!='already_normalized.v1':raise ValueError('HIRc-B reference preset requires no additional scaling')
        legacy_manifest(design)
    if annotation_mode=='required':
        if ptm_type not in {'phosphorylation','phospho'}:raise ValueError('Kinase footprint supports phosphorylation only; select quantification_only for this PTM')
        if registry_root is not None:registered=require_compatible(registry_root,sha,taxonomy_id,ptm_type)
        elif not sha:raise ValueError('Required annotation snapshot digest is missing')
    return registered
