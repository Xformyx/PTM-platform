from ptm_shared.experiment_suggestions import suggest_discriminating_interventions


def test_competing_hypotheses_are_conditional_not_probability_or_execution():
    packets=[{'packet_id':k,'observation':{'kinase':k,'wave_id':'W','target_gene':'T'}} for k in ('A','B')]
    proposals=suggest_discriminating_interventions(packets+packets)
    assert len(proposals)==2
    assert all(p['pair_count']==1 and p['status']=='proposed_not_tested' for p in proposals)
    assert all(p['information_gain_probability'] is None and p['cost'] is None for p in proposals)
    assert proposals==suggest_discriminating_interventions(list(reversed(packets)))
    assert suggest_discriminating_interventions(packets[:1])==[]
