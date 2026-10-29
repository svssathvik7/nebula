"""Measure synthetic analytics bookkeeping and reporting; no hosts or model calls."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.analytics_demo import seed
from nebula.analytics.render import render_html
from nebula.analytics.report import build_report
from nebula.application import claim_application, finish_application
from nebula.feedback import apply_feedback, suggest
from nebula.models import Event, utcnow
from nebula.store import Store


def measure(operation):
    start = time.perf_counter()
    result = operation()
    return (time.perf_counter() - start) * 1000, result


def percentiles(values):
    ordered = sorted(values)
    return {'p50_ms': round(statistics.median(ordered), 3),
            'p95_ms': round(ordered[min(len(ordered)-1, int(.95*len(ordered)))], 3)}


def transitions(root, runs, *, tracked):
    seed(root)
    values = {key: [] for key in ('suggestion', 'feedback', 'completion')}
    with ExitStack() as stack:
        if not tracked:
            for target in ('nebula.feedback.increment', 'nebula.feedback.record_feedback',
                           'nebula.application.increment'):
                stack.enter_context(patch(target, new=lambda *a, **k: None))
        with Store(root) as store:
            lesson = store.get_lesson('validation')
            project = str(root/'wallet')
            now = utcnow()
            for i in range(runs):
                episode = f'benchmark-{i}'
                elapsed, pending = measure(lambda: suggest(store, lesson, session_id='benchmark',
                    episode_id=episode, project=project, context_digest=episode, now=now))
                values['suggestion'].append(elapsed)
                event = Event(episode, 'claude', 'benchmark', 'turn', episode, project, now,
                              'UserPromptSubmit', 'human', 'Synthetic benchmark', episode)
                store.put_event(event)
                store.put_receipt(episode, 'verified-host-submission',
                                  {'verb': 'accept', 'suggestion_id': pending.suggestion_id})
                elapsed, _ = measure(lambda: apply_feedback(store, suggestion_id=pending.suggestion_id,
                    source_event_id=episode, verdict='accept', now=now))
                values['feedback'].append(elapsed)
                fields = dict(lesson_id=lesson.lesson_id, version=1,
                              session_id='benchmark', episode_id=episode)
                assert claim_application(store, **fields, project=project,
                                         context_match=True, permissions_ok=True)
                elapsed, _ = measure(lambda: finish_application(store, **fields,
                    outcome='suitable', source_event_ids=[episode]))
                values['completion'].append(elapsed)
    return {key: percentiles(samples) for key, samples in values.items()}


def run(runs):
    with tempfile.TemporaryDirectory(prefix='nebula-analytics-benchmark-') as temporary:
        root = Path(temporary).resolve()
        baseline = transitions(root/'baseline', runs, tracked=False)
        tracked = transitions(root/'tracked', runs, tracked=True)
        ancestor = root/'reporting'
        for i in range(3):
            seed(ancestor/str(i))
        durations = []
        for _ in range(runs):
            elapsed, report = measure(lambda: build_report(ancestor))
            durations.append(elapsed)
        return {'python': platform.python_version(), 'platform': platform.platform(), 'runs': runs,
                'baseline': 'Same schema/workflow with only analytics instrumentation disabled; not a historical release.',
                'without_tracking': baseline, 'with_tracking': tracked,
                'report_fixture': {'nebulas': 3, 'lesson_versions': 12, 'selected_projects': 6},
                'snapshot_generation': percentiles(durations),
                'payload_bytes': len(json.dumps(report, ensure_ascii=False, separators=(',', ':')).encode()),
                'html_bytes': len(render_html(report).encode()), 'model_calls': 0,
                'units': 'Local milliseconds and UTF-8 bytes; not user time savings.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=100)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('runs must be positive')
    print(json.dumps(run(args.runs), indent=2))
