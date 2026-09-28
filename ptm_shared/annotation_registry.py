"""Checked registry metadata and public compatibility, independent of API/worker."""
import hashlib
import json
from pathlib import Path
import re

from .study_presets import HIRCB_SNAPSHOT

VERSION='annotation_registry.v2'
REQUIRED_COLUMNS={'enzyme','substrate','residue_type','residue_offset','modification','sources','references'}
HIRCB_AUDITS=['manual_primary_source_audit.tsv','pmid_16914728.json','pmid_42644392.json']


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


class RegistryError(ValueError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def adapted_metadata(metadata,sha):
    if sha==HIRCB_SNAPSHOT and 'taxonomy_ids' not in metadata:
        metadata={**metadata,'schema_version':VERSION,'adapter_version':'hircb_legacy_snapshot_metadata.v1',
            'database':'OmniPath enzyme-substrate','source':'OmniPath frozen rat endpoint',
            'version':metadata.get('retrieved_utc','unknown'),'taxonomy_ids':['10116'],
            'ptm_types':['phosphorylation'],'orthology_translation':True,'source_taxonomy_ids':['9606'],
            'id_system':'UniProt_accession_and_gene_symbol','required_files':HIRCB_AUDITS,
            'curation_policy':'hircb_snapshot_audit.v1','accession_aliases':{'A4GW50':'Stk38l'},
            'coverage_notes':'Rat-translated substrate annotation; human INSR P06213 in Rat_hir FASTA is a separate coverage category, not rat coverage.'}
    return metadata


def inspect_snapshot(root,sha,taxonomy_id=None,ptm_type=None):
    if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):
        raise RegistryError('metadata_invalid','A valid frozen snapshot digest is required')
    directory=Path(root)/sha
    snapshot=directory/'snapshot.tsv';mpath=directory/'annotation_metadata.json'
    if not snapshot.is_file() or not mpath.is_file():raise RegistryError('metadata_invalid','Snapshot registration is incomplete')
    if digest(snapshot)!=sha:raise RegistryError('checksum_invalid','Registered snapshot checksum failed')
    try:metadata=json.loads(mpath.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError):raise RegistryError('metadata_invalid','Snapshot metadata cannot be read') from None
    if not isinstance(metadata,dict) or metadata.get('database_sha256')!=sha:
        raise RegistryError('metadata_invalid','Snapshot metadata digest does not match')
    metadata=adapted_metadata(metadata,sha)
    required=metadata.get('required_files',[])
    if not isinstance(required,list):raise RegistryError('metadata_invalid','Invalid required file manifest')
    for name in required:
        if not isinstance(name,str) or Path(name).name!=name or not (directory/name).is_file():
            raise RegistryError('metadata_invalid','Required mapping or audit file is absent')
    for name,expected in metadata.get('file_sha256',{}).items():
        if Path(name).name!=name or not (directory/name).is_file() or digest(directory/name)!=expected:
            raise RegistryError('checksum_invalid','Required mapping or audit checksum failed')
    with snapshot.open(encoding='utf-8-sig') as f:columns=set(f.readline().rstrip('\r\n').split('\t'))
    if not REQUIRED_COLUMNS.issubset(columns):raise RegistryError('metadata_invalid','Unsupported annotation table schema')
    taxa=metadata.get('taxonomy_ids',[]);ptms=metadata.get('ptm_types',[])
    if not isinstance(taxa,list) or not isinstance(ptms,list):raise RegistryError('metadata_invalid','Invalid compatibility metadata')
    supported=bool(taxa and ptms and metadata.get('id_system'))
    status='ready' if supported else 'compatibility_unknown'
    reasons=[] if supported else ['legacy_metadata_does_not_establish_compatibility']
    normalized_ptm='phosphorylation' if ptm_type=='phospho' else ptm_type
    if taxonomy_id is not None and str(taxonomy_id) not in {str(t) for t in taxa}:
        status='incompatible';reasons.append('taxonomy_not_supported')
    if normalized_ptm and normalized_ptm not in ptms:status='incompatible';reasons.append('ptm_not_supported')
    public={key:metadata.get(key) for key in ['database','source','version','retrieved_utc','taxonomy_ids','ptm_types',
        'orthology_translation','source_taxonomy_ids','id_system','required_files','coverage_notes','adapter_version']}
    public.update(sha256=sha,status=status,reasons=reasons,metadata_sha256=digest(mpath),schema_version=VERSION)
    return {**public,'metadata':metadata,'snapshot_path':str(snapshot),'reference_dir':str(directory)}


def public_registry(root,taxonomy_id=None,ptm_type=None):
    records=[]
    for directory in sorted(Path(root).glob('*')):
        if not directory.is_dir() or directory.name.startswith('.'):continue
        try:
            item=inspect_snapshot(root,directory.name,taxonomy_id,ptm_type)
            records.append({k:v for k,v in item.items() if k not in {'metadata','snapshot_path','reference_dir'}})
        except RegistryError as e:
            records.append({'sha256':directory.name if re.fullmatch('[0-9a-f]{64}',directory.name) else None,
                            'status':e.code,'reasons':[e.code]})
    return {'status':'ready' if any(r['status']=='ready' for r in records) else 'empty_registry' if not records else 'no_compatible_snapshot',
            'snapshots':records,'schema_version':VERSION}


def require_compatible(root,sha,taxonomy_id,ptm_type):
    item=inspect_snapshot(root,sha,taxonomy_id,ptm_type)
    if item['status']!='ready':raise RegistryError('incompatible_annotation','Snapshot compatibility is not established for this organism/PTM')
    return item
