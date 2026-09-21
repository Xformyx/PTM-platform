"""Incomplete identity must still yield a network node key.

구현 대상: report Isolated Nodes 표. Order 80 TypeError 정정.
사전등록: 해당 없음 (표시·그래프 키). 2026-09-21.
해석 한계: 키 존재는 identity complete가 아니다.
주장 금지: 이 키로 kinase 귀속을 주장하지 않는다.
"""
from report_generation.core.nodes.network_node import (
    _observation_node_id,
    _validate_network,
    generate_network_figure_section,
)


def test_observation_node_id_falls_back_when_feature_id_incomplete():
    oid = _observation_node_id({
        "gene": "IRS1",
        "position": "S307",
        "Modified.Sequence": "AS(UniMod:21)K",
    })
    assert oid == "IRS1-S307"


def test_observation_node_id_keeps_complete_feature_id():
    oid = _observation_node_id({
        "gene": "IRS1",
        "position": "S307",
        "Precursor.Id": "pr1",
        "Modified.Sequence": "AS(UniMod:21)K",
        "Precursor.Charge": 2,
    })
    assert oid.startswith("FEATURE-")


def test_validate_network_excludes_none_ids():
    result = _validate_network(
        [{"id": None, "type": "PTM"}, {"id": "AKT1-S473", "type": "PTM"}],
        [],
    )
    assert None not in result["orphan_node_ids"]
    assert result["orphan_node_ids"] == ["AKT1-S473"]


def test_isolated_nodes_table_skips_none_ids():
    _, supp = generate_network_figure_section({
        "legends": {"full_legend": "legend"},
        "validation": {
            "orphan_nodes": 2,
            "orphan_node_ids": [None, "AKT1-S473"],
        },
    })
    assert "AKT1-S473" in supp
    assert "| None |" not in supp
