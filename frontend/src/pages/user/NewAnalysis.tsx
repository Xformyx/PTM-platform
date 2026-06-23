/**
 * NewAnalysis — Simplified analysis request for general users.
 * 
 * Flow:
 * Step 1: Upload files (pr_matrix, pg_matrix, FASTA) + describe experiment
 * Step 2: AI auto-infers sample config → user confirms (Yes/No)
 * Step 3: Analysis starts
 */
import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Upload,
  FileText,
  Database,
  Sparkles,
  Check,
  X,
  Loader2,
  ArrowRight,
  ArrowLeft,
  AlertCircle,
  BookOpen,
  MessageSquare,
  Dna,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────
interface UploadedFile {
  name: string;
  size: number;
  type: "raw_data" | "fasta" | "reference_paper";
  file: File;
}

interface InferredConfig {
  project_name: string;
  ptm_type: "phosphorylation" | "ubiquitylation";
  organism: string;
  conditions: string[];
  contrasts: Array<{ treatment: string; control: string }>;
  sample_mapping: Array<{
    filename: string;
    shortname: string;
    condition: string;
    replicate: number;
  }>;
  detected_modifications: string[];
  confidence: "high" | "medium" | "low";
  reasoning: string;
}

type Step = "upload" | "confirm" | "running";

// ── Component ──────────────────────────────────────────────────────────────
export default function NewAnalysis() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("upload");
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [description, setDescription] = useState("");
  const [researchQuestion, setResearchQuestion] = useState("");
  const [inferring, setInferring] = useState(false);
  const [inferredConfig, setInferredConfig] = useState<InferredConfig | null>(null);
  const [inferError, setInferError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [editingField, setEditingField] = useState<string | null>(null);
  const [correctionText, setCorrectionText] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── File handling ──────────────────────────────────────────────────────
  const detectFileType = (filename: string): UploadedFile["type"] => {
    const lower = filename.toLowerCase();
    if (lower.endsWith(".mzml")) return "raw_data";
    if (lower.endsWith(".fasta") || lower.endsWith(".fa")) return "fasta";
    return "reference_paper";
  };

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || []);
    const newFiles: UploadedFile[] = selectedFiles.map((f) => ({
      name: f.name,
      size: f.size,
      type: detectFileType(f.name),
      file: f,
    }));
    setFiles((prev) => [...prev, ...newFiles]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const hasRawData = files.some((f) => f.type === "raw_data");
  const hasFasta = files.some((f) => f.type === "fasta");
  const canProceed = hasRawData && hasFasta && description.trim().length > 0;

  // ── AI Inference ───────────────────────────────────────────────────────
  const handleInfer = async () => {
    setInferring(true);
    setInferError(null);

    try {
      const formData = new FormData();
      files.forEach((f) => {
        formData.append("files", f.file);
        formData.append("file_types", f.type);
      });
      formData.append("description", description);
      if (researchQuestion) formData.append("research_question", researchQuestion);

      const result = await fetch("/api/orders/infer-config", {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("ptm-token")}` },
        body: formData,
      });

      if (!result.ok) throw new Error("Failed to infer configuration");
      const config: InferredConfig = await result.json();
      setInferredConfig(config);
      setStep("confirm");
    } catch (err: any) {
      setInferError(err.message || "AI inference failed. Please try again.");
    } finally {
      setInferring(false);
    }
  };

  // ── Correction via natural language ────────────────────────────────────
  const handleCorrection = async () => {
    if (!correctionText.trim() || !inferredConfig) return;
    setInferring(true);
    try {
      const result = await fetch("/api/orders/correct-config", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("ptm-token")}`,
        },
        body: JSON.stringify({
          current_config: inferredConfig,
          correction: correctionText,
        }),
      });
      if (!result.ok) throw new Error("Correction failed");
      const updated: InferredConfig = await result.json();
      setInferredConfig(updated);
      setCorrectionText("");
      setEditingField(null);
    } catch (err: any) {
      setInferError(err.message);
    } finally {
      setInferring(false);
    }
  };

  // ── Submit Analysis ────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!inferredConfig) return;
    setSubmitting(true);
    try {
      const formData = new FormData();
      files.forEach((f) => {
        formData.append("files", f.file);
        formData.append("file_types", f.type);
      });
      formData.append("config", JSON.stringify(inferredConfig));
      formData.append("description", description);
      if (researchQuestion) formData.append("research_question", researchQuestion);

      const result = await fetch("/api/orders/create-from-user", {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("ptm-token")}` },
        body: formData,
      });

      if (!result.ok) throw new Error("Failed to create analysis");
      const { order_id } = await result.json();
      navigate(`/app/${order_id}`);
    } catch (err: any) {
      setInferError(err.message);
      setSubmitting(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">New Analysis</h1>
        <p className="text-muted-foreground mt-1">
          mzML 파일을 업로드하고 실험을 설명해주세요. Mekii가 자동으로 처리합니다.
        </p>
      </div>

      {/* Progress Steps */}
      <div className="flex items-center gap-3 mb-8">
        {[
          { id: "upload", label: "Upload & Describe" },
          { id: "confirm", label: "AI Configuration" },
          { id: "running", label: "Analysis" },
        ].map((s, i) => (
          <div key={s.id} className="flex items-center gap-2">
            <div
              className={`h-8 w-8 rounded-full flex items-center justify-center text-sm font-medium ${
                step === s.id
                  ? "bg-primary text-primary-foreground"
                  : ["upload", "confirm", "running"].indexOf(step) > i
                  ? "bg-primary/20 text-primary"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {["upload", "confirm", "running"].indexOf(step) > i ? (
                <Check className="h-4 w-4" />
              ) : (
                i + 1
              )}
            </div>
            <span className={`text-sm ${step === s.id ? "font-medium" : "text-muted-foreground"}`}>
              {s.label}
            </span>
            {i < 2 && <ArrowRight className="h-4 w-4 text-muted-foreground mx-2" />}
          </div>
        ))}
      </div>

      {/* ═══ Step 1: Upload & Describe ═══ */}
      {step === "upload" && (
        <div className="space-y-6">
          {/* File Upload */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Upload className="h-4 w-4" />
                Upload Files
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Required files info */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className={`p-3 rounded-lg border-2 border-dashed ${hasRawData ? "border-green-300 bg-green-50 dark:bg-green-900/10" : "border-muted"}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <FileText className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium">질량분석 데이터</span>
                    {hasRawData && <Check className="h-3 w-3 text-green-600" />}
                  </div>
                  <p className="text-xs text-muted-foreground">.mzML 파일 (Thermo Orbitrap Tribrid급 이상, DIA 모드 권장)</p>
                </div>
                <div className={`p-3 rounded-lg border-2 border-dashed ${hasFasta ? "border-green-300 bg-green-50 dark:bg-green-900/10" : "border-muted"}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <Dna className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium">protein.fasta</span>
                    {hasFasta && <Check className="h-3 w-3 text-green-600" />}
                  </div>
                  <p className="text-xs text-muted-foreground">Protein FASTA DB (데이터 검색에 사용할 FASTA)</p>
                </div>
              </div>

              {/* Processing info */}
              <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
                <p className="text-xs text-primary">
                  💡 업로드된 mzML 파일은 Mekii의 자체 개발 search engine이 자동으로 PTM 정량 분석을 시작합니다.
                </p>
              </div>

              {/* File input */}
              <div className="flex items-center gap-3">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".mzml,.mzML,.fasta,.fa,.pdf"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                <Button variant="outline" onClick={() => fileInputRef.current?.click()} className="gap-2">
                  <Upload className="h-4 w-4" />
                  Select Files
                </Button>
                <span className="text-xs text-muted-foreground">
                  Supported: .mzML, .fasta, .fa, .pdf (reference papers)
                </span>
              </div>

              {/* File list */}
              {files.length > 0 && (
                <div className="space-y-2">
                  {files.map((f, i) => (
                    <div key={i} className="flex items-center gap-3 p-2 rounded-lg bg-muted/50">
                      <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-sm flex-1 truncate">{f.name}</span>
                      <Badge variant="outline" className="text-[10px] shrink-0">
                        {f.type.replace("_", " ")}
                      </Badge>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {(f.size / 1024 / 1024).toFixed(1)} MB
                      </span>
                      <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={() => removeFile(i)}>
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Experiment Description */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Describe Your Experiment
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="description" className="text-sm">
                  Experiment Description <span className="text-destructive">*</span>
                </Label>
                <textarea
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="e.g., HeLa cells treated with EGF 10ng/mL for 0, 5, 15, 30 minutes. 3 biological replicates per condition. Control is serum-free (SF) condition."
                  className="mt-1.5 w-full min-h-[100px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring resize-y"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Include: cell type, treatment, time points, replicates, control condition
                </p>
              </div>

              <Separator />

              <div>
                <Label htmlFor="question" className="text-sm flex items-center gap-2">
                  <BookOpen className="h-3.5 w-3.5" />
                  Research Question (optional)
                </Label>
                <textarea
                  id="question"
                  value={researchQuestion}
                  onChange={(e) => setResearchQuestion(e.target.value)}
                  placeholder="e.g., What is the mechanism of action (MoA) of EGF signaling in HeLa cells? Which kinases are activated in the early response?"
                  className="mt-1.5 w-full min-h-[80px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring resize-y"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  This guides the AI report generation. The report will focus on answering this question.
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Reference Papers */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                Reference Papers (optional)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-3">
                Upload relevant papers (PDF). These will be indexed into ChromaDB and used by the AI
                to provide more contextual analysis and literature-grounded interpretations.
              </p>
              {files.filter((f) => f.type === "reference_paper").length > 0 ? (
                <div className="space-y-2">
                  {files
                    .filter((f) => f.type === "reference_paper")
                    .map((f, i) => (
                      <div key={i} className="flex items-center gap-2 text-sm">
                        <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="truncate">{f.name}</span>
                        <Badge variant="secondary" className="text-[10px]">PDF</Badge>
                      </div>
                    ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  No reference papers uploaded. You can add PDFs using the file selector above.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Submit Button */}
          <div className="flex justify-end">
            <Button
              size="lg"
              disabled={!canProceed || inferring}
              onClick={handleInfer}
              className="gap-2"
            >
              {inferring ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  AI is analyzing your files...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Let AI Configure
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </div>

          {inferError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{inferError}</AlertDescription>
            </Alert>
          )}
        </div>
      )}

      {/* ═══ Step 2: AI Configuration Confirmation ═══ */}
      {step === "confirm" && inferredConfig && (
        <div className="space-y-6">
          <Alert className="border-primary/30 bg-primary/5">
            <Sparkles className="h-4 w-4 text-primary" />
            <AlertTitle className="text-primary">AI Configuration Complete</AlertTitle>
            <AlertDescription>
              Mekii AI has analyzed your files and inferred the following settings.
              Please review and confirm.
              <Badge variant="outline" className="ml-2">
                Confidence: {inferredConfig.confidence}
              </Badge>
            </AlertDescription>
          </Alert>

          {/* Inferred Configuration Display */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Inferred Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Project Name</Label>
                  <p className="font-medium">{inferredConfig.project_name}</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">PTM Type</Label>
                  <p className="font-medium capitalize">{inferredConfig.ptm_type}</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Organism</Label>
                  <p className="font-medium">{inferredConfig.organism}</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Detected Modifications</Label>
                  <div className="flex flex-wrap gap-1 mt-0.5">
                    {inferredConfig.detected_modifications.map((mod) => (
                      <Badge key={mod} variant="secondary" className="text-[10px]">{mod}</Badge>
                    ))}
                  </div>
                </div>
              </div>

              <Separator />

              {/* Conditions */}
              <div>
                <Label className="text-xs text-muted-foreground">Conditions</Label>
                <div className="flex flex-wrap gap-1 mt-1">
                  {inferredConfig.conditions.map((cond) => (
                    <Badge key={cond} variant="outline">{cond}</Badge>
                  ))}
                </div>
              </div>

              {/* Contrasts */}
              <div>
                <Label className="text-xs text-muted-foreground">Comparisons</Label>
                <div className="space-y-1 mt-1">
                  {inferredConfig.contrasts.map((c, i) => (
                    <div key={i} className="text-sm">
                      <span className="font-medium">{c.treatment}</span>
                      <span className="text-muted-foreground mx-2">vs</span>
                      <span>{c.control}</span>
                    </div>
                  ))}
                </div>
              </div>

              <Separator />

              {/* Sample Mapping Table */}
              <div>
                <Label className="text-xs text-muted-foreground">Sample Mapping</Label>
                <div className="mt-2 rounded-lg border overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium">File</th>
                        <th className="text-left px-3 py-2 font-medium">Condition</th>
                        <th className="text-left px-3 py-2 font-medium">Replicate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inferredConfig.sample_mapping.map((s, i) => (
                        <tr key={i} className="border-t">
                          <td className="px-3 py-1.5 font-mono text-xs truncate max-w-[200px]">{s.shortname}</td>
                          <td className="px-3 py-1.5">{s.condition}</td>
                          <td className="px-3 py-1.5">{s.replicate}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* AI Reasoning */}
              <div className="p-3 rounded-lg bg-muted/30 border">
                <Label className="text-xs text-muted-foreground flex items-center gap-1">
                  <Sparkles className="h-3 w-3" /> AI Reasoning
                </Label>
                <p className="text-sm mt-1">{inferredConfig.reasoning}</p>
              </div>
            </CardContent>
          </Card>

          {/* Correction Input */}
          {editingField && (
            <Card className="border-amber-200 dark:border-amber-800">
              <CardContent className="py-4 space-y-3">
                <Label className="text-sm font-medium">What needs to be corrected?</Label>
                <textarea
                  value={correctionText}
                  onChange={(e) => setCorrectionText(e.target.value)}
                  placeholder="e.g., 'rep3 파일은 Control이 아니라 EGF 조건이야' or 'Organism should be Mouse, not Human'"
                  className="w-full min-h-[60px] rounded-md border border-input bg-background px-3 py-2 text-sm resize-y"
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleCorrection} disabled={inferring} className="gap-1">
                    {inferring ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                    Re-infer
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => { setEditingField(null); setCorrectionText(""); }}>
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {inferError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{inferError}</AlertDescription>
            </Alert>
          )}

          {/* Action Buttons */}
          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={() => setStep("upload")} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={() => setEditingField("general")}
                className="gap-2"
              >
                <X className="h-4 w-4" />
                No, Correct This
              </Button>
              <Button
                size="lg"
                onClick={handleSubmit}
                disabled={submitting}
                className="gap-2"
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Starting Analysis...
                  </>
                ) : (
                  <>
                    <Check className="h-4 w-4" />
                    Yes, Start Analysis
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ═══ Step 3: Running (redirect happens, but show progress if still on page) ═══ */}
      {step === "running" && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Loader2 className="h-12 w-12 animate-spin text-primary mb-4" />
            <h3 className="text-lg font-semibold mb-2">Analysis Started</h3>
            <p className="text-muted-foreground text-center">
              Redirecting to your analysis page...
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
