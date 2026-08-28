export interface TemporalEvidenceReadiness {
  status: 'ready' | 'missing';
  source: string | null;
  artifact: string | null;
  dynamic_transition_status: string | null;
  message: string;
}

export interface Order {
  id: number;
  order_code: string;
  project_name: string;
  status: OrderStatus;
  ptm_type: 'phosphorylation' | 'ubiquitylation';
  species: string;
  organism_code?: number;
  sample_config: Record<string, unknown>;
  analysis_context?: Record<string, unknown>;
  analysis_options?: Record<string, unknown>;
  report_options: Record<string, unknown>;
  current_stage?: string;
  progress_pct: number;
  stage_detail?: string;
  result_files?: Record<string, string[]>;
  error_message?: string;
  cross_talk_data?: Record<string, unknown>;
  signal_propagation_data?: Record<string, unknown>;
  ip_overlay_data?: Record<string, unknown> | null;
  kinase_analysis_data?: Record<string, unknown>;
  kinase_activity_heatmap?: Record<string, unknown>;
  temporal_evidence_readiness?: TemporalEvidenceReadiness;
  rag_collections?: number[] | null;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  created_by?: string | null;
  run_by?: string | null;
  /** Populated when this order was shared with the current user */
  is_shared?: boolean;
  share_access?: 'full_access' | 'read_only' | null;
  /** List endpoint denormalizes analysis_options.quick_analysis */
  quick_analysis?: boolean;
}

export interface OrderShareEntry {
  user_id: number;
  name: string;
  email: string;
  access_level: 'full_access' | 'read_only';
}

export interface ShareableUser {
  id: number;
  name: string;
  email: string;
}

export type OrderStatus =
  | 'registered'
  | 'queued'
  | 'preprocessing'
  | 'rag_enrichment'
  | 'report_generation'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface OrderLog {
  id: number;
  stage: string;
  step: string;
  status: string;
  progress_pct?: number;
  message?: string;
  metadata?: Record<string, unknown>;
  duration_ms?: number;
  created_at: string;
}

export interface RagCollection {
  id: number;
  name: string;
  description?: string;
  tier: string;
  chromadb_name: string;
  embedding_model: string;
  embedding_model_info?: {
    key: string;
    hf_model_id: string;
    dimension: number;
    normalize_embeddings: boolean;
    label: string;
    license_class: string;
    status: string;
    max_sequence_length?: number | null;
  };
  chunk_strategy: string;
  chunk_size: number;
  document_count: number;
  chunk_count: number;
  is_active: boolean;
  created_at: string;
}

export interface LlmModel {
  id: number;
  name: string;
  provider: 'ollama' | 'gemini' | 'openai' | 'anthropic';
  model_id: string;
  purpose: string;
  default_temp: number;
  max_tokens: number;
  is_active: boolean;
  is_default: boolean;
  has_api_key: boolean;
}

export type AnalysisMode =
  | 'full'
  | 'ptm_topn'
  | 'log2fc_threshold'
  | 'custom_count'
  | 'protein_list';

export interface AnalysisOptions {
  mode: AnalysisMode;
  topN?: number;
  log2fcThreshold?: number;
  proteinCount?: number;
  proteinListFile?: File | null;
  proteinListPath?: string;
  /** Exploratory PR/PG subset. Same formulas; not comparable to Full. */
  quick_analysis?: boolean;
  quick_keep_all_ptm?: boolean;
  quick_max_ptm_precursors?: number;
  quick_per_protein_cap?: number;
  quick_min_detection_frac?: number;
  quick_keep_unmodified_pairs?: boolean;
  quick_include_non_ptm?: boolean;
  quick_max_non_ptm_proteins?: number;
}

export const DEFAULT_QUICK_SETTINGS = {
  quick_keep_all_ptm: false,
  quick_max_ptm_precursors: 400,
  quick_per_protein_cap: 4,
  quick_min_detection_frac: 0.5,
  quick_keep_unmodified_pairs: true,
  quick_include_non_ptm: false,
  quick_max_non_ptm_proteins: 200,
} as const;

export interface QuickAnalysisSettings {
  quick_keep_all_ptm: boolean;
  quick_max_ptm_precursors: number;
  quick_per_protein_cap: number;
  quick_min_detection_frac: number;
  quick_keep_unmodified_pairs: boolean;
  quick_include_non_ptm: boolean;
  quick_max_non_ptm_proteins: number;
}

export const DEFAULT_ANALYSIS_OPTIONS: AnalysisOptions = {
  mode: 'full',
  topN: 500,
  log2fcThreshold: 0.5,
  proteinCount: 1000,
  quick_analysis: false,
  ...DEFAULT_QUICK_SETTINGS,
};

function asFiniteNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function asBool(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value;
  return fallback;
}

export function pickQuickSettings(options: unknown): QuickAnalysisSettings {
  const src = options && typeof options === 'object' ? options as Record<string, unknown> : {};
  return {
    quick_keep_all_ptm: asBool(src.quick_keep_all_ptm, DEFAULT_QUICK_SETTINGS.quick_keep_all_ptm),
    quick_max_ptm_precursors: asFiniteNumber(src.quick_max_ptm_precursors, DEFAULT_QUICK_SETTINGS.quick_max_ptm_precursors),
    quick_per_protein_cap: asFiniteNumber(src.quick_per_protein_cap, DEFAULT_QUICK_SETTINGS.quick_per_protein_cap),
    quick_min_detection_frac: asFiniteNumber(src.quick_min_detection_frac, DEFAULT_QUICK_SETTINGS.quick_min_detection_frac),
    quick_keep_unmodified_pairs: asBool(src.quick_keep_unmodified_pairs, DEFAULT_QUICK_SETTINGS.quick_keep_unmodified_pairs),
    quick_include_non_ptm: asBool(src.quick_include_non_ptm, DEFAULT_QUICK_SETTINGS.quick_include_non_ptm),
    quick_max_non_ptm_proteins: asFiniteNumber(src.quick_max_non_ptm_proteins, DEFAULT_QUICK_SETTINGS.quick_max_non_ptm_proteins),
  };
}

export function clampQuickSettings(settings: QuickAnalysisSettings): QuickAnalysisSettings {
  const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));
  return {
    ...settings,
    quick_max_ptm_precursors: clamp(settings.quick_max_ptm_precursors, 10, 5000),
    quick_per_protein_cap: clamp(settings.quick_per_protein_cap, 0, 50),
    quick_min_detection_frac: clamp(settings.quick_min_detection_frac, 0, 1),
    quick_max_non_ptm_proteins: clamp(settings.quick_max_non_ptm_proteins, 0, 5000),
  };
}

export function isQuickAnalysis(options: unknown): boolean {
  if (!options || typeof options !== 'object') return false;
  return Boolean((options as { quick_analysis?: unknown }).quick_analysis);
}

export function formatQuickAnalysisSummary(options: unknown): string {
  if (!isQuickAnalysis(options)) return 'Off';
  const s = clampQuickSettings(pickQuickSettings(options));
  const parts: string[] = [];
  parts.push(s.quick_keep_all_ptm ? 'all target PTM' : `≤${s.quick_max_ptm_precursors} PTM`);
  parts.push(s.quick_per_protein_cap === 0 ? 'no protein cap' : `cap ${s.quick_per_protein_cap}/protein`);
  parts.push(`det≥${s.quick_min_detection_frac}`);
  if (!s.quick_keep_unmodified_pairs) parts.push('no unmodified pairs');
  if (s.quick_include_non_ptm) parts.push(`+${s.quick_max_non_ptm_proteins} non-PTM PG`);
  return `On · ${parts.join(' · ')}`;
}

export type TemporalContract = 'legacy' | 'dynamics_v1';

export const DEFAULT_TEMPORAL_CONTRACT: TemporalContract = 'dynamics_v1';

export function resolveTemporalContract(value: unknown): TemporalContract {
  return value === 'legacy' ? 'legacy' : 'dynamics_v1';
}

export function temporalContractLabel(value: unknown): string {
  return resolveTemporalContract(value) === 'legacy' ? 'Legacy' : 'Dynamics v1';
}

export interface ProgressEvent {
  order_id: number;
  stage: string;
  step: string;
  status: string;
  /** Omitted on detail-only log lines that do not update overall progress */
  progress_pct?: number | null;
  message: string;
  metadata: Record<string, unknown>;
  _ts?: number;
}
