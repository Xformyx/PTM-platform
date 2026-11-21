# V04 화면과 원본 연결 검증

V03 체크포인트는 `b8b68c1`이다. FastAPI, 기존 정량표를 읽는 함수, React 컴포넌트와 Chrome을 사용했다. 브라우저에는 합성 주문의 API 응답을 연결했다.

| 검증 경계 | 실제로 대조한 내용 |
|---|---|
| 시간 grid | Top 1에서 사라진 중간 조건, opaque label의 기록 시간, 일부 시간 미기록, 같은 5분의 서로 다른 비교를 확인했다. TSV와 Parquet가 같은 precursor의 별도 contrast를 유지한다. |
| 접근과 전송 | 목록을 읽은 뒤 두 번째 발행본으로 pointer를 교체했다. 과거 run에 대한 상세·kinase·관계 요청은 409였다. 전송 전에 TSV 경로 교체와 같은 파일의 내용 변경을 각각 시험했다. |
| Explorer | 손상된 derived run의 409 뒤 정상 parent를 열었다. pathway 503에서도 precursor와 kinase를 열었다. 늦은 응답, 키보드 포커스, 밝은·어두운 테마의 heatmap 글자 대비 4.5 이상을 확인했다. |
| 실제 컴포넌트 | Scatter에서 선택한 행의 측정 revision과 precursor를 U/P/A 상세, bundle의 feature, 근거 목록까지 대조했다. Astra Primary A에서 합성 matched form과 kinase를 열고 pin 파일의 실제 run·catalog·points 원본 참조를 확인했다. |
| 실제 저장 결과 | 공통 Control archive 1건을 읽었다. ZIP 내부 5개 파일과 추출본의 SHA-256 및 대표 form의 6개 contrast를 대조했다. 전체 패키지를 복제하거나 과학 계산을 다시 수행할 필요가 없었다. |

브라우저 검증 과정에서 좁은 화면의 차트 resize와 kinase 모듈 버튼 줄바꿈을 수정했다. 대량 All은 기존 columnar 페이지·Canvas로 열고, TSV만 있는 경우 선정된 기질을 100개씩 그린다. 기존 과학 코드가 사용하는 `ordered_conditions`의 순서는 유지했다. 저장된 원본 TSV에 scope 열이 있을 때만 표시용 조건을 분리한다.

최종 수치와 재현 경로는 같은 디렉터리의 `VECTOR_WORKSPACE_RESULTS.json` 및 `VECTOR_WORKSPACE_UPGRADE_KO.md`에 기록한다.
