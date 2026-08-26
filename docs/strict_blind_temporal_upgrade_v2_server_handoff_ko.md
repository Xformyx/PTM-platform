# Strict-blind Temporal Attribution Upgrade v2 — Server Handoff

## 1. 동결 provenance

| 항목 | 값 |
|---|---|
| Contract | `truth_free_temporal_optimized.v2` |
| Runtime config SHA-256 | `ee1671c91e1b8913b35e7eb95c1d9ea3ed916b1f220c69d31a1bbeb96dfa9455` |
| Selection ledger SHA-256 | `2a6c7c728b2b931cb00f275e39be721a4ed904f95c566077219c3f5c254201e1` |
| Last ledger record SHA-256 | `f535cb2e319de574395b7e108216832ba5154d1c4a0bf4f415321f6db59f1b7a` |
| Workbook SHA-256 | `a2cb7d6ab1167983198f80627ca412cdde78530cdfe0ecd9dbc6849f073ab484` |

## 2. 배포 전 백업

```bash
cd <PTM-platform-server-path>
git status --short --branch
git rev-parse HEAD
docker compose ps
```

현재 commit과 실행 중인 container image tag를 운영 기록에 보존한다. 기존 BenchmarkRun 결과 directory는 삭제하지 않는다.

## 3. 코드 동기화와 image rebuild

```bash
cd <PTM-platform-server-path>
git fetch github
git pull --ff-only github main
docker compose up -d --build api-server benchmark-tmm-runner benchmark-runner
docker compose ps api-server benchmark-tmm-runner benchmark-runner
```

`benchmark-runner` rebuild는 필수다. Figure SVG를 font-independent glyph path로 바꾸기 위한 `fonttools` dependency가 새 image에 설치된다.

## 4. Runtime config 확인

```bash
docker compose exec benchmark-tmm-runner \
  python -m ptm_shared.temporal_optimization_config
```

출력의 `config_sha256`가 `ee1671c9…9455`, `truth_used_for_selection`이 `false`, `iterative_profile_decision`이 `rejected_rounds_zero_retained`인지 확인한다.

## 5. 동일 snapshot strict BenchmarkRun

기존 source Order에서 새 strict BenchmarkRun을 생성한다. 다음이 분석 runtime에 전달되지 않아야 한다.

| 차단 항목 | 기대 상태 |
|---|---|
| Treatment/stimulus | masked |
| Biological question | masked |
| Exact cell line/transgene | masked |
| RAG/report/LLM context | disabled |
| Locked workbook | `benchmark-runner`에만 mount |

`benchmark-tmm-runner`와 `benchmark-runner` log에서 stage heartbeat가 갱신되고 queue가 실제 소비되는지 확인한다.

```bash
docker compose logs -f --tail=200 benchmark-tmm-runner benchmark-runner
```

## 6. 자동 acceptance verification

Completed run의 truth-free artifact, locked result와 Figure directory를 확인한 후 다음을 실행한다.

```bash
PYTHONPATH=. python scripts/verify_temporal_benchmark_handoff.py \
  --artifact <run-dir>/benchmark_blind_analysis_artifact.json \
  --locked-score <run-dir>/raw_score_summary.json \
  --figures-dir <run-dir>/figures \
  --output <run-dir>/handoff_verification_v2.json
```

`passed: true`가 아니면 일반 production default 승격이나 manuscript artifact 교체를 중단한다.

| Acceptance check | Expected |
|---|---:|
| Mapped sites | 2,447 |
| Waves | 8 |
| TMM profiles | 55 |
| Relative contribution sites | 2,243 |
| Occupancy contribution sites | 768 |
| Cascade timepoints | 6 |
| Consensus repeats | 25 |
| Adaptive uncertainty | evaluated 1,835; resolved 1,485 |
| Main directionality edges | 0 accepted, evidence gate present |
| Primary weighted score | 0.7333 |
| Figure 1–4 | zero `<text>` nodes; glyph `<path>` present |

## 7. 해석 경계

Server 결과의 kinase score는 motif-seeded attribution이다. Data-anchored kinase coverage가 0이므로 motif prior를 direct kinase–substrate evidence로 보고하면 안 된다. Directionality main edge가 0인 것은 오류가 아니라 D2+와 endpoint evidence gate를 통과한 관계가 없다는 결과다.

## 8. Rollback

다음 중 하나라도 발생하면 새 run을 논문 결과로 사용하지 않는다.

| Failure | Action |
|---|---|
| Config/ledger hash mismatch | image와 mount revision 확인 후 rebuild |
| Worker queue 미소비 | `benchmark-tmm-runner` queue name과 Redis 상태 확인 |
| Contribution alias 재출현 | deployment revision mismatch로 판단 |
| Consensus probability 없음 | `benchmark-tmm-runner`가 v2 code를 사용하지 않는 상태 |
| SVG에 `<text>` node 존재 | `benchmark-runner` rebuild 누락 |
| Primary denominator 변화 | source snapshot 또는 locked manifest mismatch |

문제가 해결되지 않으면 배포 전 commit/image로 복구하고 새 BenchmarkRun만 폐기한다. 기존 completed run과 locked artifacts는 삭제하지 않는다.
