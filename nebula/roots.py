from pathlib import Path
import json
from .models import Context
from .store import StateUnavailable

def read_config(root):
    directory=Path(root)/'.nebula'
    config=directory/'config.json'
    if directory.is_symlink() or config.is_symlink():
        raise StateUnavailable('nebula configuration must not be a symlink')
    try:
        data=json.loads(config.read_text())
        if data['root']!=str(Path(root).resolve()) or type(data['enabled']) is not bool:
            raise ValueError('invalid nebula root/state')
        if not data['projects'] or not isinstance(data['projects'],list): raise ValueError('invalid projects')
        for p in data['projects']:
            project=Path(p).resolve()
            project.relative_to(Path(root).resolve())
            if str(project)!=p or project==Path(root).resolve(): raise ValueError('invalid project')
        return data
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise StateUnavailable('nebula configuration unavailable') from exc

def resolve_context(cwd):
    current=Path(cwd).resolve()
    for ancestor in (current,*current.parents):
        if (ancestor/'.nebula').exists() or (ancestor/'.nebula').is_symlink():
            data=read_config(ancestor)
            if current==ancestor:
                return Context(ancestor,current,data['nebula_id'],data['enabled'])
            projects=[]
            for name in data['projects']:
                project=Path(name)
                if current.is_relative_to(project): projects.append(project)
            if not projects: return None
            project=max(projects,key=lambda x:len(x.parts))
            return Context(ancestor,project,data['nebula_id'],data['enabled'])
    return None
