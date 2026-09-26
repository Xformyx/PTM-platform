"""Produce an offline report-compatible evidence bundle from explicit inputs."""
import argparse
import json
from pathlib import Path
import pandas as pd

from ptm_shared.report_compatible_quantification import quantify_forms, read_fasta
from ptm_shared.report_compatible_kinase import frozen_edges, score_footprints
from ptm_shared.report_compatible_extensions import extend_and_export, file_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['pr','pg','fasta','snapshot','samples','output']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--snapshot-sha256', required=True)
    parser.add_argument('--baseline-time', type=float, default=0)
    parser.add_argument('--reference-dir', type=Path)
    args = parser.parse_args()
    if file_digest(args.snapshot) != args.snapshot_sha256:
        parser.error('Frozen snapshot SHA-256 mismatch')
    analysis = quantify_forms(pd.read_csv(args.pr,sep='\t'), pd.read_csv(args.pg,sep='\t'), read_fasta(args.fasta),
        json.loads(args.samples.read_text()), args.baseline_time)
    mappings, edges = frozen_edges(analysis, pd.read_csv(args.snapshot,sep='\t'))
    kinase = score_footprints(analysis, edges)
    result = extend_and_export(analysis,mappings,edges,kinase,args.output,
        {'PR':args.pr,'PG':args.pg,'FASTA':args.fasta,'snapshot':args.snapshot}, args.reference_dir)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
