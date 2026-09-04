from pathlib import Path

from ptm_shared.de_novo_representation import is_de_novo_representation
from ptm_shared.enrichment_free_temporal_sidecar import _write_wave_membership_audit, build_v2_sidecar
from report_generation.core.dynamic_prompt_generator import build_ptm_data_summary
from report_generation.core.nodes.context_loader import _parse_enriched_ptms


def test_de_novo_representation_uses_provenance_flags_not_numeric_magnitude() -> None:
    assert is_de_novo_representation({"Conventional_Log2FC_NA": "true", "ptm_relative_log2fc": 99.0})
    assert is_de_novo_representation({"control_pseudocount_used": 1, "ptm_relative_log2fc": 30.0})
    assert is_de_novo_representation({"activity_class": "de_novo", "ptm_relative_log2fc": 20.0})
    assert not is_de_novo_representation({"Conventional_Log2FC_NA": "false", "ptm_relative_log2fc": 30.0})


def test_report_legacy_summary_and_loader_keep_conventional_na_extreme_rows_out_of_pseudo_log2fc_paths() -> None:
    raw = {
        "gene": "DN", "position": "S7", "Condition": "15min", "PTM_Relative_Log2FC": 99.0,
        "Conventional_Log2FC_NA": "true", "DeNovo_Confidence": "high", "Ranking_Score": 4.0,
        "Detection_Pattern": "3/4 → 4/4",
    }
    parsed = _parse_enriched_ptms([raw])
    assert parsed[0]["activity_class"] == "de_novo"
    assert parsed[0]["conventional_log2fc_na"] is True
    summary = build_ptm_data_summary(parsed)
    assert "99.0" not in summary
    assert "Conventional Log2FC=NA" in summary


def test_membership_audit_is_deterministic_and_separate_from_compact_report_projection(tmp_path: Path) -> None:
    audit = _write_wave_membership_audit(
        tmp_path,
        {"waves": [
            {"wave_id": "TW-02", "members": ["B_S2", "A_S1"]},
            {"wave_id": "TW-01", "members": ["C_S3"]},
        ]},
    )
    assert audit["status"] == "written"
    assert audit["artifact_name"] == "co_wave_membership_audit.tsv"
    assert audit["member_row_count"] == 3
    assert (tmp_path / audit["artifact_name"]).read_text(encoding="utf-8").splitlines() == [
        "wave_id\tmember_rank\tsite_key",
        "TW-01\t1\tC_S3",
        "TW-02\t1\tA_S1",
        "TW-02\t2\tB_S2",
    ]


def test_canonical_sidecar_build_writes_membership_audit_without_compact_member_payload(tmp_path: Path) -> None:
    sidecar = build_v2_sidecar(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        site_observations=[],
        wave_contract={"timepoints": ["0min", "15min"], "waves": [{"wave_id": "TW-01", "members": ["A_S1"]}]},
        tmm_result={},
        enable_dynamic_transition=False,
    )
    assert sidecar["co_wave_membership_audit"]["status"] == "written"
    assert (tmp_path / "co_wave_membership_audit.tsv").exists()
