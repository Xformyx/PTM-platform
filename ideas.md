# PTM Pipeline Docs 웹사이트 디자인 브레인스토밍

## 프로젝트 특성
- 기술 문서 웹사이트 (파이프라인 매뉴얼)
- 팀원 공유 목적
- 3개 Worker의 구조, 기능, 연결 관계를 시각적으로 설명
- 코드 블록, 테이블, 다이어그램이 많은 기술 콘텐츠

---

<response>
<text>
## Idea 1: "Blueprint" — 기술 설계도 미학

**Design Movement**: Industrial Blueprint / Technical Drawing 스타일
**Core Principles**: 
1. 정밀한 그리드 기반 레이아웃으로 기술 문서의 구조적 명확성 강조
2. 모노스페이스 타이포그래피와 다이어그램 중심의 시각적 언어
3. 청사진 색상 팔레트(딥 네이비 + 화이트 라인)로 엔지니어링 느낌

**Color Philosophy**: 딥 네이비(#0a192f) 배경에 밝은 시안(#64ffda) 악센트. 기술 설계도의 정밀함과 신뢰감을 전달.
**Layout Paradigm**: 좌측 고정 사이드바 네비게이션 + 우측 넓은 콘텐츠 영역. 섹션 간 점선 구분선.
**Signature Elements**: 그리드 배경 패턴, 노드 연결선 애니메이션, 코드 블록 하이라이팅
**Interaction Philosophy**: 호버 시 노드 확대, 클릭 시 상세 패널 슬라이드
**Animation**: 페이지 전환 시 와이어프레임 드로잉 효과, 스크롤 시 파이프라인 노드 순차 등장
**Typography System**: JetBrains Mono (코드/제목) + IBM Plex Sans (본문)
</text>
<probability>0.06</probability>
</response>

<response>
<text>
## Idea 2: "Specimen" — 과학 논문 표본 미학

**Design Movement**: Scientific Publication / Academic Journal 스타일
**Core Principles**:
1. 학술 논문의 깔끔한 2-column 레이아웃을 웹에 재해석
2. 세리프 타이포그래피로 권위감과 가독성 확보
3. 미니멀한 색상 사용, 데이터 시각화에만 컬러 집중

**Color Philosophy**: 순백(#fafaf9) 배경에 차콜(#1c1917) 텍스트. 악센트는 생물학적 그린(#16a34a)과 경고 앰버(#d97706). 학술적 신뢰감.
**Layout Paradigm**: 상단 고정 TOC 바 + 메인 콘텐츠 중앙 정렬. 사이드 마진에 주석/참조 표시.
**Signature Elements**: 논문 스타일 섹션 번호링, Figure/Table 캡션, 마진 노트
**Interaction Philosophy**: 부드러운 스크롤 앵커, TOC 하이라이트 추적, 코드 블록 복사 버튼
**Animation**: 최소한의 fade-in, 스크롤 진행률 표시 바, 섹션 전환 시 부드러운 슬라이드
**Typography System**: Crimson Pro (제목) + Source Sans 3 (본문) + Fira Code (코드)
</text>
<probability>0.04</probability>
</response>

<response>
<text>
## Idea 3: "Circuit" — 회로 기판 인터랙티브 미학

**Design Movement**: PCB (Printed Circuit Board) / Data Flow Visualization
**Core Principles**:
1. 파이프라인의 데이터 흐름을 회로 기판의 전기 신호 흐름으로 시각화
2. 다크 모드 기반, 네온 트레이스 라인으로 Worker 간 연결 강조
3. 인터랙티브 다이어그램이 문서의 핵심 네비게이션 역할

**Color Philosophy**: 다크 그린-블랙(#0d1117) 배경에 에메랄드(#10b981) 트레이스. 각 Worker별 고유 색상(Preprocessing: 시안, RAG: 앰버, Report: 바이올렛).
**Layout Paradigm**: 풀스크린 인터랙티브 파이프라인 다이어그램이 히어로. 각 노드 클릭 시 상세 패널 오버레이.
**Signature Elements**: 애니메이션 데이터 흐름 라인, 펄스 효과 노드, 글로우 효과
**Interaction Philosophy**: 노드 호버 시 연결된 경로 하이라이트, 클릭 시 줌인 + 상세 정보
**Animation**: 데이터 패킷이 파이프라인을 따라 이동하는 연속 애니메이션, 노드 펄스
**Typography System**: Space Grotesk (제목) + Inter (본문) + Fira Code (코드)
</text>
<probability>0.03</probability>
</response>
