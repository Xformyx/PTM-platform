from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_production_runtime_does_not_import_benchmarking_package() -> None:
    offenders = []
    for root in (REPO_ROOT / "api-server", REPO_ROOT / "workers", REPO_ROOT / "ptm_shared"):
        for source in root.rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            if "import benchmarking" in text or "from benchmarking" in text:
                offenders.append(str(source.relative_to(REPO_ROOT)))
    assert offenders == []


def test_locked_truth_is_not_inside_production_packages() -> None:
    forbidden = []
    for root in (REPO_ROOT / "api-server", REPO_ROOT / "workers", REPO_ROOT / "ptm_shared"):
        forbidden.extend(root.rglob("*.truth.json"))
    assert forbidden == []


def test_api_and_ordinary_worker_images_do_not_copy_or_mount_benchmarking() -> None:
    dockerfiles = [REPO_ROOT / "api-server" / "Dockerfile", REPO_ROOT / "workers" / "Dockerfile"]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in dockerfiles)
    assert "COPY benchmarking" not in combined


def test_dedicated_benchmark_runner_is_the_only_service_with_locked_truth_mount() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "benchmark-runner:" in compose
    assert compose.count("./benchmarks:/opt/benchmarks:ro") == 1
    assert "dockerfile: benchmarking/Dockerfile" in compose
