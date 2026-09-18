"""Derived cursor index for a completed analysis; never a scoring input."""
import json
from pathlib import Path
import duckdb


def write_inventory_indexes(directory, manifest):
    root=Path(directory)
    definitions=(('feature_inventory',((r['feature_id'],'',r['candidate_status'],r) for r in manifest['inventory'])),
        ('candidate_memberships',((m['key'],k['canonical'],'mapped',m) for k in manifest['candidate_modules'] for m in k['members'])))
    for name,records in definitions:
        source=root/f'{name}.jsonl'
        with source.open('x') as stream:
            for fid,kinase,status,record in records:
                stream.write(json.dumps({'feature_id':fid,'kinase':kinase,'status':status,'record_json':json.dumps(record,allow_nan=False)},allow_nan=False)+'\n')
        with duckdb.connect(config={'threads':1,'memory_limit':'512MB','temp_directory':str(root/'index-spill')}) as db:
            if source.stat().st_size:
                db.read_json(str(source),format='newline_delimited',columns={'feature_id':'VARCHAR','kinase':'VARCHAR','status':'VARCHAR','record_json':'VARCHAR'}).create_view('records')
            else:
                db.execute('CREATE TABLE records(feature_id VARCHAR,kinase VARCHAR,status VARCHAR,record_json VARCHAR)')
            db.execute("COPY records TO ? (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 2048)",[str(root/f'{name}.parquet')])


def inventory_page(directory, *, kind='features', kinase=None, status=None, after='', limit=100):
    if kind not in {'features','members'} or not 1 <= limit <= 1000:
        raise ValueError('invalid_inventory_page')
    if kind=='members' and not kinase: raise ValueError('member_page_requires_kinase')
    name='feature_inventory' if kind=='features' else 'candidate_memberships'
    with duckdb.connect(config={'threads':1}) as db:
        db.read_parquet(str(Path(directory)/f'{name}.parquet')).create_view('records')
        clauses=[];params=[]
        for field,value in (('kinase',kinase),('status',status)):
            if value is not None: clauses.append(f'{field}=?');params.append(value)
        where=' AND '.join(clauses) or 'TRUE'
        count=db.execute(f'SELECT count(*) FROM records WHERE {where}',params).fetchone()[0]
        rows=db.execute(f'SELECT feature_id,record_json FROM records WHERE {where} AND feature_id>? ORDER BY feature_id LIMIT ?',[*params,after,limit+1]).fetchall()
        return {'records':[json.loads(r[1]) for r in rows[:limit]],'count':count,'unit':'feature',
                'next_cursor':rows[limit-1][0] if len(rows)>limit else None}
