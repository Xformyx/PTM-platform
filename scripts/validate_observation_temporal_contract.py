"""Run isolated report/temporal and API suites, retaining commands and JUnit.

Run with the Python environment containing the repository test dependencies.
No database, broker, Gemini or Cytoscape service is contacted by these tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REPORT_FILES = [
    "test_measured_feature_authoring.py", "test_report_rendering_fidelity.py",
    "test_quantitation_estimator_contract.py", "test_report_vector_projection.py",
    "test_measured_feature_cards.py", "test_reader_prose_quality.py",
    "test_bibliography_blocked_data_only.py", "test_de_novo_representation.py",
    "test_report_artifact_manifest.py", "test_evidence_contracts.py",
    "test_observation_denominator_contract.py", "test_dual_track_ptm_quantification.py",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/validation/task01-02")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    worker_files = {ROOT / "workers/tests" / name for name in REPORT_FILES}
    for pattern in ("test_report_review_*.py", "test_tmm*.py", "test_temporal*.py", "test_site_form*.py"):
        worker_files.update((ROOT / "workers/tests").glob(pattern))
    worker_files.update((ROOT / "ptm_shared/tests").glob("test_temporal*.py"))
    worker_files.update(ROOT / "ptm_shared/tests" / name for name in (
        "test_de_novo_report_representation.py", "test_kinase_evidence_ledger.py",
    ))
    api_files = set()
    for pattern in ("test_tmm*.py", "test_temporal*.py"):
        api_files.update((ROOT / "api-server/tests").glob(pattern))
    # The worker audit suite asserts that the production API module was never
    # imported. Keep API tests in their own process; do not relax that assertion.
    groups = {"worker-shared": worker_files, "api": api_files}
    evidence = {
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": platform.python_version(), "platform": platform.platform(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "groups": {},
        "scope": "synthetic regression and source-extracted route wiring; no full HTTP/worker/DOCX run",
    }
    implementation_files = [
        "api-server/app/api/orders.py", "api-server/app/services/temporal_kinase_scoring.py",
        "ptm_shared/temporal_feature_input.py", "ptm_shared/de_novo_representation.py",
        "ptm_shared/enrichment_free_temporal_sidecar.py", "ptm_shared/kinase_evidence_ledger.py",
        "ptm_shared/tmm_multikinase_integration.py", "workers/preprocessing/core/ptm_quantification.py",
        "workers/report_generation/core/vector_projection.py",
    ]
    reviewed_files = worker_files | api_files | {ROOT / path for path in implementation_files} | {Path(__file__)}
    evidence["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in sorted(reviewed_files)}
    exit_code = 0
    for name, files in groups.items():
        junit = args.output_dir.resolve() / f"{name}.xml"
        command = [sys.executable, "-m", "pytest", *[str(p.relative_to(ROOT)) for p in sorted(files)],
                   "-q", "--tb=short", f"--junitxml={junit}"]
        env = {**os.environ, "PYTHONPATH": "api-server:workers:.", "MPLCONFIGDIR": "/tmp/ptm-review-mpl"}
        result = subprocess.run(command, cwd=ROOT, env=env)
        suites = ET.parse(junit).getroot().iter("testsuite")
        counts = {field: 0 for field in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for field in counts:
                counts[field] += int(suite.get(field, "0"))
        evidence["groups"][name] = {"command": command, "exit_code": result.returncode,
                                    "counts": counts, "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest()}
        exit_code = exit_code or result.returncode
    (args.output_dir / "validation.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
