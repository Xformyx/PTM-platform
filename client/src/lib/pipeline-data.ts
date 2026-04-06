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
  { id: "report-temporal", label: "5.6 Temporal Co-movement (v8.0)", level: 2 },
  { id: "report-figures", label: "5.7 Figure 구성 (v8.0)", level: 2 },
  { id: "report-quality", label: "5.8 리포트 품질 개선 (v8.1)", level: 2 },
  { id: "report-classification", label: "5.9 PTM 분류 시스템 (v8.2)", level: 2 },
  { id: "report-effector", label: "5.10 Non-PTM Effector (v9.34+)", level: 2 },
  { id: "report-signalflow", label: "5.11 4-Layer Signal Flow (v9.34+)", level: 2 },
  { id: "dataflow", label: "6. 데이터 흐름 요약", level: 1 },
  { id: "infra", label: "7. 인프라 구성", level: 1 },
  { id: "operations", label: "8. 운영 가이드", level: 1 },
  { id: "ai-chat", label: "9. AI Analysis Chat", level: 1 },
  { id: "ai-chat-arch", label: "9.1 아키텍처", level: 2 },
  { id: "ai-chat-context", label: "9.2 컨텍스트 조립", level: 2 },
  { id: "ai-chat-usage", label: "9.3 사용 가이드", level: 2 },
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
  { id: 6, name: "network_analysis", range: "55% - 65%", file: "nodes/network_node.py", desc: "v9.34: PTM 데이터를 기반으로 단백질 상호작용 네트워크를 구축하고, Cytoscape Desktop의 CyREST API를 통해 시각화합니다. Figure 1 = Canonical Pathway Distribution Bar Graph (Activated + Inhibited PTM 모두 포함, 3-bar 구조로 편향 보정). Cascade diagram은 cascade_mediator가 생성. Kinase 소스 확장: KEA3 + kinase_prediction + kinase_substrate. Fallback kinase prediction 추가. PTM 노드는 Red/Blue 그라디언트, Non-PTM 노드는 Green/Purple 그라디언트(Protein_Log2FC 기반), Kinase 노드는 Amber 다이아몬드. v9.34: Non-PTM effector 노드를 timepoint별로 추출하여 state에 저장. 이 데이터는 global-kinase-modules API와 Signal Flow 다이어그램에서 4th layer로 활용됩니다.", state: "network_analysis, network_results, pathway_candidates, non_ptm_nodes" },
  { id: 7, name: "temporal_comovement", range: "65% - 70%", file: "nodes/temporal_comovement_node.py", desc: "v8.0 신규: Temporal PTM Co-movement Analysis. 전체 PTM의 시계열 Log2FC 데이터를 행렬화하고, Pearson 상관계수 기반 계층적 클러스터링(scipy.cluster.hierarchy)으로 동시 움직이는 PTM 그룹을 탐지합니다. 클러스터 패턴 분류(transient_burst, sustained_activation, biphasic_switch, sequential_wave 등), 생물학적 주석(pathway/kinase/GO term), Non-PTM interactor 연결, 그리고 Heatmap + Cluster Line Plot 시각화를 생성합니다. figure_context.py에 co-movement 컨텍스트를 주입하여 LLM이 시계열 클러스터링 결과를 해석할 수 있게 합니다. v9.36: Minor PTM 녹색 실선 시각화, 필터링 임계값 완화(MIN_AMPLITUDE 0.8, MIN_VARIANCE 0.3)로 패턴 있는 Minor PTM 포함.", state: "comovement_analysis, comovement_figures, comovement_llm_context" },
  { id: 8, name: "write_sections", range: "70% - 78%", file: "nodes/writer_node.py", desc: "v7.0: 검증된 가설, 네트워크 분석 결과, ChromaDB 문헌 컨텍스트를 종합하여 LLM이 리포트의 주요 섹션을 작성합니다. figure_context.py는 pathway_candidates를 informational context로만 제공하며, LLM이 자유롭게 맥락에 맞는 pathway를 선택하여 논의합니다. 더 이상 특정 pathway를 강제로 언급하도록 지시하지 않습니다.", state: "sections, collected_references" },
  { id: 9, name: "cascade_mediator", range: "78% - 82%", file: "nodes/cascade_mediator_node.py", desc: "v7.0 신규: Content-Driven Cascade Diagram 생성 에이전트. LLM이 작성한 Results/Discussion 텍스트에서 실제로 논의된 signaling pathway를 deterministic하게 추출합니다. 3단계 매칭: (1) 직접 pathway 이름 매칭, (2) Gene cluster 감지 (GENE_TO_PATHWAYS 매핑), (3) Alias 매칭 (ERK→MAPK, NF-κB→NF-kappa B 등). 추출된 pathway만으로 signaling_cascade.py의 렌더링 엔진을 호출하여 cascade diagram을 생성합니다. 이를 통해 본문 내용과 다이어그램이 자연스럽게 일치합니다.", state: "cascade_diagrams, cascade_pathway_names" },
  { id: 10, name: "generate_qa_report", range: "85% - 88%", file: "nodes/qa_report_node.py", desc: "2-Pass 접근법으로 Q&A 형식의 보조 리포트를 생성합니다.", state: "qa_report, qa_questions" },
  { id: 11, name: "drug_repositioning", range: "88% - 95%", file: "nodes/drug_repositioning_node.py", desc: "report_type이 extended인 경우에만 실행. PTM 분석 결과를 기반으로 약물 재배치 후보를 탐색합니다.", state: "drug_repositioning_results" },
  { id: 12, name: "format_citations", range: "95% - 97%", file: "core/citation_formatter.py", desc: "모든 섹션을 조합하고, 인라인 인용을 정규화하며, Vancouver 스타일의 참고문헌 목록을 생성합니다.", state: "final_report, citation_data" },
  { id: 13, name: "edit_report", range: "97% - 100%", file: "nodes/editor_node.py", desc: "최종 리포트를 저장하고, PTM 용어 교정, 인용 삽입, 가짜 참고문헌 제거 등의 후처리를 수행합니다.", state: "final output files" },
];

export const REPORT_FIGURES_V934 = [
  { figure: "Figure 1", type: "Bar Graph", node: "network_analysis", desc: "Canonical Pathway Distribution (Activated + Inhibited PTM, 3-bar 구조)" },
  { figure: "Figure 2+", type: "Cascade Diagram", node: "cascade_mediator", desc: "Content-Driven Signaling Cascade — LLM 본문에서 추출된 pathway 기반" },
  { figure: "Figure N", type: "Heatmap", node: "temporal_comovement", desc: "PTM Co-movement Heatmap — 클러스터별 시계열 Log2FC" },
  { figure: "Figure N+1", type: "Line Plot", node: "temporal_comovement", desc: "Cluster Line Plot — 클러스터 평균 시계열 프로파일" },
  { figure: "Figure N+2", type: "4-Layer Signal Flow", node: "kinase_annotation (signal_flow_figure)", desc: "v9.34: Receptor → Kinase → Substrate → Non-PTM Effector 4-layer 다이어그램 (time-lag 시각화 포함)" },
  { figure: "Figure N+3...", type: "Network Image", node: "network_analysis", desc: "Cytoscape 네트워크 시각화 (Timepoint별)" },
];

export const REPORT_SECTIONS = [
  { section: "Abstract", tokens: "6,144", content: "연구 요약, 주요 발견, 결론" },
  { section: "Introduction", tokens: "12,288", content: "실험 배경, 연구 목적, 관련 문헌" },
  { section: "Results", tokens: "16,384", content: "PTM 분석 결과, 통계, 경로 분석" },
  { section: "Discussion", tokens: "12,288", content: "결과 해석, 기존 연구와의 비교" },
  { section: "Conclusion", tokens: "8,192", content: "핵심 발견 요약, 향후 연구 방향" },
];

export const SIGNAL_FLOW_LAYERS = [
  { layer: 1, name: "Receptor", color: "#06b6d4", shape: "Hexagon", source: "Inferred from kinase-receptor mapping (KEGG, literature)", desc: "Upstream receptor tyrosine kinases or GPCRs that initiate signaling" },
  { layer: 2, name: "Kinase / E3 Ligase", color: "#f59e0b", shape: "Diamond", source: "iPTMnet, UniProt, KEA3, motif prediction, RAG", desc: "Regulatory enzymes annotated from 8 sources" },
  { layer: 3, name: "PTM Substrate", color: "#ef4444 / #3b82f6", shape: "Circle", source: "Experimental PTM data (PTM_Relative_Log2FC)", desc: "Phosphorylation/Ubiquitylation sites with temporal profiles" },
  { layer: 4, name: "Non-PTM Effector", color: "#10b981 / #0ea5e9", shape: "Circle", source: "PPI (STRING/BioGRID) + Expression-only (TSV Protein_Only)", desc: "Two types: PPI-based (green/red border) connected via network edges, and expression_only (sky-blue dotted border) with |Protein_Log2FC| > 0.3 from TSV" },
];

export const EFFECTOR_EXTRACTION_STEPS = [
  { step: "1a", action: "PPI-based: Network edge 추출", detail: "network_analysis state에서 timepoint별 non_ptm_nodes 추출 (STRING/BioGRID confidence score 기반)" },
  { step: "1b", action: "Expression-only: TSV Protein_Only 추출", detail: "unified_protein_data TSV에서 Data_Type='Protein_Only'이고 |Protein_Log2FC| > 0.3인 단백질 전체 추출" },
  { step: 2, action: "Substrate 연결 매핑", detail: "PPI-based 노드의 edge를 추적하여 연결된 PTM substrate 식별 (expression_only는 substrate 연결 없음)" },
  { step: 3, action: "Temporal profile 구성", detail: "unified_protein_data에서 각 condition별 Protein_Log2FC 추출" },
  { step: 4, action: "Peak FC 계산", detail: "|Protein_Log2FC|가 최대인 condition을 peak으로 설정" },
  { step: 5, action: "Evidence strength 분류", detail: "PPI-based: strong (≥700) / moderate (400-699) / weak (<400). Expression-only: expression_only" },
  { step: 6, action: "Time-lag 분석", detail: "Substrate PTM_Relative_Log2FC peak 시점 대비 Effector Protein_Log2FC peak 시점의 시간차 계산" },
  { step: 7, action: "Signal Flow 다이어그램", detail: "4-layer 다이어그램 생성 — PPI-based(실선 border) vs expression_only(점선 sky-blue border) 시각 구분" },
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
