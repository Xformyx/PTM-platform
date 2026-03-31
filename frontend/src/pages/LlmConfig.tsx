import { useEffect, useState, useRef } from "react";
import {
  Brain, Cloud, RefreshCw, Plus, Loader2, CheckCircle2,
  Thermometer, Hash, Download, Trash2, AlertCircle, HardDrive,
  Pencil, FlaskConical, X, ShieldCheck, ShieldOff,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { LlmModel } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { StaggerContainer, StaggerItem } from "@/components/motion/stagger-children";

import { CLOUD_PROVIDER_SENTINEL } from "@/lib/llm-models";

interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
  parameter_size: string;
  family: string;
  quantization: string;
}

interface TestResult {
  status: "ok" | "error" | "skipped" | "testing";
  detail?: string;
  response?: string;
}

function formatSize(bytes: number): string {
  if (bytes === 0) return "";
  const gb = bytes / (1024 ** 3);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${(bytes / (1024 ** 2)).toFixed(0)} MB`;
}

export default function LlmConfig() {
  const { isAdmin } = useAuth();
  const [models, setModels] = useState<LlmModel[]>([]);
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [pullModalOpen, setPullModalOpen] = useState(false);
  const [pullModelName, setPullModelName] = useState("");
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState("");
  const [pullPct, setPullPct] = useState(0);
  const [pullError, setPullError] = useState("");
  const [deletingModel, setDeletingModel] = useState("");
  const [addCloudOpen, setAddCloudOpen] = useState(false);
  const [addCloudSubmitting, setAddCloudSubmitting] = useState(false);
  const [addCloudForm, setAddCloudForm] = useState({
    name: "Gemini", provider: "gemini" as "gemini" | "openai" | "anthropic", api_key: "",
  });

  // Edit state
  const [editModel, setEditModel] = useState<LlmModel | null>(null);
  const [editApiKey, setEditApiKey] = useState("");
  const [editSubmitting, setEditSubmitting] = useState(false);

  // Test state: modelId → result
  const [testResults, setTestResults] = useState<Record<number, TestResult>>({});

  const abortRef = useRef<AbortController | null>(null);

  const loadAll = async () => {
    try {
      const [dbData, ollamaData] = await Promise.all([
        api.get<{ models: LlmModel[] }>("/llm/models"),
        api.get<{ models: OllamaModel[] }>("/llm/ollama/running").catch(() => ({ models: [] })),
      ]);
      setModels(dbData.models);
      setOllamaModels(ollamaData.models);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const handleSyncOllama = async () => {
    setSyncing(true);
    try {
      await api.post<{ synced: string[] }>("/llm/models/sync-ollama");
      await loadAll();
    } finally {
      setSyncing(false);
    }
  };

  const handlePull = async () => {
    if (!pullModelName.trim()) return;
    setPulling(true);
    setPullError("");
    setPullStatus("Preparing...");
    setPullPct(0);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const resp = await fetch("/api/llm/ollama/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_name: pullModelName.trim() }),
        signal: controller.signal,
      });

      const reader = resp.body?.getReader();
      if (!reader) throw new Error("No stream");

      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const lines = buf.split("\n");
        buf = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.error) {
              setPullError(data.error);
              setPulling(false);
              return;
            }
            setPullStatus(data.status || "");
            setPullPct(data.pct || 0);
          } catch { /* ignore */ }
        }
      }

      setPullStatus("Done! Syncing models...");
      await handleSyncOllama();
      setPullStatus("Complete");
      setPullPct(100);
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setPullError(e.message || "Pull failed");
      }
    } finally {
      setPulling(false);
      abortRef.current = null;
    }
  };

  const handleDelete = async (modelName: string) => {
    if (!confirm(`Delete model "${modelName}" from Ollama? This cannot be undone.`)) return;
    setDeletingModel(modelName);
    try {
      await api.post("/llm/ollama/delete", { model_name: modelName });
      await loadAll();
    } catch (e: any) {
      alert(e.message || "Delete failed");
    } finally {
      setDeletingModel("");
    }
  };

  const handleAddCloudModel = async () => {
    if (!addCloudForm.name.trim()) return;
    setAddCloudSubmitting(true);
    try {
      await api.post("/llm/models", {
        name: addCloudForm.name.trim(),
        provider: addCloudForm.provider,
        model_id: CLOUD_PROVIDER_SENTINEL,
        api_key: addCloudForm.api_key.trim() || undefined,
      });
      await loadAll();
      setAddCloudOpen(false);
      setAddCloudForm({ name: "Gemini", provider: "gemini", api_key: "" });
    } catch (e: any) {
      alert(e.response?.data?.detail || e.message || "Failed to add model");
    } finally {
      setAddCloudSubmitting(false);
    }
  };

  const handleEditSave = async () => {
    if (!editModel) return;
    setEditSubmitting(true);
    try {
      await api.put(`/llm/models/${editModel.id}`, {
        api_key: editApiKey.trim() || undefined,
      });
      await loadAll();
      setEditModel(null);
      setEditApiKey("");
      // Clear test result for this model so it re-tests fresh
      setTestResults((prev) => {
        const next = { ...prev };
        delete next[editModel.id];
        return next;
      });
    } catch (e: any) {
      alert(e.response?.data?.detail || e.message || "Failed to update API key");
    } finally {
      setEditSubmitting(false);
    }
  };

  /** Test a cloud model's API key via /health/cloud-llm (uses .env key)
   *  or directly against the provider using the DB key via /llm/models/:id/test */
  const handleTestModel = async (m: LlmModel) => {
    setTestResults((prev) => ({ ...prev, [m.id]: { status: "testing" } }));
    try {
      // Use the existing model test endpoint
      const res = await api.post<{ status: string; response_preview?: string; detail?: string }>(
        `/llm/models/${m.id}/test`
      );
      if (res.status === "ok") {
        setTestResults((prev) => ({
          ...prev,
          [m.id]: { status: "ok", response: res.response_preview || "OK" },
        }));
      } else if (res.status === "skipped") {
        // Fallback: call /health/cloud-llm for gemini/openai
        const health = await api.get<Record<string, { status: string; detail?: string; response_preview?: string }>>(
          "/health/cloud-llm"
        );
        const providerResult = health[m.provider];
        if (!providerResult) {
          setTestResults((prev) => ({
            ...prev,
            [m.id]: { status: "error", detail: "Provider not supported in health check" },
          }));
          return;
        }
        setTestResults((prev) => ({
          ...prev,
          [m.id]: {
            status: providerResult.status === "ok" ? "ok" : "error",
            detail: providerResult.detail,
            response: providerResult.response_preview,
          },
        }));
      } else {
        setTestResults((prev) => ({
          ...prev,
          [m.id]: { status: "error", detail: res.detail || "Unknown error" },
        }));
      }
    } catch (e: any) {
      setTestResults((prev) => ({
        ...prev,
        [m.id]: { status: "error", detail: e.message || "Request failed" },
      }));
    }
  };

  const closePullModal = () => {
    if (pulling && abortRef.current) {
      abortRef.current.abort();
    }
    setPullModalOpen(false);
    setPullModelName("");
    setPullStatus("");
    setPullPct(0);
    setPullError("");
    setPulling(false);
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-40" />)}
        </div>
      </div>
    );
  }

  const grouped = {
    ollama: models.filter((m) => m.provider === "ollama"),
    cloud: models.filter((m) => m.provider !== "ollama"),
  };

  const getOllamaDetail = (modelId: string) =>
    ollamaModels.find((m) => m.name === modelId);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">LLM Models</h1>
          <p className="text-sm text-muted-foreground">
            {models.length} models configured · Ollama: {ollamaModels.length} installed
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleSyncOllama} disabled={syncing} className="gap-2">
            <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing..." : "Sync Ollama"}
          </Button>
          <Button onClick={() => setPullModalOpen(true)} className="gap-2">
            <Download className="h-4 w-4" /> Pull Model
          </Button>
        </div>
      </div>

      {/* Ollama Models */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Brain className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Ollama Models</h2>
        </div>
        {ollamaModels.length > 0 ? (
          <StaggerContainer className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {ollamaModels.map((m) => {
              const dbModel = grouped.ollama.find((db) => db.model_id === m.name);
              return (
                <StaggerItem key={m.name}>
                  <Card className="group">
                    <CardContent className="p-5">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="font-mono text-sm font-semibold truncate flex-1">{m.name}</h3>
                        <div className="flex items-center gap-1.5">
                          {dbModel?.is_active ? (
                            <Badge variant="success" className="gap-1 text-[10px]">
                              <CheckCircle2 className="h-3 w-3" /> Active
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="text-[10px]">Not synced</Badge>
                          )}
                          {isAdmin && (
                            <Button
                              variant="ghost" size="icon"
                              className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-destructive hover:text-destructive"
                              onClick={() => handleDelete(m.name)}
                              disabled={deletingModel === m.name}
                            >
                              {deletingModel === m.name
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <Trash2 className="h-3.5 w-3.5" />}
                            </Button>
                          )}
                        </div>
                      </div>
                      <Separator className="mb-3" />
                      <div className="space-y-1.5 text-xs text-muted-foreground">
                        <div className="flex items-center gap-2">
                          <HardDrive className="h-3 w-3" />
                          <span>{formatSize(m.size)}</span>
                          {m.parameter_size && <span>· {m.parameter_size}</span>}
                        </div>
                        {m.family && (
                          <div className="flex items-center gap-2">
                            <Hash className="h-3 w-3" />
                            <span>{m.family}{m.quantization ? ` · ${m.quantization}` : ""}</span>
                          </div>
                        )}
                        {dbModel && (
                          <div className="flex items-center gap-2">
                            <Thermometer className="h-3 w-3" />
                            <span>Temp: {dbModel.default_temp} / Max: {dbModel.max_tokens}</span>
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </StaggerItem>
              );
            })}
          </StaggerContainer>
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Brain className="h-12 w-12 text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground">No local models detected</p>
              <p className="text-xs text-muted-foreground mt-1">Pull a model or check Ollama is running</p>
            </CardContent>
          </Card>
        )}
      </section>

      {/* Cloud Models */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Cloud className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">Cloud Models</h2>
          </div>
          <Button variant="outline" size="sm" onClick={() => setAddCloudOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" /> Add Cloud Model
          </Button>
        </div>
        {grouped.cloud.length > 0 ? (
          <StaggerContainer className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {grouped.cloud.map((m) => {
              const testResult = testResults[m.id];
              return (
                <StaggerItem key={m.id}>
                  <Card>
                    <CardContent className="p-5">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold">{m.name}</h3>
                        <Badge variant="info">{m.provider}</Badge>
                      </div>
                      <Separator className="mb-3" />
                      <div className="space-y-1.5 text-xs text-muted-foreground mb-3">
                        <div>Model: <span className="font-mono">{m.model_id === CLOUD_PROVIDER_SENTINEL ? "(Order 시 선택)" : m.model_id}</span></div>
                        <div className="flex items-center gap-1">
                          API Key:
                          {m.has_api_key ? (
                            <Badge variant="success" className="text-[10px] ml-1">Configured</Badge>
                          ) : (
                            <Badge variant="warning" className="text-[10px] ml-1">Not set</Badge>
                          )}
                        </div>
                        {/* Test Result */}
                        {testResult && testResult.status !== "testing" && (
                          <div className={`flex items-start gap-1.5 mt-1 p-1.5 rounded text-[10px] ${
                            testResult.status === "ok"
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                              : "bg-destructive/10 text-destructive"
                          }`}>
                            {testResult.status === "ok"
                              ? <ShieldCheck className="h-3 w-3 mt-0.5 shrink-0" />
                              : <ShieldOff className="h-3 w-3 mt-0.5 shrink-0" />}
                            <span className="break-all">
                              {testResult.status === "ok"
                                ? `OK${testResult.response ? ` — "${testResult.response}"` : ""}`
                                : testResult.detail || "Error"}
                            </span>
                          </div>
                        )}
                      </div>
                      {/* Action buttons */}
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs gap-1 flex-1"
                          onClick={() => handleTestModel(m)}
                          disabled={testResult?.status === "testing"}
                        >
                          {testResult?.status === "testing"
                            ? <Loader2 className="h-3 w-3 animate-spin" />
                            : <FlaskConical className="h-3 w-3" />}
                          {testResult?.status === "testing" ? "Testing..." : "Test"}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs gap-1 flex-1"
                          onClick={() => {
                            setEditModel(m);
                            setEditApiKey("");
                          }}
                        >
                          <Pencil className="h-3 w-3" /> Edit Key
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                </StaggerItem>
              );
            })}
          </StaggerContainer>
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Cloud className="h-12 w-12 text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground">No cloud models configured</p>
              <p className="text-xs text-muted-foreground mt-1">Add Gemini, OpenAI, or Anthropic models</p>
            </CardContent>
          </Card>
        )}
      </section>

      {/* Pull Model Modal */}
      <Dialog open={pullModalOpen} onOpenChange={(v) => !v && closePullModal()}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Download className="h-5 w-5" /> Pull Ollama Model
            </DialogTitle>
            <DialogDescription>
              Enter a model name from <a href="https://ollama.com/library" target="_blank" rel="noopener noreferrer" className="underline text-primary">ollama.com/library</a>
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 pt-2">
            <div className="flex gap-2">
              <Input
                placeholder="e.g. gemma3:27b, qwen2.5:14b, llama3.1:latest"
                value={pullModelName}
                onChange={(e) => setPullModelName(e.target.value)}
                disabled={pulling}
                onKeyDown={(e) => e.key === "Enter" && !pulling && handlePull()}
              />
              <Button onClick={handlePull} disabled={pulling || !pullModelName.trim()} className="gap-2 shrink-0">
                {pulling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {pulling ? "Pulling..." : "Pull"}
              </Button>
            </div>

            {(pulling || pullStatus) && (
              <div className="space-y-2 p-3 rounded-lg bg-muted/50">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground truncate flex-1">{pullStatus}</span>
                  <span className="text-xs font-mono font-semibold ml-2">{pullPct}%</span>
                </div>
                <Progress value={pullPct} className="h-2" />
              </div>
            )}

            {pullError && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span className="text-xs">{pullError}</span>
              </div>
            )}

            {pullStatus === "Complete" && !pullError && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                <span className="text-xs font-medium">Model pulled successfully!</span>
              </div>
            )}

            <div className="text-[10px] text-muted-foreground space-y-1">
              <p>Popular models: gemma3:27b, qwen2.5:14b, llama3.1:latest, mistral, phi4</p>
              <p>Use <code className="px-1 bg-muted rounded">model:tag</code> format for specific versions</p>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Cloud Model Modal */}
      <Dialog open={addCloudOpen} onOpenChange={setAddCloudOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Cloud className="h-5 w-5" /> Add Cloud Model
            </DialogTitle>
            <DialogDescription>
              Cloud LLM API 키만 등록합니다. Order Create 또는 Re-run 시 세부 모델(gemini-2.5-flash 등)을 선택할 수 있습니다.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">Provider</label>
              <select
                className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
                value={addCloudForm.provider}
                onChange={(e) => {
                  const p = e.target.value as "gemini" | "openai" | "anthropic";
                  const defaultName = p === "gemini" ? "Gemini" : p === "openai" ? "OpenAI" : "Anthropic";
                  setAddCloudForm((f) => ({ ...f, provider: p, name: defaultName }));
                }}
              >
                <option value="gemini">Gemini</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Display Name</label>
              <Input
                placeholder="e.g. Gemini (Order Create에서 표시)"
                value={addCloudForm.name}
                onChange={(e) => setAddCloudForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">API Key (optional)</label>
              <Input
                type="password"
                placeholder="Leave empty to use .env"
                value={addCloudForm.api_key}
                onChange={(e) => setAddCloudForm((f) => ({ ...f, api_key: e.target.value }))}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setAddCloudOpen(false)}>Cancel</Button>
              <Button onClick={handleAddCloudModel} disabled={addCloudSubmitting || !addCloudForm.name.trim()}>
                {addCloudSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Add
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Edit API Key Modal */}
      <Dialog open={!!editModel} onOpenChange={(open) => { if (!open) { setEditModel(null); setEditApiKey(""); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Pencil className="h-5 w-5" /> Edit API Key — {editModel?.name}
            </DialogTitle>
            <DialogDescription>
              새 API 키를 입력하면 기존 키를 교체합니다. 비워두면 변경되지 않습니다.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                New API Key
                <span className="ml-1 text-xs text-muted-foreground">
                  ({editModel?.has_api_key ? "현재 설정됨 — 교체" : "현재 없음 — 새로 등록"})
                </span>
              </label>
              <Input
                type="password"
                placeholder="새 API 키 입력..."
                value={editApiKey}
                onChange={(e) => setEditApiKey(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !editSubmitting && editApiKey.trim() && handleEditSave()}
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button
                variant="outline"
                onClick={() => { setEditModel(null); setEditApiKey(""); }}
                disabled={editSubmitting}
              >
                <X className="h-4 w-4 mr-1" /> Cancel
              </Button>
              <Button
                onClick={handleEditSave}
                disabled={editSubmitting || !editApiKey.trim()}
              >
                {editSubmitting
                  ? <Loader2 className="h-4 w-4 animate-spin mr-1" />
                  : <CheckCircle2 className="h-4 w-4 mr-1" />}
                Save Key
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
