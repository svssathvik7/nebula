"""Scoped, version-bound feedback. Receipts are supplied by trusted adapters only."""
from dataclasses import replace
from .models import Suggestion, Sample, digest, validate, timestamp, dump
from .roots import read_config
from .scoring import current_score, penalty_key, rejection_count

VERDICTS={'accept','reject','exception','correct','withdraw','disable'}


def validate_feedback(verdict, reason):
    if verdict not in VERDICTS:
        raise ValueError('invalid feedback verdict')
    if verdict == 'exception':
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
            raise ValueError('exception needs a human reason of 1 to 512 characters')
    elif reason is not None:
        raise ValueError('reason is only supported for exception feedback')


def record_override(store, pending, source, verdict, reason, now):
    """Keep a durable decision block, separate from observational samples."""
    previous = store.application(pending.lesson_id, pending.version,
                                 pending.session_id, pending.episode_id)
    data = previous or {'project': pending.project, 'status': verdict, 'timestamp': now}
    penalized = data.get('rejection_penalized', False)
    if verdict == 'reject' and not penalized:
        count = rejection_count(store, pending.lesson_id, pending.version)
        store.set_meta(penalty_key(pending.lesson_id, pending.version), min(50, count + 1))
        penalized = True
    entry = {
        'project': pending.project,
        'feedback_verdict': verdict,
        'suggestion_id': pending.suggestion_id,
        'context_digest': pending.context_digest,
        'reason': reason,
        'source_event_id': source.event_id,
        'source_digest': source.digest,
        'source_timestamp': source.timestamp,
        'initiator': 'human',
    }
    history = data.get('feedback_history')
    if history is None:
        history = []
        if 'feedback_verdict' in data:
            legacy = {field: data[field] for field in entry}
            legacy['project'] = data.get('feedback_project', data['project'])
            history = [legacy]
    exceptions = data.get('exception_history', [e for e in history if e['feedback_verdict'] == 'exception'])
    # Retain bounded evidence separately from the latest decision state. Repeated
    # acknowledgement of the same verdict/reason refreshes its source, not counts.
    identity = (pending.suggestion_id, verdict, reason)
    history = [e for e in history if
               (e['suggestion_id'], e['feedback_verdict'], e['reason']) != identity]
    history = (history + [entry])[-6:]
    if verdict == 'exception':
        exceptions = [e for e in exceptions if
                      (e['suggestion_id'], e['feedback_verdict'], e['reason']) != identity]
        exceptions = (exceptions + [entry])[-6:]
    # A real application keeps its execution project/status. Each feedback
    # snapshot owns its project, even when the same episode spans two children.
    execution = previous is not None and previous['status'] not in ('reject', 'exception')
    data = {
        **data, **entry,
        'project': previous['project'] if execution else pending.project,
        'status': previous['status'] if execution else verdict,
        'feedback_project': pending.project,
        'rejection_penalized': penalized,
        'feedback_history': history,
        'exception_history': exceptions,
    }
    store.connection.execute(
        'INSERT INTO applications VALUES(?,?,?,?,?) '
        'ON CONFLICT(lesson_id,version,session_id,episode_id) DO UPDATE SET data=excluded.data',
        (pending.lesson_id, pending.version, pending.session_id, pending.episode_id, dump(data)),
    )

def suggest(store,lesson,*,session_id,episode_id,project,context_digest,now):
    timestamp(now)
    if project not in read_config(store.root)['projects'] or (lesson.scope_projects and project not in lesson.scope_projects):
        raise ValueError('suggestion outside lesson scope')
    if store.get_lesson(lesson.lesson_id)!=lesson: raise ValueError('suggestion requires current lesson')
    key='sg-'+digest([lesson.lesson_id,lesson.version,session_id,episode_id,project,context_digest])[:32]
    value=Suggestion(key,lesson.lesson_id,lesson.version,session_id,episode_id,project,context_digest,now,'pending')
    validate(value)
    with store.transaction():
        if read_config(store.root)['mode']=='observe':
            raise ValueError('suggestions are unavailable in observation mode')
        old=store.get_suggestion(key)
        if old: return old
        store.put_suggestion(value)
        store.audit('suggestion',{'id':key})
    return value

def bound_source(store,source_event_id,**expected):
    source=store.get_event(source_event_id)
    receipt=store.receipt(source_event_id)
    if source is None or source.origin!='human' or receipt is None:
        raise ValueError('feedback requires attributable human acknowledgement')
    if receipt.get('source') not in ('verified-host-submission','interactive-terminal') or any(receipt.get(k)!=v for k,v in expected.items()):
        raise ValueError('feedback requires matching captured user acknowledgement')
    return source

def apply_feedback(store,*,suggestion_id,source_event_id,verdict,now,reason=None):
    validate_feedback(verdict, reason)
    timestamp(now)
    from .maintenance import ensure_capacity
    with store.transaction():
        ensure_capacity(store.root,essential=True)
        pending=store.get_suggestion(suggestion_id)
        if pending is None: raise ValueError('suggestion unavailable')
        value=store.get_lesson(pending.lesson_id)
        if value is None or value.version!=pending.version: raise ValueError('suggestion lesson version is stale')
        expected = {'verb': verdict, 'suggestion_id': suggestion_id}
        if verdict == 'exception': expected['reason'] = reason
        source=bound_source(store,source_event_id,**expected)
        if source.session_id!=pending.session_id or source.project!=pending.project:
            raise ValueError('feedback session/project mismatch')
        if pending.project not in read_config(store.root)['projects'] or (value.scope_projects and pending.project not in value.scope_projects):
            raise ValueError('feedback outside lesson scope')
        applied_key='feedback:'+source_event_id
        prior=store.get_meta(applied_key)
        if prior:
            if prior!={'suggestion_id':suggestion_id,'verdict':verdict}: raise ValueError('feedback source already used')
            return current_score(store,value,now=now)
        if verdict=='accept' and pending.status!='pending': raise ValueError('suggestion already completed')
        if verdict=='accept':
            if value.disabled: raise ValueError('disabled lesson cannot be confirmed')
            store.connection.execute('INSERT INTO confirmations VALUES(?,?,?) ON CONFLICT(lesson_id,version) DO UPDATE SET data=excluded.data',
                                     (value.lesson_id,value.version,dump({'source_event_id':source_event_id,'source_digest':source.digest,'project':source.project,'scope_projects':value.scope_projects,'timestamp':now,'suggestion_id':suggestion_id,'session_id':pending.session_id,'episode_id':pending.episode_id,'context_digest':pending.context_digest,'host':source.host,'initiator':'human'})))
            store.set_meta(penalty_key(value.lesson_id, value.version), 0)
        elif verdict in ('reject', 'exception'):
            record_override(store, pending, source, verdict, reason, now)
        else:
            store.connection.execute('DELETE FROM confirmations WHERE lesson_id=? AND version=?',(value.lesson_id,value.version))
            if verdict=='disable':
                value=replace(value,disabled=True); store.put_lesson(value,essential=True)
        store.put_suggestion(replace(pending,status=verdict),essential=True)
        # Feedback changes this decision episode rather than manufacturing a
        # second sample for its execution or a later correction.
        if verdict not in ('reject', 'exception'):
            store.put_sample(Sample(value.lesson_id,value.version,pending.episode_id,pending.session_id,pending.project,source_event_id,
                                    'positive' if verdict=='accept' else 'negative','unknown',source.timestamp),essential=True,provenance={'source_event_id':source_event_id,'source_digest':source.digest,'source_timestamp':source.timestamp,'origin':'human','host':source.host,'verdict':'positive' if verdict=='accept' else 'negative','outcome':'unknown','receipt':store.receipt(source_event_id)})
        store.set_meta(applied_key,{'suggestion_id':suggestion_id,'verdict':verdict})
        store.audit('feedback',{'suggestion_id':suggestion_id,'source':source_event_id,'verdict':verdict})
        return current_score(store,value,now=now)
