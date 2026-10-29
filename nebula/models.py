from dataclasses import dataclass, asdict, fields
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
from typing import get_origin

@dataclass(frozen=True)
class Context:
    root: Path
    project: Path
    nebula_id: str
    enabled: bool
    mode: str = 'off'

@dataclass(frozen=True)
class Event:
    event_id: str
    host: str
    session_id: str
    turn_id: str
    episode_id: str
    project: str
    timestamp: str
    kind: str
    origin: str
    hint: str
    digest: str

@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    version: int
    kind: str
    trigger: str
    action: str
    context_tags: tuple[str, ...]
    exceptions: tuple[str, ...]
    scope_projects: tuple[str, ...]
    rationale: str
    rationale_source: str
    evidence_ids: tuple[str, ...]
    disabled: bool = False

@dataclass(frozen=True)
class Sample:
    lesson_id: str
    version: int
    episode_id: str
    session_id: str
    project: str
    source_event_id: str
    verdict: str
    outcome: str
    timestamp: str

@dataclass(frozen=True)
class Score:
    observational_mature: bool
    observational_confidence: float
    mature: bool
    confidence: float
    positives: int
    negatives: int
    successful_episodes: int
    rejection_penalty: float = 0.0

@dataclass(frozen=True)
class Suggestion:
    suggestion_id: str
    lesson_id: str
    version: int
    session_id: str
    episode_id: str
    project: str
    context_digest: str
    created_at: str
    status: str

@dataclass(frozen=True)
class Decision:
    mode: str
    reason: str
    lesson_id: str
    version: int
    score: Score | None

TUPLES = {'context_tags','exceptions','scope_projects','evidence_ids'}

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp must include timezone')
    return parsed.astimezone(timezone.utc)

def dump(value):
    return json.dumps(asdict(value) if hasattr(value,'__dataclass_fields__') else value,
                      sort_keys=True, separators=(',',':'), ensure_ascii=False, default=str)

def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()

def load(cls, value):
    data=json.loads(value) if isinstance(value,str) else dict(value)
    allowed={f.name for f in fields(cls)}
    if data.keys()-allowed:
        raise ValueError('unknown record fields: '+', '.join(sorted(data.keys()-allowed)))
    for key in TUPLES & data.keys():
        if not isinstance(data[key],(list,tuple)) or any(not isinstance(x,str) for x in data[key]):
            raise ValueError(f'{key} must be a string list')
        data[key]=tuple(data[key])
    try:
        result=cls(**data)
    except TypeError as exc:
        raise ValueError('invalid record fields') from exc
    validate(result)
    return result

def validate(value):
    for f in fields(value):
        item=getattr(value,f.name)
        if f.type is str and not isinstance(item,str): raise ValueError(f'{f.name} must be text')
        if f.type is bool and type(item) is not bool: raise ValueError(f'{f.name} must be boolean')
        if f.type is int and type(item) is not int: raise ValueError(f'{f.name} must be integer')
        if get_origin(f.type) is tuple and (not isinstance(item,tuple) or any(not isinstance(x,str) for x in item)):
            raise ValueError(f'{f.name} must be a string tuple')
        if isinstance(item,str) and len(item)>2048:
            raise ValueError(f'{f.name} exceeds limit')
        if isinstance(item,tuple) and (len(item)>32 or any(len(x)>1024 for x in item)):
            raise ValueError(f'{f.name} exceeds limit')
    for key in ('lesson_id','event_id','suggestion_id'):
        if hasattr(value,key) and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',getattr(value,key)):
            raise ValueError(f'invalid {key}')
    if hasattr(value,'timestamp'): timestamp(value.timestamp)
    if hasattr(value,'version') and (type(value.version) is not int or value.version<1):
        raise ValueError('version must be a positive integer')
    if isinstance(value,Event):
        if value.host not in ('claude','codex') or value.origin not in ('human','assistant','subagent','system','unknown'):
            raise ValueError('invalid host or origin')
        if not value.session_id or not value.episode_id or len(value.hint)>512:
            raise ValueError('invalid event metadata')
    if isinstance(value,Lesson):
        if value.kind not in ('preference','convention','decision-heuristic','workflow'):
            raise ValueError('invalid lesson kind')
        if not value.trigger.strip() or not value.action.strip() or len(value.trigger)>512 or len(value.action)>1024:
            raise ValueError('invalid trigger/action')
        if value.rationale_source not in ('human','inferred','unspecified') or type(value.disabled) is not bool:
            raise ValueError('invalid rationale or disabled state')
    if isinstance(value,Sample):
        if value.verdict not in ('positive','negative') or value.outcome not in ('suitable','failed','unknown'):
            raise ValueError('invalid sample')
