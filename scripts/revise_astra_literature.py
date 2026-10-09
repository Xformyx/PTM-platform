"""Revise only finding literature/reader artifacts of a validated v6 package.

Uses the already frozen selection and existing RAG/model boundary. No provider
refresh, scientific recomputation, finding reselection, or deployment.
"""
import argparse
import json
from pathlib import Path
from ptm_shared.astra_reader_revision import revise_literature


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--literature-pin',type=Path,help='Explicit replacement pin captured through the existing API service; omitted keeps the archived pin')
    p.add_argument('--refresh-reason',help='Required reason for an explicit literature-only selection revision')
    a=p.parse_args()
    result=revise_literature(a.package,a.output,
        literature_pin=json.loads(a.literature_pin.read_text()) if a.literature_pin else None,
        refresh_reason=a.refresh_reason)
    (a.output/'literature_revision_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'run_id':result['run_id'],'literature':result['analysis_readiness']['literature'],
                      'archive':result['artifacts']['astra']},ensure_ascii=False))


if __name__=='__main__':main()
