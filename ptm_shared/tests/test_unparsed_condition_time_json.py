"""Condition names that are not times must stay out of JSON as inf."""

import csv
import json
from pathlib import Path

from ptm_shared.directed_temporal_relationship import analyze_directed_temporal_relationship
from ptm_shared.enrichment_free_temporal_sidecar import load_protein_time_series


def test_named_conditions_store_null_minutes_and_remain_json(tmp_path: Path):
    path = tmp_path / "all_protein_level_changes_normalized_phospho.tsv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Gene.Name", "Protein.Group", "Protein.Name", "Condition", "Log2FC", "Has_PTM"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow({"Gene.Name": "Akt1", "Protein.Group": "P1", "Protein.Name": "Akt1", "Condition": "AF", "Log2FC": "1.5", "Has_PTM": "1"})
        writer.writerow({"Gene.Name": "Akt1", "Protein.Group": "P1", "Protein.Name": "Akt1", "Condition": "mgAF", "Log2FC": "-0.4", "Has_PTM": "1"})
    trajectories, _provenance = load_protein_time_series(tmp_path, "phosphorylation")
    assert trajectories[0]["peak_timepoint"] == "AF"
    assert trajectories[0]["peak_minutes"] is None
    json.dumps(trajectories, allow_nan=False)

    relation = analyze_directed_temporal_relationship(
        {"key": "source", "temporal_values": {"AF": 1.0, "mgAF": 0.2}},
        {"key": "target", "temporal_values": {"AF": 0.2, "mgAF": 1.0}},
        ["AF", "mgAF"],
    )
    assert relation["timepoint_minutes"] == [None, None]
    assert relation["direction"] == "unresolved"
    json.dumps(relation, allow_nan=False)


def test_recorded_hour_label_stays_minutes(tmp_path: Path):
    path = tmp_path / "all_protein_level_changes_normalized_phospho.tsv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Gene.Name", "Protein.Group", "Protein.Name", "Condition", "Log2FC", "Has_PTM"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow({"Gene.Name": "Akt1", "Protein.Group": "P1", "Protein.Name": "Akt1", "Condition": "30min", "Log2FC": "0.2", "Has_PTM": "1"})
        writer.writerow({"Gene.Name": "Akt1", "Protein.Group": "P1", "Protein.Name": "Akt1", "Condition": "2h", "Log2FC": "1.2", "Has_PTM": "1"})
    trajectories, _provenance = load_protein_time_series(tmp_path, "phosphorylation")
    assert trajectories[0]["peak_timepoint"] == "2h"
    assert trajectories[0]["peak_minutes"] == 120.0
