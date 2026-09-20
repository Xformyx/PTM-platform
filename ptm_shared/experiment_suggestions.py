"""Conditional discrimination plans over existing, unvalidated hypotheses.

These are research design proposals, not automatic experiments, causal evidence,
predicted effect sizes or calibrated information-gain probabilities.
"""
from collections import defaultdict
from itertools import combinations
from .analysis_universe import signature


def suggest_discriminating_interventions(packets):
    groups=defaultdict(dict)
    for packet in packets:
        observation=packet.get('observation',{})
        kinase=observation.get('kinase')
        if not kinase:continue
        context=(observation.get('wave_id'),observation.get('target_gene'))
        groups[context].setdefault(kinase,[]).append(packet['packet_id'])
    suggestions=[]
    for context,hypotheses in sorted(groups.items(),key=lambda item:str(item[0])):
        if len(hypotheses)<2:continue
        all_pairs=list(combinations(sorted(hypotheses),2))
        for candidate in sorted(hypotheses):
            pairs=[list(pair) for pair in all_pairs if candidate in pair]
            suggestions.append({'suggestion_id':signature([context,candidate]),
                'method':'conditional_single_driver_pair_separation.v1','status':'proposed_not_tested',
                'wave_id':context[0],'target_gene':context[1],'candidate':candidate,
                'hypothesis_packet_ids':sorted({p for ids in hypotheses.values() for p in ids}),
                'separated_hypothesis_pairs':pairs,'pair_count':len(pairs),
                'suggested_action':'selective_orthogonal_perturbation_of_candidate_with_target_engagement_check',
                'readout':'measured_member_trajectories_and_orthogonal_target_readout',
                'conditional_predictions':{'candidate_is_required_driver':'attenuation_of_hypothesized_response',
                    'competing_driver_without_dependency':'response_retained'},
                'assumptions':['candidate is a required single driver under its hypothesis',
                    'perturbation engages the candidate in this experiment',
                    'no confounding off-target effect or compensatory pathway'],
                'limitations':['observational allocation does not verify these assumptions',
                    'a family candidate may lack a selective intervention; resolve feasibility first',
                    'health, dose, timing and off-target controls remain necessary'],
                'effect_size':None,'information_gain_probability':None,'cost':None,
                'feasibility_status':'requires_researcher_and_assay_review'})
    suggestions.sort(key=lambda row:(-row['pair_count'],row['suggestion_id']))
    return suggestions
