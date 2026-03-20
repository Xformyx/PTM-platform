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
  DOCKER_SERVICES,
  SHARED_INFRA,
} from "@/lib/pipeline-data";
import { Beaker, BookOpen, FileText, ArrowRight, Database, Server, Globe } from "lucide-react";

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
            Pipeline Manual v1.1
          </span>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs text-muted-foreground">2026-03-15</span>
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
            모든 노드가 데이터를 공유하며, 아래의 11개 노드가 순차적으로 실행됩니다.
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

          <SectionHeading id="report-figures" level={2}>5.6. 리포트 Figure 구성 (v7.0)</SectionHeading>
          <p className="text-base leading-relaxed text-foreground/85 mb-4">
            v7.0에서 Figure 생성 아키텍처가 변경되었습니다. <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">network_analysis</code> 노드는
            Pathway Distribution Graph와 Cytoscape 네트워크만 생성하고, Signaling Cascade Diagram은
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">cascade_mediator</code> 노드가
            LLM이 작성한 본문 내용을 분석하여 생성합니다.
          </p>

          <DataTable
            caption="Table 5b. 리포트 Figure 구성"
            headers={["Figure", "유형", "생성 함수", "설명"]}
            rows={[
              [
                <strong>Figure 1</strong>,
                "Bar Graph",
                <code className="text-xs font-mono">_generate_pathway_distribution_graph()</code>,
                "Canonical Pathway Distribution (|Log2FC| 가중치 기반 경로 분포)",
              ],
              [
                <strong>Figure 2+</strong>,
                "Cascade Diagram",
                <code className="text-xs font-mono">cascade_mediator → generate_cascade_from_selected_pathways()</code>,
                "Content-Driven Signaling Cascade — LLM 본문에서 추출된 pathway 기반, 조건별 개별 생성",
              ],
              [
                <strong>Figure N+</strong>,
                "Network Image",
                <code className="text-xs font-mono">_generate_cytoscape_networks()</code>,
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
            cascade diagram을 생성합니다. 이를 통해 본문 내용과 다이어그램이 자연스럽게 일치합니다.
            노드 색상은 PTM 활성화 상태(Red/Blue), Non-PTM 상호작용자(Green/Purple),
            Kinase(Orange Diamond)로 구분되며, 화살표는 canonical pathway template에 따른 신호 전달 방향을 나타냅니다.
          </Callout>

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

          {/* Footer */}
          <div className="mt-20 pt-8 border-t border-border">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>PTM Platform Pipeline Manual v1.1</span>
              <span>Generated by Manus AI &middot; 2026-03-15</span>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
