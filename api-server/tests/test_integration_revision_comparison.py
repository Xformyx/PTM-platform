"""Real API helpers and the shared immutable artifact registry, with fixed data."""
from pathlib import Path
from types import SimpleNamespace
import csv
import json

from app.api.compare import _pinned_comparison, _comparison_markdown
from ptm_shared.report_revision import register_revision, file_sha256


def source_revision(root, code, value, policy='already_normalized.v1', species='human'):
    output = root / code
    output.mkdir(exist_ok=True)
    vector = output / 'vector.tsv'
    row = {'Protein.Group': 'P1', 'Gene.Name': 'GENE', 'Modified.Sequence': 'AS(UniMod:21)K', 'Precursor.Id': 'precursor2',
           'Precursor.Charge': 2, 'PTM_Position': 'S2', 'FASTA_Taxonomy_ID': 9606, 'Condition': '5min',
           'PTM_ProteinAdjusted_Log2FC': value, 'PTM_Unadjusted_Log2FC': value,
           'Normalization_Policy': policy, 'PTM_ProteinAdjusted_Estimator_ID': 'protein_adjusted_mean_of_sample_ptm_to_protein_ratios.v1'}
    with vector.open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=row, delimiter='\t')
        writer.writeheader()
        writer.writerow(row)
    source = output / 'source.json'
    source.write_text(json.dumps({'species': species, 'ptm_type': 'phosphorylation',
                                 'sample_manifest': {'samples': [{'sample_id': 'sample', 'biological_unit': 'unit'}]}}))
    return register_revision(output, files=[], manifest={'artifacts': [
        {'path': str(vector), 'role': 'vector_tsv', 'sha256': file_sha256(vector)},
        {'path': str(source), 'role': 'source_run_manifest', 'sha256': file_sha256(source)}]},
                             release={'status': 'final_ready', 'publish_as_final': True, 'review_artifact_available': True})


def orders():
    return [SimpleNamespace(id=i, order_code=code, species='human', ptm_type='phosphorylation', project_name=code) for i, code in [(1, 'A'), (2, 'B')]]


def test_cmp01_signed_observations_pins_and_missingness(tmp_path):
    a, b = orders()
    rev_a, rev_b = source_revision(tmp_path, 'A', -2), source_revision(tmp_path, 'B', -1)
    source_revision(tmp_path, 'A', 8)  # A later source may not replace the queued comparison.
    comparison = _pinned_comparison(a, b, tmp_path, rev_a['revision_id'], rev_b['revision_id'])
    assert comparison['records'][0]['a']['value'] == -2
    assert comparison['records'][0]['difference'] == -1
    assert comparison == json.loads(json.dumps(comparison))
    report = _comparison_markdown(comparison)
    assert '| -2.0 | -1.0 |' in report
    assert 'review draft' in report
    missing = source_revision(tmp_path, 'B', '')
    comparison = _pinned_comparison(a, b, tmp_path, rev_a['revision_id'], missing['revision_id'])
    assert comparison['records'][0]['b']['value'] is None
    assert comparison['records'][0]['difference'] is None
    assert 'NA' in _comparison_markdown(comparison)


def test_cmp01_incompatible_policy_or_species_cannot_generate_difference(tmp_path):
    a, b = orders()
    ra, rb = source_revision(tmp_path, 'A', 1), source_revision(tmp_path, 'B', 2, 'legacy_median.v1')
    comparison = _pinned_comparison(a, b, tmp_path, ra['revision_id'], rb['revision_id'])
    assert comparison['records'][0]['difference'] is None
    assert 'quantitative_policy_incompatible' in comparison['records'][0]['reasons']
    b.species = 'mouse'
    frozen = _pinned_comparison(a, b, tmp_path, ra['revision_id'], rb['revision_id'])
    assert frozen == comparison  # Mutating the current order cannot change pinned evidence.
    rb = source_revision(tmp_path, 'B', 2, species='mouse')
    comparison = _pinned_comparison(a, b, tmp_path, ra['revision_id'], rb['revision_id'])
    assert 'species_or_ptm_type_incompatible' in comparison['records'][0]['reasons']
