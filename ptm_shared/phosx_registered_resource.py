"""Locate the round 09 PhosX matrices when they are already on the shared reference mount.

The worker scores only through the existing specificity manifest path. This module
does not download, score, or treat a gene z-score table as PhosX.
"""
import json
from pathlib import Path

from .annotation_registry import digest
from .official_specificity import PHOSX_COMMIT

DECLARED_DIRECTORY = "phosx-0.23.1-b556f59"
DECLARED_MATRIX_SHA256 = "7d18a78d6efc45925aacae9c62ea26c5d7c22519eb856b2891debeed0ea42c6d"
DECLARED_BACKGROUND_SHA256 = "487beac611126c973c36b3b01161991a7c01d08e8d00f764136eb2c45aac1c11"
DECLARED_METADATA_SHA256 = "ab48c161eb8f35225cc410331c71cd0d35c1fd198a828a6eb78069d3fc341952"
"""회차 09에서 실행 전에 고정한 PhosX 0.23.1 행렬·배경·metadata 해시.

docs/astra_evidence_integration/ROUND09B_KO.md 와 ROUND09_RESULTS.json.
2026-10-09 검증값. 이 상수로 새 점수를 만들지 않는다.
해석 한계: 해시가 맞다는 것은 같은 행렬 파일이라는 뜻이다. 여섯 시간점 실행 기록이 아니다.
주장 금지: 이 자원이 연결되었다고 kinase 귀속 정확도가 올랐다고 하지 않는다.
"""


def locate_declared_phosx_manifest(reference_root):
    """Return the local manifest only when the declared matrix bytes are present.

    구현 대상: docs/astra_evidence_integration/MIGRATION_AND_OPERATIONS_KO.md «PhosX 등록 자원»
    사전등록: 2026-10-13. 해시 값은 회차 09의 실행 전 고정값이다. 이번 조회 결과로 고르지 않았다.
    해석 한계: 파일이 없으면 None이다. None은 실패가 아니라 기존 resource_unavailable 경로다.
    주장 금지: manifest를 찾았다고 여섯 시간점 PhosX가 실행되었다고 하지 않는다.
    """
    root = Path(reference_root) / DECLARED_DIRECTORY
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        resource = json.loads(manifest.read_text())
    except json.JSONDecodeError:
        return None
    if resource.get("adapter") != "phosx_official.v1":
        return None
    if resource.get("local_use_permission") != "permitted" or resource.get("derived_export_permission") != "permitted":
        return None
    if resource.get("resource_version") != PHOSX_COMMIT:
        return None
    if resource.get("matrix_sha256") != DECLARED_MATRIX_SHA256 or resource.get("background_sha256") != DECLARED_BACKGROUND_SHA256:
        return None
    for name, expected in (("matrix", DECLARED_MATRIX_SHA256), ("background", DECLARED_BACKGROUND_SHA256)):
        relative = Path(str(resource.get(name + "_file") or ""))
        source = root / relative
        if relative.is_absolute() or ".." in relative.parts or not source.is_file() or digest(source) != expected:
            return None
    return manifest
