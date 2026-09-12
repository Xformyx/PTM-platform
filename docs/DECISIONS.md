# 협업 결정 기록

결정은 추가 기록으로 관리한다. 이전 결정을 바꿀 때 삭제하지 않고 대체하는 결정 ID와 사유를 남긴다.
연구 방법·사전등록·측정 변경은 기존 [구현 원장](implementation_log.md)의 append-only 규칙도 따른다.

## COLLAB-DEC-001 — 문서 기반 수동 협업 구조

- 날짜: 2026-09-11
- 상태: 합의됨
- 근거: 사용자 B의 현재 협업 문서 생성 요청에 명시된 역할 및 범위. 신규 과학적 판단이나 구현 TASK 승인으로 해석하지 않는다.
- 결정: A의 ChatGPT Work는 Research PI + Scientific Reviewer, B의 ChatGPT Work는 Research Collaborator/Student. GitHub를 Single Source of Truth로 사용한다.
- 실행 경로: 승인된 TASK를 Cursor가 구현하고 Mac Studio staging에서 실행·검증한다.
- OpenClaw: 선택적 운영/알림 보조도구.
- 초기 범위: 문서 구조만. 자동화/Orchestrator는 구현하지 않는다.
- 기존 기록: 보존하며 새 협업 문서는 색인과 인계 역할을 담당한다.
- 상세: [PROJECT_CONTEXT](PROJECT_CONTEXT.md).

## 이후 결정 양식

- 결정 ID / 제목 / 날짜:
- 상태: proposed / accepted / superseded / rejected
- 제안자 / 승인자 / 승인 일시:
- 배경·질문:
- 검토한 선택지·근거:
- 결정·적용 범위:
- 반대 근거·해석 한계:
- 대상 문서·TASK·commit:
- 승인 근거 링크:
- 대체하는 결정 / 후속 행동:

AI가 제시한 판단과 사용자가 승인한 결정을 구분한다. 승인자를 추정하거나 승인 날짜를 소급 기입하지 않는다.
