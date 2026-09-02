"""Regression for concurrent-write Extra data on RAG JSON artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.json_files import atomic_write_json, load_json_first_value


def test_load_json_first_value_ignores_trailing_fragment(tmp_path: Path):
    dest = tmp_path / "enriched_ptm_data_phospho.json"
    first = [{"Gene.Name": "Insr", "PTM_Position": "Y1158"}]
    dest.write_text(
        json.dumps(first, indent=2) + '      "input_genes": ["Prkca"]\n]\n',
        encoding="utf-8",
    )
    loaded = load_json_first_value(dest)
    assert loaded == first


def test_atomic_write_json_replaces_complete_document(tmp_path: Path):
    dest = tmp_path / "temporal_ptm_protein_analysis_v2.json"
    dest.write_text("{broken", encoding="utf-8")
    atomic_write_json(dest, {"status": "ok", "n": 2}, sort_keys=True, default=None)
    assert json.loads(dest.read_text(encoding="utf-8")) == {"n": 2, "status": "ok"}
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == []
