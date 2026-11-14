"""Package/report projections of saved substrate evidence, without new science."""
import json
from pathlib import Path

import pandas as pd

from .annotation_registry import digest
from .astra_card_inputs import encode, clean
from .astra_evidence_catalog import CATALOG, read_source
from .generic_workflow import json_write, object_hash
from .substrate_signal_flow import (VERSION, TABLE_KEYS, TRAJECTORIES, KINASES, KINASE_MEMBERS,
                                   LINKS, HYPOTHESES, project_signal_flow)

GUIDE_PATH='reader/SUBSTRATE_SIGNAL_FLOW.md'
PACKET_PATH='reader/substrate_signal_packet.json'
FIGURE='reader/substrate_UPA_trajectories.svg'
INPUT_TABLES={'quant/comparisons','reader_adapter/form_identity','temporal/ptm_temporal_features',
    'kinase/kinase_candidate_edges','kinase/substrate_contributions','kinase/kinase_temporal_profiles',
    'temporal/kinase_fixed_membership','temporal/target_excluded_anchors','kinase/candidate_sensitivity',
    'science/inference_results','kinase/method_scores','kinase/method_membership'}

GUIDE='''# 기질 시간 반응으로 신호 흐름 검토하기

전체 기질 → form U_joint/P_joint/A → kinase-associated substrate bundle → 알려진 관계와 관측 순서 → 검토할 가설 순서로 읽으세요.
이 읽기 순서는 substrate가 kinase를 활성화한다는 생물학적 화살표가 아닙니다.

`signal_flow/substrate_trajectories.csv`와 `substrate_bundle_membership.csv`는 전체 form/효과 scope/track입니다.
`kinase_substrate_bundles.csv`, `kinase_substrate_membership.csv`에는 실제 edge/contribution/method ID, variable/fixed 결과와 제외 진단이 있습니다.
`temporal_evidence_links.csv`, `downstream_hypotheses.csv`는 membership, 계산 의존성, 관측 선후, exact prior, 가설을 구분합니다.
각 source_ref의 table/key/hash를 catalog `source`/batch bundle로 resolve하세요. 과거 citation은 새 catalog에 재귀속하지 않습니다.

표시 개수·pin·선정 finding·페이지는 전체 population이 아닙니다. 그림은 유효 관측점 수 다음 안정 ID 순의 preview이며 중요도나 활성 순위가 아닙니다.
그림 밖 form도 전체 trajectory 및 원본 quant 표에 있습니다. 카드 보류·no-call은 접근 제한이나 비활성 판정이 아닙니다.
reference는 실행 snapshot의 각 point에 기록됩니다. shared/matched와 target-first 변화는 다른 quantity입니다.
U_joint−P_joint=A는 동일 joint mask의 log2 효과입니다. U_all/P_all은 별도 관측 집합입니다. A는 절대 occupancy가 아닙니다.
included=false의 유한 값은 calculation trace이며 일반 반응/순위/그림 값이 아닙니다. NA를 0으로 바꾸거나 gap을 잇지 않습니다.

kinase footprint는 기존 gene-balanced 값입니다. native method는 고유 점수/null/family를 따르며 log2 footprint와 합산하지 않습니다.
fixed-common NA는 0/flat이 아닙니다. 첫 entered membership는 초기 집합 구성입니다. 동일 support 후보 집합은 curated family가 아닙니다.
같은 실험의 gene/group 제외·parent sensitivity는 독립 검증이 아닙니다. source에서 기록한 no-call/localization/calibration 제한을 보존합니다.
관측 bracket의 선후는 실제 activation time/직접 전달의 증명이 아닙니다. exact prior가 없어도 측정 궤적을 설명하고 missing prior를 별도로 표시하세요.

보고서는 ①시점별 U/P/A ②전체 kinase 기질·반대 관측·구별 불가 ③prior/문헌과 일치·불일치·평가불가
④검토할 시간 흐름 가설 ⑤공통 원인/phosphatase/위치/부모단백질/membership 대안 ⑥구별할 후속 검증 순으로 작성하세요.
예: “후보와 연결된 기질의 A 반응이 초기 관측 구간에 함께 나타났다”는 탐색적 association입니다. 직접 kinase 활성 확정은 아닙니다.
U≈0/P<0/A>0이면 비보정 PTM 자체의 증가라고 쓰지 마세요. 생물학적 p/q 미계산을 significant로 표현하지 마세요.
파일 전달·mechanical anchor 검증은 문헌 의미 승인이나 AI 전체 검토 완료가 아닙니다.

[작성 packet](substrate_signal_packet.json) · [U/P/A 그림](substrate_UPA_trajectories.svg) · [전체 catalog](EVIDENCE_ACCESS.md)
저장 표 기반 재현: `python reader_replay.py --output <새 경로>`; archive 자체 코드 replay와 현재 코드 revision은 별개입니다.
'''


def report_packet(outputs):
    a=outputs[TRAJECTORIES].loc[outputs[TRAJECTORIES].track.eq('A')].sort_values(
        ['eligible_points','trajectory_id'],ascending=[False,True])
    selected=a.loc[a.eligible_points.gt(0)].head(12)
    selection=[{'trajectory_id':r.trajectory_id,'selected':r.trajectory_id in set(selected.trajectory_id),
                'eligible_points':int(r.eligible_points),'reason':'finite_observation_count_then_stable_id_preview'} for r in a.itertuples()]
    by_scope={(r.form_id,r.effect_series_id,r.track):r for r in outputs[TRAJECTORIES].itertuples()}
    bundles=outputs[KINASES].to_dict('records');observations=[]
    for r in selected.itertuples():
        tracks={track:json.loads(by_scope[r.form_id,r.effect_series_id,track].points_json)
                for track in ('U_joint','P_joint','A') if (r.form_id,r.effect_series_id,track) in by_scope}
        points=[]
        for p in json.loads(r.points_json):
            points.append({**p,**{track:next(q['value'] for q in values if q['contrast_id']==p['contrast_id']) for track,values in tracks.items()}})
        related=[b['bundle_id'] for b in bundles if b['effect_series_id']==r.effect_series_id
                 and r.form_id in json.loads(b['association_form_ids_json'])]
        observations.append({'trajectory_id':r.trajectory_id,'form_id':r.form_id,'effect_series_id':r.effect_series_id,
            'identity':json.loads(r.identity_json),'points':points,'bundle_ids':related,
            'saved_feature':json.loads(r.feature_json),'quantity':'joint_log2_contrast','unit':'log2_ratio',
            'figure_binding':{'figure':FIGURE,'trajectory_id':r.trajectory_id,'points':'reader/substrate_UPA_points.csv'}})
    related_ids={bid for o in observations for bid in o['bundle_ids']}
    bundle_preview=sorted([b for b in bundles if b['bundle_id'] in related_ids],key=lambda b:b['bundle_id'])[:12]
    preview_ids={b['bundle_id'] for b in bundle_preview}
    return {'schema_version':VERSION,'status':'available','scope':'all_saved_eligible_and_trace_rows',
        'population':{k:len(v) for k,v in outputs.items()},'full_sources':{k:k+'.csv' for k in outputs},
        'preview_selection':selection,'representative_observations':observations,
        'related_bundle_total':len(related_ids),'bundle_preview_count':len(bundle_preview),
        'bundle_evidence':[{k:(json.loads(v) if k.endswith('_json') else v) for k,v in b.items()} for b in bundle_preview],
        'hypothesis_evidence':[{k:(json.loads(v) if k.endswith('_json') else v) for k,v in h.items()}
            for h in outputs[HYPOTHESES].to_dict('records') if h['bundle_id'] in preview_ids],
        'preview_is_not_analysis_or_review_scope':True,'hypothesis_source':HYPOTHESES+'.csv',
        'literature_status_source':'reader/EXECUTION_STATUS.json','semantic_review_status':'not_performed',
        'scientific_calls':0,'search_calls':0,'model_calls':0,
        'report_sections':['measured_substrate_UPA','kinase_full_support_and_counterevidence','known_priors_and_disagreement',
            'reviewable_signal_flow_hypotheses','alternative_explanations','discriminating_followup'],
        'interpretation':'association_and_observed_order_not_direct_causal_activation'}


def draw_trajectories(directory, packet, source_root=None):
    import shutil
    points=[{'trajectory_id':o['trajectory_id'],'form_id':o['form_id'],
        **{k:r.get(k) for k in ('contrast_id','time_min','reference_condition_id','reference_time_min','U_joint','P_joint','A','status')},
        'source_ref_json':encode(r['source_ref'])} for o in packet['representative_observations'] for r in o['points']]
    points_name='reader/substrate_UPA_points.csv'
    pd.DataFrame(points,columns=['trajectory_id','form_id','contrast_id','time_min','reference_condition_id','reference_time_min','U_joint','P_joint','A','status','source_ref_json']).to_csv(Path(directory)/points_name,index=False)
    images=[FIGURE,'reader/substrate_UPA_trajectories.png']
    if source_root is not None and all((Path(source_root)/n).is_file() for n in images+[points_name]):
        # Archive replay verifies all source manifest hashes. Rebuild bindings,
        # then reuse the frozen rendering to avoid host font discovery/changes.
        if digest(Path(directory)/points_name)!=digest(Path(source_root)/points_name):
            raise ValueError('Frozen signal figure point bindings differ')
        for name in images:shutil.copyfile(Path(source_root)/name,Path(directory)/name)
        return images+[points_name]
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    observations=packet['representative_observations']; n=max(1,len(observations))
    with matplotlib.rc_context({'svg.hashsalt':'substrate_signal_flow.v1'}):
        fig,axes=plt.subplots(n,1,figsize=(10,2.6*n),squeeze=False)
        for ax,observation in zip(axes[:,0],observations):
            rows=observation['points'];valid=[r for r in rows if r['time_min'] is not None]
            for track in ('U_joint','P_joint','A'):
                ax.plot([r['time_min'] for r in valid],[r.get(track) if r.get(track) is not None else float('nan') for r in valid],marker='o',label=track)
            ax.set_title(observation['form_id']+' / '+observation['effect_series_id'],fontsize=8)
            ax.set_xlabel('Actual target time (minutes); point-specific Control in source');ax.set_ylabel('log2 contrast');ax.legend(fontsize=7)
        if not observations:axes[0,0].text(.1,.5,'No eligible saved observations')
        fig.tight_layout();fig.savefig(Path(directory)/FIGURE,metadata={'Date':None})
        fig.savefig(Path(directory)/'reader/substrate_UPA_trajectories.png',dpi=110,metadata={'Software':VERSION});plt.close(fig)
    return images+[points_name]


def write_signal_flow(directory,tables,*,source_root=None):
    from .astra_package import write_tables
    directory=Path(directory);root=Path(source_root or directory)
    catalog=json.loads((directory/CATALOG).read_text())
    design_path=root/'study/study_design.json'
    if not design_path.is_file():
        return [], {'status':'unavailable','reason':'executed_design_snapshot_missing'}
    design=json.loads(design_path.read_text())
    # Saved CSV bytes are authoritative in both normal publication and replay.
    # This also preserves the existing empty-cell/null serialization contract.
    saved={}
    for name in sorted(INPUT_TABLES):
        meta=catalog['sources'].get(name+'.csv')
        if meta is None:continue
        path=root/(name+'.csv')
        if digest(path)!=meta['sha256']:raise ValueError('Signal source hash mismatch: '+name)
        saved[name]=read_source(root,name+'.csv',meta)
    outputs=project_signal_flow(saved,design,catalog['sources'])
    entries=write_tables(outputs,directory)
    for name,meta in entries.items():
        meta.update(unique_key=TABLE_KEYS[name[:-4]],row_grain=TABLE_KEYS[name[:-4]])
        catalog['sources'][name]={**meta,'sha256':digest(directory/name),'descriptor_schema_version':VERSION,
            'availability':'available' if meta['rows'] else 'available_empty','role':'saved_signal_projection','indexed':False,
            'access':'registered_source_and_canonical_key','independent_observation_count':None}
    if source_root is None:
        path=directory/'reproducibility/data_dictionary.json';dictionary=json.loads(path.read_text());dictionary.update(entries);json_write(path,dictionary)
    catalog['catalog_id']=object_hash({k:v for k,v in catalog.items() if k!='catalog_id'});json_write(directory/CATALOG,catalog)
    packet=report_packet(outputs)
    json_write(directory/PACKET_PATH,packet)
    (directory/GUIDE_PATH).write_text(GUIDE,encoding='utf-8')
    artifacts=[name+'.csv' for name in outputs]+[PACKET_PATH,GUIDE_PATH]+draw_trajectories(directory,packet,source_root)
    return artifacts,{'status':'available','schema_version':VERSION,'guide':GUIDE_PATH,'packet':PACKET_PATH,
                      'full_sources':packet['full_sources'],'population':packet['population'],'review_status':'not_performed'}


def load_report_signal(order_root):
    """Consume the published snapshot, never the current draft or a guessed form."""
    from .substrate_signal_view import published_root
    from .astra_evidence_catalog import safe_path
    try:
        root=published_root(order_root)
        manifest=json.loads((root/'manifest.json').read_text()); entry=manifest['files'].get(PACKET_PATH)
        if not entry:return {'status':'unavailable','reason':'saved_signal_packet_missing'}
        path=safe_path(root,PACKET_PATH)
        if digest(path)!=entry['sha256']:raise ValueError('Signal report packet hash mismatch')
        packet=json.loads(path.read_text())
        return {**packet,'source_run_id':json.loads((root/'provenance.json').read_text())['run_id'],
                'source_packet_sha256':entry['sha256'],'source_package_root':str(root)}
    except FileNotFoundError:
        return {'status':'unavailable','reason':'published_astra_snapshot_unavailable'}


def format_signal_report(packet):
    if not packet or packet.get('status')!='available':return ''
    # Full display-selection ledger is stored, not repeated in every prompt.
    view={k:v for k,v in packet.items() if k!='preview_selection'}
    return ('\n=== SAVED SUBSTRATE SIGNAL EVIDENCE ===\n'+encode(view)+
        '\nDescribe concrete U/P/A points and linked substrate associations, contrary evidence, known priors, hypotheses and alternatives. '
        'Resolve full_sources beyond this preview. No-call is not inactivity; earlier response is not direct activation. '
        'Use the exact quantity/source/Control; semantic review remains not_performed.\n')
