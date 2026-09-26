"""Digest numerical preprocessing dependencies, including shared contracts."""
import hashlib
import json
from pathlib import Path

QUANTIFICATION_ENGINE_VERSION = "quantification_engine.v2"


def quantification_dependency_digest(core_dir, shared_dir=None):
    roots = {"core": Path(core_dir), "shared": Path(shared_dir) if shared_dir else Path(__file__).parent}
    files = {}
    for namespace, root in roots.items():
        # Shared numerical helpers may acquire transitive dependencies. Include
        # all production Python modules so adding an import cannot leave stale
        # quantification cached. Test files are not engine dependencies.
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(root)
            if "tests" in relative.parts or "__pycache__" in relative.parts:
                continue
            files[f"{namespace}/{relative.as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {"engine_version": QUANTIFICATION_ENGINE_VERSION, "files": files}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
