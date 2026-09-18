"""Disk-backed exact event sets for the existing co-wave calculation.

Temporary workspace only. Published full records use the immutable JSONL
artifact. No sampling, biological thresholds or wave membership changes.
"""
import json
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path


class TemporalEventSpool:
    def __init__(self, directory):
        self.tmp = TemporaryDirectory(dir=directory, prefix='.event-spool-')
        self.db = sqlite3.connect(str(Path(self.tmp.name)/'events.sqlite'))
        self.db.execute('CREATE TABLE events(collection INTEGER, ordinal INTEGER, identity TEXT, payload TEXT)')
        self.db.execute('CREATE INDEX event_identity ON events(collection,identity)')
        self.counter = 0

    def collection(self):
        self.counter += 1
        return EventRows(self, self.counter)

    def __enter__(self): return self
    def __exit__(self, *args):
        self.db.close()
        self.tmp.cleanup()


class EventRows:
    def __init__(self, store, key):
        self.store, self.key, self.count = store, key, 0

    def append(self, record):
        self.store.db.execute('INSERT INTO events VALUES(?,?,?,?)',
            [self.key,self.count,record['transition_id'],json.dumps(record,sort_keys=True,allow_nan=False)])
        self.count += 1

    def __len__(self): return self.count
    def __iter__(self):
        for (record,) in self.store.db.execute('SELECT payload FROM events WHERE collection=? ORDER BY ordinal',[self.key]):
            yield json.loads(record)

    def examples(self, maximum):
        return [json.loads(r[0]) for r in self.store.db.execute('SELECT payload FROM events WHERE collection=? ORDER BY identity,ordinal LIMIT ?',[self.key,max(0,maximum)])]

    def compare_ids(self, other, dropped_label):
        if self.store is not other.store: raise ValueError('event_spool_scope_mismatch')
        db = self.store.db
        union = db.execute('SELECT count(DISTINCT identity) FROM events WHERE collection IN (?,?) AND instr(identity,?)=0',[self.key,other.key,dropped_label]).fetchone()[0]
        common = db.execute('SELECT count(*) FROM (SELECT DISTINCT identity FROM events WHERE collection=? AND instr(identity,?)=0 INTERSECT SELECT DISTINCT identity FROM events WHERE collection=? AND instr(identity,?)=0)',[self.key,dropped_label,other.key,dropped_label]).fetchone()[0]
        return union, common/union if union else None

    def release(self):
        self.store.db.execute('DELETE FROM events WHERE collection=?',[self.key])
