export interface Order {
  id: number;
  order_code: string;
  project_name: string;
  status: OrderStatus;
  ptm_type: 'phosphorylation' | 'ubiquitination';
  species: string;
  organism_code?: number;
  sample_config: Record<string, unknown>;
  analysis_context?: Record<string, unknown>;
  report_options: Record<string, unknown>;
  current_stage?: string;
  progress_pct: number;
  stage_detail?: string;
  result_files?: Record<string, string[]>;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
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
  progress_pct: number;
  message: string;
  metadata: Record<string, unknown>;
  _ts?: number;
}
