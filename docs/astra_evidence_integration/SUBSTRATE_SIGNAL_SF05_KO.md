# SF05 패키지와 최종 작성 경로

SF04 `5eeb0aa` 다음 단계. `write_reader → write_signal_flow → project_signal_flow`를 일반 v6 발행, immutable reader revision, archive replay 공통 경로에 연결했다. source 입력은 메모리의 중간 값이 아니라 dictionary에 등록된 저장 CSV와 실행 study_design이다. `READER_CODE_FILES`에 flow/view/reader 모듈을 포함했다. 기존 quant/discovery/temporal 코드 fingerprint 구성은 바뀌지 않는다.

산출물은 `signal_flow/`의 7개 등록 표(trajectories, pattern membership, candidate associations, kinase bundles/membership, typed links, hypothesis ledger), `reader/SUBSTRATE_SIGNAL_FLOW.md`, `substrate_signal_packet.json`, U/P/A SVG·PNG·point CSV다. 표 key/grain은 TABLE_KEYS, null/status/단위는 공통 quantitative_fields descriptor를 따른다. 그림 point grain은 trajectory_id × contrast_id이며 원 quant source_ref를 가진 표시 binding이다. U/P/A는 log2_ratio, 시간은 canonical minutes, counts는 명시된 projection grain이다. native/diagnostic 중첩 값은 원 source field 계약을 따른다.

전체 relation edge를 method bundle마다 복사하던 초기 projection은 실제 큰 표에서 과도한 중복을 만들었다. 발행하지 않고 중단한 뒤 candidate × series 공통 association locator와 source key 집합으로 정규화했다. 가설도 기존 bundle 진단을 참조한다. native membership의 selected=false 행은 접근 가능하지만 기여 count/signature에는 포함하지 않는다. 원본 method membership와 수치는 변경하지 않았다.

그림은 적격 관측점 수 다음 안정 ID 순의 최대12 preview다. stable-ID heatmap preview와 중요도를 혼동하지 않으며 전체 trajectory와 selection ledger는 유지한다. included=false finite A는 heatmap 표시에서 null이고 원 CSV는 그대로다. 일반 발행/현재 코드 revision은 저장 표로 그림을 생성한다. archive replay는 point binding을 다시 생성해 byte 비교한 후 manifest 검증된 그림을 재사용한다. 이는 호스트 font 탐색 subprocess를 허용하지 않고 원 렌더링을 보존하기 위한 선택이다.

`writer_node`는 명시된 output_dir의 발행 pointer/provenance/packet hash를 검증해 같은 packet을 temporal evidence, biological synthesis, authoring state에 전달한다. 두 formatter는 실제 U/P/A·bundle·반대 근거·가설과 전체 source locator를 공급한다. `prepare_reader_figure_manifest → saved_signal_figure`는 같은 그림 hash와 quantitative binding을 사용한다. Astra 목적 주문에 새 RAG/report 실행을 자동 추가하지 않았다. saved/frozen writer fixture로 전달을 검증했으며 실제 새 모델 보고서는 만들지 않았다.

검증: source→projection→catalog→claim check→figure→두 report formatter 통과. finite-excluded heatmap 회귀 통과. 관련 그림/temporal/biological synthesis 테스트 38개와 신규 전달2개 통과. 격리 reader entrypoint 정상 발행/revision/replay 및 source 보존 테스트 통과. 초기 실패(저장 전후 empty/null 표현, font discovery subprocess)는 원인을 수정하고 재검증했다. 전체 과학 계산은 작은 기존 package fixture만 사용했다. 실제 원본은 새 과학 계산 없이 SF06에서 확인한다. 단계 SHA는 최종 보고/checkpoint 참조.
