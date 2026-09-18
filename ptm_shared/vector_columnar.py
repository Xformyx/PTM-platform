"""Derived Parquet index for view queries; original TSV remains authoritative.

Float64 and null masks are retained. Display aggregates never feed analysis.
"""
import csv
import fcntl
import hashlib
import json
import os
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from .vector_plot import project_plot_row, measurement_signature, normalize_plot_records
from .report_revision import file_sha256, _atomic_json
from .analysis_universe import signature
from .tabular_import import validate_tabular_header

VERSION = "vector_columnar.v2"
AXIS_COLUMNS = {"adjusted":"a", "unadjusted":"u", "protein":"p"}


def point_in_polygon(x, y, vertices):
    """Even/odd lasso membership in float64 source coordinates; boundary included."""
    inside = False
    a = vertices[-1]
    for b in vertices:
        cross = (x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        if cross == 0 and min(a[0],b[0]) <= x <= max(a[0],b[0]) and min(a[1],b[1]) <= y <= max(a[1],b[1]):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
        a = b
    return inside


def publish_vector_columnar(directory, suffix):
    root = Path(directory)
    with (root/f"vector_columnar{suffix}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _publish_vector_columnar(directory, suffix)


def _publish_vector_columnar(directory, suffix):
    import duckdb
    root = Path(directory)
    source = next((root/name for name in (f"ptm_vector_data_normalized{suffix}.tsv", f"ptm_vector_data_with_motifs{suffix}.tsv") if (root/name).is_file()), None)
    if source is None: return None
    digest = file_sha256(source)
    destination = root/f"vector_{digest}_{VERSION}.parquet"
    manifest_path = root/f"vector_columnar{suffix}.json"
    if not destination.exists():
        with TemporaryDirectory(dir=root) as temporary:
            tmp = Path(temporary)
            with source.open(encoding="utf-8", newline="") as stream, (tmp/"projected.jsonl").open("w") as output:
                reader = csv.DictReader(stream, delimiter="\t")
                validate_tabular_header(reader.fieldnames)
                for raw in reader:
                    malformed = None in raw or any(v is None for v in raw.values())
                    if malformed:
                        row = {"feature_id":None, "condition":None, "source_row_lineage":[{"line":reader.line_num}], "quarantine_reason":"malformed_source_row", "source_record":{"fields":list(raw.items())}}
                    else:
                        raw["source_row_lineage"] = [{"artifact":source.name,"revision":"vector-sha256:"+digest,"line":reader.line_num}]
                        row = project_plot_row(raw)
                        row["source_record"] = raw
                    record = {"feature_id":row.get("feature_id"), "condition":row.get("condition"), "source_line":reader.line_num,
                              "time_minutes":row.get("time_minutes"), "measurement_hash":signature(measurement_signature(row)), "record_json":json.dumps(row,sort_keys=True),
                              "a":row.get("ptm_protein_adjusted_log2fc"), "u":row.get("ptm_unadjusted_log2fc"), "p":row.get("protein_log2fc"),
                              "denovo":bool(row.get("conventional_log2fc_na")), "malformed":malformed}
                    for axis, col in AXIS_COLUMNS.items():
                        if row.get("axis_eligibility",{}).get(axis,{}).get("eligible") is False: record[col] = None
                    output.write(json.dumps(record,allow_nan=False)+"\n")
            with duckdb.connect(config={"threads": 1, "memory_limit": os.getenv("VECTOR_INDEX_MEMORY_LIMIT", "512MB"), "temp_directory": str(tmp/"spill")}) as db:
                # Stream wide provenance strings to row groups without a global
                # sort/materialized table. All query ordering uses stable IDs.
                db.execute("SET preserve_insertion_order=false")
                db.execute("COPY (SELECT * FROM read_json($1, format='newline_delimited', columns={feature_id:'VARCHAR',condition:'VARCHAR',source_line:'BIGINT',time_minutes:'DOUBLE',measurement_hash:'VARCHAR',record_json:'VARCHAR',a:'DOUBLE',u:'DOUBLE',p:'DOUBLE',denovo:'BOOLEAN',malformed:'BOOLEAN'})) TO $2 (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 2048)", [str(tmp/"projected.jsonl"), str(tmp/"data.parquet")])
            if file_sha256(source) != digest:
                raise ValueError("source_changed_during_columnar_publication")
            (tmp/"data.parquet").replace(destination)
    manifest = {"schema_version":VERSION,"measurement_revision":"vector-sha256:"+digest,
                "source_name":source.name,"source_sha256":digest,"filename":destination.name,"sha256":file_sha256(destination)}
    _atomic_json(manifest_path,manifest)
    return manifest


class VectorColumnar:
    def __init__(self, directory, suffix):
        import duckdb
        self.root = Path(directory)
        self.manifest = json.loads((self.root/f"vector_columnar{suffix}.json").read_text())
        if self.manifest["schema_version"] != VERSION: raise ValueError("columnar_schema_incompatible")
        path = self.root/self.manifest["filename"]
        if path.parent != self.root: raise ValueError("invalid_columnar_path")
        self.db = duckdb.connect(config={"threads":1})
        self.db.read_parquet(str(path)).create_view("observations")
        # Conflict withholding is axis-independent and includes statistics/units.
        self.db.execute("CREATE VIEW cells AS SELECT feature_id, condition, count(*) AS source_rows, count(DISTINCT measurement_hash)>1 AS conflict, CASE WHEN count(DISTINCT measurement_hash)=1 THEN max(a) END AS a, CASE WHEN count(DISTINCT measurement_hash)=1 THEN max(u) END AS u, CASE WHEN count(DISTINCT measurement_hash)=1 THEN max(p) END AS p FROM observations WHERE feature_id IS NOT NULL GROUP BY feature_id, condition")

    def close(self): self.db.close()

    def manifest_counts(self):
        row = self.db.execute("SELECT count(*), count(DISTINCT feature_id), count(*) FILTER (WHERE feature_id IS NULL), count(*) FILTER (WHERE malformed) FROM observations").fetchone()
        from .plot_selection import ordered_conditions
        conditions=ordered_conditions([{"condition":r[0],"time_minutes":r[1]} for r in self.db.execute("SELECT DISTINCT condition,time_minutes FROM observations WHERE condition IS NOT NULL").fetchall()])
        return {"source_rows":row[0],"identified_features":row[1],"identity_unresolved_rows":row[2]-row[3],"malformed_source_rows":row[3],"measurement_revision":self.manifest["measurement_revision"],"conditions":conditions}

    def selection_statistics(self, axis):
        col=AXIS_COLUMNS[axis]
        count,mean,sd=self.db.execute(f"SELECT count(DISTINCT feature_id),avg(abs({col})),stddev_pop(abs({col})) FROM cells WHERE {col} IS NOT NULL").fetchone()
        threshold=mean+2*sd if mean is not None else None
        suggested=self.db.execute(f"SELECT count(DISTINCT feature_id) FROM cells WHERE abs({col})>=?",[threshold]).fetchone()[0] if threshold is not None else 0
        return {"axis_eligible_feature_count":count,"threshold":threshold,"feature_count":suggested}

    def select_ids(self, *, mode, n, axis):
        col = AXIS_COLUMNS[axis]
        if mode not in {"per_condition_top_n", "global_top_n", "all_observed"}:
            raise ValueError("unsupported_columnar_selection")
        if mode != "all_observed" and (isinstance(n, bool) or not isinstance(n, int) or n < 1):
            raise ValueError("top_n_must_be_positive_integer")
        if mode == "per_condition_top_n":
            sql = f"SELECT DISTINCT feature_id FROM (SELECT feature_id,row_number() OVER (PARTITION BY condition ORDER BY abs({col}) DESC,feature_id) AS rank FROM cells WHERE {col} IS NOT NULL) WHERE rank <= ? ORDER BY feature_id"
            params = [n]
        elif mode == "global_top_n":
            sql = f"SELECT feature_id FROM cells WHERE {col} IS NOT NULL GROUP BY feature_id ORDER BY max(abs({col})) DESC,feature_id LIMIT ?"
            params = [n]
        else:
            sql, params = f"SELECT DISTINCT feature_id FROM cells WHERE {col} IS NOT NULL ORDER BY feature_id", []
        result = self.db.execute(sql, params).fetchmany(10001)
        if len(result) > 10000:
            raise ValueError("selection_requires_paginated_trajectory_view")
        return [r[0] for r in result]

    def distribution(self, *, axis="adjusted", bins=64):
        col = AXIS_COLUMNS[axis]
        if not 2 <= bins <= 256: raise ValueError("invalid_distribution_bins")
        rows = self.db.execute(f"SELECT min({col}),max({col}),count(*) FROM cells WHERE {col} IS NOT NULL").fetchone()
        if not rows[2]: return {"bins":[],"count":0,"bounds":None}
        low, high, count = rows
        data = self.db.execute(f"SELECT condition,least(?,floor(({col}-?)/?*?))::INTEGER AS bin,count(*) FROM cells WHERE {col} IS NOT NULL GROUP BY 1,2 ORDER BY 1,2", [bins-1,low,max(high-low,1e-12),bins]).fetchall()
        features=self.db.execute(f"SELECT count(DISTINCT feature_id) FROM cells WHERE {col} IS NOT NULL").fetchone()[0]
        return {"bins":[{"condition":c,"bin":b,"count":n} for c,b,n in data],"count":count,"eligible_features":features,
                "bounds":[low,high],"resolution":bins,"measurement_revision":self.manifest["measurement_revision"]}

    def feature_page(self, *, axis="adjusted", after="", limit=200, search=""):
        if not 1 <= limit <= 1000: raise ValueError("page_limit_must_be_1_to_1000")
        col = AXIS_COLUMNS[axis]
        ids = [r[0] for r in self.db.execute(f"SELECT DISTINCT feature_id FROM cells WHERE {col} IS NOT NULL AND feature_id > ? AND feature_id LIKE ? ORDER BY feature_id LIMIT ?", [after, f"%{search}%", limit+1]).fetchall()]
        return {"feature_ids":ids[:limit], "next_cursor":ids[limit-1] if len(ids)>limit else None, "measurement_revision":self.manifest["measurement_revision"]}

    def trajectories(self, feature_ids):
        if len(feature_ids)>1000: raise ValueError("trajectory_request_requires_pagination")
        if not feature_ids: return []
        rows = [json.loads(r[0]) for r in self.db.execute("SELECT record_json FROM observations WHERE feature_id IN (SELECT unnest(?)) ORDER BY feature_id,condition,source_line", [feature_ids]).fetchall()]
        return normalize_plot_records(rows)

    def diagnostics(self, *, kind="identity_unresolved", after=0, limit=200):
        """Raw row cursor, not a fabricated continuous feature for unresolved IDs."""
        if not 1 <= limit <= 1000: raise ValueError("page_limit_must_be_1_to_1000")
        predicates={"identity_unresolved":"feature_id IS NULL", "malformed_source_row":"malformed",
                    "conflicting_feature_condition":"(feature_id,condition) IN (SELECT feature_id,condition FROM cells WHERE conflict)"}
        if kind not in predicates: raise ValueError("unsupported_diagnostic_kind")
        predicate=predicates[kind]
        count=self.db.execute(f"SELECT count(*) FROM observations WHERE {predicate}").fetchone()[0]
        rows=self.db.execute(f"SELECT source_line,record_json FROM observations WHERE {predicate} AND source_line>? ORDER BY source_line LIMIT ?",[after,limit+1]).fetchall()
        return {"unit":"source_row","kind":kind,"count":count,"records":[json.loads(r[1]) for r in rows[:limit]],
                "next_cursor":rows[limit-1][0] if len(rows)>limit else None,"measurement_revision":self.manifest["measurement_revision"]}

    def density(self, *, axis="adjusted", condition=None, bins=64, bounds=None):
        if not 2 <= bins <= 256: raise ValueError("density_bins_must_be_2_to_256")
        col = AXIS_COLUMNS[axis]
        where = f"p IS NOT NULL AND {col} IS NOT NULL" + (" AND condition=?" if condition else "")
        parameters = [condition] if condition else []
        extent = self.db.execute(f"SELECT min(p),max(p),min({col}),max({col}),count(*) FROM cells WHERE {where}", parameters).fetchone()
        if not extent[4]: return {"bins":[],"count":0,"bounds":None,"measurement_revision":self.manifest["measurement_revision"]}
        x0,x1,y0,y1 = bounds or extent[:4]
        dx,dy = max(x1-x0,1e-12),max(y1-y0,1e-12)
        sql = f"SELECT least(?,greatest(0,floor((p-?)/?*?)))::INTEGER AS x, least(?,greatest(0,floor(({col}-?)/?*?)))::INTEGER AS y,count(*) FROM cells WHERE {where} AND p BETWEEN ? AND ? AND {col} BETWEEN ? AND ? GROUP BY 1,2 ORDER BY 1,2"
        tiles = self.db.execute(sql, [bins-1,x0,dx,bins,bins-1,y0,dy,bins,*parameters,x0,x1,y0,y1]).fetchall()
        return {"bins":[{"x":x,"y":y,"count":n} for x,y,n in tiles],"count":sum(t[2] for t in tiles),
                "full_eligible_count":extent[4],"bounds":[x0,x1,y0,y1],"resolution":bins,"measurement_revision":self.manifest["measurement_revision"]}

    def coordinate_page(self, *, axis="adjusted", condition=None, bounds, after="", limit=500, polygon=None):
        col = AXIS_COLUMNS[axis]
        if not 1 <= limit <= 1000: raise ValueError("page_limit_must_be_1_to_1000")
        where = " AND condition=?" if condition else ""
        if polygon is not None:
            import duckdb
            if not 3 <= len(polygon) <= 4096 or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in polygon):
                raise ValueError("lasso_requires_3_to_4096_finite_vertices")
            # Spatial predicate operates on canonical doubles, never density bins.
            try: self.db.remove_function("inside_lasso")
            except duckdb.InvalidInputException: pass  # connection-local UDF may not exist yet
            self.db.create_function("inside_lasso", lambda x,y: point_in_polygon(x,y,polygon), ["DOUBLE","DOUBLE"], "BOOLEAN")
            where += f" AND inside_lasso(p,{col})"
        cursor=json.loads(after) if after else ["", ""]
        rows = self.db.execute(f"SELECT feature_id,condition,p,{col} FROM cells WHERE p BETWEEN ? AND ? AND {col} BETWEEN ? AND ? AND (feature_id,condition) > (?,?){where} ORDER BY feature_id,condition LIMIT ?", [*bounds,*cursor,*([condition] if condition else []),limit+1]).fetchall()
        return {"observations":[{"feature_id":r[0],"condition":r[1],"x":r[2],"y":r[3]} for r in rows[:limit]],
                "next_cursor":json.dumps(list(rows[limit-1][:2])) if len(rows)>limit else None,"measurement_revision":self.manifest["measurement_revision"]}
