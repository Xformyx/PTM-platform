import logging
import os
import shutil
from typing import Any

import psutil
from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger("ptm-platform.system")


@router.get("/llm-config")
async def llm_config() -> dict[str, Any]:
    """Return the current LLM configuration used for report generation."""
    return {
        "default_provider": "ollama",
        "default_model": os.getenv("LLM_MODEL", "qwen2.5:32b"),
        "ollama_url": os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
    }


def _gpu_info() -> list[dict[str, Any]]:
    """Try to get GPU utilization via pynvml (nvidia-smi)."""
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            gpus.append({
                "index": i,
                "name": name,
                "gpu_util_pct": util.gpu,
                "mem_used_gb": round(mem.used / (1024 ** 3), 1),
                "mem_total_gb": round(mem.total / (1024 ** 3), 1),
                "mem_util_pct": round(mem.used / mem.total * 100, 1) if mem.total > 0 else 0,
            })
        pynvml.nvmlShutdown()
        return gpus
    except Exception:
        return []


@router.get("/metrics")
async def system_metrics() -> dict[str, Any]:
    cpu_pct = psutil.cpu_percent(interval=0.3)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_freq = psutil.cpu_freq()

    mem = psutil.virtual_memory()

    disk = shutil.disk_usage("/app/data") if shutil.os.path.exists("/app/data") else shutil.disk_usage("/")

    gpus = _gpu_info()

    return {
        "cpu": {
            "usage_pct": cpu_pct,
            "cores": cpu_count,
            "freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
        },
        "memory": {
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "usage_pct": mem.percent,
        },
        "disk": {
            "used_gb": round(disk.used / (1024 ** 3), 1),
            "total_gb": round(disk.total / (1024 ** 3), 1),
            "usage_pct": round(disk.used / disk.total * 100, 1),
        },
        "gpu": gpus,
    }
