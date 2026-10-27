"""Bounded session-triggered retention, without idle polling or source indexing."""
from datetime import timedelta
from pathlib import Path
import json,os,sqlite3
from .models import timestamp,utcnow
from .roots import read_config
from .store import Store,StateUnavailable

SOFT=32*1024*1024
HARD=64*1024*1024
RESERVE=128*1024

def usage_bytes(root):
    directory=Path(root)/'.nebula'
    if directory.is_symlink(): raise StateUnavailable('symlinked nebula state')
    total=0; scanned=0; pending=[directory]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                scanned+=1
                if scanned>10000 or entry.is_symlink(): raise StateUnavailable('unbounded or symlinked nebula storage')
                # SQLite deletes -wal/-shm when the last connection closes, so an
                # entry can vanish mid-scan; that is not a full or broken store.
                try:
                    if entry.is_dir(follow_symlinks=False): pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False): total+=entry.stat(follow_symlinks=False).st_size
                    elif os.path.lexists(entry.path): raise StateUnavailable('unsupported nebula state entry')
                except FileNotFoundError: continue
    return total

def capacity_state(root):
    try: total=usage_bytes(root)
    except (OSError,StateUnavailable): return 'hard-limit'
    return 'hard-limit' if total>=HARD else 'soft-limit' if total>=SOFT else 'normal'

def ensure_capacity(root,*,essential=False):
    try: total=usage_bytes(root)
    except OSError as exc: raise StateUnavailable('nebula storage unavailable') from exc
    if total>=HARD-(16*1024 if essential else RESERVE): raise StateUnavailable('nebula storage limit reached; learning withheld')

def prune(store,now):
    current=timestamp(now)
    raw_cutoff=(current-timedelta(days=14)).isoformat()
    sample_cutoff=(current-timedelta(days=90)).isoformat()
    db=store.connection
    db.execute('DELETE FROM events WHERE julianday(timestamp)<julianday(?)',(raw_cutoff,))
    db.execute('DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY timestamp DESC,id DESC LIMIT -1 OFFSET 10000)')
    db.execute('DELETE FROM receipts WHERE event_id NOT IN (SELECT id FROM events)')
    db.execute('DELETE FROM samples WHERE julianday(timestamp)<julianday(?)',(sample_cutoff,))
    db.execute('DELETE FROM sample_provenance WHERE NOT EXISTS (SELECT 1 FROM samples s WHERE s.lesson_id=sample_provenance.lesson_id AND s.version=sample_provenance.version AND s.episode_id=sample_provenance.episode_id)')
    db.execute('DELETE FROM audit WHERE julianday(timestamp)<julianday(?)',(sample_cutoff,))
    db.execute('DELETE FROM audit WHERE id IN (SELECT id FROM audit ORDER BY id DESC LIMIT -1 OFFSET 10000)')
    db.execute("DELETE FROM meta WHERE key LIKE 'feedback:%' AND substr(key,10) NOT IN (SELECT id FROM events)")
    # Completed applications expire after 90 days. Keep live claims and explicit
    # decision overrides so expiry cannot cause an interrupted or refused action.
    for row in db.execute('SELECT lesson_id,version,session_id,episode_id,data FROM applications').fetchall():
        data=json.loads(row['data'])
        if data['status']!='claimed' and 'feedback_verdict' not in data and timestamp(data['timestamp'])<timestamp(sample_cutoff):
            db.execute('DELETE FROM applications WHERE lesson_id=? AND version=? AND session_id=? AND episode_id=?',tuple(row[:4]))
    for row in db.execute('SELECT id,data FROM suggestions').fetchall():
        active=store.connection.execute("SELECT 1 FROM confirmations WHERE json_extract(data,'$.suggestion_id')=?",(row['id'],)).fetchone()
        if not active and timestamp(json.loads(row['data'])['created_at'])<timestamp(sample_cutoff):
            db.execute('DELETE FROM suggestions WHERE id=?',(row['id'],))
    return {'raw_cutoff':raw_cutoff,'sample_cutoff':sample_cutoff}

def maintain(root,*,now,blocking=True):
    """Prune and checkpoint. Non-blocking runs (from hooks) use a PASSIVE
    checkpoint and skip VACUUM, so they never hold other writers back."""
    root=Path(root).resolve(); timestamp(now)
    with Store(root) as store:
        before=store.status()
        with store.transaction():
            cutoffs=prune(store,now)
            store.set_meta('last-maintenance',now)
        after=store.status()
        mode='TRUNCATE' if blocking else 'PASSIVE'
        checkpoint=tuple(store.connection.execute(f'PRAGMA wal_checkpoint({mode})').fetchone())
        compacted=False
        pages=store.connection.execute('PRAGMA page_count').fetchone()[0]
        free=store.connection.execute('PRAGMA freelist_count').fetchone()[0]
        if blocking and free>256 and free>pages//4 and checkpoint[0]==0:
            try:
                store.connection.execute('VACUUM'); compacted=True
                checkpoint=tuple(store.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
            except sqlite3.OperationalError: pass
    return {'before':before,'after':after,**cutoffs,'checkpoint':checkpoint,'compacted':compacted,'bytes':usage_bytes(root),'state':capacity_state(root)}

def session_maintenance(root,session_id):
    with Store(root) as store:
        seen=store.get_meta('maintenance-sessions',[])
        soft=capacity_state(root)=='soft-limit'
        if session_id in seen and not soft: return
    # Near the storage limit, reclaiming space is worth briefly blocking writers.
    maintain(root,now=utcnow(),blocking=soft)
    with Store(root) as store:
        with store.transaction():
            seen=store.get_meta('maintenance-sessions',[])
            store.set_meta('maintenance-sessions',(seen+[session_id])[-128:])

def health(root):
    result={'usable':False,'capacity':capacity_state(root)}
    try:
        config=read_config(root)
        with Store(root) as store:
            integrity=store.connection.execute('PRAGMA quick_check').fetchone()[0]
            result.update({'integrity':integrity,'schema':2,'enabled':config['enabled'],'mode':config['mode'],'bytes':usage_bytes(root),
                           'writable':os.access(store.path,os.W_OK),'evidence_completeness':'validated sample records and independent confirmation snapshots; raw evidence may expire'})
            result['usable']=integrity=='ok' and result['writable'] and result['capacity']!='hard-limit'
    except (OSError,ValueError,sqlite3.Error,StateUnavailable) as exc: result['diagnostic']=str(exc)
    return result
