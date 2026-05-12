"""
PTMQuant integration API.

Runs ptmquant:latest Docker container to convert MzML files → pg/pr matrices.
Progress is streamed via Redis → SSE (/api/events/ptmquant/{job_id}).
"""

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import AsyncGenerator, Literal, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.dependencies import get_current_user
from app.models.ptmquant_job import PTMQuantJob

router = APIRouter(prefix="/ptmquant", tags=["ptmquant"])
logger = logging.getLogger("ptm-platform.ptmquant")

settings = get_settings()


def _ptmquant_docker_client():
    """Docker SDK client with a long API read timeout for PTMQuant jobs.

    docker-py defaults to ~60 seconds.  Streaming ``container.logs(follow=True)``
    fails with ``UnixHTTPConnectionPool … Read timed out (read timeout=60)`` when
    diaquant spends many minutes between log lines; ``container.wait()`` can hit the
    same limit on some Docker/API combinations.

    Set ``DOCKER_CLIENT_TIMEOUT_SECONDS`` (integer seconds, e.g. ``604800``) to override.
    Use ``<= 0`` or ``0`` for the library default (~60 s) when debugging.
    """
    import docker as docker_sdk  # type: ignore

    raw = os.environ.get("DOCKER_CLIENT_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return docker_sdk.from_env(timeout=7 * 24 * 3600)
    try:
        timeout_sec = int(raw, 10)
    except ValueError:
        logger.warning(
            "Invalid DOCKER_CLIENT_TIMEOUT_SECONDS=%r; using 7-day timeout", raw,
        )
        return docker_sdk.from_env(timeout=7 * 24 * 3600)
    if timeout_sec <= 0:
        return docker_sdk.from_env()
    return docker_sdk.from_env(timeout=timeout_sec)


def _discard_stale_named_ptmquant_container(
    client,
    container_name: str,
    job_dir: Path,
) -> None:
    """Remove a leftover Docker container before ``containers.run(.., name=…)``.

    Re-run/retry reuse ``ptmquant_{job}_{uuid8}``.  If a previous run ended with a
    client timeout, killed daemon, or ``remove`` never ran, the old container
    still holds the name and Docker returns HTTP 409 Conflict.
    """
    import docker.errors as docker_errors  # type: ignore

    cid_file = job_dir / "container_id.txt"
    cid = cid_file.read_text().strip() if cid_file.exists() else ""
    if cid:
        try:
            client.containers.get(cid).remove(force=True)
            logger.info(
                "[ptmquant] removed stale container %.12s (from container_id.txt) before create",
                cid,
            )
        except docker_errors.NotFound:  # noqa: BLE001 — expected
            pass
        except Exception as exc:  # pragma: no cover — log and retry by name below
            logger.warning(
                "[ptmquant] could not remove container %.12s: %s",
                cid,
                exc,
            )
        try:
            cid_file.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        client.containers.get(container_name).remove(force=True)
        logger.info(
            "[ptmquant] removed stale named container %r before create",
            container_name,
        )
    except docker_errors.NotFound:  # noqa: BLE001
        pass
    except Exception as exc:
        logger.warning(
            "[ptmquant] could not remove container by name %r: %s",
            container_name,
            exc,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pass definitions (multi-select in UI)
# ──────────────────────────────────────────────────────────────────────────────

AVAILABLE_PASSES = [
    {"id": "phospho",         "label": "Phosphorylation",         "description": "Ser/Thr/Tyr phosphorylation"},
    {"id": "ubiquitin",       "label": "Ubiquitination",          "description": "Lys ubiquitination (GlyGly)"},
    {"id": "acetyl_methyl",   "label": "Acetylation/Methylation", "description": "Lys acetylation & methylation"},
    {"id": "oglcnac",         "label": "O-GlcNAc",                "description": "Ser/Thr O-linked N-acetylglucosamine"},
    {"id": "citrullination",  "label": "Citrullination",          "description": "Arg deimination (R → Cit, Δmass 0.984)"},
    {"id": "lactyl_acyl",     "label": "Lactylation",             "description": "Lys lactylation (K-acyl, mc=3)"},
]

# Enzyme catalog exposed to the UI (mirrors diaquant.enzymes.ENZYME_CATALOG).
AVAILABLE_ENZYMES = [
    {"id": "trypsin",         "label": "Trypsin/P",     "description": "KR | restrict=P (default)"},
    {"id": "trypsin-strict",  "label": "Trypsin",       "description": "KR | strict (no P rule)"},
    {"id": "lys-c",           "label": "Lys-C/P",       "description": "K | restrict=P"},
    {"id": "lys-c-strict",    "label": "Lys-C",         "description": "K | strict"},
    {"id": "arg-c",           "label": "Arg-C",         "description": "R"},
    {"id": "asp-n",           "label": "Asp-N",         "description": "D (N-terminal)"},
    {"id": "glu-c",           "label": "Glu-C",         "description": "E (mc=3 default)"},
    {"id": "chymotrypsin",    "label": "Chymotrypsin/P","description": "FWY | restrict=P"},
    {"id": "no-cleavage",     "label": "No cleavage",   "description": "Unspecific / top-down"},
]

# Orbitrap instrument presets (mirrors diaquant.instruments.INSTRUMENT_PRESETS).
AVAILABLE_INSTRUMENTS = [
    {"id": "exploris_240",     "label": "Exploris 240 (default)", "description": "MS1 6 / MS2 12 ppm, 400–1000 m/z, NCE 28"},
    {"id": "orbitrap_astral",  "label": "Orbitrap Astral",        "description": "MS1 3 / MS2 8 ppm, 380–980 m/z, NCE 27"},
    {"id": "orbitrap_eclipse", "label": "Orbitrap Eclipse",       "description": "MS1 5 / MS2 10 ppm, 350–1500 m/z, NCE 30"},
    {"id": "fusion_lumos",     "label": "Fusion Lumos",           "description": "MS1 5 / MS2 12 ppm, 350–1500 m/z, NCE 30"},
]

# ──────────────────────────────────────────────────────────────────────────────
# Helpers: host path resolution
# ──────────────────────────────────────────────────────────────────────────────

def _host_storage_dir() -> Path:
    """Derive host storage/ path from HOST_DATA_DIR env var.

    HOST_DATA_DIR = /host/path/to/ptm-platform/data
    → storage       = /host/path/to/ptm-platform/storage
    """
    host_data = settings.HOST_DATA_DIR
    if not host_data:
        raise HTTPException(
            status_code=500,
            detail="HOST_DATA_DIR is not configured. Set it in .env for Docker volume mapping.",
        )
    return Path(host_data).parent / "storage"


def _host_file_share() -> Path:
    return _host_storage_dir() / "file_share"


def _host_reference() -> Path:
    """Host path for data/reference/ (parallel to storage/)."""
    host_data = settings.HOST_DATA_DIR
    if not host_data:
        raise HTTPException(
            status_code=500,
            detail="HOST_DATA_DIR is not configured.",
        )
    return Path(host_data) / "reference"


def _host_ptmquant(job_id: str) -> Path:
    return _host_storage_dir() / "ptmquant" / job_id


def _container_file_share() -> Path:
    return Path(settings.FILE_SHARE_DIR)


def _container_ptmquant(job_id: str) -> Path:
    return Path(settings.PTMQUANT_DIR) / job_id


# ──────────────────────────────────────────────────────────────────────────────
# Progress parsing
# ──────────────────────────────────────────────────────────────────────────────

_PROGRESS_PATTERNS = [
    (re.compile(r"\[diaquant[^\]]*\] starting", re.I),    2.0),
    (re.compile(r"Running Sage", re.I),                   10.0),
    (re.compile(r"generated \d+ fragments", re.I),        20.0),
    (re.compile(r"pass completed.*phospho", re.I),        60.0),
    (re.compile(r"pass completed.*ubiquitin", re.I),      65.0),
    (re.compile(r"pass completed.*acetyl", re.I),         70.0),
    (re.compile(r"pass completed", re.I),                 60.0),
    (re.compile(r"RT alignment|rt.alignment", re.I),      72.0),
    (re.compile(r"Quantif|DirectLFQ|directlfq", re.I),    80.0),
    (re.compile(r"Writing output|report\.tsv", re.I),     88.0),
    (re.compile(r"\[diaquant\].*done|finished", re.I),    95.0),
]

# Matches: "processing files 0 .. 8"  or  "processing files 8 .. 12"
_RE_FILE_BATCH  = re.compile(r"processing files\s+(\d+)\s*\.\.\s*(\d+)", re.I)
# Matches first line: "mzml  : 12 files"
_RE_TOTAL_FILES = re.compile(r"mzml\s*:\s*(\d+)\s*file", re.I)
# Matches: "[diaquant] batch 2/3: ['file1.mzML', ...]"
_RE_BATCH_PROGRESS = re.compile(r"batch\s+(\d+)/(\d+):", re.I)
# Matches: "[diaquant] merging N batch results..."
_RE_MERGING = re.compile(r"merging\s+(\d+)\s+batch", re.I)


def _parse_progress(line: str, total_files: int = 0, current_progress: float = 0) -> tuple[Optional[float], Optional[str]]:
    """Return (progress_pct, file_status_label) from a log line."""
    # Batch-level progress: "batch 2/3:"
    m_batch = _RE_BATCH_PROGRESS.search(line)
    if m_batch:
        cur_batch = int(m_batch.group(1))
        n_batches = int(m_batch.group(2))
        pct = 15.0 + (cur_batch - 1) / n_batches * 45.0  # 15~60%
        label = f"배치 {cur_batch}/{n_batches} 처리 중"
        return pct, label

    # Per-file batch progress within Sage: "processing files X .. Y"
    m = _RE_FILE_BATCH.search(line)
    if m and total_files > 0:
        end_idx = int(m.group(2))
        pct = 20.0 + (end_idx / total_files) * 40.0  # 20~60%
        label = f"{end_idx}/{total_files} 파일 처리 중"
        return min(pct, 59.9), label

    # Merging batches
    if _RE_MERGING.search(line):
        return 62.0, "배치 결과 병합 중"

    for pattern, pct in _PROGRESS_PATTERNS:
        if pattern.search(line):
            if pct > current_progress:
                return pct, None
    return None, None


# ──────────────────────────────────────────────────────────────────────────────
# Background Docker runner
# ──────────────────────────────────────────────────────────────────────────────

async def _run_ptmquant(job_id: str, db_url: str, attach_container_id: str | None = None) -> None:
    """Execute ptmquant:latest in a sibling Docker container, stream progress.
    If attach_container_id is given, skip container creation and attach to that existing container.
    """
    redis = await get_redis()
    channel = f"ptmquant:progress:{job_id}"

    async def _publish(payload: dict) -> None:
        try:
            await redis.publish(channel, json.dumps(payload))
        except Exception:
            pass

    # Resolve paths
    try:
        host_file_share = str(_host_file_share())
        host_job_dir    = str(_host_storage_dir() / "ptmquant" / job_id)
        container_job   = _container_ptmquant(job_id)
        job_path        = Path(settings.PTMQUANT_DIR) / job_id
    except HTTPException as e:
        await _publish({"type": "error", "message": str(e.detail), "progress": 0})
        await _update_job_status(job_id, "failed", error=str(e.detail))
        return

    # Read config to get output_subdir
    config_path = job_path / "config.yaml"
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        output_dir_in_container = cfg.get("output_dir", "/output")
    except Exception as e:
        await _publish({"type": "error", "message": f"Cannot read config: {e}", "progress": 0})
        await _update_job_status(job_id, "failed", error=str(e))
        return

    # The output directory on host is storage/file_share/{output_subdir}
    # (stored in DB as output_subdir)
    # We passed it as an absolute container path for reading; decode from config YAML
    # Actually we store it separately in the job dir (see POST handler)
    subdir_file = job_path / "output_subdir.txt"
    if subdir_file.exists():
        output_subdir = subdir_file.read_text().strip()
    else:
        output_subdir = "ptmquant_output"

    host_output_dir = str(_host_file_share() / output_subdir)
    Path(settings.FILE_SHARE_DIR) / output_subdir  # ensure created by POST handler

    host_reference = str(_host_reference())
    # v0.5.3: shared AlphaPeptDeep predicted-library cache, bind-mounted into
    # the ptmquant container at /cache/predicted_libs so diaquant can reuse
    # cached libraries across jobs (keyed by FASTA + PTM set + enzyme +
    # instrument + mz range).  Falls back gracefully when unset.
    host_lib_cache = _host_storage_dir() / "predicted_lib_cache"
    host_lib_cache.mkdir(parents=True, exist_ok=True)
    volumes = {
        host_file_share: {"bind": "/input",               "mode": "ro"},
        host_reference:  {"bind": "/reference",           "mode": "ro"},
        host_output_dir: {"bind": "/output",              "mode": "rw"},
        host_job_dir:    {"bind": "/work",                "mode": "ro"},
        str(host_lib_cache): {"bind": "/cache/predicted_libs", "mode": "rw"},
    }

    # Read memory limit from job dir (written by POST handler)
    mem_file = job_path / "max_memory_gb.txt"
    max_memory_gb = int(mem_file.read_text().strip()) if mem_file.exists() else 16
    mem_limit = f"{max(8, min(max_memory_gb, 128))}g"

    resume_file = job_path / "resume.txt"
    resume_flag = resume_file.exists() and resume_file.read_text().strip() == "1"
    # Resolve diaquant search engine:
    #   1) job config.yaml ``search_engine`` / ``engine`` (written by POST /jobs)
    #   2) else PTMQUANT_DIAQUANT_ENGINE (default sage — legacy jobs without yaml key)
    _yaml_eng = str(cfg.get("search_engine") or cfg.get("engine") or "").strip().lower()
    if _yaml_eng in ("alphadia", "sage"):
        _diaqu_engine = _yaml_eng
    else:
        _diaqu_engine = os.environ.get(
            "PTMQUANT_DIAQUANT_ENGINE", "sage"
        ).strip().lower()
    if _diaqu_engine not in ("alphadia", "sage"):
        _diaqu_engine = "sage"
    _engine_arg = "" if _diaqu_engine == "alphadia" else " --engine sage"
    docker_command = (
        f"run --config /work/config.yaml{_engine_arg}"
        + (" --resume" if resume_flag else "")
    )
    logger.info(
        "[ptmquant] job %s diaquant argv: %s (resolved_engine=%s, yaml=%r, env=%r)",
        job_id,
        docker_command,
        _diaqu_engine,
        cfg.get("search_engine"),
        os.environ.get("PTMQUANT_DIAQUANT_ENGINE"),
    )

    # Read batch_size for informational log message
    batch_size_info = cfg.get("batch_size", 0)
    n_files_info = len(cfg.get("mzml_files", []))

    await _update_job_status(job_id, "running")
    batch_msg = (
        f", auto-batch={batch_size_info}파일씩 ({-((-n_files_info) // batch_size_info)}배치)"
        if batch_size_info > 0 and n_files_info > batch_size_info
        else ""
    )
    try:
        client = _ptmquant_docker_client()

        if attach_container_id:
            # Re-attach to an already-running container (e.g. after server restart)
            container = await asyncio.to_thread(client.containers.get, attach_container_id)
            logger.info(f"[ptmquant] Re-attached to container {attach_container_id[:12]} for job {job_id}")
            await _publish({"type": "log", "message": f"[복구] 실행 중인 컨테이너에 재연결됨 ({attach_container_id[:12]})", "progress": 47})
        else:
            await _publish({"type": "log", "message": f"Starting ptmquant container (mem={mem_limit}{', resume' if resume_flag else ''}{batch_msg})...", "progress": 5})
            # Use job name as container name (sanitized, with job_id suffix for uniqueness)
            _name_file = job_path / "job_name.txt"
            _job_name = _name_file.read_text().strip() if _name_file.exists() else job_id[:8]
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", _job_name)[:40]
            container_name = f"ptmquant_{safe_name}_{job_id[:8]}"
            await asyncio.to_thread(
                _discard_stale_named_ptmquant_container,
                client,
                container_name,
                job_path,
            )
            container = await asyncio.to_thread(
                client.containers.run,
                "ptmquant:latest",
                command=docker_command,
                volumes=volumes,
                mem_limit=mem_limit,
                name=container_name,
                detach=True,
                remove=False,
            )
            # Persist container ID so cancel endpoint can kill it
            (job_path / "container_id.txt").write_text(container.id)

        log_lines: list[str] = []
        current_progress = 5.0
        total_files = 0
        file_status = ""

        # Stream logs via a background thread → asyncio.Queue to avoid
        # blocking the event loop (Docker SDK is sync-only).
        loop = asyncio.get_event_loop()
        log_q: asyncio.Queue = asyncio.Queue()

        def _log_reader() -> None:
            try:
                for chunk in container.logs(
                    stream=True, follow=True, stdout=True, stderr=True
                ):
                    loop.call_soon_threadsafe(log_q.put_nowait, chunk)
            except Exception as exc:
                loop.call_soon_threadsafe(
                    log_q.put_nowait, f"[LOG ERROR] {exc}\n".encode()
                )
            finally:
                loop.call_soon_threadsafe(log_q.put_nowait, None)  # sentinel

        reader_thread = threading.Thread(target=_log_reader, daemon=True)
        reader_thread.start()

        while True:
            chunk = await log_q.get()
            if chunk is None:
                break
            line = (chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")).rstrip()
            if not line:
                continue
            log_lines.append(line)

            # Extract total file count from header line
            m_total = _RE_TOTAL_FILES.search(line)
            if m_total:
                total_files = int(m_total.group(1))

            pct, label = _parse_progress(line, total_files, current_progress)
            if pct and pct > current_progress:
                current_progress = pct
            if label:
                file_status = label

            await _publish({
                "type": "log",
                "message": line,
                "progress": current_progress,
                "file_status": file_status,
                "total_files": total_files,
            })
            await _update_job_progress(job_id, current_progress)

        reader_thread.join(timeout=5)

        result = await asyncio.to_thread(container.wait)
        exit_code = result.get("StatusCode", -1)

        # Fallback: collect any remaining logs not captured by streaming
        if not log_lines:
            try:
                fallback = await asyncio.to_thread(
                    lambda: container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
                )
                log_lines = fallback.splitlines()
            except Exception:
                pass

        await asyncio.to_thread(container.remove, force=True)

        if exit_code == 0:
            await _publish({"type": "done", "message": "Conversion complete!", "progress": 100})
            await _update_job_status(job_id, "done", log="\n".join(log_lines), progress=100)
        else:
            err = f"ptmquant exited with code {exit_code}"
            await _publish({"type": "error", "message": err, "progress": current_progress})
            await _update_job_status(job_id, "failed", log="\n".join(log_lines), error=err)

    except Exception as e:
        logger.error(f"[PTMQuant] job {job_id} failed: {e}", exc_info=True)
        await _publish({"type": "error", "message": str(e), "progress": 0})
        await _update_job_status(job_id, "failed", error=str(e))


async def _update_job_status(
    job_id: str,
    status_val: str,
    log: Optional[str] = None,
    error: Optional[str] = None,
    progress: Optional[float] = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PTMQuantJob).where(PTMQuantJob.job_id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = status_val
            if log is not None:
                job.log = log
            if error is not None:
                job.error_message = error
            if progress is not None:
                job.progress = progress
            await session.commit()


async def _update_job_progress(job_id: str, progress: float) -> None:
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PTMQuantJob).where(PTMQuantJob.job_id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            job.progress = progress
            await session.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    name: str
    reference_file: str          # species/filename.fasta relative to REFERENCE_DIR
    input_files: list[str]       # mzML filenames in file_share
    passes: list[str]            # e.g. ["phospho", "ubiquitin"]
    output_subdir: str           # subfolder name in file_share for output
    threads: int = 4             # CPU threads (1-16)
    max_memory_gb: int = 32      # Docker memory limit in GB (8-96)
    resume: bool = False         # Reuse existing pass results (skip completed Sage runs)
    # --- v0.5.2 knobs (all optional, safe fallbacks applied in diaquant 0.5.1) ---
    enzyme: str = "trypsin"              # See AVAILABLE_ENZYMES
    instrument: str = "exploris_240"     # See AVAILABLE_INSTRUMENTS
    # v0.5.3: AlphaPeptDeep predicted library is on by default.  Cached
    # libraries under /cache/predicted_libs are shared across jobs keyed by
    # FASTA + PTM set + instrument + enzyme so repeated runs on the same
    # species / FASTA / PTM tuple are effectively free.
    predicted_library: bool = True       # Enable AlphaPeptDeep predicted spectral library
    transfer_learning: bool = False      # Fine-tune AlphaPeptDeep on pass-1 high-confidence PSMs
    # v0.5.3: phospho localization filter applied to report.ptm_site_matrix.tsv.
    # 0.75 matches the recommended PhosphoRS / SpectroMine threshold; set
    # include_low_loc_sites=True to keep all sites and filter downstream.
    site_probability_cutoff: float = 0.75
    include_low_loc_sites: bool = False
    # diaquant CLI --engine (stored in job config.yaml; overrides loose env defaults).
    search_engine: Literal["alphadia", "sage"] = "alphadia"


class JobResponse(BaseModel):
    job_id: str
    name: str
    status: str
    reference_file: Optional[str]
    input_files: Optional[list]
    passes: Optional[list]
    output_subdir: Optional[str]
    enzyme: Optional[str] = None
    instrument: Optional[str] = None
    predicted_library: Optional[bool] = None
    transfer_learning: Optional[bool] = None
    site_probability_cutoff: Optional[float] = None
    include_low_loc_sites: Optional[bool] = None
    progress: float
    error_message: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, job: PTMQuantJob) -> "JobResponse":
        return cls(
            job_id=job.job_id,
            name=job.name,
            status=job.status,
            reference_file=job.reference_file,
            input_files=job.input_files,
            passes=job.passes,
            output_subdir=job.output_subdir,
            enzyme=job.enzyme,
            instrument=job.instrument,
            predicted_library=bool(job.predicted_library) if job.predicted_library is not None else None,
            transfer_learning=bool(job.transfer_learning) if job.transfer_learning is not None else None,
            site_probability_cutoff=float(job.site_probability_cutoff)
                if getattr(job, "site_probability_cutoff", None) is not None else None,
            include_low_loc_sites=bool(job.include_low_loc_sites)
                if getattr(job, "include_low_loc_sites", None) is not None else None,
            progress=job.progress,
            error_message=job.error_message,
            created_at=job.created_at.isoformat() if job.created_at else "",
            updated_at=job.updated_at.isoformat() if job.updated_at else "",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/memory-info")
async def get_memory_info(_=Depends(get_current_user)):
    """Return host system total RAM and Docker daemon memory limit (in GB)."""
    host_total_gb: Optional[int] = None
    docker_limit_gb: Optional[int] = None

    try:
        client = _ptmquant_docker_client()
        info = client.info()
        # Docker reports MemTotal in bytes (the memory available to Docker VM)
        mem_bytes = info.get("MemTotal", 0)
        if mem_bytes:
            docker_limit_gb = max(1, round(mem_bytes / (1024 ** 3)))
            host_total_gb = docker_limit_gb  # same as Docker VM on Linux; on macOS = Docker Desktop allocation
    except Exception as exc:
        logger.warning(f"Cannot read Docker memory info: {exc}")

    return {
        "docker_limit_gb": docker_limit_gb,
        "host_total_gb": host_total_gb,
    }


@router.get("/passes")
async def list_passes(_=Depends(get_current_user)):
    """Return available PTM analysis pass types."""
    return AVAILABLE_PASSES


@router.get("/enzymes")
async def list_enzymes(_=Depends(get_current_user)):
    """Return supported proteolytic enzymes (v0.5.2)."""
    return AVAILABLE_ENZYMES


@router.get("/instruments")
async def list_instruments(_=Depends(get_current_user)):
    """Return supported Orbitrap instrument presets (v0.5.2)."""
    return AVAILABLE_INSTRUMENTS


@router.get("/files")
async def list_files(path: str = "", _=Depends(get_current_user)):
    """Browse .mzML files and subdirectories in file_share at the given relative path.
    Also returns FASTA references (always from data/reference/).
    """
    share = Path(settings.FILE_SHARE_DIR)
    ref_dir = Path(settings.REFERENCE_DIR)

    # Resolve current directory within file_share
    if path:
        parts = [p for p in Path(path).parts if p not in ("", ".", "..")]
        current = share.joinpath(*parts) if parts else share
    else:
        current = share

    try:
        current = current.resolve()
        share_resolved = share.resolve()
        if not str(current).startswith(str(share_resolved)):
            current = share_resolved  # fallback to root on invalid path
    except Exception:
        current = share.resolve()
        share_resolved = current

    rel_base = current.relative_to(share.resolve()) if current != share.resolve() else Path(".")

    mzml_files = []
    dir_entries = []

    try:
        for entry in sorted(current.iterdir()):
            if entry.name.startswith("."):
                continue
            entry_rel = str(rel_base / entry.name) if str(rel_base) != "." else entry.name
            if entry.is_dir():
                dir_entries.append({"name": entry.name, "path": entry_rel})
            elif entry.is_file() and entry.name.lower().endswith(".mzml"):
                mzml_files.append({"name": entry.name, "path": entry_rel, "size": entry.stat().st_size})
    except Exception as e:
        logger.warning(f"Error listing file_share at {current}: {e}")

    # Scan FASTA files from reference subdirectories (always from root)
    SPECIES_LABELS = {
        "human": "Human (Homo sapiens)",
        "mouse": "Mouse (Mus musculus)",
    }
    fasta_files = []
    try:
        for species_dir in sorted(ref_dir.iterdir()):
            if not species_dir.is_dir():
                continue
            species = species_dir.name.lower()
            label = SPECIES_LABELS.get(species, species.capitalize())
            for entry in sorted(species_dir.iterdir()):
                if entry.is_file() and entry.suffix.lower() in (".fasta", ".fa"):
                    fasta_files.append({
                        "name": entry.name,
                        "species": species,
                        "label": label,
                        "path": f"{species}/{entry.name}",
                        "size": entry.stat().st_size,
                    })
    except Exception as e:
        logger.warning(f"Error listing reference dir: {e}")

    return {
        "current_path": str(rel_base) if str(rel_base) != "." else "",
        "dirs": dir_entries,
        "mzml": mzml_files,
        "fasta": fasta_files,
    }


@router.post("/jobs", status_code=201)
async def create_job(
    req: CreateJobRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create and start a PTMQuant conversion job."""
    share = Path(settings.FILE_SHARE_DIR)

    ref_dir = Path(settings.REFERENCE_DIR)

    # Validate inputs — input_files may now be relative paths (subdir/file.mzML)
    for f in req.input_files:
        parts = [p for p in Path(f).parts if p not in ("", "..", ".")]
        full = share.joinpath(*parts) if parts else share / f
        if not full.is_file():
            raise HTTPException(400, detail=f"mzML file not found in file_share: {f}")
    # reference_file is stored as "species/filename.fasta" (relative to REFERENCE_DIR)
    ref_path = ref_dir / req.reference_file
    if not ref_path.is_file():
        raise HTTPException(400, detail=f"Reference FASTA not found: {req.reference_file}")
    if not req.output_subdir or "/" in req.output_subdir or ".." in req.output_subdir:
        raise HTTPException(400, detail="Invalid output_subdir name")
    if not req.passes:
        raise HTTPException(400, detail="At least one PTM pass must be selected")

    valid_pass_ids = {p["id"] for p in AVAILABLE_PASSES}
    for p in req.passes:
        if p not in valid_pass_ids:
            raise HTTPException(400, detail=f"Unknown pass: {p}")
    # v0.5.2: validate enzyme + instrument ids (falls back to defaults if empty string)
    req.enzyme = (req.enzyme or "trypsin").strip()
    req.instrument = (req.instrument or "exploris_240").strip()
    if req.enzyme not in {e["id"] for e in AVAILABLE_ENZYMES}:
        raise HTTPException(400, detail=f"Unknown enzyme: {req.enzyme}")
    if req.instrument not in {i["id"] for i in AVAILABLE_INSTRUMENTS}:
        raise HTTPException(400, detail=f"Unknown instrument preset: {req.instrument}")

    # Create job record
    job_id = str(uuid.uuid4())
    job = PTMQuantJob(
        job_id=job_id,
        name=req.name,
        status="pending",
        reference_file=req.reference_file,
        input_files=req.input_files,
        passes=req.passes,
        output_subdir=req.output_subdir,
        enzyme=req.enzyme,
        instrument=req.instrument,
        predicted_library=1 if req.predicted_library else 0,
        transfer_learning=1 if req.transfer_learning else 0,
        site_probability_cutoff=float(req.site_probability_cutoff),
        include_low_loc_sites=1 if req.include_low_loc_sites else 0,
        progress=0.0,
        user_id=user.id if hasattr(user, "id") and user.id else None,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Create job directory and write config.yaml
    job_dir = Path(settings.PTMQUANT_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save runtime params for Docker runner
    (job_dir / "output_subdir.txt").write_text(req.output_subdir)
    (job_dir / "max_memory_gb.txt").write_text(str(max(8, min(req.max_memory_gb, 128))))
    (job_dir / "resume.txt").write_text("1" if req.resume else "0")
    (job_dir / "job_name.txt").write_text(req.name)

    # Create output directory in file_share
    out_dir = share / req.output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Auto-calculate batch_size based on file sizes and mem_limit.
    #
    # Empirical memory model for Sage phospho search on eukaryotic proteomes:
    #   peak_mem ≈ SAGE_INDEX_GB (fixed, FASTA-derived fragment library)
    #              + n_files × PER_FILE_GB (spectra loading)
    #
    # Calibrated from observed data: 12 × 1.1 GB mzML + Mouse phospho ≈ 26 GB peak.
    # → SAGE_INDEX_GB ≈ 11, PER_FILE per raw GB ≈ 1.25/1.1 ≈ 1.15
    # A 4-file batch hit exactly 16 GB (SIGKILL), confirming the estimate.
    # We reserve 2 GB headroom for Docker/OS overhead.
    SAGE_INDEX_OVERHEAD_GB = 12.0   # conservative fragment-library overhead (fixed)
    SAGE_PER_FILE_MULT    = 1.2     # memory per raw GB of mzML (spectra loading)
    HEADROOM_GB           = 1.5     # buffer so Docker doesn't SIGKILL at the limit
    BYTES_PER_GB = 1024 ** 3

    total_mzml_bytes = sum(
        (share / f).stat().st_size for f in req.input_files if (share / f).is_file()
    )
    n_files = len(req.input_files)
    avg_file_gb = (total_mzml_bytes / BYTES_PER_GB / n_files) if n_files else 0.0
    available_for_files = max(0.0, req.max_memory_gb - SAGE_INDEX_OVERHEAD_GB - HEADROOM_GB)
    calc_batch_size = max(1, int(available_for_files / (avg_file_gb * SAGE_PER_FILE_MULT))) if avg_file_gb > 0 else n_files
    # Only enable batching when it would actually split the files
    batch_size = calc_batch_size if calc_batch_size < n_files else 0
    logger.info(
        f"[{job_id}] mzML total={total_mzml_bytes/BYTES_PER_GB:.1f}GB avg={avg_file_gb:.2f}GB/file "
        f"mem_limit={req.max_memory_gb}GB avail_for_files={available_for_files:.1f}GB "
        f"→ calc_batch={calc_batch_size} effective={'no batching' if batch_size == 0 else f'{batch_size} files/batch'}"
    )

    # Build config.yaml
    # reference_file = "species/filename.fasta" → /reference/species/filename.fasta
    threads = max(0, min(req.threads, 64))  # clamp to sane range
    config = {
        "fasta": f"/reference/{req.reference_file}",
        "mzml_files": [f"/input/{f.lstrip('/')}" for f in req.input_files],
        "output_dir": "/output",
        "passes": req.passes,
        "threads": threads,
        "batch_size": batch_size,
        # v0.5.2: forward UI knobs to diaquant
        "enzyme": req.enzyme,
        "instrument": req.instrument,
        # v0.5.3: AlphaPeptDeep predicted-library is always on by default.
        # Users can still opt out per job by unchecking the UI toggle; in
        # that case ``req.predicted_library`` is False and diaquant falls
        # back to Sage's built-in theoretical library.
        "predicted_library": bool(req.predicted_library),
        "rescore_with_prediction": bool(req.predicted_library),
        "pred_lib_transfer_learning": bool(req.transfer_learning),
        # v0.5.3: shared cross-job predicted-library cache.  Path is inside
        # the ptmquant container; the api-server mounts the host directory
        # at /cache/predicted_libs (see volumes dict above).
        "pred_lib_cache_dir": "/cache/predicted_libs",
        # v0.5.3: phospho localization-probability filter for the site matrix.
        "site_probability_cutoff": float(req.site_probability_cutoff),
        "include_low_loc_sites": bool(req.include_low_loc_sites),
        # Propagates to Docker argv via _run_ptmquant (diaquant ignores unknown YAML keys).
        "search_engine": req.search_engine,
    }
    with open(job_dir / "config.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Launch background task
    asyncio.create_task(_run_ptmquant(job_id, ""))

    return JobResponse.from_orm(job)


@router.get("/jobs")
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(PTMQuantJob).order_by(PTMQuantJob.created_at.desc()).limit(100)
    )
    jobs = result.scalars().all()
    return [JobResponse.from_orm(j) for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    return JobResponse.from_orm(job)


@router.get("/jobs/{job_id}/log")
async def get_job_log(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    return PlainTextResponse(job.log or "")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Kill the running Docker container and mark job as cancelled."""
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(400, detail=f"Job is not active (status: {job.status})")

    # Try to kill the Docker container
    job_path = Path(settings.PTMQUANT_DIR) / job_id
    container_id_file = job_path / "container_id.txt"
    killed = False
    if container_id_file.exists():
        container_id = container_id_file.read_text().strip()
        try:
            client = await asyncio.to_thread(_ptmquant_docker_client)
            container = await asyncio.to_thread(client.containers.get, container_id)
            await asyncio.to_thread(container.kill)
            await asyncio.to_thread(container.remove, **{"force": True})
            killed = True
            logger.info(f"[PTMQuant] Killed container {container_id} for job {job_id}")
        except Exception as e:
            logger.warning(f"[PTMQuant] Could not kill container {container_id}: {e}")

    # Publish cancellation to SSE
    redis = await get_redis()
    await redis.publish(
        f"ptmquant:progress:{job_id}",
        json.dumps({"type": "error", "message": "사용자에 의해 중단됨", "progress": job.progress}),
    )

    job.status = "cancelled"
    job.error_message = "사용자에 의해 중단됨"
    await db.commit()

    return {"ok": True, "killed": killed}


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Reset a failed/cancelled job and re-run it."""
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(400, detail=f"Only failed or cancelled jobs can be retried (status: {job.status})")

    # Reset job state
    job.status = "pending"
    job.progress = 0
    job.error_message = None
    job.log = ""
    await db.commit()
    await db.refresh(job)

    db_url = str(settings.DATABASE_URL)
    asyncio.create_task(_run_ptmquant(job_id, db_url))
    logger.info(f"[PTMQuant] Retrying job {job_id} ({job.name})")
    return {"ok": True, "job_id": job_id}


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")

    job_dir = Path(settings.PTMQUANT_DIR) / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)

    await db.delete(job)
    await db.commit()


@router.get("/jobs/{job_id}/files")
async def list_job_files(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")

    if not job.output_subdir:
        return []

    out_dir = Path(settings.FILE_SHARE_DIR) / job.output_subdir
    if not out_dir.exists():
        return []

    files = []
    for entry in sorted(out_dir.rglob("*")):
        if not entry.is_file():
            continue
        rel = str(entry.relative_to(out_dir))
        # Skip intermediate batch directories (sage_batch_0, sage_batch_1, ...)
        if any(part.startswith("sage_batch_") for part in Path(rel).parts):
            continue
        ext = entry.suffix.lower()
        stat = entry.stat()
        files.append({
            "name": entry.name,
            "path": rel,
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "is_tsv": ext == ".tsv",
            "is_json": ext == ".json",
            "is_matrix": "pg_matrix" in entry.name or "pr_matrix" in entry.name or "ptm_site" in entry.name,
        })
    return files


@router.get("/jobs/{job_id}/files/{filename:path}")
async def download_job_file(
    job_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job or not job.output_subdir:
        raise HTTPException(404, detail="Job not found")

    file_path = Path(settings.FILE_SHARE_DIR) / job.output_subdir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, detail="File not found")

    # Safety: ensure path stays within output dir
    out_dir = Path(settings.FILE_SHARE_DIR) / job.output_subdir
    try:
        file_path.resolve().relative_to(out_dir.resolve())
    except ValueError:
        raise HTTPException(403, detail="Access denied")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="text/tab-separated-values" if file_path.suffix == ".tsv" else "application/octet-stream",
    )


@router.get("/jobs/{job_id}/preview/{filename:path}")
async def preview_job_file(
    job_id: str,
    filename: str,
    lines: int = 100,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Return first N lines of a TSV/text file for preview."""
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job or not job.output_subdir:
        raise HTTPException(404, detail="Job not found")

    file_path = Path(settings.FILE_SHARE_DIR) / job.output_subdir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, detail="File not found")

    out_dir = Path(settings.FILE_SHARE_DIR) / job.output_subdir
    try:
        file_path.resolve().relative_to(out_dir.resolve())
    except ValueError:
        raise HTTPException(403, detail="Access denied")

    try:
        content_lines = []
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= lines:
                    break
                content_lines.append(line.rstrip("\n"))
        return PlainTextResponse("\n".join(content_lines))
    except Exception as e:
        raise HTTPException(500, detail=f"Cannot read file: {e}")
