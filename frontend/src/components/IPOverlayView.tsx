/**
 * IPOverlayView.tsx
 * ────────────────────────────────────────────────────────────────────────────
 * IP (Immunoprecipitation) Overlay Analysis View
 *
 * Allows users to upload IP data (bait + prey proteins) and cross-reference
 * with PTM substrate data to reveal:
 *   1. Which prey proteins are PTM substrates in the dataset
 *   2. Temporal activity changes of prey proteins after bait removal
 *   3. Which kinase modules contain prey proteins as substrates
 *   4. Signal chain connections (Receptor → Kinase → IP Prey as substrate)
 */
import { useState, useMemo, useCallback } from "react";
import {
  Loader2,
  Upload,
  Target,
  Activity,
  Network,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Trash2,
  FileSpreadsheet,
  Zap,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import * as XLSX from "xlsx";

// ── Types ────────────────────────────────────────────────────────────────────

interface PtmTimeSeriesRow {
  gene: string;
  position: string;
  condition: string;
  value: number;
  control_pseudocount_used?: boolean;
  q_value?: number | null;
}

interface GlobalKinaseModule {
  kinase: string;
  canonical: string;
  sources: string[];
  source_count: number;
  members: { key: string; gene: string; position: string; membership: string; evidence: string }[];
  total_count: number;
}

interface InferredReceptor {
  name: string;
  receptor_class: string;
  via_kinases?: string[];
  downstream_ptm_count: number;
  downstream_ptms: string[];
  confidence_score?: number;
}

interface PreyProtein {
  gene: string;
  log2fc: number;
  q_value?: number;
  spectral_count?: number;
  unique_peptides?: number;
}

interface CrossRefResult {
  // Prey found as PTM substrates
  substrates: {
    gene: string;
    position: string;
    conditions: { condition: string; fc: number; q_value?: number | null }[];
    kinases: string[];
  }[];
  // Prey found as kinase in modules
  kinases: {
    gene: string;
    module_name: string;
    substrate_count: number;
    substrates: string[];
  }[];
  // Prey connected to receptor signaling
  receptor_chain: {
    prey_gene: string;
    role: "substrate" | "kinase";
    receptor: string;
    receptor_class: string;
    via_kinase?: string;
    confidence?: number;
  }[];
  // Prey not found in any analysis
  not_found: string[];
}

interface IPOverlayViewProps {
  orderId: number;
  vectorData: PtmTimeSeriesRow[];
  conditions: string[];
  globalKinaseModules: GlobalKinaseModule[] | null;
  inferredReceptors: InferredReceptor[];
  savedIpData?: {
    bait: string;
    condition: string;
    prey_proteins: PreyProtein[];
    cross_reference: CrossRefResult;
  } | null;
}

// ── Component ────────────────────────────────────────────────────────────────

export default function IPOverlayView({
  orderId,
  vectorData,
  conditions,
  globalKinaseModules,
  inferredReceptors,
  savedIpData,
}: IPOverlayViewProps) {
  const [bait, setBait] = useState(savedIpData?.bait || "");
  const [conditionLabel, setConditionLabel] = useState(savedIpData?.condition || "");
  const [preyProteins, setPreyProteins] = useState<PreyProtein[]>(savedIpData?.prey_proteins || []);
  const [crossRef, setCrossRef] = useState<CrossRefResult | null>(savedIpData?.cross_reference || null);
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState<string>("");

  // ── File Upload Handler ──────────────────────────────────────────────────

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);

    const data = await file.arrayBuffer();
    const workbook = XLSX.read(data, { type: "array" });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);

    // Parse prey proteins from Excel
    const parsed: PreyProtein[] = [];
    for (const row of rows) {
      // Try common column names
      const gene = (row["Gene"] || row["gene"] || row["Prey"] || row["prey"] || row["Gene names"] || row["Protein"] || "") as string;
      const log2fc = parseFloat(String(row["Log2FC"] || row["log2fc"] || row["Log2_FC"] || row["Fold_Enrichment"] || row["FC"] || "0"));
      const qVal = parseFloat(String(row["q_value"] || row["Q_Value"] || row["FDR"] || row["adj_pvalue"] || ""));
      const sc = parseInt(String(row["Spectral_Count"] || row["spectral_count"] || row["SC"] || "0"));
      const up = parseInt(String(row["Unique_Peptides"] || row["unique_peptides"] || row["UP"] || "0"));

      if (gene && gene.trim()) {
        parsed.push({
          gene: gene.trim().toUpperCase(),
          log2fc: isNaN(log2fc) ? 0 : log2fc,
          q_value: isNaN(qVal) ? undefined : qVal,
          spectral_count: isNaN(sc) ? undefined : sc,
          unique_peptides: isNaN(up) ? undefined : up,
        });
      }
    }

    setPreyProteins(parsed);
  }, []);

  // ── Cross-Reference Analysis ─────────────────────────────────────────────

  const runCrossReference = useCallback(() => {
    if (preyProteins.length === 0) return;
    setLoading(true);

    // Build gene→positions map from vectorData
    const genePositions: Record<string, { position: string; conditions: { condition: string; fc: number; q_value?: number | null }[] }[]> = {};
    for (const row of vectorData) {
      const g = row.gene.toUpperCase();
      if (!genePositions[g]) genePositions[g] = [];
      const existing = genePositions[g].find((p) => p.position === row.position);
      if (existing) {
        existing.conditions.push({ condition: row.condition, fc: row.value, q_value: row.q_value });
      } else {
        genePositions[g] = [...(genePositions[g] || []), { position: row.position, conditions: [{ condition: row.condition, fc: row.value, q_value: row.q_value }] }];
      }
    }

    // Build kinase→substrates map from globalKinaseModules
    const kinaseSubstrates: Record<string, { gene: string; position: string }[]> = {};
    const substrateKinases: Record<string, string[]> = {};
    if (globalKinaseModules) {
      for (const mod of globalKinaseModules) {
        kinaseSubstrates[mod.kinase.toUpperCase()] = mod.members.map((m) => ({ gene: m.gene, position: m.position }));
        for (const m of mod.members) {
          const key = m.gene.toUpperCase();
          if (!substrateKinases[key]) substrateKinases[key] = [];
          if (!substrateKinases[key].includes(mod.kinase)) {
            substrateKinases[key].push(mod.kinase);
          }
        }
      }
    }

    // Build receptor→kinase map
    const kinaseReceptorMap: Record<string, { receptor: string; receptor_class: string; confidence?: number }[]> = {};
    for (const rec of inferredReceptors) {
      for (const k of rec.via_kinases || []) {
        const ku = k.toUpperCase();
        if (!kinaseReceptorMap[ku]) kinaseReceptorMap[ku] = [];
        kinaseReceptorMap[ku].push({ receptor: rec.name, receptor_class: rec.receptor_class, confidence: rec.confidence_score });
      }
    }

    const substrates: CrossRefResult["substrates"] = [];
    const kinases: CrossRefResult["kinases"] = [];
    const receptorChain: CrossRefResult["receptor_chain"] = [];
    const notFound: string[] = [];
    const processedGenes = new Set<string>();

    for (const prey of preyProteins) {
      const g = prey.gene.toUpperCase();
      let found = false;

      // Check if prey is a PTM substrate
      if (genePositions[g]) {
        found = true;
        for (const pos of genePositions[g]) {
          substrates.push({
            gene: prey.gene,
            position: pos.position,
            conditions: pos.conditions,
            kinases: substrateKinases[g] || [],
          });
        }
        // Check receptor chain for substrate
        const ks = substrateKinases[g] || [];
        for (const k of ks) {
          const recs = kinaseReceptorMap[k.toUpperCase()] || [];
          for (const r of recs) {
            if (!processedGenes.has(`${g}_sub_${r.receptor}`)) {
              receptorChain.push({
                prey_gene: prey.gene,
                role: "substrate",
                receptor: r.receptor,
                receptor_class: r.receptor_class,
                via_kinase: k,
                confidence: r.confidence,
              });
              processedGenes.add(`${g}_sub_${r.receptor}`);
            }
          }
        }
      }

      // Check if prey is a kinase in modules
      if (kinaseSubstrates[g]) {
        found = true;
        kinases.push({
          gene: prey.gene,
          module_name: g,
          substrate_count: kinaseSubstrates[g].length,
          substrates: kinaseSubstrates[g].slice(0, 10).map((s) => `${s.gene} ${s.position}`),
        });
        // Check receptor chain for kinase
        const recs = kinaseReceptorMap[g] || [];
        for (const r of recs) {
          if (!processedGenes.has(`${g}_kin_${r.receptor}`)) {
            receptorChain.push({
              prey_gene: prey.gene,
              role: "kinase",
              receptor: r.receptor,
              receptor_class: r.receptor_class,
              confidence: r.confidence,
            });
            processedGenes.add(`${g}_kin_${r.receptor}`);
          }
        }
      }

      if (!found) {
        notFound.push(prey.gene);
      }
    }

    const result: CrossRefResult = { substrates, kinases, receptor_chain: receptorChain, not_found: notFound };
    setCrossRef(result);
    setLoading(false);

    // Save to backend
    api.post(`/orders/${orderId}/save-ip-overlay-data`, {
      bait,
      condition: conditionLabel,
      prey_proteins: preyProteins,
      cross_reference: result,
    }).catch((err) => console.warn("Failed to save IP overlay data:", err));
  }, [preyProteins, vectorData, globalKinaseModules, inferredReceptors, orderId, bait, conditionLabel]);

  // ── Clear ────────────────────────────────────────────────────────────────

  const handleClear = () => {
    setPreyProteins([]);
    setCrossRef(null);
    setFileName("");
    setBait("");
    setConditionLabel("");
  };

  // ── Summary Stats ────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    if (!crossRef) return null;
    return {
      totalPrey: preyProteins.length,
      asSubstrate: crossRef.substrates.length,
      asKinase: crossRef.kinases.length,
      inReceptorChain: crossRef.receptor_chain.length,
      notFound: crossRef.not_found.length,
      uniqueKinases: [...new Set(crossRef.substrates.flatMap((s) => s.kinases))].length,
      uniqueReceptors: [...new Set(crossRef.receptor_chain.map((r) => r.receptor))].length,
    };
  }, [crossRef, preyProteins]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Upload Section */}
      <div className="border rounded-lg p-4 bg-muted/20">
        <div className="flex items-center gap-2 mb-3">
          <Target className="h-4 w-4 text-cyan-500" />
          <span className="text-sm font-semibold">IP Data Upload</span>
          {fileName && (
            <Badge variant="outline" className="text-xs ml-2">
              <FileSpreadsheet className="h-3 w-3 mr-1" /> {fileName}
            </Badge>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
          <div>
            <Label className="text-xs text-muted-foreground">Bait Protein</Label>
            <Input
              value={bait}
              onChange={(e) => setBait(e.target.value)}
              placeholder="e.g. PDCD5"
              className="h-8 text-xs"
            />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Condition</Label>
            <Input
              value={conditionLabel}
              onChange={(e) => setConditionLabel(e.target.value)}
              placeholder="e.g. PDCD5 knockout"
              className="h-8 text-xs"
            />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">IP Data File (.xlsx)</Label>
            <Input
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={handleFileUpload}
              className="h-8 text-xs"
            />
          </div>
          <div className="flex items-end gap-2">
            <Button
              size="sm"
              className="h-8 text-xs"
              disabled={preyProteins.length === 0 || loading}
              onClick={runCrossReference}
            >
              {loading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Zap className="h-3 w-3 mr-1" />}
              Cross-Reference
            </Button>
            {crossRef && (
              <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={handleClear}>
                <Trash2 className="h-3 w-3 mr-1" /> Clear
              </Button>
            )}
          </div>
        </div>

        {preyProteins.length > 0 && !crossRef && (
          <p className="text-xs text-muted-foreground">
            {preyProteins.length} prey proteins loaded. Click "Cross-Reference" to analyze.
          </p>
        )}
      </div>

      {/* Results */}
      {crossRef && stats && (
        <div className="space-y-4">
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <SummaryCard label="Total Prey" value={stats.totalPrey} icon={<Target className="h-3.5 w-3.5" />} color="text-slate-400" />
            <SummaryCard label="As Substrate" value={stats.asSubstrate} icon={<Activity className="h-3.5 w-3.5" />} color="text-green-400" />
            <SummaryCard label="As Kinase" value={stats.asKinase} icon={<Zap className="h-3.5 w-3.5" />} color="text-amber-400" />
            <SummaryCard label="In Signal Chain" value={stats.inReceptorChain} icon={<Network className="h-3.5 w-3.5" />} color="text-cyan-400" />
            <SummaryCard label="Not Found" value={stats.notFound} icon={<AlertTriangle className="h-3.5 w-3.5" />} color="text-red-400" />
          </div>

          {/* Interpretation Banner */}
          {bait && (
            <div className="border border-cyan-500/30 rounded-lg p-3 bg-cyan-500/5">
              <p className="text-xs text-cyan-300">
                <strong>{bait}</strong> removal ({conditionLabel}) releases {stats.asSubstrate + stats.asKinase} interactors
                that are active in this PTM dataset.
                {stats.asKinase > 0 && ` ${stats.asKinase} are kinases controlling downstream substrates.`}
                {stats.uniqueReceptors > 0 && ` Connected to ${stats.uniqueReceptors} upstream receptor(s).`}
              </p>
            </div>
          )}

          {/* Section A: Prey as Substrates */}
          {crossRef.substrates.length > 0 && (
            <div className="border rounded-lg p-3">
              <h4 className="text-xs font-semibold mb-2 flex items-center gap-1">
                <Activity className="h-3.5 w-3.5 text-green-400" />
                Prey Proteins Found as PTM Substrates ({crossRef.substrates.length})
              </h4>
              <p className="text-[10px] text-muted-foreground mb-2">
                These {bait} interactors have PTM changes in the dataset — {bait} may have been sequestering them.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-1 px-2">Gene</th>
                      <th className="py-1 px-2">Site</th>
                      <th className="py-1 px-2">Kinase(s)</th>
                      {conditions.map((c) => (
                        <th key={c} className="py-1 px-2 text-center">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {crossRef.substrates.slice(0, 30).map((s, i) => (
                      <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-1 px-2 font-medium">{s.gene}</td>
                        <td className="py-1 px-2 text-muted-foreground">{s.position}</td>
                        <td className="py-1 px-2">
                          {s.kinases.length > 0 ? (
                            <span className="text-amber-400">{s.kinases.join(", ")}</span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        {conditions.map((c) => {
                          const cond = s.conditions.find((x) => x.condition === c);
                          const fc = cond?.fc;
                          return (
                            <td key={c} className="py-1 px-2 text-center">
                              {fc !== undefined ? (
                                <span className={fc > 0 ? "text-red-400" : fc < 0 ? "text-blue-400" : "text-muted-foreground"}>
                                  {fc > 0 ? "+" : ""}{fc.toFixed(2)}
                                </span>
                              ) : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {crossRef.substrates.length > 30 && (
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Showing 30 of {crossRef.substrates.length} substrate hits
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Section B: Prey as Kinases */}
          {crossRef.kinases.length > 0 && (
            <div className="border rounded-lg p-3">
              <h4 className="text-xs font-semibold mb-2 flex items-center gap-1">
                <Zap className="h-3.5 w-3.5 text-amber-400" />
                Prey Proteins as Kinases ({crossRef.kinases.length})
              </h4>
              <p className="text-[10px] text-muted-foreground mb-2">
                These {bait} interactors are kinases with identified substrate modules — {bait} removal may activate their kinase activity.
              </p>
              <div className="space-y-2">
                {crossRef.kinases.map((k, i) => (
                  <div key={i} className="flex items-start gap-3 p-2 rounded bg-muted/30">
                    <Badge variant="outline" className="text-xs text-amber-400 border-amber-400/50">
                      {k.gene}
                    </Badge>
                    <div className="flex-1">
                      <p className="text-xs">
                        <span className="text-muted-foreground">{k.substrate_count} substrates:</span>{" "}
                        {k.substrates.join(", ")}
                        {k.substrate_count > 10 && "..."}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Section C: Signal Chain Connections */}
          {crossRef.receptor_chain.length > 0 && (
            <div className="border rounded-lg p-3">
              <h4 className="text-xs font-semibold mb-2 flex items-center gap-1">
                <Network className="h-3.5 w-3.5 text-cyan-400" />
                Signal Chain Connections ({crossRef.receptor_chain.length})
              </h4>
              <p className="text-[10px] text-muted-foreground mb-2">
                IP prey proteins connected to upstream receptor signaling pathways.
              </p>
              <div className="space-y-1">
                {crossRef.receptor_chain.slice(0, 20).map((r, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs py-1 border-b border-border/30">
                    <Badge variant="outline" className="text-[10px] text-cyan-400 border-cyan-400/50">
                      {r.receptor}
                    </Badge>
                    <ArrowRight className="h-3 w-3 text-muted-foreground" />
                    {r.via_kinase && (
                      <>
                        <span className="text-amber-400">{r.via_kinase}</span>
                        <ArrowRight className="h-3 w-3 text-muted-foreground" />
                      </>
                    )}
                    <span className={r.role === "kinase" ? "text-amber-300 font-medium" : "text-green-300 font-medium"}>
                      {r.prey_gene}
                    </span>
                    <Badge variant="secondary" className="text-[9px] ml-auto">
                      {r.role}
                    </Badge>
                    {r.confidence && (
                      <span className="text-[9px] text-muted-foreground">{Math.round(r.confidence * 100)}%</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Section D: Not Found */}
          {crossRef.not_found.length > 0 && (
            <div className="border rounded-lg p-3 opacity-70">
              <h4 className="text-xs font-semibold mb-1 flex items-center gap-1">
                <AlertTriangle className="h-3.5 w-3.5 text-muted-foreground" />
                Not Found in PTM Data ({crossRef.not_found.length})
              </h4>
              <p className="text-[10px] text-muted-foreground">
                {crossRef.not_found.slice(0, 20).join(", ")}
                {crossRef.not_found.length > 20 && ` ... +${crossRef.not_found.length - 20} more`}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Helper Components ──────────────────────────────────────────────────────

function SummaryCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  return (
    <div className="border rounded-lg p-2 text-center">
      <div className={`flex items-center justify-center gap-1 ${color} mb-1`}>
        {icon}
        <span className="text-lg font-bold">{value}</span>
      </div>
      <p className="text-[10px] text-muted-foreground">{label}</p>
    </div>
  );
}
