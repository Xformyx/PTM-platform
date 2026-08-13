# Canonical Temporal Wave Contract v1

`ptm_shared.temporal_wave_engine`은 API receptor inference, RAG, Report Generation이 공유하는 Temporal PTM Wave의 계산상 단일 진실원이다. Contract의 입력은 condition-level protein-normalized PTM Log2FC이며, 출력은 PTM site의 구조적 co-movement 결과다.

## 핵심 원칙

Temporal Wave는 **인과적 signaling edge가 아니라**, 명시된 threshold와 결측치 정책 아래 검출된 PTM site의 구조적 co-movement group이다. Wave가 논문 또는 Report에서 강한 기전적 주장을 뒷받침하려면 별도의 kinase enrichment, replicate stability, perturbation, ChromaDB 문헌 근거가 필요하다.

## 출력 계약

| 필드 | 목적 |
|---|---|
| `contract_version`, `engine_version` | 계산 알고리즘의 식별 |
| `threshold_provenance` | correlation threshold, source, filter, linkage, config hash 추적 |
| `waves` | 확정된 canonical membership 및 trajectory |
| `evidence_profile` | coherence, direction consistency, peak dispersion, amplitude, evidence tier |
| `unassigned_sites`, `excluded_sites` | 과도한 clustering을 피하기 위한 음성 결과 보존 |
| `quality_warnings` | timepoint 부족·결측치 fill 등 해석 제약 표시 |

## 현재 Evidence Tier의 범위

`high_structural_evidence`, `moderate_structural_evidence`, `exploratory_structural_evidence`는 **wave 내부의 구조적 일관성**만 반영한다. replicate stability, independent dataset reproducibility, lag evidence, kinase/pathway enrichment, soft prior agreement는 후속 P1 단계에서 실제 계산값으로 채워진다. 현재는 `null`을 유지하여 미계산 지표를 거짓 신뢰도로 대체하지 않는다.

## Benchmark 사용

`python -m ptm_shared.temporal_wave_benchmark --manifest <manifest.json> --output-dir <dir>`를 실행한다. Benchmark는 manifest가 가리키는 실제 공개/내부 perturbation time-series 파일이 존재할 때만 실행되며, 결측 파일에는 실패한다. 예시 manifest `benchmarks/temporal_wave/PXD044049.example.json`은 공개 PXD044049의 실데이터를 내려받고 platform input contract로 전처리한 뒤 사용할 수 있다.

Time permutation은 manifest의 `expected_target_windows`가 있을 때에만 temporal target recovery를 시험한다. 그 정보가 없으면 harness는 검정을 실행하지 않고 `not evaluable`을 출력한다. 이 설계는 zero-lag correlation clustering이 시간 label permutation에 본질적으로 둔감할 수 있다는 점을 숨기지 않기 위함이다.
