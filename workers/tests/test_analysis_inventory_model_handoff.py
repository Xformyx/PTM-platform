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
