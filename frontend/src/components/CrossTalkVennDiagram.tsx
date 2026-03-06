import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface DualPTMProtein {
  gene: string;
  primary_sites: string[];
  secondary_sites: string[];
  primary_ptm_type: string;
  secondary_ptm_type: string;
  shared_timepoints: string[];
  primary_timepoints: string[];
  secondary_timepoints: string[];
  concordant_ratio: number;
  pattern: 'concordant' | 'discordant' | 'mixed';
  temporal_comparison: Record<string, {
    primary_state: string;
    secondary_state: string;
    primary_ptm_log2fc: number;
    secondary_ptm_log2fc: number;
    concordant: boolean;
  }>;
}

interface CrossTalkVennDiagramProps {
  dualPTMProteins: DualPTMProtein[];
  primarySummary: {
    ptm_type: string;
    total_proteins: number;
    total_sites: number;
    timepoints: string[];
  };
  secondarySummary: {
    ptm_type: string;
    total_proteins: number;
    total_sites: number;
    timepoints: string[];
  };
  sharedNonPTM: string[];
  primaryOnlyNonPTM: string[];
  secondaryOnlyNonPTM: string[];
}

export default function CrossTalkVennDiagram({
  dualPTMProteins,
  primarySummary,
  secondarySummary,
  sharedNonPTM,
  primaryOnlyNonPTM,
  secondaryOnlyNonPTM,
}: CrossTalkVennDiagramProps) {
  const [hoveredSection, setHoveredSection] = useState<'primary' | 'secondary' | 'overlap' | 'nonptm-primary' | 'nonptm-secondary' | 'nonptm-shared' | null>(null);
  const [selectedProtein, setSelectedProtein] = useState<DualPTMProtein | null>(null);

  const pType = primarySummary.ptm_type?.charAt(0).toUpperCase() + primarySummary.ptm_type?.slice(1) || 'Primary';
  const sType = secondarySummary.ptm_type?.charAt(0).toUpperCase() + secondarySummary.ptm_type?.slice(1) || 'Secondary';

  const primaryOnlyCount = primarySummary.total_proteins - dualPTMProteins.length;
  const secondaryOnlyCount = secondarySummary.total_proteins - dualPTMProteins.length;
  const overlapCount = dualPTMProteins.length;

  const patternCounts = useMemo(() => {
    const counts = { concordant: 0, discordant: 0, mixed: 0 };
    dualPTMProteins.forEach(p => {
      counts[p.pattern]++;
    });
    return counts;
  }, [dualPTMProteins]);

  // SVG Venn Diagram dimensions
  const width = 520;
  const height = 320;
  const cx1 = 195;
  const cx2 = 325;
  const cy = 160;
  const r = 120;

  return (
    <div className="space-y-6">
      {/* Main Venn Diagram */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            PTM Protein Overlap
          </CardTitle>
          <CardDescription>
            {pType}과 {sType} 데이터셋 간 단백질 중복 분석
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col lg:flex-row items-center gap-6">
            {/* SVG Venn */}
            <svg viewBox={`0 0 ${width} ${height}`} className="w-full max-w-[520px]" style={{ minHeight: 280 }}>
              <defs>
                <clipPath id="clip-left">
                  <circle cx={cx1} cy={cy} r={r} />
                </clipPath>
                <clipPath id="clip-right">
                  <circle cx={cx2} cy={cy} r={r} />
                </clipPath>
              </defs>

              {/* Left circle (Primary) */}
              <circle
                cx={cx1} cy={cy} r={r}
                fill={hoveredSection === 'primary' ? 'rgba(59,130,246,0.35)' : 'rgba(59,130,246,0.18)'}
                stroke="rgb(59,130,246)"
                strokeWidth={2}
                className="cursor-pointer transition-all duration-200"
                onMouseEnter={() => setHoveredSection('primary')}
                onMouseLeave={() => setHoveredSection(null)}
              />

              {/* Right circle (Secondary) */}
              <circle
                cx={cx2} cy={cy} r={r}
                fill={hoveredSection === 'secondary' ? 'rgba(245,158,11,0.35)' : 'rgba(245,158,11,0.18)'}
                stroke="rgb(245,158,11)"
                strokeWidth={2}
                className="cursor-pointer transition-all duration-200"
                onMouseEnter={() => setHoveredSection('secondary')}
                onMouseLeave={() => setHoveredSection(null)}
              />

              {/* Overlap region (drawn on top) */}
              <g clipPath="url(#clip-left)">
                <circle
                  cx={cx2} cy={cy} r={r}
                  fill={hoveredSection === 'overlap' ? 'rgba(16,185,129,0.45)' : 'rgba(16,185,129,0.28)'}
                  className="cursor-pointer transition-all duration-200"
                  onMouseEnter={() => setHoveredSection('overlap')}
                  onMouseLeave={() => setHoveredSection(null)}
                />
              </g>

              {/* Labels */}
              <text x={cx1 - 50} y={cy - 15} textAnchor="middle" className="fill-blue-700 font-bold text-sm" style={{ fontSize: 14 }}>
                {pType}
              </text>
              <text x={cx1 - 50} y={cy + 8} textAnchor="middle" className="fill-blue-600 text-xs" style={{ fontSize: 12 }}>
                {primaryOnlyCount} only
              </text>

              <text x={cx2 + 50} y={cy - 15} textAnchor="middle" className="fill-amber-700 font-bold text-sm" style={{ fontSize: 14 }}>
                {sType}
              </text>
              <text x={cx2 + 50} y={cy + 8} textAnchor="middle" className="fill-amber-600 text-xs" style={{ fontSize: 12 }}>
                {secondaryOnlyCount} only
              </text>

              {/* Overlap count */}
              <text x={(cx1 + cx2) / 2} y={cy - 10} textAnchor="middle" className="fill-emerald-700 font-bold" style={{ fontSize: 20 }}>
                {overlapCount}
              </text>
              <text x={(cx1 + cx2) / 2} y={cy + 10} textAnchor="middle" className="fill-emerald-600 text-xs" style={{ fontSize: 11 }}>
                Dual-PTM
              </text>

              {/* Total counts at bottom */}
              <text x={cx1} y={height - 10} textAnchor="middle" className="fill-muted-foreground" style={{ fontSize: 11 }}>
                Total: {primarySummary.total_proteins} proteins, {primarySummary.total_sites} sites
              </text>
              <text x={cx2} y={height - 10} textAnchor="middle" className="fill-muted-foreground" style={{ fontSize: 11 }}>
                Total: {secondarySummary.total_proteins} proteins, {secondarySummary.total_sites} sites
              </text>
            </svg>

            {/* Legend & Stats */}
            <div className="space-y-4 min-w-[200px]">
              <div className="space-y-2">
                <h4 className="font-semibold text-sm">Dual-PTM Pattern</h4>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-emerald-500" />
                    <span className="text-sm">Concordant: {patternCounts.concordant}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-rose-500" />
                    <span className="text-sm">Discordant: {patternCounts.discordant}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-slate-400" />
                    <span className="text-sm">Mixed: {patternCounts.mixed}</span>
                  </div>
                </div>
              </div>

              {sharedNonPTM.length > 0 && (
                <div className="space-y-2">
                  <h4 className="font-semibold text-sm">Shared Non-PTM Interactors</h4>
                  <p className="text-xs text-muted-foreground">
                    {sharedNonPTM.length} proteins regulated by both networks
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Hover info panel */}
          {hoveredSection && (
            <div className="mt-4 p-3 bg-muted/50 rounded-lg border text-sm animate-in fade-in duration-200">
              {hoveredSection === 'primary' && (
                <p><strong>{pType} Only:</strong> {primaryOnlyCount} proteins exclusively modified by {pType}. These represent {pType}-specific signaling targets.</p>
              )}
              {hoveredSection === 'secondary' && (
                <p><strong>{sType} Only:</strong> {secondaryOnlyCount} proteins exclusively modified by {sType}. These represent {sType}-specific regulatory targets.</p>
              )}
              {hoveredSection === 'overlap' && (
                <p><strong>Dual-PTM Overlap:</strong> {overlapCount} proteins modified by BOTH {pType} and {sType}. These are potential cross-talk hubs where two PTM signals converge.</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dual-PTM Protein List */}
      {dualPTMProteins.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Dual-PTM Proteins ({dualPTMProteins.length})</CardTitle>
            <CardDescription>
              {pType}과 {sType} 두 가지 PTM이 모두 관찰된 단백질 목록
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              {dualPTMProteins.map((protein) => (
                <Tooltip key={protein.gene}>
                  <TooltipTrigger asChild>
                    <button
                      className={`p-2 rounded-lg border text-left transition-all hover:shadow-md ${
                        selectedProtein?.gene === protein.gene ? 'ring-2 ring-primary' : ''
                      } ${
                        protein.pattern === 'concordant' ? 'border-emerald-200 bg-emerald-50/50 hover:bg-emerald-50' :
                        protein.pattern === 'discordant' ? 'border-rose-200 bg-rose-50/50 hover:bg-rose-50' :
                        'border-slate-200 bg-slate-50/50 hover:bg-slate-50'
                      }`}
                      onClick={() => setSelectedProtein(selectedProtein?.gene === protein.gene ? null : protein)}
                    >
                      <p className="font-mono font-semibold text-sm truncate">{protein.gene}</p>
                      <div className="flex items-center gap-1 mt-1">
                        <Badge variant="outline" className={`text-[10px] px-1 py-0 ${
                          protein.pattern === 'concordant' ? 'border-emerald-300 text-emerald-700' :
                          protein.pattern === 'discordant' ? 'border-rose-300 text-rose-700' :
                          'border-slate-300 text-slate-600'
                        }`}>
                          {protein.pattern === 'concordant' ? 'C' : protein.pattern === 'discordant' ? 'D' : 'M'}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">{(protein.concordant_ratio * 100).toFixed(0)}%</span>
                      </div>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p className="font-semibold">{protein.gene}</p>
                    <p className="text-xs">{pType} sites: {protein.primary_sites.join(', ') || 'N/A'}</p>
                    <p className="text-xs">{sType} sites: {protein.secondary_sites.join(', ') || 'N/A'}</p>
                    <p className="text-xs">Concordant ratio: {(protein.concordant_ratio * 100).toFixed(1)}%</p>
                  </TooltipContent>
                </Tooltip>
              ))}
            </div>

            {/* Selected protein detail */}
            {selectedProtein && (
              <div className="mt-4 p-4 bg-muted/30 rounded-lg border animate-in slide-in-from-top-2 duration-200">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="font-bold text-lg">{selectedProtein.gene}</h4>
                  <Badge className={
                    selectedProtein.pattern === 'concordant' ? 'bg-emerald-100 text-emerald-800' :
                    selectedProtein.pattern === 'discordant' ? 'bg-rose-100 text-rose-800' :
                    'bg-slate-100 text-slate-800'
                  }>
                    {selectedProtein.pattern.toUpperCase()} ({(selectedProtein.concordant_ratio * 100).toFixed(1)}%)
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-4 text-sm mb-3">
                  <div>
                    <p className="text-muted-foreground font-medium">{pType} Sites</p>
                    <p className="font-mono">{selectedProtein.primary_sites.join(', ') || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground font-medium">{sType} Sites</p>
                    <p className="font-mono">{selectedProtein.secondary_sites.join(', ') || 'N/A'}</p>
                  </div>
                </div>

                {/* Temporal comparison table */}
                {Object.keys(selectedProtein.temporal_comparison).length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm border-collapse">
                      <thead>
                        <tr className="border-b">
                          <th className="text-left py-1.5 px-2 font-medium">Timepoint</th>
                          <th className="text-center py-1.5 px-2 font-medium">{pType} State</th>
                          <th className="text-center py-1.5 px-2 font-medium">{pType} Log2FC</th>
                          <th className="text-center py-1.5 px-2 font-medium">{sType} State</th>
                          <th className="text-center py-1.5 px-2 font-medium">{sType} Log2FC</th>
                          <th className="text-center py-1.5 px-2 font-medium">Pattern</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(selectedProtein.temporal_comparison).map(([tp, comp]) => (
                          <tr key={tp} className="border-b last:border-0">
                            <td className="py-1.5 px-2 font-mono">{tp}</td>
                            <td className="text-center py-1.5 px-2">
                              <Badge variant="outline" className={`text-xs ${
                                comp.primary_state === 'active' ? 'border-blue-300 text-blue-700' : 'border-purple-300 text-purple-700'
                              }`}>
                                {comp.primary_state}
                              </Badge>
                            </td>
                            <td className={`text-center py-1.5 px-2 font-mono ${
                              comp.primary_ptm_log2fc > 0 ? 'text-red-600' : 'text-blue-600'
                            }`}>
                              {comp.primary_ptm_log2fc.toFixed(2)}
                            </td>
                            <td className="text-center py-1.5 px-2">
                              <Badge variant="outline" className={`text-xs ${
                                comp.secondary_state === 'active' ? 'border-amber-300 text-amber-700' : 'border-purple-300 text-purple-700'
                              }`}>
                                {comp.secondary_state}
                              </Badge>
                            </td>
                            <td className={`text-center py-1.5 px-2 font-mono ${
                              comp.secondary_ptm_log2fc > 0 ? 'text-red-600' : 'text-blue-600'
                            }`}>
                              {comp.secondary_ptm_log2fc.toFixed(2)}
                            </td>
                            <td className="text-center py-1.5 px-2">
                              {comp.concordant ? (
                                <span className="text-emerald-600 font-semibold">Concordant</span>
                              ) : (
                                <span className="text-rose-600 font-semibold">Discordant</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
