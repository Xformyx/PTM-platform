"""Additive HTTP schema; compatibility aliases must bind the same selection."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, model_validator


class Selection(BaseModel):
    model_config = ConfigDict(extra='allow')
    mode: Literal['per_condition_top_n','global_top_n','all_observed','rag_only']
    n: int | None
    unit: Literal['modified_precursor_feature']
    axis: Literal['adjusted','unadjusted','protein']
    representation: Literal['conventional_log2_contrast','lod_relative_log2','normalized_log2_intensity','occupancy_logit_delta']
    ranking_metric: Literal['abs_effect','legacy_ranking_score']
    ranking_version: str
    tie_break: Literal['feature_id_ascending']
    selection_status: Literal['ready','unavailable','empty_selection']
    selected_feature_ids: list[str]
    union_feature_count: int
    selection_hash: str

    @model_validator(mode='after')
    def validate_counts(self):
        if self.union_feature_count != len(set(self.selected_feature_ids)):
            raise ValueError('selection_identity_count_mismatch')
        if self.mode.endswith('top_n'):
            if self.n is None or self.n < 1: raise ValueError('invalid_top_n')
        elif self.n is not None: raise ValueError('non_top_n_requires_null')
        return self


class VectorViewResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    contract_version: Literal['vector_view.v2']
    measurement_revision: str | None
    selection: Selection
    sources: dict[str, dict[str, Any]]
    coverage: dict[str, Any]
    features: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    vector_data: list[dict[str, Any]]
    top_n_ptms: list[dict[str, Any]]

    @model_validator(mode='after')
    def validate_bindings(self):
        selected=set(self.selection.selected_feature_ids)
        if {f['feature_id'] for f in self.features} != selected:
            raise ValueError('feature_selection_binding_mismatch')
        if self.features != self.top_n_ptms or self.observations != self.vector_data:
            raise ValueError('compatibility_alias_mismatch')
        if any(r.get('feature_id') not in selected for r in self.observations):
            raise ValueError('observation_selection_binding_mismatch')
        if sum(self.coverage[f'annotation_{s}_features'] for s in ('matched','unmatched','ambiguous')) != len(selected):
            raise ValueError('annotation_partition_mismatch')
        if self.sources['measurements']['revision'] != self.measurement_revision:
            raise ValueError('measurement_revision_mismatch')
        return self
