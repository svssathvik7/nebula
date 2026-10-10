"""Reproducible local overhead benchmark; no network/model calls."""
import argparse,json,statistics,subprocess,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataclasses import replace
from nebula.models import Event,Lesson,dump,utcnow
from nebula.store import Store
from nebula.lifecycle import init_nebula,set_enabled
from nebula.recall import recall
from nebula.maintenance import maintain,usage_bytes

RUNTIME=Path(__file__).resolve().parents[1]

def timed(operation):
    start=time.perf_counter(); result=operation(); return (time.perf_counter()-start)*1000,result

def percentiles(values):
    ordered=sorted(values)
    return {'p50_ms':round(statistics.median(ordered),3),'p95_ms':round(ordered[min(len(ordered)-1,int(.95*len(ordered)))],3)}

def run(events,lessons,runs):
    with tempfile.TemporaryDirectory(prefix='nebula-benchmark-') as tmp:
        root=Path(tmp).resolve(); a=root/'a'; b=root/'b'; a.mkdir(); b.mkdir(); init_nebula(root,[a,b]); set_enabled(root,True)
        now=utcnow(); insert=[]; retrieves=[]
        with Store(root) as store:
            for i in range(events):
                value=Event(f'ev-{i}','codex','bench','turn',f'e{i}',str(a),now,'PostToolUse','assistant','tool result',f'digest-{i}')
                elapsed,_=timed(lambda:store.put_event(value)); insert.append(elapsed)
            for i in range(lessons):
                store.put_lesson(Lesson(f'lesson-{i}',1,'convention','when adding a module',f'Place module {i} in src/modules.',('module',),(),(),'Reason inferred.','inferred',('ev-0',),False))
            for _ in range(runs):
                elapsed,result=timed(lambda:recall(store,project=str(a),query='adding module')); retrieves.append(elapsed)
            recall_bytes=len(dump(result).encode())
        maintain(root,now=now)
        captures=[]
        for i in range(runs):
            payload={'session_id':'bench','turn_id':f'turn-{i}','hook_event_name':'PostToolUse','cwd':str(a),'tool_name':'exec_command','tool_response':{'exit_code':0}}
            elapsed,result=timed(lambda:subprocess.run([sys.executable,str(RUNTIME/'scripts/nebula_hook.py'),'--host','codex'],input=dump(payload),text=True,capture_output=True,cwd='/private/tmp',check=True)); captures.append(elapsed)
        return {'events':events,'lessons':lessons,'runs':runs,'hook_subprocess':percentiles(captures),'insert':percentiles(insert),'recall':percentiles(retrieves),'state_bytes':usage_bytes(root),'recall_bytes':recall_bytes,'hook_p95_target_ms':50,'target_met':percentiles(captures)['p95_ms']<=50,'model_calls':0,'recall_units':'UTF-8 bytes, not exact tokens'}

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--events',type=int,default=1000); p.add_argument('--lessons',type=int,default=100); p.add_argument('--runs',type=int,default=100)
    args=p.parse_args()
    if min(args.events,args.lessons,args.runs)<1: p.error('counts must be positive')
    print(json.dumps(run(args.events,args.lessons,args.runs),indent=2))
