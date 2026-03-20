// Pipeline Manual Data — "Specimen" Design System
// Design: Academic journal style, Crimson Pro headings, Source Sans 3 body, Fira Code mono

export const HERO_BG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/hero_bg-E8AFtvgLQ8pdZY9Td8cwPM.webp";
export const PREPROCESSING_IMG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/preprocessing_illust-D6EtmNN7WX9iSsEBYrwdi7.webp";
export const RAG_IMG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/rag_illust-QNV75Jp3A2HE5YUdBB27GF.webp";
export const REPORT_IMG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/report_illust-i2BAUTzKRomTgiFhGnEhdu.webp";
export const FLOWCHART_IMG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/pipeline_flowchart_ba425145.png";

export interface TocItem {
  id: string;
  label: string;
  level: number;
}

export const TOC_ITEMS: TocItem[] = [
  { id: "overview", label: "1. 개요", level: 1 },
  { id: "flowchart", label: "2. 파이프라인 흐름도", level: 1 },
  { id: "preprocessing", label: "3. Preprocessing Worker", level: 1 },
  { id: "preprocessing-goal", label: "3.1 목표", level: 2 },
  { id: "preprocessing-input", label: "3.3 입력 데이터", level: 2 },
  { id: "preprocessing-process", label: "3.4 내부 프로세스", level: 2 },
  { id: "preprocessing-handoff", label: "3.5 다음 단계 전달", level: 2 },
  { id: "rag", label: "4. RAG Enrichment Worker", level: 1 },
  { id: "rag-goal", label: "4.1 목표", level: 2 },
  { id: "rag-process", label: "4.4 내부 프로세스", level: 2 },
  { id: "rag-8cat", label: "8-Category 분류", level: 2 },
  { id: "rag-handoff", label: "4.5 다음 단계 전달", level: 2 },
  { id: "report", label: "5. Report Generation Worker", level: 1 },
  { id: "report-goal", label: "5.1 목표", level: 2 },
  { id: "report-graph", label: "5.4 LangGraph 구조", level: 2 },
  { id: "report-nodes", label: "5.5 노드별 상세", level: 2 },
  { id: "report-figures", label: "5.6 Figure 구성 (v6.0)", level: 2 },
  { id: "dataflow", label: "6. 데이터 흐름 요약", level: 1 },
  { id: "infra", label: "7. 인프라 구성", level: 1 },
  { id: "operations", label: "8. 운영 가이드", level: 1 },
];

export interface WorkerOverview {
  name: string;
  role: string;
  queue: string;
  color: string;
  icon: string;
}

export const WORKERS: WorkerOverview[] = [
  {
    name: "Preprocessing Worker",
    role: "Raw 데이터 정량화 및 생물학적 주석(Annotation) 추가",
    queue: "preprocessing",
    color: "teal",
    icon: "beaker",
  },
  {
    name: "RAG Enrichment Worker",
    role: "문헌 검색(RAG)을 통한 심층 생물학적 컨텍스트 부여",
    queue: "rag_enrichment",
    color: "amber",
    icon: "book-open",
  },
  {
    name: "Report Generation Worker",
    role: "LLM 기반 최종 종합 분석 리포트 생성",
    queue: "report_generation",
    color: "violet",
    icon: "file-text",
  },
];

export const PREPROCESSING_INPUT_PARAMS = [
  { param: "pr_matrix_path", desc: "Peptide Report Matrix 파일 경로 (TSV)", required: true },
  { param: "pg_matrix_path", desc: "Protein Group Matrix 파일 경로 (TSV)", required: true },
  { param: "fasta_path", desc: "UniProt FASTA 파일 경로", required: true },
  { param: "config_xlsx_path", desc: "샘플-조건 매핑 설정 파일 (Excel)", required: false },
  { param: "ptm_mode", desc: 'PTM 분석 모드: phospho 또는 ubi', required: true },
  { param: "condition_map", desc: "파일명-조건 매핑 딕셔너리", required: false },
  { param: "species_tax_id", desc: "NCBI Taxonomy ID (기본값: 10090, Mouse)", required: false },
  { param: "kegg_organism", desc: "KEGG 생물종 코드 (기본값: mmu)", required: false },
  { param: "analysis_options", desc: "Downsampling 모드 및 설정", required: false },
];

export const RAG_PIPELINE_STEPS = [
  { step: 1, name: "PubMed 문헌 검색", source: "PubMed (MCP)", method: "Multi-tier 검색" },
  { step: 2, name: "조절 관계 추출", source: "PubMed 초록", method: "패턴 매칭" },
  { step: 3, name: "KEGG 경로 조회", source: "KEGG (MCP)", method: "API" },
  { step: 4, name: "STRING-DB 상호작용", source: "STRING-DB (MCP)", method: "API" },
  { step: 5, name: "UniProt 단백질 정보", source: "UniProt (MCP)", method: "API" },
  { step: 6, name: "HPA 조직 발현", source: "HPA (Local/MCP)", method: "Local-first" },
  { step: 7, name: "GTEx 조직 발현", source: "GTEx (Local/MCP)", method: "Local-first" },
  { step: 8, name: "BioGRID 상호작용", source: "BioGRID (MCP)", method: "API" },
  { step: 9, name: "LLM 초록 분석", source: "PubMed 초록", method: "LLM" },
  { step: 10, name: "LLM Kinase 예측", source: "문헌 + 컨텍스트", method: "LLM" },
  { step: 11, name: "LLM 기능적 영향 분석", source: "문헌 + 경로", method: "LLM" },
  { step: 12, name: "PMC 전문(Full-text) 분석", source: "PMC (MCP)", method: "패턴 매칭" },
  { step: 13, name: "PTM 검증/신규성 평가", source: "iPTMnet (MCP)", method: "API" },
  { step: 14, name: "조절 관계 병합", source: "KEGG + PubMed", method: "통합" },
  { step: 15, name: "8-Category 분류", source: "PTM/Protein Log2FC", method: "규칙 기반" },
  { step: 16, name: "시계열 궤적 추출", source: "다중 조건 데이터", method: "계산" },
  { step: 17, name: "Isoform 정보 추출", source: "UniProt", method: "파싱" },
  { step: 18, name: "Enrichment 결과 조립", source: "전체", method: "통합" },
];

export const EIGHT_CATEGORIES = [
  { category: "PTM-driven hyperactivation", ptm: "강한 상승", protein: "안정", meaning: "PTM에 의한 과활성화", color: "#059669" },
  { category: "PTM-driven inactivation", ptm: "강한 하강", protein: "안정", meaning: "PTM에 의한 비활성화", color: "#dc2626" },
  { category: "Compensatory PTM hyperactivation", ptm: "강한 상승", protein: "하강", meaning: "보상적 PTM 과활성화", color: "#0891b2" },
  { category: "Synergistic activation", ptm: "상승", protein: "상승", meaning: "시너지 활성화", color: "#16a34a" },
  { category: "Synergistic suppression", ptm: "하강", protein: "하강", meaning: "시너지 억제", color: "#9333ea" },
  { category: "Protein-driven (PTM passive)", ptm: "약함", protein: "변화", meaning: "단백질 주도 변화", color: "#ca8a04" },
  { category: "Discordant regulation", ptm: "상승", protein: "하강 (또는 반대)", meaning: "불일치 조절", color: "#ea580c" },
  { category: "Baseline / low-change state", ptm: "약함", protein: "안정", meaning: "기저 상태", color: "#6b7280" },
];

export const LANGGRAPH_NODES = [
  { id: 1, name: "load_context", range: "2% - 5%", file: "nodes/context_loader.py", desc: "Stage 2의 출력물인 enriched_ptm_data.json과 comprehensive_report.md를 로드하고, PTM 데이터를 구조화된 형식으로 파싱합니다.", state: "parsed_ptms, comprehensive_summary, research_questions" },
  { id: 2, name: "generate_questions", range: "5% - 10%", file: "nodes/question_generator.py", desc: "LLM을 사용하여 PTM 데이터와 종합 리포트 내용을 분석하고, 7가지 카테고리에 걸친 연구 질문을 자동 생성합니다.", state: "research_questions, ai_questions_metadata" },
  { id: 3, name: "research", range: "10% - 30%", file: "nodes/research_node.py", desc: "각 연구 질문에 대해 관련 PTM 데이터를 필터링하고, 활성화/억제된 PTM 패턴, 경로 농축, 조절 패턴을 분석합니다.", state: "research_results" },
  { id: 4, name: "hypothesize", range: "30% - 40%", file: "nodes/hypothesis_node.py", desc: "연구 분석 결과를 바탕으로 IF-THEN-BECAUSE 형식의 구조화된 가설을 생성합니다.", state: "hypotheses" },
  { id: 5, name: "validate_hypotheses", range: "40% - 55%", file: "nodes/validation_node.py", desc: "생성된 각 가설을 ChromaDB 벡터 데이터베이스의 문헌 데이터를 통해 검증하고 신뢰도 점수를 부여합니다.", state: "validated_hypotheses" },
  { id: 6, name: "network_analysis", range: "55% - 65%", file: "nodes/network_node.py", desc: "PTM 데이터를 기반으로 단백질 상호작용 네트워크를 구축하고, Cytoscape Desktop의 CyREST API를 통해 시각화합니다. v6.0: Figure 1 = Canonical Pathway Distribution Bar Graph (|Log2FC| 가중치), Figure 2 = Compartmentalized Signaling Cascade Diagram (세포 구획별 신호 전달 경로, signaling_cascade.py), Figure 3+ = Cytoscape 네트워크 이미지. PTM 노드는 Red/Blue 그라디언트, Non-PTM 노드는 Green/Purple 그라디언트(Protein_Log2FC 기반), Kinase 노드는 Amber 다이아몬드로 색상 매핑.", state: "network_analysis, network_results" },
  { id: 7, name: "write_sections", range: "70% - 85%", file: "nodes/writer_node.py", desc: "검증된 가설, 네트워크 분석 결과, ChromaDB 문헌 컨텍스트를 종합하여 LLM이 리포트의 주요 섹션을 작성합니다.", state: "sections, collected_references" },
  { id: 8, name: "generate_qa_report", range: "85% - 88%", file: "nodes/qa_report_node.py", desc: "2-Pass 접근법으로 Q&A 형식의 보조 리포트를 생성합니다.", state: "qa_report, qa_questions" },
  { id: 9, name: "drug_repositioning", range: "88% - 95%", file: "nodes/drug_repositioning_node.py", desc: "report_type이 extended인 경우에만 실행. PTM 분석 결과를 기반으로 약물 재배치 후보를 탐색합니다.", state: "drug_repositioning_results" },
  { id: 10, name: "format_citations", range: "95% - 97%", file: "core/citation_formatter.py", desc: "모든 섹션을 조합하고, 인라인 인용을 정규화하며, Vancouver 스타일의 참고문헌 목록을 생성합니다.", state: "final_report, citation_data" },
  { id: 11, name: "edit_report", range: "97% - 100%", file: "nodes/editor_node.py", desc: "최종 리포트를 저장하고, PTM 용어 교정, 인용 삽입, 가짜 참고문헌 제거 등의 후처리를 수행합니다.", state: "final output files" },
];

export const REPORT_SECTIONS = [
  { section: "Abstract", tokens: "6,144", content: "연구 요약, 주요 발견, 결론" },
  { section: "Introduction", tokens: "12,288", content: "실험 배경, 연구 목적, 관련 문헌" },
  { section: "Results", tokens: "16,384", content: "PTM 분석 결과, 통계, 경로 분석" },
  { section: "Discussion", tokens: "12,288", content: "결과 해석, 기존 연구와의 비교" },
  { section: "Conclusion", tokens: "8,192", content: "핵심 발견 요약, 향후 연구 방향" },
];

export const DOCKER_SERVICES = [
  { service: "mysql", container: "ptm-mysql", role: "관계형 데이터베이스 (Order, Log 저장)" },
  { service: "redis", container: "ptm-redis", role: "메시지 브로커, 캐시, Pub/Sub" },
  { service: "chromadb", container: "ptm-chromadb", role: "벡터 데이터베이스 (문헌 임베딩)" },
  { service: "api-server", container: "ptm-api-server", role: "FastAPI REST API 서버" },
  { service: "mcp-server", container: "ptm-mcp-server", role: "외부 API 중계 서버" },
  { service: "celery-worker-preprocessing", container: "ptm-worker-preprocessing", role: "Preprocessing Worker" },
  { service: "celery-worker-rag", container: "ptm-worker-rag", role: "RAG Enrichment Worker" },
  { service: "celery-worker-report", container: "ptm-worker-report", role: "Report Generation Worker" },
  { service: "frontend", container: "ptm-frontend", role: "React 프론트엔드" },
  { service: "gateway", container: "ptm-gateway", role: "Nginx 리버스 프록시" },
];

export const SHARED_INFRA = [
  { service: "Redis", usage: "Celery 브로커, 진행률 SSE Pub/Sub, MCP 캐시", workers: "전체" },
  { service: "MySQL", usage: "Order 상태, 진행률, 로그 저장", workers: "전체" },
  { service: "ChromaDB", usage: "문헌 벡터 DB (가설 검증, 섹션 작성용 RAG)", workers: "RAG, Report" },
  { service: "MCP-Server", usage: "외부 API 중계 (PubMed, UniProt, KEGG 등)", workers: "Preprocessing, RAG" },
  { service: "Ollama / LLM", usage: "텍스트 생성 (초록 분석, 가설, 섹션 작성)", workers: "RAG, Report" },
  { service: "Cytoscape Desktop", usage: "네트워크 시각화 (호스트 머신에서 실행)", workers: "Report" },
];
