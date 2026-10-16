"""Declared species sequence references for new Astra orders.

구현 대상: docs/astra_science_upgrade/operations_KO.md «등록된 종별 sequence reference»
사전등록: 2026-10-12. 주문 실행 전. 이미 쓰이던 종별 FASTA의 파일명을 등록 ID로 고정한다.
해석 한계: 빈 Reference ID에 선언 ID를 넣는 절차다. 디렉터리 정렬로 FASTA를 고르지 않는다.
주장 금지: 이 등록으로 kinase 귀속 정확도를 논하지 않는다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .annotation_registry import digest
from .science_reference import PreflightError, bind_registered_reference, select_reference
from .species_registry import resolve_species_context


@dataclass(frozen=True)
class DeclaredSequenceReference:
    species: str
    reference_id: str
    version: str
    source_subdir: str
    filename: str
    description: str


DECLARED_SPECIES_SEQUENCE_REFERENCES = (
    DeclaredSequenceReference(
        'human', 'human-uniprotkb-up000005640-2025-10-23', 'uniprotkb.2025-10-23',
        'human', 'uniprotkb_proteome_homo_sapiense_UP000005640_AND_revi_2025_10_23.fasta',
        'UniProtKB Homo sapiens proteome UP000005640 snapshot dated 2025-10-23. The filename keeps the source spelling sapiense.',
    ),
    DeclaredSequenceReference(
        'mouse', 'mouse-uniprotkb-2025-07-24', 'uniprotkb.2025-07-24',
        'mouse', 'uniprotkb_organism_name_Mus_musculus_AN_2025_07_24.fasta',
        'UniProtKB Mus musculus snapshot dated 2025-07-24.',
    ),
    DeclaredSequenceReference(
        'rat', 'rat-uniprotkb-2026-07-11', 'uniprotkb.2026-07-11',
        'rat', 'uniprotkb_proteome_Rat_2026_07_11.fasta',
        'UniProtKB Rattus norvegicus proteome snapshot dated 2026-07-11.',
    ),
    DeclaredSequenceReference(
        'rat_hir', 'rat-hir-uniprotkb-human-insr-2026-08-14', 'uniprotkb.rat-plus-human-insr.2026-08-14',
        'rat_hir', 'uniprotkb_proteome_Rat_add_human_INSR.fasta',
        'Rattus norvegicus proteome plus human INSR (GN=INSR, OX=9606). This is not the rat reference.',
    ),
)


def declared_reference_for_species(species: str | None) -> DeclaredSequenceReference | None:
    """Return the declared pin for a species label. Unknown labels return None."""
    try:
        label = resolve_species_context(species).label
    except ValueError:
        return None
    for item in DECLARED_SPECIES_SEQUENCE_REFERENCES:
        if item.species == label:
            return item
    return None


def _reference_contract(context: dict) -> dict:
    return (context.get('science') or {}).get('reference') or {}


def with_declared_species_reference(context: dict | None, species: str | None) -> dict:
    """Fill an empty reference_id from the declared species pin.

    An explicit reference_id is unchanged. No FASTA directory is scanned.
    """
    import copy
    result = copy.deepcopy(context or {})
    if str(_reference_contract(result).get('reference_id') or '').strip():
        return result
    declared = declared_reference_for_species(species)
    if declared is None:
        return result
    science = result.setdefault('science', {})
    reference = science.setdefault('reference', {})
    reference['reference_id'] = declared.reference_id
    return result


def without_unpinned_species_reference(context: dict | None, species: str | None) -> dict:
    """An uploaded analysis FASTA is not labeled with the species registry id.

    A caller-supplied checksum or version means the id was pinned on purpose
    and stays. Only an id that matches the species declaration and has no pin
    is removed.
    """
    import copy
    result = copy.deepcopy(context or {})
    declared = declared_reference_for_species(species)
    reference = _reference_contract(result)
    if declared is None or reference.get('reference_id') != declared.reference_id:
        return result
    if reference.get('reference_sha256') or reference.get('reference_version'):
        return result
    science = result.setdefault('science', {})
    cleaned = dict(science.get('reference') or {})
    cleaned.pop('reference_id', None)
    if cleaned:
        science['reference'] = cleaned
    else:
        science.pop('reference', None)
    return result


def prepare_astra_reference(root, context, species, uploaded_fasta: bool):
    """Resolve the reference for a new Astra order.

    An uploaded analysis FASTA wins. An empty reference_id becomes the
    declared species pin. An explicit reference_id is passed through.
    """
    if uploaded_fasta:
        return None, without_unpinned_species_reference(context, species), None
    prepared = with_declared_species_reference(context, species)
    try:
        return bind_registered_reference(root, prepared)
    except PreflightError as error:
        if error.code == 'reference_unavailable':
            raise PreflightError(
                'reference_unavailable', 'reference_id',
                f"Registered reference '{error.detail}' is not installed. "
                'Run scripts/register_species_sequence_references.py or upload an analysis FASTA.',
            ) from error
        raise


def astra_reference_status(root, species: str | None) -> dict:
    """Report whether the declared species pin is installed. Does not scan FASTA names."""
    declared = declared_reference_for_species(species)
    if declared is None:
        return {
            'astra_reference_id': None,
            'astra_reference_ready': False,
            'astra_reference_filename': None,
            'astra_reference_message': 'No declared sequence reference for this species. Upload an analysis FASTA.',
        }
    try:
        fasta, _manifest = select_reference(root, declared.reference_id)
    except PreflightError as error:
        message = str(error.detail)
        if error.code == 'reference_unavailable':
            message = (
                f"Registered reference '{error.detail}' is not installed. "
                'Run scripts/register_species_sequence_references.py or upload an analysis FASTA.'
            )
        return {
            'astra_reference_id': declared.reference_id,
            'astra_reference_ready': False,
            'astra_reference_filename': declared.filename,
            'astra_reference_message': message,
        }
    return {
        'astra_reference_id': declared.reference_id,
        'astra_reference_ready': True,
        'astra_reference_filename': Path(fasta).name,
        'astra_reference_message': f'Registered reference ready: {declared.reference_id}',
    }


def install_declared_references(root) -> list[dict]:
    """Hard-link each declared FASTA under its reference id and write the manifest.

    An existing manifest with a different id, file, or sha256 is left unchanged
    and reported as a conflict. Directory order is not consulted.
    """
    root = Path(root)
    installed = []
    for declared in DECLARED_SPECIES_SEQUENCE_REFERENCES:
        source = root / declared.source_subdir / declared.filename
        if not source.is_file():
            raise FileNotFoundError(f'Declared FASTA is missing: {source}')
        destination_dir = root / 'sequence_references' / declared.reference_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / declared.filename
        source_sha = digest(source)
        if destination.exists() or destination.is_symlink():
            if digest(destination) != source_sha:
                raise RuntimeError(f'Registered file checksum differs and was not replaced: {destination}')
        else:
            try:
                os.link(source, destination)
            except OSError:
                destination.write_bytes(source.read_bytes())
        manifest_path = destination_dir / 'manifest.json'
        manifest = {
            'reference_id': declared.reference_id,
            'version': declared.version,
            'file': declared.filename,
            'sha256': source_sha,
            'species': declared.species,
            'description': declared.description,
        }
        if manifest_path.is_file():
            current = json.loads(manifest_path.read_text())
            if any(current.get(key) != manifest[key] for key in ('reference_id', 'version', 'file', 'sha256', 'species')):
                raise RuntimeError(f'Existing manifest pin differs and was not rewritten: {manifest_path}')
        else:
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        installed.append({'species': declared.species, 'reference_id': declared.reference_id, 'sha256': source_sha})
    return installed
