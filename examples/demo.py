"""Synthetic fixture demonstration; receipts are not real human history."""
import json,sys,tempfile
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nebula.models import Event,Lesson,utcnow,digest
from nebula.lifecycle import init_nebula,set_enabled
from nebula.store import Store
from nebula.lessons import record_lesson
from nebula.feedback import suggest,apply_feedback
from nebula.scoring import current_score
from nebula.recall import recall
from nebula.application import decide,claim_application,finish_application

def run_demo():
    with tempfile.TemporaryDirectory(prefix='nebula-demo-') as temporary:
        root=Path(temporary).resolve(); a=root/'ledger'; b=root/'payments'; a.mkdir(); b.mkdir()
        init_nebula(root,[a,b]); set_enabled(root,True); now=utcnow()
        with Store(root) as store:
            def source(key,origin='human',project=a,session='s1',episode='e1',kind='UserPromptSubmit'):
                event=Event(key,'claude',session,'turn',episode,str(project),now,kind,origin,'Synthetic example evidence',digest([key,origin]))
                store.put_event(event); return event
            first=source('teaching',origin='unknown')
            value=record_lesson(store,asdict(Lesson('module-layout',1,'convention','when adding a handwritten module','Place handwritten modules in src/modules.',('module',),('generated code',),(),
                                                  'Inferred grouping convention.','inferred',(first.event_id,),False)))
            record_lesson(store,asdict(Lesson('verification',1,'workflow','before finishing a small code change','Run the targeted local validation before the full integration suite.',('verification',),('protocol changes require the full suite',),(),
                                            'Inferred iteration tradeoff.','inferred',(first.event_id,),False)))
            initial=decide(value,current_score(store,value),enabled=True,context_match=True,permissions_ok=True)
            pending=suggest(store,value,session_id='s1',episode_id='e1',project=str(a),context_digest='handwritten invoice module',now=now)
            acceptance=source('acceptance')
            store.put_receipt(acceptance.event_id,'verified-host-submission',{'verb':'accept','suggestion_id':pending.suggestion_id})
            accepted=apply_feedback(store,suggestion_id=pending.suggestion_id,source_event_id=acceptance.event_id,verdict='accept',now=now)
            recalled=recall(store,project=str(b),query='adding handwritten module')
            sibling=decide(value,current_score(store,value),enabled=True,context_match=True,permissions_ok=True)
            claimed=claim_application(store,lesson_id=value.lesson_id,version=1,session_id='s2',episode_id='e2',project=str(b),context_match=True,permissions_ok=True)
            target=b/'src/modules/invoice.py'
            if claimed:
                target.parent.mkdir(parents=True); target.write_text('def invoice_total(amounts):\n    return sum(amounts)\n')
                evidence=source('tool-result',origin='assistant',project=b,session='s2',episode='e2',kind='PostToolUse')
                finish_application(store,lesson_id=value.lesson_id,version=1,session_id='s2',episode_id='e2',outcome='suitable',source_event_ids=[evidence.event_id])
            different=decide(value,current_score(store,value),enabled=True,context_match=False,permissions_ok=True)
            withdrawal=source('withdrawal')
            store.put_receipt(withdrawal.event_id,'verified-host-submission',{'verb':'withdraw','suggestion_id':pending.suggestion_id})
            revoked=apply_feedback(store,suggestion_id=pending.suggestion_id,source_event_id=withdrawal.event_id,verdict='withdraw',now=now)
            return {'synthetic':True,'initial_mode':initial.mode,'after_acceptance':asdict(accepted),'matching_sibling_mode':sibling.mode,
                    'recalled_ids':[r['lesson_id'] for r in recalled],'different_context_mode':different.mode,
                    'artifact_verified':target.is_file() and 'return sum(amounts)' in target.read_text(),
                    'after_withdrawal':{'confirmed':store.confirmed(value.lesson_id,1),'score':asdict(revoked)},
                    'positive_samples_after_execution':accepted.positives,'note':'Synthetic receipts; actual host reasoning and direct human input are separate release gates.'}

if __name__=='__main__': print(json.dumps(run_demo(),indent=2))
