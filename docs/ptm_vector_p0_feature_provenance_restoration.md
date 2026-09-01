# P0 feature-level input provenance restoration

**선언일:** 2026-09-01  
**상태:** 결과 열람 후 진단(Insulin `feature_records=0`)에 따른 복원 규칙. 탐색적. primary 승격 금지.  
**독립성:** P4 inhibitor validation과 독립. P4는 inhibitor dataset가 준비될 때까지 보류.

## 1. 문제와 금지 규칙

P0 full ledger (`ptm_kinase_feature_provenance.v5`)는 explicit modified-precursor
identity를 요구한다. 필수 다섯 항목은 gene, position, protein group, modified
sequence, `Precursor.Id`이다. gene/site label만으로 precursor, sequence,
accession, localization을 만들지 않는다.

2026-09-01 Insulin_Signaling_V3 production sidecar는 P1/P2 bundle
`validated` + matching SHA였지만 M0–M4/R0–R4가 전부 0이었다. 원인은 설치
오류가 아니라 Stage 1 vector TSV와 RAG collapse 경로에서 `Precursor.Id`가
사라졌기 때문이다. 이 문서는 그 복원 규칙을 **재측정 전에** 고정한다.

금지:

- gene + site로 `Precursor.Id`를 합성하지 않는다.
- RAG site-collapse 레코드를 feature-level mapping 증명으로 쓰지 않는다.
- 같은 `Protein.Group` + `Modified.Sequence` + `PTM_Position` + `Condition`에
  서로 다른 precursor가 있으면 하나를 고르지 않는다. 각각이 feature다.

## 2. Stage 1 출력 계약

`PTMQuantificationAnalyzer.create_ptm_vector_data`가 쓰는
`ptm_vector_data_normalized{suffix}.tsv`는 이미 내부 join 키로
`Precursor.Id`를 사용한다. 그 값을 출력 컬럼으로 보존한다.

| 컬럼 | 역할 | 필수 |
|---|---|---|
| `Precursor.Id` | modified-precursor identity | 예. 없으면 그 행은 P0에서 제외 |
| `Precursor.Charge` | form identity (있을 때만) | 아니오 |
| `Gene.Name` | ledger site key | 예 |
| `Protein.Group` | accession/group | 예 |
| `Modified.Sequence` | peptide form | 예 |
| `PTM_Position` | reported site | 예 |

이 컬럼 추가는 Wave/TMM 수치를 바꾸지 않는다. identity 보존만 한다.

## 3. RAG / sidecar 입력 경계

Wave/TMM timeseries는 계속 RAG collapse된 gene+site 레코드에서 재구성한다.
P0 ledger는 Stage 1 artifact만 읽는다.

우선순위:

1. `ptm_vector_data_normalized{suffix}.tsv` (또는 motifs 변형)에 nonempty
   `Precursor.Id`가 있으면 그 행을 쓴다.
2. 없으면 같은 Order의 `ptm_condition_comparisons_normalized{suffix}.tsv`를
   identity·정량 소스로 쓰고, `Gene.Name`은
   `Protein.Group` → gene annotation(`ptm_protein_level_changes_*` 또는
   vector TSV)에서만 붙인다. 이는 gene/site fallback이 아니라 이미 Stage 1에
   있는 protein-group annotation을 복원하는 것이다.
3. `FASTA_Taxonomy_ID` / `FASTA_Organism`은 unified annotation TSV가 있으면
   `Protein.Group`으로만 붙인다.
4. `enriched_ptm_data_*.json`은 P0 소스가 아니다.

기존 Insulin Order는 vector TSV에 `Precursor.Id`가 없다. 같은 run의
comparisons TSV에는 이미 있으므로 전처리 재실행 없이 sidecar만 재생성할 수
있다. 이후 전처리를 다시 돌리면 vector TSV가 1번 경로를 탄다.

## 4. 해석 한계

- Ledger가 채워져도 rat→human P1 ceiling은 대개 `M3_gene_only_context`다.
  P2 R3는 P0-ready **M1**만 받는다.
- Feature count > 0은 mapping/relation/allocation 성공이 아니다.
- Compact `mapping_class_counts` / `relation_class_counts`가 0이 아니게
  되더라도 kinase 귀속 정확도를 주장하지 않는다.
- P4는 이 복원과 무관하다.

## 5. 구현 위치

- `ptm_shared/temporal_input_reconstruction.py` —
  `load_stage1_feature_provenance_rows`
- `workers/preprocessing/core/ptm_quantification.py` —
  `create_ptm_vector_data`
- `workers/rag_enrichment/tasks.py` — canonical sidecar builder
- `api-server/app/api/orders.py` — API direct sidecar builder passes the same
  local P1/P2 source-bundle environment paths as the RAG worker, preventing an
  API-triggered rebuild from replacing a validated P1/P2 sidecar with M0/R0.
