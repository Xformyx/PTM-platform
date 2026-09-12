# 승인된 작업의 작성과 인계

TASK 파일 이름은 COLLAB-TASK-001-short-title.md 형식을 사용한다. 기존 번호와 파일 존재 여부를 확인한다.
이 README는 양식이며 승인된 실행 TASK가 아니다.

## TASK 양식

- ID / 제목 / 작성일 / 작성자:
- 상태: proposed / approved / in_progress / review / blocked / done / cancelled
- 연구·백로그·질문 링크:
- 기준 branch / commit / 관련 설계 절:
- 문제·목표:
- 포함 범위 / 제외 범위:
- 산출물·예상 변경 파일:
- 데이터·환경·의존성:
- 사전등록·동결 제약:
- 완료 기준(검증 가능한 조건):
- 검증 계획(방법·예상 결과·실패 조건):
- Mac Studio staging 실행 계획 / 해당 없으면 사유:
- PI 검토:
- Scientific Reviewer 검토(반증·누출·주장 범위):
- 승인: 사용자 A / 날짜 / 승인한 TASK 버전·commit / GitHub 근거 링크:
- 구현 담당 / 검증 담당:
- 구현 PR / commit:
- 실제 검증 결과·산출물·미실행 항목:
- 리뷰 링크 / A의 수용 기록:
- 잔여 문제 / 다음 행동:

## 실행 규칙

사용자 A가 범위와 완료 기준을 승인한 뒤 Cursor가 구현한다. proposed를 구현 승인으로 취급하지 않는다.
범위·방법·평가 기준이 바뀌면 변경 사항을 기록하고 재승인을 받는다.
코드 구현과 staging 검증을 구분하며 실패·미실행 항목을 숨기지 않는다.
연구 변경은 [기존 구현 원장](../implementation_log.md)의 기록 규칙을 함께 따른다.
done 전 완료 기준 충족, 필요한 리뷰 및 사용자 A의 수용 기록을 확인하고 [현황](../RESEARCH_STATUS.md)과 [백로그](../BACKLOG.md)를 갱신한다.
