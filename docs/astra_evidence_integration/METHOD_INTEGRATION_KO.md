# 방법 연결 및 자원 상태

`astra_analysis.v6` / `astra_analysis_package.v6.experimental`은 근거 연결과 해석 가능한 상태 출력의 새 버전이다. 정량 기본값은 기존 공급 intensity 보존 정책이다. 새로운 생물학적 성능 검증을 의미하지 않는다.

| 방법 | 실제 연결/실행 | 자원·적용 범위 |
|---|---|---|
| 기존 Generic U/P/A, strict parent | 재사용, 실제 HIRc-B 실행·회귀 | 동일 joint mask, unit balancing; biological p/q 없음 |
| DIA-NN main/site report | exact run/precursor/channel, site/contrast adapter; 합성 및 API worker 실행 | 실제 main/site report 없음. 2.7 문서 grammar와 실제 export parity는 별도 |
| heuristic motif | 기존 centered matcher 및 all-row 후보 유지 | 실험 specificity 또는 posterior가 아님 |
| 선언된 local matrix | percentile/rank gate 후 descriptive specificity_A | 정책 ID·실제 membership 기록, PhosX와 별도 |
| 공식 PhosX PSSM / native activity | 공식 Python 함수 호출, synthetic HDF5→최종 bundle→replay; upstream 예제 859개 site도 실행 | commit `b556f59c39f099b5f3fcb574a8a70856c3fdc82c`, package 0.23.1. Native KS/rank null/FDR. upstream activation evidence는 실행하지 않음 |
| Kinase Library | 라이선스·설치 범위 조사, runtime adapter 미연결 | commit `6b81cf8f9736c4f88e4dc07dbd0f99fe9e67b32a`, 확인 LICENSE CC BY-NC-SA 3.0. 플랫폼 사용 범위 미확정; 공식 atlas parity 미실시 |
| repository measured-gene z-score | canonical A와 curated membership에 연결 | 측정 gene universe의 정규 근사·BH. 공식 KSEA 실행 아님; 기술 반복 biological p/q 아님 |
| 공식 KSEA / PTM-SEA | comparator 계약 존재, 이번 실제 방법 실행 없음 | 고정 공식 환경·PTMsigDB site signature와 종/서열 매핑 준비 필요. gene enrichment를 PTM-SEA로 표시하지 않음 |
| KSTAR | 이번 native adapter/network 실행 없음 | human network/background 및 mapping pin 필요 |
| PhosR | 미연결, 적용성 제한 기록 | 기본 imputation/batch correction/biological test를 technical-only 자료에 적용하지 않음 |
| MSstatsPTM | 미연결 | 적합한 biological design·공식 R 환경 필요. 현재 A를 MSstatsPTM이라고 부르지 않음 |
| RoKAI / PHOTON | deferred | network context 보조 평가이며 direct site 근거로 승격하지 않음 |
| co-wave | 기존 trajectory 함수를 A와 gene/group 제외 anchor로 실행 | 관측 정합성·민감도. 독립 validation 아님 |
| GP/latent wave | 실행하지 않음 | 기존 구현의 insulin timescale prior/잡음 모델을 범용 설계에 검증 없이 적용하지 않음 |

## PhosX 경계와 재현

공식 코드 pin과 atlas 자료의 사용 권한은 별개다. 실제 운영에서는 resource manifest에 local use와 derived export 권한을 각각 `permitted`로 확인해야 한다. 원본 재배포가 금지돼도 이 두 권한이 허용된 경우 로컬 계산은 수행하며, archive에서 원본 행렬을 제외한다. 이 archive는 동일 hash의 별도 manifest/행렬/background 없이는 full replay가 불가능하다.

공식 offset -5…+4, percentile background와 top-rank selection 함수를 사용한다. 말단 `_`는 공식 중립 factor로 처리한다. multisite/priming을 해석할 수 없으면 제외 사유를 보존한다. native enrichment는 기본 10,000 permutations·seed 1729·single spawned worker다. 테스트/공개 예제의 100 permutations는 연결 검사 예산이며 최종 연구 설정이나 정확도 합격 기준이 아니다. Native 입력의 zero 제외, residue 분리, 실제 재정렬 순서를 membership에 연결한다.

공식 scorer를 호출했다는 사실은 현재 세포의 직접 kinase–site 관계나 kinase 정답 확률을 증명하지 않는다. `method_scores`, `method_membership`, `method_executions`, `native_execution_runtime.json`에서 method score와 descriptive footprint를 구분한다.

## 공식 자료 확인

- [DIA-NN 고정 README](https://github.com/vdemichev/DiaNN/blob/5598ebbbe7a5313434f4986aa24262337ce6d5b0/README.md), [site report discussion](https://github.com/vdemichev/DiaNN/discussions/1130)
- [PhosX 고정 코드](https://github.com/alussana/phosx/tree/b556f59c39f099b5f3fcb574a8a70856c3fdc82c), [Kinase Library 고정 코드](https://github.com/TheKinaseLibrary/kinase-library/tree/6b81cf8f9736c4f88e4dc07dbd0f99fe9e67b32a)
- [STRING API](https://string-db.org/help/api/): identifier mapping 후 species별 network 질의. HTTP404를 시간 예산 확대로 해결했다고 주장하지 않음.
- [benchmarKIN 연구 저장소](https://github.com/saezlab/kinase_benchmark), [PTM-SEA 공식 구현](https://github.com/broadinstitute/ssGSEA2.0): 공개 접근 위치 확인과 실제 설치·자료 실행은 별도 상태.
