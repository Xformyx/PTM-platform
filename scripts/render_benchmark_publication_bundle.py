#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarking.publication_bundle import build_publication_sources, write_publication_bundle


def _load_optional(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--score", required=True)
    parser.add_argument("--run-metadata")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    score = json.loads(Path(args.score).read_text(encoding="utf-8"))
    publication = build_publication_sources(score, artifact, _load_optional(args.run_metadata))
    destination = Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    publication_path = destination / "publication_bundle.json"
    publication_path.write_text(
        json.dumps(publication, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written = write_publication_bundle(destination, publication)
    print(
        json.dumps(
            {
                "publication_bundle": str(publication_path),
                "scope": publication.get("scope"),
                "written": written,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
