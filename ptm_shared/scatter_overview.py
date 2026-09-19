"""Read-only source-row distribution, independent of view selection and RAG.

This is deliberately not a feature catalogue: duplicate/conflicting source rows
remain separate observations. No values from this display enter an estimator.
"""
from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import Lock

from .de_novo_representation import is_control_condition, is_de_novo_representation, sort_conditions
from .feature_identity import canonical_feature_identity, feature_key
from .quantitative_fields import axis_number
from .tabular_import import validate_tabular_header

CONTRACT_VERSION = "source_vector_scatter.v1"
POINT_LIMIT = 2000
BIN_COUNT = 64
_CACHE: OrderedDict = OrderedDict()
_CACHE_LOCK = Lock()


class ScatterSourceChanged(ValueError):
    pass


def source_path(directory, suffix):
    for kind in ("normalized", "with_motifs"):
        path = Path(directory) / f"ptm_vector_data_{kind}{suffix}.tsv"
        if path.is_file():
            return path
    raise FileNotFoundError("source_vector_tsv_unavailable")


def _fingerprint(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _records(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t", strict=True)
        header = next(reader, None)
        validate_tabular_header(header)
        for values in reader:
            yield reader.line_num, dict(zip(header, values)) if len(values) == len(header) else None


def _text(row, *names):
    for name in names:
        if name in row:
            return str(row[name])
    return ""


def _number(row, *names):
    for name in names:
        if name in row:
            try:
                value = float(row[name])
                return value if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None
    return None


def _true(row, *names):
    return any(str(row.get(name, "")).strip().lower() in {"true", "yes", "1"} for name in names)


def _coordinate(row, axis):
    if row is None:
        return "", None, "malformed_source_row"
    condition = _text(row, "Condition", "condition", "Comparison").strip()
    if condition.lower() in {"", "na", "n/a", "nan", "none", "null"}:
        return "", None, "condition_missing"
    if is_control_condition(condition):
        return condition, None, "control_reference_row"
    x = axis_number(row, "protein")
    if x is None:
        return condition, None, "protein_axis_unavailable"
    if axis == "occupancy":
        y = _number(row, "occupancy_logit_delta", "Occupancy_Logit_Delta")
        tier = _text(row, "pair_quality_tier", "Pair_Quality_Tier").strip()
        if y is None or tier not in {"O1", "O2"}:
            return condition, None, "occupancy_ineligible"
    else:
        y = axis_number(row, axis)
        prefix = "PTM_ProteinAdjusted" if axis == "adjusted" else "PTM_Unadjusted"
        low = "ptm_protein_adjusted" if axis == "adjusted" else "ptm_unadjusted"
        absent = any(n is not None and n <= 0 for n in (
            axis_number(row, "unadjusted", "control_n"), axis_number(row, "unadjusted", "treatment_n")))
        if (y is None or is_de_novo_representation(row) or absent
                or _true(row, f"{prefix}_Conventional_Log2FC_NA", f"{low}_conventional_log2fc_na")):
            return condition, None, "ptm_axis_ineligible"
    return condition, (x, y), None


def _point(row, line, xy):
    identity = canonical_feature_identity(row)
    return {"x": xy[0], "y": xy[1], "source_row": line,
            "feature_id": identity["feature_id"],
            "precursor_id": identity["precursor_id"], "charge": identity["precursor_charge"],
            "gene": _text(row, "Gene.Name", "gene", "gene_name"),
            "site": _text(row, "PTM_Position", "position", "site"),
            "protein_group": _text(row, "Protein.Group", "protein_group", "Protein.Ids"),
            "taxon": _text(row, "FASTA_Taxonomy_ID", "fasta_taxonomy_id", "Annotation_Species_Taxonomy_ID"),
            "accession": _text(row, "accession", "FASTA_Accession", "Protein.Ids"),
            "isoform": _text(row, "isoform", "Isoform"),
            "modified_sequence": _text(row, "Modified.Sequence", "modified_sequence"),
            "pair_quality_tier": _text(row, "Pair_Quality_Tier", "pair_quality_tier")}


def _bin(value, minimum, maximum):
    if maximum == minimum:
        return BIN_COUNT // 2
    return min(BIN_COUNT - 1, max(0, int((value - minimum) / (maximum - minimum) * BIN_COUNT)))


def read_scatter_overview(directory, suffix, axis="adjusted"):
    """At most 2,000 points or 64² bins per condition; never a prefix sample."""
    if axis not in {"adjusted", "unadjusted", "occupancy"}:
        raise ValueError("unsupported_scatter_axis")
    path = source_path(directory, suffix)
    before = _fingerprint(path)
    key = (str(path.resolve()), before, axis, CONTRACT_VERSION)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return deepcopy(_CACHE[key])
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    total, represented, unresolved = 0, 0, 0
    reasons, groups = Counter(), {}
    bounds = [math.inf, -math.inf, math.inf, -math.inf]
    for line, row in _records(path):
        total += 1
        condition, xy, reason = _coordinate(row, axis)
        group = None
        if condition and reason != "control_reference_row":
            group = groups.setdefault(condition, {"condition": condition, "source_rows": 0,
                "represented_rows": 0, "excluded_rows": 0, "exclusion_reasons": Counter(),
                "points": [], "bins": [], "mode": "points", "identity_unresolved_rows": 0})
            group["source_rows"] += 1
        if reason:
            reasons[reason] += 1
            if group is not None:
                group["excluded_rows"] += 1
                group["exclusion_reasons"][reason] += 1
            continue
        represented += 1
        group["represented_rows"] += 1
        identity = feature_key(row)
        missing_identity = not (identity[2] or (identity[3] and identity[4]))
        unresolved += int(missing_identity)
        group["identity_unresolved_rows"] += int(missing_identity)
        bounds = [min(bounds[0], xy[0]), max(bounds[1], xy[0]), min(bounds[2], xy[1]), max(bounds[3], xy[1])]
        if group["represented_rows"] <= POINT_LIMIT:
            group["points"].append(_point(row, line, xy))
        elif group["mode"] == "points":
            group["points"].clear()
            group["mode"] = "density"
    dense = {name: Counter() for name, group in groups.items() if group["mode"] == "density"}
    if dense:
        for _, row in _records(path):
            condition, xy, reason = _coordinate(row, axis)
            if reason is None and condition in dense:
                dense[condition][(_bin(xy[0], bounds[0], bounds[1]), _bin(xy[1], bounds[2], bounds[3]))] += 1
        for name, bins in dense.items():
            groups[name]["bins"] = [{"ix": ix, "iy": iy, "count": count} for (ix, iy), count in sorted(bins.items())]
            if sum(bins.values()) != groups[name]["represented_rows"]:
                raise ScatterSourceChanged("source_vector_changed_during_read")
    if _fingerprint(path) != before or source_path(directory, suffix) != path:
        raise ScatterSourceChanged("source_vector_changed_during_read")
    assert total == represented + sum(reasons.values())
    result = {"contract_version": CONTRACT_VERSION, "measurement_revision": "vector-sha256:" + digest.hexdigest(),
        "axis": axis, "unit": "source_vector_row", "source": {"kind": "preprocessing_vector", "filename": path.name,
        "sha256": digest.hexdigest()}, "status": "ready" if represented else "empty_source" if not total else "no_eligible_observations",
        "bounds": bounds if represented else None, "bin_resolution": BIN_COUNT, "point_limit_per_condition": POINT_LIMIT,
        "coverage": {"source_rows": total, "represented_rows": represented, "excluded_rows": sum(reasons.values()),
                     "exclusion_reasons": dict(reasons), "identity_unresolved_represented_rows": unresolved, "sampled_out_rows": 0},
        "conditions": [groups[c] for c in sort_conditions(groups)]}
    with _CACHE_LOCK:
        _CACHE[key] = deepcopy(result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 6:
            _CACHE.popitem(last=False)
    return result
