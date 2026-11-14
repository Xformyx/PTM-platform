import json
from pathlib import Path
import pandas as pd
from test_substrate_signal_flow import fixture,kinase_fixture
from ptm_shared.annotation_registry import digest
from ptm_shared.astra_package import write_tables
from ptm_shared.astra_evidence_catalog import write_evidence_access, EvidenceCatalog
from ptm_shared.generic_workflow import json_write
from ptm_shared.substrate_signal_reader import write_signal_flow,PACKET_PATH,load_report_signal
from ptm_shared.substrate_signal_view import signal_page


def test_saved_projection_to_catalog_claim_figure_and_writer(tmp_path):
    root,tables,design,registry=fixture(tmp_path)
    kinase_fixture(tables,design,registry)
    dictionary=write_tables(tables,root)
    json_write(root/'reproducibility/data_dictionary.json',dictionary)
    write_evidence_access(root)
    before={n:digest(root/n) for n in dictionary}
    artifacts,contract=write_signal_flow(root,tables)
    assert contract['status']=='available'
    c=EvidenceCatalog(root)
    page=signal_page(c,'substrate_trajectories',{'track':'A'})
    assert page['total_count']==1
    packet=json.loads((root/PACKET_PATH).read_text())
    assert packet['bundle_evidence'] and packet['hypothesis_evidence']
    observation=packet['representative_observations'][0]
    for p in observation['points']:
        r=p['source_ref'];row=c.source_rows(r['source_table'],[r['source_key']])[0]
        assert p['U_joint']-p['P_joint']==p['A']==row['A']
        citation={**r,'run_id':'actual-fixture-run','catalog_id':c.catalog['catalog_id']}
        checked=c.check_claims([{'claim_id':p['contrast_id'],'run_id':'actual-fixture-run','catalog_id':c.catalog['catalog_id'],
            'evidence_refs':[citation],'field_path':'A','asserted_value':p['A'],'unit':'log2_ratio','claim_level':'relative_effect',
            'target_time_min':p['time_min'],'reference_condition_id':p['reference_condition_id']}])
        assert checked['claims'][0]['numeric_status']=='passed'
    # Seal a small fixture boundary for the production report loader, not a new scientific run.
    files={name:{'sha256':digest(root/name),'bytes':(root/name).stat().st_size} for name in artifacts}
    json_write(root/'manifest.json',{'files':files})
    json_write(tmp_path/'enrichment_free_current.json',{'run_id':'actual-fixture-run','artifacts':{'provenance':{'path':'source/provenance.json','sha256':digest(root/'provenance.json')}}})
    loaded=load_report_signal(tmp_path)
    from report_generation.core.dynamic_prompt_generator import format_temporal_evidence_packet_for_llm
    from report_generation.core.biological_synthesis import format_biological_synthesis_packet_for_llm
    from report_generation.core.figure_manifest import saved_signal_figure
    for text in [format_temporal_evidence_packet_for_llm({'status':'unavailable','substrate_signal_flow':loaded}),
                 format_biological_synthesis_packet_for_llm({'substrate_signal_flow':loaded},section_type='results')]:
        assert observation['trajectory_id'] in text and 'K1' in text and 'not_performed' in text
    figure=saved_signal_figure(loaded)
    assert figure['quantitative_bindings'][0]['trajectory_id']==observation['trajectory_id']
    assert figure['quantitative_bindings'][0]['source_ref']==observation['points'][0]['source_ref']
    assert before=={n:digest(root/n) for n in before}
    replay=tmp_path/'replay';(replay/'reader').mkdir(parents=True)
    # The same registered source catalog is input; no source files are copied.
    json_write(replay/'reader/evidence_catalog.json',c.catalog)
    rebuilt,_=write_signal_flow(replay,tables,source_root=root)
    assert all(digest(root/name)==digest(replay/name) for name in rebuilt)


def test_excluded_finite_a_is_trace_not_heatmap_cell():
    from test_astra_figures import fixture_tables
    from ptm_shared.astra_figures import heatmap_grid
    design,tables=fixture_tables()
    frame=tables['quant/comparisons'].copy();frame['included']=True
    row=frame.loc[frame.A.notna()].index[0];frame.loc[row,'included']=False
    original=frame.copy(deep=True)
    grid,*_=heatmap_grid(frame,'form_id','contrast_id','A',design)
    r=frame.loc[row]
    assert pd.isna(grid.loc[r.form_id,r.contrast_id])
    pd.testing.assert_frame_equal(frame,original)


def test_display_refresh_preserves_unrelated_figure_bytes(tmp_path):
    from test_astra_figures import fixture_tables
    from ptm_shared.astra_figures import figure_packet
    design,tables=fixture_tables()
    figure_packet(tables,tmp_path,design)
    before={p.name:digest(p) for p in (tmp_path/'figures').iterdir()}
    legends=json.loads((tmp_path/'figures/figure_legends.json').read_text())
    tables['quant/comparisons']['included']=False
    figure_packet(tables,tmp_path,design,figure_names={'substrate_contrast_heatmap'})
    for name,h in before.items():
        if not name.startswith('substrate_contrast_heatmap') and name!='figure_legends.json':
            assert digest(tmp_path/'figures'/name)==h
    after=json.loads((tmp_path/'figures/figure_legends.json').read_text())
    assert [r for r in legends if r['figure_id']!='substrate_contrast_heatmap']==[r for r in after if r['figure_id']!='substrate_contrast_heatmap']
    assert all(r['source_table'] for r in after)
