# Network v5.0 수정 계획

## 문제 1: Non-PTM 노드가 모두 회색
**원인**: `_classify_state(0, "Non-PTM")` — value가 항상 0으로 하드코딩
**해결**: Non-PTM 노드 생성 시 enriched_data에서 해당 gene의 Protein_Log2FC를 조회하여 전달
- STRING Non-PTM: partner gene의 Protein_Log2FC를 parsed_ptms에서 조회
- BioGRID Non-PTM: 동일
- KEA3 Kinase: 동일
- 문제: Non-PTM partner는 parsed_ptms에 없을 수 있음 → enriched_data 전체에서 gene 매칭 필요
- 실제로 Non-PTM protein의 Protein_Log2FC는 enriched_data에 없을 수 있음 (PTM이 아닌 단백질이므로)
- 대안: parsed_ptms에서 같은 gene의 protein_log2fc를 사용 (PTM site가 다르더라도 같은 단백질)
- 최종 대안: gene_protein_fc 딕셔너리를 미리 구축 (gene -> Protein_Log2FC)

## 문제 2: PTM 색상 체계 변경
**요구사항**: 증가=빨강, 감소=파랑 (현재: 모두 빨강 gradient)
**해결**: NODE_COLORS의 PTM 상태에서 down 계열을 파랑으로 변경
- high_active: 진한 빨강 (유지)
- moderate_active: 빨강 (유지)  
- inhibited: 진한 파랑으로 변경
- low_inhibited: 파랑으로 변경
- neutral: 회색 (유지)

## 문제 3: Kinase 노드 수가 너무 적음
**원인**: upstream_regulators가 enrichment에서 KEA3를 통해서만 가져옴
**해결 방안**:
- PhosphoSitePlus 데이터 활용
- UniProt keyword "kinase" 기반 분류
- STRING-DB에서 kinase 활성 annotation 확인
- enriched_data의 다른 필드에서 kinase 정보 추출
