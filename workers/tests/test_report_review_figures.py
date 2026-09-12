from report_generation.core.nodes.signal_flow_figure import generate_context_aware_ptm_heatmap


def test_each_selected_feature_uses_its_own_conditions_and_eligibility(tmp_path, monkeypatch):
    from matplotlib.axes import Axes
    captured = []
    original = Axes.set_yticklabels
    def labels(self, values, *args, **kwargs):
        captured.extend(str(value) for value in values)
        return original(self, values, *args, **kwargs)
    monkeypatch.setattr(Axes, "set_yticklabels", labels)
    rows = [{"gene": gene, "position": "S1", "condition": condition,
             "Precursor.Id": gene, "Modified.Sequence": "AS(UniMod:21)K",
             "ptm_unadjusted_log2fc": .2, "ptm_relative_log2fc": .3,
             "protein_log2fc": .1, "ptm_unadjusted_conventional_log2fc_na": False}
            for gene, condition in (("EARLY", "1min"), ("LATE", "5min"), ("HIDDEN", "1min"))]
    selected = [{"gene": gene, "position": "S1", "source_feature_id": gene,
                 "modified_sequence": "AS(UniMod:21)K", "display_label": gene + " PF-00000001",
                 "conditions": [condition], "render_eligible": eligible}
                for gene, condition, eligible in (("EARLY", "1min", True), ("LATE", "5min", True), ("HIDDEN", "1min", False))]
    output = generate_context_aware_ptm_heatmap({}, rows, ["1min", "5min"], str(tmp_path), selected_features=selected)
    assert output
    assert "EARLY PF-00000001" in captured and "LATE PF-00000001" in captured
    assert "HIDDEN PF-00000001" not in captured
