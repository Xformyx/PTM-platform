# 없는 입력과 미검증 범위

Order에 저장된 종·조건·반복 구조는 재사용한다. 이 정보를 다시 입력할 필요가 없다. 확보한 PR·PG·FASTA로 수행 가능한 정량·mapping·emergence·protein·탐색 근거는 실행했다.

| 실제 미확보 자료 | 필요한 이유 | 현재 대체 가능한 범위 |
|---|---|---|
| `astra_analysis_package_g2-8402846e3668422d9fd85571a203b52f.zip` | 사용자 검토의 정확한 코드/입력/source pin과 before/after 비교 | 확보한 이전 HIRc-B v5 archive로 별도 회귀. g2 동일성은 미확인 |
| 동일 DIA-NN 분석의 `report.tsv` 또는 `report.parquet` 및 정확한 version/export 설정 | 실제 run별 precursor confidence/q-value/site 문자열과 matrix contributor join | 현재 PR에는 해당 열이 없음. synthetic join 검사만 가능 |
| 같은 분석의 site report(있다면) | version-specific Protein/Site/Probability와 main report 연결 | 선택 입력. 없으면 main report에서 검증 가능한 scope만 사용 |
| 이름이 다른 run의 명시적 Run–Channel–input_column–injection crosswalk | 중복 basename, renamed column, channel 혼동 방지 | exact 동일 Run/column은 연결 가능. 임의 suffix/순서 추정하지 않음 |
| 실제 검색 FASTA 및 필요 시 construct/taxonomy mapping | search/analysis reference 동일성, human transgene 고유 mapping 검증 | 현재 제공 FASTA의 mapping만 가능. hIRc-B라는 이름으로 isoform/construct 확정하지 않음 |
| 승인된 specificity manifest·matrix·background와 사용/파생결과/재배포 조건 | 실제 atlas scoring 및 공식 parity, 조건부 replay | 합성 HDF5와 upstream 공개 예제로 코드 연결 검사. 실험 자원 준비 완료 아님 |
| 독립 calibration artifact 및 연구/cohort 분할·원자료 hash·평가 기록 | calibrated inference의 도메인과 threshold 검증 | descriptive/exploratory 신호와 이유별 abstention 제공 |
| 독립 perturbation/WB/PRM의 실제 측정과 단위·site·independence 정보 | 해당 dataset/candidate/version 범위의 독립 실험 검증 | 현재 pending_data; 합성 자료를 biological validation으로 사용하지 않음 |

공개 benchmark 수집·정제, PTM-SEA/KSTAR/R 환경 준비, 운영 배포 확인은 별도 개발/운영 작업이며 사용자 실험 자료가 없다는 이유로 대체 설명하지 않는다. 이번 인계에서 수행되지 않은 상태로 명시했다. DIA-NN version·주입 peptide mass·upstream normalization도 확인되지 않은 채 unknown을 유지한다. 주입 부피 10 µL를 peptide mass 10 µg로 바꾸지 않는다.
