# 09시23분 보고서 검토에 따른 P1 수정 인계

작업 기준 HEAD는 `2e04f86bd2d29848f2f1f5f405eaf62d5dd3b8b6`으로, 검토 문서의 기준과 같았다. 로컬 코드만 수정했다. 브랜치·커밋·원격 저장소를 변경하지 않았으며, 기존 미추적 검토 문서는 보존했다.

## 기능별 변경과 검토용 diff

아래 patch는 기준 커밋과 작업 결과의 차이를 기능별로 나눈 검토 자료다. 파일 간 의존성이 있으므로 적용할 때는 네 묶음을 함께 사용한다. 기준 커밋의 별도 임시 사본에서 네 patch의 `git apply --check`가 통과했다.

| 묶음 | 변경 파일 | 동작 |
|---|---|---|
| [01 정량 계약](/tmp/ptm-report-review-patches/01-quantitation.patch) | `core/quantitative_fields.py`, `core/vector_projection.py`, `core/measured_feature_cards.py`, `test_report_review_quantitation.py` | canonical 축별 value/p/q/n 접근자를 공유한다. adjusted p/q의 projection 및 재projection 손실을 수정했다. 각 축의 결측 통계와 반복 수를 보존한다. 단일 조건 비교 품질을 trajectory 품질과 분리한다. |
| [02 문장 근거 연결](/tmp/ptm-report-review-patches/02-claim-binding.patch) | `core/quantitative_claims.py`, `core/reader_authoring.py`, `core/graph.py`, `test_report_review_claims.py` | 프롬프트에 PF ID, condition, axis, value, p/q/n, measurement unit, localization과 Figure 구성원을 전달한다. 숫자와 precursor 연결을 검증하고, 최종 본문에서도 다시 검사한다. fallback 본문 검사는 실제로 사용한 카드에서 식별자를 읽는다. |
| [03 문장·길이·호출](/tmp/ptm-report-review-patches/03-prose-budget-client.patch) | `common/section_budgets.py`, `common/llm_client.py`, `core/scientific_semantics.py`, `core/nodes/writer_node.py`, `test_report_review_prose.py`, `test_report_review_llm_contract.py` | 문헌 배경과 부정문을 보존하고 무조건적인 용어 치환 및 접속사 삭제를 제거한다. 단일 길이 계약, 의미 역할을 보존하는 압축, 고정 temperature 재시도를 적용한다. reader authoring 호출에 문장 JSON Schema와 값 토큰을 연결한다. |
| [04 그림 연결](/tmp/ptm-report-review-patches/04-figure-binding.patch) | `core/figure_manifest.py`, `core/nodes/signal_flow_figure.py`, `test_report_review_figures.py` | 각 선택 항목 자신의 conditions/render_eligible을 사용한다. 결측 셀을 0으로 채우지 않는다. 기본 요약 선택을 최대 16행으로 줄이고 모든 행 이름을 표시한다. 색상축에 adjusted relative PTM contrast를 명시한다. |

`core/`는 `workers/report_generation/core/`, `common/`은 `workers/common/`, 테스트 파일은 `workers/tests/` 아래에 있다. 기존 테스트 파일은 수정하지 않았다.

## 재현하고 해결한 반례

- 원본 adjusted p=0.0002/q=0.001, unadjusted p/q=null이 projection → observation/comparison card → prompt와 구조화 reference에서도 그대로 남는다. 축별 n과 measurement provenance를 별도로 전달하며 결측을 다른 축에서 빌리지 않는다.
- 같은 comparison class에서 3/3 반복과 q 근거가 있는 ZZZ_SUPPORTED가 1/2 반복·q 결측인 AAA_LOW_SUPPORT보다 먼저 선택된다. `biological_direction_inference_allowed=false`, `adjustment_effect_tested=false`를 유지한다.
- AARSD1 S88의 다른 precursor를 같은 feature로 연결하는 문장, +0.141→+9.999 변조, 잘못된 condition/axis, 식별자를 생략한 숫자 주장을 차단한다. 서로 다른 PF ID·조건·축을 명시한 올바른 비교는 허용한다.
- 구조화 초안의 값 토큰은 서버의 reference catalog에서 feature ID/condition/axis/source value로 해석된다. LLM이 토큰 앞에 다른 조건이나 축을 붙이는 경우도 차단한다. 한 문장이 잘못되어도 유효한 다른 문장은 유지한다.
- 문장에 인용한 Figure가 해당 precursor를 실제로 선택했는지 검사한다. 정상적인 Figure 인용은 통과한다.
- adjusted q로 unadjusted 유의성을 대신하는 문장과 ±0.15 descriptive tolerance를 보정 효과의 통계 검정으로 표현한 문장을 차단한다.
- 정상적인 dephosphorylation 배경, While/Although 문장, `does not prove` 부정문, 인용된 stoichiometry 배경을 보존한다. `.,`와 중복된 정량 표현을 검사한다. 정상화와 인용 배경 검증을 반복해도 결과가 유지된다.
- 실제 프로젝트 단어 계산으로 160단어인 완결된 Conclusion은 `min_words=300`을 전달해도 한 번만 호출한다. 재시도 temperature가 증가하지 않는다. 압축 후 인과 해석 한계와 독립 검증 문장이 남는다.
- 마지막 manifest 항목이 render 불가여도 앞의 적격 항목들을 지우지 않는다. 각 항목의 서로 다른 조건 집합을 적용한다.

초기 실패 확인: 정량 fixture 3개, 최초 문장 fixture 6개, 문장/길이 fixture 9개, 그림 fixture 1개가 수정 전 실패했다. 후속 반례도 추가 후 실패를 확인하고 수정했다. 정량 baseline은 기준 커밋의 임시 사본에서도 실행했다.

## 검증 결과

총 **157 passed**, 대상 17개 테스트 파일. Python 3.14.6의 독립 임시 가상환경에서 pytest를 실행했다. Python 3.11 문법 검사로 수정/추가 Python 파일 17개가 통과했고, `git diff --check`도 통과했다. 이는 저장소 전체 pytest 실행이나 운영 컨테이너 검증을 뜻하지 않는다.

[pytest JUnit 결과](/tmp/ptm-report-review-pytest.xml)

```sh
PYTHONPATH=workers:. MPLCONFIGDIR=/tmp/ptm-review-mpl \
/tmp/ptm-report-review-venv/bin/python -m pytest \
  workers/tests/test_report_review_*.py \
  workers/tests/test_measured_feature_authoring.py \
  workers/tests/test_report_rendering_fidelity.py \
  workers/tests/test_quantitation_estimator_contract.py \
  workers/tests/test_report_vector_projection.py \
  workers/tests/test_measured_feature_cards.py \
  workers/tests/test_reader_prose_quality.py \
  workers/tests/test_bibliography_blocked_data_only.py \
  workers/tests/test_de_novo_representation.py \
  workers/tests/test_report_artifact_manifest.py \
  workers/tests/test_evidence_contracts.py \
  ptm_shared/tests/test_de_novo_report_representation.py \
  workers/tests/test_temporal_report_evidence_packet.py -q
```

기존 conventional/de novo 분리, 독립 U와 A, precursor identity, partial-grid 관측과 clustering eligibility 분리, bibliography 제목 검사 제외를 포함한다. Gemini 요청은 HTTP mock으로만 확인했다. 호환 endpoint의 JSON Schema 사용 방식은 [Google 공식 호환 API 문서](https://ai.google.dev/gemini-api/docs/openai#structured-output)를 확인했다. JSON 구조만으로 과학적 의미가 검증되지는 않으므로 애플리케이션 검사를 함께 적용했다.

## 적용 범위와 남은 실행 검증

구조화 초안 생성은 기존 `shadow` reader authoring 경로에 연결했다. provider/model 선택 정책을 바꾸지 않았고, 문장 trace에 실제 client의 resolved provider/model, temperature와 response schema를 기록한다. 입력 catalog가 프롬프트 한도를 초과하면 이를 중간에서 자르지 않고 기존 fallback으로 처리한다.

자유 문장 검사는 명시된 feature·조건·축과 표시 정밀도를 기준으로 하는 보수적인 검사다. 임의의 모든 자연어 표현이나 생물학적 주장 전체를 증명하는 validator가 아니다. 안전하게 재작성할 근거가 부족한 문장은 audit에 원문과 사유를 남기고 제외하므로, 실제 모델 실행에서 제외율과 본문 완결성을 확인해야 한다. 결론의 필수 역할 검사는 어휘 규칙이며 전문가의 내용 검토를 대체하지 않는다.

09시23분 보고서의 정량 계산 전체, DOCX 재생성, 실제 Gemini 호출, 같은 입력으로 세 차례 보고서 생성, 최종 DOCX 표시 크기 검사는 실행하지 않았다. 새 실행의 ACIN1 지원 수준, VIM protein-group 및 sample mapping QC, MAPK1/3 관측, 실험 Methods metadata를 확인하지 않았다. Figure 3의 별도 통계표, 작은 trajectory panel, 문헌 비교표와 artifact manifest의 git/container/timezone/최종 파일 hash 확장은 후속 범위로 남는다.

사용자 후속 전달: DOCX가 생성되지 않던 오류는 Cursor를 사용해 수정했다. 이 수정의 실제 실행 검증은 이번 작업에 포함하지 않았으며, 위의 DOCX 재생성 미실행 기록이 생성 오류가 여전히 남았다는 뜻은 아니다.

다음 실행에서는 같은 run의 vector TSV, enriched JSON 및 분석 sidecar, replicate-level 입력·sample mapping·실험 metadata, authoring/evidence packet, figure manifest, `report_prose_trace.json`, `report_output_correctness_audit.json`, `report_artifact_manifest.json`, 최종 Markdown/DOCX를 함께 보존해야 한다. 코드 SHA, 실제 provider/model 및 설정, 생성 시간대, 사용량·지연 기록과 최종 파일 hash도 함께 확인해야 코드 변경과 특정 DOCX의 반영 여부를 구분할 수 있다. API 키는 기록하지 않는다.
