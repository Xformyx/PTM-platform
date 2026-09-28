"""Start only the isolated localhost validation services or acceptance clients.

Supply a private environment file; it is never copied to a scientific bundle or log.
No shell code is executed from the file. Only literal KEY=value assignments are read.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import urlparse


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('service',choices=['api','worker','generic','hircb','browser'])
    p.add_argument('--environment-file',type=Path,required=True)
    p.add_argument('--fixture',type=Path);p.add_argument('--output',type=Path);p.add_argument('--inputs',type=Path)
    p.add_argument('--email',default=None);p.add_argument('--port',type=int,default=8000)
    p.add_argument('--order-id',type=int)
    args=p.parse_args();env=dict(os.environ)
    for line in args.environment_file.read_text().splitlines():
        fields=shlex.split(line,comments=True)
        if not fields:continue
        if fields[0]=='export':fields=fields[1:]
        if len(fields)!=1 or '=' not in fields[0]:p.error('Environment file must contain literal KEY=value assignments only')
        key,value=fields[0].split('=',1)
        if not key.isidentifier() or key in {'HOME','CODEX_HOME'}:p.error('Invalid environment key')
        env[key]=value
    for key in ['DATABASE_URL','REDIS_URL','CELERY_BROKER_URL','CELERY_RESULT_BACKEND']:
        if key in env and urlparse(env[key]).hostname not in {'127.0.0.1','localhost'}:
            p.error('Validation services must use only localhost database/broker URLs')
    if not env.get('OUTPUT_DIR') or not env.get('REFERENCE_DIR'):p.error('Explicit isolated output and reference directories are required')
    root=Path(__file__).resolve().parents[1]
    env['PYTHONPATH']=os.pathsep.join(str(root/x) for x in ['','workers','api-server'])
    if args.service=='api':cmd=[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(args.port)]
    elif args.service=='worker':cmd=[sys.executable,'-m','celery','-A','celery_app','worker','-Q','preprocessing','--pool=solo','--concurrency=1','--loglevel=WARNING','--hostname=study-validation']
    else:
        if not args.output:p.error('--output is required')
        if args.email:env['PTM_TEST_EMAIL']=args.email
        if not env.get('PTM_TEST_EMAIL'):p.error('Set PTM_TEST_EMAIL or --email for the isolated test account')
        env['PTM_TEST_PASSWORD']=env.get('PTM_TEST_PASSWORD') or env.get('ADMIN_DEFAULT_PASSWORD','')
        if not env['PTM_TEST_PASSWORD']:p.error('Set PTM_TEST_PASSWORD for the isolated test account')
        script='validate_generic_browser.py' if args.service=='browser' else 'validate_generic_platform.py' if args.service=='generic' else 'validate_hircb_platform.py'
        if args.service=='browser':
            if not args.order_id:p.error('--order-id is required')
            return subprocess.call([sys.executable,str(root/'scripts'/script),'--order-id',str(args.order_id),'--output',str(args.output)],env=env,cwd=root)
        cmd=[sys.executable,str(root/'scripts'/script),'--base-url',f'http://127.0.0.1:{args.port}/api','--output',str(args.output)]
        if args.service=='generic':
            if not args.fixture:p.error('--fixture is required')
            cmd+=['--fixture',str(args.fixture)]
        else:
            if not args.inputs:p.error('--inputs is required')
            cmd+=['--inputs',str(args.inputs),'--reference-preset']
    try:return subprocess.call(cmd,env=env,cwd=root)
    except KeyboardInterrupt:return 130


if __name__=='__main__':raise SystemExit(main())
