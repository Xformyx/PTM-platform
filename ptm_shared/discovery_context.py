"""Separate experimental design from treatment identity in new discovery jobs."""
from .analysis_universe import signature

VERSION="discovery_context.v1"
DESIGN_FIELDS={"sample_manifest","species","taxon","taxonomy_id","cell_type","cell_model",
    "timepoints","time_unit","conditions","paired","biological_units","batch_design","dose_groups","quantification_method","acquisition_method"}
TEMPORAL_FIELDS={"time_unit_label","nominal_grid_interval_minutes","gp_length_scale_min_minutes",
    "synchrony_tau_minutes","gp_length_scale_source","pre_registration_date","pre_registered"}


def discovery_context(metadata):
    context={k:v for k,v in (metadata or {}).items() if k in DESIGN_FIELDS}
    temporal=(metadata or {}).get("temporal_context")
    if isinstance(temporal,dict):
        timing={k:v for k,v in temporal.items() if k in TEMPORAL_FIELDS}
        timing.update(study_id="blind-"+signature(timing),chemical_holdout_description="treatment_identity_withheld",
            known_relation_registry_path=None)
        context["temporal_context"]=timing
    return context
