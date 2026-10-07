# 회차 04 — reference 재사용과 명시적 갱신

2026-10-07. 기준 `d5733778bf47398a21e9d5fd7db47fff7e6def69`, 브랜치 `feature/round04-reference-provenance`. 시작 시 tracked 변경 없음, `codex-inputs/` 미커밋 자료 보존. 적용할 AGENTS.md는 발견되지 않았다. 회차 02·03의 renderer/identity 파일은 기준 commit과 byte-identical이다.

## 변경 및 재사용

| Production 파일 | 변경 내용 / 기존 함수 |
|---|---|
| `api-server/app/api/orders.py` | `_updated_analysis_context`, `_attach_enrichment_free_profile`, `resolve_order_design`, get/copy/rerun의 기존 pin 전달을 연결. 갱신 때도 이전 hash를 dispatch에 보존. 성공한 갱신의 새 pin은 다음 재분석의 기본값으로 승계. 과거 Order/패키지 bytes를 수정하지 않음. |
| `ptm_shared/astra_sources.py` | 기존 `resolve_sources`, `SourceClient.query/accept`, `pin_sources` 유지. pin 검증·실행 설명 helper 추가. 기존 Reactome adapter의 유효 빈 배열이 `accept()`를 거치도록 수정해 검증된 no_hit도 기존 cache에 저장. 새로운 수집기/cache는 없음. |
| `ptm_shared/astra_package.py` | `run_astra_analysis`의 요청/실제 정책을 plan·provenance·readiness·Results·START_HERE에 동일하게 기록. 명시적 갱신이 partial이면 진단 pin/실행 기록/단계 상태를 남기고 publish 이전에 중단. 기존 `quant_cached`, `cached_stage`, `StageLedger`, atomic current pointer 사용. Replay는 기존 직접 pinned-input 계산 경로 그대로이며 수집 resolver를 호출하지 않음. |
| `frontend/src/components/CanonicalStudyFields.tsx` | 기존 갱신 체크박스가 기존 `refresh_references`와 `acquisition_policy=research_full`을 전달. 새 옵션 체계 없음. API가 반환한 정책 설명 표시. |
| `frontend/src/components/PrimaryAEvidence.tsx` | 완료된 run의 `source_execution`을 표시. 편집 중 form 값으로 과거 결과를 표시하지 않음. |

추가 검증: `ptm_shared/tests/test_astra_source_policy.py`, `api-server/tests/test_astra_source_policy.py`, `scripts/validate_astra_reference_refresh.py`.

User create는 기존 `user_orders`의 `start_order` 위임을 이용한다. Admin create/start·copy·rerun은 기존 공용 context resolver와 `_attach_enrichment_free_profile`을 통과한다. `workers/preprocessing/tasks.py`는 config를 `run_primary_analysis`로 전달하므로 별도 worker selector/수집 설정은 추가하지 않았다. v6의 `source_universe`, `taxon_round_robin.v1`, `source_acquisition.string_network`, 기존 성공 query cache와 prior-pin 보존 경로를 유지했다.

## 실행 계약

`references/source_execution.json` 및 plan/provenance/readiness/platform result의 같은 객체에 `requested_policy`, `effective_pin_policy`, `pin_reused`, `reuse_reason`, `refresh_requested`, `previous_pin_sha256`, `used_pin_sha256`, `acquisition_executed`, `status`, `incomplete_queries`를 기록한다. 이 run metadata를 원 pin 안에 넣어 기존 hash를 바꾸지 않는다.

| 동작 | 확인 결과 |
|---|---|
| Archive replay | 원 source pin 사용. 저장 context에 refresh=true가 있어도 수집 resolver 호출 없음. 네트워크 차단 fixture에서 68개 scientific table 재현, 모두 byte-identical. |
| 같은 근거 재분석 | 엔진/profile 요청만으로 pin 갱신 없음. bounded pin이면 요청 research_full과 실제 legacy_bounded를 분리하고 **기존 제한된 근거 재사용, 이번 전체 수집 미실행** 표시. 정책 없는 과거 pin은 unknown. |
| 명시적 갱신 | 기존 refresh 경로로 새 research_full pin 생성. fixture에서 Reactome 3개→7개 전체 대상 조회, 기존 3개 cache 재사용. 정량 cache 재사용, source hash 의존 discovery 이후 단계 갱신. |
| 갱신 partial/failure | timeout·미실행 항목을 기록. 기존 성공 pointer와 ZIP 보존. incomplete 상태를 완료 ZIP으로 publish하지 않음. 적용 불가 `not_supported`는 외부 장애와 구분. |

## 실제 HIRc-B 실행

입력 PR/PG/FASTA는 지정 g1 ZIP과 세 파일 모두 SHA-256 동일하다. 재정량을 피하기 위해 회차 01의 검증된 v6 run `g3-0d38baee90a74fab8516a9b2fe5738af`의 quant/evidence cache를 별도 output으로 복사했다. 원본 cache·원 archive·운영 주문은 수정하지 않았다. calculator를 실패하도록 패치한 검증 환경에서도 실제 실행이 완료되어 quant cache miss가 없음을 확인했다.

1. **g1 bounded pin 직접 재사용 검사**: 원본 ZIP의 `references/source_pin.json` bytes SHA는 `268a149eb1636c587a1ef85499ef2038cc8379759e055728713bf032f4640584`. 이 bytes를 그대로 등록하고 기존 resolver로 재사용했다. 요청 research_full, 실제 legacy_bounded, refresh=false, 네트워크 0. 원 ZIP SHA는 `5bd457114a356a32b50b2ac259d7ea77579f4b16369f70312fff1d2dc8a219fd`이며 불변이다. 내부에 기록된 원 acquisition hash와 ZIP 내 JSON 파일 bytes hash는 다른 층이므로 덮어쓰지 않았다.

2. **실제 cached 재분석 패키지**: `g0-8584adc408d24b81b2f5162735d066bf`. 요청 research_full, refresh=false, 이전/사용 pin 모두 `7560c13a6b430363744157d74ad160a83e0939ec0754cedce20d7c0fe9dcbd8e`. 이 과거 pin에는 acquisition policy 필드가 없으므로 **unknown**을 기록했다. 네트워크 0, quant·normalization sensitivity·identity·discovery·footprint·temporal cache 모두 reused. Quant 22개 표는 ID/text/NA 정확 비교와 수치 atol=rtol=1e-10 비교를 통과했고, 실제로 22개 모두 byte-identical. 새 package 검증은 186 files / 68 scientific tables 통과.

3. **Reactome 실제 갱신 점검**: `g0-30cd41fd89ec4726b687d7ac536380db`. 요청/획득 pin 정책 research_full, refresh=true. 새 pin `28c4c1d1f9d90d2b299aa2574f11dd8e5f2da3f17bd67e07f32c78a1b49c4b49`. 기존 resolver/client에 검증용 20 신규 요청·180초 공급자 예산을 전달했다. 다른 공급자의 신규 네트워크 요청은 이번 검증 범위 밖으로 명시했으며, production의 긴 research_full 예산을 20개로 바꾸지 않았다.

| Reactome 범위 / 결과 | 값 |
|---|---:|
| 과거 pin의 기록된 accession 모집단 | 4,749 |
| 과거 pin: access_unavailable / not_run_budget | 3 / 4,746 |
| 새 기존 v6 source_universe의 전체 대상 accession | 15,977 |
| 실제 신규 HTTP 요청 | 20 (human 1, rat 19) |
| 해당 실행의 Reactome cache hit | 0 |
| hit / no_hit | 7 / 13 |
| 실패 / 예산 미실행 accession | 0 / 15,957 |
| 이전 pin 대비 새 accession–Reactome pathway 관계 | 41 |
| 수집 후 offline cache readback | 20/20, 네트워크 0 |

13개 no_hit은 기존 Reactome mapping adapter의 `identifier_absent_HTTP_404` 처리 기준이다. 성공한 동일 endpoint 조회와 구분해 기록했으며 다른 공급자의 HTTP404를 no_hit로 바꾸지 않았다. 생물학적 pathway 부재나 kinase 비활성을 뜻하지 않는다. 새 41개 관계는 species 검사를 통과한 **pathway context**이며 direct kinase–site 근거나 분석 성능 향상을 의미하지 않는다.

두 실행의 모집단 차이는 기존 v6 `source_universe`의 전체 관측 PG accession 포함과 과거 제한 pin의 범위 차이이다. 20회 조회를 15,977개 전체 수집 완료라고 보고하지 않는다. cache readback은 새 관측 20개가 추가됐다는 뜻도 아니다.

**갱신 실행은 partial로 중단되었고 새 ZIP은 publish하지 않았다.** 직전 성공 pointer는 `g0-8584adc408d24b81b2f5162735d066bf`를 유지한다. 이전 pin bytes도 그대로다. 실제 갱신에서도 primary/alternative quant cache를 재사용했으며, partial 수집을 후보 계산에 적용하지 않았다. 완전한 갱신 뒤 discovery 이후 재계산은 synthetic 성공 fixture에서 검증했다.

## 검증과 산출물

```sh
env PYTHONPATH=api-server:. MPLCONFIGDIR=/tmp/ptm-round03-matplotlib \
 /tmp/ptm-science-v5-venv/bin/python -m pytest \
 ptm_shared/tests/test_astra_source_policy.py api-server/tests/test_astra_source_policy.py \
 ptm_shared/tests/test_astra_package.py ptm_shared/tests/test_astra_evidence_integration.py \
 api-server/tests/test_analysis_context_preservation.py \
 ptm_shared/tests/test_astra_figures.py ptm_shared/tests/test_astra_curves.py \
 -q --import-mode=importlib
```

**57 passed, 1 Starlette deprecation warning, 38.93 s.** API TestClient의 실제 `/orders/resolve-design` route에 일반 v5 payload와 기존 refresh checkbox 값을 전달했다. 기존 flag에 의한 v6 해석, copy/rerun context, worker dispatch helper의 이전 hash/refresh 값과 preview 설명 일치를 확인했다. 실제 orchestrator fixture에서 plan/provenance/readiness/platform result의 객체 동등성을 확인했다. 운영 DB/Celery/UI를 새로 실행한 end-to-end 검증으로 확대해서 보고하지 않는다.

프런트엔드 `npm run build` 통과. 기존 Browserslist 및 bundle size 경고가 있으며 이번 범위에서 변경하지 않았다. Round 02/03 heatmap·curve 회귀 검사 포함. 실제 과학 실행 당시의 `astra_sources.py`, `astra_package.py` hash가 제출 코드와 일치한다.

실제 검증 명령은 다음 순서였다. `prepare`는 이전 검증 cache와 입력을 복사하고 g1과 비교하며, quantification을 수행하지 않는다.

```sh
env PYTHONPATH=. MPLCONFIGDIR=/tmp/ptm-round03-matplotlib \
 /tmp/ptm-science-v5-venv/bin/python scripts/validate_astra_reference_refresh.py prepare \
 --output codex-inputs/round04-20261007 \
 --baseline-output /tmp/ptm-round01-20261006/output_dir/Round01_HIRcB_52030d7a \
 --reference-root /tmp/ptm-round01-20261006/reference_dir \
 --g1-archive /Users/josephk/Downloads/astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip
# 같은 environment에서:
python scripts/validate_astra_reference_refresh.py reuse --output codex-inputs/round04-20261007
python scripts/validate_astra_reference_refresh.py refresh --output codex-inputs/round04-20261007 --max-requests 20 --seconds 180
```

로컬 자료는 `codex-inputs/round04-20261007/` 아래에 보존했다. 추적하는 요약은 [ROUND04_RESULTS.json](ROUND04_RESULTS.json)이다.

- [동일 pin 재사용 패키지](../../codex-inputs/round04-20261007/output/astra_analysis_package_g0-8584adc408d24b81b2f5162735d066bf.zip)
- [실제 재사용 검증](../../codex-inputs/round04-20261007/reuse_validation.json), [실제 partial 갱신 검증](../../codex-inputs/round04-20261007/refresh_validation.json), [g1 bounded 재사용](../../codex-inputs/round04-20261007/g1_bounded_reuse.json)
- [전체 Reactome 대상/상태](../../codex-inputs/round04-20261007/REACTOME_QUERY_COVERAGE.csv), [새 pathway context 41개](../../codex-inputs/round04-20261007/NEW_REACTOME_CONTEXT.csv), [cache readback](../../codex-inputs/round04-20261007/reactome_cache_readback.json)
- [정량 불변성](../../codex-inputs/round04-20261007/quant_preservation.json), [테스트 로그](../../codex-inputs/round04-20261007/tests.log), [갱신 로그](../../codex-inputs/round04-20261007/refresh.log)

## 한계

완료 범위는 로컬 소프트웨어 연결·fixture·동일 HIRc-B cached 재분석·Reactome 제한 실조회이다. 운영 환경/배포는 미확인이다. 전체 15,977 accession 및 다른 공급자의 research_full 수집은 이번 실제 검증에서 완료하지 않았다. 신규 자원 전체를 적용한 scientific 결과나 품질 향상을 주장하지 않는다. Localization/specificity/kinase threshold·판정/문헌 비교 및 회차 05 이후는 변경하지 않았다.
