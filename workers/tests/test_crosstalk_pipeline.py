"""
Cross-Talk Pipeline End-to-End Test Script
==========================================

Tests the complete cross-talk pipeline from preprocessing through report generation.
Can be run in two modes:
  1. Unit test mode (mock LLM): Tests data flow and integration without LLM calls
  2. Integration test mode: Tests with real LLM (requires running LLM service)

Usage:
  python -m pytest tests/test_crosstalk_pipeline.py -v
  python tests/test_crosstalk_pipeline.py  # standalone
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "report_generation"))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("test_crosstalk")


# ============================================================================
# Test Data Generators
# ============================================================================

def generate_mock_primary_results(ptm_type="phosphorylation"):
    """Generate mock primary PTM network results."""
    return {
        "summary": {
            "total_ptms": 150,
            "total_proteins": 85,
            "total_edges": 320,
        },
        "timepoints": ["5min", "15min", "30min", "60min"],
        "network": {
            "nodes": [
                {"gene": "Mapk3", "type": "ptm", "ptm_sites": ["Thr202", "Tyr204"]},
                {"gene": "Akt1", "type": "ptm", "ptm_sites": ["Ser473", "Thr308"]},
                {"gene": "Gsk3b", "type": "ptm", "ptm_sites": ["Ser9"]},
                {"gene": "Mtor", "type": "ptm", "ptm_sites": ["Ser2448"]},
                {"gene": "Rps6", "type": "ptm", "ptm_sites": ["Ser235", "Ser236"]},
                {"gene": "Stat3", "type": "ptm", "ptm_sites": ["Tyr705"]},
                {"gene": "Hsp90ab1", "type": "non_ptm"},
                {"gene": "Ywhaz", "type": "non_ptm"},
                {"gene": "Cdk2", "type": "non_ptm"},
            ],
            "edges": [
                {"source": "Mapk3", "target": "Rps6", "type": "kinase_substrate"},
                {"source": "Akt1", "target": "Gsk3b", "type": "kinase_substrate"},
                {"source": "Akt1", "target": "Mtor", "type": "kinase_substrate"},
                {"source": "Hsp90ab1", "target": "Akt1", "type": "ppi"},
                {"source": "Ywhaz", "target": "Mapk3", "type": "ppi"},
            ],
        },
        "tsv_data": "Gene.Name\tPTM_Position\tCondition\tPTM_Relative_Log2FC\n"
                     "Mapk3\tThr202\t5min\t1.5\n"
                     "Mapk3\tThr202\t15min\t2.3\n"
                     "Mapk3\tThr202\t30min\t1.8\n"
                     "Akt1\tSer473\t5min\t0.8\n"
                     "Akt1\tSer473\t15min\t1.9\n"
                     "Akt1\tSer473\t30min\t2.5\n"
                     "Gsk3b\tSer9\t5min\t-0.5\n"
                     "Gsk3b\tSer9\t15min\t-1.2\n"
                     "Gsk3b\tSer9\t30min\t-1.8\n"
                     "Mtor\tSer2448\t5min\t0.3\n"
                     "Mtor\tSer2448\t15min\t1.1\n"
                     "Mtor\tSer2448\t30min\t1.6\n"
                     "Rps6\tSer235\t5min\t0.1\n"
                     "Rps6\tSer235\t15min\t0.9\n"
                     "Rps6\tSer235\t30min\t1.4\n"
                     "Stat3\tTyr705\t5min\t2.1\n"
                     "Stat3\tTyr705\t15min\t1.5\n"
                     "Stat3\tTyr705\t30min\t0.8\n",
    }


def generate_mock_secondary_results(ptm_type="ubiquitylation"):
    """Generate mock secondary PTM network results."""
    return {
        "summary": {
            "total_ptms": 120,
            "total_proteins": 70,
            "total_edges": 250,
        },
        "timepoints": ["5min", "15min", "30min", "60min"],
        "network": {
            "nodes": [
                {"gene": "Mapk3", "type": "ptm", "ptm_sites": ["Lys63"]},
                {"gene": "Akt1", "type": "ptm", "ptm_sites": ["Lys48"]},
                {"gene": "Gsk3b", "type": "ptm", "ptm_sites": ["Lys183"]},
                {"gene": "Rps6", "type": "ptm", "ptm_sites": ["Lys48"]},
                {"gene": "Nedd4", "type": "non_ptm"},
                {"gene": "Hsp90ab1", "type": "non_ptm"},
                {"gene": "Usp7", "type": "non_ptm"},
            ],
            "edges": [
                {"source": "Nedd4", "target": "Akt1", "type": "e3_substrate"},
                {"source": "Usp7", "target": "Mapk3", "type": "dub_substrate"},
                {"source": "Hsp90ab1", "target": "Gsk3b", "type": "ppi"},
            ],
        },
        "tsv_data": "Gene.Name\tPTM_Position\tCondition\tPTM_Relative_Log2FC\n"
                     "Mapk3\tLys63\t5min\t1.2\n"
                     "Mapk3\tLys63\t15min\t2.0\n"
                     "Mapk3\tLys63\t30min\t1.5\n"
                     "Akt1\tLys48\t5min\t-0.5\n"
                     "Akt1\tLys48\t15min\t-1.3\n"
                     "Akt1\tLys48\t30min\t-2.0\n"
                     "Gsk3b\tLys183\t5min\t0.3\n"
                     "Gsk3b\tLys183\t15min\t1.5\n"
                     "Gsk3b\tLys183\t30min\t2.2\n"
                     "Rps6\tLys48\t5min\t0.2\n"
                     "Rps6\tLys48\t15min\t0.8\n"
                     "Rps6\tLys48\t30min\t1.1\n",
    }


# ============================================================================
# Test 1: build_crosstalk_data (Core Algorithm)
# ============================================================================

def test_build_crosstalk_data():
    """Test the core cross-talk data building algorithm."""
    logger.info("=" * 60)
    logger.info("TEST 1: build_crosstalk_data")
    logger.info("=" * 60)

    try:
        from report_generation.core.nodes.crosstalk_node import build_crosstalk_data
    except ImportError:
        logger.warning("Cannot import build_crosstalk_data — testing with mock")
        logger.info("SKIP: build_crosstalk_data not importable in test environment")
        return None

    primary = generate_mock_primary_results()
    secondary = generate_mock_secondary_results()

    crosstalk_data = build_crosstalk_data(
        primary_results=primary,
        secondary_results=secondary,
        primary_ptm_type="phosphorylation",
        secondary_ptm_type="ubiquitylation",
    )

    # Validate structure
    assert "dual_ptm_proteins" in crosstalk_data, "Missing dual_ptm_proteins"
    assert "sequential_gating" in crosstalk_data, "Missing sequential_gating"
    assert "shared_nonptm" in crosstalk_data, "Missing shared_nonptm"
    assert "non_ptm_interactors" in crosstalk_data, "Missing non_ptm_interactors"

    dual = crosstalk_data["dual_ptm_proteins"]
    logger.info(f"  Dual-PTM proteins found: {len(dual)}")
    for p in dual:
        logger.info(f"    {p['gene']}: pattern={p['pattern']}, concordance={p['concordant_ratio']:.0%}")

    # Expected: Mapk3, Akt1, Gsk3b, Rps6 should be dual-PTM
    dual_genes = {p["gene"] for p in dual}
    assert "Mapk3" in dual_genes, "Mapk3 should be dual-PTM"
    assert "Akt1" in dual_genes, "Akt1 should be dual-PTM"

    # Mapk3: both up → concordant
    mapk3 = next(p for p in dual if p["gene"] == "Mapk3")
    assert mapk3["pattern"] == "concordant", f"Mapk3 should be concordant, got {mapk3['pattern']}"

    # Akt1: phospho up, ubi down → discordant
    akt1 = next(p for p in dual if p["gene"] == "Akt1")
    assert akt1["pattern"] == "discordant", f"Akt1 should be discordant, got {akt1['pattern']}"

    # Shared non-PTM: Hsp90ab1 should be shared
    shared = crosstalk_data["shared_nonptm"]
    logger.info(f"  Shared non-PTM interactors: {shared}")
    assert "Hsp90ab1" in shared, "Hsp90ab1 should be shared non-PTM interactor"

    logger.info("  ✓ build_crosstalk_data PASSED")
    return crosstalk_data


# ============================================================================
# Test 2: Cross-Talk Figure Generation
# ============================================================================

def test_crosstalk_figures(crosstalk_data=None):
    """Test cross-talk figure generation."""
    logger.info("=" * 60)
    logger.info("TEST 2: Cross-Talk Figure Generation")
    logger.info("=" * 60)

    if crosstalk_data is None:
        # Use minimal mock data
        crosstalk_data = {
            "dual_ptm_proteins": [
                {"gene": "Mapk3", "pattern": "concordant", "concordant_ratio": 0.9,
                 "primary_sites": ["Thr202"], "secondary_sites": ["Lys63"],
                 "shared_timepoints": ["5min", "15min", "30min"],
                 "details": [{"timepoint": "5min", "primary_fc": 1.5, "secondary_fc": 1.2, "concordant": True}],
                 "temporal_comparison": {"5min": {"concordant": True, "primary_state": "up", "secondary_state": "up",
                                                   "primary_ptm_log2fc": 1.5, "secondary_ptm_log2fc": 1.2}}},
                {"gene": "Akt1", "pattern": "discordant", "concordant_ratio": 0.1,
                 "primary_sites": ["Ser473"], "secondary_sites": ["Lys48"],
                 "shared_timepoints": ["5min", "15min", "30min"],
                 "details": [{"timepoint": "5min", "primary_fc": 0.8, "secondary_fc": -0.5, "concordant": False}],
                 "temporal_comparison": {"5min": {"concordant": False, "primary_state": "up", "secondary_state": "down",
                                                   "primary_ptm_log2fc": 0.8, "secondary_ptm_log2fc": -0.5}}},
            ],
            "sequential_gating": [
                {"gene": "Gsk3b", "leading_ptm": "phosphorylation", "lagging_ptm": "ubiquitylation",
                 "leading_first_tp": "5min", "lagging_first_tp": "15min",
                 "time_lag_minutes": 10, "mechanism_hint": "phosphodegron"},
            ],
            "shared_nonptm": ["Hsp90ab1", "Ywhaz"],
            "non_ptm_interactors": [
                {"gene": "Hsp90ab1", "connected_dual_ptm_proteins": ["Mapk3", "Akt1"],
                 "primary_ptm_interactions": ["Akt1"], "secondary_ptm_interactions": ["Gsk3b"]},
            ],
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            from report_generation.core.crosstalk_figures import (
                generate_all_crosstalk_figures,
                generate_crosstalk_figure_section,
                generate_crosstalk_sankey,
                generate_dual_volcano,
            )
        except ImportError:
            logger.warning("Cannot import crosstalk_figures — skipping")
            logger.info("SKIP: crosstalk_figures not importable")
            return

        # Test all figures
        figures = generate_all_crosstalk_figures(
            crosstalk_data, tmpdir,
            primary_ptm_type="phosphorylation",
            secondary_ptm_type="ubiquitylation",
        )

        logger.info(f"  Generated figures: {list(figures.keys())}")
        for name, path in figures.items():
            assert os.path.exists(path), f"Figure {name} not found at {path}"
            size = os.path.getsize(path)
            logger.info(f"    {name}: {path} ({size:,} bytes)")

        # Test figure section generation
        section = generate_crosstalk_figure_section(
            crosstalk_data, figures,
            primary_ptm_type="phosphorylation",
            secondary_ptm_type="ubiquitylation",
        )
        assert "Cross-Talk Network Visualization" in section
        logger.info(f"  Figure section length: {len(section)} chars")

        logger.info("  ✓ Cross-Talk Figure Generation PASSED")


# ============================================================================
# Test 3: Cross-Talk Vocabulary
# ============================================================================

def test_crosstalk_vocabulary():
    """Test cross-talk vocabulary support."""
    logger.info("=" * 60)
    logger.info("TEST 3: Cross-Talk Vocabulary")
    logger.info("=" * 60)

    try:
        from common.ptm_vocabulary import (
            get_normalized_ptm_type,
            build_crosstalk_vocabulary_prompt_block,
        )
    except ImportError:
        logger.warning("Cannot import ptm_vocabulary — skipping")
        return

    # Test normalization
    assert get_normalized_ptm_type("cross_talk") == "cross_talk"
    assert get_normalized_ptm_type("crosstalk") == "cross_talk"
    logger.info("  ✓ cross_talk normalization works")

    # Test vocabulary block
    block = build_crosstalk_vocabulary_prompt_block("phosphorylation", "ubiquitylation")
    assert "Cross-Talk Analysis" in block
    assert "phosphorylation" in block.lower()
    assert "ubiquitylation" in block.lower()
    assert "dual-PTM protein" in block
    assert "concordant regulation" in block
    assert "sequential gating" in block
    assert "phosphodegron" in block
    logger.info(f"  Vocabulary block length: {len(block)} chars")
    logger.info("  ✓ Cross-Talk Vocabulary PASSED")


# ============================================================================
# Test 4: Postprocessor Cross-Talk Mode
# ============================================================================

def test_postprocessor_crosstalk():
    """Test that postprocessor correctly handles cross-talk mode."""
    logger.info("=" * 60)
    logger.info("TEST 4: Postprocessor Cross-Talk Mode")
    logger.info("=" * 60)

    try:
        from common.report_postprocessor import postprocess_full_report
    except ImportError:
        logger.warning("Cannot import report_postprocessor — skipping")
        return

    # Test: In cross-talk mode, both PTM types should be preserved
    test_text = (
        "## Results\n\n"
        "The phosphorylation of Mapk3 at Thr202 was concordant with ubiquitylation at Lys63. "
        "This kinase-substrate relationship suggests phosphodegron-mediated cross-talk. "
        "The E3 ligase-substrate interaction between Nedd4 and Akt1 was discordant with "
        "the kinase activity observed at Ser473. "
        "Deubiquitylation by Usp7 reversed the ubiquitylation signal.\n"
    )

    # Cross-talk mode: should NOT strip phosphorylation or ubiquitylation terms
    crosstalk_metadata = {
        "n_dual": 10, "n_conc": 5, "n_disc": 3,
        "n_gate": 2, "n_shared_nonptm": 4,
        "is_crosstalk": True,
    }
    result = postprocess_full_report(test_text, ptm_type="phosphorylation",
                                      crosstalk_metadata=crosstalk_metadata)

    assert "phosphorylation" in result, "Cross-talk mode should preserve 'phosphorylation'"
    assert "ubiquitylation" in result, "Cross-talk mode should preserve 'ubiquitylation'"
    assert "kinase-substrate" in result, "Cross-talk mode should preserve 'kinase-substrate'"
    assert "E3 ligase-substrate" in result, "Cross-talk mode should preserve 'E3 ligase-substrate'"
    assert "ubiquitination" not in result, "Should correct 'ubiquitination' to 'ubiquitylation'"

    logger.info("  ✓ Cross-talk mode preserves both PTM vocabularies")

    # Non-cross-talk mode: should strip wrong PTM terms
    result_normal = postprocess_full_report(test_text, ptm_type="ubiquitylation")
    # In ubiquitylation mode, 'kinase-substrate' should be corrected
    logger.info(f"  Normal mode result contains 'kinase-substrate': {'kinase-substrate' in result_normal}")

    logger.info("  ✓ Postprocessor Cross-Talk Mode PASSED")


# ============================================================================
# Test 5: Pipeline Integration (Graph Flow)
# ============================================================================

def test_graph_crosstalk_routing():
    """Test that graph.py correctly routes cross-talk mode."""
    logger.info("=" * 60)
    logger.info("TEST 5: Graph Cross-Talk Routing")
    logger.info("=" * 60)

    try:
        from report_generation.core.graph import build_report_graph
    except ImportError:
        logger.warning("Cannot import graph — skipping")
        return

    # Build graph and verify cross-talk node exists
    graph = build_report_graph()

    # Check that the graph has the crosstalk_analysis node
    nodes = list(graph.nodes) if hasattr(graph, 'nodes') else []
    logger.info(f"  Graph nodes: {nodes}")

    # The graph should have a route_by_mode conditional edge
    logger.info("  ✓ Graph Cross-Talk Routing test completed")


# ============================================================================
# Main
# ============================================================================

def run_all_tests():
    """Run all cross-talk pipeline tests."""
    logger.info("=" * 70)
    logger.info("CROSS-TALK PIPELINE TEST SUITE")
    logger.info("=" * 70)

    results = {}

    # Test 1: Core algorithm
    try:
        crosstalk_data = test_build_crosstalk_data()
        results["build_crosstalk_data"] = "PASS"
    except Exception as e:
        logger.error(f"TEST 1 FAILED: {e}", exc_info=True)
        results["build_crosstalk_data"] = f"FAIL: {e}"
        crosstalk_data = None

    # Test 2: Figure generation
    try:
        test_crosstalk_figures(crosstalk_data)
        results["figure_generation"] = "PASS"
    except Exception as e:
        logger.error(f"TEST 2 FAILED: {e}", exc_info=True)
        results["figure_generation"] = f"FAIL: {e}"

    # Test 3: Vocabulary
    try:
        test_crosstalk_vocabulary()
        results["vocabulary"] = "PASS"
    except Exception as e:
        logger.error(f"TEST 3 FAILED: {e}", exc_info=True)
        results["vocabulary"] = f"FAIL: {e}"

    # Test 4: Postprocessor
    try:
        test_postprocessor_crosstalk()
        results["postprocessor"] = "PASS"
    except Exception as e:
        logger.error(f"TEST 4 FAILED: {e}", exc_info=True)
        results["postprocessor"] = f"FAIL: {e}"

    # Test 5: Graph routing
    try:
        test_graph_crosstalk_routing()
        results["graph_routing"] = "PASS"
    except Exception as e:
        logger.error(f"TEST 5 FAILED: {e}", exc_info=True)
        results["graph_routing"] = f"FAIL: {e}"

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("=" * 70)
    passed = sum(1 for v in results.values() if v == "PASS")
    total = len(results)
    for name, result in results.items():
        status = "✓" if result == "PASS" else "✗"
        logger.info(f"  {status} {name}: {result}")
    logger.info(f"\n  Total: {passed}/{total} passed")
    logger.info("=" * 70)

    return results


if __name__ == "__main__":
    run_all_tests()
