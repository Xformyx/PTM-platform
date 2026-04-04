// Home.tsx — PTM Platform Pipeline Manual
// Design: "Specimen" — Academic journal style
// Typography: Crimson Pro (headings), Source Sans 3 (body), Fira Code (code)
// Colors: warm white bg, charcoal text, green primary, amber accent, violet for report

import ReadingProgress from "@/components/ReadingProgress";
import TableOfContents from "@/components/TableOfContents";
import MobileNav from "@/components/MobileNav";
import SectionHeading from "@/components/SectionHeading";
import DataTable from "@/components/DataTable";
import CodeBlock from "@/components/CodeBlock";
import Callout from "@/components/Callout";
import StepCard from "@/components/StepCard";
import NodeCard from "@/components/NodeCard";
import {
  HERO_BG,
  PREPROCESSING_IMG,
  RAG_IMG,
  REPORT_IMG,
  FLOWCHART_IMG,
  WORKERS,
  PREPROCESSING_INPUT_PARAMS,
  RAG_PIPELINE_STEPS,
  EIGHT_CATEGORIES,
  LANGGRAPH_NODES,
  REPORT_SECTIONS,
  REPORT_FIGURES_V934,
  SIGNAL_FLOW_LAYERS,
  EFFECTOR_EXTRACTION_STEPS,
  DOCKER_SERVICES,
  SHARED_INFRA,
} from "@/lib/pipeline-data";
import { Beaker, BookOpen, FileText, ArrowRight, Database, Server, Globe, Layers, Zap } from "lucide-react";

const workerIcons = {
  beaker: Beaker,
  "book-open": BookOpen,
  "file-text": FileText,
};

const workerColors = {
  teal: { bg: "bg-teal-50", border: "border-teal-200", text: "text-teal-700", dot: "bg-teal-500" },
  amber: { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", dot: "bg-amber-500" },
  violet: { bg: "bg-violet-50", border: "border-violet-200", text: "text-violet-700", dot: "bg-violet-500" },
};

export default function Home() {
  return (
    <div className="min-h-screen bg-background">
      <ReadingProgress />
      <MobileNav />

      {/* Header */}
      <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-md border-b border-border">
        <div className="container flex items-center h-14 gap-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-primary flex items-center justify-center">
              <span className="text-primary-foreground text-xs font-bold font-mono">P</span>
            </div>
            <span className="font-serif font-bold text-lg text-foreground hidden sm:block">
              PTM Platform
            </span>
          </div>
          <span className="text-xs text-muted-foreground font-mono hidden sm:block">
            Pipeline Manual v1.7
          </span>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs text-muted-foreground">2026-04-05</span>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-border">
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage: `url(${HERO_BG})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="relative container py-16 sm:py-24">
          <p className="text-sm font-mono text-primary mb-3 tracking-wider uppercase">
            Technical Documentation
          </p>
          <h1 className="font-serif text-4xl sm:text-5xl lg:text-6xl font-bold text-foreground leading-tight max-w-3xl">
            Worker Pipeline Manual
          </h1>
          <p className="mt-5 text-lg text-muted-foreground max-w-2xl leading-relaxed">
            Preprocessing, RAG Enrichment, Report Generation 세 Worker의 구조, 기능, 데이터 흐름을 상세히 설명합니다.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            {WORKERS.map((w) => {
              const c = workerColors[w.color as keyof typeof workerColors];
              return (
                <span
                  key={w.name}
                  className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border ${c.bg} ${c.border} ${c.text}`}
                >
                  <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                  {w.name}
                </span>
              );
            })}
          </div>
        </div>
      </section>

      {/* Main layout: sidebar + content */}
      <div className="container flex gap-8 py-8">
        {/* Sidebar TOC (desktop) */}
        <aside className="hidden lg:block w-56 shrink-0">
          <TableOfContents />
        </aside>

        {/* Content */}
        <main className="flex-1 min-w-0 max-w-4xl">

          {/* 1. Overview */}
          <SectionHeading id="overview" level={1}>1. 개요</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            PTM Platform은 대규모 Proteomics 실험 데이터로부터 번역 후 변형(Post-Translational Modification, PTM) 패턴을 분석하고,
            최신 연구 문헌과 결합하여 종합적인 과학 리포트를 자동 생성하는 시스템입니다. 전체 분석 파이프라인은 세 개의 독립적인
            <strong> Celery Worker</strong>로 구성되어 있으며, 각 Worker는 고유한 역할을 수행하면서 순차적으로 연결됩니다.
          </p>

          <DataTable
            caption="Table 1. Worker 개요 및 Celery Queue 매핑"
            headers={["Worker", "역할", "Celery Queue"]}
            rows={WORKERS.map((w) => {
              const c = workerColors[w.color as keyof typeof workerColors];
              return [
                <span className="flex items-center gap-2 font-medium">
                  <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                  {w.name}
                </span>,
                w.role,
                <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{w.queue}</code>,
              ];
            })}
          />

          <p className="text-base leading-relaxed text-foreground/85">
            세 Worker는 <strong>Celery Task Queue</strong>와 <strong>Redis</strong> 메시지 브로커를 통해 비동기적으로 연결됩니다.
            한 단계가 완료되면 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">app.send_task()</code>를 호출하여
            다음 Worker의 Queue에 새로운 Task를 자동으로 생성하고, 이전 단계의 출력 파일 경로와 설정 정보를 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">config</code> 딕셔너리로 전달합니다.
          </p>

          {/* 2. Flowchart */}
          <SectionHeading id="flowchart" level={1}>2. 파이프라인 흐름도</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            아래 다이어그램은 PTM Platform의 전체 데이터 처리 흐름을 시각적으로 보여줍니다.
            분홍색 노드는 각 단계의 진입점을, 녹색 노드는 최종 산출물을 나타냅니다.
          </p>
          <figure className="my-6">
            <div className="border border-border rounded-lg overflow-hidden bg-white p-4 shadow-sm">
              <img
                src={FLOWCHART_IMG}
                alt="PTM Platform Pipeline Flowchart"
                className="w-full max-w-2xl mx-auto"
                loading="lazy"
              />
            </div>
            <figcaption className="mt-2 text-center text-xs text-muted-foreground italic">
              Figure 1. PTM Platform 전체 파이프라인 흐름도
            </figcaption>
          </figure>

          {/* 3. Preprocessing Worker */}
          <SectionHeading id="preprocessing" level={1}>3. Stage 1: Preprocessing Worker</SectionHeading>
          <figure className="my-6">
            <div className="rounded-lg overflow-hidden border border-border shadow-sm">
              <img
                src={PREPROCESSING_IMG}
                alt="Preprocessing Worker Illustration"
                className="w-full"
                loading="lazy"
              />
            </div>
            <figcaption className="mt-2 text-center text-xs text-muted-foreground italic">
              Figure 2. Preprocessing Worker 개념도 — Raw 데이터에서 정규화된 PTM 데이터셋으로의 변환
            </figcaption>
          </figure>

          <SectionHeading id="preprocessing-goal" level={2}>3.1. 목표</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            사용자가 업로드한 Raw Proteomics 데이터(PR Matrix, PG Matrix, FASTA)를 분석 가능한 <strong>정규화된 PTM 데이터셋</strong>으로 변환합니다.
            이 단계에서 PTM 사이트별 상대적 정량 값(Log2 Fold Change)을 계산하고, 단백질 도메인, 모티프, 생물학적 경로 등의 기본 주석을 추가합니다.
          </p>
          <p className="text-sm text-muted-foreground mb-6">
            <strong>진입점:</strong> <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">workers/preprocessing/tasks.py</code>의{" "}
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">run_preprocessing(order_id, config)</code>
          </p>

          <SectionHeading id="preprocessing-input" level={2}>3.3. 입력 데이터</SectionHeading>
          <DataTable
            caption="Table 2. Preprocessing Worker 입력 파라미터"
            headers={["파라미터", "설명", "필수"]}
            rows={PREPROCESSING_INPUT_PARAMS.map((p) => [
              <code className="text-xs font-mono">{p.param}</code>,
              p.desc,
              p.required ? <span className="text-primary font-bold">O</span> : <span className="text-muted-foreground">X</span>,
            ])}
          />

          <SectionHeading id="preprocessing-process" level={2}>3.4. 내부 프로세스</SectionHeading>
          <p className="text-sm text-muted-foreground mb-4">
            Preprocessing Worker는 4개의 순차적 Step으로 구성되며, 각 Step의 출력 파일이 이미 존재하면 해당 Step을 건너뜁니다(Idempotent 설계).
          </p>

          <div className="ml-2">
            <StepCard step="Step 1" title="PTM Quantification" progress="0% - 50%" file="core/ptm_quantification.py" color="teal">
              FASTA 파일에서 단백질 서열 정보를 로드한 후, PR/PG Matrix에 Median Normalization을 적용합니다.
              이후 PTM 사이트별 상대적 정량 값(PTM Relative Log2FC)과 단백질 수준의 변화(Protein Log2FC)를 계산하고,
              조건(Condition) 간 비교 분석을 수행합니다.
              <Callout type="output">
                <code className="text-xs font-mono">ptm_vector_data_normalized_&#123;phospho|ubi&#125;.tsv</code>,{" "}
                <code className="text-xs font-mono">all_protein_level_changes_normalized_&#123;phospho|ubi&#125;.tsv</code>
              </Callout>
            </StepCard>

            <StepCard step="Step 1b" title="PTM Vector Report" progress="52% - 55%" file="core/ptm_vector_report_generator.py" color="teal">
              PTM Vector 데이터를 기반으로 2D Scatter Plot(PTM Log2FC vs Protein Log2FC)을 생성합니다.
              PTM 변화가 단백질 발현 변화와 독립적인지(PTM-driven) 또는 연동되는지(Protein-driven)를 직관적으로 보여줍니다.
              <Callout type="output">
                <code className="text-xs font-mono">ptm_vector_report_*.png</code>,{" "}
                <code className="text-xs font-mono">ptm_vector_summary_report*.png</code>
              </Callout>
            </StepCard>

            <StepCard step="Step 2" title="Unified Enrichment" progress="50% - 70%" file="core/unified_enricher.py" color="teal">
              MCP-Server를 통해 InterPro 데이터베이스에서 단백질 도메인 정보를 조회하고,
              15종 이상의 Kinase 인식 모티프 패턴(PKA, PKC, CK2, CDK, MAPK 등)을 서열 기반으로 매칭합니다.
              <Callout type="output">
                <code className="text-xs font-mono">unified_protein_data_enriched_&#123;phospho|ubi&#125;.tsv</code>
              </Callout>
            </StepCard>

            <StepCard step="Step 3" title="Biological Enrichment" progress="70% - 90%" file="core/biological_enricher.py" color="teal">
              MCP-Server를 통해 UniProt, STRING-DB, KEGG 등 주요 생물학적 데이터베이스의 정보를 통합합니다.
              <DataTable
                compact
                headers={["데이터베이스", "추가되는 정보"]}
                rows={[
                  [<strong>UniProt</strong>, "세포 내 위치, 단백질 기능 요약, GO Terms (BP, MF, CC)"],
                  [<strong>STRING-DB</strong>, "단백질-단백질 상호작용 파트너 및 상호작용 점수"],
                  [<strong>KEGG</strong>, "관련 대사/신호전달 경로(Pathway) 목록"],
                ]}
              />
              <Callout type="output">
                <code className="text-xs font-mono">unified_protein_data_enriched_bio_enriched_&#123;phospho|ubi&#125;.tsv</code>
              </Callout>
            </StepCard>

            <StepCard step="Step 4" title="Finalization" progress="90% - 100%" file="tasks.py" color="teal">
              모든 출력 파일 목록을 정리하고 처리 시간을 기록합니다.
              <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">chain_to_next</code> 설정이 True(기본값)이면
              다음 단계인 RAG Enrichment Worker로 자동 전환됩니다.
            </StepCard>
          </div>

          <SectionHeading id="preprocessing-handoff" level={2}>3.5. 다음 단계로의 전달</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-3">
            Preprocessing이 완료되면 RAG Enrichment Worker에 다음 정보를 전달합니다:
          </p>
          <CodeBlock
            title="rag_config 전달 데이터"
            language="python"
            code={`rag_config = {
    "order_code": order_code,
    "preprocessing_output_dir": str(order_output),   # Stage 1 출력 디렉토리
    "ptm_mode": ptm_mode,                            # phospho | ubi
    "experimental_context": {...},                    # 실험 조건 정보
    "top_n_ptms": 50,                                # 상위 N개 PTM 선별 수
    "chromadb_collections": [...],                    # ChromaDB 컬렉션 목록
    "llm_provider": "ollama",                        # LLM 제공자
    "llm_model": "gemma3:27b",                       # LLM 모델명
    "report_title": "PTM Comprehensive Analysis Report",
}`}
          />

          {/* 4. RAG Enrichment Worker */}
          <SectionHeading id="rag" level={1}>4. Stage 2: RAG Enrichment Worker</SectionHeading>
          <figure className="my-6">
            <div className="rounded-lg overflow-hidden border border-border shadow-sm">
              <img
                src={RAG_IMG}
                alt="RAG Enrichment Worker Illustration"
                className="w-full"
                loading="lazy"
              />
            </div>
            <figcaption className="mt-2 text-center text-xs text-muted-foreground italic">
              Figure 3. RAG Enrichment Worker 개념도 — 문헌 검색과 AI 분석을 통한 데이터 보강
            </figcaption>
          </figure>

          <SectionHeading id="rag-goal" level={2}>4.1. 목표</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-6">
            Preprocessing 단계에서 생성된 정량 데이터에 <strong>최신 연구 문헌 정보</strong>를 결합하여 각 PTM 사이트의 생물학적 컨텍스트를 극대화합니다.
            PubMed 문헌 검색, LLM 기반 초록 분석, 다중 데이터베이스 통합을 통해 풍부한 메타데이터를 생성하고,
            이를 바탕으로 1차 종합 리포트(Markdown)를 작성합니다.
          </p>

          <SectionHeading id="rag-process" level={2}>4.4. 내부 프로세스</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            <strong>Step 1 (0%-10%):</strong> Preprocessing의 출력물인 TSV 파일을 로드하고, |PTM_Relative_Log2FC| 기준으로 상위 N개의 고유 PTM 사이트를 선별합니다.
          </p>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            <strong>Step 2 (10%-70%):</strong> <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">RAGEnrichmentPipeline</code>이
            선별된 각 PTM 사이트에 대해 아래의 18단계 분석을 수행합니다.
          </p>

          <DataTable
            caption="Table 3. RAG Enrichment Pipeline 18단계 분석"
            headers={["#", "분석 항목", "데이터 소스", "방식"]}
            compact
            rows={RAG_PIPELINE_STEPS.map((s) => [
              <span className="font-mono text-xs">{s.step}</span>,
              s.name,
              <span className="text-xs">{s.source}</span>,
              <span className={`text-xs px-1.5 py-0.5 rounded ${
                s.method === "LLM" ? "bg-violet-50 text-violet-700" :
                s.method === "API" ? "bg-sky-50 text-sky-700" :
                s.method === "통합" ? "bg-amber-50 text-amber-700" :
                "bg-muted text-muted-foreground"
              }`}>{s.method}</span>,
            ])}
          />

          <SectionHeading id="rag-8cat" level={2}>8-Category Cell-Signaling 분류 시스템</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            PTM Log2FC와 Protein Log2FC의 조합을 기반으로 각 PTM 사이트의 생물학적 의미를 자동으로 분류합니다.
          </p>
          <DataTable
            caption="Table 4. 8-Category Cell-Signaling 분류 체계"
            headers={["분류", "PTM 변화", "단백질 변화", "의미"]}
            rows={EIGHT_CATEGORIES.map((cat) => [
              <span className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: cat.color }} />
                <span className="text-xs font-medium">{cat.category}</span>
              </span>,
              <span className="text-center text-xs">{cat.ptm}</span>,
              <span className="text-center text-xs">{cat.protein}</span>,
              <span className="text-xs">{cat.meaning}</span>,
            ])}
          />

          <p className="text-base leading-relaxed text-foreground/85 mt-4 mb-3">
            <strong>Step 3 (70%-95%):</strong> Enrich된 모든 PTM 데이터를 종합하여 포괄적인 Markdown 형식의 1차 종합 리포트를 생성합니다.
          </p>
          <Callout type="output">
            <code className="text-xs font-mono">enriched_ptm_data_&#123;ptm_mode&#125;.json</code>,{" "}
            <code className="text-xs font-mono">comprehensive_report_&#123;ptm_mode&#125;.md</code>
          </Callout>

          <SectionHeading id="rag-handoff" level={2}>4.5. 다음 단계로의 전달</SectionHeading>
          <CodeBlock
            title="report_config 전달 데이터"
            language="python"
            code={`report_config = {
    "order_code": order_code,
    "rag_output_dir": str(order_output),
    "enriched_json_path": str(enriched_json_path),   # Stage 2 JSON 출력
    "md_report_path": str(md_path),                  # Stage 2 MD 리포트
    "experimental_context": {...},
    "research_questions": [...],                     # 사용자 연구 질문
    "chromadb_collections": [...],
    "llm_provider": "ollama",
    "llm_model": "gemma3:27b",
    "report_title": "PTM Comprehensive Analysis Report",
}`}
          />

          {/* 5. Report Generation Worker */}
          <SectionHeading id="report" level={1}>5. Stage 3: Report Generation Worker</SectionHeading>
          <figure className="my-6">
            <div className="rounded-lg overflow-hidden border border-border shadow-sm">
              <img
                src={REPORT_IMG}
                alt="Report Generation Worker Illustration"
                className="w-full"
                loading="lazy"
              />
            </div>
            <figcaption className="mt-2 text-center text-xs text-muted-foreground italic">
              Figure 4. Report Generation Worker 개념도 — LangGraph 기반 자율 에이전트 시스템
            </figcaption>
          </figure>

          <SectionHeading id="report-goal" level={2}>5.1. 목표</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-6">
            RAG로 보강된 데이터와 사용자의 연구 질문을 바탕으로, <strong>LangGraph StateGraph</strong> 기반의 자율 에이전트 시스템을 통해
            학술 논문 수준의 최종 종합 분석 리포트를 생성합니다. 가설 생성 및 검증, 네트워크 시각화, LLM 기반 섹션 작성,
            인용 포맷팅까지 전 과정을 자동화합니다.
          </p>

          <SectionHeading id="report-graph" level={2}>5.4. LangGraph StateGraph 구조</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">ReportState</code>라는 TypedDict 상태 객체를 통해
            모든 노드가 데이터를 공유하며, 아래의 13개 노드가 순차적으로 실행됩니다.
          </p>

          {/* Node flow visualization */}
          <div className="my-6 p-4 bg-violet-50/50 rounded-lg border border-violet-100 overflow-x-auto">
            <div className="flex items-center gap-1 text-xs font-mono text-violet-700 whitespace-nowrap">
              {LANGGRAPH_NODES.map((node, i) => (
                <span key={node.id} className="flex items-center gap-1">
                  <span className="px-2 py-1 bg-violet-100 rounded border border-violet-200">
                    {node.name}
                  </span>
                  {i < LANGGRAPH_NODES.length - 1 && <ArrowRight className="w-3 h-3 text-violet-400 shrink-0" />}
                </span>
              ))}
              <ArrowRight className="w-3 h-3 text-violet-400 shrink-0" />
              <span className="px-2 py-1 bg-green-100 text-green-700 rounded border border-green-200 font-bold">
                END
              </span>
            </div>
          </div>

          <SectionHeading id="report-nodes" level={2}>5.5. 노드별 상세 설명</SectionHeading>
          <div className="space-y-2 mb-6">
            {LANGGRAPH_NODES.map((node) => (
              <NodeCard key={node.id} {...node} />
            ))}
          </div>

          <p className="text-base leading-relaxed text-foreground/85 mb-3">
            <strong>write_sections</strong> 노드에서 생성되는 리포트 섹션 구성:
          </p>
          <DataTable
            caption="Table 5. LLM 작성 리포트 섹션 구성"
            headers={["섹션", "최대 토큰", "주요 내용"]}
            rows={REPORT_SECTIONS.map((s) => [
              <strong>{s.section}</strong>,
              <span className="font-mono text-xs">{s.tokens}</span>,
              s.content,
            ])}
          />

          <Callout type="output">
            <code className="text-xs font-mono">final_report.md</code>,{" "}
            <code className="text-xs font-mono">final_report.docx</code>,{" "}
            <code className="text-xs font-mono">*.png</code> (네트워크 이미지)
          </Callout>

          {/* 5.6 Temporal Co-movement Analysis (v8.0) */}
          <SectionHeading id="report-temporal" level={2}>5.6. Temporal PTM Co-movement Analysis (v8.0)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v8.0에서 추가된 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">temporal_comovement</code> 노드는
            전체 PTM의 시계열 Log2FC 데이터를 분석하여 동시에 움직이는 PTM 그룹을 탐지합니다.
            이 분석은 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">network_analysis</code> 이후,
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">write_sections</code> 이전에 실행됩니다.
          </p>

          <DataTable
            caption="Table 5b. Temporal Co-movement 분석 파이프라인"
            headers={["단계", "처리 내용", "알고리즘/도구"]}
            rows={[
              ["1. 행렬 구축", "PTM × Timepoint Log2FC 행렬 생성", "numpy array"],
              ["2. 유의 필터링", "낮은 분산/진폭의 PTM 제거 (flat lines)", "variance ≥ 0.3, amplitude ≥ 1.0"],
              ["3. 상관 행렬", "Pearson 상관계수 행렬 계산", "numpy corrcoef"],
              ["4. 계층적 클러스터링", "Average linkage 기반 클러스터링", "scipy.cluster.hierarchy"],
              ["5. 패턴 분류", "클러스터별 시계열 패턴 분류", "규칙 기반 분류기"],
              ["6. 생물학적 주석", "Pathway, Kinase, GO term 매핑", "enrichment 데이터 활용"],
              ["7. Non-PTM 연결", "클러스터 유전자와 Non-PTM interactor 매칭", "네트워크 엣지 데이터"],
              ["8. 시각화", "Heatmap + Cluster Line Plot 생성", "matplotlib/seaborn"],
            ]}
          />

          <DataTable
            caption="Table 5c. 클러스터 패턴 분류 기준"
            headers={["패턴", "조건", "생물학적 의미"]}
            rows={[
              ["transient_burst", "spike_ratio ≤ 0.4, max > 3, 양의 방향", "일시적 급등 후 기저선 복귀"],
              ["transient_suppression", "spike_ratio ≤ 0.4, max > 3, 음의 방향", "일시적 억제 후 복귀"],
              ["sustained_activation", "sustained_ratio ≥ 0.6, 양의 방향 우세", "지속적 활성화 유지"],
              ["sustained_inhibition", "sustained_ratio ≥ 0.6, 음의 방향 우세", "지속적 억제 유지"],
              ["biphasic_switch", "sign_changes ≥ 1 (양↔음 전환)", "이중 위상 반응"],
              ["sequential_wave", "peak_spread ≥ 3, members ≥ 3", "순차적 활성화 파동"],
              ["co_activated", "양의 방향 우세 (기타)", "공동 활성화"],
              ["co_inhibited", "음의 방향 우세 (기타)", "공동 억제"],
            ]}
          />

          <Callout type="info">
            <strong>Co-movement 분석 결과물.</strong> 이 노드는 3가지 state를 출력합니다:
            (1) <code className="text-xs font-mono">comovement_analysis</code> — 클러스터 목록, 멤버 상세, 패턴, 상관계수,
            (2) <code className="text-xs font-mono">comovement_figures</code> — Heatmap과 Cluster Line Plot PNG 파일 경로,
            (3) <code className="text-xs font-mono">comovement_llm_context</code> — LLM이 해석할 수 있는 텍스트 요약.
            이 컨텍스트는 <code className="text-xs font-mono">figure_context.py</code>를 통해 write_sections 노드에 주입되어,
            LLM이 시계열 클러스터링 결과를 리포트에 자연스럽게 통합할 수 있게 합니다.
          </Callout>

          {/* 5.7 Figure Composition (v8.0) */}
          <SectionHeading id="report-figures" level={2}>5.7. 리포트 Figure 구성 (v8.0)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v8.0에서 Figure 구성이 확장되었습니다. 기존 Pathway Distribution, Cascade Diagram, Cytoscape 네트워크에
            Temporal Co-movement Heatmap과 Cluster Line Plot이 추가되었습니다.
          </p>

          <DataTable
            caption="Table 5d. 리포트 Figure 구성 (v8.0)"
            headers={["Figure", "유형", "생성 노드", "설명"]}
            rows={[
              [
                <strong>Figure 1</strong>,
                "Bar Graph",
                <code className="text-xs font-mono">network_analysis</code>,
                "Canonical Pathway Distribution (Activated + Inhibited PTM 모두 포함, 3-bar 구조)",
              ],
              [
                <strong>Figure 2+</strong>,
                "Cascade Diagram",
                <code className="text-xs font-mono">cascade_mediator</code>,
                "Content-Driven Signaling Cascade — LLM 본문에서 추출된 pathway 기반",
              ],
              [
                <strong>Figure N</strong>,
                "Heatmap",
                <code className="text-xs font-mono">temporal_comovement</code>,
                "PTM Co-movement Heatmap — 클러스터별 시계열 Log2FC 히트맵",
              ],
              [
                <strong>Figure N+1</strong>,
                "Line Plot",
                <code className="text-xs font-mono">temporal_comovement</code>,
                "Cluster Line Plot — 각 클러스터의 평균 시계열 프로파일",
              ],
              [
                <strong>Figure N+2...</strong>,
                "Network Image",
                <code className="text-xs font-mono">network_analysis</code>,
                "Cytoscape 네트워크 시각화 (Timepoint별)",
              ],
            ]}
          />

          <Callout type="info">
            <strong>v7.0 아키텍처 변경: Content-Driven Cascade Diagram.</strong> 이전 버전(v6.5)에서는
            <code className="text-xs font-mono">network_analysis</code> 노드가 cascade diagram을 먼저 생성하고,
            LLM에게 해당 pathway를 강제로 언급하도록 지시했습니다. v7.0에서는 이 순서가 역전됩니다:
            (1) LLM이 pathway_candidates를 참고하되 자유롭게 맥락에 맞는 pathway를 선택하여 본문을 작성,
            (2) <code className="text-xs font-mono">cascade_mediator</code> 노드가 Results/Discussion 텍스트에서
            실제 논의된 pathway를 3단계로 추출 (직접 이름 매칭 → Gene cluster 감지 → Alias 매칭),
            (3) 추출된 pathway만으로 <code className="text-xs font-mono">signaling_cascade.py</code>의 렌더링 엔진을 호출하여
            cascade diagram을 생성합니다.
          </Callout>

          {/* 5.8 Report Quality Improvements (v8.1) */}
          <SectionHeading id="report-quality" level={2}>5.8. 리포트 품질 개선 (v8.1)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v8.1에서는 생성된 리포트의 과학적 품질을 전반적으로 개선하는 여러 수정이 적용되었습니다.
          </p>

          <DataTable
            caption="Table 5e. v8.1 품질 개선 항목"
            headers={["항목", "문제", "해결"]}
            rows={[
              ["Vector Plot 시간 정렬", "10min이 2min 앞에 표시 (사전순 정렬)", "자연어 정렬 함수 적용 (parseTimeOrder / _natural_sort_key)"],
              ["Treatment Name 강제", "리포트에서 'applied treatment'로만 표기", "LLM 프롬프트에 treatment name 명시적 주입"],
              ["극단값 Log2FC 주석", "Log2FC > 15 값의 의미 설명 부재", "Binary ON/OFF switch 해석 가이드 추가"],
              ["Fallback Kinase 예측", "enrichment에 kinase 없을 때 빈 네트워크", "LLM 기반 kinase 예측 fallback 추가"],
              ["Figure 1 편향 보정", "Activated PTM만 포함된 bar graph", "3-bar 구조 (Activated + Inhibited + Net)"],
              ["Off-topic 참고문헌 필터링", "관련 없는 문헌이 인용됨", "제목/초록 키워드 매칭 기반 필터링"],
            ]}
          />

          {/* 5.9 PTM Classification System (v8.2) */}
          <SectionHeading id="report-classification" level={2}>5.9. PTM 분류 시스템 (v8.2)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v8.2에서는 프론트엔드의 PTM 시계열 분류 로직을 백엔드의 temporal_comovement 패턴 분류와 일치시켰습니다.
            기존 5개 카테고리에서 8개 카테고리로 확장하고, 분류 기준을 데이터 적응형으로 개선했습니다.
          </p>

          <DataTable
            caption="Table 5f. PTM 분류 카테고리 (v8.2)"
            headers={["카테고리", "조건", "설명"]}
            rows={[
              ["Sustained Activation", "sustainedRatio ≥ 0.5, 양의 방향 우세", "대부분 시간대에서 높은 양의 Log2FC"],
              ["Sustained Inhibition", "sustainedRatio ≥ 0.5, 음의 방향 우세", "대부분 시간대에서 음의 Log2FC"],
              ["Transient Burst", "spikeRatio ≤ 0.4, absMax > 2.0", "일시적 급등 후 기저선 복귀"],
              ["Increasing", "trendDiff > 0.8, ups > downs, dirChanges ≤ 2", "시간에 따른 증가 추세"],
              ["Decreasing", "trendDiff < -0.8, downs > ups, dirChanges ≤ 2", "시간에 따른 감소 추세"],
              ["Biphasic", "signChanges ≥ 1, range > 1.5", "양↔음 전환이 있는 이중 위상 패턴"],
              ["Volatile", "dirChanges ≥ 3, range > 1.5", "다수의 방향 전환 (불규칙 변동)"],
              ["Other", "absMax < 0.8 또는 미분류", "낮은 변동 또는 미분류 패턴"],
            ]}
          />

          <Callout type="warning">
            <strong>v8.2 분류 개선 핵심.</strong> 이전 버전에서는 고정 임계값(|Log2FC| ≥ 2)을 사용하여
            대부분의 PTM이 "Volatile"로 분류되는 문제가 있었습니다. v8.2에서는 데이터 적응형 메트릭
            (spikeRatio, sustainedRatio, signChanges)을 도입하고, 분류 우선순위를 specificity 순서로
            정렬하여 의미 있는 분류 분포를 달성합니다. 또한 중간 강도 신호(absMax ≥ 1.0)에 대한
            fallback 분류 로직을 추가하여 "Other"로 빠지는 PTM 수를 최소화합니다.
          </Callout>

          {/* 5.10 Non-PTM Effector Integration (v9.34) */}
          <SectionHeading id="report-effector" level={2}>5.10. Non-PTM Effector 통합 (v9.34+)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v9.34+에서는 <strong>Non-PTM Effector 단백질</strong>을 두 가지 유형으로 4번째 레이어에 통합했습니다.
          </p>
          <p className="text-base leading-relaxed text-foreground/85 mb-2">
            <strong>(1) PPI-based Effector</strong> — STRING-DB, BioGRID, KEA3 네트워크 엣지를 통해
            PTM Substrate와 물리적으로 상호작용하는 단백질입니다. Evidence strength는 PPI confidence score에 따라
            strong (≥700), moderate (400-699), weak (&lt;400)으로 분류됩니다.
            프론트엔드에서 <strong>green/red 실선 border</strong>로 표시됩니다.
          </p>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            <strong>(2) Expression-only Effector</strong> — TSV의 <code className="text-xs font-mono">Data_Type = "Protein_Only"</code> 행 중
            |Protein_Log2FC| &gt; 0.3인 모든 단백질을 포함합니다. PPI 관계 없이 유의미한 발현 변화만으로 추출되며,
            프론트엔드에서 <strong>sky-blue 점선 border</strong>로 시각적으로 구분됩니다.
            이를 통해 PPI 데이터베이스에 등록되지 않았지만 실험적으로 유의미한 변화를 보이는 단백질도 분석에 포함됩니다.
          </p>

          <DataTable
            caption="Table 5g. Non-PTM Effector 추출 파이프라인"
            headers={["단계", "처리", "상세"]}
            rows={EFFECTOR_EXTRACTION_STEPS.map((s) => [
              <span className="font-mono text-xs">{s.step}</span>,
              <strong>{s.action}</strong>,
              s.detail,
            ])}
          />

          <Callout type="info">
            <strong>Effector 데이터 구조.</strong> 각 Non-PTM Effector는 다음 정보를 포함합니다:
            <code className="text-xs font-mono">gene</code> (HGNC 심볼),
            <code className="text-xs font-mono">peak_fc</code> (|Log2FC| 최대값),
            <code className="text-xs font-mono">peak_condition</code> (peak 시점),
            <code className="text-xs font-mono">evidence_strength</code> (strong/moderate/weak/expression_only),
            <code className="text-xs font-mono">sources</code> (STRING/BioGRID/KEA3 또는 "expression_only"),
            <code className="text-xs font-mono">temporal_profile</code> (condition별 Protein_Log2FC),
            <code className="text-xs font-mono">connected_substrates</code> (PPI-based만 해당, expression_only는 빈 배열).
            이 데이터는 <code className="text-xs font-mono">global-kinase-modules</code> API의
            <code className="text-xs font-mono">effector_proteins</code> 필드로 프론트엔드에 전달됩니다.
          </Callout>

          {/* 5.11 4-Layer Signal Flow (v9.34) */}
          <SectionHeading id="report-signalflow" level={2}>5.11. 4-Layer Signal Flow 다이어그램 (v9.34)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v9.34+에서 Signal Flow 다이어그램이 기존 3-layer(Receptor → Kinase → Substrate)에서
            <strong> 4-layer(Receptor → Kinase → Substrate → Non-PTM Effector)</strong>로 확장되었습니다.
            이 다이어그램은 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">signal_flow_figure.py</code>에서
            matplotlib로 렌더링되며, 프론트엔드의 Signal Flow 탭에서도 동일한 구조를 인터랙티브하게 시각화합니다.
            Non-PTM Effector 레이어에서는 PPI-based와 expression_only 두 유형이 시각적으로 구분됩니다.
          </p>

          <DataTable
            caption="Table 5h. Signal Flow 4-Layer 구조"
            headers={["Layer", "이름", "색상", "노드 형태", "데이터 소스"]}
            rows={SIGNAL_FLOW_LAYERS.map((l) => [
              <span className="font-mono font-bold">{l.layer}</span>,
              <strong>{l.name}</strong>,
              <span className="inline-flex items-center gap-1">
                <span className="w-3 h-3 rounded" style={{ backgroundColor: l.color.split(" / ")[0] }} />
                <code className="text-xs font-mono">{l.color}</code>
              </span>,
              l.shape,
              <span className="text-xs">{l.source}</span>,
            ])}
          />

          {/* 4-layer visual diagram */}
          <div className="my-6 p-5 bg-gradient-to-b from-slate-50 to-white rounded-lg border border-border">
            <div className="flex flex-col items-center gap-3">
              {SIGNAL_FLOW_LAYERS.map((l, i) => (
                <div key={l.layer} className="flex flex-col items-center gap-2 w-full">
                  <div
                    className="flex items-center gap-3 px-5 py-3 rounded-lg border-2 w-full max-w-lg"
                    style={{ borderColor: l.color.split(" / ")[0], backgroundColor: l.color.split(" / ")[0] + "15" }}
                  >
                    <span className="font-mono font-bold text-sm" style={{ color: l.color.split(" / ")[0] }}>L{l.layer}</span>
                    <div>
                      <p className="text-sm font-semibold text-foreground">{l.name}</p>
                      <p className="text-xs text-muted-foreground">{l.desc}</p>
                    </div>
                  </div>
                  {i < SIGNAL_FLOW_LAYERS.length - 1 && (
                    <ArrowRight className="w-4 h-4 text-muted-foreground rotate-90" />
                  )}
                </div>
              ))}
            </div>
            <p className="text-center text-xs text-muted-foreground mt-4 italic">
              Figure. Signal Flow 4-Layer 구조 개념도 — 각 레이어는 신호 전달 방향을 따라 위에서 아래로 배치됩니다
            </p>
          </div>

          <Callout type="info">
            <strong>Time-lag 시각화.</strong> PPI-based Effector의 peak Protein_Log2FC 시점을
            연결된 substrate의 peak PTM_Relative_Log2FC 시점과 비교하여 time-lag를 계산합니다.
            Expression-only Effector는 substrate 연결이 없으므로 time-lag 대신 peak condition만 표시됩니다.
            프론트엔드의 Signal Flow 탭에서는 이 정보가 툴팁으로 표시되며,
            Cascade View 탭에서는 temporal swimlane에 effector 데이터가 오버레이됩니다.
          </Callout>

          {/* Updated Figure table */}
          <DataTable
            caption="Table 5i. 리포트 Figure 구성 (v9.34 업데이트)"
            headers={["Figure", "유형", "생성 노드", "설명"]}
            rows={REPORT_FIGURES_V934.map((f) => [
              <strong>{f.figure}</strong>,
              f.type,
              <code className="text-xs font-mono">{f.node}</code>,
              f.desc,
            ])}
          />

          {/* 6. Data Flow */}
          <SectionHeading id="dataflow" level={1}>6. Worker 간 데이터 흐름 요약</SectionHeading>

          {/* Visual data flow */}
          <div className="my-8 flex flex-col sm:flex-row items-stretch gap-4">
            {[
              { name: "Preprocessing", color: "teal", outputs: ["ptm_vector_data.tsv"] },
              { name: "RAG Enrichment", color: "amber", outputs: ["enriched_ptm_data.json", "comprehensive_report.md"] },
              { name: "Report Generation", color: "violet", outputs: ["final_report.md", "final_report.docx", "*.png"] },
            ].map((w, i) => {
              const c = workerColors[w.color as keyof typeof workerColors];
              return (
                <div key={w.name} className="flex items-center gap-4 flex-1">
                  <div className={`flex-1 rounded-lg border ${c.border} ${c.bg} p-4`}>
                    <p className={`text-xs font-semibold ${c.text} mb-2`}>{w.name}</p>
                    {w.outputs.map((o) => (
                      <p key={o} className="text-xs font-mono text-foreground/70">{o}</p>
                    ))}
                  </div>
                  {i < 2 && (
                    <ArrowRight className="w-5 h-5 text-muted-foreground shrink-0 hidden sm:block" />
                  )}
                </div>
              );
            })}
          </div>

          <DataTable
            caption="Table 6. Worker 간 전달 데이터"
            headers={["전달 구간", "전달 방식", "핵심 전달 데이터"]}
            rows={[
              [
                <span className="font-medium">Preprocessing → RAG</span>,
                <code className="text-xs font-mono">Celery send_task()</code>,
                <code className="text-xs font-mono">preprocessing_output_dir</code>,
              ],
              [
                <span className="font-medium">RAG → Report</span>,
                <code className="text-xs font-mono">Celery send_task()</code>,
                <span><code className="text-xs font-mono">enriched_json_path</code>, <code className="text-xs font-mono">md_report_path</code></span>,
              ],
            ]}
          />

          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            모든 Worker는 공유 볼륨(<code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">./data:/app/data</code>)을 통해
            동일한 파일 시스템에 접근하므로, 파일 경로만 전달하면 다음 Worker가 해당 파일을 직접 읽을 수 있습니다.
          </p>

          <DataTable
            caption="Table 7. 공유 인프라 서비스"
            headers={["서비스", "용도", "Worker 사용"]}
            rows={SHARED_INFRA.map((s) => [
              <strong>{s.service}</strong>,
              s.usage,
              <span className="text-xs">{s.workers}</span>,
            ])}
          />

          <h3 className="font-serif text-xl font-semibold mt-8 mb-3">6.2. 진행률 보고 체계</h3>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            모든 Worker는 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">common/progress.py</code>의{" "}
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">publish_progress()</code> 함수를 통해
            실시간 진행률을 세 가지 채널로 동시에 보고합니다:
          </p>
          <div className="space-y-3 mb-6">
            {[
              { icon: Database, label: "MySQL orders 테이블", desc: "progress_pct, stage_detail, current_stage 컬럼 업데이트" },
              { icon: Database, label: "MySQL order_logs 테이블", desc: "모든 진행 이벤트를 시계열로 기록 (감사 추적용)" },
              { icon: Globe, label: "Redis Pub/Sub", desc: "order:progress:{order_id} 채널로 JSON 메시지 발행 (프론트엔드 SSE 실시간 스트리밍용)" },
            ].map((ch) => (
              <div key={ch.label} className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border/50">
                <ch.icon className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-foreground">{ch.label}</p>
                  <p className="text-xs text-muted-foreground">{ch.desc}</p>
                </div>
              </div>
            ))}
          </div>

          {/* 7. Infrastructure */}
          <SectionHeading id="infra" level={1}>7. 인프라 구성</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            PTM Platform은 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">docker-compose.yml</code>에 정의된
            <strong> 10개의 서비스 컨테이너</strong>로 구성됩니다.
          </p>

          <DataTable
            caption="Table 8. Docker Compose 서비스 구성"
            headers={["서비스", "컨테이너명", "역할"]}
            compact
            rows={DOCKER_SERVICES.map((s) => [
              <code className="text-xs font-mono">{s.service}</code>,
              <code className="text-xs font-mono text-muted-foreground">{s.container}</code>,
              s.role,
            ])}
          />

          <h3 className="font-serif text-xl font-semibold mt-8 mb-3">7.2. 네트워크 및 외부 연결</h3>
          <CodeBlock
            title="Docker Network 구조"
            language="text"
            code={`Docker Network (ptm-platform-network)
├── mysql:3306
├── redis:6379
├── chromadb:8000
├── api-server:8080
├── mcp-server:8001
├── celery-worker-preprocessing
├── celery-worker-rag
├── celery-worker-report
├── frontend:3000
└── gateway:80/443

Host Machine
├── Cytoscape Desktop → host.docker.internal:1234
└── Ollama → host.docker.internal:11434`}
          />

          {/* 8. Operations */}
          <SectionHeading id="operations" level={1}>8. 운영 가이드</SectionHeading>

          <h3 className="font-serif text-xl font-semibold mt-6 mb-3">8.1. 특정 단계만 재실행</h3>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            각 Worker는 <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">chain_to_next</code> 설정을 통해 독립적으로 실행할 수 있습니다.
            특정 단계에서 오류가 발생한 경우, 해당 단계만 재실행하면 이전 단계의 출력물을 재사용합니다.
          </p>

          <h3 className="font-serif text-xl font-semibold mt-6 mb-3">8.2. 코드 변경 후 적용</h3>
          <p className="text-base leading-relaxed text-foreground/85 mb-3">
            Worker 코드를 수정한 경우, Docker 이미지를 재빌드해야 합니다.
          </p>
          <CodeBlock
            title="특정 Worker만 재빌드 및 재시작"
            language="bash"
            code={`# 특정 Worker만 재빌드 및 재시작
docker compose build --no-cache celery-worker-report
docker compose up -d celery-worker-report`}
          />

          <h3 className="font-serif text-xl font-semibold mt-6 mb-3">8.3. Idempotent 설계</h3>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            Preprocessing Worker는 각 Step의 출력 파일 존재 여부를 확인하여, 이미 완료된 Step을 건너뜁니다.
            따라서 중간에 실패한 경우 동일한 Order를 다시 실행하면 완료된 부분은 건너뛰고 실패한 지점부터 재개됩니다.
            강제로 처음부터 재실행하려면 해당 Order의 출력 디렉토리를 삭제해야 합니다.
          </p>
          <Callout type="warning">
            강제 재실행 시 해당 Order의 출력 디렉토리를 삭제해야 합니다. 이는 이전 단계의 출력물이 남아있으면
            해당 Step을 건너뛰기 때문입니다.
          </Callout>

          {/* ═══════════════════════════════════════════════════════════════ */}
          {/* 9. AI Analysis Chat */}
          {/* ═══════════════════════════════════════════════════════════════ */}
          <SectionHeading id="ai-chat" level={1}>9. AI Analysis Chat</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            Vector Plot &gt; Top N PTM Time-series 페이지에 내장된 <strong>컨텍스트 기반 AI 채팅</strong> 기능입니다.
            분석이 완료된 주문의 모든 결과 데이터를 참조하여 연구자의 질문에 답변합니다.
          </p>
          <Callout type="info">
            고정 모델: <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">exaone-deep:7.8b</code> (Ollama, 32K context window, 한국어/영어 지원)
          </Callout>

          <SectionHeading id="ai-chat-arch" level={2}>9.1. 아키텍처</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            채팅은 SSE(Server-Sent Events) 스트리밍 방식으로 동작합니다.
            프론트엔드에서 현재 뷰 상태(체크된 PTM, 활성 탭, 필터 등)를 자동으로 백엔드에 전달하고,
            백엔드는 주문의 분석 결과 파일들을 읽어 컨텍스트를 조립한 뒤 Ollama에 스트리밍 요청합니다.
          </p>
          <CodeBlock
            title="API 엔드포인트"
            language="text"
            code={`POST /api/orders/{order_id}/chat   (SSE streaming)
GET  /api/orders/{order_id}/chat-context-info

Request Body:
{
  "message": "이 receptor는 신뢰할 만해?",
  "conversation_history": [...],
  "view_context": {
    "active_tab": "vector-plot",
    "checked_ptms": ["MAPK1_Y187", "AKT1_S473"],
    "metric": "relative"
  },
  "rag_collection_ids": [1, 3]
}`}
          />

          <SectionHeading id="ai-chat-context" level={2}>9.2. 컨텍스트 조립</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            32K 토큰 제약 내에서 최대한 풍부한 컨텍스트를 제공하기 위해, 각 데이터 소스별 토큰 예산을 배분합니다.
          </p>
          <DataTable
            headers={["컨텍스트 영역", "토큰 예산", "소스 파일"]}
            rows={[
              ["실험 정보", "~500", "Order DB (species, treatment, time_points)"],
              ["현재 뷰 상태", "~500", "Frontend view_context (실시간)"],
              ["분석 리포트", "~4K", "comprehensive_report_*.md"],
              ["Enriched PTM 요약", "~3K", "enriched_ptm_data_*.json (상위 30개)"],
              ["Kinase Module", "~3K", "global_kinase_modules_*.json"],
              ["Co-movement 클러스터", "~1.5K", "temporal_comovement_*.json"],
              ["파이프라인 방법론", "~1.5K", "고정 텍스트 (Evidence Scoring 등)"],
              ["RAG 문헌 검색", "~3K", "ChromaDB 쿼리 (사용자 질문 기반)"],
              ["대화 히스토리", "~3K", "최근 10턴"],
            ]}
          />
          <Callout type="info">
            RAG Collection은 사용자가 채팅 패널에서 직접 선택할 수 있습니다.
            선택된 collection에서 사용자 질문과 관련된 문헌을 검색하여 답변에 반영합니다.
          </Callout>

          <SectionHeading id="ai-chat-usage" level={2}>9.3. 사용 가이드</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-3">
            Vector Plot 탭에서 <strong>"AI Chat"</strong> 버튼을 클릭하면 우측에 채팅 패널이 열립니다.
            다음과 같은 질문 유형을 지원합니다:
          </p>
          <DataTable
            headers={["질문 유형", "예시", "참조 데이터"]}
            rows={[
              ["신뢰도 평가", "이 receptor는 얼마나 신뢰할 만해?", "Evidence Scoring (0-5)"],
              ["방법론 설명", "PTM-vector 방식이 왜 우월한지?", "Pipeline Methodology"],
              ["관계 탐색", "관련된 substrate들은 뭐야?", "Kinase Module, Signal Flow"],
              ["Temporal 해석", "A 단백질의 변화는 어떤 영향?", "Co-movement, Vector Data"],
              ["Discovery", "새로운 upstream regulator를 찾으려면?", "RAG Collection + PPI"],
              ["결과 신뢰도", "분석 결과가 얼마나 신뢰할 만하지?", "Evidence Scoring, q-value"],
            ]}
          />
          <Callout type="warning">
            AI 답변은 분석 데이터와 RAG 문헌에 기반하지만, 항상 원본 데이터를 직접 확인하세요.
            LLM의 추론 범위는 사용자 데이터와 ChromaDB 내 정보로 한정됩니다.
          </Callout>

          {/* Footer */}
          <div className="mt-20 pt-8 border-t border-border">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>PTM Platform Pipeline Manual v1.7</span>
              <span>Generated by Manus AI &middot; 2026-04-05</span>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
