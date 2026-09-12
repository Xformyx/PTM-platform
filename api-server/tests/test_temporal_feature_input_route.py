"""Execute route input wiring without database/Celery side effects.

The AST extraction runs actual statements, not a copy of the old input loop.
HTTP permissions, persistence and dispatch require separate integration tests.
"""
import ast
import hashlib
import json
from pathlib import Path

import numpy as np

from app.services.temporal_kinase_scoring import compute_weighted_kinase_scores
from ptm_shared.enrichment_free_temporal_sidecar import build_production_site_observations
from ptm_shared.temporal_wave_input_projection import project_temporal_wave_input


def route_input(rows):
    path = Path(__file__).parents[1] / "app/api/orders.py"
    tree = ast.parse(path.read_text())
    route = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "kinase_activity_heatmap")
    start = next(i for i, n in enumerate(route.body) if isinstance(n, ast.ImportFrom) and n.module == "ptm_shared.temporal_feature_input")
    end = next(i for i, n in enumerate(route.body[start:], start) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "conditions_sorted" for t in n.targets))
    env = {"vector_data": rows, "kinase_modules": [{"kinase": "K", "ptms": [{"gene": "G", "position": "S1"}]}]}
    exec(compile(ast.Module(body=route.body[start:end + 1], type_ignores=[]), str(path), "exec"), env)
    return env


def test_actual_route_keeps_forms_through_tmm_and_partial_wave_projection():
    rows = [dict(gene="G", position="S1", precursor_id=p, condition=c,
                 log2fc=v, q_value=None, is_de_novo_representation=False)
            for p, c, v in [("P1", "1min", 1.), ("P1", "5min", None), ("P1", "15min", 1.),
                            ("P2", "1min", -3.), ("P2", "5min", 0.), ("P2", "15min", -3.)]]
    env = route_input(rows)
    assert env["temporal_inputs"] == route_input(rows[::-1])["temporal_inputs"]
    keys = [env["member_key"](p) for p in env["kinase_modules"][0]["ptms"]]
    assert len(keys) == 2
    assert set(keys) == set(env["ptm_timeseries"])
    result = compute_weighted_kinase_scores(
        [{"canonical": "K", "members": [{"key": key} for key in keys]}],
        env["ptm_timeseries"], {key: ["K"] for key in keys}, env["conditions_sorted"],
    )["K"]
    assert result["observation_counts"] == {"1min": 2, "5min": 1, "15min": 2}
    assert {d["ptm_key"] for d in result["contribution_details"]} == set(keys)
    observations, vectors = build_production_site_observations(
        env["ptm_timeseries"], env["conditions_sorted"], env["temporal_inputs"]["features"],
    )
    assert len(observations) == 2
    assert {o["gene"] for o in observations} == {"G"}
    assert {o["site"] for o in observations} == {"S1"}
    eligible, audit = project_temporal_wave_input(vectors, env["conditions_sorted"])
    assert len(eligible) == 1


def test_route_clustering_never_fills_partial_feature_with_zero():
    rows = [dict(gene="G", position="S1", precursor_id="P1", condition=c, log2fc=v)
            for c, v in [("1min", 1.), ("5min", None), ("15min", 1.)]]
    env = route_input(rows)
    tree = ast.parse((Path(__file__).parents[1] / "app/api/orders.py").read_text())
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_cluster_ptms_by_trajectory")
    env["np"] = np
    exec(compile(ast.Module(body=[function], type_ignores=[]), "route_clustering", "exec"), env)
    clusters = env["_cluster_ptms_by_trajectory"](env["kinase_modules"][0]["ptms"])
    assert len(clusters) == 1
    assert not clusters[0]["clustering_eligible"]
    assert clusters[0]["reason"] == "incomplete_observed_grid"


def test_old_sidecar_is_preserved_but_not_reused_for_new_feature_values(tmp_path):
    tree = ast.parse((Path(__file__).parents[1] / "app/api/orders.py").read_text())
    statement = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and ast.unparse(n.test) == "unified_sidecar is not None")
    path = tmp_path / "sidecar.json"
    old = {"provenance": {"temporal_input": {"feature_input_sha256": "old-input"}}}
    path.write_text(json.dumps(old))
    def write_json(target, data, **_):
        target.write_text(json.dumps(data))
    env = {"unified_sidecar": old, "unified_path": path, "hashlib": hashlib,
           "temporal_inputs": {"input_sha256": "new-input"}, "atomic_write_json": write_json}
    code = compile(ast.Module(body=[statement], type_ignores=[]), "sidecar_reuse_gate", "exec")
    exec(code, env)
    assert env["unified_sidecar"] is None
    preserved = list(tmp_path.glob("*.previous-*.json"))
    assert len(preserved) == 1
    assert json.loads(preserved[0].read_text()) == old
    env["unified_sidecar"] = old
    env["temporal_inputs"]["input_sha256"] = "old-input"
    exec(code, env)
    assert env["unified_sidecar"] == old
