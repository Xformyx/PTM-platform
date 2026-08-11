"""Contract checks between PTM-platform consumer and PTM-CoScientist packet schema."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


PLATFORM_ROOT = Path(__file__).resolve().parents[2]
COSCIENTIST_PACKET = (
    PLATFORM_ROOT.parent / "PTM-CoScientist" / "src" / "core" / "discussion_packet.py"
)


def _read_schema_version(path: Path) -> str | None:
    if not path.exists():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SCHEMA_VERSION":
                    if isinstance(node.value, ast.Constant):
                        return str(node.value.value)
    return None


class DiscussionPacketContractTests(unittest.TestCase):
    def test_platform_supports_schema_1_0(self):
        sys.path.insert(0, str(PLATFORM_ROOT / "workers"))
        from report_generation.core.nodes import external_coscientist_node as node

        self.assertEqual(node._SUPPORTED_SCHEMA, "1.0")
        self.assertEqual(node._PACKET_TYPE, "discussion_evidence_packet")

    def test_local_coscientist_schema_matches_when_repo_present(self):
        version = _read_schema_version(COSCIENTIST_PACKET)
        if version is None:
            self.skipTest(f"PTM-CoScientist packet module not found at {COSCIENTIST_PACKET}")
        self.assertEqual(version, "1.0")


if __name__ == "__main__":
    unittest.main()
