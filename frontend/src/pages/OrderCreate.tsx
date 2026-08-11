import { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check, Upload, AlertCircle, ArrowLeft, ArrowRight, Loader2,
  FileSpreadsheet, Regex, Trash2, SlidersHorizontal, Brain,
  Plus, X, MessageSquare, Network, FlaskConical, BookOpen,
  ChevronDown, ChevronUp, Settings2, RotateCcw, GitMerge, Copy,
  Database, CheckSquare, Square,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AutoResizeTextarea } from "@/components/ui/auto-resize-textarea";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { AnalysisOptions } from "@/lib/types";
import { DEFAULT_ANALYSIS_OPTIONS } from "@/lib/types";
import AnalysisOptionsModal from "@/components/AnalysisOptionsModal";
import { CLOUD_MODEL_PRESETS, type CloudProvider } from "@/lib/llm-models";

const STEPS = ["Project & Files", "Sample Config", "Analysis Focus", "Report Options"];

const CLOUD_PROVIDERS = ["gemini", "openai", "anthropic"] as const;
function isCloudProviderSelection(val: string): boolean {
  const p = val?.split(":")[0];
  return !!(p && CLOUD_PROVIDERS.includes(p as any));
}

/** Minimum model size (in billions) for RAG Enrichment to ensure quality */
const MIN_RAG_MODEL_SIZE_B = 14;

/** Extract model size in billions from model name (e.g., 'qwen2.5:14b' -> 14) */
function getModelSizeB(modelName: string): number {
  if (!modelName) return 0;
  // Cloud providers are unrestricted
  if (isCloudProviderSelection(modelName)) return 0;
  const lower = modelName.toLowerCase();
  // Parse size tag after colon (Ollama format: 'name:sizeb')
  if (lower.includes(":")) {
    const tag = lower.split(":")[1];
    const m = tag?.match(/^(\d+(?:\.\d+)?)b/);
    if (m) return Math.floor(parseFloat(m[1]));
  }
  // Fallback: find NNb pattern
  const m = lower.match(/[:\-_](\d+(?:\.\d+)?)b/);
  if (m) return Math.floor(parseFloat(m[1]));
  return 0;
}

/** Check if selected RAG model is below minimum size */
function isRagModelTooSmall(modelName: string): boolean {
  if (!modelName) return false; // default is fine
  const size = getModelSizeB(modelName);
  return size > 0 && size < MIN_RAG_MODEL_SIZE_B;
}

// ── Types ────────────────────────────────────────────────────────────────────

interface SampleEntry {
  filename: string;
  shortname: string;
  condition: string;
  group: string;
  replicate: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const METADATA_COLUMNS = new Set([
  "Protein.Group", "Protein.Ids", "Protein.Names", "Genes",
  "First.Protein.Description", "Proteotypic", "Stripped.Sequence",
  "Modified.Sequence", "Precursor.Charge", "Precursor.Id",
]);

function getBasename(path: string): string {
  const parts = path.split(/[\\\/]/);
  return parts[parts.length - 1] || path;
}

async function readTsvHeaders(file: File): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const slice = file.slice(0, 200 * 1024);
    reader.onload = () => {
      const text = reader.result as string;
      const firstLine = text.split("\n")[0].trim();
      resolve(firstLine.split("\t"));
    };
    reader.onerror = reject;
    reader.readAsText(slice);
  });
}

function extractSampleColumns(headers: string[]): string[] {
  return headers.filter((h) => !METADATA_COLUMNS.has(h.trim()) && h.trim() !== "");
}

function autoParseColumns(
  columns: string[],
  pattern: string,
  controlKw: string,
): SampleEntry[] {
  let regex: RegExp;
  try {
    regex = new RegExp(pattern);
  } catch {
    return columns.map((col) => ({
      filename: col, shortname: getBasename(col),
      condition: "", group: "Treatment", replicate: 1,
    }));
  }

  return columns.map((col) => {
    const basename = getBasename(col);
    const match = basename.match(regex);
    if (match && match.length >= 3) {
      const condLabel = match[1];
      const rep = parseInt(match[2]) || 1;
      const isCtrl = condLabel.toLowerCase() === controlKw.toLowerCase();
      return {
        filename: col, shortname: basename,
        condition: `${condLabel}_${rep}`,
        group: isCtrl ? "Control" : "Treatment",
        replicate: rep,
      };
    }
    return { filename: col, shortname: basename, condition: "", group: "Treatment", replicate: 1 };
  });
}

// ── File Drop Zone ───────────────────────────────────────────────────────────

function FileDropZone({
  label, accept, file, hint, onChange,
}: {
  label: string; accept: string; file: File | null; hint?: string;
  onChange: (f: File | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      <div
        className={cn(
          "relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors cursor-pointer",
          file ? "border-primary/50 bg-primary/5" : "border-muted-foreground/25 hover:border-muted-foreground/50",
        )}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef} type="file" accept={accept} className="sr-only"
          onChange={(e) => onChange(e.target.files?.[0] || null)}
        />
        <Upload className="h-5 w-5 text-muted-foreground mb-2" />
        {file ? (
          <p className="text-sm font-medium text-primary">{file.name}</p>
        ) : (
          <p className="text-sm text-muted-foreground">Click to select file</p>
        )}
      </div>
    </div>
  );
}

// ── Slide Animation ──────────────────────────────────────────────────────────

const slideVariants = {
  enter: (dir: number) => ({ x: dir > 0 ? 60 : -60, opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (dir: number) => ({ x: dir > 0 ? -60 : 60, opacity: 0 }),
};

// ── Main Component ───────────────────────────────────────────────────────────

export default function OrderCreate() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Step 0: Project & Files
  const [form, setForm] = useState({
    project_name: "", ptm_type: "phosphorylation", species: "mouse",
    cell_type: "", treatment: "", time_points: "", biological_question: "", special_conditions: "",
    report_type: "comprehensive", ptm_selection_mode: "de_novo_regulated" as "top_n" | "de_novo" | "regulated" | "de_novo_regulated" | "minor" | "all", top_n_ptms: 50, llm_model: "", rag_enrichment_llm_model: "",
    analysis_mode: "ptm_only" as "ptm_only" | "ptm_nonptm_network" | "cross_talk",
    secondary_ptm_type: "ubiquitylation",
  });
  const [researchQuestions, setResearchQuestions] = useState<string[]>([]);
  const [newQuestion, setNewQuestion] = useState("");

  // Treatment typo detection
  const [treatmentSuggestions, setTreatmentSuggestions] = useState<Array<{
    original_token: string; suggested: string; canonical: string;
    confidence: string; distance: number;
  }>>([]);
  const [treatmentSuggestionsVisible, setTreatmentSuggestionsVisible] = useState(false);
  const treatmentDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleTreatmentChange = (value: string) => {
    setForm({ ...form, treatment: value });
    if (treatmentDebounceRef.current) clearTimeout(treatmentDebounceRef.current);
    if (!value.trim()) { setTreatmentSuggestions([]); setTreatmentSuggestionsVisible(false); return; }
    treatmentDebounceRef.current = setTimeout(async () => {
      try {
        const res = await api.post<{ suggestions: typeof treatmentSuggestions }>(
          "/orders/validate-treatment", { treatment: value }
        );
        if (res.suggestions && res.suggestions.length > 0) {
          setTreatmentSuggestions(res.suggestions);
          setTreatmentSuggestionsVisible(true);
        } else {
          setTreatmentSuggestions([]);
          setTreatmentSuggestionsVisible(false);
        }
      } catch { /* ignore */ }
    }, 800);
  };

  const applyTreatmentSuggestion = (original: string, suggested: string) => {
    const updated = form.treatment.replace(new RegExp(original, 'gi'), suggested);
    setForm({ ...form, treatment: updated });
    setTreatmentSuggestions([]);
    setTreatmentSuggestionsVisible(false);
  };
  const [llmModels, setLlmModels] = useState<{ provider: string; model_id: string; name: string }[]>([]);
  const [defaultLlmModel, setDefaultLlmModel] = useState("");
  const [llmCloudModelVariant, setLlmCloudModelVariant] = useState("");
  const [ragEnrichmentLlmCloudModelVariant, setRagEnrichmentLlmCloudModelVariant] = useState("");
  const [files, setFiles] = useState<{
    pr_matrix: File | null; pg_matrix: File | null; config_file: File | null;
  }>({ pr_matrix: null, pg_matrix: null, config_file: null });
  const [secondaryFiles, setSecondaryFiles] = useState<{
    pr_matrix: File | null; pg_matrix: File | null;
  }>({ pr_matrix: null, pg_matrix: null });

  // Step 1: Sample Config
  const [sampleColumns, setSampleColumns] = useState<string[]>([]);
  const [samples, setSamples] = useState<SampleEntry[]>([]);
  const [regexPattern, setRegexPattern] = useState("_([^_]+?)_(\\d+)\\.\\w+$");
  const [controlKeyword, setControlKeyword] = useState("control");
  const [parseTab, setParseTab] = useState("auto");
  const [configParsing, setConfigParsing] = useState(false);
  const [singleTimePoint, setSingleTimePoint] = useState(false);

  // Secondary Sample Config (Cross-Talk mode)
  const [secondarySampleColumns, setSecondarySampleColumns] = useState<string[]>([]);
  const [secondarySamples, setSecondarySamples] = useState<SampleEntry[]>([]);
  const [secondaryRegexPattern, setSecondaryRegexPattern] = useState("_([^_]+?)_(\\d+)\\.\\w+$");
  const [secondaryControlKeyword, setSecondaryControlKeyword] = useState("control");
  const [secondaryParseTab, setSecondaryParseTab] = useState("auto");
  const [secondarySingleTimePoint, setSecondarySingleTimePoint] = useState(false);

  // Analysis Options
  const [analysisOptions, setAnalysisOptions] = useState<AnalysisOptions>({ ...DEFAULT_ANALYSIS_OPTIONS });
  const [analysisModalOpen, setAnalysisModalOpen] = useState(false);

  // Copy from Order
  const [copyFromOpen, setCopyFromOpen] = useState(false);
  const [copyFromOrders, setCopyFromOrders] = useState<{ id: number; order_code: string; project_name: string; status: string }[]>([]);
  const [copyFromLoading, setCopyFromLoading] = useState(false);

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

  // Advanced Report Config
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [reportConfig, setReportConfig] = useState({
    md_summary_max_chars: 12000,
    section_chars_limit: 1500,
    llm_tokens_abstract: 4096,
    llm_tokens_introduction: 12288,
    llm_tokens_results: 16384,
    llm_tokens_time_course: 8192,
    llm_tokens_discussion: 12288,
    llm_tokens_conclusion: 6144,
    llm_temperature: 0.6,
    chromadb_results_per_section: 10,
    ptm_detail_count: 30,
  });

  const goTo = useCallback((s: number) => {
    setDirection(s > step ? 1 : -1);
    setStep(s);
  }, [step]);

  // Load RAG collections
  useEffect(() => {
    setRagCollectionsLoading(true);
    api.get<{ collections: RagCollectionItem[] }>("/rag/collections")
      .then((d) => {
        const active = d.collections.filter((c) => c.is_active);
        setRagCollections(active);
      })
      .catch(() => setRagCollections([]))
      .finally(() => setRagCollectionsLoading(false));
  }, []);

  // Load Ollama models and default LLM config
  useEffect(() => {
    api.get<{ default_model: string }>("/system/llm-config").then((c) => {
      setDefaultLlmModel(c.default_model);
    }).catch(() => {}); 
    api.get<{ models: { provider: string; model_id: string; name: string; is_active: boolean }[] }>("/llm/models").then((d) => {
      const fromApi = d.models.filter((m) => m.is_active).map((m) => ({ provider: m.provider, model_id: m.model_id, name: m.name }));
      const cloudProviders: { provider: string; model_id: string; name: string }[] = [
        { provider: "gemini", model_id: "__provider__", name: "Gemini" },
        { provider: "openai", model_id: "__provider__", name: "OpenAI" },
        { provider: "anthropic", model_id: "__provider__", name: "Anthropic" },
      ];
      const hasProvider = (p: string) => fromApi.some((m) => m.provider === p && m.model_id === "__provider__");
      const merged = [...fromApi];
      for (const cp of cloudProviders) { if (!hasProvider(cp.provider)) merged.push(cp); }
      setLlmModels(merged);
    }).catch(() => {});
  }, []);

  // Load orders for Copy from
  useEffect(() => {
    if (copyFromOpen) {
      api.get<{ orders: { id: number; order_code: string; project_name: string; status: string }[] }>("/orders?page_size=50")
        .then((d) => setCopyFromOrders(d.orders))
        .catch(() => setCopyFromOrders([]));
    }
  }, [copyFromOpen]);

  const handleCopyFromOrder = useCallback(async (orderId: number) => {
    setCopyFromLoading(true);
    try {
      const order = await api.get<{ analysis_context: Record<string, string> }>(`/orders/${orderId}`);
      const ctx = order.analysis_context || {};
      const str = (v: unknown) => (v != null && typeof v === "string" ? v : "");

      setForm((f) => ({
        ...f,
        cell_type: str(ctx.cell_type),
        treatment: str(ctx.treatment),
        time_points: str(ctx.time_points),
        biological_question: str(ctx.biological_question),
        special_conditions: str(ctx.special_conditions),
      }));
      setCopyFromOpen(false);
    } catch (e) {
      console.error(e);
    } finally {
      setCopyFromLoading(false);
    }
  }, []);

  // When PR matrix changes, extract headers
  const handlePrChange = useCallback(async (file: File | null) => {
    setFiles((prev) => ({ ...prev, pr_matrix: file }));
    if (file) {
      try {
        const headers = await readTsvHeaders(file);
        const cols = extractSampleColumns(headers);
        setSampleColumns(cols);
        setSamples([]);
      } catch {
        setSampleColumns([]);
      }
    } else {
      setSampleColumns([]);
      setSamples([]);
    }
  }, []);

  const handleAutoParse = useCallback(() => {
    const parsed = autoParseColumns(sampleColumns, regexPattern, controlKeyword);
    setSamples(parsed);
  }, [sampleColumns, regexPattern, controlKeyword]);

  // Secondary PR Matrix header parsing for Cross-Talk mode
  const handleSecondaryPrChange = useCallback(async (file: File | null) => {
    setSecondaryFiles((prev) => ({ ...prev, pr_matrix: file }));
    if (file) {
      try {
        const headers = await readTsvHeaders(file);
        const cols = extractSampleColumns(headers);
        setSecondarySampleColumns(cols);
        setSecondarySamples([]);
      } catch {
        setSecondarySampleColumns([]);
      }
    } else {
      setSecondarySampleColumns([]);
      setSecondarySamples([]);
    }
  }, []);

  const handleSecondaryAutoParse = useCallback(() => {
    const parsed = autoParseColumns(secondarySampleColumns, secondaryRegexPattern, secondaryControlKeyword);
    setSecondarySamples(parsed);
  }, [secondarySampleColumns, secondaryRegexPattern, secondaryControlKeyword]);

  const updateSecondarySample = useCallback((idx: number, field: keyof SampleEntry, value: string | number) => {
    setSecondarySamples((prev) => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s));
  }, []);

  const removeSecondarySample = useCallback((idx: number) => {
    setSecondarySamples((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleConfigUpload = useCallback(async (file: File | null) => {
    setFiles((prev) => ({ ...prev, config_file: file }));
    if (!file) return;
    setConfigParsing(true);
    try {
      const fd = new FormData();
      fd.append("config_file", file);
      const result = await api.upload<{ samples: Array<{
        file_name: string; condition: string; group: string; replicate: number;
      }> }>("/orders/parse-config", fd);

      const parsed: SampleEntry[] = result.samples.map((s) => ({
        filename: s.file_name,
        shortname: getBasename(s.file_name),
        condition: s.condition,
        group: s.group,
        replicate: s.replicate,
      }));
      setSamples(parsed);
    } catch (e: any) {
      setError(e.message || "Failed to parse config file");
    } finally {
      setConfigParsing(false);
    }
  }, []);

  const updateSample = useCallback((idx: number, field: keyof SampleEntry, value: string | number) => {
    setSamples((prev) => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s));
  }, []);

  const removeSample = useCallback((idx: number) => {
    setSamples((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  // Submit
  const handleSubmit = async () => {
    if (!files.pr_matrix || !files.pg_matrix) {
      setError("PR Matrix and PG Matrix files are required");
      return;
    }
    if (form.analysis_mode === "cross_talk" && (!secondaryFiles.pr_matrix || !secondaryFiles.pg_matrix)) {
      setError("Cross-Talk mode requires secondary PR Matrix and PG Matrix files");
      return;
    }
    if (form.analysis_mode === "cross_talk" && secondarySamples.length === 0) {
      setError("Cross-Talk mode requires secondary sample configuration. Go back to Step 3 and configure secondary samples.");
      return;
    }
    if (samples.length === 0) {
      setError("Sample configuration is required. Go back to Step 2 and configure samples.");
      return;
    }

    setLoading(true);
    setError("");

    const sampleConfig = {
      source: parseTab === "auto" ? "auto_parse" : "xlsx",
      regex_pattern: parseTab === "auto" ? regexPattern : undefined,
      single_time_point: singleTimePoint,
      samples: samples.map((s) => ({
        file_name: s.filename,
        condition: s.condition,
        group: s.group,
        replicate: s.replicate,
      })),
    };

    const formData = new FormData();
    formData.append("project_name", form.project_name);
    formData.append("ptm_type", form.ptm_type);
    formData.append("species", form.species);
    formData.append("sample_config", JSON.stringify(sampleConfig));
    formData.append("analysis_context", JSON.stringify({
      cell_type: form.cell_type, treatment: form.treatment,
      time_points: form.time_points, biological_question: form.biological_question,
      special_conditions: form.special_conditions,
    }));
    // Build nested report_config from flat state
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
    formData.append("report_options", JSON.stringify({
      report_type: form.report_type, ptm_selection_mode: form.ptm_selection_mode, top_n_ptms: form.top_n_ptms, output_format: "md",
      analysis_mode: form.analysis_mode,
      research_questions: form.report_type === "co_scientist" ? [] : (researchQuestions.length > 0 ? researchQuestions : []),
      ...(form.llm_model ? (() => {
        const colonIdx = form.llm_model.indexOf(":");
        const [p, m] = colonIdx >= 0 ? [form.llm_model.slice(0, colonIdx), form.llm_model.slice(colonIdx + 1)] : ["ollama", form.llm_model];
        const presets = CLOUD_MODEL_PRESETS[p as CloudProvider];
        const model = isCloudProviderSelection(form.llm_model)
          ? (llmCloudModelVariant || (presets?.some((x) => x.id === m) ? m : presets?.[0]?.id))
          : m;
        return model ? { llm_model: model, llm_provider: p } : {};
      })() : {}),
      ...(form.rag_enrichment_llm_model ? (() => {
        const colonIdx = form.rag_enrichment_llm_model.indexOf(":");
        const [p, m] = colonIdx >= 0 ? [form.rag_enrichment_llm_model.slice(0, colonIdx), form.rag_enrichment_llm_model.slice(colonIdx + 1)] : ["ollama", form.rag_enrichment_llm_model];
        const presets = CLOUD_MODEL_PRESETS[p as CloudProvider];
        const model = isCloudProviderSelection(form.rag_enrichment_llm_model)
          ? (ragEnrichmentLlmCloudModelVariant || (presets?.some((x) => x.id === m) ? m : presets?.[0]?.id))
          : m;
        return model ? { rag_enrichment_llm_model: model, rag_enrichment_llm_provider: p } : {};
      })() : {}),
      report_config: reportConfigNested,
    }));
    const { proteinListFile, ...analysisOptsForJson } = analysisOptions;
    formData.append("analysis_options", JSON.stringify(analysisOptsForJson));
    // RAG collection selection (null = all active)
    if (!useAllCollections && selectedCollectionIds.length > 0) {
      formData.append("rag_collections", JSON.stringify(selectedCollectionIds));
    }
    formData.append("pr_matrix", files.pr_matrix);
    formData.append("pg_matrix", files.pg_matrix);
    if (files.config_file) formData.append("config_file", files.config_file);
    if (analysisOptions.mode === "protein_list" && proteinListFile) {
      formData.append("protein_list", proteinListFile);
    }
    if (form.analysis_mode === "cross_talk") {
      formData.append("secondary_ptm_type", form.secondary_ptm_type);
      if (secondaryFiles.pr_matrix) formData.append("secondary_pr_matrix", secondaryFiles.pr_matrix);
      if (secondaryFiles.pg_matrix) formData.append("secondary_pg_matrix", secondaryFiles.pg_matrix);
      // Secondary sample configuration
      const secondarySampleConfig = {
        source: secondaryParseTab === "auto" ? "auto_parse" : "manual",
        regex_pattern: secondaryParseTab === "auto" ? secondaryRegexPattern : undefined,
        single_time_point: secondarySingleTimePoint,
        samples: secondarySamples.map((s) => ({
          file_name: s.filename,
          condition: s.condition,
          group: s.group,
          replicate: s.replicate,
        })),
      };
      formData.append("secondary_sample_config", JSON.stringify(secondarySampleConfig));
    }

    try {
      const result = await api.upload<{ id: number; order_code: string }>("/orders", formData);
      navigate(`/admin/orders/${result.id}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // Condition summary for step 1
  const conditionSummary = samples.length > 0
    ? Object.entries(
        samples.reduce<Record<string, number>>((acc, s) => {
          const key = `${s.group}:${s.condition}`;
          acc[key] = (acc[key] || 0) + 1;
          return acc;
        }, {}),
      )
    : [];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Create New Order</h1>

      {/* Step Indicator */}
      <div className="flex items-center gap-1">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-1">
            <button
              onClick={() => i < step && goTo(i)}
              className={cn(
                "flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                i < step ? "bg-primary text-primary-foreground cursor-pointer"
                  : i === step ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {i < step ? <Check className="h-3 w-3" /> : <span className="font-bold">{i + 1}</span>}
              <span className="hidden sm:inline">{label}</span>
            </button>
            {i < STEPS.length - 1 && (
              <div className={cn("h-px w-6", i < step ? "bg-primary" : "bg-border")} />
            )}
          </div>
        ))}
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Steps */}
      <Card>
        <CardContent className="p-6">
          <AnimatePresence mode="wait" custom={direction}>
            {/* ── Step 0: Project & Files ─────────────────────────── */}
            {step === 0 && (
              <motion.div key="s0" custom={direction} variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.25, ease: "easeInOut" }} className="space-y-5"
              >
                <div className="space-y-2">
                  <Label htmlFor="project_name">Order Name</Label>
                  <Input id="project_name" value={form.project_name}
                    onChange={(e) => setForm({ ...form, project_name: e.target.value })}
                    placeholder="e.g., PTM-2026-0004 or Mouse Muscle Phosphoproteome"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>PTM Type</Label>
                    <Select value={form.ptm_type} onValueChange={(v) => setForm({ ...form, ptm_type: v })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="phosphorylation">Phosphorylation</SelectItem>
                        <SelectItem value="ubiquitylation">Ubiquitylation</SelectItem>
                        <SelectItem value="acetylation">Acetylation</SelectItem>
                        <SelectItem value="methylation">Methylation</SelectItem>
                        <SelectItem value="sumoylation">SUMOylation</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Species</Label>
                    <Select value={form.species} onValueChange={(v) => setForm({ ...form, species: v })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="mouse">Mouse</SelectItem>
                        <SelectItem value="human">Human</SelectItem>
                        <SelectItem value="rat">Rat</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <FileDropZone label="PR Matrix (.tsv)" accept=".tsv,.csv"
                  file={files.pr_matrix} onChange={handlePrChange}
                />
                <FileDropZone label="PG Matrix (.tsv)" accept=".tsv,.csv"
                  file={files.pg_matrix}
                  onChange={(f) => setFiles({ ...files, pg_matrix: f })}
                />

                <div className="rounded-lg border border-dashed border-muted-foreground/25 bg-muted/30 p-4">
                  <p className="text-sm font-medium">Reference FASTA</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Automatically resolved from <code className="text-xs bg-muted px-1 rounded">data/reference/{form.species}/</code>
                  </p>
                </div>

                {sampleColumns.length > 0 && (
                  <div className="rounded-lg border bg-muted/30 p-3">
                    <p className="text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{sampleColumns.length}</span> sample columns detected from PR Matrix
                    </p>
                  </div>
                )}

                <div className="flex justify-end">
                  <Button onClick={() => goTo(1)} disabled={!form.project_name || !files.pr_matrix}>
                    Next <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </motion.div>
            )}

            {/* ── Step 1: Sample Configuration ────────────────────── */}
            {step === 1 && (
              <motion.div key="s1" custom={direction} variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.25, ease: "easeInOut" }} className="space-y-5"
              >
                <div>
                  <h3 className="text-sm font-semibold mb-1">Sample Configuration</h3>
                  <p className="text-xs text-muted-foreground">
                    Define Condition, Group, and Replicate for each sample.
                  </p>
                </div>

                <div className="flex items-center gap-3 rounded-lg border-2 border-amber-500/40 bg-amber-500/5 px-4 py-3">
                  <input
                    type="checkbox"
                    id="single-time-point"
                    checked={singleTimePoint}
                    onChange={(e) => setSingleTimePoint(e.target.checked)}
                    className="h-4 w-4 rounded border-input shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <Label htmlFor="single-time-point" className="text-sm font-medium cursor-pointer">
                      Single time point
                    </Label>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Check if samples are not time-series (no temporal grouping)
                    </p>
                  </div>
                </div>

                <Tabs value={parseTab} onValueChange={setParseTab}>
                  <TabsList className="grid w-full grid-cols-2">
                    <TabsTrigger value="auto" className="gap-2">
                      <Regex className="h-3.5 w-3.5" /> Auto Parse
                    </TabsTrigger>
                    <TabsTrigger value="xlsx" className="gap-2">
                      <FileSpreadsheet className="h-3.5 w-3.5" /> Upload config.xlsx
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="auto" className="space-y-4 mt-4">
                    <div className="grid grid-cols-[1fr_auto_auto] gap-3 items-end">
                      <div className="space-y-1.5">
                        <Label className="text-xs">Regex Pattern <span className="text-muted-foreground">(applied to filename)</span></Label>
                        <Input value={regexPattern} onChange={(e) => setRegexPattern(e.target.value)}
                          className="font-mono text-xs" placeholder="_([^_]+?)_(\d+)\.\w+$"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs">Control Keyword</Label>
                        <Input value={controlKeyword} onChange={(e) => setControlKeyword(e.target.value)}
                          className="w-28 text-xs" placeholder="control"
                        />
                      </div>
                      <Button onClick={handleAutoParse} disabled={sampleColumns.length === 0} size="sm">
                        Parse
                      </Button>
                    </div>
                    <div className="text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
                      <p className="font-medium text-foreground">How it works:</p>
                      <p>Group 1 = <strong>Condition label</strong> (e.g. control, 3h, 6h)</p>
                      <p>Group 2 = <strong>Replicate number</strong> (e.g. 1, 2, 3)</p>
                      <p>If condition matches "{controlKeyword}" → Group = <Badge variant="secondary" className="text-[10px] py-0">Control</Badge>, else → <Badge variant="secondary" className="text-[10px] py-0">Treatment</Badge></p>
                      {sampleColumns.length > 0 && (
                        <>
                          <Separator className="my-2" />
                          <p className="font-medium text-foreground">Example filename:</p>
                          <p className="font-mono break-all">{getBasename(sampleColumns[0])}</p>
                        </>
                      )}
                    </div>
                  </TabsContent>

                  <TabsContent value="xlsx" className="space-y-4 mt-4">
                    <FileDropZone
                      label="Sample Config (.xlsx)"
                      accept=".xlsx,.xls"
                      hint="Excel with columns: File_Name, Condition, Group, Replicate"
                      file={files.config_file}
                      onChange={handleConfigUpload}
                    />
                    {configParsing && (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" /> Parsing config file...
                      </div>
                    )}
                  </TabsContent>
                </Tabs>

                {/* Sample Table */}
                {samples.length > 0 && (
                  <>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium">{samples.length} Samples</p>
                      <div className="flex gap-1.5 flex-wrap">
                        {conditionSummary.map(([key, count]) => {
                          const [group, cond] = key.split(":");
                          return (
                            <Badge key={key} variant={group === "Control" ? "default" : "secondary"} className="text-[10px]">
                              {cond || group} ({count})
                            </Badge>
                          );
                        })}
                      </div>
                    </div>

                    <div className="rounded-lg border overflow-hidden">
                      <div className="max-h-[320px] overflow-y-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-xs w-[35%]">Sample File</TableHead>
                              <TableHead className="text-xs">Condition</TableHead>
                              <TableHead className="text-xs">Group</TableHead>
                              <TableHead className="text-xs w-16">Rep.</TableHead>
                              <TableHead className="text-xs w-10"></TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {samples.map((s, i) => (
                              <TableRow key={i}>
                                <TableCell className="font-mono text-[11px] truncate max-w-[200px]" title={s.filename}>
                                  {s.shortname}
                                </TableCell>
                                <TableCell>
                                  <Input value={s.condition} className="h-7 text-xs"
                                    onChange={(e) => updateSample(i, "condition", e.target.value)}
                                  />
                                </TableCell>
                                <TableCell>
                                  <Select value={s.group} onValueChange={(v) => updateSample(i, "group", v)}>
                                    <SelectTrigger className="h-7 text-xs w-[110px]"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="Control">Control</SelectItem>
                                      <SelectItem value="Treatment">Treatment</SelectItem>
                                    </SelectContent>
                                  </Select>
                                </TableCell>
                                <TableCell>
                                  <Input type="number" value={s.replicate} min={1}
                                    className="h-7 text-xs w-14"
                                    onChange={(e) => updateSample(i, "replicate", parseInt(e.target.value) || 1)}
                                  />
                                </TableCell>
                                <TableCell>
                                  <Button variant="ghost" size="icon" className="h-7 w-7"
                                    onClick={() => removeSample(i)}
                                  >
                                    <Trash2 className="h-3 w-3 text-muted-foreground" />
                                  </Button>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  </>
                )}

                <div className="flex justify-between">
                  <Button variant="outline" onClick={() => goTo(0)}>
                    <ArrowLeft className="mr-2 h-4 w-4" /> Back
                  </Button>
                  <Button onClick={() => goTo(2)} disabled={samples.length === 0}>
                    Next <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </motion.div>
            )}

            {/* ── Step 2: Analysis Focus ──────────────────────────── */}
            {step === 2 && (
              <motion.div key="s2" custom={direction} variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.25, ease: "easeInOut" }} className="space-y-5"
              >
                <div className="flex items-center justify-between gap-4">
                  <div />
                  <Button variant="outline" size="sm" onClick={() => setCopyFromOpen(true)} className="gap-2 shrink-0">
                    <Copy className="h-4 w-4" /> Copy from Order
                  </Button>
                </div>
                {/* Analysis Mode Selection */}
                <div className="space-y-3">
                  <Label className="text-sm font-semibold">Analysis Mode</Label>
                  <div className="grid grid-cols-3 gap-3">
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, analysis_mode: "ptm_only" })}
                      className={cn(
                        "flex flex-col items-start gap-2 rounded-lg border-2 p-4 text-left transition-all",
                        form.analysis_mode === "ptm_only"
                          ? "border-primary bg-primary/5"
                          : "border-muted hover:border-muted-foreground/30",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <FlaskConical className={cn("h-5 w-5", form.analysis_mode === "ptm_only" ? "text-primary" : "text-muted-foreground")} />
                        <span className="font-medium text-sm">PTM-Only</span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        Multi-Agent analysis with ChromaDB RAG, hypothesis generation, and literature-backed report.
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, analysis_mode: "ptm_nonptm_network" })}
                      className={cn(
                        "flex flex-col items-start gap-2 rounded-lg border-2 p-4 text-left transition-all",
                        form.analysis_mode === "ptm_nonptm_network"
                          ? "border-primary bg-primary/5"
                          : "border-muted hover:border-muted-foreground/30",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <Network className={cn("h-5 w-5", form.analysis_mode === "ptm_nonptm_network" ? "text-primary" : "text-muted-foreground")} />
                        <span className="font-medium text-sm">PTM + Network</span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        Includes KEA3 kinase enrichment, STRING-DB protein interactions, and network analysis.
                      </p>
                      <div className="flex gap-1">
                        <Badge variant="secondary" className="text-[9px]">KEA3</Badge>
                        <Badge variant="secondary" className="text-[9px]">STRING-DB</Badge>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, analysis_mode: "cross_talk" })}
                      className={cn(
                        "flex flex-col items-start gap-2 rounded-lg border-2 p-4 text-left transition-all",
                        form.analysis_mode === "cross_talk"
                          ? "border-amber-500 bg-amber-50/50"
                          : "border-muted hover:border-muted-foreground/30",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <GitMerge className={cn("h-5 w-5", form.analysis_mode === "cross_talk" ? "text-amber-600" : "text-muted-foreground")} />
                        <span className="font-medium text-sm">Cross-Talk (Phos x Ub)</span>
                        <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-600">Cross-Talk</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        Phosphorylation과 Ubiquitylation 두 PTM 데이터셋을 동시에 분석하여 Dual-PTM 단백질, Concordant/Discordant 패턴, Sequential Gating 메커니즘을 규명합니다.
                      </p>
                      <div className="flex gap-1 flex-wrap">
                        <Badge variant="secondary" className="text-[9px]">Dual-PTM</Badge>
                        <Badge variant="secondary" className="text-[9px]">Sequential Gating</Badge>
                        <Badge variant="secondary" className="text-[9px]">TIME LAG</Badge>
                      </div>
                    </button>
                  </div>
                </div>

                {/* Cross-Talk: Secondary PTM Type & Files */}
                {form.analysis_mode === "cross_talk" && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50/30 p-4 space-y-4">
                    <div className="flex items-center gap-2">
                      <GitMerge className="h-4 w-4 text-amber-600" />
                      <Label className="font-semibold text-amber-800">Secondary PTM Dataset (Cross-Talk)</Label>
                    </div>
                    <p className="text-xs text-amber-700">
                      위의 기본 파일이 첫 번째 PTM ({form.ptm_type})이라면, 여기에 두 번째 PTM 데이터를 업로드하세요.
                    </p>
                    <div className="space-y-2">
                      <Label className="text-xs">Secondary PTM Type</Label>
                      <Select value={form.secondary_ptm_type} onValueChange={(v) => setForm({ ...form, secondary_ptm_type: v })}>
                        <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="phosphorylation">Phosphorylation</SelectItem>
                          <SelectItem value="ubiquitylation">Ubiquitylation</SelectItem>
                          <SelectItem value="acetylation">Acetylation</SelectItem>
                          <SelectItem value="methylation">Methylation</SelectItem>
                          <SelectItem value="sumoylation">SUMOylation</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <FileDropZone label="Secondary PR Matrix (.tsv)" accept=".tsv,.csv"
                      file={secondaryFiles.pr_matrix}
                      onChange={handleSecondaryPrChange}
                    />
                    <FileDropZone label="Secondary PG Matrix (.tsv)" accept=".tsv,.csv"
                      file={secondaryFiles.pg_matrix}
                      onChange={(f) => setSecondaryFiles((prev) => ({ ...prev, pg_matrix: f }))}
                    />

                    {/* Secondary Sample Configuration */}
                    {secondarySampleColumns.length > 0 && (
                      <div className="rounded-lg border border-amber-300 bg-white/60 p-4 space-y-3">
                        <div className="flex items-center gap-2">
                          <SlidersHorizontal className="h-4 w-4 text-amber-600" />
                          <Label className="font-semibold text-amber-800 text-sm">Secondary Sample Configuration</Label>
                          <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-600">
                            {secondarySampleColumns.length} columns detected
                          </Badge>
                        </div>
                        <p className="text-xs text-amber-700">
                          Secondary PR Matrix에서 {secondarySampleColumns.length}개의 샘플 컬럼이 감지되었습니다. 각 샘플의 Condition과 Group을 설정하세요.
                        </p>

                        <Tabs value={secondaryParseTab} onValueChange={setSecondaryParseTab}>
                          <TabsList className="h-8">
                            <TabsTrigger value="auto" className="text-xs gap-1"><Regex className="h-3 w-3" /> Auto Parse</TabsTrigger>
                            <TabsTrigger value="manual" className="text-xs gap-1"><SlidersHorizontal className="h-3 w-3" /> Manual</TabsTrigger>
                          </TabsList>
                          <TabsContent value="auto" className="space-y-2 mt-2">
                            <div className="grid grid-cols-2 gap-2">
                              <div className="space-y-1">
                                <Label className="text-[10px]">Regex Pattern</Label>
                                <Input className="h-7 text-xs font-mono" value={secondaryRegexPattern}
                                  onChange={(e) => setSecondaryRegexPattern(e.target.value)} />
                              </div>
                              <div className="space-y-1">
                                <Label className="text-[10px]">Control Keyword</Label>
                                <Input className="h-7 text-xs" value={secondaryControlKeyword}
                                  onChange={(e) => setSecondaryControlKeyword(e.target.value)} />
                              </div>
                            </div>
                            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleSecondaryAutoParse}>
                              <Regex className="mr-1 h-3 w-3" /> Parse Secondary Samples
                            </Button>
                          </TabsContent>
                        </Tabs>

                        <div className="flex items-center gap-2">
                          <input type="checkbox" id="sec-single-tp" checked={secondarySingleTimePoint}
                            onChange={(e) => setSecondarySingleTimePoint(e.target.checked)}
                            className="rounded border-amber-300" />
                          <Label htmlFor="sec-single-tp" className="text-xs text-amber-700 cursor-pointer">
                            Single Time Point (non-temporal comparison)
                          </Label>
                        </div>

                        {secondarySamples.length > 0 && (
                          <div className="rounded border border-amber-200 overflow-hidden">
                            <Table>
                              <TableHeader>
                                <TableRow className="bg-amber-50/50">
                                  <TableHead className="text-[10px] py-1 px-2 w-[200px]">File Name</TableHead>
                                  <TableHead className="text-[10px] py-1 px-2">Condition</TableHead>
                                  <TableHead className="text-[10px] py-1 px-2">Group</TableHead>
                                  <TableHead className="text-[10px] py-1 px-2 w-[60px]">Rep</TableHead>
                                  <TableHead className="text-[10px] py-1 px-2 w-[30px]"></TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {secondarySamples.map((s, i) => (
                                  <TableRow key={i} className="hover:bg-amber-50/30">
                                    <TableCell className="text-[10px] py-0.5 px-2 font-mono truncate max-w-[200px]" title={s.filename}>
                                      {s.shortname}
                                    </TableCell>
                                    <TableCell className="py-0.5 px-1">
                                      <Input className="h-6 text-[10px]" value={s.condition}
                                        onChange={(e) => updateSecondarySample(i, "condition", e.target.value)} />
                                    </TableCell>
                                    <TableCell className="py-0.5 px-1">
                                      <Select value={s.group} onValueChange={(v) => updateSecondarySample(i, "group", v)}>
                                        <SelectTrigger className="h-6 text-[10px]"><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="Control">Control</SelectItem>
                                          <SelectItem value="Treatment">Treatment</SelectItem>
                                        </SelectContent>
                                      </Select>
                                    </TableCell>
                                    <TableCell className="py-0.5 px-1">
                                      <Input type="number" className="h-6 text-[10px] w-12" value={s.replicate}
                                        onChange={(e) => updateSecondarySample(i, "replicate", parseInt(e.target.value) || 1)} min={1} />
                                    </TableCell>
                                    <TableCell className="py-0.5 px-1">
                                      <button onClick={() => removeSecondarySample(i)} className="text-red-400 hover:text-red-600">
                                        <Trash2 className="h-3 w-3" />
                                      </button>
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </div>
                        )}

                        {secondarySamples.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(
                              secondarySamples.reduce<Record<string, number>>((acc, s) => {
                                const key = `${s.group}:${s.condition}`;
                                acc[key] = (acc[key] || 0) + 1;
                                return acc;
                              }, {})
                            ).map(([key, count]) => {
                              const [group, cond] = key.split(":");
                              return (
                                <Badge key={key} variant={group === "Control" ? "secondary" : "outline"} className="text-[9px]">
                                  {cond || group} (n={count})
                                </Badge>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                <Separator />

                <div className="space-y-2">
                  <Label>Cell Type</Label>
                  <Input value={form.cell_type}
                    onChange={(e) => setForm({ ...form, cell_type: e.target.value })}
                    placeholder="e.g., C2C12 myotubes"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Treatment</Label>
                  <div className="relative">
                    <Input value={form.treatment}
                      onChange={(e) => handleTreatmentChange(e.target.value)}
                      placeholder="e.g., Irisin stimulation"
                    />
                    {treatmentSuggestionsVisible && treatmentSuggestions.length > 0 && (
                      <div className="absolute z-50 top-full left-0 right-0 mt-1 rounded-lg border border-amber-500/40 bg-gray-900/95 backdrop-blur-sm shadow-xl p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-semibold text-amber-400 flex items-center gap-1">
                            <span>⚠</span> Did you mean?
                          </p>
                          <button
                            type="button"
                            onClick={() => setTreatmentSuggestionsVisible(false)}
                            className="text-gray-500 hover:text-gray-300 text-xs"
                          >✕</button>
                        </div>
                        {treatmentSuggestions.map((s, i) => (
                          <div key={i} className="flex items-center justify-between gap-2 text-sm">
                            <span className="text-gray-400">
                              <span className="line-through text-red-400/70">{s.original_token}</span>
                              {" → "}
                              <span className="text-green-400 font-medium">{s.suggested}</span>
                            </span>
                            <div className="flex items-center gap-1">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${
                                s.confidence === 'high' ? 'bg-green-500/20 text-green-400' :
                                s.confidence === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                                'bg-gray-500/20 text-gray-400'
                              }`}>{s.confidence}</span>
                              <button
                                type="button"
                                onClick={() => applyTreatmentSuggestion(s.original_token, s.suggested)}
                                className="text-xs px-2 py-0.5 rounded bg-blue-600/30 hover:bg-blue-600/50 text-blue-300 border border-blue-500/30 transition-colors"
                              >Apply</button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Time Points</Label>
                  <Input value={form.time_points}
                    onChange={(e) => setForm({ ...form, time_points: e.target.value })}
                    placeholder="e.g., 0, 5, 15, 30 min"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Biological Question</Label>
                  <Textarea value={form.biological_question}
                    onChange={(e) => setForm({ ...form, biological_question: e.target.value })}
                    placeholder="e.g., What signaling pathways are activated by irisin in skeletal muscle?"
                    rows={3}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Special Conditions</Label>
                  <Input value={form.special_conditions}
                    onChange={(e) => setForm({ ...form, special_conditions: e.target.value })}
                    placeholder="e.g., hypoxia, serum starvation, knockdown"
                  />
                </div>

                <div className="flex justify-between">
                  <Button variant="outline" onClick={() => goTo(1)}>
                    <ArrowLeft className="mr-2 h-4 w-4" /> Back
                  </Button>
                  <Button onClick={() => goTo(3)}>
                    Next <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </motion.div>
            )}

            {/* ── Step 3: Report Options ──────────────────────────── */}
            {step === 3 && (
              <motion.div key="s3" custom={direction} variants={slideVariants}
                initial="enter" animate="center" exit="exit"
                transition={{ duration: 0.25, ease: "easeInOut" }} className="space-y-5"
              >
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Report Type</Label>
                    <Select
                      value={form.report_type}
                      onValueChange={(v) => {
                        setForm({ ...form, report_type: v });
                        if (v === "co_scientist") {
                          setResearchQuestions([]);
                          setNewQuestion("");
                        }
                      }}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="comprehensive">Standard Report</SelectItem>
                        <SelectItem value="extended">Extended (+ Drug Repositioning)</SelectItem>
                        <SelectItem value="co_scientist">Data-Grounded Analysis (데이터 기반 가설·검증)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-[10px] text-muted-foreground">
                      {form.report_type === "extended"
                        ? "Drug target prioritization 및 repositioning 분석 포함"
                        : form.report_type === "co_scientist"
                        ? "AI 자율 분석: Temporal Cascade · Co-Wave · Autophosphorylation · TMM 통합 가설 생성 및 데이터 검증"
                        : "PTM 분석, 가설 검증, 네트워크 분석 기반 보고서"}
                    </p>
                    {form.report_type === "co_scientist" && (
                      <div className="rounded-md border border-blue-500/30 bg-blue-500/10 p-2 text-[10px] text-blue-300 space-y-1">
                        <p className="font-semibold text-blue-200">🔬 Data-Grounded Analysis</p>
                        <p>AI가 4개 데이터 소스를 통합하여 가설을 자동 생성하고 실험 데이터로 직접 검증합니다. 검증된 가설은 레포트에 수치 포함 자동 삽입됩니다.</p>
                      </div>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label>PTM Selection Mode</Label>
                    <Select
                      value={form.ptm_selection_mode}
                      onValueChange={(v) => setForm({ ...form, ptm_selection_mode: v as typeof form.ptm_selection_mode })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="de_novo_regulated">De novo + Regulated (recommended)</SelectItem>
                        <SelectItem value="de_novo">De novo only</SelectItem>
                        <SelectItem value="regulated">Regulated only</SelectItem>
                        <SelectItem value="minor">Minor only</SelectItem>
                        <SelectItem value="all">All PTMs</SelectItem>
                        <SelectItem value="top_n">Top N by |FC| (legacy)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-[10px] text-muted-foreground">
                      {form.ptm_selection_mode === "de_novo_regulated" && "De novo (no control) + Statistically regulated (q < 0.05, |FC| ≥ 1.0) PTMs"}
                      {form.ptm_selection_mode === "de_novo" && "Only PTMs with no control condition (pseudocount imputed)"}
                      {form.ptm_selection_mode === "regulated" && "Only statistically significant PTMs (q < 0.05, |Log2FC| ≥ 1.0)"}
                      {form.ptm_selection_mode === "minor" && "PTMs that are neither de novo nor statistically regulated"}
                      {form.ptm_selection_mode === "all" && "All detected PTMs — may increase analysis time significantly"}
                      {form.ptm_selection_mode === "top_n" && `Top ${form.top_n_ptms} PTMs ranked by max |Log2FC|`}
                    </p>
                    {form.ptm_selection_mode === "top_n" && (
                      <div className="flex items-center gap-2 mt-2">
                        <Label className="text-xs whitespace-nowrap">Top N:</Label>
                        <Input
                          type="number"
                          min={10}
                          max={500}
                          value={form.top_n_ptms}
                          onChange={(e) => setForm({ ...form, top_n_ptms: Math.max(10, Math.min(500, parseInt(e.target.value) || 50)) })}
                          className="w-24 h-8 text-sm"
                        />
                        <span className="text-[10px] text-muted-foreground">10–500</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* LLM Model for RAG Enrichment */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Database className="h-4 w-4" /> LLM Model (RAG Enrichment)
                  </Label>
                  <Select
                    value={form.rag_enrichment_llm_model || ""}
                    onValueChange={(v) => {
                      setForm({ ...form, rag_enrichment_llm_model: v === "__default__" ? "" : v });
                      if (v === "__default__" || !isCloudProviderSelection(v)) {
                        setRagEnrichmentLlmCloudModelVariant("");
                      } else {
                        const [, m] = v.split(":", 2);
                        const p = v.split(":")[0] as CloudProvider;
                        const presets = CLOUD_MODEL_PRESETS[p];
                        const validId = presets?.some((x) => x.id === m) ? m : presets?.[0]?.id || "";
                        setRagEnrichmentLlmCloudModelVariant(validId);
                      }
                    }}
                  >
                    <SelectTrigger><SelectValue placeholder={`Default (Report model)`} /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">
                        Default ({defaultLlmModel || "Report model"})
                      </SelectItem>
                      {llmModels.map((m) => {
                        const val = `${m.provider}:${m.model_id}`;
                        return (
                          <SelectItem key={val} value={val}>
                            {m.name} ({m.provider})
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                  {isCloudProviderSelection(form.rag_enrichment_llm_model || "") && (
                    <div className="flex items-center gap-2 pl-2 border-l-2 border-muted">
                      <Label className="text-xs shrink-0">세부 모델</Label>
                      <Select
                        value={ragEnrichmentLlmCloudModelVariant || CLOUD_MODEL_PRESETS[form.rag_enrichment_llm_model.split(":")[0] as CloudProvider]?.[0]?.id}
                        onValueChange={setRagEnrichmentLlmCloudModelVariant}
                      >
                        <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {CLOUD_MODEL_PRESETS[form.rag_enrichment_llm_model.split(":")[0] as CloudProvider]?.map((x) => (
                            <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">
                    RAG Enrichment 단계(Abstract 분석, 키나제 예측 등) 전용. 미선택 시 Report 모델을 사용합니다.
                  </p>
                  {isRagModelTooSmall(form.rag_enrichment_llm_model) && (
                    <div className="flex items-start gap-2 p-2 rounded-md bg-amber-500/10 border border-amber-500/30">
                      <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                      <p className="text-xs text-amber-500">
                        선택한 모델({form.rag_enrichment_llm_model})은 {getModelSizeB(form.rag_enrichment_llm_model)}B로,
                        RAG Enrichment 최소 권장 크기({MIN_RAG_MODEL_SIZE_B}B) 미만입니다.
                        JSON 파싱 실패 및 hallucination 위험이 높아 서버에서 자동으로 qwen2.5:14b로 대체됩니다.
                      </p>
                    </div>
                  )}
                </div>

                {/* LLM Model for Report Generation */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Brain className="h-4 w-4" /> LLM Model for Report Generation
                  </Label>
                  <Select
                    value={form.llm_model || ""}
                    onValueChange={(v) => {
                      setForm({ ...form, llm_model: v === "__default__" ? "" : v });
                      if (v === "__default__" || !isCloudProviderSelection(v)) {
                        setLlmCloudModelVariant("");
                      } else {
                        const [, m] = v.split(":", 2);
                        const p = v.split(":")[0] as CloudProvider;
                        const presets = CLOUD_MODEL_PRESETS[p];
                        const validId = presets?.some((x) => x.id === m) ? m : presets?.[0]?.id || "";
                        setLlmCloudModelVariant(validId);
                      }
                    }}
                  >
                    <SelectTrigger><SelectValue placeholder={`Default (${defaultLlmModel || "auto"})`} /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">
                        Default ({defaultLlmModel || "auto"})
                      </SelectItem>
                      {llmModels.map((m) => {
                        const val = `${m.provider}:${m.model_id}`;
                        return (
                          <SelectItem key={val} value={val}>
                            {m.name} ({m.provider})
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                  {isCloudProviderSelection(form.llm_model || "") && (
                    <div className="flex items-center gap-2 pl-2 border-l-2 border-muted">
                      <Label className="text-xs shrink-0">세부 모델</Label>
                      <Select
                        value={llmCloudModelVariant || CLOUD_MODEL_PRESETS[form.llm_model.split(":")[0] as CloudProvider]?.[0]?.id}
                        onValueChange={setLlmCloudModelVariant}
                      >
                        <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {CLOUD_MODEL_PRESETS[form.llm_model.split(":")[0] as CloudProvider]?.map((x) => (
                            <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Report Generation에서 사용할 LLM 모델. Cloud 선택 시 세부 모델을 선택하세요.
                  </p>
                </div>

                {/* RAG Collection Selection */}
                <div className="space-y-3">
                  <Label className="flex items-center gap-2">
                    <Database className="h-4 w-4" /> RAG Literature Collections
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    분석에 참조할 문헌 컬렉션을 선택합니다. 전체 선택 시 모든 활성 컬렉션이 사용됩니다.
                  </p>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className={cn(
                        "flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-colors",
                        useAllCollections
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-muted-foreground/25 hover:border-muted-foreground/50"
                      )}
                      onClick={() => {
                        setUseAllCollections(true);
                        setSelectedCollectionIds([]);
                      }}
                    >
                      {useAllCollections ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                      전체 사용 ({ragCollections.length}개)
                    </button>
                    <button
                      type="button"
                      className={cn(
                        "flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-colors",
                        !useAllCollections
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-muted-foreground/25 hover:border-muted-foreground/50"
                      )}
                      onClick={() => setUseAllCollections(false)}
                    >
                      {!useAllCollections ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                      직접 선택
                    </button>
                  </div>
                  {!useAllCollections && (
                    <div className="rounded-lg border max-h-[240px] overflow-y-auto">
                      {ragCollectionsLoading ? (
                        <div className="flex items-center justify-center py-6">
                          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                      ) : ragCollections.length === 0 ? (
                        <p className="text-sm text-muted-foreground py-4 text-center">등록된 활성 컬렉션이 없습니다.</p>
                      ) : (
                        <div className="divide-y">
                          {/* Select All / Deselect All */}
                          <div className="flex items-center justify-between px-4 py-2 bg-muted/30">
                            <span className="text-xs font-medium text-muted-foreground">
                              {selectedCollectionIds.length}개 선택됨
                            </span>
                            <div className="flex gap-2">
                              <button
                                type="button"
                                className="text-xs text-primary hover:underline"
                                onClick={() => setSelectedCollectionIds(ragCollections.map((c) => c.id))}
                              >
                                전체 선택
                              </button>
                              <button
                                type="button"
                                className="text-xs text-muted-foreground hover:underline"
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
                                  "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/50",
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
                                  <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                                ) : (
                                  <Square className="h-4 w-4 text-muted-foreground shrink-0" />
                                )}
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm font-medium truncate">{c.name}</span>
                                    <Badge variant="secondary" className="text-[10px] shrink-0">{c.tier}</Badge>
                                  </div>
                                  {c.description && (
                                    <p className="text-xs text-muted-foreground truncate mt-0.5">{c.description}</p>
                                  )}
                                </div>
                                <span className="text-xs text-muted-foreground shrink-0">
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

                {/* Research Questions — Co-Scientist mode generates these autonomously */}
                {form.report_type !== "co_scientist" && (
                <div className="space-y-3">
                  <Label className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4" /> Research Questions
                    <span className="text-xs text-muted-foreground font-normal">(optional)</span>
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    특정 연구 질문을 직접 입력하면 해당 질문 중심으로 보고서가 생성됩니다.
                    입력하지 않으면 AI가 자동으로 질문을 생성합니다.
                  </p>
                  <div className="space-y-2">
                    {researchQuestions.map((q, i) => (
                      <div key={i} className="flex items-start gap-2 group">
                        <span className="text-xs text-muted-foreground mt-2 w-5 shrink-0">Q{i + 1}</span>
                        <div className="flex-1 rounded-lg border px-3 py-2 text-sm bg-muted/30">{q}</div>
                        <Button
                          variant="ghost" size="icon" className="h-8 w-8 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
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
                        placeholder="e.g., How does phosphorylation of MAPK3 at T202 regulate downstream signaling?"
                        className="flex-1 min-w-0 text-sm"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey && newQuestion.trim()) {
                            e.preventDefault();
                            setResearchQuestions([...researchQuestions, newQuestion.trim()]);
                            setNewQuestion("");
                          }
                        }}
                      />
                      <Button
                        type="button" variant="outline" size="icon" className="shrink-0 mt-1"
                        disabled={!newQuestion.trim()}
                        onClick={() => {
                          if (newQuestion.trim()) {
                            setResearchQuestions([...researchQuestions, newQuestion.trim()]);
                            setNewQuestion("");
                          }
                        }}
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
                )}

                {/* Analysis Options */}
                <div className="space-y-2">
                  <Label>Analysis Options</Label>
                  <div className="flex items-center gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      className="gap-2"
                      onClick={() => setAnalysisModalOpen(true)}
                    >
                      <SlidersHorizontal className="h-4 w-4" />
                      Configure Downsampling
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      {analysisOptions.mode === "full" && "Full Analysis (all proteins)"}
                      {analysisOptions.mode === "ptm_topn" && `PTM sites + Top ${analysisOptions.topN} proteins`}
                      {analysisOptions.mode === "log2fc_threshold" && `|Log2FC| ≥ ${analysisOptions.log2fcThreshold}`}
                      {analysisOptions.mode === "custom_count" && `Top ${analysisOptions.proteinCount} proteins`}
                      {analysisOptions.mode === "protein_list" && (analysisOptions.proteinListFile ? `Custom list: ${analysisOptions.proteinListFile.name}` : "Custom list (no file selected)")}
                    </span>
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

                <Separator />

                {/* Summary */}
                <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
                  <p className="text-sm font-medium">Order Summary</p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <span className="text-muted-foreground">Project</span>
                    <span className="font-medium">{form.project_name}</span>
                    <span className="text-muted-foreground">PTM Type</span>
                    <span className="font-medium capitalize">{form.ptm_type}</span>
                    <span className="text-muted-foreground">Species</span>
                    <span className="font-medium capitalize">{form.species}</span>
                    <span className="text-muted-foreground">Analysis Mode</span>
                    <span className="font-medium">
                      {form.analysis_mode === "ptm_only" ? "PTM-Only" : form.analysis_mode === "cross_talk" ? "Cross-Talk" : "PTM + Network"}
                    </span>
                    <span className="text-muted-foreground">Report Type</span>
                    <span className="font-medium">{form.report_type === "extended" ? "Extended" : form.report_type === "co_scientist" ? "Data-Grounded Analysis" : "Standard"}</span>
                    <span className="text-muted-foreground">Samples</span>
                    <span className="font-medium">{samples.length} configured</span>
                    <span className="text-muted-foreground">Research Questions</span>
                    <span className="font-medium">{form.report_type === "co_scientist" ? "Data-Grounded 자동 생성" : researchQuestions.length > 0 ? `${researchQuestions.length} custom` : "AI auto-generate"}</span>
                    <span className="text-muted-foreground">Downsampling</span>
                    <span className="font-medium">
                      {analysisOptions.mode === "full" ? "None (Full)" : analysisOptions.mode.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())}
                    </span>
                    <span className="text-muted-foreground">LLM (RAG Enrichment)</span>
                    <span className="font-medium font-mono text-xs">
                      {form.rag_enrichment_llm_model
                        ? (isCloudProviderSelection(form.rag_enrichment_llm_model)
                          ? `${llmModels.find((m) => `${m.provider}:${m.model_id}` === form.rag_enrichment_llm_model)?.name || form.rag_enrichment_llm_model.split(":")[0]} - ${CLOUD_MODEL_PRESETS[form.rag_enrichment_llm_model.split(":")[0] as CloudProvider]?.find((x) => x.id === (ragEnrichmentLlmCloudModelVariant || CLOUD_MODEL_PRESETS[form.rag_enrichment_llm_model.split(":")[0] as CloudProvider]?.[0]?.id))?.name || ragEnrichmentLlmCloudModelVariant || "?"}`
                          : (llmModels.find((m) => `${m.provider}:${m.model_id}` === form.rag_enrichment_llm_model)?.name || form.rag_enrichment_llm_model))
                        : `Default (Report model)`}
                    </span>
                    <span className="text-muted-foreground">LLM Model (Report)</span>
                    <span className="font-medium font-mono text-xs">
                      {form.llm_model
                        ? (isCloudProviderSelection(form.llm_model)
                          ? `${llmModels.find((m) => `${m.provider}:${m.model_id}` === form.llm_model)?.name || form.llm_model.split(":")[0]} - ${CLOUD_MODEL_PRESETS[form.llm_model.split(":")[0] as CloudProvider]?.find((x) => x.id === (llmCloudModelVariant || CLOUD_MODEL_PRESETS[form.llm_model.split(":")[0] as CloudProvider]?.[0]?.id))?.name || llmCloudModelVariant || "?"}`
                          : (llmModels.find((m) => `${m.provider}:${m.model_id}` === form.llm_model)?.name || form.llm_model))
                        : `Default (${defaultLlmModel})`}
                    </span>
                    <span className="text-muted-foreground">RAG Collections</span>
                    <span className="font-medium">
                      {useAllCollections
                        ? `전체 (${ragCollections.length}개)`
                        : selectedCollectionIds.length > 0
                          ? `${selectedCollectionIds.length}개 선택`
                          : "전체 (미선택 시 기본)"}
                    </span>
                  </div>
                </div>

                <div className="flex justify-between">
                  <Button variant="outline" onClick={() => goTo(2)}>
                    <ArrowLeft className="mr-2 h-4 w-4" /> Back
                  </Button>
                  <Button onClick={handleSubmit} disabled={loading}>
                    {loading ? (
                      <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Creating...</>
                    ) : (
                      "Create Order"
                    )}
                  </Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </Card>

      <AnalysisOptionsModal
        open={analysisModalOpen}
        onOpenChange={setAnalysisModalOpen}
        value={analysisOptions}
        onChange={setAnalysisOptions}
      />

      {/* Copy from Order Dialog */}
      <Dialog open={copyFromOpen} onOpenChange={setCopyFromOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Copy className="h-5 w-5" /> Copy from Order
            </DialogTitle>
            <DialogDescription>
              Cell Type, Treatment, Time Points, Biological Question, Special Conditions만 가져옵니다. Order name 등 다른 정보는 새로 입력하세요.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[320px] overflow-y-auto space-y-1 py-2">
            {copyFromOrders.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">등록된 Order가 없습니다.</p>
            ) : (
              copyFromOrders.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  onClick={() => handleCopyFromOrder(o.id)}
                  disabled={copyFromLoading}
                  className={cn(
                    "w-full flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-colors",
                    "hover:bg-muted/50 hover:border-muted-foreground/30",
                    copyFromLoading && "opacity-60 cursor-not-allowed",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm truncate">{o.project_name || o.order_code}</p>
                    <p className="text-xs text-muted-foreground truncate">{o.order_code}</p>
                  </div>
                  <Badge variant="secondary" className="text-[10px] shrink-0">{o.status}</Badge>
                  {copyFromLoading && <Loader2 className="h-4 w-4 animate-spin shrink-0" />}
                </button>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
