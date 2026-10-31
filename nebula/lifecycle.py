from pathlib import Path
import json
import os
from .models import Context, digest
from .store import Store
from .roots import read_config

def write_config(root,data):
    path=root/'.nebula/config.json'
    temp=path.with_name('config.tmp-'+os.urandom(6).hex())
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(data,out,sort_keys=True); out.flush(); os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)

def child_project(root,path):
    project=Path(path).resolve(strict=True)
    project.relative_to(root)
    if not project.is_dir() or project==root: raise ValueError('select child project directories')
    return str(project)

def init_nebula(root,projects):
    root=Path(root).resolve(strict=True)
    selected=[child_project(root,p) for p in projects]
    if not selected: raise ValueError('select at least one child project')
    directory=root/'.nebula'
    if directory.exists() or directory.is_symlink():
        raise ValueError('nebula state already exists; refusing to overwrite it')
    directory.mkdir(mode=0o700)
    (directory/'.gitignore').write_text('*\n')
    data={'root':str(root),'projects':sorted(set(selected)),'nebula_id':digest(str(root))[:24],'enabled':False,'mode':'off'}
    write_config(root,data)
    with Store(root,create=True): pass
    return Context(root,root,data['nebula_id'],False)

def set_enabled(root,enabled):
    set_mode(root,'full' if enabled else 'off')

def set_mode(root,mode):
    if mode not in ('off','observe','full'): raise ValueError('invalid nebula mode')
    root=Path(root).resolve()
    with Store(root) as store,store.transaction():
        data=read_config(root)
        data['mode']=mode
        data['enabled']=mode!='off'
        write_config(root,data)
        store.audit('mode',{'mode':mode,'enabled':data['enabled']})

def add_projects(root,projects):
    """Select more children in an existing nebula; memory and mode are kept."""
    root=Path(root).resolve(strict=True); read_config(root)
    requested=list(dict.fromkeys(child_project(root,p) for p in projects))
    with Store(root) as store,store.transaction():
        data=read_config(root)
        added=[p for p in requested if p not in data['projects']]
        data['projects']=sorted(data['projects']+added)
        if added:
            write_config(root,data)
            store.audit('add-project',{'projects':len(added)})
    return {'added':added,'already_selected':[p for p in requested if p not in added],'projects':data['projects']}

def remove_projects(root,projects):
    """Deselect children without deleting lessons. Registrations must be
    uninstalled first so no hooks or recovery records point at a deselected
    child. A deleted child folder can still be removed."""
    from .install import recovery_entries
    root=Path(root).resolve(strict=True); read_config(root)
    requested=list(dict.fromkeys(str(Path(p).resolve()) for p in projects))
    with Store(root) as store,store.transaction():
        data=read_config(root)
        missing=[p for p in requested if p not in data['projects']]
        if missing: raise ValueError(f'project is not selected in this nebula: {missing[0]}')
        remaining=[p for p in data['projects'] if p not in requested]
        if not remaining: raise ValueError('a nebula needs at least one selected project; use off to pause it instead')
        pending={(v['project'],v['host']) for v in recovery_entries(root)}
        for project in requested:
            hosts=[h for h in ('claude','codex') if store.installation(project,h) or (project,h) in pending]
            if hosts: raise ValueError(f'uninstall {project} for host {", ".join(hosts)} before removing it')
        data['projects']=remaining
        write_config(root,data)
        store.audit('remove-project',{'projects':len(requested)})
        orphaned=sorted({v.lesson_id for v in store.lessons() if v.scope_projects and set(v.scope_projects)<=set(requested)})
    return {'removed':requested,'projects':remaining,'lessons_scoped_only_to_removed':orphaned}
