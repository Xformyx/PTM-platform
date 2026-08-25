"""Offline, locked-reference benchmark utilities.

This package is intentionally outside ``ptm_shared`` and the worker wheel.
Production analysis, RAG, report, and LLM runtime code must never import it.
"""

from .contracts import BenchmarkManifest, BenchmarkManifestError
from .locked_scorer import LockedBenchmarkScorer, LockedScoreError

__all__ = [
    "BenchmarkManifest",
    "BenchmarkManifestError",
    "LockedBenchmarkScorer",
    "LockedScoreError",
]
