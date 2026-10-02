"""Content-addressed reference preflight for experimental Astra v5 only."""
import hashlib
import copy
import json
import re
from pathlib import Path
from .annotation_registry import digest
from .species_registry import resolve_species_context

VERSION = 'reference_inventory.v1'


def candidate_protein_groups(edges, groups, reference):
    """Exact enzyme taxon plus accession or original-case symbol; no substrate fallback."""
    taxa={str(t) for t in edges.kinase_taxon.dropna()}
    if len(taxa)!=1:return set()
    tax=next(iter(taxa));entries={e['accession']:e for e in reference['entries']}
    accessions=set(edges.candidate_accession.dropna());genes=set(edges.candidate_gene.dropna())
    result=set()
    for group in groups:
        members=[entries.get(a) for a in str(group).split(';')]
        if not members or any(e is None or e['taxon']!=tax for e in members):continue
        if any(e['accession'] in accessions or e['gene'] in genes for e in members):result.add(group)
    return result


class PreflightError(ValueError):
    def __init__(self, code, field, detail):
        self.code, self.field, self.detail = code, field, detail
        super().__init__(f'{code} [{field}]: {detail}')


def records(path):
    header = None; parts = []
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            if line.startswith('>'):
                if header is not None: yield header, ''.join(parts)
                header = line[1:].strip(); parts = []
            elif line.strip():
                if header is None: raise PreflightError('invalid_fasta', 'fasta_path', 'Sequence before header')
                parts.append(line.strip().upper())
        if header is not None: yield header, ''.join(parts)


def inventory(path, mapping=None):
    mapping = mapping or {}; entries = mapping.get('accessions', {}); result = []; seen = {}
    for header, sequence in records(path):
        raw_id = header.split()[0]; pieces = raw_id.split('|')
        accession = pieces[1] if len(pieces) >= 3 and pieces[0] in {'sp', 'tr'} else raw_id
        supplied = entries.get(accession, {})
        ox = re.search(r'\bOX=(\d+)', header); gn = re.search(r'\bGN=([^\s]+)', header)
        taxon = ox[1] if ox else supplied.get('taxon')
        if isinstance(taxon, list): taxon = None  # retain ambiguity in mapping resource, never majority-vote
        if ox and supplied.get('taxon') is not None and str(supplied['taxon']) != ox[1]:
            raise PreflightError('taxonomy_mapping_conflict', accession, 'FASTA OX and registered mapping disagree')
        sha = hashlib.sha256(sequence.encode()).hexdigest()
        if accession in seen and seen[accession] != (sha, taxon):
            raise PreflightError('accession_sequence_conflict', accession, 'Same accession has differing sequence or taxon')
        if accession in seen: continue
        seen[accession] = (sha, taxon)
        kind = supplied.get('kind', 'decoy' if raw_id.startswith(('REV_', 'DECOY_')) else 'contaminant' if raw_id.startswith('CON__') else 'biological')
        if kind not in {'biological','decoy','contaminant','spike_in'}:
            raise PreflightError('reference_entry_kind', accession, 'Unknown reference entry kind')
        if not sequence or not re.fullmatch('[A-Z*]+', sequence):
            raise PreflightError('invalid_sequence', accession, 'Empty or invalid sequence alphabet')
        result.append({'accession': accession, 'raw_identifier': raw_id, 'sequence': sequence,
            'reviewed':raw_id.startswith('sp|'),
            'sequence_sha256': sha, 'taxon': str(taxon) if taxon is not None else None,
            'gene': gn[1] if gn else supplied.get('gene'), 'entry_kind': kind,
            'taxonomy_source': 'FASTA.OX' if ox else 'registered_mapping' if taxon else 'unresolved',
            'gene_source': 'FASTA.GN' if gn else 'registered_mapping' if supplied.get('gene') else 'unresolved',
            'mapping_candidates': supplied.get('candidates', []), 'header': header})
    if not result: raise PreflightError('empty_reference', 'fasta_path', 'No FASTA sequences')
    return result


def select_reference(root, reference_id):
    """An explicit registry ID resolves one immutable manifest; never sort FASTA names."""
    if not reference_id or not re.fullmatch(r'[A-Za-z0-9_.-]+', reference_id):
        raise PreflightError('reference_id_required', 'reference_id', 'Choose a registered reference or upload FASTA')
    path = Path(root)/'sequence_references'/reference_id/'manifest.json'
    if not path.is_file(): raise PreflightError('reference_unavailable','reference_id',reference_id)
    manifest = json.loads(path.read_text())
    fasta = (path.parent/manifest['file']).resolve()
    if not fasta.is_relative_to(path.parent.resolve()) or not fasta.is_file() or digest(fasta) != manifest.get('sha256'):
        raise PreflightError('reference_checksum_invalid','reference_id',reference_id)
    if manifest.get('reference_id') != reference_id or not manifest.get('version'):
        raise PreflightError('reference_metadata_invalid','reference_id',reference_id)
    return str(fasta), manifest


def bind_registered_reference(root, context):
    """Pin registry metadata without putting accession arrays in Order context."""
    context=copy.deepcopy(context)
    contract=context.setdefault('science',{}).setdefault('reference',{})
    fasta,manifest=select_reference(root,contract.get('reference_id'))
    manifest_path=Path(root)/'sequence_references'/manifest['reference_id']/'manifest.json'
    contract.update(reference_version=manifest['version'],reference_sha256=manifest['sha256'],
                    registry_manifest_sha256=digest(manifest_path))
    mapping_path=str(manifest_path) if manifest.get('taxonomy_mapping') else None
    return fasta,context,mapping_path


def preflight(config, context):
    design = context['study_design']; study = design['study']; policy = context.get('science', {})
    species = config.get('species') or study.get('species')
    try: species_record = resolve_species_context(species)
    except ValueError: raise PreflightError('species_required', 'species', 'Explicit registered species is required') from None
    tax = config.get('species_tax_id')
    if tax is None: raise PreflightError('taxonomy_required', 'species_tax_id', 'Worker taxonomy is missing')
    if str(tax) != str(species_record.taxonomy_id) or str(tax) != str(study.get('taxonomy_id')):
        raise PreflightError('species_contract_conflict','species_tax_id','Species, design and worker taxonomy disagree')
    if config.get('kegg_organism') is not None and config['kegg_organism'] != species_record.kegg_organism:
        raise PreflightError('species_contract_conflict','kegg_organism','KEGG organism differs from declared species')
    contract = policy.get('reference', {}); scope = contract.get('species_scope','mixed_species' if species_record.label=='rat_hir' else 'single_species')
    if scope not in {'single_species','mixed_species'}: raise PreflightError('species_scope_invalid','science.reference.species_scope',scope)
    expected = {str(t) for t in contract.get('expected_sample_taxa', [str(tax)] if scope == 'single_species' else ['10116','9606'] if species_record.label=='rat_hir' else [])}
    if not expected or (scope == 'single_species' and expected != {str(tax)}):
        raise PreflightError('expected_taxa_required','science.reference.expected_sample_taxa','Declare expected biological taxa')
    if config.get('fasta_path'):
        path = Path(config['fasta_path']); sha = digest(path)
        identifier = contract.get('reference_id') or 'uploaded-'+sha
        meta = {'reference_id':identifier,'version':contract.get('reference_version','user_supplied_content_addressed')}
    else:
        path, meta = select_reference(config['reference_root'],contract.get('reference_id')); path=Path(path);sha=digest(path)
    if contract.get('reference_sha256') and contract['reference_sha256'] != sha:
        raise PreflightError('reference_checksum_invalid','science.reference.reference_sha256','Reference content changed')
    mapping_path=config.get('taxonomy_mapping_path')
    mapping=json.loads(Path(mapping_path).read_text()) if mapping_path else meta.get('taxonomy_mapping',{})
    if mapping.get('taxonomy_mapping') is not None:
        # A registry manifest is a pinned file input, not a giant context array.
        if mapping.get('sha256')!=sha or mapping.get('reference_id')!=contract.get('reference_id'):
            raise PreflightError('mapping_reference_conflict','taxonomy_mapping_path','Registry mapping targets a different reference')
        if contract.get('registry_manifest_sha256') and digest(mapping_path)!=contract['registry_manifest_sha256']:
            raise PreflightError('reference_metadata_changed','taxonomy_mapping_path','Pinned registry manifest changed')
        mapping=mapping['taxonomy_mapping']
    if mapping and any(not mapping.get(k) for k in ('source','release','accessions')):
        raise PreflightError('mapping_provenance_missing','taxonomy_mapping_path','Require source, release and accession mapping')
    entries=inventory(path,mapping)
    biological={e['taxon'] for e in entries if e['entry_kind']=='biological' and e['taxon'] is not None}
    if biological-expected:
        raise PreflightError('species_reference_conflict','science.reference.expected_sample_taxa','Unexpected biological taxa: '+','.join(sorted(biological-expected)))
    search=config.get('search_fasta_path'); search_sha=digest(search) if search else None
    if search_sha and search_sha != sha:
        conversion=contract.get('search_conversion',{})
        if conversion.get('from_sha256')!=search_sha or conversion.get('to_sha256')!=sha or not conversion.get('approval_source') or not conversion.get('mapping_sha256'):
            raise PreflightError('search_reference_conflict','search_fasta_path','Different search/analysis FASTA requires approved conversion provenance')
        searched=inventory(search,mapping)
        search_sequences={e['accession']:(e['sequence_sha256'],e['taxon']) for e in searched if e['entry_kind']=='biological'}
        analysis_sequences={e['accession']:(e['sequence_sha256'],e['taxon']) for e in entries if e['entry_kind']=='biological'}
        if search_sequences!=analysis_sequences:
            raise PreflightError('search_conversion_unsupported','search_fasta_path','This release supports approved header-only conversions with identical accession, sequence and taxonomy; coordinate-changing conversions are not implemented')
    target=study.get('analysis_target') or ('proteomics' if study['ptm_type']=='proteomics' else 'phosphoproteomics' if study['ptm_type'] in {'phosphorylation','phospho'} else 'other_ptm')
    if target not in {'phosphoproteomics','proteomics','other_ptm'}: raise PreflightError('analysis_target_invalid','study.analysis_target',target)
    if target=='proteomics' and study['ptm_type']!='proteomics':raise PreflightError('analysis_target_conflict','study.ptm_type','Protein-only target requires proteomics PTM code')
    if not config.get('pg_matrix_path'):
        raise PreflightError('parent_input_required' if target!='proteomics' else 'protein_input_required','pg_matrix_path','This v5 release requires PG; U-only execution is not implemented, no synthetic A will be generated')
    if target!='proteomics' and not config.get('pr_matrix_path'):raise PreflightError('precursor_input_required','pr_matrix_path','PTM analysis requires PR')
    return {'schema_version':VERSION, **meta,'reference_sha256':sha,'reference_path':str(path),
        'species_scope':scope,'host_taxon':contract.get('host_taxon','10116' if species_record.label=='rat_hir' else None), 'expected_sample_taxa':sorted(expected),
        'reference_taxon_inventory':sorted(biological),'taxonomy_mapping_resource_sha256':digest(mapping_path) if mapping_path else None,
        'species_resolution_status':'partial_unknown_taxonomy' if any(e['taxon'] is None and e['entry_kind']=='biological' for e in entries) else 'verified_inventory',
        'species_resolution_source':'explicit_design_and_sequence_inventory','search_fasta_sha256':search_sha,
        'search_reference_status':'not_provided' if search is None else 'identical' if search_sha==sha else 'approved_conversion',
        'analysis_target':target,'design_axis':study.get('design_axis','time_course'),'entries':entries}
