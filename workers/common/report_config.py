"""
Centralized Report Generation Configuration.

All configurable parameters for the report generation pipeline are defined here
with their default values. Users can override these via `report_options` in the
Order Create form (Advanced Settings panel).

Usage:
    from common.report_config import get_report_config
    cfg = get_report_config(report_options)
    max_tok = cfg["llm_tokens"]["results"]
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration values
# ---------------------------------------------------------------------------

REPORT_CONFIG_DEFAULTS: Dict[str, Any] = {
    # --- Enrichment ---
    "top_n_ptms": 20,

    # --- Report Context Extraction ---
    "md_summary_max_chars": 12000,        # Max chars to extract from comprehensive MD report
    "section_chars_limit": 1500,          # Max chars per section keyword match

    # --- LLM Token Limits (per section) ---
    "llm_tokens": {
        "abstract": 4096,
        "introduction": 12288,
        "results": 16384,
        "time_course": 8192,
        "discussion": 12288,
        "conclusion": 6144,
    },

    # --- LLM Generation ---
    "llm_temperature": 0.6,

    # --- Literature Search ---
    "chromadb_results_per_section": 10,   # ChromaDB vector search results per section
    "pubmed_refs_per_section": {          # PubMed references per section
        "introduction": 20,
        "results": 25,
        "discussion": 20,
        "conclusion": 10,
        "abstract": 10,
    },

    # --- PTM Detail ---
    "ptm_detail_count": 30,              # Number of PTMs with full enrichment detail in prompts

    # --- Word Count Targets ---
    "word_targets": {
        "results": "3000-5000",
        "discussion": "2000-3000",
        "introduction": "1500-2500",
        "conclusion": "800-1200",
        "abstract": "300-500",
    },
}


# ---------------------------------------------------------------------------
# Config resolver
# ---------------------------------------------------------------------------

def get_report_config(report_options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Merge user-provided report_options with defaults.

    The `report_options` dict may contain a nested `report_config` key
    with overrides, or the overrides may be at the top level.

    Returns a fully resolved config dict.
    """
    report_options = report_options or {}

    # User overrides can be in report_options["report_config"] or top-level
    user_cfg = report_options.get("report_config", {})

    # Deep merge with defaults
    cfg = _deep_merge(REPORT_CONFIG_DEFAULTS, user_cfg)

    # Also pick up top_n_ptms from report_options root if present
    if "top_n_ptms" in report_options and "top_n_ptms" not in user_cfg:
        cfg["top_n_ptms"] = report_options["top_n_ptms"]

    logger.info(
        f"Report config resolved: "
        f"md_summary={cfg['md_summary_max_chars']}, "
        f"chromadb_results={cfg['chromadb_results_per_section']}, "
        f"ptm_detail={cfg['ptm_detail_count']}, "
        f"llm_temp={cfg['llm_temperature']}"
    )

    return cfg


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    """Recursively merge overrides into defaults."""
    result = dict(defaults)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Config description (for frontend display)
# ---------------------------------------------------------------------------

REPORT_CONFIG_SCHEMA = [
    {
        "key": "md_summary_max_chars",
        "label": "MD Summary Max Characters",
        "description": "Maximum characters to extract from comprehensive MD report for LLM context",
        "type": "number",
        "default": 12000,
        "min": 3000,
        "max": 50000,
        "step": 1000,
        "category": "context",
    },
    {
        "key": "section_chars_limit",
        "label": "Section Characters Limit",
        "description": "Maximum characters per section keyword match from MD report",
        "type": "number",
        "default": 1500,
        "min": 500,
        "max": 5000,
        "step": 500,
        "category": "context",
    },
    {
        "key": "llm_tokens.abstract",
        "label": "Abstract Max Tokens",
        "description": "LLM token limit for Abstract section",
        "type": "number",
        "default": 4096,
        "min": 1024,
        "max": 32768,
        "step": 1024,
        "category": "llm_tokens",
    },
    {
        "key": "llm_tokens.introduction",
        "label": "Introduction Max Tokens",
        "description": "LLM token limit for Introduction section",
        "type": "number",
        "default": 12288,
        "min": 4096,
        "max": 32768,
        "step": 1024,
        "category": "llm_tokens",
    },
    {
        "key": "llm_tokens.results",
        "label": "Results Max Tokens",
        "description": "LLM token limit for Results section",
        "type": "number",
        "default": 16384,
        "min": 4096,
        "max": 65536,
        "step": 1024,
        "category": "llm_tokens",
    },
    {
        "key": "llm_tokens.time_course",
        "label": "Time-Course Max Tokens",
        "description": "LLM token limit for Time-Course Analysis section",
        "type": "number",
        "default": 8192,
        "min": 2048,
        "max": 32768,
        "step": 1024,
        "category": "llm_tokens",
    },
    {
        "key": "llm_tokens.discussion",
        "label": "Discussion Max Tokens",
        "description": "LLM token limit for Discussion section",
        "type": "number",
        "default": 12288,
        "min": 4096,
        "max": 32768,
        "step": 1024,
        "category": "llm_tokens",
    },
    {
        "key": "llm_tokens.conclusion",
        "label": "Conclusion Max Tokens",
        "description": "LLM token limit for Conclusion section",
        "type": "number",
        "default": 6144,
        "min": 2048,
        "max": 16384,
        "step": 1024,
        "category": "llm_tokens",
    },
    {
        "key": "llm_temperature",
        "label": "LLM Temperature",
        "description": "Controls randomness of LLM output (0.0 = deterministic, 1.0 = creative)",
        "type": "number",
        "default": 0.6,
        "min": 0.0,
        "max": 1.0,
        "step": 0.1,
        "category": "llm",
    },
    {
        "key": "chromadb_results_per_section",
        "label": "ChromaDB Results per Section",
        "description": "Number of vector search results from ChromaDB per report section",
        "type": "number",
        "default": 10,
        "min": 3,
        "max": 30,
        "step": 1,
        "category": "literature",
    },
    {
        "key": "ptm_detail_count",
        "label": "PTM Detail Count",
        "description": "Number of top PTMs to include with full enrichment detail in LLM prompts",
        "type": "number",
        "default": 30,
        "min": 5,
        "max": 100,
        "step": 5,
        "category": "ptm",
    },
]
