"""Account for TSV records and preserve physical locators without numeric edits."""
import csv
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from .report_revision import file_sha256, _atomic_json


def validate_tabular_header(header):
    if not header or any(not str(name).strip() for name in header) or len(set(header)) != len(header):
        raise ValueError('ambiguous_source_header')


def read_quantitative_tsv(path, output_dir):
    import pandas as pd
    path, root = Path(path), Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    digest = file_sha256(path)
    name = f"import_{digest}.quarantine.jsonl"
    quarantine_path = root/name
    source_count = parsed_count = malformed_count = 0
    locators, parse_failure = [], None
    with NamedTemporaryFile(mode="w+", encoding="utf-8", newline="", suffix=".tsv") as cleaned:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as quarantine:
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.reader(stream, delimiter="\t", strict=True)
                writer = csv.writer(cleaned, delimiter="\t")
                previous_line = 0
                try:
                    header = next(reader)
                    validate_tabular_header(header)
                    previous_line = reader.line_num
                    writer.writerow(header)
                    for row in reader:
                        source_count += 1
                        locator = {"start_line":previous_line+1,"end_line":reader.line_num}
                        previous_line = reader.line_num
                        if len(row) != len(header):
                            malformed_count += 1
                            quarantine.write(json.dumps({"source_sha256":digest, **locator,
                                "reason":"malformed_source_row", "raw_fields":row}, ensure_ascii=False)+"\n")
                        else:
                            parsed_count += 1
                            locators.append(locator)
                            writer.writerow(row)
                except (csv.Error, StopIteration, UnicodeError, ValueError) as exc:
                    parse_failure = "ambiguous_source_header" if str(exc)=='ambiguous_source_header' else "unrecoverable_tsv_parse_failure"
                    quarantine.write(json.dumps({"source_sha256":digest,"start_line":previous_line+1,
                        "end_line":reader.line_num,"reason":parse_failure,"unparsed_suffix_retained_in_source":True})+"\n")
        cleaned.flush()
        frame = None if parse_failure else pd.read_csv(cleaned.name, sep="\t", low_memory=False)
    if quarantine_path.exists():
        if file_sha256(quarantine_path) != file_sha256(quarantine.name):
            raise ValueError("immutable_quarantine_conflict")
        os.unlink(quarantine.name)
    else:
        os.replace(quarantine.name, quarantine_path)
    audit = {"schema_version":"tabular_import.v1", "source_sha256":digest,
        "execution_status":"failed" if parse_failure else "completed", "failure_reason":parse_failure,
        "source_rows":None if parse_failure else source_count, "parsed_rows":parsed_count,
        "quarantined_rows":malformed_count, "quarantine_artifact":name,"quarantine_sha256":file_sha256(quarantine_path)}
    _atomic_json(root/f"import_{digest}.json", audit)
    if parse_failure: raise ValueError(parse_failure)
    frame.attrs.update(source_row_locators=locators, import_accounting=audit)
    return frame
