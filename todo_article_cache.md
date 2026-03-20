# Article Cache 개선 계획

## 백엔드 변경

### 1. MCP Server: article 캐시 시 메타데이터 추가
- `search_ptm_pubmed()` 에서 article 캐시할 때 `search_gene`, `search_position`, `cached_at` 타임스탬프 추가
- 현재: article dict에 search_gene이 없음 → list_cached_articles에서 search_gene 검색이 안됨

### 2. API Server: Order별 사용된 article 조회 엔드포인트 추가
- `GET /api/orders/{order_code}/articles` → enriched_ptm_data JSON에서 articles 추출
- 각 PTM별로 어떤 gene/position 검색으로 가져왔는지 포함

### 3. MCP Server: list_cached_articles에 정렬/필터 개선
- cached_at 기준 정렬 옵션 추가 (newest first)
- "new" 표시를 위한 cached_at 필드 활용

## 프론트엔드 변경

### 1. Articles.tsx 개선
- [x] 검색 기능 (이미 구현됨)
- [ ] "NEW" 배지 표시 (cached_at 기준 24시간 이내)
- [ ] Gene/Position 컬럼에 검색 keyword 표시
- [ ] Order 연결 정보 표시 (어떤 Order에서 추가되었는지)

### 2. Order 상세 페이지에 사용된 Article 탭/섹션 추가
- Order 분석 완료 후 enriched_ptm_data에서 article 목록 추출하여 표시
