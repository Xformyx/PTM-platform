"""Rejected comparisons keep the v6 gate and gain a failure class."""
import pandas as pd
from ptm_shared.astra_evidence_v6 import report_addendum
from ptm_shared.finding_literature import quote_binding_failure


DOCUMENT = "CANDIDATE0 S7 increased in mouse cells after insulin at 5min."
IDENTITY = {"gene": "CANDIDATE0", "candidate_residue_annotation": "S7"}


def _candidate(**overrides):
    row = {
        "quote": DOCUMENT,
        "reference_scope": "site",
        "relationship": "known_agreement",
        "external_finding": "S7 increased",
        "species": "mouse",
        "cell_type": "mouse cells",
        "time": "5min",
        "insulin_dose": "",
        "readout": "",
        "perturbation": "insulin",
    }
    row.update(overrides)
    return row


def test_quote_missing_from_chunk_is_citation_mismatch():
    reason, klass = quote_binding_failure(_candidate(quote="invented finding"), {"document": DOCUMENT, "doi": "10.1000/fixture"}, IDENTITY)
    assert reason == "quote_not_in_retrieved_chunk"
    assert klass == "citation_mismatch"


def test_scope_and_condition_failures_are_distinct_and_still_rejected():
    hit = {"document": DOCUMENT, "doi": "10.1000/fixture"}
    reason, klass = quote_binding_failure(_candidate(quote="increased in mouse cells", reference_scope="gene"), hit, IDENTITY)
    assert reason == "scope_identifier_absent_from_quote"
    assert klass == "scope"
    reason, klass = quote_binding_failure(_candidate(species="rat"), hit, IDENTITY)
    assert reason == "condition_context_not_in_quote"
    assert klass == "condition_comparison"


def test_passing_quote_is_not_named_as_a_new_approval():
    reason, klass = quote_binding_failure(_candidate(), {"document": DOCUMENT, "doi": "10.1000/fixture"}, IDENTITY)
    assert (reason, klass) == ("unbound_quote_context_or_scope", "unclassified")


def test_zscore_rows_without_executions_are_not_described_as_phosx():
    comparisons = pd.DataFrame([{
        "included": True, "A": 1.0, "form_id": "form", "contrast_id": "contrast",
        "U_joint": 1.0, "P_joint": 0.5,
    }])
    scores = pd.DataFrame([{"method_id": "repository_measured_gene_zscore"}] * 41)
    text = report_addendum(
        {"quant/comparisons": comparisons, "kinase/method_scores": scores, "kinase/method_executions": pd.DataFrame()},
        {"specificity": {}},
    )
    assert "PhosX was not executed" in text
    assert "repository_measured_gene_zscore" in text
    assert "not a six-contrast PhosX result" in text
