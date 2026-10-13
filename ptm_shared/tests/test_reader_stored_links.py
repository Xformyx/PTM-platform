"""Stored reader links: precursor membership, recorded time, and retrieved sources."""
import json

import pandas as pd

from ptm_shared.astra_literature import retrieved_source_guidance, write
from ptm_shared.astra_reader import kinase_link_sentence, selected_kinase_contribution_summary
from ptm_shared.measured_feature_cards import build_feature_observation_cards, project_recorded_time_order


def _row(condition, adjusted):
    return {
        "gene": "PTPRK",
        "position": "Y873",
        "condition": condition,
        "Precursor.Id": "PTPRK_Y873",
        "Modified.Sequence": "AY(UniMod:21)TK",
        "Protein.Group": "P_PTPRK",
        "ptm_unadjusted_log2fc": adjusted - 0.01,
        "ptm_protein_adjusted_log2fc": adjusted,
        "ptm_relative_log2fc": adjusted,
        "protein_log2fc": -0.4,
    }


def test_condition_grid_uses_recorded_minutes_not_label_order():
    labels = [
        ("15min vs Control [contrast_15]", 15),
        ("180min vs Control [contrast_180]", 180),
        ("1min vs Control [contrast_1]", 1),
        ("30min vs Control [contrast_30]", 30),
        ("5min vs Control [contrast_5]", 5),
        ("60min vs Control [contrast_60]", 60),
    ]
    state = {
        "vector_plot_raw_data": [_row(label, 0.1) for label, _minutes in labels],
        "sample_manifest": {"conditions": [{"condition": label, "time_minutes": minutes} for label, minutes in labels]},
    }
    card = build_feature_observation_cards(state, maximum=1)[0]
    assert card["condition_grid"]["conditions"] == [label for label, _minutes in sorted(labels, key=lambda item: item[1])]
    assert [point["time_minutes"] for point in card["trajectory"]] == [1, 5, 15, 30, 60, 180]


def test_precursor_membership_is_not_a_kinase_contribution():
    findings = [
        {"finding_id": "f1", "feature_label": "TAOK1 feature", "form_id": "form_taok",
         "source_bindings": [{"membership_ids": ["card_member_1"], "contrast_id": "cA", "arm_id": "arm",
                              "reference_condition_id": "base", "pairing": "unpaired"}]},
        {"finding_id": "f2", "feature_label": "PTPRK feature", "form_id": "form_ptprk",
         "source_bindings": [{"membership_ids": ["card_member_2"], "contrast_id": "cA", "arm_id": "arm",
                              "reference_condition_id": "base", "pairing": "unpaired"}]},
    ]
    contributions = pd.DataFrame({
        "form_ids": ["form_taok", "form_taok;other", "form_ta", "form_other", "form_taok"],
        "candidate_id": ["c1", "c2", "c_short", "c3", "c_out"],
        "contrast_id": ["cA", "cA", "cA", "cA", "cB"],
    })
    precursor = pd.DataFrame({"membership_id": ["card_member_1"]})
    temporal = [
        {"finding_id": "f1", "status": "linked", "candidates": [
            {"candidate_id": "c1", "track": "motif_A"}, {"candidate_id": "c1", "track": "specificity_A"}, {"candidate_id": "c2", "track": "motif_A"}]},
        {"finding_id": "f2", "status": "linked", "candidates": []},
    ]
    summary = selected_kinase_contribution_summary(
        findings, contributions, precursor_membership=precursor, temporal_findings=temporal)
    assert summary["precursor_linked_findings"] == 1
    assert summary["contribution_linked_findings"] == 1
    assert summary["candidate_count"] == 2
    text = kinase_link_sentence(summary)
    assert "kinase 후보가 아닙니다" in text
    assert "연결된 선정 관측은 1개" in text
    assert "candidate_id는 2개" in text
    assert "하나의 연결 수로 합치지 않습니다" in text
    absent = kinase_link_sentence(selected_kinase_contribution_summary(findings, None))
    assert "0개" not in absent
    assert "없어" in absent
    scoped = selected_kinase_contribution_summary(findings, contributions, precursor_membership=precursor)
    assert scoped["candidate_count"] == 2


def _grid(labels, times):
    return {
        "condition_grid": {"conditions": list(labels)},
        "trajectory": [{"condition": label, "time_minutes": minutes} for label, minutes in zip(labels, times)],
        "source_bindings": [{"contrast_id": f"contrast_{minutes}", "time_min": minutes, "U_joint": index}
                            for index, minutes in enumerate(times)],
    }


def test_recorded_time_projection_repairs_both_known_label_orders_without_changing_values():
    orders = [
        ["15min vs Control [contrast_15]", "180min vs Control [contrast_180]", "1min vs Control [contrast_1]",
         "30min vs Control [contrast_30]", "5min vs Control [contrast_5]", "60min vs Control [contrast_60]"],
        ["5min vs Control [contrast_5]", "1min vs Control [contrast_1]", "30min vs Control [contrast_30]",
         "180min vs Control [contrast_180]", "15min vs Control [contrast_15]", "60min vs Control [contrast_60]"],
    ]
    expected = ["1min vs Control [contrast_1]", "5min vs Control [contrast_5]", "15min vs Control [contrast_15]",
                "30min vs Control [contrast_30]", "60min vs Control [contrast_60]", "180min vs Control [contrast_180]"]
    minutes = {"1min vs Control [contrast_1]": 1, "5min vs Control [contrast_5]": 5, "15min vs Control [contrast_15]": 15,
               "30min vs Control [contrast_30]": 30, "60min vs Control [contrast_60]": 60, "180min vs Control [contrast_180]": 180}
    for labels in orders:
        card = _grid(labels, [minutes[label] for label in labels])
        values = {binding["contrast_id"]: binding["U_joint"] for binding in card["source_bindings"]}
        project_recorded_time_order(card)
        assert card["condition_grid"]["conditions"] == expected
        assert [binding["time_min"] for binding in card["source_bindings"]] == [1, 5, 15, 30, 60, 180]
        assert {binding["contrast_id"]: binding["U_joint"] for binding in card["source_bindings"]} == values
        project_recorded_time_order(card)
        assert card["condition_grid"]["conditions"] == expected


def test_unresolved_or_same_time_rows_are_not_collapsed():
    missing = _grid(["15min", "1min"], [15, None])
    project_recorded_time_order(missing)
    assert missing["condition_grid"]["conditions"] == ["15min", "1min"]
    assert missing["condition_grid"]["time_order_status"] == "unresolved_recorded_time"
    same = {
        "condition_grid": {"conditions": ["a vs other", "b vs base"]},
        "trajectory": [{"condition": "a vs other", "time_minutes": 30}, {"condition": "b vs base", "time_minutes": 30}],
        "source_bindings": [
            {"contrast_id": "other", "time_min": 30, "reference_condition_id": "other_base", "U_joint": 1},
            {"contrast_id": "base", "time_min": 30, "reference_condition_id": "base", "U_joint": 2},
        ],
    }
    project_recorded_time_order(same)
    assert same["condition_grid"]["conditions"] == ["a vs other", "b vs base"]
    assert [binding["contrast_id"] for binding in same["source_bindings"]] == ["other", "base"]
    assert [binding["U_joint"] for binding in same["source_bindings"]] == [1, 2]


def test_literature_guidance_lists_retrieved_source_identifiers(tmp_path):
    source = {
        "title": "Stored paper",
        "doi": "10.1073/pnas.0711713105",
        "pmid": "18268350",
        "evidence_location": {"section": "results", "chunk_index": 6, "chunk_id": "chunk-6"},
        "export_status": "metadata_only_export_permission_unconfirmed",
    }
    section = "\n".join(retrieved_source_guidance([
        ("b-source", source),
        ("a-source", {"doi": "10.1073/pnas.0711713105", "pmid": "18268350",
                      "evidence_location": {"chunk_id": "chunk-7", "chunk_index": 7, "section": "results"}}),
        ("meta-only", {"metadata": {"DOI": "10.1000/meta", "PMID": "1"}, "title": "Meta"}),
    ]))
    assert section.index("source_key=a-source") < section.index("source_key=b-source")
    assert "DOI=10.1073/pnas.0711713105" in section
    assert "PMID=18268350" in section
    assert "chunk_id=chunk-6" in section
    assert "DOI=10.1000/meta" in section
    assert "검색 구간 3개, 고유 논문 2편" in section
    duplicate = "\n".join(retrieved_source_guidance([
        ("same", {"doi": "10.1/a", "evidence_location": {"chunk_id": "1", "chunk_index": 1, "section": "results"}}),
        ("same", {"doi": "10.1/a", "evidence_location": {"chunk_id": "2", "chunk_index": 2, "section": "methods"}}),
    ]))
    assert duplicate.count("source_key=same") == 2
    assert "chunk_id=1" in duplicate and "chunk_id=2" in duplicate
    packet = {
        "literature": {
            "pin": {"documents": [{"metadata": {"DOI": None, "PMID": None}, "content_status": "metadata_only"}]},
            "summary": {"semantically_verified_comparable_findings": 0},
            "finding_records": {},
        },
        "reader_cards": [],
    }
    tables = {
        "reader/packet": pd.DataFrame([{"packet_json": json.dumps(packet)}]),
        "reader/literature_comparisons": pd.DataFrame(columns=["finding_id", "comparison_json", "source_key"]),
        "reader/literature_sources": pd.DataFrame([{"source_key": "src", "source_json": json.dumps(source)}]),
    }
    write(tmp_path, tables)
    text = (tmp_path / "reader" / "LITERATURE.md").read_text()
    source_section = text.split("## 검색된 구간의 출처", 1)[1].split("## 패키지 문서 목록", 1)[0]
    assert "DOI=10.1073/pnas.0711713105" in source_section
    assert "PMID=18268350" in source_section
    assert "DOI=없음" not in source_section
    assert "승인된 비교는 semantically_verified_comparable_findings" in text
