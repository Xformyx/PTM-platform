# Preprocessing and Normalization Overview

## Preprocessing 단계

Preprocessing은 업로드된 DIA-NN 정량 결과를 분석 가능한 PTM 벡터와 단백질 주석 테이블로 바꾸는 단계입니다. RAG나 LLM 해석은 아직 하지 않고, 이후 RAG Enrichment와 Report Generation이 읽을 정량/주석 기반 입력 파일을 만드는 역할입니다.

### 입력

Order Start 시 API 서버가 Preprocessing Celery task에 다음 정보를 넘깁니다.

- `pr_matrix_path`: DIA-NN precursor/report matrix. PTM precursor 정량의 주 입력입니다.
- `pg_matrix_path`: DIA-NN protein group matrix. protein abundance 보정에 사용합니다.
- `fasta_path`: UniProt/FASTA reference. 단백질 서열, gene name, motif 위치 확인에 씁니다.
- `condition_map`: sample filename -> condition/group 매핑입니다.
- `ptm_mode`: `phospho` 또는 `ubi`.
- `species_tax_id`, `kegg_organism`: 이후 생물학적 annotation에 사용됩니다.
- `analysis_options`: Quick Analysis, downsampling 등 실행 옵션입니다.

### 단계별 흐름

#### 1. 실행 준비

`workers/preprocessing/tasks.py`의 `run_preprocessing`이 시작되면 order 상태를 `preprocessing`으로 바꾸고, 이전 phase log를 정리합니다. 또 `run_generation` guard로 이미 새 실행이 시작된 오래된 worker라면 산출물을 쓰지 않고 중단합니다.

완료/취소된 order를 full Start하면 output directory를 지우고 처음부터 다시 만듭니다. Stage re-run은 필요한 단계만 다시 돌리는 방식입니다.

#### 2. Quick Analysis 옵션 처리

Quick Analysis가 켜져 있으면 PR/PG matrix를 먼저 subset합니다. 공식 full 분석과 같은 계산식을 쓰지만 입력을 줄이는 exploratory 실행입니다. 이후 단계는 subset된 파일을 대상으로 그대로 진행됩니다.

#### 3. PTM 정량화

핵심은 `workers/preprocessing/core/ptm_quantification.py`의 `PTMQuantificationAnalyzer`입니다.

이 단계에서 하는 일은 다음과 같습니다.

- FASTA를 읽어 UniProt ID, protein name, gene name, sequence를 준비합니다.
- PR/PG matrix를 로드합니다.
- sample intensity에 median normalization을 적용합니다.
- phospho/ubi 모드에 맞는 target PTM precursor만 필터링합니다.
- PTM site-level relative quantification을 계산합니다.
- modified/unmodified pair 기반의 apparent occupancy audit를 계산합니다.
- condition별 PTM log2FC를 계산합니다.
- PG matrix로 protein-level log2FC를 계산합니다.
- PTM 변화량과 protein 변화량을 결합해 PTM vector를 만듭니다.

주요 산출물은 다음입니다.

- `ptm_vector_data_normalized_phospho.tsv` 또는 `_ubi.tsv`
- `all_protein_level_changes_normalized_phospho.tsv` 또는 `_ubi.tsv`
- condition comparison, relative quantification, pair audit 관련 TSV들
- `normalization_factors.tsv`

여기서 중요한 점은 PTM vector가 단순 PTM fold-change가 아니라, protein abundance 변화와 PTM 상대 변화가 같이 들어간 downstream 분석용 표라는 것입니다.

#### 4. Pipeline 통계 생성

정량화 결과를 읽어 `pipeline_statistics_phospho.json` 또는 `_ubi.json`을 만듭니다.

포함되는 내용은 대략 다음입니다.

- PR/PG 입력 row 수
- PTM precursor/site/protein 수
- normalization factor 범위
- condition별 up/down/unchanged count
- protein-level 변화 수
- PTM vector quadrant count

프론트의 통계/상태 표시와 QC 확인에 쓰입니다.

#### 5. PTM Vector Plot 생성

정량화 TSV를 기반으로 2D scatter plot과 summary plot을 만듭니다. 보통 Vector Plot 탭에서 보는 그림들이 이 단계 산출물입니다.

이미 `ptm_vector_report_*.png` 같은 파일이 있으면 cached로 보고 건너뜁니다.

#### 6. Temporal Representation Learning

환경변수 `PTM_REPRESENTATION_LEARNING_ENABLED=1`이면 추가로 temporal PTM representation을 학습합니다.

산출물 예시는 다음입니다.

- `ptm_representation_embeddings_phospho.tsv`
- `ptm_representation_benchmark_phospho.json`

이건 기존 PTM vector, canonical co-wave, TMM 계산을 대체하지 않는 additive layer입니다.

#### 7. Ubiquitin Linkage 분석

`ptm_mode == "ubi"`일 때만 ubiquitin linkage analyzer가 실행됩니다. K48/K63 등 linkage 관련 패턴이 있으면 별도 결과를 만듭니다. phospho order에서는 실행되지 않습니다.

#### 8. Unified Enrichment

`UnifiedProteinEnricher`가 PTM vector와 all-protein table을 합쳐 domain/motif 중심의 enrichment TSV를 만듭니다.

주요 산출물:

- `unified_protein_data_enriched_phospho.tsv` 또는 `_ubi.tsv`

여기에는 PTM site, protein 변화량, sequence window, motif/domain 관련 정보가 붙습니다.

#### 9. Biological Enrichment

`BiologicalEnricher`가 UniProt, STRING, KEGG 등 생물학적 annotation을 붙입니다.

주요 산출물:

- `unified_protein_data_enriched_bio_enriched_phospho.tsv` 또는 `_ubi.tsv`

이 파일은 RAG Enrichment가 문헌 enrichment를 시작할 때 중요한 입력으로 사용됩니다. 즉 Preprocessing의 최종 목적지는 문헌 검색 가능한 단백질/PTM 후보 테이블을 만드는 것입니다.

#### 10. Cross-Talk 모드의 secondary PTM 처리

분석 모드가 `cross_talk`이고 secondary PR/PG 파일이 있으면, primary와 별도로 `secondary_ptm/` 아래에서 같은 전처리 흐름을 한 번 더 실행합니다.

예를 들어 primary가 phosphorylation이면 secondary는 ubiquitylation일 수 있습니다.

### 최종 산출물

Preprocessing이 끝나면 order output directory에 대략 이런 파일들이 생깁니다.

- `ptm_vector_data_normalized_*.tsv`
- `all_protein_level_changes_normalized_*.tsv`
- `unified_protein_data_enriched_*.tsv`
- `unified_protein_data_enriched_bio_enriched_*.tsv`
- `pipeline_statistics_*.json`
- `ptm_vector_report_*.png`
- optional: representation learning 결과
- optional: ubiquitin linkage 결과
- optional: `secondary_ptm/` 결과

### 다음 단계로 넘기는 것

Preprocessing이 성공하고 `chain_to_next=True`이면 자동으로 RAG Enrichment로 넘어갑니다. RAG 단계는 Preprocessing이 만든 bio-enriched TSV를 읽어서 PubMed/ChromaDB/생물학 DB 문헌 정보를 붙이고, 최종 `enriched_ptm_data_*.json`을 만듭니다.

요약하면, Preprocessing은 정량 데이터 정리 + protein abundance 보정 + PTM vector 생성 + motif/domain/biology annotation 준비 단계입니다. 이후 RAG와 Report는 이 단계가 만든 표와 그림을 기반으로 동작합니다.

## Normalization 방식

현재 Preprocessing의 normalization은 sample-wise median normalization입니다. PR matrix와 PG matrix를 각각 따로 정규화합니다.

핵심 로직은 `workers/preprocessing/core/ptm_quantification.py`에 있습니다.

```python
def apply_median_normalization(self) -> bool:
    self.pr_matrix_normalized = self.pr_matrix.copy()
    pr_factors = self._normalize_matrix(self.pr_matrix_normalized, self.sample_columns, "PR")

    self.pg_matrix_normalized = self.pg_matrix.copy()
    pg_factors = self._normalize_matrix(self.pg_matrix_normalized, self.sample_columns, "PG")

    self._save_normalization_factors(pr_factors, pg_factors)
```

정규화 방식은 다음입니다.

1. sample column은 기본적으로 `.mzML`로 끝나는 컬럼입니다.
2. 각 sample column에서 `0`은 missing처럼 보고 `NaN`으로 바꾼 뒤 제외합니다.
3. sample별 median intensity를 계산합니다.
4. 모든 sample median들의 median을 `global_median`으로 잡습니다.
5. 각 sample에 대해 `factor = global_median / sample_median`을 계산합니다.
6. 해당 sample column 전체 intensity에 factor를 곱합니다.

수식으로는 다음과 같습니다.

```text
sample_median_j = median(nonzero intensities in sample j)

global_median = median(sample_median_1, sample_median_2, ...)

normalization_factor_j = global_median / sample_median_j

normalized_intensity_ij = raw_intensity_ij * normalization_factor_j
```

이 작업은 PR과 PG에 별도로 적용됩니다.

```python
def _normalize_matrix(matrix, sample_columns, matrix_type):
    medians = {}
    for sample in sample_columns:
        values = matrix[sample].replace(0, np.nan).dropna()
        medians[sample] = values.median() if len(values) > 0 else 1.0

    global_median = np.median(list(medians.values()))
    for sample in sample_columns:
        factor = global_median / medians[sample]
        matrix[sample] = matrix[sample] * factor
```

정규화 factor는 `normalization_factors.tsv`로 저장됩니다. 각 sample마다 PR factor와 PG factor가 따로 기록됩니다.

그 다음 PTM relative abundance는 normalized PR intensity를 normalized PG protein intensity로 나눠서 계산합니다.

```python
PTM_Relative_Abundance = PTM_Intensity / Protein_Intensity
```

정리하면, 현재 방식은 total signal distribution을 sample 간 median 기준으로 맞춘 뒤, 그 normalized 값으로 PTM/protein abundance ratio를 계산하는 구조입니다. Log transform이나 quantile normalization은 normalization 단계에서는 하지 않습니다.
