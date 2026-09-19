"""Synthetic source-row contracts; quantities are not biological validation."""
import csv
import hashlib
import json
import pytest
from ptm_shared import scatter_overview as scatter


def row(**changes):
    return {"Gene.Name": "Rps6", "PTM_Position": "S2", "Precursor.Id": "p1", "Precursor.Charge": "2",
            "Protein.Group": "P1", "FASTA_Taxonomy_ID": "10090", "Condition": "5min",
            "Protein_Log2FC": "0", "PTM_ProteinAdjusted_Log2FC": "1", "PTM_Unadjusted_Log2FC": "2",
            "Occupancy_Logit_Delta": "0.5", "Pair_Quality_Tier": "O2", **changes}


def write_rows(root, rows, filename="ptm_vector_data_normalized_phospho.tsv"):
    path = root / filename
    fields = list(dict.fromkeys(k for r in rows for k in r)) or list(row())
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader(); writer.writerows(rows)
    return path


def test_source_rows_preserve_case_precursors_duplicates_conflicts_and_unknown_identity(tmp_path):
    records = [row(), row(**{"Gene.Name": "Akt1", "Precursor.Id": "p2", "Precursor.Charge": "3"}),
               row(**{"Gene.Name": "INSR", "Precursor.Id": ""}), row(),
               row(**{"PTM_ProteinAdjusted_Log2FC": "-3", "FASTA_Taxonomy_ID": "9606", "Isoform": "P1-2"})]
    path = write_rows(tmp_path, records)
    before = path.read_bytes()
    data = scatter.read_scatter_overview(tmp_path, "_phospho")
    points = data["conditions"][0]["points"]
    assert [p["gene"] for p in points] == ["Rps6", "Akt1", "INSR", "Rps6", "Rps6"]
    assert [p["y"] for p in points] == [1, 1, 1, 1, -3]
    assert points[0]["feature_id"] == points[3]["feature_id"]
    assert points[0]["feature_id"] != points[1]["feature_id"] != points[4]["feature_id"]
    assert points[2]["feature_id"] is None
    assert points[4]["isoform"] == "P1-2" and points[4]["taxon"] == "9606"
    assert data["coverage"]["identity_unresolved_represented_rows"] == 1
    assert data["coverage"]["source_rows"] == data["coverage"]["represented_rows"] == 5
    for annotation in ("[]", "[", '[{"gene":"RPS6"}]'):
        (tmp_path / "enriched_ptm_data_phospho.json").write_text(annotation)
        assert scatter.read_scatter_overview(tmp_path, "_phospho") == data
    assert path.read_bytes() == before
    assert data["source"]["sha256"] == hashlib.sha256(before).hexdigest()


def test_axes_null_zero_finite_eligibility_partition_and_no_reconstructed_fallback(tmp_path):
    records = [row(**{"PTM_ProteinAdjusted_Log2FC": "0", "PTM_Unadjusted_Log2FC": "0"})]
    records += [row(**{"Protein_Log2FC": x}) for x in ("", "NaN", "Inf", "-Inf")]
    records += [row(**{"PTM_ProteinAdjusted_Log2FC": x, "PTM_Unadjusted_Log2FC": x}) for x in ("", "NaN", "Inf", "-Inf")]
    records += [row(**{"Conventional_Log2FC_NA": "True"}), row(**{"Control_Pseudocount_Used": "true"}),
                row(**{"Condition": "Control"}), row(**{"Condition": ""}),
                row(**{"PTM_Unadjusted_Log2FC": "", "PTM_Absolute_Log2FC": "99"})]
    path = write_rows(tmp_path, records)
    with path.open("a") as stream: stream.write("too\tfew\tcolumns\n")
    data = scatter.read_scatter_overview(tmp_path, "_phospho")
    assert data["coverage"]["source_rows"] == 15
    assert data["coverage"]["represented_rows"] == 2  # A remains independent of absent U.
    assert data["coverage"]["exclusion_reasons"] == {"protein_axis_unavailable": 4, "ptm_axis_ineligible": 6,
        "control_reference_row": 1, "condition_missing": 1, "malformed_source_row": 1}
    assert data["conditions"][0]["points"][0]["x"] == data["conditions"][0]["points"][0]["y"] == 0
    u = scatter.read_scatter_overview(tmp_path, "_phospho", "unadjusted")
    assert [p["y"] for p in u["conditions"][0]["points"]] == [0]
    assert u["measurement_revision"] == data["measurement_revision"]
    json.dumps(data, allow_nan=False)


def test_occupancy_tiers_and_missing_source_are_explicit(tmp_path):
    with pytest.raises(FileNotFoundError): scatter.read_scatter_overview(tmp_path, "_phospho")
    write_rows(tmp_path, [row(**{"Pair_Quality_Tier": tier, "Occupancy_Logit_Delta": "0"}) for tier in ("O0", "O1", "O2", "O3", "")])
    data = scatter.read_scatter_overview(tmp_path, "_phospho", "occupancy")
    assert data["coverage"]["represented_rows"] == 2
    assert data["coverage"]["exclusion_reasons"] == {"occupancy_ineligible": 3}
    assert all(p["y"] == 0 for p in data["conditions"][0]["points"])
    with pytest.raises(ValueError, match="unsupported"): scatter.read_scatter_overview(tmp_path, "_phospho", "absolute")


def test_threshold_is_representation_switch_and_all_bins_include_late_extreme(tmp_path):
    write_rows(tmp_path, [row(**{"Condition": condition, "Protein_Log2FC": str(i % 31),
        "PTM_ProteinAdjusted_Log2FC": str(-999 if i == n - 1 else i % 11)})
        for condition, n in (("1h", 2000), ("5min", 2001), ("180min", 4100)) for i in range(n)])
    data = scatter.read_scatter_overview(tmp_path, "_phospho")
    assert [g["condition"] for g in data["conditions"]] == ["5min", "1h", "180min"]
    for group in data["conditions"]:
        if group["condition"] == "1h":
            assert group["mode"] == "points" and len(group["points"]) == 2000
        else:
            assert group["mode"] == "density" and group["points"] == []
            assert sum(b["count"] for b in group["bins"]) == group["represented_rows"]
            assert len(group["bins"]) <= 64 * 64
            assert any(b["iy"] == 0 for b in group["bins"])
    assert data["coverage"]["sampled_out_rows"] == 0
    assert data["coverage"]["represented_rows"] == 8101


def test_source_fallback_cache_invalidation_and_snapshot_independence(tmp_path):
    motif = write_rows(tmp_path, [row()], "ptm_vector_data_with_motifs_phospho.tsv")
    first = scatter.read_scatter_overview(tmp_path, "_phospho")
    assert first["source"]["filename"] == motif.name
    normalized = write_rows(tmp_path, [row(**{"PTM_ProteinAdjusted_Log2FC": "3"})])
    second = scatter.read_scatter_overview(tmp_path, "_phospho")
    assert second["source"]["filename"] == normalized.name
    from ptm_shared.vector_columnar import publish_vector_columnar
    publish_vector_columnar(tmp_path, "_phospho")
    assert scatter.read_scatter_overview(tmp_path, "_phospho") == second
    write_rows(tmp_path, [row(**{"PTM_ProteinAdjusted_Log2FC": "4"})])
    third = scatter.read_scatter_overview(tmp_path, "_phospho")
    assert third["measurement_revision"] != second["measurement_revision"]
    assert third["conditions"][0]["points"][0]["y"] == 4
    third["conditions"][0]["points"].clear()
    assert scatter.read_scatter_overview(tmp_path, "_phospho")["conditions"][0]["points"]


def test_concurrent_source_change_is_not_cached(tmp_path, monkeypatch):
    path = write_rows(tmp_path, [row()])
    original = scatter._records
    def changing(path):
        yield from original(path)
        path.write_text(path.read_text().replace("Rps6", "Akt1"))
    monkeypatch.setattr(scatter, "_records", changing)
    with pytest.raises(scatter.ScatterSourceChanged): scatter.read_scatter_overview(tmp_path, "_phospho")
    monkeypatch.setattr(scatter, "_records", original)
    assert scatter.read_scatter_overview(tmp_path, "_phospho")["conditions"][0]["points"][0]["gene"] == "Akt1"


def test_empty_header_only_and_bad_header_are_distinct(tmp_path):
    path = write_rows(tmp_path, [])
    assert scatter.read_scatter_overview(tmp_path, "_phospho")["status"] == "empty_source"
    path.write_text("Condition\tCondition\n1min\t5min\n")
    with pytest.raises(ValueError, match="ambiguous_source_header"): scatter.read_scatter_overview(tmp_path, "_phospho")


def test_constant_zero_density_preserves_every_row(tmp_path):
    write_rows(tmp_path, [row(**{"PTM_ProteinAdjusted_Log2FC": "0"})] * 2001)
    data = scatter.read_scatter_overview(tmp_path, "_phospho")
    assert data["bounds"] == [0, 0, 0, 0]
    assert data["conditions"][0]["bins"] == [{"ix": 32, "iy": 32, "count": 2001}]
