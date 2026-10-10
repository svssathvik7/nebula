import sqlite3
import unittest
from unittest.mock import patch
from nebula.lifecycle import init_nebula
from nebula.store import Store, StateUnavailable
from nebula.models import timestamp
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
