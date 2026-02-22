import { useState, useRef } from "react";
import {
  Layers, Filter, Hash, FileText, Upload, Zap, Info,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { AnalysisMode, AnalysisOptions } from "@/lib/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: AnalysisOptions;
  onChange: (opts: AnalysisOptions) => void;
}

const OPTIONS: {
  mode: AnalysisMode;
  label: string;
  icon: typeof Layers;
  desc: string;
  detail: string;
}[] = [
  {
    mode: "full",
    label: "Option 1: Full Analysis",
    icon: Layers,
    desc: "Analyze all proteins without filtering",
    detail: "All unique proteins in the dataset will be enriched via UniProt, InterPro, STRING-DB, and KEGG. This provides the most comprehensive results but takes the longest.",
  },
  {
    mode: "ptm_topn",
    label: "Option 2: PTM Sites + Top N",
    icon: Zap,
    desc: "All PTM sites + Top N proteins by |Log2FC|",
    detail: "Always includes all PTM-modified proteins. Additionally selects the Top N proteins ranked by absolute Log2 Fold Change. Recommended for balanced speed vs. coverage.",
  },
  {
    mode: "log2fc_threshold",
    label: "Option 3: Log2FC Threshold",
    icon: Filter,
    desc: "Only proteins with |Log2FC| above threshold",
    detail: "Includes all PTM sites plus any protein whose absolute Log2 Fold Change exceeds the specified threshold. Lower threshold = more proteins.",
  },
  {
    mode: "custom_count",
    label: "Option 4: Custom Protein Count",
    icon: Hash,
    desc: "Select top N proteins by significance",
    detail: "Selects the top N proteins ordered by absolute Log2 Fold Change. PTM sites are always included regardless of the count.",
  },
  {
    mode: "protein_list",
    label: "Option 5: Custom Protein List",
    icon: FileText,
    desc: "Upload a .txt file with target protein IDs",
    detail: "Upload a text file listing one protein ID (UniProt accession) per line. Only these proteins will be enriched. PTM sites are always included.",
  },
];

export default function AnalysisOptionsModal({ open, onOpenChange, value, onChange }: Props) {
  const [local, setLocal] = useState<AnalysisOptions>({ ...value });
  const fileRef = useRef<HTMLInputElement>(null);

  const handleOpen = (o: boolean) => {
    if (o) setLocal({ ...value });
    onOpenChange(o);
  };

  const handleSave = () => {
    onChange({ ...local });
    onOpenChange(false);
  };

  const selected = OPTIONS.find((o) => o.mode === local.mode);

  return (
    <Dialog open={open} onOpenChange={handleOpen}>
      <DialogContent className="sm:max-w-[600px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Filter className="h-5 w-5" /> Analysis Options
          </DialogTitle>
          <DialogDescription>
            Choose how many proteins to include in biological enrichment. Fewer proteins = faster analysis.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = local.mode === opt.mode;
            return (
              <button
                key={opt.mode}
                type="button"
                onClick={() => setLocal((p) => ({ ...p, mode: opt.mode }))}
                className={cn(
                  "w-full rounded-lg border p-3 text-left transition-all",
                  active
                    ? "border-primary bg-primary/5 ring-1 ring-primary/30"
                    : "border-border hover:border-muted-foreground/50 hover:bg-muted/30",
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cn(
                    "mt-0.5 rounded-md p-1.5",
                    active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                  )}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={cn("text-sm font-medium", active && "text-primary")}>{opt.label}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{opt.desc}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Parameter inputs for the selected option */}
        {selected && local.mode !== "full" && (
          <>
            <Separator />
            <div className="space-y-4">
              <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/50 rounded-lg p-3">
                <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                <span>{selected.detail}</span>
              </div>

              {local.mode === "ptm_topn" && (
                <div className="grid gap-2 max-w-xs">
                  <Label htmlFor="topN" className="text-sm">Top N proteins (by |Log2FC|)</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="topN"
                      type="number"
                      min={50}
                      max={10000}
                      value={local.topN ?? 500}
                      onChange={(e) => setLocal((p) => ({ ...p, topN: parseInt(e.target.value) || 500 }))}
                      className="w-28"
                    />
                    <span className="text-xs text-muted-foreground">+ all PTM sites</span>
                  </div>
                </div>
              )}

              {local.mode === "log2fc_threshold" && (
                <div className="grid gap-2 max-w-xs">
                  <Label htmlFor="threshold" className="text-sm">|Log2FC| Threshold</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="threshold"
                      type="number"
                      min={0.1}
                      max={5}
                      step={0.1}
                      value={local.log2fcThreshold ?? 0.5}
                      onChange={(e) =>
                        setLocal((p) => ({ ...p, log2fcThreshold: parseFloat(e.target.value) || 0.5 }))
                      }
                      className="w-28"
                    />
                    <span className="text-xs text-muted-foreground">+ all PTM sites</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Proteins with |Protein_Log2FC| &ge; this value will be included.
                  </p>
                </div>
              )}

              {local.mode === "custom_count" && (
                <div className="grid gap-2 max-w-xs">
                  <Label htmlFor="proteinCount" className="text-sm">Number of proteins</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="proteinCount"
                      type="number"
                      min={50}
                      max={20000}
                      value={local.proteinCount ?? 1000}
                      onChange={(e) =>
                        setLocal((p) => ({ ...p, proteinCount: parseInt(e.target.value) || 1000 }))
                      }
                      className="w-28"
                    />
                    <span className="text-xs text-muted-foreground">+ all PTM sites</span>
                  </div>
                </div>
              )}

              {local.mode === "protein_list" && (
                <div className="space-y-3">
                  <Label className="text-sm">Protein List (.txt)</Label>
                  <div
                    className={cn(
                      "flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-5 transition-colors cursor-pointer",
                      local.proteinListFile
                        ? "border-primary/50 bg-primary/5"
                        : "border-muted-foreground/25 hover:border-muted-foreground/50",
                    )}
                    onClick={() => fileRef.current?.click()}
                  >
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".txt"
                      className="sr-only"
                      onChange={(e) => {
                        const f = e.target.files?.[0] || null;
                        setLocal((p) => ({ ...p, proteinListFile: f }));
                      }}
                    />
                    <Upload className="h-5 w-5 text-muted-foreground mb-2" />
                    {local.proteinListFile ? (
                      <p className="text-sm font-medium text-primary">{local.proteinListFile.name}</p>
                    ) : (
                      <p className="text-sm text-muted-foreground">Click to select .txt file</p>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    One protein ID per line (e.g., UniProt accession like Q9WTQ5, P12345).
                  </p>
                </div>
              )}
            </div>
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave}>Apply</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
