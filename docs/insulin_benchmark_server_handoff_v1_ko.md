# Insulin benchmark optimized temporal contract 서버 이전 절차 v1

## 1. 이전 대상

서버 이전의 기준 configuration은 `truth_free_temporal_optimized.v1`이다. 배포 runtime configuration SHA-256은 `7b9674a29bde3f094f40e0bb6323f1c3d1ba99b075a801f00e26de9d6825a28c`이고, 이를 선택한 optimization record SHA-256은 `2c625933b8fdab6fe59f7bc48eee00ee1698b1f4f253df86e1099fb79f618c62`이다. 이 configuration은 locked workbook truth를 보지 않고 replicate holdout stability와 reconstruction으로 선택되었다. 일반 Order의 기존 TMM default는 변경하지 않으며, strict BenchmarkRun만 명시적으로 opt-in한다.

```bash
PYTHONPATH="$PWD" python3 -m ptm_shared.temporal_optimization_config
```

## 2. 코드 동기화와 image rebuild

```bash
cd <PTM-platform-server-path>
git status --short --branch
git fetch github
git pull --ff-only github main
docker compose up -d --build api-server benchmark-tmm-runner benchmark-runner
```

`benchmark-tmm-runner`가 없거나 이전 image를 사용하면 BenchmarkRun이 `Waiting for durable TMM worker`에 머무를 수 있다. API와 두 runner는 동일 commit으로 rebuild해야 한다.

## 3. Worker 상태 확인

```bash
docker compose ps api-server benchmark-tmm-runner benchmark-runner
docker compose logs --tail=200 benchmark-tmm-runner
docker compose logs --tail=200 benchmark-runner
```

BenchmarkRun을 시작한 뒤 API status에서 stage와 heartbeat가 갱신되는지 확인한다. 동일 snapshot에 대한 중복 run은 만들지 않는다. 기존 run이 old revision에서 완료 또는 실패했다면 새 revision으로 명확히 구분되는 새 run을 한 번 생성한다.

## 4. Expected optimized contract

| 항목 | 기대값 |
|---|---:|
| Site aggregation | median |
| Wave correlation threshold | 0.70 |
| Wave minimum amplitude | 0.40 |
| Wave count | 8 |
| TMM profile minimum exclusive substrate | 5 |
| TMM Gaussian sigma log-time | 0.80 |
| TMM target transform | magnitude |
| TMM candidate modules | 59 |
| TMM profiles | 55 |
| Contribution site entries | 4,486 |
| Cascade timepoints | 6 |
| Directionality edges | 0, accepted with non-causal note |
| Locked canonical weighted score | 0.7333333333 |

Raw preprocessing과 external annotation availability가 완전히 동일할 때 위 count가 재현되어야 한다. External annotation source가 변경되면 candidate module 수가 달라질 수 있으므로, 해당 경우에는 `tmm_input_kinase_provenance`와 source cache revision을 함께 기록한다.

## 5. Artifact verification

완료된 run의 truth-free artifact와 locked score JSON을 내려받은 뒤 다음을 실행한다.

```bash
cd <PTM-platform-server-path>
PYTHONPATH="$PWD/api-server:$PWD" python3 scripts/verify_temporal_benchmark_handoff.py \
  --artifact /path/to/benchmark_blind_analysis_artifact.json \
  --locked-score /path/to/locked_score_result.json \
  --output /path/to/handoff_verification.json
```

종료코드 0과 `"passed": true`가 필요하다. 방향성 edge 0은 이번 frozen run의 예상 결과이며, cascade 6개 timepoint가 별도로 확인되어야 한다.

## 6. Figure 및 source-data 확인

Figure 1–4와 `benchmark_source_data.zip`을 함께 보관한다. Figure 3에는 실제 TMM bar와 fractional contribution record가 있어야 하고, Figure 4에는 1·5·15·30·60분 contribution-weighted cascade가 있어야 한다. Figure 4의 directionality panel은 stable kinase-pair edge가 없음을 명시해야 하며, 이를 pipeline failure 또는 causality evidence로 해석하지 않는다.

```bash
sha256sum figures/Fig1.svg figures/Fig2.svg figures/Fig3.svg figures/Fig4.svg benchmark_source_data.zip \
  > publication_bundle.sha256
```

## 7. 실패 시 점검 순서

| 현상 | 우선 점검 |
|---|---|
| TMM profile 0 | `include_tmm_candidate_modules`, pre-redistribution graph, worker revision |
| Contribution 0 | site별 candidate multiplicity와 `tmm_site_contribution_matrix` |
| Figure 3 blank | artifact field persistence와 publication bundle revision |
| Cascade 0 | `tmm_weighted_temporal_cascade` serialization |
| Mapping 감소 | FASTA accession/OX provenance와 normalized vector gene/site key |
| Score 불일치 | preprocessing hash, sample ordering, locked truth version, scorer revision |

## 8. Rollback 원칙

서버에서 예상하지 못한 regression이 발생하면 configuration 값을 임의로 조정하지 않는다. 이전 안정 commit으로 worker와 API를 함께 되돌리고, failed artifact·worker log·config hash를 보존한 뒤 원인을 분석한다. Locked workbook을 tuning에 다시 사용하거나 insulin-specific kinase/site를 코드에 hardcode해서는 안 된다.
