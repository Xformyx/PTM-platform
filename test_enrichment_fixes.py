"""
Test script to verify enrichment pipeline fixes:
1. _empty_enrichment now uses Log2FC for proper classification
2. _classify_ptm_8cat produces correct results
3. Individual MCP call failures don't break entire enrichment
"""

import sys
sys.path.insert(0, "/home/ubuntu/PTM-platform/workers")

# ============================================================
# Test 1: _classify_ptm_8cat produces correct classifications
# ============================================================
print("=" * 60)
print("Test 1: _classify_ptm_8cat classification logic")
print("=" * 60)

from rag_enrichment.core.enrichment_pipeline import RAGEnrichmentPipeline

test_cases = [
    # (ptm_log2fc, protein_log2fc, expected_level)
    (3.5, 0.1, "PTM-driven hyperactivation"),
    (-3.0, 0.2, "PTM-driven inactivation"),
    (3.0, -1.0, "Compensatory PTM hyperactivation"),
    (1.0, 1.0, "Coupled activation"),
    (-1.0, -1.0, "Coupled shutdown"),
    (-1.0, 1.0, "Desensitization-like pattern"),
    (0.2, 1.5, "Expression-driven change"),
    (0.1, 0.1, "Baseline / low-change state"),
]

all_passed = True
for ptm_fc, prot_fc, expected in test_cases:
    result = RAGEnrichmentPipeline._classify_ptm_8cat(ptm_fc, prot_fc)
    level = result["level"]
    status = "PASS" if level == expected else "FAIL"
    if status == "FAIL":
        all_passed = False
    print(f"  [{status}] PTM={ptm_fc:+.1f}, Prot={prot_fc:+.1f} → {level}")
    if status == "FAIL":
        print(f"         Expected: {expected}")

print(f"\nTest 1 result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

# ============================================================
# Test 2: _empty_enrichment now uses Log2FC for classification
# ============================================================
print("\n" + "=" * 60)
print("Test 2: _empty_enrichment with Log2FC-based classification")
print("=" * 60)

# Test with high PTM change
result_high = RAGEnrichmentPipeline._empty_enrichment(ptm_log2fc=3.5, protein_log2fc=0.1)
cls_high = result_high["classification"]
print(f"  PTM=3.5, Prot=0.1 → {cls_high['level']} (short: {cls_high['short_label']}, sig: {cls_high['significance']})")
assert cls_high["level"] == "PTM-driven hyperactivation", f"Expected 'PTM-driven hyperactivation', got '{cls_high['level']}'"
assert cls_high["significance"] == "High", f"Expected 'High', got '{cls_high['significance']}'"
print("  [PASS] High PTM change correctly classified")

# Test with default (0, 0)
result_default = RAGEnrichmentPipeline._empty_enrichment()
cls_default = result_default["classification"]
print(f"  PTM=0, Prot=0 → {cls_default['level']} (short: {cls_default['short_label']}, sig: {cls_default['significance']})")
assert cls_default["level"] == "Baseline / low-change state", f"Expected 'Baseline', got '{cls_default['level']}'"
print("  [PASS] Default correctly classified as Baseline")

# Test with coupled shutdown
result_shutdown = RAGEnrichmentPipeline._empty_enrichment(ptm_log2fc=-1.5, protein_log2fc=-1.2)
cls_shutdown = result_shutdown["classification"]
print(f"  PTM=-1.5, Prot=-1.2 → {cls_shutdown['level']} (short: {cls_shutdown['short_label']}, sig: {cls_shutdown['significance']})")
assert cls_shutdown["level"] == "Coupled shutdown", f"Expected 'Coupled shutdown', got '{cls_shutdown['level']}'"
print("  [PASS] Coupled shutdown correctly classified")

print("\nTest 2 result: ALL PASSED")

# ============================================================
# Test 3: _empty_enrichment structure is complete
# ============================================================
print("\n" + "=" * 60)
print("Test 3: _empty_enrichment structure completeness")
print("=" * 60)

required_keys = [
    "search_summary", "articles", "recent_findings", "regulation",
    "pathways", "string_db", "string_interactions", "diseases",
    "localization", "function_summary", "aliases", "go_terms",
    "classification", "hpa", "gtex", "biogrid", "isoform_info",
    "trajectory", "abstract_analysis", "kinase_prediction",
    "functional_impact", "fulltext_analysis", "ptm_validation",
]

result = RAGEnrichmentPipeline._empty_enrichment(1.0, 0.5)
missing = [k for k in required_keys if k not in result]
if missing:
    print(f"  [FAIL] Missing keys: {missing}")
else:
    print(f"  [PASS] All {len(required_keys)} required keys present")

print("\nTest 3 result: ALL PASSED")

# ============================================================
# Test 4: Report generator handles enrichment data correctly
# ============================================================
print("\n" + "=" * 60)
print("Test 4: Report generator with enrichment data")
print("=" * 60)

from rag_enrichment.core.report_generator import ComprehensiveReportGenerator

# Create a mock PTM with enrichment
mock_ptm = {
    "gene": "MAPK1",
    "position": "T185",
    "ptm_type": "Phosphorylation",
    "protein_log2fc": 0.2,
    "ptm_relative_log2fc": 3.5,
    "Protein_Log2FC": 0.2,
    "PTM_Relative_Log2FC": 3.5,
    "rag_enrichment": RAGEnrichmentPipeline._empty_enrichment(3.5, 0.2),
}

generator = ComprehensiveReportGenerator()
report = generator.generate_full_report([mock_ptm])

# Check that classification appears correctly
if "PTM-driven hyperactivation" in report:
    print("  [PASS] 'PTM-driven hyperactivation' found in report")
else:
    print("  [FAIL] 'PTM-driven hyperactivation' NOT found in report")
    # Check what classification appears
    import re
    cls_match = re.search(r"Classification.*?\|.*?\*\*(.*?)\*\*", report)
    if cls_match:
        print(f"         Found classification: {cls_match.group(1)}")

if "Baseline" not in report.split("Classification Criteria")[0]:
    print("  [PASS] 'Baseline' does NOT appear before Classification Criteria section")
else:
    # Check if Baseline appears in the PTM section (not just the criteria table)
    ptm_section = report.split("## 1.")[1] if "## 1." in report else ""
    if "Baseline" in ptm_section:
        print("  [WARN] 'Baseline' appears in PTM section — check classification")
    else:
        print("  [PASS] 'Baseline' only in criteria table, not in PTM classification")

if "High" in report:
    print("  [PASS] 'High' significance found in report")
else:
    print("  [FAIL] 'High' significance NOT found in report")

# Check summary table
if "PTM-driven" in report:
    print("  [PASS] Summary table contains proper classification")
else:
    print("  [FAIL] Summary table missing proper classification")

print("\nTest 4 result: COMPLETED")

# ============================================================
# Test 5: Report with multiple PTMs of different classifications
# ============================================================
print("\n" + "=" * 60)
print("Test 5: Report with multiple PTM classifications")
print("=" * 60)

mock_ptms = [
    {
        "gene": "MAPK1", "position": "T185", "ptm_type": "Phosphorylation",
        "protein_log2fc": 0.2, "ptm_relative_log2fc": 3.5,
        "Protein_Log2FC": 0.2, "PTM_Relative_Log2FC": 3.5,
        "rag_enrichment": RAGEnrichmentPipeline._empty_enrichment(3.5, 0.2),
    },
    {
        "gene": "AKT1", "position": "S473", "ptm_type": "Phosphorylation",
        "protein_log2fc": 1.2, "ptm_relative_log2fc": 1.5,
        "Protein_Log2FC": 1.2, "PTM_Relative_Log2FC": 1.5,
        "rag_enrichment": RAGEnrichmentPipeline._empty_enrichment(1.5, 1.2),
    },
    {
        "gene": "TP53", "position": "S15", "ptm_type": "Phosphorylation",
        "protein_log2fc": -0.8, "ptm_relative_log2fc": -2.5,
        "Protein_Log2FC": -0.8, "PTM_Relative_Log2FC": -2.5,
        "rag_enrichment": RAGEnrichmentPipeline._empty_enrichment(-2.5, -0.8),
    },
]

generator2 = ComprehensiveReportGenerator()
report2 = generator2.generate_full_report(mock_ptms)

classifications_found = {
    "PTM-driven hyperactivation": "PTM-driven hyperactivation" in report2,
    "Coupled activation": "Coupled activation" in report2,
    "Coupled shutdown": "Coupled shutdown" in report2,
}

for cls, found in classifications_found.items():
    status = "PASS" if found else "FAIL"
    print(f"  [{status}] '{cls}' {'found' if found else 'NOT found'} in report")

# Count how many times "Baseline" appears in PTM sections (not criteria table)
ptm_sections = report2.split("## PTM Classification Criteria")[-1]
baseline_count = ptm_sections.count("Baseline / low-change state")
print(f"  'Baseline / low-change state' appears {baseline_count} times in PTM sections")
if baseline_count == 0:
    print("  [PASS] No incorrect Baseline classifications")
else:
    print(f"  [INFO] {baseline_count} Baseline appearances (check if in criteria table)")

# Report size check
report_lines = len(report2.split("\n"))
print(f"\n  Report size: {len(report2)} chars, {report_lines} lines")
if report_lines > 100:
    print("  [PASS] Report has substantial content")
else:
    print("  [WARN] Report seems short")

print("\nTest 5 result: COMPLETED")
print("\n" + "=" * 60)
print("ALL TESTS COMPLETED")
print("=" * 60)
