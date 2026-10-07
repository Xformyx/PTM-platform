"""Round06 validation only: read existing results, invoke existing pure card builders.

The namespace loader avoids core/__init__'s report graph/LLM initialization;
consumer function bodies are unmodified. No report writer or finding selector runs.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys
import types

import pandas as pd

from ptm_shared.astra_card_inputs import consumer_states, equivalent, validate_card_inputs


def card_builders():
    workers = Path(__file__).resolve().parents[1] / 'workers'
    if str(workers) not in sys.path: sys.path.insert(0, str(workers))
    for name, path in [('report_generation', workers/'report_generation'),
                       ('report_generation.core', workers/'report_generation/core')]:
        if name not in sys.modules:
            namespace = types.ModuleType(name); namespace.__path__ = [str(path)]
            sys.modules[name] = namespace
    module = importlib.import_module('report_generation.core.measured_feature_cards')
    return module.build_feature_observation_cards, module.build_quantitation_comparison_cards


def verify_consumers(tables, maximum_states=3):
    observe, compare = card_builders()
    examples = []
    for state in consumer_states(tables):
        observations = observe(state, minimum_points=1)
        comparisons = compare(state)
        if not observations: continue
        source = {r['condition']: r for r in state['vector_plot_raw_data']}
        # Validate every point, including nulls, against the source projection.
        for card in observations:
            for point in card['trajectory']:
                raw = source[point['condition']]
                for key, original in [('ptm_unadjusted_log2fc','U_joint'),
                                      ('protein_log2fc','P_joint'), ('ptm_protein_adjusted_log2fc','A'),
                                      ('time_minutes','time_min')]:
                    assert equivalent(point[key], raw[original]), (key, point, raw)
                for axis in ['unadjusted','protein','adjusted']:
                    assert set(point['axes'][axis]['control_sample_ids']) == set(raw['ptm_unadjusted_control_sample_ids'])
                    assert set(point['axes'][axis]['treatment_sample_ids']) == set(raw['ptm_unadjusted_treatment_sample_ids'])
        for card in comparisons:
            raw = source[card['condition']]
            for key, original in [('ptm_unadjusted_log2fc','U_joint'),
                                  ('protein_log2fc','P_joint'), ('ptm_protein_adjusted_log2fc','A')]:
                assert equivalent(card[key], raw[original]), (key, card, raw)
        examples.append({'consumer_state_id':state['consumer_state_id'],
                         'source_adapter_row_ids':state['source_adapter_row_ids'],
                         'source_rows':state['vector_plot_raw_data'],
                         'observation_cards':observations, 'comparison_cards':comparisons})
        if len(examples) >= maximum_states: break
    return examples


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
    names=['quant/summary','quant/comparisons','quant/runlevel','science/site_identity_audit',
           'science/localization_by_contrast','reader_adapter/form_identity','reader_adapter/form_contrasts',
           'reader_adapter/precursor_membership','reader_adapter/study_metadata']
    tables={k:pd.read_csv(a.package/(k+'.csv'),low_memory=False) for k in names}
    design=json.loads((a.package/'study/study_design.json').read_text())
    validate_card_inputs(tables,design)
    examples=verify_consumers(tables)
    assert examples, 'No representable form read by existing consumer'
    rows=tables['reader_adapter/form_contrasts']; states=list(consumer_states(tables))
    result={'run_id':a.package.name,'adapter_rows':len(rows),'forms':len(tables['reader_adapter/form_identity']),
            'eligible_rows':int(rows.card_input_eligible.sum()),'supported_consumer_states':len(states),
            'restriction_counts':rows.restriction_reasons.fillna('').str.split(';').explode().value_counts().to_dict(),
            'all_row_values_ids_NA_masks':'passed','representative_existing_consumer_states':len(examples),
            'production_findings_selected':False,'validation_scope':'existing_tables_and_consumer_input_parity'}
    for name,value in [('CARD_INPUT_VALIDATION.json',result),('CARD_INPUT_EXAMPLES.json',examples)]:
        (a.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
