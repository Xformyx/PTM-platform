"""Graph-aware pathway expansion contract tests.

구현 대상: docs/graph_aware_pathway_expansion_contract_v1.md §2–§8
사전등록: 2026-08-23. 탐색적.
해석 한계: 합성 데이터로 산식만 고정한다. pathway 재현성을 검증하지 않는다.
주장 금지: 통과를 kinase 귀속 또는 insulin pathway 개선으로 서술하지 않는다.
"""

from __future__ import annotations

from ptm_shared.pathway_expansion import (
    MIN_UNIVERSE,
    PathwayExpansionResult,
    PathwaySummary,
    classify_term,
    extract_direct_membership,
    functional_sign,
    nes_with_fdr,
    network_support_score,
    protein_capped_score,
    score_pathways,
    site_evidence_score,
    weighted_enrichment_score,
)


def test_denovo_has_no_direct_evidence_score():
    e, *_ = site_evidence_score(log2fc=29.1, is_denovo=True, detected=3, expected=3, q_value=None)
    assert e is None
    e_reg, *_ = site_evidence_score(log2fc=2.0, is_denovo=False, detected=3, expected=3, q_value=0.01)
    assert e_reg is not None
    assert abs(e_reg - 2.0) < 1e-9


def test_protein_cap_uses_signed_max_not_sum():
    assert protein_capped_score([1.0, -3.0, 2.0]) == -3.0
    assert protein_capped_score([0.4, 0.5]) == 0.5


def test_weighted_es_is_higher_when_hits_are_at_the_top():
    ranked = [f"G{i}" for i in range(20)]
    scores = {g: float(20 - i) for i, g in enumerate(ranked)}
    top_hits = set(ranked[:4])
    bottom_hits = set(ranked[-4:])
    assert weighted_enrichment_score(ranked, scores, top_hits) > weighted_enrichment_score(
        ranked, scores, bottom_hits
    )


def test_nes_does_not_rank_a_large_empty_pathway_above_a_coherent_small_one():
    scores = {f"G{i:02d}": (5.0 - i * 0.1 if i < 8 else 0.2) for i in range(20)}
    membership = {
        "small_top": {f"G{i:02d}" for i in range(4)},
        "large_bottom": {f"G{i:02d}" for i in range(8, 20)},
    }
    result = nes_with_fdr(scores, membership, timepoint_index=0)
    assert result["small_top"]["nes"] is not None
    assert result["large_bottom"]["nes"] is not None
    assert result["small_top"]["nes"] > result["large_bottom"]["nes"]


def test_string_support_is_not_a_direct_hit_and_is_degree_normalized():
    direct = {"IRS1"}
    protein_e = {"IRS1": 2.0}
    edges = [
        ("IRS1", "HUB1", 0.9),
        ("HUB1", "A", 0.9),
        ("HUB1", "B", 0.9),
        ("HUB1", "C", 0.9),
        ("IRS1", "LEAF1", 0.9),
    ]
    support = network_support_score(direct, protein_e, edges)
    assert support != 0.0
    # Hub neighbor is down-weighted versus the leaf.
    hub_only = network_support_score(direct, protein_e, [("IRS1", "HUB1", 0.9), ("HUB1", "A", 0.9), ("HUB1", "B", 0.9)])
    leaf_only = network_support_score(direct, protein_e, [("IRS1", "LEAF1", 0.9)])
    assert abs(leaf_only) > abs(hub_only)


def test_score_pathways_excludes_denovo_from_direct_universe_and_keeps_counts():
    parsed = []
    for i in range(16):
        parsed.append({
            "gene": f"REG{i}",
            "position": f"S{i+1}",
            "ptm_relative_log2fc": 2.5 if i < 6 else 0.2,
            "q_value": 0.01,
            "condition": "15min",
            "activity_class": "regulated",
        })
    parsed.append({
        "gene": "IRS1",
        "position": "S522",
        "ptm_relative_log2fc": 29.1,
        "conventional_log2fc_na": True,
        "control_pseudocount_used": True,
        "denovo_confidence": "high",
        "detection_treatment": "3/3",
        "condition": "15min",
        "activity_class": "de_novo",
    })
    enriched = []
    for i in range(16):
        pws = ["PI3K-Akt signaling"] if i < 6 else ["Cell cycle"]
        enriched.append({
            "gene": f"REG{i}",
            "rag_enrichment": {"pathways": pws},
        })
    enriched.append({
        "gene": "IRS1",
        "rag_enrichment": {"pathways": ["PI3K-Akt signaling"]},
    })
    result = score_pathways(parsed, enriched, {"edges": []}, {})
    assert result.universe_size >= MIN_UNIVERSE or result.universe_size == 16
    pi3k = next(s for s in result.summaries if "PI3K" in s.pathway)
    cell = next(s for s in result.summaries if "Cell cycle" in s.pathway)
    assert pi3k.high_confidence_denovo_count >= 1
    assert pi3k.peak_nes is not None and cell.peak_nes is not None
    assert pi3k.peak_nes > cell.peak_nes


def test_unannotated_pathway_is_modulated_not_activated():
    assert classify_term(
        n_direct=5,
        n_annotated=0,
        direction_consistency=None,
        peak_nes=2.2,
        network_support=0.4,
    ) == "modulated"
    assert classify_term(
        n_direct=0,
        n_annotated=0,
        direction_consistency=None,
        peak_nes=None,
        network_support=0.3,
    ) == "network-associated"
    assert functional_sign("GSK3A", "Ser21") == -1
    assert functional_sign("IRS1", "S522") == 0
    assert functional_sign("UNKNOWN", "S1") == 0


def test_membership_strips_species_suffix_and_excludes_string_indirect():
    membership = extract_direct_membership([
        {
            "gene": "AKT1",
            "rag_enrichment": {
                "pathways": [{"name": "PI3K-Akt signaling pathway - Mus musculus (house mouse)"}],
                "reactome": {"signaling_pathways": [{"name": "PI3K-Akt signaling pathway"}]},
                "string_indirect": {"signaling_pathways": [{"name": "Insulin signaling pathway"}]},
            },
        }
    ])
    assert "Insulin signaling pathway" not in membership
    assert "PI3K-Akt signaling pathway" in membership
    assert membership["PI3K-Akt signaling pathway"] == {"AKT1"}


def test_figure_candidates_rank_by_signed_nes_not_template():
    from report_generation.core.nodes.pathway_figure import (
        build_pathway_candidates,
        display_summaries,
        is_disease_pathway,
    )

    assert is_disease_pathway("Epstein-Barr virus infection")
    assert not is_disease_pathway("MAPK signaling pathway")

    result = PathwayExpansionResult(
        universe_size=20,
        timepoints=["15min"],
        n_perm=500,
        seed=20260823,
        summaries=[
            PathwaySummary(
                pathway="Epstein-Barr virus infection",
                peak_timepoint="15min",
                peak_nes=3.0,
                peak_q=0.01,
                n_direct=4,
                protein_support_peak=0.2,
                network_support_peak=0.1,
                denovo_support_count=0,
                high_confidence_denovo_count=0,
                coherence=None,
                term="modulated",
            ),
            PathwaySummary(
                pathway="MAPK signaling pathway",
                peak_timepoint="15min",
                peak_nes=1.4,
                peak_q=0.04,
                n_direct=5,
                protein_support_peak=0.3,
                network_support_peak=0.2,
                denovo_support_count=0,
                high_confidence_denovo_count=0,
                coherence=0.5,
                term="modulated",
                direct_genes=["MAPK1"],
            ),
            PathwaySummary(
                pathway="Cell cycle",
                peak_timepoint="15min",
                peak_nes=-1.6,
                peak_q=0.05,
                n_direct=8,
                protein_support_peak=0.1,
                network_support_peak=0.4,
                denovo_support_count=0,
                high_confidence_denovo_count=0,
                coherence=None,
                term="modulated",
                direct_genes=["CDK1"],
            ),
        ],
    )
    shown = display_summaries(result)
    assert [s.pathway for s in shown] == ["MAPK signaling pathway", "Cell cycle"]
    candidates = build_pathway_candidates([], [], {"nodes": [], "edges": []}, "/tmp", expansion=result)
    names = [c["name"] for c in candidates["candidates"]]
    assert names[0] == "MAPK signaling pathway"
    assert candidates["candidates"][0]["composite_score"] == 1.4
    assert "Epstein-Barr virus infection" not in names
