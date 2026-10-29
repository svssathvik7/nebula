"""Bounded advisory capture; no model calls and no tool authorization decisions."""
import json
import os
import random
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .models import Event, digest, utcnow, validate
from .roots import resolve_context, read_config
from .store import Store, StateUnavailable
from .adapters import claude, codex

EVENTS={'SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','PostToolUseFailure','Stop','SessionEnd'}
HOOK_BUSY_TIMEOUT_MS=500
MAINTENANCE_BUSY_TIMEOUT_MS=100
CAPTURE_ATTEMPT_TIMEOUT_MS=50
CAPTURE_DEADLINE_MS=750

def normalize(host,payload,*,now):
    if host not in ('claude','codex') or not isinstance(payload,dict): return None
    kind=payload.get('hook_event_name')
    session=payload.get('session_id')
    cwd=payload.get('cwd')
    if kind not in EVENTS or not isinstance(session,str) or not session or not isinstance(cwd,str): return None
    turn=payload.get('turn_id') or payload.get('tool_use_id') or ''
    if not isinstance(turn,str): return None
    # Tool-use identifiers are not decision episodes; without a turn ID the
    # active skill supplies episode grouping when it records a lesson sample.
    episode=payload.get('turn_id') or session
    if not isinstance(episode,str): return None
    episode='ep-'+digest([host,session,episode])[:32]
    source=(claude if host=='claude' else codex).origin(payload)
    hint=kind
    if kind in ('PreToolUse','PostToolUse','PostToolUseFailure'):
        name=payload.get('tool_name','unknown')
        hint=f'{kind}: {str(name)[:80]}'
        response=payload.get('tool_response')
        if isinstance(response,dict) and type(response.get('exit_code')) is int:
            hint+=f" exit_code={response['exit_code']}"
    fingerprint=digest({'host':host,'payload':payload})
    value=Event(f'ev-{fingerprint[:32]}',host,session,turn,episode,str(Path(cwd).resolve()),now,kind,source,hint,fingerprint)
    try: validate(value)
    except (ValueError,TypeError): return None
    return value

def capture_event(root,host,payload,*,now):
    value=normalize(host,payload,now=now)
    if value is None: return None
    context=resolve_context(Path(value.project))
    if context is None or context.root!=Path(root).resolve() or not context.enabled or context.project==context.root:
        return None
    from dataclasses import replace
    value=replace(value,project=str(context.project))
    from .maintenance import capacity_state,session_maintenance
    if capacity_state(root)=='hard-limit': return None
    # Maintenance is best effort with a short lock wait: under contention it is
    # skipped rather than spending the time the event write needs.
    with busy_timeout(MAINTENANCE_BUSY_TIMEOUT_MS):
        try: session_maintenance(root,value.session_id)
        except (StateUnavailable,sqlite3.Error): pass
    # SQLite's own busy handler backs off in growing sleeps and lets waiters
    # miss the lock when many hooks pile up, so retry short attempts with jitter.
    deadline=time.monotonic()+CAPTURE_DEADLINE_MS/1000
    with busy_timeout(CAPTURE_ATTEMPT_TIMEOUT_MS):
        while True:
            try:
                with Store(root) as store,store.transaction():
                    store.put_event(value)
                    store.bound_raw_events(now)
                return value.event_id
            except (StateUnavailable,sqlite3.OperationalError) as exc:
                if not database_busy(exc) or time.monotonic()>=deadline: return None
                time.sleep(random.uniform(0.002,0.015))

def database_busy(exc):
    """True only for lock contention, so a full or broken store is not retried."""
    while exc is not None:
        if isinstance(exc,sqlite3.OperationalError) and ('locked' in str(exc) or 'busy' in str(exc)): return True
        exc=exc.__cause__
    return False

@contextmanager
def busy_timeout(ms):
    previous=Store.busy_timeout_ms
    Store.busy_timeout_ms=min(previous,ms)
    try: yield
    finally: Store.busy_timeout_ms=previous

def run_hook(host,stream,output):
    Store.busy_timeout_ms=HOOK_BUSY_TIMEOUT_MS
    try:
        raw=stream.read(65537)
        if len(raw)>65536: return 0
        payload=json.loads(raw)
        if not isinstance(payload,dict): return 0
        context=resolve_context(Path(payload.get('cwd','')))
        if context is None or not context.enabled: return 0
        key=capture_event(context.root,host,payload,now=utcnow())
        if key and payload.get('hook_event_name') in ('SessionStart','UserPromptSubmit'):
            if read_config(context.root)['mode']=='observe':
                message=f'Nebula is in OBSERVE mode. Captured event {key}. Use the nebula skill to record candidate observations at completed decision boundaries. Do not suggest or apply learned behavior or request confirmation. Continue the user\'s ordinary task without using lessons as instructions. Unknown prompt provenance is not human confirmation.'
            else:
                message=f'Nebula is ON. Captured event {key}. Use the nebula skill to recall relevant lessons and record a lesson at a completed decision boundary. Unknown prompt provenance is not human confirmation.'
            result={'hookSpecificOutput':{'hookEventName':payload['hook_event_name'],'additionalContext':message}}
            output.write(json.dumps(result,separators=(',',':'))+'\n')
    except (OSError,ValueError,TypeError,RecursionError,sqlite3.Error,StateUnavailable):
        return 0
    return 0
