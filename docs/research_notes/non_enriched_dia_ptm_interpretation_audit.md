# 비-enrichment DIA 입력에서의 PTM Activity·TMM 해석 범위 감사

작성일: 2026-08-15 (GMT+9)
작성자: Manus AI

## 핵심 정정

PTM-platform은 phosphopeptide enrichment 기반 phosphoproteomics를 입력으로 요구하지 않는다. 현재 전처리는 **DIA-NN precursor matrix(PR)와 protein-group matrix(PG)** 를 읽고, PR matrix에서 설정한 variable modification을 포함한 modified precursor를 선별한다. 그러므로 플랫폼이 전혀 PTM을 관찰하지 않는 것은 아니다.

다만 관찰 범위는 enrichment phosphoproteomics의 전역 phosphosite coverage와 다르다. 이 플랫폼의 직접 관찰값은 **unenriched DIA에서 검출된 modified peptide precursor intensity**이며, 해당 intensity를 동일 protein group의 intensity로 나눈 relative modified-peptide signal이다. 검출되지 않은 modification은 unmodified 또는 비활성이라는 뜻이 아니라, 이 acquisition에서 관찰되지 않았다는 뜻이다.

> 현재 TMM은 kinase 단백질량이나 직접 효소활성을 분해하지 않는다. 동일 조건에서 검출된 modified-peptide relative trajectories 중, 후보 kinase의 exclusive-substrate trajectory가 shared modified-peptide trajectory를 얼마나 설명하는지를 계산한다.

## 코드로 확인한 실제 관찰량

| 처리 단계 | 구현 위치 | 실제 처리 | 안전한 해석 |
|---|---|---|---|
| Input | `workers/preprocessing/core/ptm_quantification.py:256–275` | DIA-NN PR matrix와 PG matrix를 로드 | PR은 precursor-level, PG는 protein-group-level 정량 입력 |
| PTM 선별 | `ptm_quantification.py:375–389` | `Modified.Sequence`의 설정 PTM UniMod 표기를 이용해 modified precursor만 선별 | 검출된 variable-modified peptide만 분석 대상 |
| 상대 정량 | `ptm_quantification.py:395–427` | `PTM_Relative_Abundance = PTM_Intensity / Protein_Intensity` | 단백질량으로 보정한 **modified-peptide relative abundance proxy** |
| 조건 비교 | `ptm_quantification.py:498–621` | relative abundance를 control 대비 log2FC로 계산하고 Welch t-test·BH FDR 적용 | modified-peptide relative regulation의 통계적 관찰 |
| Vector 입력 | `ptm_quantification.py:687–742` | `PTM_Relative_Log2FC`와 PG 기반 `Protein_Log2FC`를 저장 | PTM-driven change와 protein-driven change를 분리하여 검토할 근거 |
| Temporal/TMM 입력 | `api-server/app/api/orders.py:6743–6798, 8032–8108` | time-series·TMM 입력으로 `PTM_Relative_Log2FC` 사용 | TMM은 relative modified-peptide trajectory의 attribution |

## 현재 분석에서 가능한 주장과 불가능한 주장

| 구분 | 가능한 표현 | 피해야 할 표현 |
|---|---|---|
| Observed signal | “검출된 GENE site의 relative modified-peptide signal이 조건별로 변화했다.” | “전체 phosphoproteome에서 해당 site의 occupancy가 변화했다.” |
| Activity class | “statistically regulated modified-peptide signal” | “직접 측정된 kinase activity” 또는 “단백질 활성 상태” |
| TMM contribution | “조건 특이적 trajectory 설명 기여도” | “직접 인산화 비율”, “kinase 효소활성의 정량값” |
| Co-wave | “검출된 modified-peptide relative signals의 동시 변화” | “동시에 활성화한 모든 substrate가 동일 kinase의 직접 표적” |
| Directionality | “temporal-precedence-supported sequence” | “causal pathway”, “A가 B를 유발했다” |
| Non-detection | “이 acquisition에서 관찰되지 않음” | “PTM 부재”, “비활성” |

## 현재 구현에서 잘 보존되는 부분

`PTM_Relative_Abundance`를 PG intensity로 나누고, `PTM_Relative_Log2FC`와 `Protein_Log2FC`를 함께 저장하는 구조는 비-enrichment 입력에 적합한 출발점이다. 단순 modified-precursor intensity 증가를 protein abundance 증가와 동일시하지 않도록 하기 때문이다.

또한 API는 `PTM_Relative_Log2FC`를 time-series에 넣고, `de_novo`·`regulated`·`minor` class를 control pseudocount, BH-adjusted q-value, effect size로 구분한다. 특히 de novo signal의 pseudo-count 기반 과대 fold-change를 receptor score에서 낮은 가중치로 취급하는 점은 적절하다. 이 class는 **activity 자체**가 아니라 relative modified-peptide regulation의 품질/강도 등급으로 설명해야 한다.

TMM은 이 relative trajectory를 입력으로 사용하므로, 사용자의 “조건 특이적 kinase 기여도 분해”라는 정의와도 정합적이다. 단, 결과는 **검출된 modified peptide set에 조건부**이며, 후보 kinase 또는 비검출 substrate가 빠질 수 있다는 한계를 output provenance에 유지해야 한다.

## 확인된 해석·품질 위험

| 우선순위 | 위험 | 현재 상태 | 권고 |
|---|---|---|---|
| P0 | Assay scope 혼동 | 일부 문서와 report prompt가 `active kinases detected` 또는 일반적 phosphoproteome 용어를 사용 | `unenriched modified-peptide relative signal` 및 `inferred kinase-associated program`으로 표준화 |
| P0 | Modified-site localization provenance | preprocessing 코드에서 localization probability 또는 modification-specific FDR filtering을 확인하지 못함 | DIA-NN/검색 결과의 PTM localization·precursor q-value를 optional 필수 입력 metadata로 보존하고 threshold를 provenance로 기록 |
| P1 | Missingness 해석 | intensity가 없는 precursor는 결과 행에서 제외됨 | per-site detection rate, timepoint별 missingness, observed-only flag를 vector·TMM confidence에 추가 |
| P1 | Protein group ambiguity | PTM precursor와 PG의 `Protein.Group`이 다중 accession을 포함할 수 있음 | protein-group ambiguity count 및 ambiguous-site flag를 저장하고 cautious wording 적용 |
| P1 | Kinase activity wording | writer context에 “active kinases detected”라는 표현이 남아 있음 | “candidate kinase-associated modified-peptide program”으로 변경하고 direct activity assay와 구분 |

## Insulin Astral DIA benchmark의 정정된 역할

사용자의 insulin experiment는 enrichment phosphoproteomics benchmark가 아니라, **unenriched Astral DIA modified-peptide temporal benchmark**로 정의해야 한다. 가장 중요한 운영 전제는 DIA-NN search/library 설정에서 관심 PTM을 variable modification으로 허용하고 modified precursor가 충분히 정량되도록 하는 것이다.

이 benchmark에서 평가할 중심 질문은 다음과 같다.

> “Unenriched Astral DIA에서 반복적으로 검출된 modified-peptide relative trajectory를 이용할 때, TMM은 shared candidate kinase 간의 조건 특이적 설명 기여도를 안정적으로 분해하고, time-order permutation에서 그 이점을 잃는가?”

PXD043599과 PXD001792는 insulin signaling의 known temporal chronology를 확인하는 외부 biological reference로 여전히 유용하다. 그러나 enrichment phosphoproteomics의 site coverage를 직접 performance baseline으로 삼아서는 안 된다. primary benchmark의 coverage·missingness·relative-signal precision은 동일한 unenriched Astral DIA 조건에서 평가해야 한다.

## 후속 구현 권고

아래 항목은 현재 정상 기능을 바꾸지 않으면서 provenance와 보고서 안전성을 높이는 개선안이다. 핵심 scoring threshold는 사용자 승인 없이 변경하지 않는다.

| 우선순위 | 제안 | 변경 범위 |
|---|---|---|
| P0 | output metadata에 `assay_scope=unenriched_modified_peptide_dia`, `ptm_signal_definition=modified_precursor_over_protein_group` 추가 | preprocessing output·API provenance |
| P0 | `activity_class` UI/LLM 표시명을 `relative_PTMs_regulation_class`로 변경 | report prompt·frontend label, 내부 key 유지 가능 |
| P0 | report의 “active kinases detected”를 “candidate kinase-associated modified-peptide programs”로 교체 | `writer_node.py` prompt/context |
| P1 | localization q-value, precursor q-value, site detection rate, protein-group ambiguity를 TMM confidence/evidence profile에 전달 | preprocessing→API→shared contracts |
| P1 | modified precursor가 비검출인 경우 0으로 보간하지 않고 missingness-aware profile confidence를 별도 산출 | TMM/temporal-wave robustness |

이 조치는 PTM-platform의 강점을 약화시키지 않는다. 오히려 enrichment 없이도 관찰 가능한 modified peptide를 protein abundance와 분리하고, 그 시간 구조를 TMM으로 설명한다는 **명확하고 검증 가능한 방법론적 정체성**을 제공한다.
