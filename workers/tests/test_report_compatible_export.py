import json
import pandas as pd
from preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer
from ptm_shared.report_compatible_export import artifact_names


def test_complete_preprocessing_exports_separate_form_mode_and_truthful_provenance(tmp_path):
    samples = ['c1','c2','c3','t1','t2','t3']
    condition_map = {s:'Control' if s[0]=='c' else '5min' for s in samples}
    manifest = {'samples':[{'sample_id':s,'condition':c,'biological_unit':c} for s,c in condition_map.items()],
                'conditions':[{'condition':'Control','time_minutes':0},{'condition':'5min','time_minutes':5}]}
    fasta = tmp_path / 'reference.fasta'
    fasta.write_text('>sp|P12345|EXAMPLE Example OS=Rattus norvegicus OX=10116 GN=GENE\nMPEPASKAAAZZ\n')
    rows = []
    for sequence, modified, charge, values in [
        ('ASK','AS(UniMod:21)K',2,[100,110,90,200,220,180]),
        ('ASK','AS(UniMod:21)K',3,[10,11,9,20,22,18]),
        ('PEP','PEP',2,[1000]*6), ('AAA','AAA',2,[2000]*6)]:
        rows.append({'Protein.Group':'P12345','Protein.Ids':'P12345','Protein.Names':'EXAMPLE','Genes':'GENE',
            'First.Protein.Description':'Example','Proteotypic':1,'Stripped.Sequence':sequence,'Modified.Sequence':modified,
            'Precursor.Charge':charge,'Precursor.Id':modified+str(charge), **dict(zip(samples,values))})
    pr,pg = tmp_path/'pr.tsv',tmp_path/'pg.tsv'
    pd.DataFrame(rows).to_csv(pr,sep='\t',index=False)
    pd.DataFrame([{'Protein.Group':'P12345','Protein.Ids':'P12345','Protein.Names':'EXAMPLE','Genes':'GENE',
        'First.Protein.Description':'Example','N.Sequences':2,**{s:1000 for s in samples}}]).to_csv(pg,sep='\t',index=False)
    output = tmp_path/'output'
    analyzer = PTMQuantificationAnalyzer(str(fasta),str(output),condition_map=condition_map,
        sample_manifest=manifest,normalization_policy='already_normalized.v1',
        quantitation_export_mode='legacy_plus_report_compatible.v1')
    analyzer.motif_analyzer = None
    assert analyzer.run_analysis(str(pr),str(pg))
    assert all((output/name).exists() for name in artifact_names('_phospho'))
    forms = pd.read_csv(output/'report_compatible_summary_phospho.tsv',sep='\t')
    assert len(forms) == 1
    assert forms.iloc[0].A_log2FC_5 == 1
    vector = pd.read_csv(output/'ptm_vector_data_normalized_phospho.tsv',sep='\t')
    assert len(vector) == 2
    assert vector.PTM_Unadjusted_P_Value.isna().all()
    assert vector.q_value.isna().all()
    provenance = json.loads((output/'normalization_provenance_phospho.json').read_text())
    assert provenance['sample_scaling_status'] == 'not_performed'
    assert provenance['samples_scaled'] == 0
    assert provenance['upstream_quantity_scale_status'] == 'unknown_not_recorded'
