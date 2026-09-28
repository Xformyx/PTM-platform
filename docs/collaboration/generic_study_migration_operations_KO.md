# Study design v3 migration·운영 등록

## Schema 및 migration

구조 정의는 `ptm_shared/study_design.schema.json`, 서버의 의미 검증은 `study_design.validate_study_design()` / `require_resolved()`다. UI는 `POST /orders/resolve-design`의 결과를 표시하며 별도 시간 파서를 사용하지 않는다. 계산 시작 전 서버와 worker에서 다시 검사한다.

- Study: organism/taxonomy, cell/tissue, treatment 원문, 연구 질문, 특수 조건, 원래 time_points, acquisition/processing.
- Arm: 안정 ID와 복수 treatment(name/dose/unit/status). 비화학적 조건은 dose_status=not_applicable로 표현한다.
- Condition: 안정 ID, arm ID, label, 입력 time(value/unit/original), 내부 minutes, role. 같은 시간도 서로 다른 condition이면 합치지 않는다.
- Material: 실제 측정 시료. Biological unit/donor/block/pair와 다른 개념이다. 동일 material ID를 다른 조건에 재사용하면 차단하며 unit/pair ID로 관계를 표현한다.
- Injection: 실제 input column과 material/condition/technical ID. 하나의 input column을 중복 배정하지 않는다.
- Contrast: target/reference condition ID와 pairing. 공통 baseline은 여러 contrast에서 같은 injection을 참조한다.
- Field provenance: 원값, 출처, confirmation 상태, 변환 규칙. Time tolerance는 abs=1e-8 min, rel=1e-12다. 보간하지 않는다.

우선순위는 기존 structured/manifest → 명확한 unit label/list 후보다. 자유 문자열과 충돌하면 문제 코드·field path를 반환한다. Time list와 파일 list를 위치로 zip하지 않는다. 기존 Rep는 condition suffix grouping과 명시적 technical 선언 후 번호 후보로만 사용한다.

V1 biological_unit은 과거 통계 grouping ID로 보존하고 material은 condition별로 구분한다. Paired v1의 관계는 그대로 pair ID에 이관하며 생물학적 donor 관계를 새로 추론하지 않는다. Unknown 반복은 descriptive-only, biological n은 unknown이다. 새 material 관계를 확인한 경우에만 biological unit 정보를 사용한다.

Draft 저장은 허용하지만 contrast/reference, time conflict, raw column 누락, pairing mapping, profile capability, 필수 snapshot의 문제는 Start에서 422와 이유로 차단한다. Canonical JSON을 직접 수정하거나 혼합 설계를 입력할 때도 같은 규칙을 적용한다. 미지원 schema version은 자동으로 v3로 바꾸지 않는다.

기존 주문은 v2/standard export mode를 그대로 읽는다. Generic으로 전환하려면 명시적으로 profile을 바꾼 새 실행을 만든다. 과거 output/provenance는 migration하지 않는다. Copy는 context를 복제하지만 새 order/run이며 재계산한다. Run directory와 완료 pointer를 분리하고, 검증된 ZIP이 생긴 뒤에만 pointer를 원자적으로 교체한다.

## Snapshot 등록과 호환성

새 registry metadata 권장 필드:

```json
{
  "schema_version": "annotation_registry.v2",
  "database": "source database name",
  "source": "source and retrieval method",
  "version": "frozen source version",
  "retrieved_utc": "recorded retrieval time",
  "database_sha256": "SHA-256 of snapshot.tsv",
  "taxonomy_ids": ["9606"],
  "ptm_types": ["phosphorylation"],
  "orthology_translation": false,
  "source_taxonomy_ids": ["9606"],
  "id_system": "UniProt_accession_and_gene_symbol",
  "required_files": [],
  "file_sha256": {}
}
```

위 값은 예시 schema이며 human annotation 등록·검증을 뜻하지 않는다. Snapshot TSV는 enzyme/substrate/residue_type/residue_offset/modification/sources/references가 필요하다. 실제 종·ID·orthology 정보는 원자료 근거로 채운다. Unknown legacy metadata는 compatibility_unknown이며 generic 필수 annotation에 사용할 수 없다.

HIRc-B snapshot `80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07`은 기존 metadata/audit를 해석하는 adapter가 있다. Rat endpoint의 human→rat translation과 Rat_hir의 human INSR coverage를 구분한다. Source caution/priming-site audit 파일을 함께 제공한다.

관리자가 승인된 reference 디렉터리에서 다음 명령을 실행한다. 변수는 해당 환경의 실제 검증된 경로와 digest로 설정한다.

```bash
PYTHONPATH=. python scripts/register_frozen_annotation.py \
  --snapshot "$SNAPSHOT_TSV" --audit-dir "$ANNOTATION_AUDIT_DIR" \
  --sha256 "$SNAPSHOT_SHA256" --reference-root "$PTM_REFERENCE_ROOT"
```

등록 스크립트는 staging directory에서 snapshot/metadata/필수 audit를 검증한 뒤 원자적으로 등록한다. 이미 유효한 content-addressed 디렉터리는 변경하지 않는다. 실패한 불완전 디렉터리 때문에 재시도가 막혔다면 원인을 확인한 뒤 `--recover-incomplete`를 추가한다. 이 옵션은 기존 불완전 디렉터리를 hidden recovery 이름으로 보존하고 검증된 사본을 게시한다.

API의 인증된 `GET /orders/frozen-annotations?taxonomy_id=…&ptm_type=…`에서 ready 및 정확한 digest를 확인한다. Empty registry, 권한 오류, 접근/서버 오류, incompatible, checksum/metadata invalid는 다른 상태다. 사용자 UI에는 다음 행동을 표시하며 서버 경로는 노출하지 않는다.

## 배포 절차와 실제 확인 범위

이번 검증에서는 격리된 API/worker가 같은 reference root를 사용해 synthetic human snapshot과 실제 HIRc-B snapshot을 읽었다. 실제 작업 실행과 bundle digest로 확인했다. 운영 volume의 상태를 확인한 것은 아니다.

코드 배포와 reference 배포는 별도다. 운영 담당자가 다음을 순서대로 확인한다.

1. 인계 revision과 테스트 근거를 확인한다. 기존 실행이 끝나도록 하고 input/output/reference를 보존한다.
2. 기존 [배포 스크립트 안내](../../scripts/README.md)에 따라 API·worker의 공통 Python 코드와 frontend를 반영한다. 실행 중 코드를 덮어써 loaded code와 bundle source가 달라지지 않게 worker를 재시작한다.
3. Compose의 API/전처리 worker가 같은 reference volume을 읽는지 실제 mount와 각 프로세스의 REFERENCE_DIR로 확인한다. 코드 push만으로 reference 데이터가 배포되지는 않는다.
4. 승인된 snapshot을 등록하고 각 서비스에서 동일 digest/metadata/audit가 보이는지 검사한다. 유효한 기존 snapshot을 덮어쓰지 않는다.
5. 운영 권한이 있는 담당자가 목록 API, 사용자 선택, worker 접근, 정상적인 새 주문의 report/ZIP run ID·hash를 확인한다. 로컬 fixture 주문 생성 스크립트를 운영에 실행하지 않는다.
6. 확인 전에는 운영 URL 적용 완료라고 보고하지 않는다. 이번 인계의 운영 배포/실제 URL 확인 상태는 pending이다.

## Rollback

기존 v2 결과와 raw input은 보존되어 있으므로 과거 결과를 재작성할 필요가 없다. 코드 rollback은 배포 전 revision/image로 되돌리고 API·worker·frontend를 함께 재시작한다. 새 generic 주문의 실행은 일시 중지하고 legacy profile로 몰래 재해석하지 않는다. 새 run ZIP은 독립 archive/replay가 가능하므로 삭제하지 않는다. 유효한 annotation 디렉터리는 content-addressed 자료로 유지한다.

운영 DB schema migration은 이번 변경에 필요하지 않다. 기존 JSON context에 canonical design을 추가하며, 과거 결과를 현재 주문 설정으로 설명하지 않는다. 실패/중단 export directory는 완료 pointer에 게시되지 않는다.
