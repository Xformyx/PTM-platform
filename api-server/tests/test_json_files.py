from pathlib import Path

from app.core.json_files import load_json_first_value


def test_load_json_first_value_ignores_trailing_fragment(tmp_path: Path):
    dest = tmp_path / "enriched_ptm_data_phospho.json"
    dest.write_text('[1, 2]\n{"partial":', encoding="utf-8")
    assert load_json_first_value(dest) == [1, 2]
