"""Declared local matrix adapter, separate from curated relations and heuristic motifs.

No atlas is bundled. A manifest cannot self-certify calibration or official parity.
The generic scorer accepts explicit log2-additive or multiplicative matrix semantics;
unsupported priming/terminal rules degrade rather than inventing scores.
"""
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id

VERSION='experimental_specificity_adapter.v1'
COLUMNS=['specificity_id','site_id','form_id','measurement_group_id','candidate_id','kinase_accession','kinase_taxon',
 'reference_assay_taxon','substrate_taxon','resource_id','matrix_sha256','background_sha256','sequence_window',
 'score','percentile','percentile_scale','rank','status','restriction_reasons','edge_type','official_parity_status']
REQUIRED=['resource_id','resource_version','publication_doi','source_url','license_identifier','redistribution_status',
 'assay_taxon','supported_center_residues','window_offsets','alphabet','matrix_scale','pseudocount_policy',
 'terminal_policy','priming_modification_policy','matrix_sha256','background_sha256','matrix_file','background_file']


def load_resource(manifest_path):
    path=Path(manifest_path);meta=json.loads(path.read_text())
    if any(k not in meta for k in REQUIRED):raise ValueError('specificity_resource_metadata_incomplete')
    if meta['license_identifier'] in (None,'unknown','unresolved'):return None,{'status':'license_unresolved'}
    files=[]
    for field in ('matrix','background'):
        p=(path.parent/meta[field+'_file']).resolve()
        if not p.is_relative_to(path.parent.resolve()) or not p.is_file() or digest(p)!=meta[field+'_sha256']:
            raise ValueError('specificity_resource_checksum_invalid:'+field)
        files.append(p)
    if meta['matrix_scale'] not in {'log2_additive','linear_product'} or meta['pseudocount_policy']!='none':
        raise ValueError('specificity_score_semantics_unsupported')
    if meta['terminal_policy']!='reject' or meta['priming_modification_policy']!='reject':
        raise ValueError('specificity_terminal_or_priming_unsupported')
    matrices=json.loads(files[0].read_text());background=json.loads(files[1].read_text())
    return (meta,matrices,background),{**meta,'manifest_sha256':digest(path),'adapter_version':VERSION,
        'status':'local_resource_available','official_parity_status':'official_parity_not_verified',
        'scope':'declared_matrix_adapter_not_PhosX_or_Kinase_Library_full_algorithm'}


def score_sites(sites, entries, manifest_path=None):
    if not manifest_path:return pd.DataFrame(columns=COLUMNS),{'status':'resource_unavailable','official_parity_status':'official_parity_not_verified'}
    resource,metadata=load_resource(manifest_path)
    if resource is None:return pd.DataFrame(columns=COLUMNS),metadata
    meta,matrices,background=resource;fasta={r['accession']:r for r in entries};rows=[]
    for site in sites.to_dict('records'):
        protein=fasta[site['input_accession']];seq=protein['sequence'];pos=int(site['input_position'])-1
        offsets=meta['window_offsets'];window=''.join(seq[pos+o] if 0<=pos+o<len(seq) else '_' for o in offsets)
        for kinase,matrix in sorted(matrices.items()):
            status='scored';reason=[];score=None;percentile=None
            if site.get('form_modification_count',1)>1:reason.append('priming_or_multisite_context_unsupported')
            if seq[pos] not in meta['supported_center_residues']:reason.append('unsupported_center_residue')
            if '_' in window:reason.append('terminal_window_unsupported')
            if any(a not in meta['alphabet'] for a in window):reason.append('unsupported_residue')
            if not reason:
                try:values=[float(matrix['weights'][str(o)][a]) for o,a in zip(offsets,window)]
                except (KeyError,TypeError,ValueError):reason.append('matrix_cell_unavailable');values=[]
                if not reason and (not all(math.isfinite(v) for v in values) or meta['matrix_scale']=='linear_product' and any(v<0 for v in values)):
                    reason.append('invalid_matrix_value')
                if not reason:
                    score=sum(values) if meta['matrix_scale']=='log2_additive' else math.prod(values)
                    bg=np.asarray(background.get(kinase,[]),float)
                    if len(bg) and np.isfinite(bg).all():percentile=float(np.mean(bg<=score)*100)
            if reason:status='not_evaluable'
            candidate=stable_id('specificity_candidate',[matrix.get('kinase_taxon'),kinase])
            rows.append({'specificity_id':stable_id('specificity',[site['site_id'],site['form_id'],kinase,meta['matrix_sha256'],meta['background_sha256']]),
                **{k:site[k] for k in ('site_id','form_id','measurement_group_id','substrate_taxon')},'candidate_id':candidate,
                'kinase_accession':kinase,'kinase_taxon':matrix.get('kinase_taxon'),'reference_assay_taxon':matrix.get('assay_taxon',meta['assay_taxon']),
                'resource_id':meta['resource_id'],'matrix_sha256':meta['matrix_sha256'],'background_sha256':meta['background_sha256'],
                'sequence_window':window,'score':score,'percentile':percentile,'percentile_scale':'0_to_100_reference_background',
                'rank':None,'status':status,'restriction_reasons':';'.join(reason),'edge_type':'experimental_specificity_prediction',
                'official_parity_status':'official_parity_not_verified'})
    frame=pd.DataFrame(rows,columns=COLUMNS)
    if len(frame):frame['rank']=frame.groupby(['form_id','site_id']).score.rank(method='min',ascending=False)
    return frame,metadata
