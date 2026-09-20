from report_generation.core.reader_authoring import build_authoring_packet
from report_generation.core.section_model_packet import build_section_model_packet


def test_full_analysis_scope_and_revision_survive_section_compaction():
    inventory={'analysis_revision':'synthetic-revision','input_revision':'synthetic-input',
        'analysis_manifest_id':'synthetic-manifest','coverage':{'analysis_features':500,'mapped_features':90},
        'execution_status':'completed','evaluation_status':'evaluated','track_status':{'relative':'evaluated','occupancy':'not_evaluable'},
        'input_scope':{'quick_analysis':True},'artifact_directory':'.analysis_results/synthetic',
        'inventory':[{'feature_id':f'synthetic-{i}','candidate_status':'unassigned'} for i in range(500)]}
    packet=build_authoring_packet({'analysis_evidence_inventory':inventory})
    for stage in (0,5):
        model=build_section_model_packet(packet,None,'results',compaction_stage=stage)
        frame=next(card for card in model['reader_cards'] if card['category']=='study_frame')
        scope=frame['analysis_scope_contract']
        assert scope['analysis_revision']=='synthetic-revision'
        assert scope['coverage']['analysis_features']==500
        assert scope['track_status']['occupancy']=='not_evaluable'
        assert scope['input_scope']['quick_analysis'] is True
        assert 'inventory' not in scope


def test_pinned_pathway_values_and_evidence_ids_reach_writer_packet():
    from ptm_shared.pathway_membership_index import build_pathway_result
    data=build_pathway_result({'conditions':['1min','5min']},
        {'features':{'F':{'protein_group':'P','fasta_taxonomy_id':'10090'}},'ptm_timeseries':{'F':{'1min':0.,'5min':2.}}},
        [{'pathway_key':'PW-test','name':'Synthetic path','protein_accessions':['P'],'taxon':'10090'}],
        {'status':'available','sha256':'synthetic-reference'})
    packet=build_authoring_packet({'analysis_evidence_inventory':{'pathway_result':data,
        'evidence_bundle_id':'synthetic-bundle','component_revisions':{'pathway':'synthetic-pathway-revision'}}})
    cards=[c for c in packet['reader_cards'] if c.get('category')=='pathway_context']
    assert len(cards)==1
    values=cards[0]['value_records']
    assert [v['value'] for v in values]==[0.,2.]
    assert all(v['evidence_id'] in cards[0]['evidence_ids'] for v in values)
    from report_generation.core.reader_authoring import deterministic_authoring_plan, focus_authoring_packet
    plan=deterministic_authoring_plan(packet)
    packet=focus_authoring_packet(packet,plan)
    for stage in (0,5):
        projected=build_section_model_packet(packet,plan,'results',compaction_stage=stage)
        # Typed numeric context must survive the model projection, including 0.
        path=next(c for c in projected['reader_cards'] if c.get('category')=='pathway_context')
        assert [v['value'] for v in path['value_records']]==[0.,2.]
