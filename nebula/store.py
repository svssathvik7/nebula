"""Transactional local storage. Captured events are evidence, not instructions."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
from .models import Event, Lesson, Sample, Suggestion, dump, load, validate, utcnow, timestamp

class StateUnavailable(RuntimeError): pass

class Store:
    def __init__(self,root,*,create=False):
        self.root=Path(root).resolve()
        self.directory=self.root/'.nebula'
        self.path=self.directory/'state.sqlite3'
        self.connection=None
        if self.directory.is_symlink() or self.path.is_symlink():
            raise StateUnavailable('nebula state must not be a symlink')
        if not create and not self.path.is_file():
            raise StateUnavailable('nebula database missing; refusing to recreate history')
        try:
            self.connection=sqlite3.connect(self.path,timeout=0.1,isolation_level=None)
            self.connection.row_factory=sqlite3.Row
            self.connection.execute('PRAGMA busy_timeout=100')
            if create:
                os.chmod(self.path,0o600)
                self.connection.execute('PRAGMA journal_mode=WAL')
                self._schema()
            version=self.connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (1,2,3): raise StateUnavailable('unsupported or missing nebula schema')
            self._validate_schema(version)
            if version==1: self._migrate_v1()
            if version<3: self._migrate_v2()
            self._validate_schema(3)
            self.schema_version=3
        except (sqlite3.Error,OSError) as exc:
            self.close()
            raise StateUnavailable('nebula database unavailable') from exc
        except (StateUnavailable,ValueError):
            self.close(); raise

    def _schema(self):
        self.connection.executescript('''
        BEGIN;
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE events(id TEXT PRIMARY KEY,digest TEXT NOT NULL,timestamp TEXT NOT NULL,data TEXT NOT NULL);
        CREATE INDEX events_time ON events(timestamp);
        CREATE TABLE receipts(event_id TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE lessons(id TEXT NOT NULL,version INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(id,version));
        CREATE TABLE samples(lesson_id TEXT,version INTEGER,episode_id TEXT,timestamp TEXT,data TEXT NOT NULL,PRIMARY KEY(lesson_id,version,episode_id));
        CREATE INDEX samples_time ON samples(timestamp);
        CREATE TABLE suggestions(id TEXT PRIMARY KEY,lesson_id TEXT,version INTEGER,session_id TEXT,episode_id TEXT,data TEXT NOT NULL);
        CREATE TABLE confirmations(lesson_id TEXT,version INTEGER,data TEXT NOT NULL,PRIMARY KEY(lesson_id,version));
        CREATE TABLE applications(lesson_id TEXT,version INTEGER,session_id TEXT,episode_id TEXT,data TEXT NOT NULL,PRIMARY KEY(lesson_id,version,session_id,episode_id));
        CREATE TABLE installations(project TEXT,host TEXT,data TEXT NOT NULL,PRIMARY KEY(project,host));
        CREATE TABLE audit(id INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE sample_provenance(lesson_id TEXT,version INTEGER,episode_id TEXT,data TEXT NOT NULL,PRIMARY KEY(lesson_id,version,episode_id));
        ''')
        from .analytics.tracking import create_tracking
        create_tracking(self.connection,since=utcnow())
        self.connection.execute('PRAGMA user_version=3')
        self.connection.execute('COMMIT')

    def _validate_schema(self,version):
        expected={'meta':('key','value'),'events':('id','digest','timestamp','data'),
                  'receipts':('event_id','data'),'lessons':('id','version','data'),
                  'samples':('lesson_id','version','episode_id','timestamp','data'),
                  'suggestions':('id','lesson_id','version','session_id','episode_id','data'),
                  'confirmations':('lesson_id','version','data'),
                  'applications':('lesson_id','version','session_id','episode_id','data'),
                  'installations':('project','host','data'),'audit':('id','timestamp','kind','data')}
        if version>=2: expected['sample_provenance']=('lesson_id','version','episode_id','data')
        if version>=3:
            from .analytics.tracking import TABLES
            expected.update(TABLES)
        for name,columns in expected.items():
            info=self.connection.execute(f'PRAGMA table_info({name})').fetchall()
            if tuple(row['name'] for row in info)!=columns or not any(row['pk'] for row in info):
                raise StateUnavailable('nebula schema incomplete: '+name)

    def _migrate_v1(self):
        # Old sample rows are retained but cannot silently become verified
        # provenance. Existing confirmation bindings are reconstructed only
        # where their original receipt and suggestion still agree.
        with self.transaction():
            self.connection.execute('CREATE TABLE sample_provenance(lesson_id TEXT,version INTEGER,episode_id TEXT,data TEXT NOT NULL,PRIMARY KEY(lesson_id,version,episode_id))')
            for row in self.connection.execute('SELECT lesson_id,version,data FROM confirmations').fetchall():
                data=json.loads(row['data']); receipt=self.receipt(data.get('source_event_id',''))
                pending=self.get_suggestion(receipt.get('suggestion_id','')) if receipt else None
                source=self.get_event(data.get('source_event_id',''))
                if pending and source and source.origin=='human' and (pending.lesson_id,pending.version)==(row['lesson_id'],row['version']) and receipt.get('verb')=='accept':
                    data.update({'suggestion_id':pending.suggestion_id,'session_id':pending.session_id,'episode_id':pending.episode_id,'context_digest':pending.context_digest,'host':source.host,'initiator':'human'})
                else: data['legacy_unverified']=True
                self.connection.execute('UPDATE confirmations SET data=? WHERE lesson_id=? AND version=?',(dump(data),row['lesson_id'],row['version']))
            self.connection.execute('PRAGMA user_version=2')

    def _migrate_v2(self):
        from .analytics.tracking import create_tracking
        from .maintenance import ensure_capacity
        ensure_capacity(self.root,essential=True)
        with self.transaction():
            create_tracking(self.connection,since=utcnow())
            self.connection.execute('PRAGMA user_version=3')

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def close(self):
        if self.connection is not None:
            self.connection.close(); self.connection=None

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            yield self; return
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield self
            self.connection.execute('COMMIT')
        except BaseException:
            self.connection.execute('ROLLBACK'); raise

    def put_event(self,value,*,essential=False):
        from .maintenance import ensure_capacity
        ensure_capacity(self.root,essential=essential)
        validate(value)
        with self.transaction():
            old=self.connection.execute('SELECT digest FROM events WHERE id=?',(value.event_id,)).fetchone()
            if old:
                if old['digest']!=value.digest: raise ValueError('event ID reused with different payload')
                return False
            self.connection.execute('INSERT INTO events VALUES(?,?,?,?)',(value.event_id,value.digest,value.timestamp,dump(value)))
            self.trim_event_count()
            return True

    def get_event(self,key):
        row=self.connection.execute('SELECT data FROM events WHERE id=?',(key,)).fetchone()
        return load(Event,row[0]) if row else None

    def put_lesson(self,value,*,essential=False):
        from .maintenance import ensure_capacity
        ensure_capacity(self.root,essential=essential)
        validate(value)
        self.connection.execute('INSERT INTO lessons VALUES(?,?,?) ON CONFLICT(id,version) DO UPDATE SET data=excluded.data',
                                (value.lesson_id,value.version,dump(value)))

    def get_lesson(self,key,version=None):
        if version is None:
            row=self.connection.execute('SELECT data FROM lessons WHERE id=? ORDER BY version DESC LIMIT 1',(key,)).fetchone()
        else: row=self.connection.execute('SELECT data FROM lessons WHERE id=? AND version=?',(key,version)).fetchone()
        return load(Lesson,row[0]) if row else None

    def lessons(self):
        return [load(Lesson,r[0]) for r in self.connection.execute('SELECT data FROM lessons l WHERE version=(SELECT max(version) FROM lessons WHERE id=l.id) ORDER BY id')]

    def put_sample(self,value,*,provenance=None,essential=False):
        from .maintenance import ensure_capacity
        ensure_capacity(self.root,essential=essential)
        validate(value)
        old=self.connection.execute('SELECT data FROM samples WHERE lesson_id=? AND version=? AND episode_id=?',
                                    (value.lesson_id,value.version,value.episode_id)).fetchone()
        if old and old[0]==dump(value): return False
        self.connection.execute('INSERT INTO samples VALUES(?,?,?,?,?) ON CONFLICT(lesson_id,version,episode_id) DO UPDATE SET timestamp=excluded.timestamp,data=excluded.data',
                                (value.lesson_id,value.version,value.episode_id,value.timestamp,dump(value)))
        source=self.get_event(value.source_event_id)
        snapshot=provenance or {'source_digest':source.digest if source else None,'source_timestamp':source.timestamp if source else value.timestamp,'verdict':value.verdict,'outcome':value.outcome,'source':'internal'}
        self.connection.execute('INSERT INTO sample_provenance VALUES(?,?,?,?) ON CONFLICT(lesson_id,version,episode_id) DO UPDATE SET data=excluded.data',(value.lesson_id,value.version,value.episode_id,dump(snapshot)))
        return not bool(old)

    def samples(self,key,version):
        return [load(Sample,r[0]) for r in self.connection.execute('SELECT data FROM samples WHERE lesson_id=? AND version=? ORDER BY episode_id',(key,version))]

    def put_receipt(self,event_id,source,acknowledgement):
        data={'source':source,**(acknowledgement or {})}
        existing=self.receipt(event_id)
        if existing and existing!=data: raise ValueError('receipt cannot be rewritten')
        self.connection.execute('INSERT OR IGNORE INTO receipts VALUES(?,?)',(event_id,dump(data)))

    def receipt(self,key):
        row=self.connection.execute('SELECT data FROM receipts WHERE event_id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def audit(self,kind,data):
        self.connection.execute('INSERT INTO audit(timestamp,kind,data) VALUES(?,?,?)',(utcnow(),kind,dump(data)))

    def set_meta(self,key,value):
        self.connection.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,dump(value)))

    def get_meta(self,key,default=None):
        row=self.connection.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def status(self):
        return {name:self.connection.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                for name in ('events','lessons','samples','suggestions','confirmations','applications')}

    def confirmation(self,key,version):
        row=self.connection.execute('SELECT data FROM confirmations WHERE lesson_id=? AND version=?',(key,version)).fetchone()
        return json.loads(row[0]) if row else None

    def confirmed(self,key,version):
        value=self.confirmation(key,version)
        return value is not None and not value.get('legacy_unverified',False)

    def get_suggestion(self,key):
        row=self.connection.execute('SELECT data FROM suggestions WHERE id=?',(key,)).fetchone()
        return load(Suggestion,row[0]) if row else None

    def put_suggestion(self,value,*,essential=False):
        from .maintenance import ensure_capacity
        ensure_capacity(self.root,essential=essential)
        validate(value)
        self.connection.execute('INSERT INTO suggestions VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                                (value.suggestion_id,value.lesson_id,value.version,value.session_id,value.episode_id,dump(value)))

    def pending_suggestions(self,session_id):
        values=[load(Suggestion,r[0]) for r in self.connection.execute('SELECT data FROM suggestions WHERE session_id=? ORDER BY id',(session_id,))]
        return [v for v in values if v.status=='pending']

    def application(self,key,version,session_id,episode_id):
        row=self.connection.execute('SELECT data FROM applications WHERE lesson_id=? AND version=? AND session_id=? AND episode_id=?',
                                    (key,version,session_id,episode_id)).fetchone()
        return json.loads(row[0]) if row else None

    def feedback_history(self,key,version,*,exceptions_only=False):
        field = 'exception_history' if exceptions_only else 'feedback_history'
        if exceptions_only:
            clause = "json_array_length(data,'$.exception_history')>0 OR json_extract(data,'$.feedback_verdict')='exception'"
        else:
            clause = "json_extract(data,'$.feedback_verdict') IS NOT NULL"
        # The clause is selected above; record identities and JSON paths are bound.
        query = f"""
            SELECT session_id,episode_id,data FROM applications
            WHERE lesson_id=? AND version=? AND ({clause})
            ORDER BY COALESCE(
                (SELECT max(julianday(json_extract(j.value,'$.source_timestamp')))
                 FROM json_each(data,?) j),
                julianday(json_extract(data,'$.source_timestamp'))
            ) DESC,session_id,episode_id
            LIMIT 6
        """
        rows = self.connection.execute(query,(key,version,'$.'+field)).fetchall()
        records = {}
        for row in rows:
            data = json.loads(row['data'])
            entries = data.get(field)
            if entries is None:
                entries = [{**data, 'project': data.get('feedback_project', data['project'])}]
            elif not exceptions_only:
                entries = entries + data.get('exception_history', [])
            for entry in entries:
                identity = (entry['source_event_id'], entry['feedback_verdict'])
                records[identity] = {**entry, 'session_id': row['session_id'],
                                     'episode_id': row['episode_id']}
        return sorted(records.values(), key=lambda e: timestamp(e['source_timestamp']), reverse=True)[:6]

    def installation(self,project,host):
        row=self.connection.execute('SELECT data FROM installations WHERE project=? AND host=?',(project,host)).fetchone()
        return json.loads(row[0]) if row else None

    def sample_provenance(self,key,version,episode_id):
        row=self.connection.execute('SELECT data FROM sample_provenance WHERE lesson_id=? AND version=? AND episode_id=?',(key,version,episode_id)).fetchone()
        return json.loads(row[0]) if row else None

    def bound_raw_events(self,now):
        from datetime import timedelta
        cutoff=(timestamp(now)-timedelta(days=14)).isoformat()
        self.connection.execute('DELETE FROM events WHERE timestamp<?',(cutoff,))
        self.trim_event_count()
        self.connection.execute('DELETE FROM receipts WHERE event_id NOT IN (SELECT id FROM events)')

    def trim_event_count(self):
        count=self.connection.execute('SELECT count(*) FROM events').fetchone()[0]
        if count>10000:
            self.connection.execute('DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY timestamp,id LIMIT ?)',(count-10000,))
            self.connection.execute('DELETE FROM receipts WHERE event_id NOT IN (SELECT id FROM events)')
