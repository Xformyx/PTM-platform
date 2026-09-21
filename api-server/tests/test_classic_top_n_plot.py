"""Classic Top N Time-series selection is a display restore, not a new ranking."""
import csv
import json
from app.services.vector_view import CLASSIC_TOP_N_DEFAULT, load_classic_top_n_plot


FIELDS = [
    "Gene.Name", "PTM_Position", "Precursor.Id", "Precursor.Charge",
    "Modified.Sequence", "Protein.Group", "FASTA_Taxonomy_ID", "FASTA_Accession",
    "Condition", "PTM_ProteinAdjusted_Log2FC", "Protein_Log2FC",
    "Ranking_Score", "Conventional_Log2FC_NA", "LOD_Relative_Log2",
]


def write_vector(root, rows):
    path = root / "ptm_vector_data_normalized_phospho.tsv"
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def row(gene, precursor, condition, value, **extra):
    record = {
        "Gene.Name": gene, "PTM_Position": "S185", "Precursor.Id": precursor,
        "Precursor.Charge": 2, "Modified.Sequence": "AS(UniMod:21)AA",
        "Protein.Group": f"P{gene}", "FASTA_Taxonomy_ID": 10090,
        "FASTA_Accession": "fixture-accession", "Condition": condition,
        "PTM_ProteinAdjusted_Log2FC": value, "Protein_Log2FC": 0,
        "Ranking_Score": "", "Conventional_Log2FC_NA": "", "LOD_Relative_Log2": "",
    }
    record.update(extra)
    return record


def test_classic_default_n_is_historical_twenty():
    assert CLASSIC_TOP_N_DEFAULT == 20


def test_small_enriched_file_is_the_historical_top_n_set(tmp_path):
    write_vector(tmp_path, [
        row("Rps6", "p1", "1min", 6), row("Rps6", "p1", "5min", 0.2),
        row("Akt1", "p2", "1min", 5), row("Akt1", "p2", "5min", 4),
    ])
    (tmp_path / "enriched_ptm_data_phospho.json").write_text(
        json.dumps([{"gene": "Rps6", "position": "S185", "taxon": "10090", "accession": "P0"}])
    )
    view = load_classic_top_n_plot(tmp_path, "_phospho", {"top_n_ptms": 2})
    assert view["classic_selection_source"] == "enriched_top_n"
    assert view["source"] == "enriched"
    assert view["top_n_setting"] == 2
    assert {p["gene"] for p in view["top_n_ptms"]} == {"RPS6"}
    assert {r["gene"] for r in view["vector_data"]} == {"RPS6"}


def test_full_inventory_enriched_falls_back_to_tsv_ranking(tmp_path):
    write_vector(tmp_path, [
        row("Rps6", "p1", "1min", 8),
        row("Akt1", "p2", "1min", 5),
        row("Insr", "p3", "1min", 1),
        row("Mapk1", "p4", "1min", 0.2),
    ])
    (tmp_path / "enriched_ptm_data_phospho.json").write_text(
        json.dumps([{"gene": g, "position": "S185"} for g in ("Rps6", "Akt1", "Insr", "Mapk1")])
    )
    view = load_classic_top_n_plot(tmp_path, "_phospho", {"top_n_ptms": 1})
    assert view["classic_selection_source"] == "tsv_per_condition_ranking"
    assert view["source"] == "preprocessing"
    assert {p["gene"] for p in view["top_n_ptms"]} == {"RPS6"}


def test_denovo_without_conventional_contrast_can_enter_tsv_ranking(tmp_path):
    write_vector(tmp_path, [
        row("Rps6", "p1", "1min", 0.1),
        row("Irs1", "p2", "1min", "", Ranking_Score=9, Conventional_Log2FC_NA="true", LOD_Relative_Log2=4.5),
    ])
    view = load_classic_top_n_plot(tmp_path, "_phospho", {"top_n_ptms": 1})
    assert view["classic_selection_source"] == "tsv_per_condition_ranking"
    assert any(p["gene"] == "IRS1" for p in view["top_n_ptms"])


def test_classic_payload_is_starlette_jsonable(tmp_path):
    import math
    from app.services.vector_view import jsonable_classic_payload
    raw = {
        "vector_data": [{"ptm_relative_log2fc": math.nan, "source_record": {"x": 1}, "ok": 1.5}],
        "top_n_ptms": [{"annotation_match": {"source": {"n": math.inf}}}],
    }
    clean = jsonable_classic_payload(raw)
    json.dumps(clean, allow_nan=False)
    assert "source_record" not in clean["vector_data"][0]
    assert clean["vector_data"][0]["ptm_relative_log2fc"] is None
    assert clean["vector_data"][0]["ok"] == 1.5
    assert clean["top_n_ptms"][0]["annotation_match"]["source"]["n"] is None
