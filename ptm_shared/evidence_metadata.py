"""Run provenance and an explicit interpretation contract for evidence bundles."""
import hashlib
import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

import numpy as np
import pandas as pd

ACQUISITION_FIELDS = ('injection_amount', 'insulin_concentration', 'starvation_duration',
                      'acquisition_conditions', 'diann_version', 'diann_processing', 'diann_normalization')


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def software_versions():
    packages = {}
    for name in ('numpy','pandas','scipy','fastapi','sqlalchemy','celery'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = 'not_installed'
    return {'python':sys.version, 'platform':platform.platform(), 'packages':packages}


def build_provenance(inputs, samples, run_context=None, normalization=None):
    from .report_compatible_extensions import file_digest, STRICT_PARENT_V1_VERSION, EXPORT_VERSION
    from .report_compatible_quantification import VERSION as quantification_version
    from .report_compatible_kinase import VERSION as kinase_version, JOINT_COMPARISON_VERSION, HELD_OUT_GENES
    from .strict_parent_paired import DEFAULT_ESTIMATOR, COMPLETE_VERSION
    from .normalization_provenance import normalization_provenance
    context = dict(run_context or {})
    input_hashes = {name:{'sha256':file_digest(path), 'bytes':path.stat().st_size}
                    for name,path in inputs.items()}
    result = {'schema_version':'evidence_run_provenance.v2', 'order_id':context.get('order_id'),
        'order_code':context.get('order_code'), 'run_id':context.get('run_id', 'offline-' + digest_json(input_hashes)[:16]),
        'run_generation':context.get('run_generation'), 'input_files':input_hashes,
        'design_schema_version':'sample_manifest.v1', 'design_sha256':digest_json(samples),
        'declared_design':context.get('sample_manifest', {'samples':samples}),
        'normalization':normalization or normalization_provenance('already_normalized.v1',
            {s['original_column']:1.0 for s in samples},{s['original_column']:1.0 for s in samples}),
        'estimator_versions':{'quantification':quantification_version,'kinase_primary':kinase_version,
            'kinase_joint_comparison':JOINT_COMPARISON_VERSION,'strict_parent_legacy':STRICT_PARENT_V1_VERSION,
            'strict_parent_default':DEFAULT_ESTIMATOR,'strict_parent_complete_mask':COMPLETE_VERSION,'export':EXPORT_VERSION},
        'annotation_sha256':input_hashes.get('snapshot',{}).get('sha256'),
        'acquisition_metadata':{key:(context.get('acquisition_metadata') or {}).get(key) or 'unknown' for key in ACQUISITION_FIELDS},
        'analysis_profile':context.get('analysis_profile','offline_report_compatible'),
        'held_out_policy':{'genes':sorted(HELD_OUT_GENES),
            'selection_timing':'fixed_before_reanalysis_discovery_scoring_after_original_report_review',
            'prospective_preregistration':False, 'independent_biological_validation':False}}
    result['provenance_id'] = digest_json(result)
    return result


def form_evidence_status(analysis, edges, kinase):
    rows = analysis['comparisons'][['form_id','time_min','included','exclusion_reasons']].merge(
        analysis['summary'][['form_id','primary_mapping_eligible','primary_adjustment_eligible','baseline_undetected_all_runs',
                             'mapping_status','parent_match']], on='form_id', validate='many_to_one')
    rows = rows.merge(analysis['detection'][['form_id','time_min','detected_n','joint_observed_n','eligible_A','first_ge2_time']],
                      on=['form_id','time_min'], validate='one_to_one')
    curated = edges.loc[edges.primary_edge_eligible.astype(bool)]
    edge_counts = curated.groupby('form_id').size()
    rows['curated_edge_count'] = rows.form_id.map(edge_counts).fillna(0).astype(int)
    membership = kinase['mode_membership']
    membership = membership.loc[membership['mode'].eq('primary_A')].copy()
    membership['form_id'] = membership.form_ids.str.split(';')
    membership = membership.explode('form_id')
    adequate = kinase['profiles'].loc[kinase['profiles']['mode'].eq('primary_A'),['entity','time_min','coverage_adequate']]
    joined = membership.merge(adequate,on=['entity','time_min'])
    contribution_keys = set(zip(joined.form_id, joined.time_min))
    adequate_keys = set(zip(joined.loc[joined.coverage_adequate,'form_id'],joined.loc[joined.coverage_adequate,'time_min']))
    rows['primary_footprint_contributor'] = [(f,t) in contribution_keys for f,t in zip(rows.form_id,rows.time_min)]
    rows['any_candidate_coverage_adequate'] = [(f,t) in adequate_keys for f,t in zip(rows.form_id,rows.time_min)]
    rows['strict_attribution_status'] = 'no_call_localization_unavailable'
    rows['evidence_tier'] = np.select([
        ~rows.primary_adjustment_eligible, rows.primary_footprint_contributor,
        rows.baseline_undetected_all_runs & rows.eligible_A.notna() & rows.curated_edge_count.gt(0), rows.included],
        ['excluded_identity_or_parent','exploratory_baseline_footprint','emergent_curated_candidate','quantified_without_primary_kinase_footprint'],
        default='detection_only_or_insufficient_observation')
    rows['kinase_no_call_reason'] = np.select([
        ~rows.primary_adjustment_eligible, rows.curated_edge_count.eq(0), ~rows.included,
        ~rows.primary_footprint_contributor, ~rows.any_candidate_coverage_adequate],
        ['mapping_or_parent_ineligible','no_curated_observed_edge','baseline_comparison_unavailable',
         'not_single_site_primary_contributor','candidate_substrate_coverage_insufficient'], default='strict_localization_unknown;exploratory_available')
    return rows


def analysis_readiness(analysis, kinase, provenance):
    n_units = {}
    for row in provenance['declared_design'].get('samples',[]):
        condition = row.get('condition', str(row.get('time_min','unknown')))
        n_units.setdefault(condition,set()).add(row.get('biological_unit', 'unknown'))
    return {'schema_version':'analysis_readiness.v2', 'primary_A_available':bool(analysis['comparisons'].included.any()),
        'exploratory_footprint_available':bool(kinase['site_scores'].shape[0]),
        'strict_attribution':'no_call_localization_unavailable',
        'biological_unit_counts':{c:len(units) if 'unknown' not in units else 'unknown' for c,units in n_units.items()},
        'biological_p_q':'not_generated', 'rat_annotation':'human_to_rat_orthology_translation_not_direct_rat_validation',
        'S6K_source_caution':'Interpret primary together with HNRNPA1 omission; coverage can fall below 5 sites / 3 genes.',
        'strict_parent_default':provenance['estimator_versions']['strict_parent_default'],
        'absence_interpretation':'no_call_or_low_confidence_does_not_establish_absence_of_biological_response',
        'held_out_policy':provenance['held_out_policy'], 'provenance_id':provenance['provenance_id']}


def data_dictionary(tables):
    descriptions = {
        'summary':('phosphoform',['form_id'],'Charge-collapsed identity and eligibility; one Protein.Group is not necessarily one accession.'),
        'runlevel':('form × injection',['form_id','run'],'Positive PR/PG intensities, log values and observed masks. Missing is not zero.'),
        'comparisons':('form × treated time',['form_id','time_min'],'A, U_joint and P_joint share the same injection mask. U_all/P_all have their own masks.'),
        'detection':('form × treated time',['form_id','time_min'],'raw_candidate_A preserves calculation; eligible_A and inference_use_allowed gate interpretation. Different post references must not be pooled.'),
        'form_evidence_status':('form × treated time',['form_id','time_min'],'Detection through mapping, parent, baseline quantitation, curated edge, coverage and evidence tier.'),
        'site_mappings':('form × accession × assigned residue',['form_id','mapped_accession','residue_offset'],'Exact FASTA coordinate crosswalk; assigned offset is not localization confidence.'),
        'all_edges':('form × assigned site × annotation enzyme',['form_id','mapped_accession','residue_offset','enzyme'],'Retained and excluded frozen annotations with sources and reasons.'),
        'emergent_kinase_evidence':('form × site × candidate entity × treated time',['form_id','site_key','entity','time_min','mapped_accession','kinase_gene'], 'Emergence candidates only; never baseline fold-change or primary_A contributions.'),
    }
    result = {}
    for name, frame in tables.items():
        if name in descriptions:
            grain, keys, meaning = descriptions[name]
        elif 'peptide_mask_audit' in name:
            grain,keys,meaning = 'form × time × alternate peptide', ['form_id','time_min','sequence'], 'Actual joint run IDs/counts and paired/complete-mask inclusion reasons; numerator and denominator use identical runs.'
        elif 'sensitivity' in name or 'paired_sensitivity' in name:
            grain,keys,meaning = 'form × time', ['form_id','time_min'], 'Versioned alternative-parent sensitivity; v1 separate means differs from v2 paired ratios.'
        elif name.startswith('kinase_'):
            keys = [k for k in ('entity','mode','time_min','substrate_gene','site_key','feature_key','omitted_gene','omit_baseline_run','omit_treatment_run') if k in frame]
            grain,meaning = ' × '.join(keys), 'Descriptive substrate evidence; median forms→site, median sites→gene, mean genes. Aggregate A need not equal aggregate U minus P.'
        elif name == 'strict_parent_selected_sequences':
            grain,keys,meaning = 'protein group × unmodified sequence', ['Protein.Group','Stripped.Sequence'], 'Selected representative charge and supplied intensities; excludes any backbone observed modified.'
        elif name == 'strict_parent_sequences':
            grain,keys,meaning = 'protein group × sequence × time', ['protein_group','sequence','time_min'], 'Available-run sequence log contrast; descriptive protein layer, distinct from paired alternate-parent correction.'
        else:
            keys = [k for k in ('form_id','protein_group','gene','entity','time_min','omitted_early_time_min') if k in frame]
            grain,meaning = ' × '.join(keys), 'Same-experiment descriptive protein/temporal evidence. No independent biological or causal validation.'
        result[name+'.csv'] = {'row_unit':grain, 'join_keys':keys, 'meaning':meaning,
            'columns':list(frame.columns), 'missing_policy':'empty numeric cell = unavailable, never zero; see status/exclusion fields and analysis_readiness.json',
            'counts_are':'observations/features as specified, not independent biological samples',
            'run_provenance':'provenance.json and manifest entry for this artifact'}
    return {'schema_version':'astra_data_dictionary.v2','tables':result}
