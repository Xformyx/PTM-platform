import { axisValue, finite, type QuantRow, type QuantAxis } from "./quantitation.ts";

export type ViewMode = "per_condition_top_n" | "global_top_n" | "all_observed" | "rag_only";
export type Representation = "conventional_log2_contrast" | "lod_relative_log2" | "normalized_log2_intensity" | "occupancy_logit_delta";
export type VectorView = {
  contract_version: string; measurement_revision: string;
  selection: {mode: ViewMode; n: number | null; axis: string; representation: Representation; union_feature_count: number;
    selected_feature_ids: string[]; selection_hash: string; selection_status: string; reason_codes: string[]};
  sources: {annotations: {status: string; revision: string | null}};
  coverage: Record<string, number | boolean | Record<string, number>>;
  conditions: string[];
  features: Array<{feature_id: string; gene: string; position: string; label: string; annotation_match: {status: string; match_scope: string}}>;
  observations: QuantRow[];
};

export function selectionLabel(selection: VectorView["selection"]): string {
  const m = selection.union_feature_count;
  switch (selection.mode) {
    case "per_condition_top_n": return `조건별 Top ${selection.n} · 합집합 ${m} precursor features`;
    case "global_top_n": return `전체 Top ${selection.n} · ${m} precursor features`;
    case "all_observed": return `전체 관측 precursor features ${m}개`;
    case "rag_only": return `RAG 대상만 · ${m} precursor features`;
  }
}

export function representationValue(row: QuantRow, axis: QuantAxis, representation: Representation): number | null {
  if (row.conflicting_row_count) return null;
  if (representation === "conventional_log2_contrast") return axisValue(row, axis);
  const value = row[representation];
  return finite(value) ? value : null;
}

export function finiteExtent(values: Iterable<unknown>, fallback: [number, number] = [-1, 1]): [number, number] {
  let low = Infinity, high = -Infinity;
  for (const value of values) if (finite(value)) { low = Math.min(low, value); high = Math.max(high, value); }
  return low === Infinity ? fallback : [low, high];
}

// Index once per immutable response, including null cells. No site-key fallback.
export function indexObservations(rows: QuantRow[]) {
  const index = new Map<string, Map<string, QuantRow[]>>();
  for (const row of rows) {
    if (!row.feature_id) continue;
    if (!index.has(row.feature_id)) index.set(row.feature_id, new Map());
    const byCondition = index.get(row.feature_id)!;
    byCondition.set(row.condition, [...(byCondition.get(row.condition) || []), row]);
  }
  return index;
}

export function indexedTrajectory(index: ReturnType<typeof indexObservations>, id: string, conditions: string[], axis: QuantAxis, representation: Representation) {
  return conditions.map(c => {
    const rows = index.get(id)?.get(c) || [];
    const values = new Set(rows.map(row => representationValue(row, axis, representation)));
    return values.size === 1 ? values.values().next().value ?? null : null;
  });
}

export function renderedCounts(trajectories: (number | null)[][]) {
  let points = 0, segments = 0;
  for (const values of trajectories) for (let i = 0; i < values.length; i++) {
    if (finite(values[i])) { points++; if (i > 0 && finite(values[i-1])) segments++; }
  }
  return {points, segments};
}

// A stale completion may never replace the latest requested view.
export class LatestRequest {
  private sequence = 0;
  begin() { return ++this.sequence; }
  current(token: number) { return token === this.sequence; }
  invalidate() { this.sequence++; }
}

const pending = new Map<string, Promise<unknown>>();
export function sharedViewRequest<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const existing = pending.get(key);
  if (existing) return existing as Promise<T>;
  const request = fetcher().finally(() => { if (pending.get(key) === request) pending.delete(key); });
  pending.set(key, request);
  return request;
}

export function observedSvgPath(conditions:string[], scores:Record<string,number|null|undefined>, x:(i:number)=>number,y:(v:number)=>number):string {
  let connected=false;const path:string[]=[];
  conditions.forEach((c,i)=>{const v=scores[c];if(!finite(v)){connected=false;return;}path.push(`${connected?'L':'M'}${x(i)},${y(v)}`);connected=true;});
  return path.join(' ');
}

export function savedViewSettings(orderId:number):Partial<{mode:ViewMode;n:number|null;axis:QuantAxis;representation:Representation}> {
 try {
  const p=JSON.parse(localStorage.getItem(`vector-view.v2:${orderId}`)||'{}');
  return {mode:['per_condition_top_n','global_top_n','all_observed','rag_only'].includes(p.mode)?p.mode:undefined,
   n:Number.isInteger(p.n)&&p.n>0?p.n:null,axis:['relative','unadjusted','protein'].includes(p.axis)?p.axis:undefined,
   representation:['conventional_log2_contrast','lod_relative_log2','normalized_log2_intensity','occupancy_logit_delta'].includes(p.representation)?p.representation:undefined};
 }catch{return {};}
}
