"""Generate a synthetic multi-Nebula report without touching actual host settings."""
import argparse
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nebula.application import claim_application, finish_application
from nebula.analytics.report import build_report
from nebula.analytics.render import write_report
from nebula.feedback import suggest, apply_feedback
from nebula.lifecycle import init_nebula, set_enabled
from nebula.models import Event, Lesson, utcnow
from nebula.store import Store


def seed(root, *, legacy=False):
    a, b = root / 'wallet', root / 'indexer'
    a.mkdir(parents=True); b.mkdir()
    init_nebula(root, [a, b]); set_enabled(root, True)
    now = utcnow()
    with Store(root) as store:
        values = [
            Lesson('validation', 1, 'workflow', 'Before finishing a small code change',
                   'Run targeted validation before the full suite.', ('verification',),
                   ('Protocol changes require the full suite.',), (),
                   'Synthetic example: get useful feedback early.', 'inferred', ()),
            Lesson('module-layout', 1, 'convention', 'When adding a handwritten module',
                   'Place handwritten modules in src/modules.', ('module',),
                   ('Generated code follows its generator.',), (),
                   'Synthetic example: keep related modules together.', 'inferred', ()),
            Lesson('release', 1, 'preference', 'Before creating a release',
                   'Summarize user-facing behavior and verification.', ('release',), (), (),
                   'Synthetic example: keep release review concrete.', 'inferred', ()),
        ]
        for value in values:
            store.put_lesson(value)
            pending = suggest(store, value, session_id='synthetic', episode_id=value.lesson_id,
                              project=str(a), context_digest='synthetic-context', now=now)
            for i, verdict in enumerate(('accept', 'reject', 'exception') if value.lesson_id == 'module-layout' else ('accept',)):
                key = f'synthetic-{value.lesson_id}-{i}'
                store.put_event(Event(key, 'claude', 'synthetic', 'turn', value.lesson_id,
                                      str(a), now, 'UserPromptSubmit', 'human', 'Synthetic receipt', key))
                acknowledgement = {'verb': verdict, 'suggestion_id': pending.suggestion_id}
                reason = 'Generated module for this task' if verdict == 'exception' else None
                if reason:
                    acknowledgement['reason'] = reason
                store.put_receipt(key, 'verified-host-submission', acknowledgement)
                apply_feedback(store, suggestion_id=pending.suggestion_id, source_event_id=key,
                               verdict=verdict, reason=reason, now=now)
            if value.lesson_id == 'validation':
                for i in range(3):
                    fields = dict(lesson_id=value.lesson_id, version=1, session_id='synthetic',
                                  episode_id=f'apply-{i}')
                    assert claim_application(store, **fields, project=str(b), context_match=True, permissions_ok=True)
                    key = f'synthetic-outcome-{i}'
                    store.put_event(Event(key, 'codex', 'synthetic', 'tool', f'apply-{i}', str(b),
                                          now, 'PostToolUse', 'assistant', 'Synthetic outcome', key))
                    finish_application(store, **fields, outcome='suitable', source_event_ids=[key])
        store.put_lesson(replace(values[2], version=2, action='List verification results before release notes.'))
        if legacy:
            for table in ('analytics_counters','analytics_feedback','analytics_meta'):
                store.connection.execute('DROP TABLE ' + table)
            store.connection.execute('PRAGMA user_version=2')


def demo_report():
    with tempfile.TemporaryDirectory(prefix='nebula-analytics-demo-') as temporary:
        root = Path(temporary).resolve()
        seed(root / 'bitcoin')
        seed(root / 'trading')
        seed(root / 'legacy', legacy=True)
        (root / 'unavailable/.nebula').mkdir(parents=True)
        report = build_report(root)
        report['warnings'].insert(0, 'SYNTHETIC DEMO: receipts and outcomes are fixtures, not real human sessions.')
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(write_report(demo_report(), scan_root=args.output.parent, output=args.output))
