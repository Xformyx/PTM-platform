# V01 시간 grid와 관측 적격성
시작 main b1f69bf → 원격 기준 3311050 fast-forward. 작업 브랜치 codex/vector-workspace. 기존 codex-inputs는 미추적 상태로 보존했다.
전체 TSV snapshot / columnar distinct condition,time_minutes → condition_grid → classic Top-N. 시간 충돌과 label fallback을 표시하고, 관측 없는 조건도 유지한다. 숫자 분축·선형선·null gap, empty 축 선택과 재시도를 제공한다. 다중 부위 화면은 저장된 pair만 소비한다.
vector_view_v2 및 classic_top_n 24개 통과. 다음 V02는 발행 revision과 파일 bytes를 확인한다.
