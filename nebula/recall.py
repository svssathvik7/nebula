"""Cheap lexical shortlist; the active agent assesses semantic applicability."""
from dataclasses import asdict
import re
from .models import dump
from .roots import read_config
from .scoring import current_score
from .application import suspension_key

def words(text): return set(re.findall(r'\w+',text.casefold()))

def recall(store,*,project,query,limit=6):
    config=read_config(store.root)
    if not config['enabled'] or project not in config['projects']: return []
    if not isinstance(query,str): raise ValueError('query must be text')
    tokens=words(query[:4096])
    if not tokens: return []
    limit=min(6,max(0,int(limit))); ranked=[]
    for value in store.lessons():
        if value.disabled or (value.scope_projects and project not in value.scope_projects): continue
        overlap=len(tokens & words(value.trigger+' '+' '.join(value.context_tags)))
        if not overlap: continue
        stats=current_score(store,value)
        ranked.append((overlap,stats.confidence,value,stats))
    ranked.sort(key=lambda item:(-item[0],-item[1],item[2].lesson_id))
    results=[]
    for _,_,value,stats in ranked[:limit]:
        conflict=any(other.trigger.casefold()==value.trigger.casefold() and other.action!=value.action for _,_,other,_ in ranked)
        item={'lesson_id':value.lesson_id,'version':value.version,'kind':value.kind,'trigger':value.trigger,'action':value.action,
              'context_tags':list(value.context_tags),'exceptions':list(value.exceptions),'scope_projects':list(value.scope_projects),
              'score':asdict(stats),'confirmed':store.confirmed(value.lesson_id,value.version),
              'requires_inspection':False,'suspended':bool(store.get_meta(suspension_key(value.lesson_id,value.version),False)),'conflict':conflict}
        exceptions = store.feedback_history(value.lesson_id,value.version,exceptions_only=True)
        if exceptions:
            item['exception_feedback'] = [{'project': e['project'], 'context_digest': e['context_digest'],
                                           'reason': e['reason']} for e in exceptions]
        # Trim descriptive fields only; never silently omit an exception or
        # scope boundary then offer that truncated record for application.
        if len(dump(item).encode())>4096:
            item={'lesson_id':value.lesson_id,'version':value.version,'kind':value.kind,'trigger':value.trigger,
                  'score':asdict(stats),'confirmed':store.confirmed(value.lesson_id,value.version),
                  'conflict':conflict,'requires_inspection':True,'reason':'Full action/context/exceptions/scope require inspect before assessment.'}
        if len(dump(results+[item]).encode())>8192: continue
        results.append(item)
    return results
