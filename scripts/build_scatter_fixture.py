"""Synthetic reader fixtures and measured whole-row aggregation; no order writes."""
import argparse
import csv
import json
import platform
import resource
import time
from pathlib import Path
from ptm_shared.scatter_overview import read_scatter_overview


def write_source(directory, count, label="Rps6"):
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "ptm_vector_data_normalized_phospho.tsv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["Gene.Name", "PTM_Position", "Precursor.Id", "Precursor.Charge", "Protein.Group",
            "FASTA_Taxonomy_ID", "Condition", "Protein_Log2FC", "PTM_ProteinAdjusted_Log2FC",
            "PTM_Unadjusted_Log2FC", "Occupancy_Logit_Delta", "Pair_Quality_Tier"])
        for i in range(count):
            c, j = i % 6, i // 6
            x, y = (j % 101 - 50) / 10, (j % 97 - 48) / 5
            if j == 0: x = y = 0
            if i == count - 1: x, y = 99, -99
            writer.writerow([label if j % 3 == 0 else "Akt1" if j % 3 == 1 else "INSR", "S2",
                "" if j == 3 else f"p{j}", 2 + j % 2, "P1", "10090",
                ("30sec", "1min", "5min", "1h", "120min", "180min")[c], x, y, y + 2,
                y / 10, "O2" if j % 2 == 0 else "O0"])
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=120000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for name, count, label in (("small", 150, "Rps6"), ("other", 12, "OtherOrder"), ("large", args.rows, "Rps6")):
        directory = args.output / name
        write_source(directory, count, label)
        for axis in ("adjusted", "unadjusted", "occupancy"):
            if name == "large" and axis != "adjusted": continue
            start = time.perf_counter()
            data = read_scatter_overview(directory, "_phospho", axis)
            elapsed = time.perf_counter() - start
            text = json.dumps(data, ensure_ascii=False, allow_nan=False)
            (args.output / f"{name}-{axis}.json").write_text(text)
            if name == "large":
                cached_start = time.perf_counter()
                assert read_scatter_overview(directory, "_phospho", axis) == data
                cached = time.perf_counter() - cached_start
                assert data["coverage"]["source_rows"] == data["coverage"]["represented_rows"] == count
                assert sum(b["count"] for g in data["conditions"] for b in g["bins"]) == count
                assert data["coverage"]["sampled_out_rows"] == 0
                result = {"synthetic_only": True, "rows": count, "conditions": 6, "bin_count": sum(len(g["bins"]) for g in data["conditions"]),
                    "query_seconds": elapsed, "cache_seconds": cached, "json_bytes": len(text.encode()),
                    "peak_rss_native": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "rss_unit": "bytes" if platform.system() == "Darwin" else "KiB", "platform": platform.platform(),
                    "python": platform.python_version(), "coverage": data["coverage"]}
                (args.output / "scale-result.json").write_text(json.dumps(result, indent=2))
                print(json.dumps(result))
    # Degenerate ranges and empty states use the same reader as the route.
    for name, rows in (("constant", 2001), ("empty", 0), ("noeligible", 1)):
        directory = args.output / name
        directory.mkdir()
        source = directory / "ptm_vector_data_normalized_phospho.tsv"
        with source.open("w", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(["Condition", "Protein_Log2FC", "PTM_ProteinAdjusted_Log2FC"])
            writer.writerows([["5min", "" if name == "noeligible" else "0", "0"] for _ in range(rows)])
        (args.output / f"{name}-adjusted.json").write_text(json.dumps(read_scatter_overview(directory, "_phospho"), allow_nan=False))


if __name__ == "__main__": main()
