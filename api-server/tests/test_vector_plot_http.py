"""Real FastAPI route -> JSON -> the React evidence table, synthetic storage/DB."""
import csv
import json
import subprocess
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import orders


def test_route_to_ui_preserves_null_support_and_distinct_forms(tmp_path, monkeypatch):
    output = tmp_path / "SYNTHETIC"
    output.mkdir()
    rows = [{"Gene.Name": "G", "PTM_Position": "S1", "Precursor.Id": p, "Condition": c,
             "PTM_Unadjusted_Log2FC": v, "PTM_ProteinAdjusted_Log2FC": "", "Protein_Log2FC": "",
             "PTM_ProteinAdjusted_Missing_Reason": "protein_denominator_unavailable",
             "PTM_Unadjusted_Q_Value": q, "PTM_Unadjusted_Control_N": 1}
            for p, c, v, q in [("P1", "5min", 2, .5), ("P1", "40min", .1, .001), ("P2", "5min", -2, .01)]]
    path = output / "ptm_vector_data_normalized_phospho.tsv"
    with path.open("w") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    order = SimpleNamespace(id=1, order_code="SYNTHETIC", ptm_type="phosphorylation", report_options={"top_n_ptms": 20},
                            receptor_inference_data={"receptors": [{"name": "fixture-context"}], "top_n_setting": 20,
                                                     "cowave_analysis": {"legacy_gene_site_values": [9]},
                                                     "divergence_pairs": [{"old": 9}]})
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: order)))
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    monkeypatch.setattr(orders, "_check_order_access_async", AsyncMock())
    app = FastAPI()
    app.include_router(orders.router)
    app.dependency_overrides[orders.get_db] = lambda: db
    app.dependency_overrides[orders.get_current_user] = lambda: SimpleNamespace(id=1, role="admin")
    response = TestClient(app).get("/orders/1/vector-plot-data?lock_receptor=true&axis=unadjusted")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cowave_analysis"] is None
    assert payload["divergence_pairs"] == []
    assert len(payload["top_n_ptms"]) == 2
    assert all(r["ptm_protein_adjusted_log2fc"] is None and r["protein_log2fc"] is None for r in payload["vector_data"])
    assert {r["feature_id"] for r in payload["vector_data"]} == {p["feature_id"] for p in payload["top_n_ptms"]}
    # Bundle the same component imported by OrderDetail, then render its actual
    # markup with this route response. This is not a browser layout test.
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    script = tmp_path / "ui.cjs"
    esbuild = frontend / "node_modules/.bin/esbuild"
    if not esbuild.exists():
        # pnpm's isolated linker does not expose transitive package bins in
        # node_modules/.bin. Locate the installed Vite/esbuild binary without
        # depending on a particular package-manager linker mode.
        candidates = sorted((frontend / "node_modules/.pnpm").glob("esbuild@*/node_modules/esbuild/bin/esbuild"))
        assert candidates, "esbuild binary was not installed for component bundle regression"
        esbuild = candidates[-1]
    subprocess.run([str(esbuild), "src/components/QuantitationEvidenceTable.tsx",
                    "--bundle", "--external:react", "--external:react-dom", "--platform=node", "--format=cjs", "--jsx=automatic", f"--outfile={script}"], cwd=frontend, check=True, capture_output=True)
    render = "const React=require('react'), R=require('react-dom/server'); const C=require(process.argv[1]); let s=''; process.stdin.on('data',d=>s+=d); process.stdin.on('end',()=>process.stdout.write(R.renderToStaticMarkup(React.createElement(C.QuantitationEvidenceTable,{rows:JSON.parse(s).vector_data}))));"
    result = subprocess.run(["node", "-e", render, str(script)], cwd=frontend, env={**os.environ,"NODE_PATH":str(frontend/"node_modules")}, input=json.dumps(payload), text=True, capture_output=True, check=True)
    assert "protein_denominator_unavailable" in result.stdout
    assert "<strong>NA</strong>" in result.stdout
    assert "2.000" in result.stdout and "-2.000" in result.stdout
    assert "q: 0.500" in result.stdout
