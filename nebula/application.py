"""Application bookkeeping. Host tools remain responsible for actual execution."""
from .models import Decision,dump,utcnow,digest
from .roots import read_config
from .feedback import bound_source
from .scoring import current_score

def suspension_key(key,version): return f'suspended:{key}:{version}'

def decide(lesson,score,*,enabled,context_match,permissions_ok,suspended=False):
    if context_match is not None and type(context_match) is not bool: raise ValueError('context match must be boolean or null')
    if type(permissions_ok) is not bool: raise ValueError('permissions assessment must be boolean')
    if not enabled or context_match is False: mode,reason='none','OFF or context does not match'
    elif context_match is None: mode,reason='suggest','context match is uncertain'
    elif lesson.disabled or suspended or not permissions_ok: mode,reason='blocked','disabled, suspended, or permission unavailable'
    elif score.mature and score.confidence>.75: mode,reason='apply','qualified lesson and matching context'
    else: mode,reason='suggest','lesson requires confirmation'
    return Decision(mode,reason,lesson.lesson_id,lesson.version,score)

def claim_application(store,*,lesson_id,version,session_id,episode_id,project,context_match=None,permissions_ok=False):
    if not all(isinstance(x,str) and 0<len(x)<=2048 for x in (session_id,episode_id,project)): raise ValueError('invalid application identity')
    if (context_match is not None and type(context_match) is not bool) or type(permissions_ok) is not bool: raise ValueError('invalid context/permission assessment')
    with store.transaction():
        from .maintenance import ensure_capacity
        from .store import StateUnavailable
        try: ensure_capacity(store.root)
        except StateUnavailable: return False
        config=read_config(store.root); value=store.get_lesson(lesson_id)
        if config['mode']!='full': return False
        if value is None or value.version!=version or project not in config['projects'] or (value.scope_projects and project not in value.scope_projects): return False
        decision=decide(value,current_score(store,value),enabled=config['enabled'],context_match=context_match,permissions_ok=permissions_ok,
                        suspended=bool(store.get_meta(suspension_key(lesson_id,version),False)))
        if decision.mode!='apply': return False
        row=store.connection.execute('SELECT 1 FROM applications WHERE lesson_id=? AND version=? AND session_id=? AND episode_id=?',(lesson_id,version,session_id,episode_id)).fetchone()
        if row: return False
        store.connection.execute('INSERT INTO applications VALUES(?,?,?,?,?)',(lesson_id,version,session_id,episode_id,dump({'project':project,'status':'claimed','timestamp':utcnow()})))
        store.audit('application-claim',{'lesson_id':lesson_id,'version':version,'episode_id':episode_id})
        return True

def finish_application(store,*,lesson_id,version,session_id,episode_id,outcome,source_event_ids):
    if outcome not in ('suitable','failed','unknown'): raise ValueError('invalid application outcome')
    if not isinstance(source_event_ids,list) or len(source_event_ids)>32: raise ValueError('invalid outcome evidence')
    with store.transaction():
        application=store.application(lesson_id,version,session_id,episode_id)
        if application is None: raise ValueError('application was not claimed')
        sources=[store.get_event(k) for k in source_event_ids]
        if not sources or any(e is None or e.session_id!=session_id or e.project!=application['project'] for e in sources):
            raise ValueError('outcome needs captured evidence in the application session/project')
        completed={**application,'status':outcome,'source_event_ids':source_event_ids}
        if application['status']!='claimed':
            if application!=completed: raise ValueError('application already finished; record review instead')
            return
        store.connection.execute('UPDATE applications SET data=? WHERE lesson_id=? AND version=? AND session_id=? AND episode_id=?',
                                 (dump(completed),lesson_id,version,session_id,episode_id))
        if outcome=='failed': store.set_meta(suspension_key(lesson_id,version),{'failure_id':'failure-'+digest([lesson_id,version,session_id,episode_id,source_event_ids])[:32],'session_id':session_id,'episode_id':episode_id,'source_event_ids':source_event_ids,'timestamp':utcnow()})
        store.audit('application-finish',{'lesson_id':lesson_id,'version':version,'episode_id':episode_id,'outcome':outcome})

def review_application(store,*,lesson_id,version,source_event_id):
    with store.transaction():
        from .maintenance import ensure_capacity
        ensure_capacity(store.root,essential=True)
        value=store.get_lesson(lesson_id)
        if value is None or value.version!=version: raise ValueError('review needs current lesson')
        key=suspension_key(lesson_id,version)
        suspension=store.get_meta(key,False)
        consumed=store.get_meta('review-receipt:'+source_event_id)
        if not suspension:
            if consumed and consumed.get('lesson_id')==lesson_id and consumed.get('version')==version: return
            raise ValueError('lesson has no failure to review')
        if not isinstance(suspension,dict): raise ValueError('legacy suspension needs explicit repair before review')
        failure_id=suspension['failure_id']
        if consumed and consumed.get('failure_id')!=failure_id: raise ValueError('review receipt belongs to an earlier failure')
        source=bound_source(store,source_event_id,verb='review',lesson_id=lesson_id,version=version,failure_id=failure_id)
        if source.project not in read_config(store.root)['projects'] or (value.scope_projects and source.project not in value.scope_projects): raise ValueError('review outside lesson scope')
        store.set_meta('review-receipt:'+source_event_id,{'lesson_id':lesson_id,'version':version,'failure_id':failure_id})
        store.set_meta(key,False)
        store.audit('application-review',{'lesson_id':lesson_id,'version':version,'source':source_event_id,'failure_id':failure_id})
