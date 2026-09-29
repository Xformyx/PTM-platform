"""Validate and replay a downloaded Astra package with outbound sockets disabled.

Run with the chosen Python environment. Neither the repository engine nor a
server registry is imported: only the downloaded package's bundled code is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import socket
import sys
import time
import urllib.request
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    bundle=args.output/'package';bundle.mkdir();bundle=bundle.resolve()
    with zipfile.ZipFile(args.archive) as archive:
        for name in archive.namelist():
            if not (bundle/name).resolve().is_relative_to(bundle):raise ValueError('Unsafe archive path')
        if archive.testzip():raise ValueError('Archive CRC failure')
        archive.extractall(bundle)
    attempts=[]
    def blocked(*args,**kwargs):
        attempts.append('outbound_request')
        raise RuntimeError('Network disabled for independent replay')
    socket.create_connection=blocked
    socket.socket.connect=blocked
    socket.socket.connect_ex=blocked
    urllib.request.urlopen=blocked
    sys.path.insert(0,str(bundle/'reproducibility/code'))
    from ptm_shared.astra_package import replay_package
    import numpy,pandas
    start=time.monotonic();replay_package(bundle,args.output/'recomputed')
    result=json.loads((args.output/'recomputed/replay_result.json').read_text())
    result.update(python=platform.python_version(),numpy=numpy.__version__,pandas=pandas.__version__,
        elapsed_seconds=time.monotonic()-start,network_attempts=len(attempts),
        archive_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        engine_source='downloaded_archive/reproducibility/code; repository_engine_not_imported')
    if attempts:raise AssertionError('Replay attempted network access')
    (args.output/'validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='tables'},indent=2))


if __name__=='__main__':main()
