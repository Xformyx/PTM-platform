"""Predeclared same-injection alternate-parent sensitivities.

v1 remains available in report_compatible_extensions.joint_sensitivity.
The default v2 aggregates per-peptide log-ratio contrasts, never subtracts a
peptide-specific parent contrast from an unmatched form mean.
"""
import numpy as np
import pandas as pd

from .report_compatible_quantification import contrast

PAIRED_VERSION = 'strict_unmodified_parent_paired_ratios.v2'
COMPLETE_VERSION = 'strict_unmodified_parent_complete_mask.v2'
DEFAULT_ESTIMATOR = PAIRED_VERSION
MIN_OBSERVATIONS_PER_CONDITION = 2
MIN_INDEPENDENT_SEQUENCES = 2


def paired_parent_sensitivities(analysis, selected, peptide_logs):
    selected = selected.reset_index(drop=True)
    groups = selected.groupby('Protein.Group').indices
    form_indices = {f: i for i, f in enumerate(analysis['summary'].form_id)}
    forms = analysis['summary'].set_index('form_id')
    samples = analysis['samples']
    baseline = np.array([i for i, s in enumerate(samples) if s['time_min'] == analysis['baseline_time']])
    per_time = {t: np.array([i for i, s in enumerate(samples) if s['time_min'] == t])
                for t in {s['time_min'] for s in samples}}
    audit, paired, complete = [], [], []
    for comparison in analysis['comparisons'].query('included').to_dict('records'):
        form_id, time = comparison['form_id'], comparison['time_min']
        fi = form_indices[form_id]
        parent_group = forms.loc[form_id, 'parent_pg']
        candidates = np.asarray(groups.get(parent_group, []), dtype=int)
        # PG eligibility and observation are part of this sensitivity's policy.
        form_joint = np.isfinite(analysis['arrays']['A'][fi])
        base = baseline[form_joint[baseline]]
        treated = per_time[time][form_joint[per_time[time]]]
        peptide = peptide_logs[candidates]
        ratio = np.where(form_joint, analysis['arrays']['U'][fi] - peptide, np.nan)
        delta, bn, tn = contrast(ratio, base, treated, MIN_OBSERVATIONS_PER_CONDITION)
        eligible = np.isfinite(delta)
        full_mask = np.isfinite(peptide[:, np.r_[base, treated]]).all(axis=1)
        for j, peptide_index in enumerate(candidates):
            metadata = selected.iloc[peptide_index]
            actual_base = [i for i in base if np.isfinite(ratio[j, i])]
            actual_treated = [i for i in treated if np.isfinite(ratio[j, i])]
            reasons = []
            if bn[j] < MIN_OBSERVATIONS_PER_CONDITION:
                reasons.append('baseline_joint_n_lt2')
            if tn[j] < MIN_OBSERVATIONS_PER_CONDITION:
                reasons.append('treated_joint_n_lt2')
            audit.append({'form_id': form_id, 'time_min': time, 'protein_group': parent_group,
                'sequence': metadata['Stripped.Sequence'], 'precursor_id': metadata['Precursor.Id'],
                'baseline_run_ids': ';'.join(samples[i]['run'] for i in actual_base),
                'treated_run_ids': ';'.join(samples[i]['run'] for i in actual_treated),
                'baseline_joint_n': int(bn[j]), 'treated_joint_n': int(tn[j]),
                'form_baseline_joint_n': len(base), 'form_treated_joint_n': len(treated),
                'paired_included': bool(eligible[j]), 'paired_exclusion_reason': ';'.join(reasons),
                'complete_mask_included': bool(eligible[j] and full_mask[j]),
                'complete_mask_exclusion_reason': ';'.join(reasons + ([] if full_mask[j] else ['missing_on_form_joint_run'])),
                'paired_log2_ratio_change': delta[j], 'estimator_version': PAIRED_VERSION})
        for target, mask, version in [(paired, eligible, PAIRED_VERSION),
                                      (complete, eligible & full_mask, COMPLETE_VERSION)]:
            n = int(mask.sum())
            value = float(np.median(delta[mask])) if n >= MIN_INDEPENDENT_SEQUENCES else np.nan
            target.append({'form_id': form_id, 'time_min': time, 'protein_group': parent_group,
                'strict_parent_A': value, 'PG_parent_A': comparison['A'], 'peptide_n': n,
                'candidate_peptide_n': len(candidates), 'estimator_version': version,
                'status': 'evaluable' if n >= MIN_INDEPENDENT_SEQUENCES else 'insufficient_independent_sequences',
                'min_observations_per_condition': MIN_OBSERVATIONS_PER_CONDITION,
                'min_independent_sequences': MIN_INDEPENDENT_SEQUENCES,
                'same_injection_policy': 'PTM_and_PG_and_each_unmodified_peptide',
                'default_alternative_parent_estimator': version == DEFAULT_ESTIMATOR,
                'sign_retained': bool(value * comparison['A'] > 0) if np.isfinite(value) else None,
                'threshold_0p5_retained': bool((abs(value) >= .5) == (abs(comparison['A']) >= .5)) if np.isfinite(value) else None})
    return {'paired_sensitivity_v2': pd.DataFrame(paired), 'complete_mask_sensitivity_v2': pd.DataFrame(complete),
            'peptide_mask_audit_v2': pd.DataFrame(audit)}
