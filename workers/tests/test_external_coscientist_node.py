"""Regression coverage for isolated external Co-Scientist packet consumption."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from report_generation.core.nodes import external_coscientist_node as node  # noqa: E402


def _ready_packet() -> dict:
    return {
        "schema_version": "1.0",
        "packet_type": "discussion_evidence_packet",
        "session_id": "session-1",
        "generated_at": "2026-08-01T00:00:00+00:00",
        "source_orders": ["ORDER_001"],
        "research_goal": "Test a temporal SRC mechanism",
        "ptm_type": "phosphorylation",
        "rag_collections": ["microglia"],
        "status": "ready",
        "selected_hypotheses": [
            {
                "id": "CS-H1",
                "priority_tier": "high",
                "claim": "IF SRC-Y416 rises early, THEN SRC signaling may contribute to the acute response BECAUSE kinase activation is time-aligned.",
                "category": "temporal",
                "supporting_ptm_sites": ["SRC-Y416"],
                "data_support": [{"site": "SRC-Y416", "condition": "1h", "log2fc": 1.2}],
                "literature_evidence": [{"title": "SRC signaling in microglia", "pmid": "123456"}],
                "counter_evidence": [{"title": "Context-dependent SRC activity", "doi": "10.1000/test"}],
                "limitations": ["The site alone does not establish pathway causality."],
                "testable_prediction": "SRC inhibition should reduce the 1h module response.",
                "quality_gate": {"passed": True},
            }
        ],
        "experiment_priorities": [],
    }


class ExternalCoScientistNodeTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "co_scientist_integration": {"enabled": True, "mode": "addendum", "session_id": "session-1"},
            "parsed_ptms": [{"gene": "SRC", "position": "Y416"}],
            "vector_plot_raw_data": [],
            "chromadb_collections": [],
            "output_dir": "",
        }

    def test_disabled_feature_never_calls_remote_service(self):
        with patch.dict(os.environ, {"COSCIENTIST_ENABLED": "false"}), patch.object(node, "_get_json") as get_json:
            result = node.run_external_coscientist_context(self.state)
        self.assertEqual(result["co_scientist_status"], "disabled")
        get_json.assert_not_called()

    def test_ready_packet_requires_quality_gate_ptm_and_resolved_literature(self):
        packet = _ready_packet()
        with patch.dict(os.environ, {"COSCIENTIST_ENABLED": "true"}), \
             patch.object(node, "_get_json", side_effect=[{"status": "completed"}, packet]), \
             patch.object(node, "_resolve_supporting_literature", return_value=[{"title": "SRC signaling in microglia", "pmid": "123456"}]):
            result = node.run_external_coscientist_context(self.state)
        self.assertEqual(result["co_scientist_status"], "ready")
        self.assertEqual(len(result["co_scientist_discussion_packet"]["selected_hypotheses"]), 1)

    def test_unsupported_schema_fails_closed_without_raising(self):
        packet = _ready_packet()
        packet["schema_version"] = "2.0"
        with patch.dict(os.environ, {"COSCIENTIST_ENABLED": "true"}), \
             patch.object(node, "_get_json", side_effect=[{"status": "completed"}, packet]):
            result = node.run_external_coscientist_context(self.state)
        self.assertEqual(result["co_scientist_status"], "failed")
        self.assertIn("Unsupported packet schema", result["co_scientist_warning"])


if __name__ == "__main__":
    unittest.main()
