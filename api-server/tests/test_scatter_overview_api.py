import csv
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import orders, analysis_jobs, vector_view


def client_for_viewer(tmp_path, monkeypatch):
    order = SimpleNamespace(id=1, order_code="SYNTHETIC", user_id=2, ptm_type="phosphorylation")
    root = tmp_path / order.order_code
    root.mkdir()
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: order)))
    app = FastAPI(); app.include_router(vector_view.router); app.include_router(orders.router)
    app.dependency_overrides[vector_view.get_db] = lambda: db
    app.dependency_overrides[vector_view.get_current_user] = lambda: SimpleNamespace(id=7, role="viewer")
    # Real order access check with a read-only share, never a write grant.
    monkeypatch.setattr(orders, "_get_share_access", AsyncMock(return_value="read_only"))
    write = AsyncMock(side_effect=AssertionError("Scatter must not request write access"))
    monkeypatch.setattr(analysis_jobs, "_require_write_access", write)
    monkeypatch.setattr(vector_view, "get_settings", lambda: SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    return TestClient(app), root, write


def test_legacy_viewer_without_snapshot_reads_all_rows_without_jobs(tmp_path, monkeypatch):
    client, root, write = client_for_viewer(tmp_path, monkeypatch)
    source = root / "ptm_vector_data_normalized_phospho.tsv"
    with source.open("w") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["Gene.Name", "Condition", "Protein_Log2FC", "PTM_ProteinAdjusted_Log2FC", "Precursor.Id"])
        writer.writerows([["Rps6", f"{i % 6 + 1}min", 0, i, f"p{i}"] for i in range(150)])
    original = source.read_bytes()
    old = client.post("/orders/1/vector-view/manifest", json={})
    assert old.status_code == 409 and old.json()["detail"]["reason"] == "columnar_snapshot_unavailable"
    new = client.get("/orders/1/vector-scatter-data")
    assert new.status_code == 200, new.text
    data = new.json()
    assert data["coverage"]["represented_rows"] == 150
    assert sum(len(c["points"]) for c in data["conditions"]) == 150
    assert set(root.iterdir()) == {source} and source.read_bytes() == original
    assert write.await_count == 0
    for rag in ("[]", "["):
        (root / "enriched_ptm_data_phospho.json").write_text(rag)
        assert client.get("/orders/1/vector-scatter-data").json() == data
    download = client.get(f"/orders/1/files/{data['source']['filename']}")
    assert download.status_code == 200 and download.content == original
    assert client.get("/orders/1/vector-scatter-data?axis=invalid").status_code == 422


def test_permission_missing_source_and_corrupt_tsv_are_not_empty_success(tmp_path, monkeypatch):
    client, root, _ = client_for_viewer(tmp_path, monkeypatch)
    url = "/orders/1/vector-scatter-data"
    assert client.get(url).status_code == 404
    monkeypatch.setattr(orders, "_get_share_access", AsyncMock(return_value=None))
    assert client.get(url).status_code == 403
    monkeypatch.setattr(orders, "_get_share_access", AsyncMock(return_value="read_only"))
    (root / "ptm_vector_data_with_motifs_phospho.tsv").write_text('Condition\tProtein_Log2FC\n"unterminated')
    assert client.get(url).status_code == 422


def test_scatter_to_exact_curve_and_download_revision(tmp_path, monkeypatch):
    client, root, write = client_for_viewer(tmp_path, monkeypatch)
    source = root / "ptm_vector_data_normalized_phospho.tsv"
    source.write_text("Condition\tTime_Minutes\tPrecursor.Id\tProtein_Log2FC\tPTM_ProteinAdjusted_Log2FC\tPTM_Unadjusted_Log2FC\n"
                      "ControllerDrug\t30\tpep1\t0\t1\t2\nother\t5\tpep2\t0\t2\t2\n")
    view=client.get("/orders/1/vector-scatter-data").json()
    point=next(c for c in view["conditions"] if c["condition"]=="ControllerDrug")["points"][0]
    url="/orders/1/vector-view/feature-detail"
    request={"measurement_revision":view["measurement_revision"],"options":{"feature_id":point["feature_id"]}}
    detail=client.post(url,json=request).json()
    assert detail["feature"]["feature_id"]==point["feature_id"]
    assert [c["time_minutes"] for c in detail["condition_grid"]]==[5,30]
    assert detail["observations"][0]["ptm_protein_adjusted_log2fc"]==point["y"]
    download="/orders/1/vector-scatter-source?sha256="+view["source"]["sha256"]
    assert client.get(download).content==source.read_bytes()
    source.write_text(source.read_text().replace("pep1","pep3"))
    assert client.get(download).status_code==client.post(url,json=request).status_code==409
    assert not write.await_count
