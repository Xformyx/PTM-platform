import { useEffect, useState, useRef } from "react";
import {
  Brain, Cloud, RefreshCw, Plus, Loader2, CheckCircle2,
  Thermometer, Hash, Download, Trash2, AlertCircle, HardDrive, X,
} from "lucide-react";
import { api } from "@/lib/api";
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

interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
  parameter_size: string;
  family: string;
  quantization: string;
}

function formatSize(bytes: number): string {
  if (bytes === 0) return "";
  const gb = bytes / (1024 ** 3);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${(bytes / (1024 ** 2)).toFixed(0)} MB`;
}

export default function LlmConfig() {
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
        <div className="flex items-center gap-2 mb-4">
          <Cloud className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Cloud Models</h2>
        </div>
        {grouped.cloud.length > 0 ? (
          <StaggerContainer className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {grouped.cloud.map((m) => (
              <StaggerItem key={m.id}>
                <Card>
                  <CardContent className="p-5">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-semibold">{m.name}</h3>
                      <Badge variant="info">{m.provider}</Badge>
                    </div>
                    <Separator className="mb-3" />
                    <div className="space-y-1.5 text-xs text-muted-foreground">
                      <div>Model: <span className="font-mono">{m.model_id}</span></div>
                      <div>API Key: {m.has_api_key ? (
                        <Badge variant="success" className="text-[10px] ml-1">Configured</Badge>
                      ) : (
                        <Badge variant="warning" className="text-[10px] ml-1">Not set</Badge>
                      )}</div>
                    </div>
                  </CardContent>
                </Card>
              </StaggerItem>
            ))}
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
    </div>
  );
}
