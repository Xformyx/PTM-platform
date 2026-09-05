import { useState, useEffect } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { AutoResizeTextarea } from "@/components/ui/auto-resize-textarea";
import { Brain, BookOpen, FlaskConical, MessageSquare, Network, Plus, SlidersHorizontal, X, ChevronDown, ChevronUp, Settings2, RotateCcw, Database, CheckSquare, Square, Loader2, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import AnalysisOptionsModal from "./AnalysisOptionsModal";
import type { AnalysisOptions, TemporalContract } from "@/lib/types";
import { DEFAULT_ANALYSIS_OPTIONS, DEFAULT_TEMPORAL_CONTRACT, clampQuickSettings, pickQuickSettings, resolveTemporalContract } from "@/lib/types";
import QuickAnalysisCustomFields from "./QuickAnalysisOptions";
import { cn } from "@/lib/utils";
import { CLOUD_PROVIDER_SENTINEL, CLOUD_MODEL_PRESETS, type CloudProvider } from "@/lib/llm-models";

const CLOUD_PROVIDERS = ["gemini", "openai", "anthropic"] as const;

function isCloudProviderSelection(val: string): boolean {
  const p = val?.split(":")[0];
  return !!(p && CLOUD_PROVIDERS.includes(p as any));
}

/** Minimum model size (in billions) for RAG Enrichment */
const MIN_RAG_MODEL_SIZE_B = 14;
function getModelSizeB(modelName: string): number {
  if (!modelName) return 0;
  if (isCloudProviderSelection(modelName)) return 0;
  const lower = modelName.toLowerCase();
  if (lower.includes(":")) {
    const tag = lower.split(":")[1];
    const m = tag?.match(/^(\d+(?:\.\d+)?)b/);
    if (m) return Math.floor(parseFloat(m[1]));
  }
  const m = lower.match(/[:\-_](\d+(?:\.\d+)?)b/);
  if (m) return Math.floor(parseFloat(m[1]));
  return 0;
}
function isRagModelTooSmall(modelName: string): boolean {
  if (!modelName) return false;
  const size = getModelSizeB(modelName);
  return size > 0 && size < MIN_RAG_MODEL_SIZE_B;
}

interface Order {
  id: number;
  order_code: string;
  analysis_context?: Record<string, unknown>;
  analysis_options?: Record<string, unknown>;
  report_options?: Record<string, unknown>;
  rag_collections?: number[] | null;
  kinase_analysis_data?: Record<string, unknown>;
  temporal_evidence_readiness?: {
    status: "ready" | "missing";
    source: string | null;
    artifact: string | null;
    dynamic_transition_status: string | null;
    message: string;
  };
}

interface LlmModelOption {
  provider: string;
  model_id: string;
  name: string;
}

export interface RerunConfirmPayload {
  analysis_context: Record<string, unknown>;
  analysis_options: Record<string, unknown>;
  report_options: Record<string, unknown>;
  rag_collections?: number[] | null;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  order: Order | null;
  llmModels: LlmModelOption[];
  defaultLlmModel: string;
  onConfirm: (opts: RerunConfirmPayload) => void | Promise<void>;
  confirmLabel?: string;
  duplicateMode?: boolean;
  duplicateName?: string;
  onDuplicateNameChange?: (name: string) => void;
}

const DEFAULT_CONTEXT = {
  cell_type: "",
  treatment: "",
  time_points: "",
  biological_question: "",
  special_conditions: "",
};

export default function RerunOptionsModal({
  open,
  onOpenChange,
  order,
  llmModels,
  defaultLlmModel,
  onConfirm,
  confirmLabel = "Confirm & Run",
  duplicateMode = false,
  duplicateName = "",
  onDuplicateNameChange,
}: Props) {
  const [analysisContext, setAnalysisContext] = useState<Record<string, string>>(DEFAULT_CONTEXT);
  const [analysisMode, setAnalysisMode] = useState<"ptm_only" | "ptm_nonptm_network">("ptm_only");
  const [temporalContract, setTemporalContract] = useState<TemporalContract>(DEFAULT_TEMPORAL_CONTRACT);
  const [analysisOptions, setAnalysisOptions] = useState<AnalysisOptions>({ ...DEFAULT_ANALYSIS_OPTIONS });
  const [analysisModalOpen, setAnalysisModalOpen] = useState(false);
  const [reportType, setReportType] = useState("comprehensive");
  const [ptmSelectionMode, setPtmSelectionMode] = useState<"top_n" | "de_novo" | "regulated" | "de_novo_regulated" | "minor" | "all">("de_novo_regulated");
  const [topNPtms, setTopNPtms] = useState(50);
  const [llmModel, setLlmModel] = useState("");
  const [ragEnrichmentLlmModel, setRagEnrichmentLlmModel] = useState("");
  const [llmCloudModelVariant, setLlmCloudModelVariant] = useState("");
  const [ragEnrichmentLlmCloudModelVariant, setRagEnrichmentLlmCloudModelVariant] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [researchQuestions, setResearchQuestions] = useState<string[]>([]);
  const [newQuestion, setNewQuestion] = useState("");
  const [coScientistIntegrationMode, setCoScientistIntegrationMode] = useState<"disabled" | "addendum" | "enhanced_discussion">("disabled");
  const [coScientistSessionId, setCoScientistSessionId] = useState("");
  const [coScientistSessions, setCoScientistSessions] = useState<Array<{ session_id: string; status: string; created_at?: string; research_goal?: string }>>([]);
  const [coScientistSessionsLoading, setCoScientistSessionsLoading] = useState(false);

  // RAG Collection Selection
  interface RagCollectionItem {
    id: number;
    name: string;
    description: string | null;
    tier: string;
    chromadb_name: string;
    document_count: number;
    chunk_count: number;
    is_active: boolean;
  }
  const [ragCollections, setRagCollections] = useState<RagCollectionItem[]>([]);
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<number[]>([]);
  const [ragCollectionsLoading, setRagCollectionsLoading] = useState(false);
  const [useAllCollections, setUseAllCollections] = useState(true);
  const [reportConfig, setReportConfig] = useState({
    md_summary_max_chars: 12000, section_chars_limit: 1500,
    llm_tokens_abstract: 4096, llm_tokens_introduction: 12288,
    llm_tokens_results: 16384, llm_tokens_time_course: 8192,
    llm_tokens_discussion: 12288, llm_tokens_conclusion: 6144,
    llm_temperature: 0.6, chromadb_results_per_section: 10,
    ptm_detail_count: 30,
  });

  // Load RAG collections when modal opens
  useEffect(() => {
    if (open) {
      setRagCollectionsLoading(true);
      api.get<{ collections: RagCollectionItem[] }>("/rag/collections")
        .then((d) => {
          const active = d.collections.filter((c) => c.is_active);
          setRagCollections(active);
        })
        .catch(() => setRagCollections([]))
        .finally(() => setRagCollectionsLoading(false));
    }
  }, [open]);

  // A researcher must explicitly choose a completed external session. Sessions
  // are never auto-attached because a session can pursue a deliberately narrow goal.
  useEffect(() => {
    if (!open || !order) return;
    setCoScientistSessionsLoading(true);
    api.get<{ sessions?: Array<{ session_id: string; status: string; created_at?: string; research_goal?: string }> } | Array<{ session_id: string; status: string; created_at?: string; research_goal?: string }>>(
      `/orders/${order.id}/coscientist/sessions`
    )
      .then((payload) => {
        const sessions = Array.isArray(payload) ? payload : (payload.sessions || []);
        setCoScientistSessions(sessions.filter((session) => session.status === "completed"));
      })
      .catch(() => setCoScientistSessions([]))
      .finally(() => setCoScientistSessionsLoading(false));
  }, [open, order?.id]);

  // Load existing order values whenever modal opens — preserve user's previous settings
  useEffect(() => {
    if (open && order) {
      // Restore RAG collection selection from order
      const existingRagCols = order.rag_collections;
      if (existingRagCols && Array.isArray(existingRagCols) && existingRagCols.length > 0) {
        setUseAllCollections(false);
        setSelectedCollectionIds(existingRagCols);
      } else {
        setUseAllCollections(true);
        setSelectedCollectionIds([]);
      }
      const ctx = (order.analysis_context || {}) as Record<string, unknown>;
      const str = (v: unknown) => (v != null && typeof v === "string" ? v : "");
      setAnalysisContext({
        cell_type: str(ctx.cell_type),
        treatment: str(ctx.treatment),
        time_points: str(ctx.time_points),
        biological_question: str(ctx.biological_question),
        special_conditions: str(ctx.special_conditions),
      });
      const ro = (order.report_options || {}) as Record<string, unknown>;
      const modeVal = ro.analysis_mode as string;
      setAnalysisMode(
        modeVal === "ptm_nonptm_network" ? "ptm_nonptm_network" : "ptm_only"
      );
      setTemporalContract(resolveTemporalContract(ro.temporal_contract));
      setReportType(typeof ro.report_type === "string" ? ro.report_type : "comprehensive");
      const coIntegration = (ro.co_scientist_integration || {}) as Record<string, unknown>;
      const savedIntegrationMode = coIntegration.mode;
      setCoScientistIntegrationMode(
        coIntegration.enabled === true && (savedIntegrationMode === "addendum" || savedIntegrationMode === "enhanced_discussion")
          ? savedIntegrationMode
          : "disabled"
      );
      setCoScientistSessionId(typeof coIntegration.session_id === "string" ? coIntegration.session_id : "");
      const savedMode = ro.ptm_selection_mode as string;
      const validModes = ["top_n", "de_novo", "regulated", "de_novo_regulated", "minor", "all"];
      setPtmSelectionMode(validModes.includes(savedMode) ? savedMode as typeof ptmSelectionMode : "de_novo_regulated");
      const savedTopN = typeof ro.top_n_ptms === "number" ? ro.top_n_ptms : 50;
      setTopNPtms(savedTopN);
      const lm = ro.llm_model as string; const rp = ro.llm_provider as string;
      const rem = ro.rag_enrichment_llm_model as string;
      const rerp = ro.rag_enrichment_llm_provider as string;
      const hasProviderConfig = (p: string) => llmModels.some((m) => m.provider === p && m.model_id === CLOUD_PROVIDER_SENTINEL);
      if (rp && lm) {
        setLlmModel(hasProviderConfig(rp) ? `${rp}:${CLOUD_PROVIDER_SENTINEL}` : `${rp}:${lm}`);
        setLlmCloudModelVariant(CLOUD_PROVIDERS.includes(rp as any) ? lm : "");
      } else {
        setLlmModel(lm || "");
      }
      if (rerp && rem) {
        setRagEnrichmentLlmModel(hasProviderConfig(rerp) ? `${rerp}:${CLOUD_PROVIDER_SENTINEL}` : `${rerp}:${rem}`);
        setRagEnrichmentLlmCloudModelVariant(CLOUD_PROVIDERS.includes(rerp as any) ? rem : "");
      } else {
        setRagEnrichmentLlmModel(rem || "");
        setRagEnrichmentLlmCloudModelVariant("");
      }
      const rq = ro.research_questions;
      setResearchQuestions(Array.isArray(rq) ? rq.filter((q): q is string => typeof q === "string") : []);
      const ao = (order.analysis_options || {}) as Record<string, unknown>;
      const n = (v: unknown, def: number) => (typeof v === "number" && !isNaN(v) ? v : def);
      setAnalysisOptions({
        mode: (ao.mode as AnalysisOptions["mode"]) || "full",
        topN: n(ao.topN ?? ao.top_n, 500),
        log2fcThreshold: n(ao.log2fcThreshold ?? ao.log2fc_threshold, 0.5),
        proteinCount: n(ao.proteinCount ?? ao.protein_count, 1000),
        proteinListPath: typeof ao.protein_list_path === "string" ? ao.protein_list_path : undefined,
        quick_analysis: Boolean(ao.quick_analysis),
        ...pickQuickSettings(ao),
      });
      // Load existing report_config
      const rc = ro.report_config as Record<string, unknown> | undefined;
      if (rc) {
        const lt = (rc.llm_tokens || {}) as Record<string, unknown>;
        setReportConfig({
          md_summary_max_chars: n(rc.md_summary_max_chars, 12000),
          section_chars_limit: n(rc.section_chars_limit, 1500),
          llm_tokens_abstract: n(lt.abstract, 4096),
          llm_tokens_introduction: n(lt.introduction, 12288),
          llm_tokens_results: n(lt.results, 16384),
          llm_tokens_time_course: n(lt.time_course, 8192),
          llm_tokens_discussion: n(lt.discussion, 12288),
          llm_tokens_conclusion: n(lt.conclusion, 6144),
          llm_temperature: typeof rc.llm_temperature === "number" ? rc.llm_temperature : 0.6,
          chromadb_results_per_section: n(rc.chromadb_results_per_section, 10),
          ptm_detail_count: n(rc.ptm_detail_count, 30),
        });
      }
    }
  }, [open, order, llmModels]);

  const handleConfirm = async () => {
    if (!order) return;
    setSubmitting(true);
    try {
      const optsForApi: Record<string, unknown> = {
        mode: analysisOptions.mode,
        topN: analysisOptions.topN,
        log2fcThreshold: analysisOptions.log2fcThreshold,
        proteinCount: analysisOptions.proteinCount,
        quick_analysis: Boolean(analysisOptions.quick_analysis),
        ...clampQuickSettings(pickQuickSettings(analysisOptions)),
      };
      if (order.analysis_options?.protein_list_path) {
        optsForApi.protein_list_path = order.analysis_options.protein_list_path;
      }
      const baseReportOpts = (order.report_options || {}) as Record<string, unknown>;
      const reportConfigNested = {
        md_summary_max_chars: reportConfig.md_summary_max_chars,
        section_chars_limit: reportConfig.section_chars_limit,
        llm_tokens: {
          abstract: reportConfig.llm_tokens_abstract,
          introduction: reportConfig.llm_tokens_introduction,
          results: reportConfig.llm_tokens_results,
          time_course: reportConfig.llm_tokens_time_course,
          discussion: reportConfig.llm_tokens_discussion,
          conclusion: reportConfig.llm_tokens_conclusion,
        },
        llm_temperature: reportConfig.llm_temperature,
        chromadb_results_per_section: reportConfig.chromadb_results_per_section,
        ptm_detail_count: reportConfig.ptm_detail_count,
      };
      await onConfirm({
        analysis_context: analysisContext,
        analysis_options: optsForApi,
        rag_collections: useAllCollections ? null : (selectedCollectionIds.length > 0 ? selectedCollectionIds : null),
          report_options: {
          ...baseReportOpts,
          report_type: reportType,
          ptm_selection_mode: ptmSelectionMode,
          top_n_ptms: topNPtms,
          output_format: baseReportOpts.output_format ?? "md",
          analysis_mode: analysisMode,
          temporal_contract: temporalContract,
          research_questions: reportType === "co_scientist" ? [] : researchQuestions,
          co_scientist_integration: coScientistIntegrationMode !== "disabled" && coScientistSessionId
            ? { enabled: true, mode: coScientistIntegrationMode, session_id: coScientistSessionId, max_hypotheses: 2 }
            : { enabled: false },
          ...(llmModel ? (() => {
            const colonIdx = llmModel.indexOf(":");
            const [p, m] = colonIdx >= 0 ? [llmModel.slice(0, colonIdx), llmModel.slice(colonIdx + 1)] : ["ollama", llmModel];
            const presets = CLOUD_MODEL_PRESETS[p as CloudProvider];
            const model = isCloudProviderSelection(llmModel)
              ? (llmCloudModelVariant || (presets?.some((x) => x.id === m) ? m : presets?.[0]?.id))
              : m;
            return model ? { llm_model: model, llm_provider: p } : {};
          })() : {}),
          ...(ragEnrichmentLlmModel ? (() => {
            const colonIdx = ragEnrichmentLlmModel.indexOf(":");
            const [p, m] = colonIdx >= 0 ? [ragEnrichmentLlmModel.slice(0, colonIdx), ragEnrichmentLlmModel.slice(colonIdx + 1)] : ["ollama", ragEnrichmentLlmModel];
            const presets = CLOUD_MODEL_PRESETS[p as CloudProvider];
            const model = isCloudProviderSelection(ragEnrichmentLlmModel)
              ? (ragEnrichmentLlmCloudModelVariant || (presets?.some((x) => x.id === m) ? m : presets?.[0]?.id))
              : m;
            return model ? { rag_enrichment_llm_model: model, rag_enrichment_llm_provider: p } : {};
          })() : {}),
          report_config: reportConfigNested,
        },
      });
      onOpenChange(false);
    } catch (e) {
      console.error(e);
      const msg = e instanceof Error ? e.message : "알 수 없는 오류가 발생했습니다.";
      alert(`분석 실행에 실패했습니다: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (!order) return null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[900px] max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{duplicateMode ? "Duplicate Order — Options" : "Analysis Focus & Report Options"}</DialogTitle>
            <DialogDescription>
              {duplicateMode
                ? "Duplicate 시 분석 설정을 변경할 수 있습니다. 기존 Order 설정값이 표시됩니다."
                : "전체 또는 단계별 Re-run 시 반드시 이 화면에서 설정을 확인·수정한 뒤 Confirm 해주세요. 기존 Order 설정값이 표시됩니다."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6">
            {duplicateMode && (
              <div className="space-y-2">
                <Label className="text-sm font-semibold">New Order Name</Label>
                <Input
                  value={duplicateName}
                  onChange={(e) => onDuplicateNameChange?.(e.target.value)}
                  placeholder="Enter new order name"
                  className="text-sm"
                />
              </div>
            )}
            {/* Analysis Focus */}
            <div className="space-y-4">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <FlaskConical className="h-4 w-4" /> Analysis Focus
              </h4>
              <div
                className={cn(
                  "w-full rounded-lg border text-left transition-colors",
                  analysisOptions.quick_analysis
                    ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30"
                    : "hover:bg-muted/40",
                )}
              >
                <button
                  type="button"
                  onClick={() => setAnalysisOptions({
                    ...analysisOptions,
                    quick_analysis: !analysisOptions.quick_analysis,
                  })}
                  className="w-full p-3 text-left"
                >
                  <div className="flex items-start gap-2">
                    <Zap className={cn("h-4 w-4 mt-0.5", analysisOptions.quick_analysis ? "text-amber-700" : "text-muted-foreground")} />
                    <div>
                      <p className="text-xs font-medium">
                        Quick Analysis {analysisOptions.quick_analysis ? "(On · Custom / Exploratory)" : "(Off)"}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        Subset PR/PG before quantification. Same formulas. Not comparable to Full.
                      </p>
                    </div>
                  </div>
                </button>
                {analysisOptions.quick_analysis && (
                  <div className="border-t border-amber-300/60 px-3 pb-3">
                    <QuickAnalysisCustomFields
                      value={analysisOptions}
                      onChange={setAnalysisOptions}
                      compact
                    />
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setAnalysisMode("ptm_only")}
                  className={cn(
                    "flex flex-col items-start gap-1.5 rounded-lg border-2 p-3 text-left transition-all",
                    analysisMode === "ptm_only"
                      ? "border-primary bg-primary/5"
                      : "border-muted hover:border-muted-foreground/30",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <FlaskConical className={cn("h-4 w-4", analysisMode === "ptm_only" ? "text-primary" : "text-muted-foreground")} />
                    <span className="font-medium text-xs">PTM-Only</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground">RAG, hypothesis, literature report</p>
                </button>
                <button
                  type="button"
                  onClick={() => setAnalysisMode("ptm_nonptm_network")}
                  className={cn(
                    "flex flex-col items-start gap-1.5 rounded-lg border-2 p-3 text-left transition-all",
                    analysisMode === "ptm_nonptm_network"
                      ? "border-primary bg-primary/5"
                      : "border-muted hover:border-muted-foreground/30",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Network className={cn("h-4 w-4", analysisMode === "ptm_nonptm_network" ? "text-primary" : "text-muted-foreground")} />
                    <span className="font-medium text-xs">PTM + Network</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground">KEA3, STRING-DB, network</p>
                </button>
              </div>
              <div className="space-y-2">
                <Label className="text-xs">Temporal Contract</Label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setTemporalContract("dynamics_v1")}
                    className={cn(
                      "flex flex-col items-start gap-1.5 rounded-lg border-2 p-3 text-left transition-all",
                      temporalContract === "dynamics_v1"
                        ? "border-primary bg-primary/5"
                        : "border-muted hover:border-muted-foreground/30",
                    )}
                  >
                    <span className="font-medium text-xs">Dynamics v1</span>
                    <p className="text-[10px] text-muted-foreground">group_share, sub-patterns, P1/Atlas</p>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTemporalContract("legacy")}
                    className={cn(
                      "flex flex-col items-start gap-1.5 rounded-lg border-2 p-3 text-left transition-all",
                      temporalContract === "legacy"
                        ? "border-primary bg-primary/5"
                        : "border-muted hover:border-muted-foreground/30",
                    )}
                  >
                    <span className="font-medium text-xs">Legacy</span>
                    <p className="text-[10px] text-muted-foreground">pre-2026-08 heatmap and report path</p>
                  </button>
                </div>
              </div>
              <div className="grid gap-2">
                <Label className="text-xs">Cell Type</Label>
                <Input
                  value={analysisContext.cell_type}
                  onChange={(e) => setAnalysisContext((p) => ({ ...p, cell_type: e.target.value }))}
                  placeholder="e.g., C2C12 myotubes"
                  className="h-8 text-sm"
                />
                <Label className="text-xs">Treatment</Label>
                <Input
                  value={analysisContext.treatment}
                  onChange={(e) => setAnalysisContext((p) => ({ ...p, treatment: e.target.value }))}
                  placeholder="e.g., Irisin stimulation"
                  className="h-8 text-sm"
                />
                <Label className="text-xs">Time Points</Label>
                <Input
                  value={analysisContext.time_points}
                  onChange={(e) => setAnalysisContext((p) => ({ ...p, time_points: e.target.value }))}
                  placeholder="e.g., 0, 5, 15, 30 min"
                  className="h-8 text-sm"
                />
                <Label className="text-xs">Biological Question</Label>
                <Textarea
                  value={analysisContext.biological_question}
                  onChange={(e) => setAnalysisContext((p) => ({ ...p, biological_question: e.target.value }))}
                  placeholder="e.g., What signaling pathways are activated?"
                  rows={2}
                  className="text-sm"
                />
                <Label className="text-xs">Special Conditions</Label>
                <Input
                  value={analysisContext.special_conditions}
                  onChange={(e) => setAnalysisContext((p) => ({ ...p, special_conditions: e.target.value }))}
                  placeholder="e.g., hypoxia, serum starvation, knockdown"
                  className="h-8 text-sm"
                />
              </div>
              <div className="flex items-center gap-3">
                <Label className="text-xs">Analysis Options (protein selection)</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5"
                  onClick={() => setAnalysisModalOpen(true)}
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  Configure
                </Button>
              </div>
            </div>

            {/* Report Options */}
            <div className="space-y-4">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <Brain className="h-4 w-4" /> Report Options
              </h4>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <Label className="text-xs">Report Type</Label>
                  <Select
                    value={reportType}
                    onValueChange={(value) => {
                      setReportType(value);
                      if (value === "co_scientist") {
                        setResearchQuestions([]);
                        setNewQuestion("");
                      }
                    }}
                  >
                    <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="comprehensive">Standard Report</SelectItem>
                      <SelectItem value="extended">Extended (+ Drug Repositioning)</SelectItem>
                      <SelectItem value="co_scientist">Data-Grounded Analysis (데이터 기반 가설·검증)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {reportType === "co_scientist" && (
                  <div className="rounded-md border border-blue-500/30 bg-blue-500/10 p-2.5 text-[10px] text-blue-300 space-y-1">
                    <p className="font-semibold text-blue-200">🔬 Data-Grounded Analysis</p>
                    <p>AI가 4개 데이터 소스를 통합하여 가설을 자동 생성하고 실험 데이터로 직접 검증합니다:</p>
                    <ul className="list-disc list-inside space-y-0.5 text-blue-300/80">
                      <li>Temporal PTM Trajectory Clustering — complete-case PTM trajectory의 구조적 군집화</li>
                      <li>Local Co-membership Transition — 고정 cluster 내 sampled-interval pattern annotation</li>
                      <li>Self-PTM annotation — regulatory-site interpretation에 필요한 추가 evidence 확인</li>
                      <li>TMM Contribution — candidate substrate footprint의 many-to-many allocation</li>
                    </ul>
                    <p className="text-blue-200/70">검증된 가설은 레포트에 수치 포함 자동 삽입됩니다 (예: "21/28 substrates peak at 1h")</p>
                  </div>
                )}
                <div className="space-y-1.5 rounded-md border border-violet-500/25 bg-violet-500/5 p-2.5">
                  <Label className="text-xs flex items-center gap-1"><FlaskConical className="h-3.5 w-3.5" /> External Co-Scientist Discussion</Label>
                  <Select value={coScientistIntegrationMode} onValueChange={(value) => setCoScientistIntegrationMode(value as typeof coScientistIntegrationMode)}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="disabled" className="text-xs">Do not include external Co-Scientist</SelectItem>
                      <SelectItem value="addendum" className="text-xs">Hypothesis &amp; Validation Addendum</SelectItem>
                      <SelectItem value="enhanced_discussion" className="text-xs">Enhanced Discussion (opt-in)</SelectItem>
                    </SelectContent>
                  </Select>
                  {coScientistIntegrationMode !== "disabled" && (
                    <>
                      <Select value={coScientistSessionId || "__none__"} onValueChange={(value) => setCoScientistSessionId(value === "__none__" ? "" : value)}>
                        <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Select completed session" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__" className="text-xs">No session selected</SelectItem>
                          {coScientistSessions.map((session) => (
                            <SelectItem key={session.session_id} value={session.session_id} className="text-xs">
                              {session.session_id.slice(0, 10)} · {session.research_goal?.slice(0, 46) || "Untitled research"}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className="text-[10px] text-muted-foreground leading-tight">
                        {coScientistSessionsLoading
                          ? "Loading completed Co-Scientist sessions…"
                          : coScientistSessions.length
                          ? "Only a selected completed session with a quality-gated Discussion Evidence Packet can be used."
                          : "No completed session is available. Run external Co-Scientist from this order first."}
                      </p>
                    </>
                  )}
                  <p className="text-[10px] text-muted-foreground leading-tight">
                    Addendum preserves external hypotheses separately. Enhanced Discussion uses at most two re-verified candidates with limitations; Results remain platform data only.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">PTM Selection Mode</Label>
                  <Select value={ptmSelectionMode} onValueChange={(v) => setPtmSelectionMode(v as typeof ptmSelectionMode)}>
                    <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="de_novo_regulated">De novo + Regulated</SelectItem>
                      <SelectItem value="de_novo">De novo only</SelectItem>
                      <SelectItem value="regulated">Regulated only</SelectItem>
                      <SelectItem value="minor">Minor only</SelectItem>
                      <SelectItem value="all">All PTMs</SelectItem>
                      <SelectItem value="top_n">Top N by ranking score</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-[10px] text-muted-foreground">
                    {ptmSelectionMode === "de_novo_regulated" && "Regulated ∪ High/Moderate de novo. LOD-relative rank, not pseudo-Log2FC."}
                    {ptmSelectionMode === "de_novo" && "No-control PTMs only (Log2FC=NA)"}
                    {ptmSelectionMode === "regulated" && "Statistically significant PTMs only"}
                    {ptmSelectionMode === "minor" && "Neither de novo nor regulated"}
                    {ptmSelectionMode === "all" && "All PTMs — may increase analysis time"}
                    {ptmSelectionMode === "top_n" && `Top ${topNPtms} by ranking score`}
                  </p>
                  {ptmSelectionMode === "top_n" && (
                    <div className="flex items-center gap-2 mt-1.5">
                      <Label className="text-[10px] whitespace-nowrap">Top N:</Label>
                      <Input
                        type="number"
                        min={10}
                        max={500}
                        value={topNPtms}
                        onChange={(e) => setTopNPtms(Math.max(10, Math.min(500, parseInt(e.target.value) || 50)))}
                        className="w-20 h-7 text-xs"
                      />
                      <span className="text-[10px] text-muted-foreground">10–500</span>
                    </div>
                  )}
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs flex items-center gap-1">
                  <Database className="h-3.5 w-3.5" /> LLM Model (RAG Enrichment)
                </Label>
                <Select
                  value={ragEnrichmentLlmModel || "__default__"}
                  onValueChange={(v) => {
                    setRagEnrichmentLlmModel(v === "__default__" ? "" : v);
                    if (v !== "__default__" && isCloudProviderSelection(v)) {
                      const [, m] = v.split(":", 2);
                      const p = v.split(":")[0] as CloudProvider;
                      const presets = CLOUD_MODEL_PRESETS[p];
                      const validId = presets?.some((x) => x.id === m) ? m : presets?.[0]?.id || "";
                      setRagEnrichmentLlmCloudModelVariant(validId);
                    } else {
                      setRagEnrichmentLlmCloudModelVariant("");
                    }
                  }}
                >
                  <SelectTrigger className="h-8"><SelectValue placeholder={`Default (Report model)`} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">Default (Report model)</SelectItem>
                    {llmModels.map((m) => {
                      const val = `${m.provider}:${m.model_id}`;
                      return <SelectItem key={val} value={val}>{m.name} ({m.provider})</SelectItem>;
                    })}
                  </SelectContent>
                </Select>
                {isCloudProviderSelection(ragEnrichmentLlmModel || "") && (
                  <div className="flex items-center gap-2 pl-2 border-l-2 border-muted">
                    <Label className="text-xs shrink-0">세부 모델</Label>
                    <Select
                      value={ragEnrichmentLlmCloudModelVariant || CLOUD_MODEL_PRESETS[ragEnrichmentLlmModel.split(":")[0] as CloudProvider]?.[0]?.id}
                      onValueChange={setRagEnrichmentLlmCloudModelVariant}
                    >
                      <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {CLOUD_MODEL_PRESETS[ragEnrichmentLlmModel.split(":")[0] as CloudProvider]?.map((x) => (
                          <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <p className="text-[10px] text-muted-foreground">
                  RAG Enrichment 단계(Abstract/키나제 예측 등). 미선택 시 Report 모델을 사용합니다.
                </p>
                {isRagModelTooSmall(ragEnrichmentLlmModel) && (
                  <div className="flex items-start gap-1.5 p-1.5 rounded bg-amber-500/10 border border-amber-500/30">
                    <p className="text-[10px] text-amber-500">
                      ⚠️ {getModelSizeB(ragEnrichmentLlmModel)}B 모델은 최소 권장({MIN_RAG_MODEL_SIZE_B}B) 미만입니다. 서버에서 qwen2.5:14b로 자동 대체됩니다.
                    </p>
                  </div>
                )}
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">LLM Model (Report Generation)</Label>
                <Select
                  value={llmModel || "__default__"}
                  onValueChange={(v) => {
                    setLlmModel(v === "__default__" ? "" : v);
                    if (v !== "__default__" && isCloudProviderSelection(v)) {
                      const [, m] = v.split(":", 2);
                      const p = v.split(":")[0] as CloudProvider;
                      const presets = CLOUD_MODEL_PRESETS[p];
                      const validId = presets?.some((x) => x.id === m) ? m : presets?.[0]?.id || "";
                      setLlmCloudModelVariant(validId);
                    } else {
                      setLlmCloudModelVariant("");
                    }
                  }}
                >
                  <SelectTrigger className="h-8"><SelectValue placeholder={`Default (${defaultLlmModel || "auto"})`} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">Default ({defaultLlmModel || "auto"})</SelectItem>
                    {llmModels.map((m) => {
                      const val = `${m.provider}:${m.model_id}`;
                      return <SelectItem key={val} value={val}>{m.name} ({m.provider})</SelectItem>;
                    })}
                  </SelectContent>
                </Select>
                {isCloudProviderSelection(llmModel || "") && (
                  <div className="flex items-center gap-2 pl-2 border-l-2 border-muted">
                    <Label className="text-xs shrink-0">세부 모델</Label>
                    <Select
                      value={llmCloudModelVariant || CLOUD_MODEL_PRESETS[llmModel.split(":")[0] as CloudProvider]?.[0]?.id}
                      onValueChange={setLlmCloudModelVariant}
                    >
                      <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {CLOUD_MODEL_PRESETS[llmModel.split(":")[0] as CloudProvider]?.map((x) => (
                          <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>
              {/* RAG Collection Selection */}
              <div className="space-y-1.5">
                <Label className="text-xs flex items-center gap-1">
                  <Database className="h-3.5 w-3.5" /> RAG Literature Collections
                </Label>
                <p className="text-[10px] text-muted-foreground">
                  분석에 참조할 문헌 컬렉션을 선택합니다. 전체 선택 시 모든 활성 컬렉션이 사용됩니다.
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className={cn(
                      "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                      useAllCollections
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-muted-foreground/25 hover:border-muted-foreground/50"
                    )}
                    onClick={() => {
                      setUseAllCollections(true);
                      setSelectedCollectionIds([]);
                    }}
                  >
                    {useAllCollections ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                    전체 사용 ({ragCollections.length}개)
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                      !useAllCollections
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-muted-foreground/25 hover:border-muted-foreground/50"
                    )}
                    onClick={() => setUseAllCollections(false)}
                  >
                    {!useAllCollections ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                    직접 선택
                  </button>
                </div>
                {!useAllCollections && (
                  <div className="rounded-lg border max-h-[180px] overflow-y-auto">
                    {ragCollectionsLoading ? (
                      <div className="flex items-center justify-center py-4">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    ) : ragCollections.length === 0 ? (
                      <p className="text-xs text-muted-foreground py-3 text-center">등록된 활성 컬렉션이 없습니다.</p>
                    ) : (
                      <div className="divide-y">
                        <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30">
                          <span className="text-[10px] font-medium text-muted-foreground">
                            {selectedCollectionIds.length}개 선택됨
                          </span>
                          <div className="flex gap-2">
                            <button
                              type="button"
                              className="text-[10px] text-primary hover:underline"
                              onClick={() => setSelectedCollectionIds(ragCollections.map((c) => c.id))}
                            >
                              전체 선택
                            </button>
                            <button
                              type="button"
                              className="text-[10px] text-muted-foreground hover:underline"
                              onClick={() => setSelectedCollectionIds([])}
                            >
                              선택 해제
                            </button>
                          </div>
                        </div>
                        {ragCollections.map((c) => {
                          const isSelected = selectedCollectionIds.includes(c.id);
                          return (
                            <button
                              key={c.id}
                              type="button"
                              className={cn(
                                "w-full flex items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/50",
                                isSelected && "bg-primary/5"
                              )}
                              onClick={() => {
                                setSelectedCollectionIds((prev) =>
                                  isSelected
                                    ? prev.filter((id) => id !== c.id)
                                    : [...prev, c.id]
                                );
                              }}
                            >
                              {isSelected ? (
                                <CheckSquare className="h-3.5 w-3.5 text-primary shrink-0" />
                              ) : (
                                <Square className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                              )}
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-xs font-medium truncate">{c.name}</span>
                                  <Badge variant="secondary" className="text-[9px] shrink-0">{c.tier}</Badge>
                                </div>
                                {c.description && (
                                  <p className="text-[10px] text-muted-foreground truncate mt-0.5">{c.description}</p>
                                )}
                              </div>
                              <span className="text-[10px] text-muted-foreground shrink-0">
                                {c.document_count} docs / {c.chunk_count} chunks
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {reportType !== "co_scientist" && (
              <div className="space-y-1.5">
                <Label className="text-xs flex items-center gap-1">
                  <MessageSquare className="h-3.5 w-3.5" /> Research Questions (optional)
                </Label>
                <div className="space-y-2">
                  {researchQuestions.map((q, i) => (
                    <div key={i} className="flex gap-2 group items-start">
                      <span className="text-[10px] text-muted-foreground mt-2 w-4 shrink-0">Q{i + 1}</span>
                      <AutoResizeTextarea
                        value={q}
                        onChange={(e) =>
                          setResearchQuestions(
                            researchQuestions.map((qq, j) => (j === i ? e.target.value : qq))
                          )
                        }
                        className="flex-1 min-w-0 text-xs"
                        placeholder="Research question..."
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 shrink-0 mt-1 opacity-0 group-hover:opacity-100"
                        onClick={() => setResearchQuestions(researchQuestions.filter((_, j) => j !== i))}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                  <div className="flex gap-2 items-start">
                    <AutoResizeTextarea
                      value={newQuestion}
                      onChange={(e) => setNewQuestion(e.target.value)}
                      placeholder="Add research question..."
                      className="flex-1 min-w-0 text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey && newQuestion.trim()) {
                          e.preventDefault();
                          setResearchQuestions([...researchQuestions, newQuestion.trim()]);
                          setNewQuestion("");
                        }
                      }}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="h-8 w-8 shrink-0 mt-1"
                      disabled={!newQuestion.trim()}
                      onClick={() => {
                        if (newQuestion.trim()) {
                          setResearchQuestions([...researchQuestions, newQuestion.trim()]);
                          setNewQuestion("");
                        }
                      }}
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
              )}
            </div>

            {/* Advanced Report Settings */}
            <div className="rounded-lg border">
              <button
                type="button"
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50 transition-colors"
                onClick={() => setAdvancedOpen(!advancedOpen)}
              >
                <span className="flex items-center gap-2">
                  <Settings2 className="h-4 w-4" />
                  Advanced Report Settings
                  <span className="text-xs text-muted-foreground font-normal">(optional)</span>
                </span>
                {advancedOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
              {advancedOpen && (
                <div className="border-t px-4 pb-4 space-y-5">
                  {/* Reset button */}
                  <div className="flex justify-end pt-3">
                    <Button type="button" variant="ghost" size="sm" className="gap-1 text-xs"
                      onClick={() => setReportConfig({
                        md_summary_max_chars: 12000, section_chars_limit: 1500,
                        llm_tokens_abstract: 4096, llm_tokens_introduction: 12288,
                        llm_tokens_results: 16384, llm_tokens_time_course: 8192,
                        llm_tokens_discussion: 12288, llm_tokens_conclusion: 6144,
                        llm_temperature: 0.6, chromadb_results_per_section: 10,
                        ptm_detail_count: 30,
                      })}>
                      <RotateCcw className="h-3 w-3" /> Reset to Defaults
                    </Button>
                  </div>

                  {/* Context Extraction */}
                  <div className="space-y-3">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Context Extraction</p>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label className="text-xs">MD Summary Max Characters</Label>
                        <Input type="number" value={reportConfig.md_summary_max_chars}
                          onChange={(e) => setReportConfig({ ...reportConfig, md_summary_max_chars: parseInt(e.target.value) || 12000 })}
                          min={3000} max={50000} step={1000} className="h-8 text-xs" />
                        <p className="text-[10px] text-muted-foreground">Max chars from comprehensive MD report for LLM context</p>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">Section Characters Limit</Label>
                        <Input type="number" value={reportConfig.section_chars_limit}
                          onChange={(e) => setReportConfig({ ...reportConfig, section_chars_limit: parseInt(e.target.value) || 1500 })}
                          min={500} max={5000} step={500} className="h-8 text-xs" />
                        <p className="text-[10px] text-muted-foreground">Max chars per section keyword match</p>
                      </div>
                    </div>
                  </div>

                  {/* LLM Token Limits */}
                  <div className="space-y-3">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">LLM Token Limits (per section)</p>
                    <div className="grid grid-cols-3 gap-3">
                      {([
                        { key: "llm_tokens_abstract", label: "Abstract", def: 4096 },
                        { key: "llm_tokens_introduction", label: "Introduction", def: 12288 },
                        { key: "llm_tokens_results", label: "Results", def: 16384 },
                        { key: "llm_tokens_time_course", label: "Time-Course", def: 8192 },
                        { key: "llm_tokens_discussion", label: "Discussion", def: 12288 },
                        { key: "llm_tokens_conclusion", label: "Conclusion", def: 6144 },
                      ] as const).map(({ key, label, def }) => (
                        <div key={key} className="space-y-1">
                          <Label className="text-xs">{label}</Label>
                          <Input type="number" value={reportConfig[key]}
                            onChange={(e) => setReportConfig({ ...reportConfig, [key]: parseInt(e.target.value) || def })}
                            min={1024} max={65536} step={1024} className="h-8 text-xs" />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* LLM & Literature */}
                  <div className="space-y-3">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">LLM & Literature</p>
                    <div className="grid grid-cols-3 gap-3">
                      <div className="space-y-1">
                        <Label className="text-xs">LLM Temperature</Label>
                        <Input type="number" value={reportConfig.llm_temperature}
                          onChange={(e) => setReportConfig({ ...reportConfig, llm_temperature: parseFloat(e.target.value) || 0.6 })}
                          min={0} max={1} step={0.1} className="h-8 text-xs" />
                        <p className="text-[10px] text-muted-foreground">0.0 = deterministic, 1.0 = creative</p>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">ChromaDB Results/Section</Label>
                        <Input type="number" value={reportConfig.chromadb_results_per_section}
                          onChange={(e) => setReportConfig({ ...reportConfig, chromadb_results_per_section: parseInt(e.target.value) || 10 })}
                          min={3} max={30} step={1} className="h-8 text-xs" />
                        <p className="text-[10px] text-muted-foreground">Vector search results per section</p>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">PTM Detail Count</Label>
                        <Input type="number" value={reportConfig.ptm_detail_count}
                          onChange={(e) => setReportConfig({ ...reportConfig, ptm_detail_count: parseInt(e.target.value) || 30 })}
                          min={5} max={100} step={5} className="h-8 text-xs" />
                        <p className="text-[10px] text-muted-foreground">Top PTMs with full detail in prompts</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <div className="flex flex-wrap items-center gap-2 mr-auto">
              {order?.kinase_analysis_data && (order.kinase_analysis_data as any)?.kinase_modules?.length > 0 && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-xs">
                  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Kinase analysis included ({(order.kinase_analysis_data as any).kinase_modules.length} modules)
                </div>
              )}
              {order?.temporal_evidence_readiness?.status === "ready" ? (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-sky-500/10 border border-sky-500/20 text-sky-700 dark:text-sky-300 text-xs">
                  <CheckSquare className="h-3 w-3" />
                  Temporal evidence ready
                </div>
              ) : order?.temporal_evidence_readiness?.status === "missing" ? (
                <div className="flex max-w-[430px] items-center gap-1.5 px-2 py-1 rounded-md bg-amber-500/10 border border-amber-500/25 text-amber-700 dark:text-amber-300 text-xs">
                  <Zap className="h-3 w-3 shrink-0" />
                  Temporal evidence will be prepared before Report generation
                </div>
              ) : null}
            </div>
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={handleConfirm} disabled={submitting}>
              {submitting ? "Saving..." : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AnalysisOptionsModal
        open={analysisModalOpen}
        onOpenChange={setAnalysisModalOpen}
        value={analysisOptions}
        onChange={setAnalysisOptions}
      />
    </>
  );
}
