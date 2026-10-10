"""Bounded advisory capture; no model calls and no tool authorization decisions."""
import json
import os
import sqlite3
from pathlib import Path
from .models import Event, digest, utcnow, validate
from .roots import resolve_context
from .store import Store, StateUnavailable
from .adapters import claude, codex

EVENTS={'SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','PostToolUseFailure','Stop','SessionEnd'}

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
    try:
        session_maintenance(root,value.session_id)
        with Store(root) as store,store.transaction():
            store.put_event(value)
            store.bound_raw_events(now)
    except StateUnavailable: return None
    return value.event_id

def run_hook(host,stream,output):
    try:
        raw=stream.read(65537)
        if len(raw)>65536: return 0
        payload=json.loads(raw)
        if not isinstance(payload,dict): return 0
        context=resolve_context(Path(payload.get('cwd','')))
        if context is None or not context.enabled: return 0
        key=capture_event(context.root,host,payload,now=utcnow())
        if key and payload.get('hook_event_name') in ('SessionStart','UserPromptSubmit'):
            message=f'Nebula is ON. Captured event {key}. Use the nebula skill to recall relevant lessons and record a lesson at a completed decision boundary. Unknown prompt provenance is not human confirmation.'
            result={'hookSpecificOutput':{'hookEventName':payload['hook_event_name'],'additionalContext':message}}
            output.write(json.dumps(result,separators=(',',':'))+'\n')
    except (OSError,ValueError,TypeError,sqlite3.Error,StateUnavailable):
        return 0
    return 0
