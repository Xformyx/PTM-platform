"""Read progress from an isolated validation API; prints no credentials."""
import argparse,json,os,httpx
from urllib.parse import urlparse
p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--order-id',type=int,required=True);p.add_argument('--output');p.add_argument('--cancel',action='store_true');a=p.parse_args()
if urlparse(a.base_url).hostname!='127.0.0.1':p.error('localhost only')
c=httpx.Client(base_url=a.base_url);r=c.post('/auth/login',json={'email':os.environ['PTM_TEST_EMAIL'],'password':os.environ['PTM_TEST_PASSWORD']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token']
r=c.get('/orders/'+str(a.order_id));r.raise_for_status();v=r.json();print(json.dumps({k:v.get(k) for k in ['id','status','current_stage','stage_detail','progress_pct','error_message']},ensure_ascii=False))

if a.cancel:
    if not str(v.get('order_code','')).startswith(('HIRcB_followup_','Generic_')):raise ValueError('Only named validation fixtures may be cancelled')
    response=c.post('/orders/'+str(a.order_id)+'/cancel');response.raise_for_status();print('Validation fixture cancelled')
