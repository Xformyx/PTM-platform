import { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check, Upload, AlertCircle, ArrowLeft, ArrowRight, Loader2,
  FileSpreadsheet, Regex, Trash2, SlidersHorizontal, Brain,
  Plus, X, MessageSquare, Network, FlaskConical, BookOpen,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { AnalysisOptions } from "@/lib/types";
import { DEFAULT_ANALYSIS_OPTIONS } from "@/lib/types";
import AnalysisOptionsModal from "@/components/AnalysisOptionsModal";

const STEPS = ["Project & Files", "Sample Config", "Analysis Focus", "Report Options"];

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
    report_type: "comprehensive", top_n_ptms: 20, llm_model: "", rag_llm_model: "",
    analysis_mode: "ptm_only" as "ptm_only" | "ptm_nonptm_network",
  });
  const [researchQuestions, setResearchQuestions] = useState<string[]>([]);
  const [newQuestion, setNewQuestion] = useState("");
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [defaultLlmModel, setDefaultLlmModel] = useState("");
  const [files, setFiles] = useState<{
    pr_matrix: File | null; pg_matrix: File | null; config_file: File | null;
  }>({ pr_matrix: null, pg_matrix: null, config_file: null });

  // Step 1: Sample Config
  const [sampleColumns, setSampleColumns] = useState<string[]>([]);
  const [samples, setSamples] = useState<SampleEntry[]>([]);
  const [regexPattern, setRegexPattern] = useState("_([^_]+?)_(\\d+)\\.\\w+$");
  const [controlKeyword, setControlKeyword] = useState("control");
  const [parseTab, setParseTab] = useState("auto");
  const [configParsing, setConfigParsing] = useState(false);

  // Analysis Options
  const [analysisOptions, setAnalysisOptions] = useState<AnalysisOptions>({ ...DEFAULT_ANALYSIS_OPTIONS });
  const [analysisModalOpen, setAnalysisModalOpen] = useState(false);

  const goTo = useCallback((s: number) => {
    setDirection(s > step ? 1 : -1);
    setStep(s);
  }, [step]);

  // Load Ollama models and default LLM config
  useEffect(() => {
    api.get<{ default_model: string }>("/system/llm-config").then((c) => {
      setDefaultLlmModel(c.default_model);
    }).catch(() => {});
    api.get<{ models: { name: string; is_active: boolean }[] }>("/llm/models").then((d) => {
      const names = d.models.filter((m) => m.is_active).map((m) => m.name);
      setOllamaModels(names);
    }).catch(() => {});
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
    if (samples.length === 0) {
      setError("Sample configuration is required. Go back to Step 2 and configure samples.");
      return;
    }

    setLoading(true);
    setError("");

    const sampleConfig = {
      source: parseTab === "auto" ? "auto_parse" : "xlsx",
      regex_pattern: parseTab === "auto" ? regexPattern : undefined,
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
    formData.append("report_options", JSON.stringify({
      report_type: form.report_type, top_n_ptms: form.top_n_ptms, output_format: "md",
      analysis_mode: form.analysis_mode,
      research_questions: researchQuestions.length > 0 ? researchQuestions : [],
      ...(form.llm_model ? { llm_model: form.llm_model, llm_provider: "ollama" } : {}),
      ...(form.rag_llm_model ? { rag_llm_model: form.rag_llm_model } : {}),
    }));
    const { proteinListFile, ...analysisOptsForJson } = analysisOptions;
    formData.append("analysis_options", JSON.stringify(analysisOptsForJson));
    formData.append("pr_matrix", files.pr_matrix);
    formData.append("pg_matrix", files.pg_matrix);
    if (files.config_file) formData.append("config_file", files.config_file);
    if (analysisOptions.mode === "protein_list" && proteinListFile) {
      formData.append("protein_list", proteinListFile);
    }

    try {
      const result = await api.upload<{ id: number; order_code: string }>("/orders", formData);
      navigate(`/orders/${result.id}`);
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
                        <SelectItem value="ubiquitination">Ubiquitination</SelectItem>
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
                {/* Analysis Mode Selection */}
                <div className="space-y-3">
                  <Label className="text-sm font-semibold">Analysis Mode</Label>
                  <div className="grid grid-cols-2 gap-3">
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
                  </div>
                </div>

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
                  <Input value={form.treatment}
                    onChange={(e) => setForm({ ...form, treatment: e.target.value })}
                    placeholder="e.g., Irisin stimulation"
                  />
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
                    <Select value={form.report_type} onValueChange={(v) => setForm({ ...form, report_type: v })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="comprehensive">Standard Report</SelectItem>
                        <SelectItem value="extended">Extended (+ Drug Repositioning)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-[10px] text-muted-foreground">
                      {form.report_type === "extended"
                        ? "Drug target prioritization 및 repositioning 분석 포함"
                        : "PTM 분석, 가설 검증, 네트워크 분석 기반 보고서"}
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Top N PTMs to Analyze</Label>
                    <Input type="number" value={form.top_n_ptms}
                      onChange={(e) => setForm({ ...form, top_n_ptms: parseInt(e.target.value) || 20 })}
                      min={5} max={100}
                    />
                  </div>
                </div>

                {/* LLM Model for Paper Read (RAG Enrichment) */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <BookOpen className="h-4 w-4" /> LLM Model for Paper Read
                  </Label>
                  <Select
                    value={form.rag_llm_model || ""}
                    onValueChange={(v) => setForm({ ...form, rag_llm_model: v === "__default__" ? "" : v })}
                  >
                    <SelectTrigger><SelectValue placeholder={`Default (${defaultLlmModel || "auto"})`} /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">
                        Default ({defaultLlmModel || "auto"})
                      </SelectItem>
                      {ollamaModels.map((m) => (
                        <SelectItem key={m} value={m}>{m}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    논문 읽기 및 요약(RAG Enrichment)에서 사용할 LLM 모델. Abstract 분석, 키나제 예측, 기능적 영향 분석에 사용됩니다.
                  </p>
                </div>

                {/* LLM Model for Report Generation */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Brain className="h-4 w-4" /> LLM Model for Report Generation
                  </Label>
                  <Select
                    value={form.llm_model || ""}
                    onValueChange={(v) => setForm({ ...form, llm_model: v === "__default__" ? "" : v })}
                  >
                    <SelectTrigger><SelectValue placeholder={`Default (${defaultLlmModel || "auto"})`} /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">
                        Default ({defaultLlmModel || "auto"})
                      </SelectItem>
                      {ollamaModels.map((m) => (
                        <SelectItem key={m} value={m}>{m}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Report Generation에서 사용할 LLM 모델. Default는 서버 설정({defaultLlmModel || "env"})을 따릅니다.
                  </p>
                </div>

                {/* Research Questions */}
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
                    <div className="flex gap-2">
                      <Input
                        value={newQuestion}
                        onChange={(e) => setNewQuestion(e.target.value)}
                        placeholder="e.g., How does phosphorylation of MAPK3 at T202 regulate downstream signaling?"
                        className="text-sm"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newQuestion.trim()) {
                            setResearchQuestions([...researchQuestions, newQuestion.trim()]);
                            setNewQuestion("");
                          }
                        }}
                      />
                      <Button
                        type="button" variant="outline" size="icon" className="shrink-0"
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
                    <span className="font-medium">{form.analysis_mode === "ptm_only" ? "PTM-Only" : "PTM + Network"}</span>
                    <span className="text-muted-foreground">Report Type</span>
                    <span className="font-medium">{form.report_type === "extended" ? "Extended" : "Standard"}</span>
                    <span className="text-muted-foreground">Samples</span>
                    <span className="font-medium">{samples.length} configured</span>
                    <span className="text-muted-foreground">Research Questions</span>
                    <span className="font-medium">{researchQuestions.length > 0 ? `${researchQuestions.length} custom` : "AI auto-generate"}</span>
                    <span className="text-muted-foreground">Downsampling</span>
                    <span className="font-medium">
                      {analysisOptions.mode === "full" ? "None (Full)" : analysisOptions.mode.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())}
                    </span>
                    <span className="text-muted-foreground">LLM Model (Report)</span>
                    <span className="font-medium font-mono text-xs">
                      {form.llm_model || `Default (${defaultLlmModel})`}
                    </span>
                    <span className="text-muted-foreground">LLM Model (Paper Read)</span>
                    <span className="font-medium font-mono text-xs">
                      {form.rag_llm_model || `Default (${defaultLlmModel})`}
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
    </div>
  );
}
