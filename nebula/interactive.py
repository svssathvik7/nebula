"""Local user acknowledgement fallback when host prompt provenance is unknown.

A terminal is an operational human input boundary, not cryptographic identity.
Agents must ask users to run these commands themselves; never pipe or simulate
terminal input. No noninteractive endpoint can create a receipt.
"""
from dataclasses import replace
import uuid
from .models import dump,digest,utcnow
from .feedback import apply_feedback,validate_feedback
from .lessons import record_sample
from .models import Sample
from .roots import read_config

def read_ack(stream,out,expected,preview):
    if not stream.isatty(): raise ValueError('direct interactive terminal required; ask the user to run this command')
    out.write(preview+'\nType exactly: '+expected+'\n> '); out.flush()
    answer=stream.readline(4097).strip()
    if answer!=expected: raise ValueError('acknowledgement did not match; nothing confirmed')

def confirm(store,*,suggestion_id,verdict,stream,out,reason=None):
    validate_feedback(verdict, reason)
    pending=store.get_suggestion(suggestion_id)
    if pending is None: raise ValueError('suggestion unavailable')
    value=store.get_lesson(pending.lesson_id)
    if value is None or value.version!=pending.version: raise ValueError('suggestion is stale')
    expected=f'NEBULA {verdict.upper()} {suggestion_id}'
    preview=dump({'lesson':value,'suggestion':pending,'reason':reason})
    read_ack(stream,out,expected,preview)
    from .models import Event
    now=utcnow(); key='human-'+uuid.uuid4().hex
    row=store.connection.execute("SELECT json_extract(data,'$.host') FROM events WHERE json_extract(data,'$.session_id')=? AND json_extract(data,'$.project')=? ORDER BY timestamp DESC LIMIT 1",(pending.session_id,pending.project)).fetchone()
    host=row[0] if row else (store.confirmation(value.lesson_id,value.version) or {}).get('host','codex')
    source=Event(key,host,pending.session_id,'',pending.episode_id,pending.project,now,'LocalAcknowledgement','human',expected,digest([expected,reason,key]))
    with store.transaction():
        receipt = {'verb': verdict, 'suggestion_id': suggestion_id}
        if verdict == 'exception': receipt['reason'] = reason
        store.put_event(source,essential=True); store.put_receipt(key,'interactive-terminal',receipt)
        return apply_feedback(store,suggestion_id=suggestion_id,source_event_id=key,verdict=verdict,now=now,reason=reason)

def attest(store,*,event_id,lesson_id,verdict,outcome,stream,out):
    source=store.get_event(event_id); value=store.get_lesson(lesson_id)
    if source is None or source.kind!='UserPromptSubmit' or source.origin!='unknown': raise ValueError('attest needs an unknown-origin captured prompt')
    if value is None or source.project not in read_config(store.root)['projects']: raise ValueError('attribution lesson/project unavailable')
    expected=f'NEBULA OBSERVE {lesson_id} {event_id} {verdict} {outcome}'
    read_ack(stream,out,expected,dump({'lesson':value,'event':source,'verdict':verdict,'outcome':outcome}))
    key='human-'+uuid.uuid4().hex; now=utcnow()
    attributed=replace(source,event_id=key,origin='human',hint='Locally attributed human choice',digest=digest([key,source.digest]),timestamp=now)
    with store.transaction():
        store.put_event(attributed,essential=verdict=='negative'); store.put_receipt(key,'interactive-terminal',{'verb':'observe','lesson_id':lesson_id,'version':value.version,'outcome':outcome,'verdict':verdict,'attributed_event_id':event_id})
        record_sample(store,Sample(lesson_id,value.version,source.episode_id,source.session_id,source.project,key,verdict,outcome,now))
    return {'source_event_id':key,'sample_recorded':True}

def review(store,*,lesson_id,version,event_id,stream,out):
    from .application import review_application
    source=store.get_event(event_id); value=store.get_lesson(lesson_id)
    if source is None or value is None or value.version!=version: raise ValueError('review lesson/event unavailable')
    from .application import suspension_key
    suspension=store.get_meta(suspension_key(lesson_id,version),False)
    if not isinstance(suspension,dict): raise ValueError('no current failure binding')
    failure_id=suspension['failure_id']
    expected=f'NEBULA REVIEW {lesson_id} {version} {failure_id}'
    read_ack(stream,out,expected,dump({'lesson':value,'failure':suspension}))
    key='human-'+uuid.uuid4().hex
    with store.transaction():
        store.put_event(replace(source,event_id=key,origin='human',kind='LocalAcknowledgement',hint=expected,timestamp=utcnow(),digest=digest([key,expected])),essential=True)
        store.put_receipt(key,'interactive-terminal',{'verb':'review','lesson_id':lesson_id,'version':version,'failure_id':failure_id})
        review_application(store,lesson_id=lesson_id,version=version,source_event_id=key)
    return {'reviewed':True}
