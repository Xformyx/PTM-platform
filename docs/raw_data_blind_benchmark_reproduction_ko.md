# 실원자료 Blind Benchmark 재현 기록

## 목적과 실행 경계

이 기록은 사용자가 제공한 DIA-NN precursor/protein-group matrix 및 Rat+human INSR FASTA에 **현재 production preprocessing, canonical Temporal Wave, global kinase module, full TMM, offline locked scoring**을 적용한 로컬 재현 결과다. 정량값은 바꾸지 않았고, raw sample header만 중립 sample ID로 대체했다. analysis 단계는 workbook truth를 읽지 않았으며, truth는 마지막 offline locked scoring 단계에서만 사용했다.

| 항목 | 결과 |
|---|---:|
| Quantitative samples | 21 (6 numeric timepoints × 3 + control × 3) |
| Input phospho precursors | 3,035 |
| Normalized gene–site time series | 2,447 |
| Canonical Waves | 8 |
| Wave members | 622 |
| FASTA sequence+isoform+species mapped sites | 2,447 |

## 발견한 실패 seam

수정 전 full production replay에서 preprocessing과 Wave는 정상 완료됐지만, strict blind child는 source Order RAG/context를 의도적으로 포함하지 않는다. 해당 raw replay에서 direct iPTMnet/UniProt site lookup도 kinase anchor를 만들지 못해 global module이 0개가 됐고, 따라서 TMM input `kinase_modules`가 빈 목록이 됐다. 이는 원자료에 temporal signal이 없다는 결과가 아니라 **annotation-to-TMM input contract failure**였다.

## 일반화된 수정

`global-kinase-modules`에는 opt-in `allow_motif_only_seed`가 추가됐다. 이 flag는 다음 조건에서만 작동한다.

1. direct/contextual anchor가 전혀 없고,
2. strict blind executor가 명시적으로 flag를 전달하며,
3. sequence/motif candidate가 존재할 때다.

이때 candidate는 `motif_only_seed` provenance로 별도 표시된다. 이는 Tier 1/2 canonical scoring evidence로 승격되지 않으며, TMM/cascade가 계산 가능한 discovery-layer input을 제공할 뿐이다. normal Order의 기본 호출은 flag를 전달하지 않으므로 기존 anchor-required phosphorylation 동작을 유지한다.

또한 production normalized vector에 `FASTA_Taxonomy_ID` column이 없는 경우, supplied FASTA record의 accession-level `OX`를 trusted per-record species provenance로 사용하도록 benchmark artifact mapper를 보완했다. 따라서 rat background와 human transgene이 함께 있는 FASTA도 accession별 taxon provenance를 유지한다.

## 수정 후 실원자료 결과

| TMM artifact field | Reproduced count |
|---|---:|
| Annotated kinase modules | 23 |
| TMM kinase score rows | 48 |
| TMM profiles | 22 |
| Fractional contribution records | 4,894 |
| Contribution-weighted cascade timepoints | 6 |
| Observed kinase-pair directionality relationships | 6 |

Figure 3 source data retains `input_evidence_tier` and `input_sources_json`. This replay marks all resulting TMM input modules as `motif_only_seed`, so their trajectories must be described as **motif-seeded, TMM-weighted candidate attribution**, not direct kinase–substrate validation.

## Offline locked score

The final isolated scorer produced a real Figure 1–4 bundle and source TSV/ZIP files. The locked-score summary was: detectable anchor recall 1.000, regulated anchor recall 0.333, direction accuracy 1.000 among regulated detectable anchors, peak-window accuracy 1.000 among those anchors, chain completeness 0.000, and canonical weighted score 0.733. Denominators are recorded in `locked_score_result.json`; this result is not a claim of causal validation.

## Reproduction outputs

The local validation workspace contains the truth-free analysis artifact, Figure 1–4 SVGs, per-figure source TSV files, and the offline locked score bundle under `raw_benchmark_workspace/locked_score_bundle/`. These generated inputs/outputs are intentionally outside the repository and are not committed.
