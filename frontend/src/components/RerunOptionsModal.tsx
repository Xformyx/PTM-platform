import { useState, useEffect } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Brain, BookOpen, FlaskConical, MessageSquare, Network, Plus, SlidersHorizontal, X, ChevronDown, ChevronUp, Settings2, RotateCcw } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import AnalysisOptionsModal from "./AnalysisOptionsModal";
import type { AnalysisOptions } from "@/lib/types";
import { DEFAULT_ANALYSIS_OPTIONS } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Order {
  id: number;
  order_code: string;
  analysis_context?: Record<string, unknown>;
  analysis_options?: Record<string, unknown>;
  report_options?: Record<string, unknown>;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  order: Order | null;
  ollamaModels: string[];
  defaultLlmModel: string;
  onConfirm: (opts: {
    analysis_context: Record<string, unknown>;
    analysis_options: Record<string, unknown>;
    report_options: Record<string, unknown>;
  }) => void | Promise<void>;
  confirmLabel?: string;
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
  ollamaModels,
  defaultLlmModel,
  onConfirm,
  confirmLabel = "Confirm & Run",
}: Props) {
  const [analysisContext, setAnalysisContext] = useState<Record<string, string>>(DEFAULT_CONTEXT);
  const [analysisMode, setAnalysisMode] = useState<"ptm_only" | "ptm_nonptm_network">("ptm_only");
  const [analysisOptions, setAnalysisOptions] = useState<AnalysisOptions>({ ...DEFAULT_ANALYSIS_OPTIONS });
  const [analysisModalOpen, setAnalysisModalOpen] = useState(false);
  const [reportType, setReportType] = useState("comprehensive");
  const [topNptms, setTopNptms] = useState(20);
  const [llmModel, setLlmModel] = useState("");
  const [ragLlmModel, setRagLlmModel] = useState("");
  const [researchQuestions, setResearchQuestions] = useState<string[]>([]);
  const [newQuestion, setNewQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [reportConfig, setReportConfig] = useState({
    md_summary_max_chars: 12000, section_chars_limit: 1500,
    llm_tokens_abstract: 4096, llm_tokens_introduction: 12288,
    llm_tokens_results: 16384, llm_tokens_time_course: 8192,
    llm_tokens_discussion: 12288, llm_tokens_conclusion: 6144,
    llm_temperature: 0.6, chromadb_results_per_section: 10,
    ptm_detail_count: 30,
  });

  // Load existing order values whenever modal opens — preserve user's previous settings
  useEffect(() => {
    if (open && order) {
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
      setReportType(typeof ro.report_type === "string" ? ro.report_type : "comprehensive");
      const topN = ro.top_n_ptms;
      setTopNptms(typeof topN === "number" && !isNaN(topN) ? topN : 20);
      setLlmModel(typeof ro.llm_model === "string" ? ro.llm_model : "");
      setRagLlmModel(typeof ro.rag_llm_model === "string" ? ro.rag_llm_model : "");
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
  }, [open, order]);

  const handleConfirm = async () => {
    if (!order) return;
    setSubmitting(true);
    try {
      const optsForApi: Record<string, unknown> = {
        mode: analysisOptions.mode,
        topN: analysisOptions.topN,
        log2fcThreshold: analysisOptions.log2fcThreshold,
        proteinCount: analysisOptions.proteinCount,
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
        report_options: {
          ...baseReportOpts,
          report_type: reportType,
          top_n_ptms: topNptms,
          output_format: baseReportOpts.output_format ?? "md",
          analysis_mode: analysisMode,
          research_questions: researchQuestions,
          ...(llmModel ? { llm_model: llmModel, llm_provider: "ollama" as const } : {}),
          ...(ragLlmModel ? { rag_llm_model: ragLlmModel } : {}),
          report_config: reportConfigNested,
        },
      });
      onOpenChange(false);
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  if (!order) return null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Analysis Focus & Report Options</DialogTitle>
            <DialogDescription>
              전체 또는 단계별 Re-run 시 반드시 이 화면에서 설정을 확인·수정한 뒤 Confirm 해주세요.
              기존 Order 설정값이 표시됩니다.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6">
            {/* Analysis Focus */}
            <div className="space-y-4">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <FlaskConical className="h-4 w-4" /> Analysis Focus
              </h4>
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
                  <Select value={reportType} onValueChange={setReportType}>
                    <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="comprehensive">Standard Report</SelectItem>
                      <SelectItem value="extended">Extended (+ Drug Repositioning)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Top N PTMs</Label>
                  <Input
                    type="number"
                    value={topNptms}
                    onChange={(e) => setTopNptms(parseInt(e.target.value) || 20)}
                    min={5}
                    max={100}
                    className="h-8"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">LLM Model (Report Generation)</Label>
                <Select
                  value={llmModel || "__default__"}
                  onValueChange={(v) => setLlmModel(v === "__default__" ? "" : v)}
                >
                  <SelectTrigger className="h-8"><SelectValue placeholder={`Default (${defaultLlmModel || "auto"})`} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">Default ({defaultLlmModel || "auto"})</SelectItem>
                    {ollamaModels.map((m) => (
                      <SelectItem key={m} value={m}>{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">LLM Model (Paper Read)</Label>
                <Select
                  value={ragLlmModel || "__default__"}
                  onValueChange={(v) => setRagLlmModel(v === "__default__" ? "" : v)}
                >
                  <SelectTrigger className="h-8"><SelectValue placeholder={`Default (${defaultLlmModel || "auto"})`} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">Default ({defaultLlmModel || "auto"})</SelectItem>
                    {ollamaModels.map((m) => (
                      <SelectItem key={m} value={m}>{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs flex items-center gap-1">
                  <MessageSquare className="h-3.5 w-3.5" /> Research Questions (optional)
                </Label>
                <div className="space-y-2">
                  {researchQuestions.map((q, i) => (
                    <div key={i} className="flex gap-2 group">
                      <span className="text-[10px] text-muted-foreground mt-1.5 w-4 shrink-0">Q{i + 1}</span>
                      <div className="flex-1 rounded border px-2 py-1.5 text-xs bg-muted/30">{q}</div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100"
                        onClick={() => setResearchQuestions(researchQuestions.filter((_, j) => j !== i))}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                  <div className="flex gap-2">
                    <Input
                      value={newQuestion}
                      onChange={(e) => setNewQuestion(e.target.value)}
                      placeholder="Add research question..."
                      className="h-8 text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && newQuestion.trim()) {
                          setResearchQuestions([...researchQuestions, newQuestion.trim()]);
                          setNewQuestion("");
                        }
                      }}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="h-8 w-8 shrink-0"
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
