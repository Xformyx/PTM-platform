import csv
import pytest
from ptm_shared.vector_columnar import publish_vector_columnar, VectorColumnar
from ptm_shared.vector_plot import project_plot_row


def test_roundtrip_density_duplicates_and_exact_drilldown(tmp_path):
    rows = [{"Gene.Name":"Rps6","PTM_Position":"S1","Precursor.Id":f"p{i}","Condition":"5min",
             "PTM_ProteinAdjusted_Log2FC":v,"Protein_Log2FC":x} for i,(v,x) in enumerate(((0,0),(2,1),(-90,-40),(None,5),(2,1)))]
    with (tmp_path/"ptm_vector_data_normalized_phospho.tsv").open("w") as f:
        writer=csv.DictWriter(f,fieldnames=rows[0],delimiter="\t");writer.writeheader();writer.writerows(rows)
    publish_vector_columnar(tmp_path,"_phospho")
    store=VectorColumnar(tmp_path,"_phospho")
    try:
        assert store.manifest_counts()["source_rows"]==5
        density=store.density()
        assert density["count"]==sum(b["count"] for b in density["bins"])==4
        assert density["bounds"]==[-40,1,-90,2]
        page=store.feature_page(limit=2)
        second=store.feature_page(limit=2,after=page["next_cursor"])
        assert set(page["feature_ids"]).isdisjoint(second["feature_ids"])
        fid=project_plot_row(rows[0])["feature_id"]
        trajectory=store.trajectories([fid])
        assert trajectory[0]["ptm_protein_adjusted_log2fc"]==0
        assert trajectory[0]["source_record"]["Gene.Name"]=="Rps6"
        exact=store.coordinate_page(bounds=[-40,1,-90,2],condition="5min")
        assert len(exact["observations"])==4
        lasso=store.coordinate_page(bounds=[-40,1,-90,2],condition="5min",polygon=[[-.5,-.5],[1.5,-.5],[1.5,2.5],[-.5,2.5]])
        assert len(lasso["observations"])==3  # distinct IDs at the same coordinate survive
        assert {r["feature_id"] for r in lasso["observations"]} == {project_plot_row(rows[i])["feature_id"] for i in (0,1,4)}
    finally: store.close()


def test_unresolved_and_malformed_rows_have_a_full_cursor_without_fake_ids(tmp_path):
    (tmp_path/'ptm_vector_data_normalized_phospho.tsv').write_text(
        'Gene.Name\tPTM_Position\tPrecursor.Id\tCondition\tPTM_ProteinAdjusted_Log2FC\n'
        'Rps6\tS1\tp1\t1min\t0\nRps6\tS1\t\t1min\t2\nRps6\tS1\tp2\t1min\t3\tEXTRA\n')
    publish_vector_columnar(tmp_path,'_phospho')
    store=VectorColumnar(tmp_path,'_phospho')
    try:
        counts=store.manifest_counts()
        assert counts['source_rows']==3 and counts['identified_features']==1
        page=store.diagnostics(limit=1)
        assert page['count']==2 and len(page['records'])==1
        tail=store.diagnostics(after=page['next_cursor'],limit=1)
        assert tail['next_cursor'] is None
        assert 'EXTRA' in str(tail['records'][0]['source_record'])
        assert tail['records'][0]['feature_id'] is None
        assert store.diagnostics(kind='malformed_source_row')['count']==1
    finally:store.close()
