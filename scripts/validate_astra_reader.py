"""Round07 validation from frozen scientific tables; no preprocessing/network."""
import argparse
import json
from pathlib import Path
import re
import time

import pandas as pd

from ptm_shared.astra_reader import build_reader_tables, validate_reader, write_reader
from ptm_shared.astra_package import write_tables


def load_inputs(root):
    dictionary=json.loads((root/'reproducibility/data_dictionary.json').read_text())
    names=['quant/summary','quant/comparisons','science/inference_results',
           'reader_adapter/form_identity','reader_adapter/form_contrasts',
           'reader_adapter/precursor_membership','reader_adapter/study_metadata']
    return {name:pd.read_csv(root/(name+'.csv'),float_precision='round_trip',low_memory=False,
        dtype={k:'str' for k,v in dictionary[name+'.csv']['dtypes'].items() if v=='str'}) for name in names}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    tables=load_inputs(args.package)
    snapshot=json.loads((args.package/'study/user_input_snapshot.json').read_text())
    design=json.loads((args.package/'study/study_design.json').read_text())
    start=time.monotonic()
    reader=build_reader_tables(tables,design,snapshot)
    result=validate_reader({**tables,**reader})
    write_tables(reader,args.output);write_reader(args.output,reader)
    missing=[]
    for link in re.findall(r'\]\(([^)]+)\)',(args.output/'reader/READ_ME.md').read_text()):
        if not (args.output/'reader'/link).resolve().exists() and not (args.package/'reader'/link).resolve().exists():missing.append(link)
    if missing:raise ValueError('Reader links missing: '+str(missing))
    packet=json.loads(reader['reader/packet'].iloc[0].packet_json)
    result.update(baseline_run_id=args.package.name,elapsed_seconds=time.monotonic()-start,
                  coverage=packet['coverage_inventory'],links_valid=True,
                  original_questions=packet['original_questions'])
    (args.output/'READER_VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
