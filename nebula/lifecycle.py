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

def init_nebula(root,projects):
    root=Path(root).resolve(strict=True)
    selected=[]
    for p in projects:
        project=Path(p).resolve(strict=True)
        project.relative_to(root)
        if not project.is_dir() or project==root: raise ValueError('select child project directories')
        selected.append(str(project))
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
