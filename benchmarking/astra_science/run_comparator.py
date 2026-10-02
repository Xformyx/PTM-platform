"""Run a declared external comparator without importing benchmark labels in production.

This process adapter preserves native outputs. It does NOT implement or certify
KSEA/PTM-SEA/PhosX/KSTAR. The caller supplies the real, licensed pinned tool and
method-specific input conversion; unavailable resources produce an explicit record.
"""
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from .evaluate import PROTOCOL


def run(contract,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    if contract['method'] not in PROTOCOL['comparators']:raise ValueError('Unknown comparator')
    required=['code_pin','resource_pin','command','input_conversion_version','native_output_semantics','support_domain']
    missing=[field for field in required if not contract.get(field)]
    files=contract.get('files',[])
    for item in files:
        path=Path(item['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:missing.append('missing_or_changed_'+item['role'])
    record={'method':contract['method'],'contract':contract,'status':'not_run_pinned_implementation_or_resource_unavailable','missing':missing}
    if not missing:
        if not isinstance(contract['command'],list) or not all(isinstance(v,str) for v in contract['command']):raise ValueError('Command must be an argv array, never shell text')
        started=time.monotonic()
        with (output/'stdout.log').open('wb') as out,(output/'stderr.log').open('wb') as err:
            try:
                result=subprocess.run(contract['command'],cwd=output,stdout=out,stderr=err,timeout=contract.get('timeout_seconds',3600),shell=False)
                record.update(status='native_process_completed_requires_output_validation' if result.returncode==0 else 'failed',exit_code=result.returncode)
            except subprocess.TimeoutExpired:record.update(status='timeout')
        record['elapsed_seconds']=time.monotonic()-started
    record['official_parity']='not_certified_by_process_adapter'
    (output/'execution.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False))
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--contract',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(json.loads(args.contract.read_text()),args.output),indent=2))


if __name__=='__main__':main()
