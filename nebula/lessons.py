from dataclasses import asdict,replace
from pathlib import Path
from .models import Lesson, validate, load, digest, timestamp, utcnow
from .roots import read_config

MATERIAL=('kind','trigger','action','context_tags','exceptions','scope_projects')

def record_lesson(store,draft):
    value=load(Lesson,draft)
    if not value.evidence_ids: raise ValueError('a lesson requires captured evidence references')
    events=[store.get_event(key) for key in value.evidence_ids]
    if any(e is None for e in events): raise ValueError('lesson evidence unavailable')
    if value.rationale_source=='human' and not any(e.origin=='human' for e in events):
        raise ValueError('human rationale needs attributable human evidence')
    selected=read_config(store.root)['projects']
    if any(p not in selected for p in value.scope_projects): raise ValueError('lesson scope is not a selected project')
    with store.transaction():
        old=store.get_lesson(value.lesson_id)
        if old:
            changed=any(getattr(old,k)!=getattr(value,k) for k in MATERIAL)
            value=replace(value,version=old.version+int(changed),disabled=old.disabled)
        else: value=replace(value,version=1)
        store.put_lesson(value)
        store.audit('lesson',{'lesson_id':value.lesson_id,'version':value.version,'evidence_ids':value.evidence_ids})
    return value

def record_sample(store,value):
    validate(value)
    lesson=store.get_lesson(value.lesson_id)
    source=store.get_event(value.source_event_id)
    if lesson is None or lesson.version!=value.version: raise ValueError('sample lesson is not current')
    if source is None or source.origin!='human': raise ValueError('sample needs attributable human choice')
    if (source.session_id,source.episode_id,source.project)!=(value.session_id,value.episode_id,value.project):
        raise ValueError('sample identity does not match source evidence')
    if value.project not in read_config(store.root)['projects'] or (lesson.scope_projects and value.project not in lesson.scope_projects):
        raise ValueError('sample outside selected lesson scope')
    if timestamp(value.timestamp)!=timestamp(source.timestamp) or timestamp(source.timestamp)>timestamp(utcnow()):
        raise ValueError('sample age must match captured attribution time')
    receipt=store.receipt(source.event_id)
    if receipt is not None:
        if receipt.get('verb')=='observe':
            expected={'lesson_id':value.lesson_id,'version':value.version,'verdict':value.verdict,'outcome':value.outcome}
            if any(receipt.get(k)!=v for k,v in expected.items()): raise ValueError('sample does not match attributed choice')
        elif receipt.get('verb') in ('reject', 'exception'):
            raise ValueError('task-specific feedback cannot be an observational sample')
        elif receipt.get('verb') in ('accept','correct','withdraw','disable'):
            pending=store.get_suggestion(receipt.get('suggestion_id',''))
            verdict='positive' if receipt['verb']=='accept' else 'negative'
            if pending is None or (pending.lesson_id,pending.version)!=(value.lesson_id,value.version) or value.verdict!=verdict or value.outcome!='unknown':
                raise ValueError('sample does not match bound suggestion feedback')
        else: raise ValueError('sample receipt is not a bound human choice')
        if receipt.get('source') not in ('verified-host-submission','interactive-terminal'): raise ValueError('unverified sample receipt')
    if value.outcome=='suitable' and (receipt is None or receipt.get('outcome')!='suitable'):
        raise ValueError('suitable outcome needs explicit verified feedback')
    provenance={'source_event_id':source.event_id,'source_digest':source.digest,'source_timestamp':source.timestamp,
                'origin':source.origin,'host':source.host,'verdict':value.verdict,'outcome':value.outcome,'receipt':receipt}
    with store.transaction():
        result=store.put_sample(value,provenance=provenance,essential=value.verdict=='negative')
        confirmation=store.confirmation(value.lesson_id,value.version)
        if value.verdict=='negative' and confirmation and timestamp(source.timestamp)>=timestamp(confirmation['timestamp']):
            store.connection.execute('DELETE FROM confirmations WHERE lesson_id=? AND version=?',(value.lesson_id,value.version))
        store.audit('sample',{'lesson_id':value.lesson_id,'episode_id':value.episode_id,'verdict':value.verdict,'source':value.source_event_id})
    return result
