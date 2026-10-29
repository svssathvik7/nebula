import argparse,json,sqlite3,sys,webbrowser
from dataclasses import asdict
from pathlib import Path
from .models import dump,utcnow,load,Sample
from .store import Store,StateUnavailable
from .roots import resolve_context,read_config
from .lifecycle import init_nebula,set_mode
from .capture import capture_event
from .lessons import record_lesson,record_sample
from .feedback import suggest,apply_feedback,VERDICTS
from .recall import recall
from .scoring import current_score
from . import application
from .install import plan_install,install,uninstall

RUNTIME=Path(__file__).resolve().parents[1]

def input_json():
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536: raise ValueError('input exceeds 64 KiB')
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError('input must be a JSON object')
    return value

def parser():
    p=argparse.ArgumentParser(description='Nebula: shared session learning for Claude and Codex')
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init'); init.add_argument('directory',type=Path); init.add_argument('--project',action='append',required=True,type=Path)
    stats=sub.add_parser('stats',help='Generate a local multi-nebula analytics report')
    stats.add_argument('--root',type=Path)
    stats.add_argument('--output',type=Path)
    stats.add_argument('--open',action='store_true',help='Open the saved report in your browser')
    for name in ('on','off','mode','status','observe','record-lesson','record-sample','recall','suggest','feedback','inspect','application','install','uninstall','maintain','confirm','attest','review'):
        cmd=sub.add_parser(name); cmd.add_argument('--root',type=Path)
        if name in ('record-lesson','record-sample','suggest','application'): cmd.add_argument('--stdin',action='store_true',required=True)
        if name=='observe': cmd.add_argument('--host',required=True,choices=('claude','codex'))
        if name=='on': cmd.add_argument('mode',nargs='?',choices=('full','observe'),default='full')
        if name=='status': cmd.add_argument('--summary',action='store_true',help='Return only current mode and enabled state for automatic checks')
        if name=='mode': cmd.add_argument('mode',choices=('off','observe','full'))
        if name=='recall': cmd.add_argument('--project',required=True,type=Path); cmd.add_argument('--query',required=True)
        if name in ('install','uninstall'):
            cmd.add_argument('--project',action='append',required=True,type=Path); cmd.add_argument('--host',action='append',required=True,choices=('claude','codex'))
            if name=='install': cmd.add_argument('--dry-run',action='store_true')
        if name in ('feedback','confirm'):
            cmd.add_argument('--suggestion',required=True); cmd.add_argument('--verdict',required=True,choices=sorted(VERDICTS))
            cmd.add_argument('--reason',help='Human reason for an explicit exception (1 to 512 characters)')
            if name=='feedback': cmd.add_argument('--source-event',required=True)
        if name in ('inspect','attest','review'): cmd.add_argument('--lesson',required=True)
        if name=='attest':
            cmd.add_argument('--event',required=True); cmd.add_argument('--verdict',required=True,choices=('positive','negative')); cmd.add_argument('--outcome',required=True,choices=('suitable','failed','unknown'))
        if name=='review': cmd.add_argument('--event',required=True); cmd.add_argument('--version',required=True,type=int)
        if name=='application': cmd.add_argument('operation',choices=('claim','finish','review'))
    return p

def stats_result(args):
    from .analytics.report import build_report
    from .analytics.render import write_report
    report=build_report(args.root or Path.cwd())
    output=write_report(report,scan_root=Path(report['scan_root']),output=args.output)
    warnings=[*report['warnings'],*report['discovery']['warnings']]
    for nebula in report['nebulas']:
        if not nebula['available']: warnings.append(nebula['diagnostic'])
        else: warnings.extend(nebula['warnings'])
    if args.open:
        try:
            if not webbrowser.open(output.as_uri()): warnings.append('Browser did not open; the report is saved at the output path.')
        except (OSError,webbrowser.Error):
            warnings.append('Browser could not open; the report is saved at the output path.')
    return {'output':str(output),'generated_at':report['generated_at'],
            'discovered_nebulas':report['summary']['discovered_nebulas'],
            'available_nebulas':report['summary']['available_nebulas'],
            'discovery_complete':report['discovery']['complete'],
            'details_complete':all(n['coverage']['details_complete'] for n in report['nebulas'] if n['available']),
            'warnings':[w[:512] for w in warnings[:10]],'warnings_omitted':max(0,len(warnings)-10)}

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=='stats': result=stats_result(args)
        elif args.command=='init': result=asdict(init_nebula(args.directory,args.project))
        else:
            if args.root is None:
                context=resolve_context(Path.cwd())
                if context is None: raise ValueError('no selected nebula here; pass --root')
                root=context.root
            else: root=args.root.resolve(strict=True)
            if args.command=='on':
                set_mode(root,args.mode); result={'mode':args.mode,'enabled':True}
            elif args.command=='off':
                set_mode(root,'off'); result={'mode':'off','enabled':False}
            elif args.command=='mode':
                set_mode(root,args.mode); result={'mode':args.mode,'enabled':args.mode!='off'}
            elif args.command=='observe': result={'event_id':capture_event(root,args.host,input_json(),now=utcnow())}
            elif args.command=='install':
                changes=plan_install(root,args.project,args.host,RUNTIME)
                result={'changes':changes} if args.dry_run else install(changes)
            elif args.command=='uninstall': result={'results':[uninstall(root,project,host) for project in args.project for host in args.host]}
            elif args.command=='maintain':
                from .maintenance import maintain
                result=maintain(root,now=utcnow())
            else:
                with Store(root) as store:
                    if args.command=='status':
                        config=read_config(root)
                        if args.summary:
                            result={'mode':config['mode'],'enabled':config['enabled']}
                        else:
                            result={**config,'counts':store.status(),'lessons':[{'lesson_id':v.lesson_id,'version':v.version,'disabled':v.disabled,'score':asdict(current_score(store,v))} for v in store.lessons()]}
                            from .maintenance import health
                            result['health']=health(root)
                            result['recent_events']=[json.loads(r[0]) for r in store.connection.execute('SELECT data FROM events ORDER BY timestamp DESC LIMIT 6')]
                    elif args.command=='record-lesson': result=record_lesson(store,input_json())
                    elif args.command=='record-sample': result={'new_sample':record_sample(store,load(Sample,input_json()))}
                    elif args.command=='recall': result=recall(store,project=str(args.project.resolve()),query=args.query)
                    elif args.command=='suggest':
                        data=input_json(); value=store.get_lesson(data.pop('lesson_id'))
                        if value is None: raise ValueError('lesson unavailable')
                        result=suggest(store,value,now=utcnow(),**data)
                    elif args.command=='feedback': result=apply_feedback(store,suggestion_id=args.suggestion,source_event_id=args.source_event,verdict=args.verdict,now=utcnow(),reason=args.reason)
                    elif args.command=='confirm':
                        from .interactive import confirm
                        result=confirm(store,suggestion_id=args.suggestion,verdict=args.verdict,stream=sys.stdin,out=sys.stderr,reason=args.reason)
                    elif args.command=='attest':
                        from .interactive import attest
                        result=attest(store,event_id=args.event,lesson_id=args.lesson,verdict=args.verdict,outcome=args.outcome,stream=sys.stdin,out=sys.stderr)
                    elif args.command=='review':
                        from .interactive import review
                        result=review(store,lesson_id=args.lesson,version=args.version,event_id=args.event,stream=sys.stdin,out=sys.stderr)
                    elif args.command=='inspect':
                        value=store.get_lesson(args.lesson)
                        if value is None: raise ValueError('lesson unavailable')
                        result={'lesson':asdict(value),'score':asdict(current_score(store,value)),'confirmation':store.confirmation(value.lesson_id,value.version),
                                'feedback':store.feedback_history(value.lesson_id,value.version),
                                'samples':[asdict(v) for v in store.samples(value.lesson_id,value.version)],
                                'sample_provenance':[store.sample_provenance(v.lesson_id,v.version,v.episode_id) for v in store.samples(value.lesson_id,value.version)],
                                'evidence':[asdict(e) if (e:=store.get_event(k)) else {'event_id':k,'expired_or_missing':True} for k in value.evidence_ids]}
                    elif args.command=='application':
                        operation={'claim':application.claim_application,'finish':application.finish_application,'review':application.review_application}[args.operation]
                        result={'result':operation(store,**input_json())}
        sys.stdout.write(dump(result)+'\n'); return 0
    except (OSError,ValueError,TypeError,KeyError,RecursionError,sqlite3.Error,StateUnavailable) as exc:
        sys.stderr.write(dump({'error':type(exc).__name__,'message':str(exc)})+'\n'); return 1
