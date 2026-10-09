"""Publish a reader-only revision from a validated v6 package's saved tables."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import time
from unittest.mock import patch

from ptm_shared.astra_reader_revision import revise_temporal


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();start=time.monotonic()
    def forbidden(*args,**kwargs):raise AssertionError('Reader revision forbids scientific calculation, retrieval and network')
    # These guards also protect against an accidental future consumer dependency.
    with ExitStack() as stack:
        for name in ['socket.create_connection','urllib.request.urlopen','requests.sessions.Session.request',
                     'ptm_shared.astra_package.compute_science','ptm_shared.astra_package.resolve_sources',
                     'ptm_shared.astra_literature.collect','ptm_shared.astra_reader.build_reader_tables',
                     'ptm_shared.astra_temporal.integrate_temporal','ptm_shared.phosx_activity_adapter.execute']:
            stack.enter_context(patch(name,side_effect=forbidden))
        result=revise_temporal(a.package,a.output)
    print(json.dumps({'run_id':result['run_id'],'artifacts':result['artifacts'],
                      'elapsed_seconds':time.monotonic()-start,'scientific_recalculation':False,'network_requests':0},ensure_ascii=False))


if __name__=='__main__':main()
