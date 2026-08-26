from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from benchmarking.golden_baseline import capture_v1_semantic_baseline, write_json


def _commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, cwd=Path(__file__).resolve().parents[1]
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--score", required=True)
    parser.add_argument("--figure-dir", required=True)
    parser.add_argument("--source-data-dir", required=True)
    parser.add_argument("--input-hashes", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    artifact_path = Path(args.artifact)
    score_path = Path(args.score)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    score = json.loads(score_path.read_text(encoding="utf-8"))
    input_hashes = json.loads(Path(args.input_hashes).read_text(encoding="utf-8"))
    baseline = capture_v1_semantic_baseline(
        artifact=artifact,
        score_summary=score,
        artifact_path=artifact_path,
        score_path=score_path,
        figure_dir=args.figure_dir,
        source_data_dir=args.source_data_dir,
        input_hashes=input_hashes,
        code_commit=_commit(),
    )
    write_json(args.output, baseline)
    print(json.dumps(baseline, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
