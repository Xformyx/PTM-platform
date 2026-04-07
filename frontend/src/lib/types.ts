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
  kinase_analysis_data?: Record<string, unknown>;
  rag_collections?: number[] | null;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  created_by?: string | null;
  run_by?: string | null;
  /** Populated when this order was shared with the current user */
  is_shared?: boolean;
  share_access?: 'full_access' | 'read_only' | null;
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
  | 'pending'
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
}

export const DEFAULT_ANALYSIS_OPTIONS: AnalysisOptions = {
  mode: 'full',
  topN: 500,
  log2fcThreshold: 0.5,
  proteinCount: 1000,
};

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
