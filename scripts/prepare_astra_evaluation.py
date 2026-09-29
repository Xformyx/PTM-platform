"""Freeze a rubric and matched-input report evaluation plan; does not run a model."""
import argparse,hashlib,json,shutil
from pathlib import Path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reviews',type=Path,help='Optional blinded human-scored JSON records; never synthesized')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    root=a.package;snapshot=json.loads((root/'study/user_input_snapshot.json').read_text())
    rubric={'version':'astra_matched_inputs_evaluation.v1','fixed_before_model_generation':True,
        'dimensions':{k:{'denominator':d,'measure':m} for k,d,m in [
            ('numeric_accuracy','audited numeric claims','incorrect numeric/mask/denominator claims'),
            ('traceability','main claims','claims with correct row and source links'),
            ('overinterpretation','all audited claims','biological n, p/q, occupancy, causality and directness errors'),
            ('evidence_retention','predeclared challenge cases','omitted correction/emergence/protein/opposing evidence'),
            ('kinase_interpretation','kinase claims','candidate/activity/abundance/tier/ambiguity errors'),
            ('temporal_interpretation','temporal claims','grid, mask, bracket or recovery errors'),
            ('literature_comparison','audited paper comparisons','incorrect condition-aware concordance judgments'),
            ('citation_accuracy','citations','PMID/DOI/claim mismatches or fabricated source conclusions'),
            ('reproducibility_efficiency','review tasks','replay success, minutes to trace a value and duplicated computation') ]},
        'no_composite_winner_without_predeclared_weights':True,'biological_ground_truth':'unavailable_without_independent_experiment',
        'insulin_expected_pattern_is_not_ground_truth':True}
    (a.output/'rubric.json').write_text(json.dumps(rubric,indent=2))
    shared=[Path('inputs/PR.tsv'),Path('inputs/PG.tsv'),Path('inputs/reference.fasta'),Path('study/user_input_snapshot.json'),Path('study/study_design.json'),Path('references/literature_pin.json')]
    for doc in json.loads((root/'references/literature_pin.json').read_text()).get('documents',[]):
        if doc.get('package_file'):shared.append(Path(doc['package_file']))
    manifest={'status':'not_run_model_access_unavailable','rubric_sha256':sha(a.output/'rubric.json'),
        'model':{'name':None,'version':None,'prompt_version':'matched_report_prompt.v1','tool_budget':None,'time_budget':None,'context_budget':None,'sampling_repetitions':None},
        'arms':{'A':'same raw inputs, exact research facts/questions and permitted papers','B':'A plus platform evidence package','C':'optional frozen Generic v3 package; supply its original run hash'},
        'shared_inputs':[{'file':str(p),'sha256':sha(root/p)} for p in shared],
        'platform_manifest_sha256':sha(root/'manifest.json'),
        'fairness':'Fix identical external literature access and tool/time/context budgets before execution. Separate processing benefit from extra source-information benefit.',
        'blinding':'Randomize anonymous report labels before reviewers score; keep allocation key outside reviewer packet.',
        'results':[]}
    (a.output/'evaluation_manifest.json').write_text(json.dumps(manifest,indent=2))
    questions=(snapshot['original'].get('report_options') or {}).get('research_questions')
    prompt='Write the requested scientific report using the supplied study facts and questions. Preserve uncertainty, distinguish evidence from hypothesis, and cite primary sources. Include a claim-to-evidence table with exact numeric rows, statistical units and limitations. Do not invent localization, biological replication, p/q, occupancy or causal evidence. Compare study conditions across literature.\n\nOriginal research questions (identical in every arm):\n'+json.dumps(questions,ensure_ascii=False,indent=2)
    (a.output/'matched_report_prompt.md').write_text(prompt,encoding='utf-8')
    if a.reviews:
        reviews=json.loads(a.reviews.read_text())
        for r in reviews:
            if r.get('dimension') not in rubric['dimensions'] or not r.get('anonymous_report_id') or not r.get('evidence_ref'):raise ValueError('Review requires blinded ID, rubric dimension and evidence')
            if not isinstance(r.get('numerator'),(int,float)) or not isinstance(r.get('denominator'),(int,float)) or not 0<=r['numerator']<=r['denominator']:raise ValueError('Invalid measured numerator/denominator')
        shutil.copyfile(a.reviews,a.output/'observed_reviews.json')
        (a.output/'review_rates.json').write_text(json.dumps([{**r,'rate':r['numerator']/r['denominator'] if r['denominator'] else None} for r in reviews],indent=2))
    print(json.dumps({'prepared':True,'actual_model_comparison':'not_run_model_access_unavailable'}))

if __name__=='__main__':main()
