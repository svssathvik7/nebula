"""Read-only setup diagnosis. Each problem names a concrete fix."""
import json,shlex
from pathlib import Path
from .roots import read_config
from .store import StateUnavailable

HOOK_FILES={'claude':'.claude/settings.local.json','codex':'.codex/hooks.json'}
PROBLEM_LIMIT=20

def find_root(cwd):
    current=Path(cwd).resolve()
    for ancestor in (current,*current.parents):
        if (ancestor/'.nebula').exists() or (ancestor/'.nebula').is_symlink(): return ancestor
    return None

def check(name,status,detail,fix=None):
    value={'check':name,'status':status,'detail':detail}
    if fix: value['fix']=fix
    return value

def doctor(root,*,runtime,all_checks=False):
    root=Path(root).resolve(); runtime=Path(runtime).resolve(); checks=[]
    try: config=read_config(root)
    except StateUnavailable as exc:
        checks.append(check('config','fail',f'{root}/.nebula/config.json is missing or invalid ({exc.__cause__ or exc}).',
                            'Restore the file from a backup or fix it by hand. Do not run /nebula init again: it refuses existing state so memory is not lost.'))
        return report(root,None,checks,all_checks)
    checks.append(check('config','ok',f"{len(config['projects'])} selected project(s)"))
    checks.append(state_check(root))
    checks.append(check('mode','ok',f"{config['mode']}") if config['mode']!='off' else
                  check('mode','warn','Nebula is off: nothing is captured or applied.','/nebula on (or /nebula on observe to learn quietly).'))
    try:
        from .store import Store
        with Store(root) as store:
            installed={(p,h):store.installation(p,h) for p in config['projects'] for h in HOOK_FILES}
    except (OSError,ValueError,StateUnavailable):
        installed={}
    for project in config['projects']:
        name=Path(project).relative_to(root).as_posix(); hosts=[h for h in HOOK_FILES if installed.get((project,h))]
        if not Path(project).is_dir():
            checks.append(check(f'project {name}','fail',f'{project} no longer exists.',f'Restore the folder, or remove it from the nebula (/nebula remove {name}).'))
            continue
        checks.append(check(f'project {name}','ok',f"installed for {', '.join(hosts)}") if hosts else
                      check(f'project {name}','warn','Nebula is not installed here for any host, so no session in it learns or recalls.',
                            f'/nebula install {name} (runs install --project for this folder).'))
        for host in hosts: checks.append(host_check(name,project,host,installed[(project,host)],runtime))
    pending=recovery(root)
    if pending:
        checks.append(check('interrupted install','warn',f'An install was interrupted for: {pending}.','Run the same /nebula install again; it resumes from the recorded state.'))
    return report(root,config['mode'],checks,all_checks)

def state_check(root):
    from .maintenance import health
    value=health(root)
    if not value['usable'] and value.get('diagnostic'):
        return check('state','fail',f"Database unavailable: {value['diagnostic']}",'Learned behavior is withheld until it is fixed. Check permissions on .nebula/ and free disk space.')
    if value.get('integrity')!='ok':
        return check('state','fail',f"Database integrity check failed: {value.get('integrity')}.",'Restore .nebula/state.sqlite3 from a backup.')
    if not value.get('writable'):
        return check('state','fail','Database is not writable.','Fix permissions on .nebula/state.sqlite3.')
    if value['capacity']=='hard-limit':
        return check('state','fail','Storage hard limit reached: capture and application have stopped.','/nebula maintain to prune expired evidence.')
    if value['capacity']=='soft-limit':
        return check('state','warn','Storage is near its limit.','/nebula maintain to prune expired evidence.')
    return check('state','ok',f"schema {value['schema']}, {value['bytes']} bytes")

def host_check(name,project,host,manifest,runtime):
    problems=[]; other=set()
    for entry in manifest:
        path=Path(entry['path'])
        if entry['kind']=='skill':
            target=Path(entry['after']['link'])
            if not path.is_symlink(): problems.append(f'skill link {path} is missing')
            elif not (path.resolve()/'SKILL.md').is_file(): problems.append(f'skill link points to {target}, which no longer has SKILL.md')
            elif target.resolve()!=(runtime/'skills/nebula').resolve(): other.add(str(target.parents[1]))
        elif entry['kind']=='hooks':
            try: document=json.loads(path.read_text())
            except (OSError,ValueError): document=None
            hooks=document.get('hooks') if isinstance(document,dict) else None
            for event,groups in entry.get('groups',{}).items():
                command=groups[0]['hooks'][0]['command']
                present=isinstance(hooks,dict) and isinstance(hooks.get(event),list) and any(
                    isinstance(g,dict) and any(isinstance(h,dict) and h.get('command')==command for h in g.get('hooks',[])) for g in hooks[event])
                if not present: problems.append(f'{event} hooks are missing from {path}'); continue
                interpreter,script=shlex.split(command)[:2]
                if not Path(interpreter).is_file(): problems.append(f'hook interpreter {interpreter} no longer exists')
                if not Path(script).is_file(): problems.append(f'hook script {script} no longer exists')
                elif Path(script).resolve()!=(runtime/'scripts/nebula_hook.py').resolve(): other.add(str(Path(script).resolve().parents[1]))
    problems=list(dict.fromkeys(problems))
    if problems:
        return check(f'{host} in {name}','fail','; '.join(problems)+'.',
                     f'Reinstall from this checkout: /nebula uninstall {name} --host {host}, then /nebula install {name} --host {host}. If you moved the Nebula checkout, this is expected.')
    if other:
        return check(f'{host} in {name}','warn',f"Installed from another checkout: {', '.join(sorted(other))}.",
                     f'Fine if intended. To use this checkout ({runtime}), reinstall: /nebula uninstall {name} --host {host}, then /nebula install {name} --host {host}.')
    return check(f'{host} in {name}','ok','skill link and hooks in place')

def recovery(root):
    from .install import recovery_entries
    try: values=recovery_entries(root)
    except (OSError,ValueError,KeyError,TypeError,StateUnavailable): return 'unreadable .nebula/install-recovery.json'
    return ', '.join(sorted({f"{v['host']} in {Path(v['project']).name}" for v in values}))

def report(root,mode,checks,all_checks):
    # A large nebula has hundreds of passing checks; by default list only
    # problems, failures first, so the output stays small enough for an agent.
    summary={s:sum(c['status']==s for c in checks) for s in ('ok','warn','fail')}
    result={'root':str(root),'ok':summary['fail']==0,'mode':mode,'summary':summary}
    if all_checks: result['checks']=checks; return result
    problems=sorted((c for c in checks if c['status']!='ok'),key=lambda c:c['status']!='fail')
    result['checks']=problems[:PROBLEM_LIMIT]
    if len(problems)>PROBLEM_LIMIT: result['problems_omitted']=len(problems)-PROBLEM_LIMIT
    return result
