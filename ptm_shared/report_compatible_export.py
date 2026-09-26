"""Versioned form evidence outputs alongside existing platform vectors."""
import json
from pathlib import Path

from .report_compatible_quantification import quantify_forms, read_fasta, samples_from_manifest, VERSION
from .report_compatible_extensions import strict_unmodified_parent, late_layer, file_digest

MODE = 'legacy_plus_report_compatible.v1'
TABLES = ['summary', 'runlevel', 'comparisons', 'detection', 'strict_parent_proteins',
          'strict_parent_sequences', 'strict_parent_joint_sensitivity', 'held_out_protein_layer']


def artifact_names(suffix):
    return [f'report_compatible_{name}{suffix}.tsv' for name in TABLES] + [f'report_compatible_contract{suffix}.json']


def export_form_evidence(pr, pg, fasta_path, manifest, condition_map, output_dir, suffix, normalization_policy):
    samples = samples_from_manifest(manifest, condition_map)
    analysis = quantify_forms(pr, pg, read_fasta(fasta_path), samples)
    strict = strict_unmodified_parent(analysis)
    tables = {key: analysis[key] for key in ['summary', 'runlevel', 'comparisons', 'detection']}
    tables.update({'strict_parent_' + key: strict[key] for key in ['proteins', 'sequences', 'joint_sensitivity']})
    tables['held_out_protein_layer'] = late_layer(analysis, strict['proteins'])
    root = Path(output_dir)
    files = {}
    for name, frame in tables.items():
        path = root / f'report_compatible_{name}{suffix}.tsv'
        pending = path.with_suffix('.pending')
        frame.to_csv(pending, sep='\t', index=False)
        pending.replace(path)
        files[path.name] = file_digest(path)
    contract = {'mode': MODE, 'estimator_version': VERSION, 'normalization_policy': normalization_policy,
                'formula': 'A = mean(log2(PR/PG))_treated - mean(log2(PR/PG))_baseline; A = U_joint - P_joint',
                'form_identity': ['Protein.Group', 'Modified.Sequence'], 'charge_aggregation': 'sum_positive_observations_min_count_1',
                'biological_inference': 'withheld_in_descriptive_evidence_layer',
                'localization': 'unknown; assigned sequence offsets only',
                'existing_vector_estimator': 'unchanged_legacy_precursor_arithmetic_mean_of_ratios',
                'kinase_scoring': 'requires_explicit_frozen_snapshot_offline_bundle', 'files_sha256': files}
    path = root / f'report_compatible_contract{suffix}.json'
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(contract, indent=2)); pending.replace(path)
    return contract
