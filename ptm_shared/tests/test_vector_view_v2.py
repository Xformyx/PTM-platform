"""Synthetic labels exercise contracts, not biological assignment accuracy."""
from ptm_shared.vector_plot import project_plot_row, plot_feature_metadata
from ptm_shared.vector_plot import normalize_plot_records, measurement_signature
from ptm_shared.plot_selection import build_vector_view, select_plot_features, ordered_conditions
from ptm_shared.annotation_context import build_annotation_context_key
import pytest
from copy import deepcopy


def measured(gene="Rps6", precursor="p1", condition="1min", value=2, **extra):
    return project_plot_row({"Gene.Name": gene, "PTM_Position": "S185",
        "Precursor.Id": precursor, "Precursor.Charge": 2, "Condition": condition,
        "PTM_ProteinAdjusted_Log2FC": value, "PTM_Unadjusted_Log2FC": value,
        "FASTA_Taxonomy_ID": "10090", "FASTA_Accession": "fixture-accession", **extra})


def test_v01_mixed_case_annotation_is_not_a_measurement_filter():
    rows = [measured(gene=g, precursor=g, condition=c) for g in ("Rps6", "Akt1", "INSR")
            for c in ("1min", "5min")]
    annotations = [{"gene": g, "position": "S185", "fasta_taxonomy_id": "10090",
                    "accession": "fixture-accession"} for g in ("Rps6", "Akt1", "INSR")]
    features = plot_feature_metadata(rows, annotations)
    assert {p["feature_id"] for p in features} == {r["feature_id"] for r in rows}
    assert {p["source_gene_label"] for p in features} == {"Rps6", "Akt1", "INSR"}


def view(rows, annotations=(), status="available", **options):
    return build_vector_view(normalize_plot_records(rows), annotations, measurement_revision="fixture-v1",
        annotation_source={"kind": "rag", "status": status, "revision": "fixture-annotation-v1"}, **options)


def test_v02_normalized_matching_preserves_measurements_and_identity():
    rows = [measured()]
    baseline = deepcopy(rows)
    annotation = {"gene": " RPS6 ", "position": "s185", "fasta_taxonomy_id": "10090", "accession": "fixture-accession"}
    result = view(rows, [annotation])
    assert result["features"][0]["annotation_match"]["match_method"] == "normalized_context"
    assert rows == baseline
    assert measurement_signature(result["observations"][0]) == measurement_signature(rows[0])
    assert build_annotation_context_key({"gene": " Rps6 ", "position": "185"})[1] == ""


def test_v03_v04_forms_are_distinct_and_foreign_context_cannot_select():
    rows = [measured(precursor="p2", **{"Precursor.Charge": 2}), measured(precursor="p3", **{"Precursor.Charge": 3})]
    for fields in ({"fasta_taxonomy_id": "9606"}, {"isoform": "other-isoform"}):
        annotation = {"gene": "Rps6", "position": "S185", "accession": "fixture-accession", **fields}
        result = view(rows, [annotation], mode="all_observed", n=None)
        assert len(result["features"]) == 2
        assert all(p["annotation_match"]["match_scope"] not in {"feature", "site_context"} for p in result["features"])
        assert not view(rows, [annotation], mode="rag_only", n=None)["features"]


@pytest.mark.parametrize("status", ["missing", "empty", "partial", "failed", "available"])
def test_v05_v06_v19_annotation_cannot_change_default_selection(status):
    rows = [measured(precursor=f"p{i}", value=i) for i in range(4)]
    baseline = view(rows, [], "missing")
    result = view(rows, [{"gene": "Rps6", "position": "S185"}], status)
    assert result["selection"] == baseline["selection"]
    assert result["observations"] == baseline["observations"]


def test_v07_annotation_identity_collisions_are_preserved():
    annotations = [{"annotation_id": "same", "gene": "Rps6", "position": "S185", "claim": c} for c in ("one", "two")]
    result = view([measured()], annotations)
    match = result["features"][0]["annotation_match"]
    assert match["status"] == "ambiguous"
    assert len(match["assertions"]) == 2


def four_features():
    return [measured(precursor=f"F{i+1}", condition=c, value=v)
            for i, values in enumerate(((6,.2),(5,4),(1,8),(.5,7)))
            for c, v in zip(("1min", "5min"), values)]


def test_v08_v09_per_condition_union_recovers_every_time():
    rows = four_features()
    per = view(rows, n=2)
    glob = view(rows, mode="global_top_n", n=2)
    assert (len(per["features"]), len(per["observations"])) == (4,8)
    assert (len(glob["features"]), len(glob["observations"])) == (2,4)
    assert {p["precursor_id"] for p in glob["features"]} == {"F3", "F4"}


def test_v10_ties_and_input_order_are_deterministic():
    rows = [measured(precursor=p, condition=c) for p in ("z", "a", "b") for c in ("5min", "1min")]
    assert view(rows, n=2) == view(rows[::-1], n=2)
    assert view(rows, n=2)["selection"]["selected_feature_ids"] == sorted({r["feature_id"] for r in rows})[:2]


def test_v11_v12_v13_missing_zero_partial_and_unresolved():
    rows = [measured(value=v, precursor=f"p{i}") for i, v in enumerate((0, None, "NaN", "inf", "-inf"))]
    rows += [measured(precursor="", value=5), measured(condition="180min", value=3)]
    result = view(rows, mode="all_observed", n=None)
    assert len(result["features"]) == 2
    assert result["coverage"]["identity_unresolved_rows"] == 1
    assert result["coverage"]["finite_observations"] == 2
    assert ordered_conditions(rows + [measured(condition="5min")]) == ["1min", "5min", "180min"]
    denom = measured(**{"PTM_ProteinAdjusted_Log2FC": "", "PTM_Unadjusted_Log2FC": 2,
                        "PTM_ProteinAdjusted_Missing_Reason": "protein_denominator_unavailable"})
    assert not view([denom])["features"]
    assert view([denom], axis="unadjusted")["observations"][0]["ptm_unadjusted_log2fc"] == 2


def test_v14_metadata_duplicates_vs_measurement_and_unit_conflicts():
    a = measured()
    b = {**a, "source_gene_label": "RPS6", "source_row_lineage": [{"line": 2}]}
    result = normalize_plot_records([a,b])
    assert result[0]["ptm_protein_adjusted_log2fc"] == 2
    assert result[0]["source_row_count"] == 2
    assert result[0]["source_row_lineage"] == [{"line": 2}]
    for b in ({**a, "ptm_protein_adjusted_log2fc": 4}, {**a, "biological_unit": "another-unit"}):
        assert normalize_plot_records([a,b])[0]["ptm_protein_adjusted_log2fc"] is None


def test_v15_rag_only_never_falls_back_and_requires_site_scope():
    rows = [measured()]
    assert view(rows, status="missing", mode="rag_only", n=None)["selection"]["selection_status"] == "unavailable"
    assert view(rows, status="empty", mode="rag_only", n=None)["selection"]["selection_status"] == "empty_selection"
    assert not view(rows, [{"gene": "Rps6"}], mode="rag_only", n=None)["features"]
    ann = {"gene": "Rps6", "position": "S185", "fasta_taxonomy_id": "10090", "accession": "fixture-accession"}
    assert len(view(rows, [ann], mode="rag_only", n=None)["features"]) == 1


def test_v16_annotation_partition_is_not_a_funnel():
    rows = [measured(gene=f"g{i}", precursor=f"p{i}") for i in range(50)]
    annotations = [{"gene": f"g{i}", "position": "S185"} for i in range(32)]
    result = view(rows, annotations)
    c = result["coverage"]
    assert c["selected_features"] == 50
    assert c["annotation_matched_features"] == 32
    assert c["annotation_unmatched_features"] == 18
    assert sum(c[f"annotation_{state}_features"] for state in ("matched", "unmatched", "ambiguous")) == 50


def test_v18_view_changes_do_not_change_source_revision():
    one = view(four_features(), n=1)
    two = view(four_features(), n=2)
    assert one["measurement_revision"] == two["measurement_revision"]
    assert one["selection"]["selection_hash"] != two["selection"]["selection_hash"]
    with pytest.raises(ValueError):
        select_plot_features([], mode="all_observed", n=9999)


def test_analysis_signatures_cover_late_candidate_members_weights_and_references():
    from ptm_shared.analysis_universe import build_analysis_manifest
    rows=[measured(precursor=f'p{i}') for i in range(35)]
    snapshot={'rows':rows,'measurement_revision':'frozen','source_rows':35}
    modules=[{'canonical':f'K{i:02d}','members':[{'key':r['feature_id'],'weight':1}]} for i,r in enumerate(rows)]
    def manifest(mods=modules,**kwargs):return build_analysis_manifest(snapshot,candidate_modules=mods,**kwargs)[0]['analysis_manifest_id']
    baseline=manifest()
    assert manifest(list(reversed(modules)))==baseline
    changed=deepcopy(modules);changed[-1]['members'][0]['weight']=.5
    assert manifest(changed)!=baseline
    changed=deepcopy(modules);changed[-1]['canonical']='DIFFERENT31'
    assert manifest(changed)!=baseline
    assert manifest(reference_snapshots={'release':'other'})!=baseline
    assert manifest(sample_manifest={'biological_units':3})!=baseline
    assert manifest(config={'track':'other'})!=baseline
