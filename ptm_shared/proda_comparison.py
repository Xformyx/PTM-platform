"""Optional label-free dropout comparison over frozen raw observations.

The effect is a log-location coefficient, not the existing arithmetic-mean
sample-ratio A estimator. No protein adjustment or causal claim is implied.
"""
import csv
import json
import math
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from statistics import median
from .feature_identity import feature_key
from .sample_manifest import validate_sample_manifest
from .report_revision import file_sha256

MODEL="proda_label_free.v1"


def prepare_proda_input(inventory, features, *, quantification_method):
    if quantification_method!="label_free": raise ValueError("label_free_assay_not_declared")
    design=validate_sample_manifest(inventory.get("sample_manifest"),inventory.get("condition_map"))
    if design["status"]!="validated": raise ValueError("biological_design_unavailable")
    if design["pairing"]!="unpaired": raise ValueError("paired_proda_adapter_not_available")
    sample_groups=defaultdict(list)
    for sample in design["samples"]:
        sample_groups[(sample["condition"],sample["biological_unit"])].append(sample["sample_id"])
    units=sorted(sample_groups)
    conditions=sorted({c for c,_ in units})
    if "Control" not in conditions: raise ValueError("explicit_Control_reference_required")
    conditions=["Control"]+[c for c in conditions if c!="Control"]
    if any(sum(c==condition for c,_ in units)<2 for condition in conditions):
        raise ValueError("insufficient_biological_units")
    unit_conditions=defaultdict(set)
    for c,u in units: unit_conditions[u].add(c)
    if any(len(values)>1 for values in unit_conditions.values()): raise ValueError("unpaired_units_overlap_conditions")
    lookup=defaultdict(list)
    for fid,identity in features.items(): lookup[feature_key(identity)[2:6]].append(fid)
    rows, accounting, seen = {}, [], set()
    for raw in inventory.get("records",[]):
        reason=raw.get("reason")
        matches=lookup.get(feature_key(raw["identity"])[2:6],[])
        if len(matches)!=1: reason="ambiguous_or_unmatched_precursor_binding"
        if reason in {"conflicting_duplicate","exact_duplicate","not_requested_ptm","ambiguous_or_unmatched_precursor_binding"}:
            accounting.append({"source_row":raw["source_row"],"reason":reason});continue
        fid=matches[0]
        if fid in seen: raise ValueError("duplicate_raw_feature_after_inventory_dedup")
        seen.add(fid)
        values=[]
        for unit in units:
            observed=[raw.get("sample_observations",{}).get(s) for s in sample_groups[unit]]
            finite=[math.log2(float(v)) for v in observed if v is not None and math.isfinite(float(v)) and float(v)>0]
            values.append(median(finite) if finite else None)
        rows[fid]=values
    return {"rows":rows,"units":[{"condition":c,"biological_unit":u,"source_samples":sample_groups[(c,u)]} for c,u in units],
        "conditions":conditions,"source_accounting":accounting,"source_rows":len(inventory.get("records",[])),
        "aggregation":"median_log2_positive_raw_intensity_within_biological_unit",
        "zero_policy":"nonpositive_intensity_not_loggable_retained_in_source_inventory",
        "normalization":"no_additional_normalization_in_adapter",
        "source_normalization_policy":inventory.get("normalization_policy"),"imputation":False}


def run_proda_comparison(source, destination, features, config):
    source,destination=Path(source),Path(destination)
    base={"model_id":MODEL,"default_model_promoted":False,"independent_validation":False,
        "records":[],"track":"unadjusted_model_log_location","unit":"log2_location_contrast",
        "biological_interval_type":"dropout_model_conditional_standard_error","protein_adjustment":False}
    pointer=source/"observation_inventory_current.json"
    if not pointer.is_file(): return {**base,"status":"not_evaluable","reason":"raw_observation_inventory_missing"}
    ref=json.loads(pointer.read_text());raw=source/ref["filename"]
    if raw.parent!=source or file_sha256(raw)!=ref["sha256"]: raise ValueError("raw_inventory_binding_mismatch")
    try:
        prepared=prepare_proda_input(json.loads(raw.read_text()),features,
            quantification_method=config.get("analysis_context",{}).get("quantification_method"))
    except ValueError as exc: return {**base,"status":"not_evaluable","reason":str(exc),"source_sha256":ref["sha256"]}
    base.update(source_sha256=ref["sha256"],input_contract={k:v for k,v in prepared.items() if k!="rows"},
        eligible_features=len(prepared["rows"]),feature_scope=len(features))
    expected=config.get("comparison_package_versions",{}).get("proDA")
    executable=shutil.which("Rscript")
    if not executable or not expected:
        return {**base,"status":"not_available","reason":"Rscript_unavailable" if not executable else "proDA_version_not_pinned"}
    destination.mkdir(exist_ok=True,parents=True)
    matrix=destination/"input.tsv"; design=destination/"design.tsv"
    with matrix.open("w") as handle:
        writer=csv.writer(handle,delimiter='\t');writer.writerow(['feature_id']+[f'S{i}' for i in range(len(prepared['units']))])
        for fid,values in sorted(prepared['rows'].items()): writer.writerow([fid]+['NA' if v is None else v for v in values])
    with design.open("w") as handle:
        writer=csv.writer(handle,delimiter='\t');writer.writerow(['sample','condition'])
        for i,unit in enumerate(prepared['units']): writer.writerow([f'S{i}','C'+str(prepared['conditions'].index(unit['condition']))])
    script=Path(__file__).with_name("proda_comparison.R")
    try:
        process=subprocess.run([executable,str(script),str(matrix),str(design),str(destination/'results.tsv'),expected],
            capture_output=True,text=True,timeout=1800,check=False)
    except subprocess.TimeoutExpired:
        return {**base,"status":"timed_out","reason":"proDA_execution_timeout"}
    (destination/'stdout.log').write_text(process.stdout);(destination/'stderr.log').write_text(process.stderr)
    if process.returncode: return {**base,"status":"failed","reason":"proDA_solver_or_version_failure","exit_code":process.returncode}
    records=[]
    for row in csv.DictReader((destination/'results.tsv').open(),delimiter='\t'):
        fid=row['name']
        if fid not in prepared['rows']: raise ValueError("proDA_returned_unknown_feature")
        condition=prepared['conditions'][int(row['condition'][1:])]
        counts={c:sum(v is not None for v,u in zip(prepared['rows'][fid],prepared['units']) if u['condition']==c) for c in ('Control',condition)}
        def number(key):
            try: value=float(row[key]); return value if math.isfinite(value) else None
            except (ValueError,KeyError): return None
        supported=min(counts.values())>0
        records.append({"feature_id":fid,"condition":condition,"model_conditional_effect":number('diff'),
            "effect":number('diff') if supported else None,"standard_error":number('se'),
            "p_value":number('pval'),"q_value":number('adj_pval'),"biological_detection_counts":counts,
            "evaluation_status":"evaluated" if number('diff') is not None else "not_evaluable",
            "reason":None if supported else "all_missing_in_one_condition_model_extrapolation",
            "multiple_testing_family":"features_within_each_condition_contrast"})
    return {**base,"status":"completed","records":records,"package_version":expected,
        "adapter_script_sha256":file_sha256(script),"execution_exit_code":process.returncode}
