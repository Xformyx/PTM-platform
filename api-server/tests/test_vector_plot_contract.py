"""General vector route CSV boundary, separate from kinase heatmap input."""
import ast
import csv
from pathlib import Path


def route_vectors(tmp_path, rows):
    path = Path(__file__).parents[1] / "app/api/orders.py"
    route = next(n for n in ast.parse(path.read_text()).body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_vector_plot_data")
    loop = next(n for n in route.body if isinstance(n, ast.For) and ast.unparse(n.target) == "name")
    with (tmp_path / "ptm_vector_data_normalized_phospho.tsv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for row in rows for k in row)), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    env = {"output_dir": tmp_path, "file_suffix": "_phospho", "vector_data": []}
    exec(compile(ast.Module(body=[loop], type_ignores=[]), str(path), "exec"), env)
    return env["vector_data"]


def test_canonical_null_survives_general_route_with_independent_support(tmp_path):
    row = {"Gene.Name": "G", "PTM_Position": "S1", "Precursor.Id": "P1", "Condition": "5min",
           "PTM_Unadjusted_Log2FC": 1, "PTM_ProteinAdjusted_Log2FC": "", "PTM_Relative_Log2FC": 7,
           "Protein_Log2FC": "inf", "PTM_ProteinAdjusted_Missing_Reason": "protein_denominator_unavailable",
           "PTM_Unadjusted_Q_Value": .001, "PTM_Unadjusted_Control_Sample_IDs": '["c1"]'}
    result = route_vectors(tmp_path, [row])[0]
    assert result["ptm_unadjusted_log2fc"] == 1
    assert result["ptm_protein_adjusted_log2fc"] is None
    assert result["protein_log2fc"] is None
    assert result["ptm_protein_adjusted_missing_reason"] == "protein_denominator_unavailable"
    assert result["ptm_unadjusted_control_sample_ids"] == ["c1"]
    assert result["ptm_unadjusted_q_value"] == .001
    assert result["feature_id"]
