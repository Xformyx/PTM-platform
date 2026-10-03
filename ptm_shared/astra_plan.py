"""An internal execution plan, not another set of user-selectable analysis modes."""
from .astra_inputs import stable_id
from .study_design import require_resolved
from pathlib import Path
import hashlib

PROFILE = 'astra_analysis.v4'
VERSION = 'astra_plan.v1'
STAGES = {'resolve_inputs_and_plan': [], 'quantify_evidence': ['resolve_inputs_and_plan'],
          'resolve_annotation': ['resolve_inputs_and_plan'],
          'discover_regulators': ['quantify_evidence', 'resolve_annotation'],
          'score_regulator_footprints': ['discover_regulators'],
          'integrate_temporal_layers': ['score_regulator_footprints'],
          'assemble_evidence_package': ['integrate_temporal_layers'],
          'validate_and_publish': ['assemble_evidence_package']}


def effective_context(context):
    result = dict(context)
    result.setdefault('normalization_policy', 'already_normalized.v1')
    if result['normalization_policy'] == 'use_supplied_intensities':
        result['normalization_policy'] = 'already_normalized.v1'
    result['annotation_mode'] = 'automatic'
    return result


def validate_execution(context, ptm_type, taxonomy_id, options=None, pr_columns=None, pg_columns=None):
    design = require_resolved(context.get('study_design') or {}, pr_columns, pg_columns)
    if str(design['study'].get('taxonomy_id')) != str(taxonomy_id) or design['study'].get('ptm_type') != ptm_type:
        raise ValueError('Canonical organism/PTM conflicts with inputs')
    from .contrast_quantification import PTM_CODES
    if ptm_type not in PTM_CODES or ptm_type=='proteomics':
        raise ValueError('Unsupported quantitative PTM code')
    if effective_context(context)['normalization_policy'] not in {'already_normalized.v1', 'legacy_median.v1'}:
        raise ValueError('Unsupported explicit normalization policy')


def resolve_plan(context, hashes=None, source_pin=None, taxa=None):
    from .contrast_quantification import VERSION as estimator
    ctx = effective_context(context); design = ctx['study_design']
    # Interpretation-only fields cannot change quantitative fingerprints.
    numeric_design = {k: design[k] for k in ('conditions','contrasts','materials','injections','replication_declaration')}
    conditions = []
    for c in numeric_design['conditions']:
        conditions.append({k: c.get(k) for k in ('condition_id','arm_id','time','role','reference_condition_id')})
    numeric_design = {**numeric_design, 'conditions': conditions}
    code=lambda names:{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}
    quant_code=code(['contrast_quantification.py','report_compatible_quantification.py','normalization_provenance.py','study_design.py','generic_workflow.py','generic_kinase.py','strict_parent_paired.py','report_compatible_extensions.py'])
    discovery_code=code(['astra_discovery.py','generic_kinase.py','motif_candidate_calibration.py','motif_library.json'])
    temporal_code=code(['astra_temporal.py','substrate_temporal_dynamics.py','kinase_trajectory_evidence.py'])
    quant = stable_id('quant', [hashes, numeric_design, design['study']['ptm_type'], design['study']['taxonomy_id'], estimator, ctx['normalization_policy'],quant_code])
    discovery = stable_id('discovery', [quant, source_pin, ctx.get('localization_evidence'), discovery_code])
    temporal = stable_id('temporal', [discovery, ctx.get('temporal_policy', {}), temporal_code])
    return {'schema_version': VERSION, 'profile': PROFILE, 'input_fingerprints': hashes or {},
        'design_hash': stable_id('design', design), 'ptm_type': design['study']['ptm_type'], 'fasta_taxa': sorted({str(t) for t in (taxa or []) if t is not None}),
        'enrichment_status': ctx.get('enrichment_status', 'unknown'), 'estimator': estimator,
        'normalization': {'requested': context.get('normalization_policy'), 'effective': ctx['normalization_policy'],
            'external_name': 'use_supplied_intensities' if ctx['normalization_policy'] == 'already_normalized.v1' else 'separate_PR_PG_median',
            'upstream_status': design['study'].get('processing', {}).get('upstream_normalization', 'unknown')},
        'replication': design['replication_declaration'], 'biological_inference': 'unavailable_method_not_implemented',
        'stages': [{'stage': name, 'dependencies': dependencies} for name, dependencies in STAGES.items()],
        'fingerprints': {'quant': quant, 'discovery': discovery, 'temporal': temporal}, 'code_dependencies':{'quant':quant_code,'discovery':discovery_code,'temporal':temporal_code},
        'source_policy': 'reuse_pinned_then_validated_cache_then_bounded_provider_queries',
        'source_pin': source_pin, 'overrides': {k: ctx[k] for k in ('normalization_policy','temporal_policy') if k in context},
        'unsupported_requested_options': {'protein_subsetting': 'full_matrices_used', 'legacy_LLM_RAG_network_execution': 'not_run_preferences_exported'},
        'summary': 'Supplied quantification → same-injection parent adjustment → database and anchored motif candidates → measured temporal and protein integration → Astra package'}
