from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile

NOW = '2026-10-07T00:00:00+00:00'

@contextmanager
def workspace():
    with tempfile.TemporaryDirectory(prefix='nebula-test-') as tmp:
        root = Path(tmp) / 'nebula'
        a, b = root / 'a', root / 'b'
        a.mkdir(parents=True)
        b.mkdir()
        yield root.resolve(), a.resolve(), b.resolve()

def event(**changes):
    from nebula.models import Event
    return replace(Event('event-1', 'claude', 's1', 't1', 'e1', '/project',
                         NOW, 'UserPromptSubmit', 'human', 'choose module layout', 'digest-1'), **changes)

def lesson(**changes):
    from nebula.models import Lesson
    return replace(Lesson('layout', 1, 'convention', 'when adding a module',
                          'Place the module in src/modules.', ('module',), (), (),
                          'Keep modules together.', 'inferred', (), False), **changes)

def sample(**changes):
    from nebula.models import Sample
    return replace(Sample('layout', 1, 'e1', 's1', '/project', 'event-1',
                          'positive', 'suitable', NOW), **changes)

def mature_samples(**changes):
    return [sample(episode_id=f'e{i}', session_id=f's{i%3}', project=f'/p{i%2}',
                   source_event_id=f'event-{i}', **{k:v for k,v in changes.items()
                   if k not in ('episode_id','session_id','project','source_event_id')})
            if not {'session_id','project'} & changes.keys() else
            sample(**dict(episode_id=f'e{i}',session_id=f's{i%3}',project=f'/p{i%2}',
                          source_event_id=f'event-{i}', **{} ) | changes)
            for i in range(5)]
