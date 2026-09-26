"""Explicit primary-A profile and content-addressed frozen annotation registry."""
import json
from pathlib import Path
import re

from .report_compatible_quantification import samples_from_manifest
from .report_compatible_extensions import file_digest

PROFILE = 'enrichment_free_phosphorylation_timecourse.v2'
EXPORT_MODE = 'enrichment_free_primary.v2'


def enabled(context):
    return isinstance(context, dict) and context.get('quantitation_export_mode') == EXPORT_MODE


def annotation_snapshot(root, sha256):
    if not isinstance(sha256,str) or not re.fullmatch('[0-9a-f]{64}',sha256):
        raise ValueError('A frozen annotation SHA-256 is required')
    directory = Path(root) / sha256
    path = directory / 'snapshot.tsv'
    if not path.is_file() or file_digest(path) != sha256:
        raise ValueError('Registered frozen annotation is absent or checksum differs')
    metadata_path = directory / 'annotation_metadata.json'
    if not metadata_path.is_file():
        raise ValueError('Frozen annotation metadata is required')
    metadata = json.loads(metadata_path.read_text())
    if metadata.get('database_sha256') != sha256:
        raise ValueError('Frozen annotation metadata checksum differs')
    return {'snapshot_path':str(path), 'reference_dir':str(directory), 'sha256':sha256,
            'retrieved_utc':metadata.get('retrieved_utc','unknown')}


def validate_profile(context, condition_map, ptm_type, species_tax_id, analysis_options=None):
    if not enabled(context):
        return None
    if ptm_type not in {'phosphorylation','phospho'}:
        raise ValueError('The primary-A profile requires phosphorylation input')
    if str(species_tax_id) != '10116':
        raise ValueError('This frozen rat annotation profile currently supports rat/Rat_hir')
    if context.get('enrichment_status') != 'enrichment_free':
        raise ValueError('Declare enrichment_status=enrichment_free for this profile')
    if (analysis_options or {}).get('quick_analysis'):
        raise ValueError('This profile requires full PR/PG matrices, including unmodified peptides')
    if (analysis_options or {}).get('mode','full') != 'full':
        raise ValueError('The primary-A profile requires full protein selection')
    if context.get('normalization_policy') not in {'already_normalized.v1','legacy_median.v1'}:
        raise ValueError('Explicit normalization_policy is required')
    return samples_from_manifest(context.get('sample_manifest'),condition_map)
