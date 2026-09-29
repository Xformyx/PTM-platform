"""KEA3 statistics preserve their original meaning; missing p/q stay null."""
import math

VERSION = 'kea3_typed_response.v3'


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_kea3(payload):
    if not isinstance(payload, dict) or any(not isinstance(v, list) for v in payload.values()):
        raise ValueError('Invalid KEA3 library payload')
    rows = []
    for library, entries in sorted(payload.items()):
        for position, entry in enumerate(entries, 1):
            if not isinstance(entry, dict) or not (entry.get('TF') or entry.get('Kinase')):
                raise ValueError('Invalid KEA3 candidate row')
            overlap = entry.get('Overlapping_Genes', [])
            if isinstance(overlap, str):
                overlap = [s.strip() for s in overlap.split(',') if s.strip()]
            rows.append({'kinase': entry.get('TF', entry.get('Kinase')), 'library': library,
                'rank': numeric(entry.get('Rank')), 'source_row_position':position, 'score': numeric(entry.get('Score')),
                'p_value': numeric(entry.get('P-value', entry.get('p_value'))),
                'q_value': numeric(entry.get('FDR', entry.get('q_value'))),
                'statistic_type': 'integrated_rank' if library.startswith('Integrated') else 'gene_set_library_statistic',
                'overlapping_genes': overlap, 'background': 'external_service_uncontrolled',
                'direction': None, 'direct_site_evidence': False})
    return rows


def mapped_human_genes(genes, taxonomy_id, mapping=None):
    if str(taxonomy_id) == '9606':
        return sorted(set(genes))  # Preserve verified species symbols; case conversion is not orthology.
    mapping = mapping or {}
    if any(g not in mapping or not mapping[g].get('verified') for g in genes):
        raise ValueError('verified_human_orthology_mapping_required')
    return sorted({r for g in genes for r in mapping[g]['human_genes']})
