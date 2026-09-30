"""Sidecar identity audit must open the enriched JSON without treating a list as an iterator.

구현 대상: report_artifact_manifest temporal_input identity audits
사전등록: 해당 없음. 감사 메타만 읽고 TMM 점수는 계산하지 않는다.
해석 한계: 파일 선택과 호출 가능 여부만 본다. 교차검증 통과가 귀속 정확도가 아니다.
주장 금지: 이 검사로 kinase 예측 개선을 주장하지 않는다.
"""

from app.services.production_temporal_analysis import _sidecar_identity_audits


def test_sidecar_audit_reads_sorted_enriched_json(tmp_path):
    order_root = tmp_path / "order"
    source_dir = order_root / "inputs" / "vector"
    source_dir.mkdir(parents=True)
    (order_root / "enriched_ptm_data_phospho.json").write_text("[]", encoding="utf-8")

    audits = _sidecar_identity_audits(source_dir, [])

    assert set(audits) == {
        "site_form_provenance_audit",
        "enriched_vector_crosswalk_audit",
    }
