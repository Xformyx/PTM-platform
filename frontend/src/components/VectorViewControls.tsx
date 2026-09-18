import {selectionLabel, type VectorView, type ViewMode, type Representation} from "../lib/vectorView";

export function VectorViewControls({view, mode, n, representation, onMode, onN, onRepresentation}: {
  view?: VectorView | null; mode: ViewMode; n: number | null; representation: Representation;
  onMode: (v: ViewMode) => void; onN: (v: number) => void; onRepresentation: (v: Representation) => void;
}) {
  return <div className="space-y-2" data-testid="vector-view-controls">
    <div className="flex gap-3 flex-wrap">
      <label>표시 선택 <select aria-label="표시 선택" value={mode} onChange={e => onMode(e.target.value as ViewMode)}>
        <option value="per_condition_top_n">조건별 Top N 합집합</option><option value="global_top_n">전체 Top N</option>
        <option value="all_observed">전체 관측</option><option value="rag_only">RAG 대상만</option></select></label>
      {mode.endsWith("top_n") && <label>N <input aria-label="표시 N" type="number" min={1} value={n ?? view?.selection.n ?? ""}
        onChange={e => { const v = Number(e.target.value); if (Number.isInteger(v) && v > 0) onN(v); }} /></label>}
      <label>정량 표현 <select aria-label="정량 표현" value={representation} onChange={e => onRepresentation(e.target.value as Representation)}>
        <option value="conventional_log2_contrast">Conventional log2 contrast</option><option value="lod_relative_log2">LOD-relative log2</option>
        <option value="normalized_log2_intensity">Normalized log2 intensity</option><option value="occupancy_logit_delta">Occupancy logit delta</option></select></label>
    </div>
    {view && <><p data-testid="selection-label">{selectionLabel(view.selection)}</p>
      <p>측정값: 전처리 vector / 주석: RAG {view.sources.annotations.status}</p>
      <p data-testid="coverage">선정 {String(view.coverage.selected_features)} · 이름 연결 {String(view.coverage.annotation_matched_features)} ·
        주석 없음 {String(view.coverage.annotation_unmatched_features)} · 모호 {String(view.coverage.annotation_ambiguous_features)} ·
        식별자 유효 {String(view.coverage.identity_valid_selected_features)} · 축 유효 {String(view.coverage.axis_eligible_selected_features)} ·
        식별 보류 원본 행 {String(view.coverage.identity_unresolved_rows)}</p>
      <p className="text-xs">주석 연결은 기본 보기의 측정값 표시 조건이 아닙니다. 표시 선택은 분석 모집단을 바꾸지 않습니다.</p>
    </>}
  </div>;
}
