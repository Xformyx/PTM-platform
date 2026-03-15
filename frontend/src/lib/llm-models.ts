/**
 * Cloud LLM 모델 프리셋.
 * Cloud Models는 API Key만 등록하고, Order Create / Re-run 시 여기서 세부 모델을 선택합니다.
 */
export const CLOUD_PROVIDER_SENTINEL = "__provider__";

export type CloudProvider = "gemini" | "openai" | "anthropic";

export const CLOUD_MODEL_PRESETS: Record<CloudProvider, { id: string; name: string }[]> = {
  gemini: [
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash" },
    { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro" },
    { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash" },
    { id: "gemini-2.5-flash-lite", name: "Gemini 2.5 Flash-Lite" },
    { id: "gemini-flash-latest", name: "Gemini Flash Latest" },
    { id: "gemini-pro-latest", name: "Gemini Pro Latest" },
    { id: "gemini-3-pro-preview", name: "Gemini 3 Pro Preview" },
    { id: "gemini-3-flash-preview", name: "Gemini 3 Flash Preview" },
    { id: "gemini-3.1-pro-preview", name: "Gemini 3.1 Pro Preview" },
    { id: "gemma-3-27b-it", name: "Gemma 3 27B" },
    { id: "gemma-3-12b-it", name: "Gemma 3 12B" },
  ],
  openai: [
    { id: "gpt-4.1-mini", name: "GPT-4.1 Mini" },
    { id: "gpt-4.1", name: "GPT-4.1" },
    { id: "gpt-4o", name: "GPT-4o" },
    { id: "gpt-4o-mini", name: "GPT-4o Mini" },
    { id: "gpt-4-turbo", name: "GPT-4 Turbo" },
    { id: "gpt-3.5-turbo", name: "GPT-3.5 Turbo" },
  ],
  anthropic: [
    { id: "claude-sonnet-4-20250514", name: "Claude Sonnet 4" },
    { id: "claude-3-5-sonnet-20241022", name: "Claude 3.5 Sonnet" },
    { id: "claude-3-opus-20240229", name: "Claude 3 Opus" },
  ],
};
