import numpy as np
import pandas as pd
import pytest

from ptm_shared.report_compatible_extensions import strict_unmodified_parent
from ptm_shared.report_compatible_quantification import quantify_forms
from ptm_shared.strict_parent_paired import PAIRED_VERSION


def analysis(missing=False):
    columns=['b1','b2','b3','t1','t2','t3']
    common={'Protein.Group':'P1','Protein.Ids':'P1','Genes':'G','Proteotypic':1,'Precursor.Charge':2}
    data=[]
    for peptide, modified, vals in [
        ('ASK','AS(UniMod:21)K',[1,4,16,4,16,256]),
        ('AAA','AAA',[2,2,2,4,4,np.nan if missing else 4]),
        ('PEP','PEP',[8,8,8,16,16,16]),
        ('GGG','GGG',[1,1,1,2,2,2])]:
        data.append({**common,'Stripped.Sequence':peptide,'Modified.Sequence':modified,'Precursor.Id':peptide,**dict(zip(columns,vals))})
    pg=pd.DataFrame([{'Protein.Group':'P1','Genes':'G',**{c:1 for c in columns}}])
    samples=[{'original_column':c,'run':c,'time_min':0 if c[0]=='b' else 5,'run_suffix':int(c[-1])} for c in columns]
    return quantify_forms(pd.DataFrame(data),pg,{'P1':{'sequence':'ASKAAAPEPGGG','gene':'G','reviewed':True}},samples)


def test_complete_observation_matches_legacy_and_paired_ratios():
    result=strict_unmodified_parent(analysis())
    v1=result['joint_sensitivity'].iloc[0].strict_parent_A
    paired=result['paired_sensitivity_v2'].iloc[0]
    assert paired.strict_parent_A == pytest.approx(v1)
    assert paired.estimator_version == PAIRED_VERSION
    assert paired.default_alternative_parent_estimator
    assert result['complete_mask_sensitivity_v2'].iloc[0].strict_parent_A == pytest.approx(v1)


def test_missing_peptide_uses_identical_numerator_and_denominator_runs():
    result=strict_unmodified_parent(analysis(missing=True))
    audit=result['peptide_mask_audit_v2'].set_index('sequence')
    row=audit.loc['AAA']
    assert row.baseline_run_ids == 'b1;b2;b3'
    assert row.treated_run_ids == 't1;t2'
    # log2(4/4), log2(16/4), versus log2(1/2),log2(4/2),log2(16/2)
    assert row.paired_log2_ratio_change == pytest.approx(0)
    assert row.paired_included and not row.complete_mask_included
    assert row.complete_mask_exclusion_reason == 'missing_on_form_joint_run'
    assert result['paired_sensitivity_v2'].iloc[0].peptide_n == 3
    assert result['complete_mask_sensitivity_v2'].iloc[0].peptide_n == 2


def test_minimum_two_sequences_and_two_joint_observations_is_explicit():
    a=analysis(missing=True)
    a['pr'].loc[a['pr']['Stripped.Sequence'].isin(['PEP','GGG']),['t2','t3']]=np.nan
    result=strict_unmodified_parent(a)
    assert pd.isna(result['paired_sensitivity_v2'].iloc[0].strict_parent_A)
    assert result['paired_sensitivity_v2'].iloc[0].status == 'insufficient_independent_sequences'
    audit=result['peptide_mask_audit_v2']
    assert audit.loc[audit.sequence.eq('PEP'),'paired_exclusion_reason'].iloc[0] == 'treated_joint_n_lt2'
