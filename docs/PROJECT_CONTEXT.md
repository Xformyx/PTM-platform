# PTM 협업 프로젝트 컨텍스트

작성일: 2026-09-11. 이 문서는 협업 운영의 진입점이며 기존 과학적 설계·계약을 대체하지 않는다.

## 목적과 기존 구조

PTM-platform은 질량분석 기반 PTM 데이터를 전처리하고, 근거를 보강하여 분석 보고서를 만드는 플랫폼이다. 기술 개요는 [기존 아키텍처](01-architecture.md)를 따른다.
루트의 api-server, frontend, gateway, mcp-server, workers, ptm_shared, benchmarking, benchmarks, scripts 및 기존 docs/research_notes, docs/results를 유지한다.

## 역할

| 참여자/도구 | 합의된 역할 | 책임과 경계 |
|---|---|---|
| 사용자 A의 ChatGPT Work | Research PI + Scientific Reviewer | 연구 방향·우선순위·TASK 초안 및 과학적 검토를 지원한다. PI 의견과 Reviewer의 반증·한계 평가를 구분하여 기록한다. 최종 승인 주체는 사용자 A다. |
| 사용자 B의 ChatGPT Work | Research Collaborator/Student | 문헌 조사, 질문, 가설, 분석 계획과 결과 초안을 작성하고 근거를 연결한다. |
| GitHub | Single Source of Truth | 합의된 문서, TASK, 결정, 코드, 검토와 검증 결과의 기준 기록이다. |
| Cursor | 승인된 TASK 구현 | 승인된 범위와 완료 기준에 따라 구현하고 변경·검증 근거를 남긴다. |
| Mac Studio | staging 실행/검증 | 대상 commit과 환경을 기록하여 실행·재현성을 검증한다. 현재 가동 상태는 별도 확인 대상이다. |
| OpenClaw | 선택적 운영/알림 보조 | 필요 시 별도 검토한다. 연구 판단·승인 권한을 갖지 않는다. |

같은 사용자 A의 두 AI 역할은 독립된 사람의 검토와 동일하지 않다. AI의 제안이나 리뷰만으로 승인 처리하지 않는다.

## 수동 협업 흐름

1. A/B는 작업 시작 시 이 문서, [연구 현황](RESEARCH_STATUS.md), [결정](DECISIONS.md), 관련 TASK와 원문을 읽고 기준 commit을 기록한다.
2. B는 [질문](student/QUESTIONS.md) 또는 [백로그](BACKLOG.md)에 근거·불확실성을 포함한 제안을 남긴다.
3. A의 Research PI가 범위와 완료 기준을 구체화하고 Scientific Reviewer가 방법·반증·누출·해석 한계를 검토한다.
4. 사용자 A가 대상 TASK 버전과 범위를 명시하여 GitHub에 승인 기록을 남긴다.
5. Cursor가 승인된 TASK를 구현하고 PR 및 검증 근거를 연결한다.
6. Mac Studio staging에서 대상 commit을 실행·검증하고 [리뷰 기록](reviews/README.md)을 작성한다.
7. 사용자 A의 수용 판단 후 담당자가 상태·결정·백로그를 갱신한다. 병합은 저장소의 기존 권한과 절차를 따른다.

## 문서 지도와 충돌 처리

- [RESEARCH_MASTER](RESEARCH_MASTER.md): 기존 연구 설계와 근거의 색인.
- [RESEARCH_STATUS](RESEARCH_STATUS.md): 현재 인계 상태와 다음 행동.
- [DECISIONS](DECISIONS.md): 협업 결정 이력.
- [BACKLOG](BACKLOG.md): 미승인 제안과 TASK 연결.
- [Student Guide](student/STUDENT_GUIDE.md), [Questions](student/QUESTIONS.md).
- [TASK 작성 규칙](tasks/README.md), [리뷰 작성 규칙](reviews/README.md).

기존 원문·사전등록·동결 계약을 새 요약으로 덮어쓰지 않는다. 상충하면 양쪽 경로와 기준 commit을 기록하고 A에게 판단을 요청한다. 날짜나 파일 이름만으로 우선순위를 정하지 않는다.
GitHub에 반영되지 않은 채팅 합의는 공유 상태로 간주하지 않는다. 큰 데이터는 승인된 저장소에 두고 GitHub에는 위치·버전·해시·접근 조건을 기록한다.

이번 단계는 Markdown 문서 구조만 구축한다. 자동화, Orchestrator, 스케줄러, 에이전트 설정 및 OpenClaw 연동은 구현하지 않는다.
