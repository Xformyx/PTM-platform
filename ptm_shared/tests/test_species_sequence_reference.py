import json

import pytest

from ptm_shared.annotation_registry import digest
from ptm_shared.science_reference import select_reference
from ptm_shared.species_sequence_reference import (
    DECLARED_SPECIES_SEQUENCE_REFERENCES,
    declared_reference_for_species,
    install_declared_references,
    prepare_astra_reference,
    with_declared_species_reference,
)


def test_declared_rat_hir_is_not_the_rat_reference():
    rat = declared_reference_for_species('rat')
    rat_hir = declared_reference_for_species('rat-hir')
    assert rat.reference_id == 'rat-uniprotkb-2026-07-11'
    assert rat_hir.reference_id == 'rat-hir-uniprotkb-human-insr-2026-08-14'
    assert rat.filename != rat_hir.filename
    assert {item.species for item in DECLARED_SPECIES_SEQUENCE_REFERENCES} == {'human', 'mouse', 'rat', 'rat_hir'}


def test_empty_reference_id_uses_the_declared_pin_and_keeps_an_explicit_id():
    filled = with_declared_species_reference({}, 'rat_hir')
    assert filled['science']['reference']['reference_id'] == 'rat-hir-uniprotkb-human-insr-2026-08-14'
    explicit = with_declared_species_reference({'science': {'reference': {'reference_id': 'custom-human'}}}, 'rat')
    assert explicit['science']['reference']['reference_id'] == 'custom-human'


def test_install_pins_the_declared_name_when_another_fasta_sorts_first(tmp_path, monkeypatch):
    from ptm_shared import species_sequence_reference as module
    declared = module.DeclaredSequenceReference(
        'rat', 'rat-pin', 'uniprotkb.test', 'rat', 'z_declared.fasta', 'declared rat file',
    )
    monkeypatch.setattr(module, 'DECLARED_SPECIES_SEQUENCE_REFERENCES', (declared,))
    species = tmp_path / 'rat'
    species.mkdir()
    (species / 'a_other.fasta').write_text('>A OX=10116\nAAA\n')
    chosen = species / 'z_declared.fasta'
    chosen.write_text('>B OX=10116\nBBB\n')
    installed = module.install_declared_references(tmp_path)
    selected, manifest = select_reference(tmp_path, 'rat-pin')
    assert installed[0]['sha256'] == digest(chosen)
    assert selected.endswith('z_declared.fasta')
    assert manifest['file'] == 'z_declared.fasta'
    assert 'a_other.fasta' not in json.dumps(manifest)


def test_prepare_uses_installed_pin_and_upload_drops_the_unpinned_species_id(tmp_path, monkeypatch):
    from ptm_shared import species_sequence_reference as module
    declared = module.DeclaredSequenceReference(
        'human', 'human-pin', 'uniprotkb.test', 'human', 'human.fasta', 'declared human file',
    )
    monkeypatch.setattr(module, 'DECLARED_SPECIES_SEQUENCE_REFERENCES', (declared,))
    species = tmp_path / 'human'
    species.mkdir()
    (species / 'human.fasta').write_text('>H OX=9606\nASA\n')
    install_declared_references(tmp_path)
    fasta, context, mapping = prepare_astra_reference(tmp_path, {}, 'human', False)
    assert fasta.endswith('human.fasta')
    assert context['science']['reference']['reference_sha256'] == digest(fasta)
    assert mapping is None
    uploaded = prepare_astra_reference(
        tmp_path,
        {'science': {'reference': {'reference_id': 'human-pin'}}},
        'human',
        True,
    )
    assert uploaded[0] is None
    assert 'reference_id' not in (uploaded[1].get('science') or {}).get('reference', {})


def test_existing_manifest_with_a_different_checksum_is_not_rewritten(tmp_path, monkeypatch):
    from ptm_shared import species_sequence_reference as module
    declared = module.DeclaredSequenceReference(
        'mouse', 'mouse-pin', 'uniprotkb.test', 'mouse', 'mouse.fasta', 'declared mouse file',
    )
    monkeypatch.setattr(module, 'DECLARED_SPECIES_SEQUENCE_REFERENCES', (declared,))
    species = tmp_path / 'mouse'
    species.mkdir()
    (species / 'mouse.fasta').write_text('>M OX=10090\nASA\n')
    install_declared_references(tmp_path)
    manifest = tmp_path / 'sequence_references' / 'mouse-pin' / 'manifest.json'
    body = json.loads(manifest.read_text())
    body['sha256'] = '0' * 64
    manifest.write_text(json.dumps(body))
    with pytest.raises(RuntimeError, match='not rewritten'):
        install_declared_references(tmp_path)
    assert json.loads(manifest.read_text())['sha256'] == '0' * 64
