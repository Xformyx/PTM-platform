"""Command-line entry points for building locked references and scoring artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import BenchmarkManifest
from .locked_scorer import LockedBenchmarkScorer
from .result_bundle import write_score_bundle
from .xlsx_adapter import build_insulin_locked_reference


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline PTM locked benchmark tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-insulin-reference", help="convert an analyst-owned insulin workbook")
    build.add_argument("--workbook", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--dataset-id", default="insulin_signaling_v1")
    score = subparsers.add_parser("score", help="score an archived blind analysis artifact")
    score.add_argument("--manifest", required=True)
    score.add_argument("--analysis-artifact", required=True)
    score.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if args.command == "build-insulin-reference":
        manifest, truth = build_insulin_locked_reference(
            args.workbook, args.output_dir, dataset_id=args.dataset_id
        )
        print(json.dumps({"manifest": str(manifest), "locked_truth": str(truth)}, ensure_ascii=False))
        return 0
    manifest = BenchmarkManifest.load(args.manifest)
    artifact_path = Path(args.analysis_artifact)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    result = LockedBenchmarkScorer(manifest).score(artifact)
    paths = write_score_bundle(args.output_dir, result, analysis_artifact_path=artifact_path)
    print(json.dumps(paths, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
