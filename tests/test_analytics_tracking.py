import sqlite3
import unittest
from unittest.mock import patch
from nebula.lifecycle import init_nebula
from nebula.store import Store, StateUnavailable
from nebula.models import timestamp
from nebula.feedback import suggest, apply_feedback
from nebula.application import claim_application, finish_application
from nebula.lifecycle import set_enabled
from nebula.maintenance import prune
from tests.support import event, NOW
from nebula.analytics.tracking import increment, read_counters
from tests.support import workspace, lesson


def make_legacy(store, version=2):
    for table in ('analytics_counters', 'analytics_feedback', 'analytics_meta'):
        store.connection.execute(f'DROP TABLE {table}')
    if version == 1:
        store.connection.execute('DROP TABLE sample_provenance')
    store.connection.execute(f'PRAGMA user_version={version}')


class TrackingTests(unittest.TestCase):
    def test_new_schema_and_zero_counters(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertEqual(read_counters(store.connection)['accepted'], 0)
                since = store.connection.execute("SELECT value FROM analytics_meta WHERE key='since'").fetchone()[0]
                timestamp(since)

    def test_legacy_upgrade_preserves_lessons_without_backfill(self):
        for version in (1, 2):
            with self.subTest(version=version), workspace() as (root, a, b):
                init_nebula(root, [a, b])
                with Store(root) as store:
                    store.put_lesson(lesson())
                    make_legacy(store, version)
                with Store(root) as store:
                    self.assertEqual(store.get_lesson('layout'), lesson())
                    self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
                    self.assertEqual(sum(read_counters(store.connection).values()), 0)

    def test_increment_validation_and_transaction_rollback(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                with self.assertRaises(ValueError):
                    increment(store.connection, lesson_id='layout', version=1, project=str(a), metric='bad')
                with self.assertRaises(RuntimeError), store.transaction():
                    increment(store.connection, lesson_id='layout', version=1, project=str(a), metric='accepted')
                    raise RuntimeError('rollback')
                self.assertEqual(read_counters(store.connection)['accepted'], 0)
                with store.transaction():
                    increment(store.connection, lesson_id='layout', version=1, project=str(a), metric='accepted')
                self.assertEqual(read_counters(store.connection, project=str(a))['accepted'], 1)
                self.assertEqual(read_counters(store.connection, project=str(b))['accepted'], 0)

    def test_failed_migration_is_atomic(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                make_legacy(store)
            with patch('nebula.analytics.tracking.timestamp', side_effect=ValueError('invalid time')):
                with self.assertRaises(ValueError):
                    Store(root)
            with sqlite3.connect(root / '.nebula/state.sqlite3') as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='analytics_meta'").fetchone())

    def test_migration_collision_is_rejected(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                store.connection.execute('PRAGMA user_version=2')
            with self.assertRaises(StateUnavailable):
                Store(root)


class TransitionTests(unittest.TestCase):
    def pending(self, store, project, *, episode='e1'):
        value = lesson()
        store.put_lesson(value)
        return suggest(store, value, session_id='s1', episode_id=episode,
                       project=str(project), context_digest='context', now=NOW)

    def feedback(self, store, pending, verdict, key, reason=None):
        source = event(event_id=key, digest=key, project=pending.project,
                       session_id=pending.session_id, episode_id=pending.episode_id)
        store.put_event(source)
        receipt = {'verb': verdict, 'suggestion_id': pending.suggestion_id}
        if reason is not None:
            receipt['reason'] = reason
        store.put_receipt(key, 'verified-host-submission', receipt)
        return apply_feedback(store, suggestion_id=pending.suggestion_id,
                              source_event_id=key, verdict=verdict, reason=reason, now=NOW)

    def test_suggestion_and_feedback_replay_deduplicate_categories(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                pending = self.pending(store, a)
                self.assertEqual(self.pending(store, a), pending)
                self.feedback(store, pending, 'accept', 'accept')
                self.feedback(store, pending, 'accept', 'accept')
                self.feedback(store, pending, 'reject', 'reject')
                store.bound_raw_events('2026-11-01T00:00:00Z')
                self.feedback(store, pending, 'reject', 'repeat')
                self.feedback(store, pending, 'exception', 'exception', 'one-off route')
                self.feedback(store, pending, 'exception', 'exception-new', 'another route')
                self.feedback(store, pending, 'withdraw', 'withdraw')
                self.feedback(store, pending, 'correct', 'correct')
                self.feedback(store, pending, 'disable', 'disable')
                counters = read_counters(store.connection)
                for metric in ('suggestions','accepted','rejected','exceptions','withdrawn','corrected','disabled'):
                    self.assertEqual(counters[metric], 1, metric)
                self.assertEqual(counters['claims'], 0)

    def test_outcomes_only_count_first_completion_and_survive_retention(self):
        for outcome, metric in (('suitable','successful'), ('failed','failed'), ('unknown','unknown')):
            with self.subTest(outcome=outcome), workspace() as (root, a, b):
                init_nebula(root, [a, b]); set_enabled(root, True)
                with Store(root) as store:
                    pending = self.pending(store, a)
                    self.feedback(store, pending, 'accept', 'accept')
                    fields = dict(lesson_id='layout', version=1, session_id='s1', episode_id='execution')
                    self.assertTrue(claim_application(store, **fields, project=str(b), context_match=True, permissions_ok=True))
                    self.assertFalse(claim_application(store, **fields, project=str(b), context_match=True, permissions_ok=True))
                    store.put_event(event(event_id='outcome', project=str(b)))
                    finish_application(store, **fields, outcome=outcome, source_event_ids=['outcome'])
                    finish_application(store, **fields, outcome=outcome, source_event_ids=['outcome'])
                    self.assertEqual(read_counters(store.connection, project=str(b))['claims'], 1)
                    self.assertEqual(read_counters(store.connection, project=str(b))[metric], 1)
                    before = read_counters(store.connection)
                    with store.transaction():
                        prune(store, '2028-01-01T00:00:00Z')
                    self.assertEqual(read_counters(store.connection), before)

    def test_counter_failure_rolls_back_feedback_and_claim(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b]); set_enabled(root, True)
            with Store(root) as store:
                pending = self.pending(store, a)
                with patch('nebula.feedback.record_feedback', side_effect=RuntimeError('counter interrupted')):
                    with self.assertRaises(RuntimeError):
                        self.feedback(store, pending, 'accept', 'accept')
                self.assertFalse(store.confirmed('layout', 1))
                self.assertEqual(store.get_suggestion(pending.suggestion_id).status, 'pending')
                self.feedback(store, pending, 'accept', 'accept')
                with patch('nebula.application.increment', side_effect=RuntimeError('counter interrupted')):
                    with self.assertRaises(RuntimeError):
                        claim_application(store, lesson_id='layout', version=1, session_id='s1',
                                          episode_id='apply', project=str(a), context_match=True, permissions_ok=True)
                self.assertIsNone(store.application('layout', 1, 's1', 'apply'))

    def test_two_writers_count_one_claim(self):
        from concurrent.futures import ThreadPoolExecutor
        with workspace() as (root, a, b):
            init_nebula(root, [a, b]); set_enabled(root, True)
            with Store(root) as store:
                self.feedback(store, self.pending(store, a), 'accept', 'accept')
            def claim():
                with Store(root) as store:
                    return claim_application(store, lesson_id='layout', version=1, session_id='s1',
                                             episode_id='apply', project=str(a), context_match=True, permissions_ok=True)
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(lambda _: claim(), range(2))), [False, True])
            with Store(root) as store:
                self.assertEqual(read_counters(store.connection)['claims'], 1)
