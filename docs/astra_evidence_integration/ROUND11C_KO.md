# 11-C — 저장 결과의 그림 의미와 읽기 순서

11-B 성공 run `g5-b2d6432b11e741ea9f998126903de0c1`의 저장 표만 사용했다. `revise_temporal → read_tables → attach_temporal/attach_reading_guidance → figure_packet/write_reader → seal_archive`를 재사용했다. 호출 중 과학 계산·문헌 collect·네트워크를 금지하는 검증 guard를 적용했다. 원 성공 ZIP/pointer는 수정하지 않았다.

## 변경과 보존

- `astra_figures.heatmap_grid`의 기존 열 순서/첫 50 stable form ID는 유지. `heatmap_style`은 선택 grid 전체의 max(abs(A))로 대칭 범위를 정하고 0은 중립색, NA는 회색으로 표시한다. 전부 0/NA인 경우 표시 범위만 ±1이며 셀 값은 바꾸지 않는다.
- Detection은 순차색과 정수 injection count 눈금. `scheduled_n` 분모를 기존 열 metadata에 연결하며 biological n으로 표시하지 않는다.
- `feature_identity.project_reader_display_identity`를 확장해 gene·후보 좌표·multiple mapping 표시와 원 ID/전체 mapping crosswalk를 보존한다. 대표 site/localization을 만들지 않았다.
- `astra_reader`의 기존 authoring rules/READ_ME, `astra_package.start_here`: 원문 질문·readiness → 선정/보류 → 시간/방법/문헌 → 필요한 원본 행 순서. 큰 source pin을 최초 필수 읽기로 요구하지 않는다.
- `PrimaryAEvidence`: 실제 reader/method/literature와 참조 부분 완료, localization 미측정을 각각 보여 준다. 정책 이름은 완료 상태가 아니다.
- `astra_reader_revision`: 기존 불변 복사/봉인 경로에 선택적 그림 갱신을 연결했다. 고정 문헌 pin의 기존 apply만 호출해 완료된 빈 비교를 `compared_no_supported_relationship`로 표현한다. 새 검색·판단은 없다.

실제 PNG 두 장을 직접 열어 label/단위/색/시간순서/잘림을 확인했다. 원본 그림 25개 중 source/curve 등 21개 byte 동일. 의도된 수정은 heatmap SVG 두 개, detection 열 metadata, figure legend다. 새 PNG·row crosswalk·display metadata를 추가했다. 첫 50행, A 1→5→15→30→60→180분, detection Control→동일 시간 순서, 7개 kinase series/41개 유효 값과 Mapk3 60분 결측 gap은 보존했다. Heatmap은 생물학적 상위 50개가 아니다.

## 실제 검증

새 reader/display revision `g0-f52d284b915048499b2679bff066a9ec`, 부모 g5. ZIP SHA `7d912036f4f3d24c43122bb4fa2346b30ec91b01c1925b42eb016bc9aa3610bd`.

정량·과학·adapter·cards/findings·문헌 CSV를 포함해 reader/packet 외 모든 기존 dictionary 표 byte 동일. reference pin/문헌 pin/선정 ID·순서 보존. 수정 전후 heatmap source 값·NA와 원 column ID/label 대응 정확 비교. 과학 재계산·method 실행·RAG/LLM 호출 0.

고유 Python 회귀 18개 통과(시간/곡선 기존 회귀 + 중립색/0/NA/분모/identity + 작성 지침). Frontend TypeScript/Vite build 통과; 기존 큰 bundle/Browserslist 경고는 남는다. 새 패키지 자체 코드의 offline reader replay 21개 파일 byte 동일, 네트워크 0. 상대 링크 누락 0. 검증 수·선정 목록은 `ROUND11C_RESULTS.json`에 기록했다.

변경 전 SVG: `codex-inputs/round11-20261010/B/downloaded-g5-b2d6432b11e741ea9f998126903de0c1/figures/`. 변경 후 PNG/SVG 및 읽기 문서: `codex-inputs/round11-20261010/C/final/enrichment_free_runs/g0-f52d284b915048499b2679bff066a9ec/`. 실제 이미지·ZIP은 임시 검증 산출물로 Git에 넣지 않았다.

운영 release/flag는 변경하지 않았다. 11-D에서 같은 코드의 일반 로컬 UI 재실행/Results 다운로드와 동일 pin·cache 재사용을 확인한다. 새로운 Astra 세션 소비와 운영 사용환경 확인은 별도 접근이 필요하다. 그림 개선은 과학 성능·kinase 활성 검증이 아니다.
