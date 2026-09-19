import { useEffect, useMemo, useRef, useState } from "react";
import { Download, Loader2, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { api } from "../lib/api";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { binBounds, exclusionLabels, orderedConditions, SCATTER_PALETTE, scatterAxes, viewportBounds } from "../lib/scatterOverview";
import type { Bounds, ScatterAxis, ScatterCondition, ScatterOverview } from "../lib/scatterOverview";

const MARGIN = { left: 48, right: 12, top: 15, bottom: 40 };
const HEIGHT = 280;

function ConditionChart({ condition, sourceBounds, viewport, resolution, color, axis }: {
  condition: ScatterCondition; sourceBounds: Bounds; viewport: Bounds; resolution: number; color: string; axis: ScatterAxis;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(300);
  const [hover, setHover] = useState("");
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => setWidth(Math.max(100, entries[0].contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const sx = (x: number) => MARGIN.left + (x - viewport[0]) / (viewport[1] - viewport[0]) * plotWidth;
  const sy = (y: number) => MARGIN.top + (viewport[3] - y) / (viewport[3] - viewport[2]) * plotHeight;
  useEffect(() => { setHover(""); }, [condition, viewport, axis]);
  useEffect(() => {
    const element = canvas.current, context = element?.getContext("2d");
    if (!element || !context) return;
    const ratio = window.devicePixelRatio || 1;
    element.width = Math.round(width * ratio); element.height = Math.round(HEIGHT * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, HEIGHT);
    context.font = "10px system-ui";
    context.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const x = viewport[0] + (viewport[1] - viewport[0]) * i / 4;
      const y = viewport[2] + (viewport[3] - viewport[2]) * i / 4;
      context.strokeStyle = "#d1d5db"; context.lineWidth = .5;
      context.beginPath(); context.moveTo(sx(x), MARGIN.top); context.lineTo(sx(x), HEIGHT - MARGIN.bottom); context.stroke();
      context.beginPath(); context.moveTo(MARGIN.left, sy(y)); context.lineTo(width - MARGIN.right, sy(y)); context.stroke();
      context.fillStyle = "#64748b";
      context.fillText(x.toPrecision(3), sx(x), HEIGHT - 23);
      context.save(); context.textAlign = "right"; context.fillText(y.toPrecision(3), MARGIN.left - 5, sy(y) + 3); context.restore();
    }
    context.font = "11px system-ui";
    context.fillText("Protein log₂FC", MARGIN.left + plotWidth / 2, HEIGHT - 5);
    context.save(); context.translate(12, MARGIN.top + plotHeight / 2); context.rotate(-Math.PI / 2);
    context.fillText(scatterAxes[axis].short, 0, 0); context.restore();
    context.save(); context.beginPath(); context.rect(MARGIN.left, MARGIN.top, plotWidth, plotHeight); context.clip();
    context.strokeStyle = "#ef4444"; context.lineWidth = .7; context.setLineDash([3, 3]);
    context.beginPath(); context.moveTo(sx(0), MARGIN.top); context.lineTo(sx(0), HEIGHT - MARGIN.bottom);
    context.moveTo(MARGIN.left, sy(0)); context.lineTo(width - MARGIN.right, sy(0)); context.stroke(); context.setLineDash([]);
    context.fillStyle = color;
    if (condition.mode === "points") {
      context.globalAlpha = .75;
      for (const p of condition.points) { context.beginPath(); context.arc(sx(p.x), sy(p.y), 3, 0, Math.PI * 2); context.fill(); }
    } else {
      let maximum = 1;
      for (const bin of condition.bins) maximum = Math.max(maximum, bin.count);
      for (const bin of condition.bins) {
        const b = binBounds(bin, sourceBounds, resolution);
        context.globalAlpha = .25 + .75 * Math.log1p(bin.count) / Math.log1p(maximum);
        context.fillRect(sx(b[0]), sy(b[3]), Math.max(2, sx(b[1]) - sx(b[0])), Math.max(2, sy(b[2]) - sy(b[3])));
      }
    }
    context.restore();
  }, [condition, sourceBounds, viewport, resolution, color, axis, width]);
  return <Card className="min-w-0 overflow-hidden" data-testid="scatter-condition" data-condition={condition.condition}>
    <CardHeader className="px-3 py-2">
      <CardTitle className="flex items-center gap-2 text-sm"><span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: color }} />{condition.condition}</CardTitle>
      <p className="text-xs text-muted-foreground">유효 관측행 {condition.represented_rows.toLocaleString()} · {condition.mode === "density" ? "전체 밀도 집계" : "개별 점"} · 제외 {condition.excluded_rows.toLocaleString()}</p>
    </CardHeader>
    <CardContent className="p-2">
      {condition.represented_rows === 0 ? <p className="p-4 text-sm text-muted-foreground">이 조건에 축 적격 관측이 없습니다.</p> : <>
        <canvas ref={canvas} aria-label={`${condition.condition} ${scatterAxes[axis].short} scatter`} role="img"
          className="block w-full" style={{ height: HEIGHT }} data-viewport={JSON.stringify(viewport)}
          onPointerLeave={() => setHover("")} onPointerMove={event => {
            const rect = event.currentTarget.getBoundingClientRect();
            const px = event.clientX - rect.left, py = event.clientY - rect.top;
            if (px < MARGIN.left || px > width - MARGIN.right || py < MARGIN.top || py > HEIGHT - MARGIN.bottom) { setHover(""); return; }
            if (condition.mode === "points") {
              const hits = condition.points.filter(p => Math.hypot(sx(p.x) - px, sy(p.y) - py) <= 7);
              const p = hits[0];
              setHover(p ? `${p.gene} ${p.site} · precursor ${p.precursor_id || "식별자 미해결"} · charge ${p.charge || "?"} · protein ${p.protein_group || "?"} · taxon ${p.taxon || "?"} · P=${p.x} · ${scatterAxes[axis].short}=${p.y} · 원본 행 ${p.source_row}${hits.length > 1 ? ` · 인접 관측 ${hits.length}행 (각 값은 원본 TSV)` : ""}` : "");
            } else {
              const hit = condition.bins.find(bin => {
                const b = binBounds(bin, sourceBounds, resolution);
                // Constant axes have zero-width source ranges; use the same
                // minimum painted footprint while reporting the exact range.
                return px >= sx(b[0]) && px <= sx(b[0]) + Math.max(2, sx(b[1]) - sx(b[0]))
                  && py >= sy(b[3]) && py <= sy(b[3]) + Math.max(2, sy(b[2]) - sy(b[3]));
              });
              const b = hit && binBounds(hit, sourceBounds, resolution);
              setHover(hit && b ? `구간 관측 ${hit.count}행 · P [${b[0].toPrecision(4)}, ${b[1].toPrecision(4)}] · ${scatterAxes[axis].short} [${b[2].toPrecision(4)}, ${b[3].toPrecision(4)}] · 개별 precursor 값은 원본 TSV에서 확인` : "");
            }
          }} />
        <p role="status" className="min-h-10 break-words px-2 text-xs text-muted-foreground" data-testid="scatter-hover">{hover || "점 또는 밀도 구간에 마우스를 올려 값을 확인하세요."}</p>
      </>}
    </CardContent>
  </Card>;
}

export function VectorScatterPlots({ orderId }: { orderId: number }) {
  const [axis, setAxis] = useState<ScatterAxis>("adjusted");
  const [zoom, setZoom] = useState(1), [retry, setRetry] = useState(0);
  const [state, setState] = useState<{ key: string; data?: ScatterOverview; error?: string }>({ key: "" });
  const [downloadError, setDownloadError] = useState("");
  const requestKey = `${orderId}:${axis}:${retry}`;
  useEffect(() => {
    const abort = new AbortController();
    setState({ key: requestKey }); setZoom(1); setDownloadError("");
    api.get<ScatterOverview>(`/orders/${orderId}/vector-scatter-data?axis=${axis}`, { signal: abort.signal })
      .then(data => { if (!abort.signal.aborted) setState({ key: requestKey, data }); })
      .catch(error => { if (!abort.signal.aborted) setState({ key: requestKey, error: String(error.message || error) }); });
    return () => abort.abort();
  }, [orderId, axis, requestKey]);
  const current = state.key === requestKey ? state : null;
  const data = current?.data;
  const conditions = useMemo(() => data ? orderedConditions(data.conditions) : [], [data]);
  const viewport = useMemo(() => data?.bounds ? viewportBounds(data.bounds, zoom) : null, [data, zoom]);
  return <section className="min-w-0 space-y-4" data-testid="vector-scatter">
    <div className="flex flex-wrap items-center gap-2">
      {(Object.keys(scatterAxes) as ScatterAxis[]).map(value => <Button key={value} size="sm" variant={axis === value ? "default" : "outline"}
        aria-pressed={axis === value} onClick={() => setAxis(value)}>{scatterAxes[value].label}</Button>)}
      <Button size="sm" variant="outline" aria-label="확대" disabled={!data?.bounds || zoom >= 8} onClick={() => setZoom(z => Math.min(8, z * 1.5))}><ZoomIn className="h-4 w-4" /></Button>
      <Button size="sm" variant="outline" aria-label="축소" disabled={!data?.bounds || zoom <= .5} onClick={() => setZoom(z => Math.max(.5, z / 1.5))}><ZoomOut className="h-4 w-4" /></Button>
      <Button size="sm" variant="outline" disabled={!data?.bounds} onClick={() => setZoom(1)}>전체 범위</Button>
      <span className="text-xs text-muted-foreground">{zoom.toFixed(2)}×</span>
      {data && <Button size="sm" variant="outline" onClick={() => {
        setDownloadError("");
        api.downloadFile(`/orders/${orderId}/files/${encodeURIComponent(data.source.filename)}`, data.source.filename)
          .catch(error => setDownloadError(String(error.message || error)));
      }}><Download className="mr-1 h-4 w-4" />원본 TSV</Button>}
    </div>
    <p className="text-xs text-muted-foreground">측정값: 전처리 vector 원본 관측행. 중복 행도 각각 계수하므로 고유 precursor 수·time-series 선정 수·분석 입력 수와 다릅니다. Top N과 RAG 주석은 이 분포를 제한하지 않습니다.</p>
    {axis === "occupancy" && <p className="text-xs text-muted-foreground">O1/O2 paired 관측의 Δlogit입니다. O2는 apparent occupancy이며 보정된 물리적 점유율을 뜻하지 않습니다.</p>}
    {downloadError && <p role="alert">다운로드 실패: {downloadError}</p>}
    {current?.error ? <div role="alert" className="rounded-md border p-4 text-sm">
      Scatter 조회 실패: {current.error}<Button className="ml-2" size="sm" variant="outline" onClick={() => setRetry(r => r + 1)}><RotateCcw className="mr-1 h-3 w-3" />다시 시도</Button>
    </div> : !data ? <p role="status" className="flex items-center gap-2 p-4 text-sm"><Loader2 className="h-4 w-4 animate-spin" />전체 관측 분포 불러오는 중…</p> : <>
      <p className="text-sm" data-testid="scatter-counts">원본 {data.coverage.source_rows.toLocaleString()}행 = 표시 가능 {data.coverage.represented_rows.toLocaleString()}행 + 제외 {data.coverage.excluded_rows.toLocaleString()}행 · 식별자 미해결 표시 {data.coverage.identity_unresolved_represented_rows.toLocaleString()}행 · 표본 제외 {data.coverage.sampled_out_rows}행</p>
      <p className="text-xs text-muted-foreground">조건별 {data.point_limit_per_condition.toLocaleString()}행 이하는 모든 점, 초과하면 전체 관측의 {data.bin_resolution}×{data.bin_resolution} 밀도입니다. 확대는 표시 범위만 바꾸며 원본 수는 유지합니다. 밀도에서 개별 precursor 값은 원본 TSV로 확인하세요.</p>
      {data.coverage.excluded_rows > 0 && <details className="text-xs"><summary className="cursor-pointer">제외 사유</summary>
        <ul className="mt-2 space-y-1">{Object.entries(data.coverage.exclusion_reasons).map(([reason, count]) => <li key={reason}>{exclusionLabels[reason] || reason}: {count.toLocaleString()}행</li>)}</ul>
      </details>}
      {data.status === "empty_source" ? <p role="status">원본 TSV에 관측행이 없습니다.</p> : data.status === "no_eligible_observations" ? <p role="status">선택한 두 축에 적격한 관측이 없습니다. 제외 사유와 다른 축을 확인하세요.</p> : viewport && data.bounds && <div className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {conditions.map((condition, i) => <ConditionChart key={`${requestKey}:${condition.condition}`} condition={condition} axis={axis}
          sourceBounds={data.bounds!} viewport={viewport} resolution={data.bin_resolution} color={SCATTER_PALETTE[i % SCATTER_PALETTE.length]} />)}
      </div>}
      <details className="break-all text-xs text-muted-foreground"><summary className="cursor-pointer">측정 출처</summary>{data.source.filename} · {data.measurement_revision}</details>
    </>}
  </section>;
}
