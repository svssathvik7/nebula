"""Reviewable registration; only exact manifest-owned changes are removed."""
import json,os,shlex,stat,sys,tomllib
from pathlib import Path
from .models import dump
from .roots import read_config,resolve_context
from .store import Store

HOSTS={'claude','codex'}

def write_atomic(path,text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.nebula-'+os.urandom(6).hex())
    # Keep the permissions of a file the user already has; new files stay private.
    mode=stat.S_IMODE(path.stat().st_mode) if path.is_file() and not path.is_symlink() else 0o600
    try:
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as out:
            out.write(text); out.flush(); os.fsync(out.fileno())
        os.chmod(temporary,mode)
        os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)

def render_json(document,like=None):
    """Serialize host settings in the style of the user's existing file, keeping key order."""
    text=(like or {}).get('text','').strip()
    if text and '\n' not in text: return json.dumps(document,separators=(',',':'),ensure_ascii=False)+'\n'
    indent=next((len(line)-len(line.lstrip(' ')) for line in text.splitlines()[1:] if line.startswith(' ')),2)
    return json.dumps(document,indent=indent,ensure_ascii=False)+'\n'

def usable_hooks_document(document):
    hooks=document.get('hooks',{}) if isinstance(document,dict) else None
    return isinstance(hooks,dict) and all(isinstance(v,list) for v in hooks.values())

def snapshot(path):
    path=Path(path)
    if path.is_symlink(): return {'link':os.readlink(path)}
    if path.exists():
        if not path.is_file(): raise ValueError(f'configuration collision: {path}')
        return {'text':path.read_text()}
    return None

def safe_parent(path,project):
    for parent in (path.parent,*path.parent.parents):
        if parent==project: break
        if parent.is_symlink(): raise ValueError(f'symlinked configuration directory: {parent}')

def hook_groups(runtime,host):
    command=' '.join(shlex.quote(x) for x in (sys.executable,str(runtime.resolve()/'scripts/nebula_hook.py'),'--host',host))
    groups={}
    for name in ('SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop'):
        group={'hooks':[{'type':'command','command':command,'timeout':1}]}
        if name in ('PreToolUse','PostToolUse'):
            # Codex uses a different tool namespace; capturing all is cheap
            # and excludes raw commands/output from persisted metadata.
            group['matcher']='.*'
        groups[name]=[group]
    return groups

def recovery_entries(root):
    path=Path(root)/'.nebula/install-recovery.json'
    if path.is_symlink(): raise ValueError('installation recovery file must not be a symlink')
    if not path.exists(): return []
    if path.stat().st_size>1024*1024: raise ValueError('installation recovery record too large')
    values=json.loads(path.read_text())
    if not isinstance(values,list): raise ValueError('invalid installation recovery record')
    selected=read_config(root)['projects']
    for value in values:
        project=Path(value['project']); target=Path(value['path'])
        allowed={project/'.claude/skills/nebula',project/'.agents/skills/nebula',
                 project/'.claude/settings.local.json',project/'.codex/hooks.json',project/'.codex/config.toml'}
        if value['root']!=str(Path(root).resolve()) or str(project) not in selected or target not in allowed:
            raise ValueError('installation recovery scope mismatch')
    return values

def write_recovery(root,entries):
    path=Path(root)/'.nebula/install-recovery.json'
    if entries:
        serialized=dump(entries)+'\n'
        if len(serialized.encode())>1024*1024: raise ValueError('installation recovery record exceeds 1 MiB')
        write_atomic(path,serialized)
    else: path.unlink(missing_ok=True)

def ownership_entry(change):
    value=dict(change)
    value['before']=value.pop('original_before',value['before'])
    value['after']=value.pop('original_after',value['after'])
    value.pop('recovery',None)
    return value

def plan_install(root,projects,hosts,runtime):
    root=Path(root).resolve(); runtime=Path(runtime).resolve(strict=True); config=read_config(root)
    if not (runtime/'skills/nebula/SKILL.md').is_file(): raise ValueError('runtime skill is missing')
    changes=[]; recovery=recovery_entries(root)
    with Store(root) as store:
        for project in dict.fromkeys(Path(p).resolve(strict=True) for p in projects):
            context=resolve_context(project)
            if str(project) not in config['projects'] or context is None or context.root!=root or context.project!=project:
                raise ValueError('installation project is not selected in this nebula')
            for host in dict.fromkeys(hosts):
                if host not in HOSTS: raise ValueError('unsupported host')
                manifest=store.installation(str(project),host) or []
                pending=[v for v in recovery if v['project']==str(project) and v['host']==host]
                owned=manifest+pending
                link=project/('.claude' if host=='claude' else '.agents')/'skills/nebula'
                path=project/('.claude/settings.local.json' if host=='claude' else '.codex/hooks.json')
                for target in (link,path): safe_parent(target,project)
                if link.exists() or link.is_symlink():
                    if not any(v['kind']=='skill' and v['path']==str(link) for v in owned) or not link.is_symlink() or link.resolve()!=runtime/'skills/nebula': raise ValueError(f'skill collision: {link}')
                if path.is_symlink(): raise ValueError('hook configuration must not be a symlink')
                before=snapshot(path)
                document=json.loads(before['text']) if before else {}
                if not isinstance(document,dict) or not isinstance(document.get('hooks',{}),dict): raise ValueError('invalid hooks configuration')
                if any(not isinstance(v,list) for v in document.get('hooks',{}).values()): raise ValueError('hook groups must be arrays')
                groups=hook_groups(runtime,host)
                if host=='codex':
                    layer=project/'.codex/config.toml'; safe_parent(layer,project)
                    if layer.is_symlink(): raise ValueError('config layer must not be a symlink')
                    layer_before=snapshot(layer)
                    if layer_before:
                        inline=tomllib.loads(layer_before['text']).get('hooks',{})
                        if isinstance(inline,dict):
                            for name,entries in inline.items():
                                if name in groups and isinstance(entries,list):
                                    command=groups[name][0]['hooks'][0]['command']
                                    if any(any(h.get('command')==command for h in e.get('hooks',[]) if isinstance(h,dict)) for e in entries if isinstance(e,dict)):
                                        del groups[name]
                    else:
                        changes.append({'root':str(root),'project':str(project),'host':host,'kind':'config','path':str(layer),'before':None,'after':{'text':''}})
                if not link.exists() and not link.is_symlink():
                    changes.append({'root':str(root),'project':str(project),'host':host,'kind':'skill','path':str(link),'before':None,'after':{'link':str(runtime/'skills/nebula')}})
                additions={}
                for name,values in groups.items():
                    entries=document.get('hooks',{}).get(name,[])
                    existing_commands={h.get('command') for e in entries if isinstance(e,dict) for h in e.get('hooks',[]) if isinstance(h,dict)}
                    missing=[g for g in values if g['hooks'][0]['command'] not in existing_commands]
                    if missing: additions[name]=missing
                additions={name:values for name,values in additions.items() if values}
                if additions:
                    merged=json.loads(json.dumps(document)); merged.setdefault('hooks',{})
                    for name,values in additions.items(): merged['hooks'].setdefault(name,[]).extend(values)
                    changes.append({'root':str(root),'project':str(project),'host':host,'kind':'hooks','path':str(path),'before':before,'after':{'text':render_json(merged,before)},'groups':additions})
    paths={v['path'] for v in changes}
    requested={(str(Path(p).resolve()),h) for p in projects for h in hosts}
    for old in recovery:
        if (old['project'],old['host']) not in requested: continue
        current=snapshot(old['path'])
        if old['path'] in paths:
            change=next(v for v in changes if v['path']==old['path'])
            change['original_before']=old['before']
            if old['kind']=='hooks':
                for name,groups in old.get('groups',{}).items():
                    additions=change.setdefault('groups',{}).setdefault(name,[])
                    additions.extend(g for g in groups if g not in additions)
            continue
        if current is None: continue
        if old['kind']=='skill' and current!=old['after']: raise ValueError('interrupted skill link was modified')
        changes.append({**old,'before':current,'after':current,'original_before':old['before'],'original_after':old['after'],'recovery':True})
    return changes

def install(changeset):
    if not changeset: return {'installed':[]}
    roots={v['root'] for v in changeset}
    if len(roots)!=1: raise ValueError('changeset must belong to one nebula')
    for change in changeset:
        project=Path(change['project']); path=Path(change['path']); safe_parent(path,project)
        if not path.is_relative_to(project) or snapshot(path)!=change['before']: raise ValueError('installation plan is stale')
    applied=[]
    root=Path(next(iter(roots)))
    pending=recovery_entries(root)
    processed={v['path'] for v in changeset}
    remaining=[v for v in pending if v['path'] not in processed]
    write_recovery(root,remaining+[ownership_entry(v) for v in changeset])
    with Store(Path(next(iter(roots)))) as store:
        try:
            with store.transaction():
                for change in changeset:
                    path=Path(change['path']); path.parent.mkdir(parents=True,exist_ok=True)
                    if change['after']!=change['before']:
                        if change['kind']=='skill': path.symlink_to(change['after']['link'],target_is_directory=True)
                        else: write_atomic(path,change['after']['text'])
                        applied.append(change)
                for project,host in {(v['project'],v['host']) for v in changeset}:
                    manifest=store.installation(project,host) or []
                    additions=[ownership_entry(v) for v in changeset if v['project']==project and v['host']==host]
                    manifest.extend(v for v in additions if v not in manifest)
                    store.connection.execute('INSERT INTO installations VALUES(?,?,?) ON CONFLICT(project,host) DO UPDATE SET data=excluded.data',(project,host,dump(manifest)))
                store.audit('install',{'entries':len(applied)})
        except BaseException:
            for change in reversed(applied):
                path=Path(change['path'])
                if snapshot(path)==change['after']:
                    if change['before'] is None: path.unlink()
                    else: write_atomic(path,change['before']['text'])
            raise
    write_recovery(root,remaining)
    return {'installed':[v['path'] for v in changeset]}

def uninstall(root,project,host):
    root=Path(root).resolve(); project=Path(project).resolve(); skipped=[]; removed=[]; retained=[]
    with Store(root) as store:
        pending=recovery_entries(root)
        unfinished=[v for v in pending if v['project']==str(project) and v['host']==host]
        manifest=store.installation(str(project),host) or []
        manifest.extend(v for v in unfinished if v not in manifest)
        for change in reversed(manifest):
            path=Path(change['path']); safe_parent(path,project)
            current=snapshot(path)
            if current is None: continue
            if change['kind']=='hooks' and not path.is_symlink():
                try: document=json.loads(current['text'])
                except (ValueError,KeyError,RecursionError): document=None
                if not usable_hooks_document(document): skipped.append(str(path)); retained.append(change); continue
                try: original=json.loads(change['before']['text']) if change['before'] else {}
                except ValueError: original={}
                original_hooks=original.get('hooks',{}) if usable_hooks_document(original) else {}
                modified=False
                for name,groups in change['groups'].items():
                    entries=document.get('hooks',{}).get(name,[])
                    for group in groups:
                        if group in entries: entries.remove(group)
                        else:
                            # A missing entry is already removed; a changed
                            # command with the same launcher is user-owned now.
                            command=group['hooks'][0]['command']
                            if any(any(h.get('command')==command for h in e.get('hooks',[]) if isinstance(h,dict)) for e in entries if isinstance(e,dict)): modified=True
                    # Drop only keys Nebula created; an empty key the user had stays.
                    if not entries and name in document.get('hooks',{}) and name not in original_hooks: del document['hooks'][name]
                if not document.get('hooks') and 'hooks' not in original: document.pop('hooks',None)
                if modified: skipped.append(str(path)); retained.append(change)
                if document=={} and change['before'] is None: path.unlink()
                elif change['before'] and document==original: write_atomic(path,change['before']['text'])
                else: write_atomic(path,render_json(document,current))
                removed.append(str(path)); continue
            if current!=change['after']: skipped.append(str(path)); retained.append(change); continue
            if change['before'] is None: path.unlink()
            else: write_atomic(path,change['before']['text'])
            removed.append(str(path))
        with store.transaction():
            if retained: store.connection.execute('UPDATE installations SET data=? WHERE project=? AND host=?',(dump(list(reversed(retained))),str(project),host))
            else: store.connection.execute('DELETE FROM installations WHERE project=? AND host=?',(str(project),host))
            store.audit('uninstall',{'project':str(project),'host':host,'skipped':skipped})
    write_recovery(root,[v for v in pending if v not in unfinished])
    return {'removed':removed,'skipped':skipped}
