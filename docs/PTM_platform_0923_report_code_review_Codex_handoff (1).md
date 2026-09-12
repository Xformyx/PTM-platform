**PTM Platform 09시23분 보고서 평가와 Codex 개발 지침**

검토일: 2026년 9월 12일. 검토 대상 보고서: Insulin_Signaling_V3_260912_report_260912_0923.docx, 14쪽.
코드 기준: Xformyx/PTM-platform, main의 2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6.
기준 커밋 시각: 2026-09-12 06:19:51 UTC. 보고서에 생성 커밋과 시간대가 없어 이 코드가 첨부 DOCX를 생성한 버전인지는 확정할 수 없다.

**판정**

정량식과 de novo 표시 제한은 개선됐다. 그러나 보고서는 여전히 분석 결과를 확인하는 초안 수준이며, 핵심 생물학적 결론과 주요 수치를 그대로 외부 보고서나 논문에 재사용하기에는 수정할 부분이 있다. 현재 main에서 일부 권고가 구현된 것은 확인했지만, 통계 필드 전달과 품질 등급, 문장 검증, 길이 정책에 실제 결함이 남아 있다. Gemini 모델 변경보다 이 경로를 먼저 고치는 것이 효과적이다.

이번 작업은 읽기와 검토였다. 원격 코드, 브랜치, 커밋을 변경하지 않았다. 보고서 생성·정량 계산 전체를 재실행하지 않았고 Gemini API도 호출하지 않았다. 기존 소스의 독립적으로 실행 가능한 검증 함수 17개를 직접 실행해 모두 통과했다. 이 환경에는 pytest가 없어 pytest 전체 실행으로 간주해서는 안 된다. 별도 소규모 입력으로 아래 결함을 재현했다.

비교에 사용한 enriched JSON과 정량 TSV는 이전 21시58분 보고서에 첨부된 데이터다. 새 09시23분 실행의 데이터라고 간주하지 않았다. 같은 수치가 반복되는 사례의 이전 근거를 확인하는 용도로만 사용했다.

**이전 권고의 반영 상태**

| 항목 | 판정 | 보고서와 코드에서 확인한 내용 |
|---|---|---|
| 보정값을 단순 U−G로 설명하던 문제 | 반영 | 3쪽과 4쪽에서 sample-wise PTM/protein 비율을 먼저 계산하고, 조건별 산술평균의 비를 log2로 변환한다고 설명한다. reconstructed 값도 독립 측정과 구분한다. |
| GTSE1 등 control-undetected 값의 conventional heatmap 유입 | 표시 개선, 전체 데이터 검증은 미완료 | 8쪽 그림의 극단적인 약 ±23 범위가 약 ±6으로 줄고 conventional eligibility를 명시한다. 현재 selector도 각 조건의 eligibility를 검사한다. 새 실행의 모든 행이 적절히 제외됐는지는 해당 실행의 manifest/입력으로 확인해야 한다. |
| precursor 식별 유지 | 카드와 그림은 개선, 본문은 미완료 | 10쪽 Figure 3에서 AARSD1 S88 1분과 5분의 PF ID가 다르다. 6쪽과 11쪽 본문은 이를 같은 feature의 시간 변화처럼 연결한다. |
| 낮은 반복 수·통계 지원을 가진 대표 사례 | 미완료 | ACIN1 S216이 Abstract와 본문, Figure 3의 대표 사례로 남아 있다. 이전 첨부 데이터에서 이 행은 control 1회, 180분 treatment 2회 검출, unadjusted q값 결측이었다. 새 실행도 같은 지지 수준인지는 새 sidecar로 확인해야 한다. |
| 문장 후처리 손상 | 미완료 | 1쪽의 dephosphorylation 대체 문장, 2쪽·11쪽의 phosphorylation protein-abundance-adjusted relative PTM ratio, 여러 문단의 마침표 뒤 쉼표가 남는다. |
| 짧은 Conclusion과 RQ 답변 | 분량은 반영, 내용 압축은 미흡 | 공백 기준 Conclusion 166단어, 프로젝트 단어 계산 함수 기준 171단어. RQ 답변은 프로젝트 기준 260단어. Conclusion은 개별 수치 반복에 치우쳐 핵심 한계와 다음 검증 단계가 사라졌다. |
| partial time-course feature의 관측과 clustering 구분 | 소스에서 반영 | 불완전 grid도 display 가능하고 clustering eligibility는 별도로 계산한다. 해당 기존 테스트도 통과했다. 새 본문에서는 이 개선이 유용한 초기 insulin 관측으로 연결되지 않았다. |
| kinase footprint 부재와 kinase 자체 PTM 관측 구분 | 설명 부족 | 평가 불가가 kinase 부재라는 뜻이 아니라는 설명은 좋다. 다만 별도로 관측 가능한 kinase precursor 결과를 보여주는 체계가 필요하다. |
| pair-window 분모와 인과 해석 제한 | 부분 반영 | Figure 2는 분모를 명시한다. 본문의 basal state 복귀, signal termination, negative feedback 추론은 concordance 감소만으로 입증되지 않는다. |
| 실험·통계 Methods | 미완료 | 세포명·시점·정량식은 있으나 생물학적/기술적 반복의 구분, 샘플 대응, 결측 처리, 통계 검정과 BH 적용 범위, localization 한계 등이 재현 가능한 수준으로 정리되지 않았다. |

U는 독립 unadjusted PTM contrast, A는 protein-adjusted PTM contrast, G는 linked protein contrast를 뜻한다. A가 U−G와 일반적으로 같지 않다는 현재 설명은 유지해야 한다. A는 절대 occupancy도 직접 kinase activity도 아니다.

**코드에서 확인한 우선 수정 사항**

아래 경로와 줄 번호는 검토 기준 커밋에 대한 것이다. Codex가 작업할 때 main이 바뀌었다면 먼저 현재 구현과 대조해야 한다. P1은 다음 보고서의 신뢰성 확보를 위해 우선 처리할 항목, P2는 설명력과 재현성을 높이는 후속 항목이다.

**P1 통계 필드가 projection과 카드 사이에서 유실된다**

위치:
- workers/report_generation/core/vector_projection.py, project_report_vector_row, 95–96행
- workers/report_generation/core/measured_feature_cards.py, _point_quality, 208–229행
- 같은 파일 build_quantitation_comparison_cards, 486–491행

projection은 보정된 통계를 ptm_protein_adjusted_p_value / ptm_protein_adjusted_q_value로 내보낸다. 소비자는 PTM_Relative_Q_Value, ptm_relative_q_value, q_value 등을 찾으며 이 canonical 이름을 읽지 않는다.

재현: 원본 adjusted q=0.001 → projected adjusted q=0.001 → 비교 카드 adjusted q=null. 관측 카드도 q_supported=false가 됐다. 즉 통계가 없었던 것이 아니라 전달 중 누락됐다.

수정: 하나의 정량 스키마와 필드 접근자를 공유한다. raw→projection→card→prompt→render의 계약 테스트를 추가한다. adjusted와 unadjusted 통계는 각각의 축에 연결하고, 한 축의 q값으로 다른 축의 유의성을 대신하지 않는다. 가능하면 각 축의 유효 반복 수도 별도 필드로 전달한다.

완료 기준: adjusted q=0.001과 결측 unadjusted q를 가진 입력에서 출력에도 각각 0.001/null이 유지된다. p값도 동일하다. n 또는 q를 새로 만들어 채우지 않는다.

**P1 단일 조건 비교 카드는 모두 exploratory가 된다**

위치:
- measured_feature_cards.py, _narrative_quality_tier, 232–245행
- build_quantitation_comparison_cards, 492–495행과 506–512행

비교 카드 생성기는 한 조건의 point 하나를 _narrative_quality_tier에 전달한다. 그러나 이 함수는 high/moderate에 conventional_count≥2를 요구한다. 따라서 모든 단일 조건 비교가 exploratory로 떨어지고 품질 등급 우선 정렬이 작동하지 않는다.

재현: 같은 comparison class에서 control/treatment 3/3, q=0.001인 ZZZ_SUPPORTED와 1/2, q결측인 AAA_LOW_SUPPORT가 모두 exploratory가 됐다. 후자가 이름순으로 먼저 선택됐다.

수정: 시간 궤적 품질과 단일 feature-condition 비교 품질을 별도 함수로 평가한다. 또는 비교 카드에 전체 trajectory 품질을 명시적으로 결합하되 평가 단위를 분명히 한다. quality를 단순 관측 지원과 통계 지원으로 나누는 것도 적절하다.

완료 기준: 같은 비교 유형 안에서 충분한 반복과 적절한 통계 근거를 가진 카드가 우선된다. 단순한 보정 전후 부호 변화에는 biological_direction_inference_allowed=false를 유지한다. 두 값의 q<0.05만으로 보정 효과 자체가 통계적으로 검정됐다고 표현하지 않는다.

**P1 Gemini에 필요한 식별자와 통계가 전달되지 않고 문장 검증도 이를 확인하지 않는다**

위치:
- reader_authoring.py, format_authoring_packet_for_llm, 686–704행
- reader_authoring.py, validate_and_repair_sections, 1031–1163행
- scientific_semantics.py, _matching_feature_fact, 103–115행

카드에는 reader_feature_id, trajectory, replicate_support, statistical_support가 있지만, 일반 evidence card 프롬프트는 주로 reader_summary, 동사, boundary만 출력한다. 이 summary에는 PF ID와 n/q값이 포함되지 않는다. Figure card가 가진 selected_reader_feature_ids도 해당 프롬프트 부분에서 빠진다. 모델이 같은 gene/site의 서로 다른 precursor를 구분하기 어려워진다.

검증기는 evidence marker의 존재·등록 여부와 일부 용어를 검사하지만, 문장 안 숫자가 어떤 feature/condition/axis 값인지 대조하지 않는다. _matching_feature_fact도 gene와 residue 문자열만으로 첫 카드를 선택한다.

재현:
- 서로 다른 AARSD1 precursor 카드 두 개를 제공했는데도 “the same AARSD1 S88 feature”의 1분과 5분 설명을 그대로 retain했다.
- 입력 카드의 +0.141을 본문에서 +9.999로 바꾼 문장도 이 validator에서 retain됐다.
- 이 재현은 해당 validator의 범위를 보여준다. 서비스 전체의 모든 경로에 숫자 검증이 없다고 단정하는 것은 아니다.

수정:
1. Gemini 입력에 feature_id, condition, axis, 값, n, q, measurement_unit, localization 상태를 명시한다.
2. 새 구조화 출력에는 문장과 evidence references를 연결한다. 각 reference는 feature_id/condition/axis 또는 figure_key를 포함한다.
3. 숫자는 가능하면 LLM 자유 출력 대신 value token을 결정적으로 치환한다. 자유 숫자는 표시 정밀도에 따른 허용 오차 안에서 검증한다.
4. 동일 site라도 precursor가 다르면 별도 관측으로 서술한다. 공식적인 site aggregation이 있다면 aggregation rule과 구성 feature를 명시한다.
5. 본문에서 “Figure 1”을 인용한 측정값이 그 그림에 실제 포함되는지 검사한다.

완료 기준: 같은 gene/site에 precursor 둘을 둔 반례, 잘못된 condition, 잘못된 axis, +9.999 변조를 막는다. 서로 다른 precursor임을 명시한 올바른 비교는 허용한다.

**P1 안전한 배경 문장까지 치환하며 문법을 손상시킨다**

위치:
- scientific_semantics.py, repair_semantic_sentence, 118–194행
- scientific_semantics.py, normalize_reader_prose, 197–235행
- reader_authoring.py, occupancy 관련 처리, 1103–1106행

재현:
- “The orchestration of phosphorylation and dephosphorylation controls signaling.”이 “phosphorylation and decrease in the measured phosphorylation-feature contrast”로 변했다.
- “While phosphorylation increased, protein abundance remained stable.”에서 While만 삭제돼 comma splice가 생겼다.
- “phosphorylation stoichiometry”가 “phosphorylation protein-abundance-adjusted relative PTM ratio”로 변했다.
- “The measured signal remained.,”는 수정되지 않았고 language audit의 doubled_punctuation_count=0이었다.

이는 새 보고서의 실제 문장 손상과 같은 패턴이다. 현재 2e04f86의 bibliography 제외 수정은 좋은 조치지만, Introduction/Discussion 안의 정상적인 문헌 배경도 구분해야 한다.

수정: 문자열 금칙어 치환과 과학적 주장 검증을 분리한다. observation, literature_context, hypothesis를 구분하고 evidence scope에 따라 검증한다. 일반적인 phosphorylation/dephosphorylation 배경 설명을 current-data claim처럼 낮추지 않는다. 문장 재작성은 문제가 있는 문장 전체에 적용하고 숫자·ID·부정·인용을 고정한 뒤 다시 검증한다. 단순 접속사 삭제는 중단한다.

완료 기준: 정상 인용 배경과 부정문은 보존된다. 측정 데이터가 뒷받침하지 않는 기전 주장은 제한된다. 마침표 뒤 쉼표와 의미 중복 치환을 검출한다. 반복 적용해도 문장이 계속 바뀌지 않도록 한다.

**P1 길이 지시가 서로 충돌하고 압축이 결론의 의미를 잃게 한다**

위치:
- reader_authoring.py, SECTION_STORY_CONTRACT
- nodes/writer_node.py, SECTION_MIN_WORDS, 180–192행 및 1136–1147행
- common/llm_client.py, generate_with_retry, 388–478행
- scientific_semantics.py, _compress_plain_section 및 enforce_report_word_budgets, 242–337행

Conclusion story contract는 maximum_words=170이다. 하지만 실제 생성 재시도는 minimum_words=300을 전달한다. RQ도 story maximum=220과 생성 minimum=250이 충돌한다. 프롬프트 formatter는 maximum_words 자체를 출력하지 않고 최소 길이만 표시한다. 최종 압축은 Conclusion 180, RQ 260단어를 사용한다.

generate_with_retry는 긴 응답을 best_result로 선정하고 재시도 때 temperature를 올린다. _compress_plain_section은 앞에서부터 들어갈 문장을 고르므로 뒤쪽의 한계·다음 실험이 사라질 수 있다.

재현: 197단어 Conclusion을 180단어로 줄였을 때 마지막의 “does not establish causality”와 독립 검증 계획이 모두 삭제됐다. 길이 audit는 통과했다.

수정: 생성·재시도·검증·렌더가 하나의 section budget을 공유하도록 한다. 짧더라도 필요한 의미를 모두 담았으면 통과시킨다. 재시도는 실제 누락이나 오류를 대상으로 하며 단순히 단어 수를 늘리도록 하지 않는다. Conclusion은 핵심 결과, 의미, 한계, 다음 검증의 필수 역할을 보존한다. 모델별 권장 설정을 존중하며 temperature를 자동으로 올리는 로직을 제거한다.

완료 기준: 적절한 160단어 Conclusion을 300단어로 늘리기 위한 추가 호출이 발생하지 않는다. 최종 압축 후에도 한계와 다음 검증 문장이 남는다.

**P2 본문과 그림의 연결 및 표시 단위를 개선한다**

위치:
- figure_manifest.py, select_reader_heatmap_features 및 figure readability/binding 검사
- nodes/signal_flow_figure.py, generate_context_aware_ptm_heatmap
- reader_authoring.py의 figure card 프롬프트

8쪽 Figure 1은 20개 행을 그리면서 대략 절반의 행 이름을 생략한다. 특히 강한 색을 보이는 행의 이름이 가려져 독자가 해석하기 어렵다. 본문은 PLEC/VIM/SEPTIN9/GSTM2/AP3D1을 중심으로 서술하지만, 그림의 대표 예시와 본문을 직접 연결하는 근거를 제공하지 않는다. 새 실행의 전체 selected feature 명단이 없어 숨겨진 모든 행의 정체를 확인했다고 주장할 수는 없다.

소스에서 heatmap selection과 narrative observation selection이 별도로 수행된다. 기존 binding audit가 내부 식별자 유무를 확인하더라도 본문이 인용한 특정 관측과 실제 그림의 일치를 보장하지는 않는다.

추가 정적 결함: signal_flow_figure.py의 1059–1064행은 requested 항목을 순회하면서 이전 for-loop의 마지막 feature 변수를 참조한다. manifest 항목별 conditions/render_eligible 값이 달라지면 마지막 항목의 정책이 다른 행에도 적용될 수 있다. requested record에 항목 자체 또는 해당 조건·eligibility를 함께 저장한다.

수정:
- 핵심 관측 3–5개는 전체 이름과 PF ID를 표시하는 작은 trajectory panel로 제시한다.
- 요약 heatmap은 12–16행 정도로 조절하고 모든 행 이름을 남긴다.
- 축 이름을 실제 A 값인 protein-adjusted relative PTM log2 contrast로 통일한다.
- Figure 3에 n과 각 축의 q값/결측을 별도 표로 함께 제시한다.
- Figure 2는 동일 interval transition과 pair-window 분모를 유지하고, 표시하지 않은 pair state의 범위를 범례에 명확히 설명한다.
- 최종 DOCX의 실제 표시 크기에서 확인한다. PNG 해상도 검사만으로 글자 가독성을 보장하지 않는다.

**보고서의 과학적 내용을 더 좋게 만드는 수정**

1. 정량 사례를 먼저 검증한다. ACIN1 S216은 이전 데이터와 같은 n/q 상태라면 산술적인 보정 예제로 제한하고 Abstract의 주된 생물학적 증거에서는 우선순위를 낮춘다. q값이 없음을 유의하지 않음이나 변화 없음으로 바꾸지는 않는다.

2. 6쪽 AARSD1 문장은 다음 의미로 교정한다.
“동일한 S88 후보 주석에 연결된 서로 다른 두 modified precursor에서, 1분의 한 precursor는 +0.141→+0.295, 5분의 다른 precursor는 −0.296→−0.103으로 보정됐다. 이는 동일 precursor의 시간 변화에 대한 비교가 아니다.”
Figure 3에서 실제 식별자는 각각 PF-1BEF4E81과 PF-EC1CD6EC이다.

3. VIM의 parent-protein 변동을 QC 대상으로 올린다. 보고서 수치만 보면 5분 −2.387에서 15분 +2.009로 약 21배 차이가 난다. 이를 빠른 단백질 합성/분해의 증거로 바로 서술하지 않는다. 같은 protein group인지, 어떤 비수식 peptide가 기여했는지, 결측·정규화·sample mapping·추출성 차이가 영향을 주는지 확인한다. 실제 변화일 가능성을 배제하지 않되 단백질 변화가 의미를 바꾼다는 주장에 앞서 근거를 보강한다.

4. 비단조 궤적 자체를 post-receptor signaling defects의 증거처럼 설명하지 않는다. 현재 보고서에는 해당 결함이나 insulin resistance를 비교하는 조건이 제시되지 않는다. 마찬가지로 concordance loss는 pair state의 변화이며 개별 PTM이 baseline으로 돌아왔다는 뜻이 아니다.

5. 관측, 문헌상 조절 부위 주석, substrate footprint, perturbation 결과를 구분해 보여준다. 이전 첨부 자료에는 MAPK1/MAPK3의 TEY 이중 인산화 precursor 관측이 있었다. 새 실행에서도 유지되는지 검증한 뒤, 정확한 precursor 수준의 관측으로 제시할 수 있다. 이것을 부위 localization의 독립 증명이나 직접 substrate 귀속으로 올려서는 안 된다. footprint 평가 불가를 이유로 관측까지 숨길 필요도 없다.

6. “kinase를 평가하려면 enrichment가 필요하다”는 13쪽 문장을 고친다. 해당 분석의 평가 불가 원인부터 확인해야 한다. feature 관측 부족, site mapping 부족, substrate reference coverage 부족, 통계 기준 미충족은 서로 다른 문제다. 기존 enrichment-free 측정에서 유효한 관측을 먼저 활용하고, 필요한 경우 표적 측정이나 perturbation을 설계한다.

7. Methods를 실제 metadata로 채운다. 세포 모델·인슐린 처리·시간점·생물학적 반복과 기술적 반복·대조군 설계·MS 정규화·sample-wise 분모·결측 처리·검정과 BH family·clustering/state threshold·measurement unit을 명시한다. 저장된 replicate-level 분석 입력이 없다는 사실과 실험에 biological replicate가 없다는 사실을 혼동하지 않는다.

8. insulin 문헌과의 비교를 표로 만든다. 사전에 정한 canonical 비교와 새 후보 발견을 구분한다. 각 행에 기대하는 현상, 이번 실행의 해당 관측, 매칭 수준, 검증되지 않은 부분을 둔다. 모든 보고서에 정답처럼 ERK를 강제 삽입하는 방식은 피하고 관측된 자료를 표시한다. Turewicz 등 2025년 연구는 건강한 사람 유래 myotube 모델이므로 HIRc-B 결과와의 차이를 곧바로 결함으로 해석할 수 없다. 해당 연구의 설계와 결과는 아래 1차 문헌에서 확인했다.
[Turewicz 등 2025년 원논문](https://www.nature.com/articles/s41467-025-56335-6)

**Gemini API를 유지하면서 구현할 현실적인 순서**

먼저 기존 코드의 전달·분류·길이 충돌을 고친다. 다음으로 대표 데이터가 포함된 작은 evidence packet을 만들고, structured output으로 문장과 근거를 연결한다. 모델을 교체하거나 에이전트 수를 늘리는 작업보다 선행해야 할 부분이다.

현재 common/llm_client.py는 Gemini의 OpenAI 호환 endpoint를 사용하는 자유 텍스트 호출이다. 코드에서 planner는 “JSON only”라는 프롬프트를 사용하지만 이 경로에 JSON Schema 기반 response_format을 전달하지 않는다. 기존 호환 경로를 유지하면서 구조화 출력과 애플리케이션 검증을 추가할 수 있다. Google 공식 문서 역시 schema에 맞는 JSON이라도 값의 의미는 애플리케이션에서 검증해야 한다고 설명한다.
- [Google Gemini 구조화 출력 공식 문서](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google Gemini OpenAI 호환 API 공식 문서](https://ai.google.dev/gemini-api/docs/openai)

권장 구조는 다음과 같다.

정량 레코드 확정 → 근거 카드 생성 → 그림과 핵심 관측 선택 → 구조화된 문장 초안 → 숫자·식별자·주장 범위 검증 → 실패 문장만 제한적 재작성 → 최종 조판과 문서 검사.

실행 순서:
- 1차 변경: canonical p/q 필드 전달과 단일 조건 품질 함수. 원자료 재분석보다 먼저 해결한다.
- 2차 변경: feature/condition/axis/value 연결과 문장 검증. P1 반례를 regression fixture로 만든다.
- 3차 변경: 용어 치환과 섹션 길이 계약. 적절한 짧은 문장이 통과하도록 한다.
- 4차 변경: 그림·본문 연결, 실제 크기 가독성, 대표 사례 선택과 Methods 보강.
- 5차 검증: 같은 입력과 같은 코드·모델 설정으로 보고서 3회 생성해 변동을 측정한다. 이는 초기 smoke test이며 보편적인 정확도 보증은 아니다.

실제 실행의 resolved provider/model ID를 기록한다. 공통 client의 기본 GEMINI_MODEL은 gemini-2.5-flash이고 UI/환경/설정으로 변경될 수 있으므로, 사용자가 Pro를 선택했다는 사실만으로 실제 API 호출도 Pro였다고 단정하지 않는다. 민감한 키를 남기지 말고 resolved model, 사용한 설정, request/response usage와 지연 시간을 남긴다.

현재 artifact manifest는 입력과 Markdown 해시를 기록한다는 장점이 있다. 여기에 git commit SHA, worker/container version, prompt/validator schema version, resolved model ID, generation time zone, 최종 DOCX와 figure manifest 해시를 추가하면 새 보고서가 어느 수정으로 생성됐는지 판정하기 쉬워진다.

**Codex에 붙여 넣을 개발 요청**

아래 요청은 전체 시스템 재설계 대신 위에서 재현한 보고서 결함을 작게 수정하도록 구성했다.

> Xformyx/PTM-platform의 현재 코드를 읽고, 이 검토 문서의 P1 항목을 순서대로 수정해 주세요. 검토 기준은 2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6이며 현재 변경 사항과 먼저 대조해 주세요.
>
> 먼저 vector_projection과 measured_feature_cards의 adjusted p/q 필드 계약을 통일하고, single-condition comparison 품질과 trajectory 품질을 분리해 주세요. raw row에서 최종 card까지 통계·반복·measurement unit이 보존되는지 검증해 주세요.
>
> 다음으로 reader_authoring의 프롬프트와 validator를 수정해, 동일 gene/site의 서로 다른 precursor를 같은 trajectory로 서술하지 못하게 해 주세요. quantitative claim은 feature ID, condition, axis, source value와 연결하고 허용되지 않은 수치·시점·축을 탐지해 주세요.
>
> scientific_semantics의 blanket substitution과 접속사 삭제를 제거하거나 근거 유형에 따라 제한해 주세요. 정상적인 문헌 배경과 부정문은 보존하면서 unsupported current-data mechanism claim만 제한해 주세요. 잘못된 문장은 숫자·ID·인용을 고정해 문장 단위로 고치고 재검증해 주세요.
>
> section budget을 하나로 통합해 Conclusion 300단어 minimum과 170/180단어 maximum 충돌을 해소해 주세요. 재시도에서 단어 수만 늘리거나 temperature를 자동 증가시키지 말고, 결론의 핵심 결과·한계·다음 검증을 보존해 주세요.
>
> 각 수정은 먼저 실패를 재현하는 작은 fixture를 만들고, 수정 후 통과시키세요. 기존 conventional/de novo 분리, 독립 U와 A 구분, precursor identity, partial-grid 관측 허용, bibliography 제목 검사 제외는 보존해 주세요. 기존 테스트를 단순히 느슨하게 만들지 마세요.
>
> 마지막에 변경 파일, 해결한 반례, 실행한 검증과 미실행 범위, 보고서 생성에 필요한 추가 artifact를 보고해 주세요. 기능별로 검토 가능한 작은 diff로 제시해 주세요.

권장 regression cases:
- adjusted q=0.001이 projection→observation/comparison card에서 사라지지 않는다.
- control/treatment 3/3, q=0.001인 행이 1/2, q결측 행보다 같은 비교 class에서 우선된다.
- AARSD1 S88 두 precursor를 “same feature”로 연결한 문장은 막고, 서로 다른 precursor라고 밝힌 문장은 허용한다.
- +0.141을 +9.999로 바꾼 숫자 변조와 condition/axis 바꾸기를 탐지한다.
- 정상적인 dephosphorylation 배경 설명, While/Although 문장, does not prove 부정문을 훼손하지 않는다.
- 마침표 뒤 쉼표와 occupancy 치환 중복을 탐지한다.
- 적절한 160단어 Conclusion에 불필요한 분량 재시도가 없으며, 압축 후에도 해석 한계와 다음 검증이 남는다.
- Figure의 각 선택 항목에 자기 conditions/render_eligible이 적용되고, 본문이 인용한 feature가 해당 Figure에 존재한다.
- 통계적 유의성과 ±0.15 descriptive tolerance를 혼동하지 않는다.
- partial grid의 관측 표시와 clustering 제외가 독립적으로 작동한다.

**다음 실행에서 함께 확인할 산출물**

새 report_prose_trace.json, report_output_correctness_audit.json, report_artifact_manifest.json, figure manifest, authoring/evidence packet, 같은 실행의 vector TSV가 있으면 “코드가 수정됐다”와 “그 수정이 이 DOCX에 반영됐다”를 구분해 확인할 수 있다. 이 문서의 코드 결함은 현재 main에서 확인했지만, 09시23분 실행의 전체 정량 재현과 실제 사용 모델 검증은 이 자료 없이 확정하지 않았다.

**주요 코드 근거**

- [정량 projection](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/vector_projection.py#L80-L100)
- [카드의 품질 평가](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/measured_feature_cards.py#L208-L245)
- [단일 조건 비교 생성](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/measured_feature_cards.py#L447-L512)
- [Gemini용 카드 전달](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/reader_authoring.py#L659-L705)
- [문장 검증](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/reader_authoring.py#L1031-L1163)
- [의미 치환과 문장 정리](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/scientific_semantics.py#L118-L235)
- [섹션 압축](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/scientific_semantics.py#L242-L337)
- [생성 최소 단어 수](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/nodes/writer_node.py#L180-L192)
- [LLM 재시도](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/common/llm_client.py#L388-L478)
- [heatmap의 선택 feature 사용](https://github.com/Xformyx/PTM-platform/blob/2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6/workers/report_generation/core/nodes/signal_flow_figure.py#L1049-L1069)
