import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "rag_enrichment" / "core" / "evidence_routing.py"
_SPEC = importlib.util.spec_from_file_location("evidence_routing", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

ABSTRACT_TARGETED = _MODULE.ABSTRACT_TARGETED
DB_ONLY = _MODULE.DB_ONLY
FULLTEXT_ESCALATED = _MODULE.FULLTEXT_ESCALATED
build_structured_database_packet = _MODULE.build_structured_database_packet
decide_evidence_route = _MODULE.decide_evidence_route


def _packet(*, exact_site_known: bool, pathways: int = 1):
    return build_structured_database_packet(
        gene="AKT1",
        position="S473",
        species="rat",
        iptmnet_data={
            "sites_found": 1 if exact_site_known else 0,
            "novelty": {"status": "KNOWN" if exact_site_known else "NOVEL"},
        },
        uniprot_info={"function_summary": "kinase"},
        kegg_pathways=[{"name": "Insulin signaling"}] * pathways,
        reactome_data={},
        interactions=[],
    )


def test_curated_low_priority_site_uses_db_only():
    decision = decide_evidence_route(
        ptm={},
        classification={"significance": "Low"},
        structured_packet=_packet(exact_site_known=True),
        context={"treatment": "insulin"},
    )
    assert decision["route"] == DB_ONLY
    assert decision["literature_required"] is False


def test_uncurated_high_signal_site_uses_targeted_abstracts():
    decision = decide_evidence_route(
        ptm={},
        classification={"significance": "High"},
        structured_packet=_packet(exact_site_known=False),
        context={"treatment": "insulin"},
    )
    assert decision["route"] == ABSTRACT_TARGETED
    assert "exact_site_not_curated" in decision["reason_codes"]


def test_uncurated_low_priority_site_stays_database_only_without_context():
    decision = decide_evidence_route(
        ptm={},
        classification={"significance": "Low"},
        structured_packet=_packet(exact_site_known=False),
        context={},
    )
    assert decision["route"] == DB_ONLY


def test_fulltext_requires_explicit_escalation():
    decision = decide_evidence_route(
        ptm={"requires_fulltext": True},
        classification={"significance": "High"},
        structured_packet=_packet(exact_site_known=False),
        context={},
    )
    assert decision["route"] == FULLTEXT_ESCALATED


def test_structured_packet_preserves_exact_site_provenance():
    packet = _packet(exact_site_known=True, pathways=2)
    assert packet["iptmnet"]["exact_site_known"] is True
    assert packet["pathway_context"]["kegg_pathway_count"] == 2
