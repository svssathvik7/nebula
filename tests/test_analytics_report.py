from dataclasses import replace
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from nebula.lifecycle import init_nebula, set_enabled
from nebula.store import Store
from nebula.analytics.snapshot import snapshot_nebula, ReadOnlyStore
from nebula.analytics.report import build_report, bound_payload
from nebula.analytics.tracking import increment
from tests.support import workspace, lesson, NOW
from tests import test_analytics_tracking as fixtures


class ReportTests(unittest.TestCase):
    def dump(self, root):
        with closing(sqlite3.connect(root / '.nebula/state.sqlite3')) as db:
            return '\n'.join(db.iterdump())

    def test_all_schemas_report_without_mutation_or_migration(self):
        for version in (1, 2, 3):
            with self.subTest(version=version), workspace() as (root, a, b):
                init_nebula(root, [a, b])
                with Store(root) as store:
                    store.put_lesson(lesson())
                    if version < 3:
                        fixtures.make_legacy(store, version)
                before = self.dump(root)
                config = (root / '.nebula/config.json').read_bytes()
                result = snapshot_nebula(root)
                self.assertTrue(result['available'], result)
                self.assertEqual(result['schema'], version)
                self.assertEqual(result['analytics_since'] is None, version < 3)
                self.assertEqual(self.dump(root), before)
                self.assertEqual((root / '.nebula/config.json').read_bytes(), config)

    def test_counts_versions_and_projects_survive_detail_cap(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                store.put_lesson(lesson())
                store.put_lesson(lesson(version=2))
                store.put_lesson(lesson(lesson_id='other'))
                with store.transaction():
                    increment(store.connection, lesson_id='layout', version=1, project=str(a), metric='successful')
                    increment(store.connection, lesson_id='layout', version=2, project=str(b), metric='accepted')
            report = snapshot_nebula(root, lesson_limit=1)
            self.assertEqual(report['counts']['current_lessons'], 2)
            self.assertEqual(report['tracked_metrics']['successful'], 1)
            self.assertFalse(report['coverage']['details_complete'])
            full = snapshot_nebula(root)
            self.assertEqual(len(full['lessons']), 3)
            self.assertEqual({r['project'] for r in full['metric_rows']}, {str(a),str(b)})

    def test_override_rows_not_executions(self):
        helper = fixtures.TransitionTests()
        with workspace() as (root, a, b):
            init_nebula(root, [a, b]); set_enabled(root, True)
            with Store(root) as store:
                pending = helper.pending(store, a)
                helper.feedback(store, pending, 'reject', 'reject')
            report = snapshot_nebula(root)
            self.assertEqual(report['counts']['unfinished_applications'], 0)
            self.assertEqual(report['tracked_metrics']['successful'], 0)
            self.assertEqual(report['tracked_metrics']['rejected'], 1)

    def test_unavailable_is_not_a_zero_nebula(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            (b / '.nebula').mkdir()
            report = build_report(root.parent)
            self.assertEqual(report['summary']['discovered_nebulas'], 2)
            self.assertEqual(report['summary']['available_nebulas'], 1)
            bad = next(n for n in report['nebulas'] if not n['available'])
            self.assertNotIn('tracked_metrics', bad)

    def test_v1_confirmation_is_not_verified(self):
        helper = fixtures.TransitionTests()
        with workspace() as (root, a, b):
            init_nebula(root, [a, b]); set_enabled(root, True)
            with Store(root) as store:
                helper.feedback(store, helper.pending(store, a), 'accept', 'accept')
                fixtures.make_legacy(store, 1)
            result = snapshot_nebula(root)
            self.assertFalse(result['lessons'][0]['confirmed'])
            self.assertFalse(result['lessons'][0]['score']['mature'])

    def test_readonly_snapshot_coherent_while_writer_commits(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with ReadOnlyStore(root) as reader:
                before = reader.connection.execute('SELECT count(*) FROM lessons').fetchone()[0]
                with Store(root) as writer:
                    writer.put_lesson(lesson())
                self.assertEqual(reader.connection.execute('SELECT count(*) FROM lessons').fetchone()[0], before)
                with self.assertRaises(sqlite3.OperationalError):
                    reader.connection.execute('DELETE FROM lessons')
            self.assertEqual(snapshot_nebula(root)['counts']['current_lessons'], 1)

    def test_empty_report_and_payload_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = build_report(Path(temporary))
            self.assertEqual(result['summary']['available_nebulas'], 0)
            result['nebulas'] = [{'available': True, 'lessons': [{'lesson':{'action':'x'*10000}}],
                                  'activity': [], 'metric_rows': [], 'coverage': {'details_complete':True}}]
            bound_payload(result, max_bytes=3000)
            self.assertFalse(result['nebulas'][0]['coverage']['details_complete'])
            self.assertTrue(result['warnings'])

    def test_symlinked_state_and_corrupt_counters_unavailable(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                store.connection.execute("DELETE FROM analytics_meta WHERE key='since'")
            self.assertFalse(snapshot_nebula(root)['available'])
            (b / '.nebula').symlink_to(root / '.nebula', target_is_directory=True)
            self.assertFalse(snapshot_nebula(b)['available'])

    def test_malformed_audit_root_preserves_healthy_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary).resolve()
            for name in ('bad', 'healthy'):
                root = ancestor/name; child = root/'project'; child.mkdir(parents=True)
                init_nebula(root, [child])
                with Store(root) as store:
                    store.put_lesson(lesson())
                    if name == 'bad': store.audit('malformed', [])
            report = build_report(ancestor)
            self.assertEqual(report['summary']['available_nebulas'], 1)
            bad = next(n for n in report['nebulas'] if not n['available'])
            self.assertIn('audit', bad['diagnostic'])

    def test_application_activity_has_execution_project(self):
        from examples.analytics_demo import seed
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()/'nebula'; seed(root)
            report = snapshot_nebula(root)
            executions = [a for a in report['activity'] if a['kind'] in ('application-claim','application-finish')]
            self.assertEqual(len(executions), 6)
            self.assertEqual({a['project'] for a in executions}, {str(root/'indexer')})
            # Historical rows without project identity are deliberately unresolved.
            with Store(root) as store:
                store.audit('application-claim', {'lesson_id':'validation','version':1,'episode_id':'old'})
            self.assertIsNone(snapshot_nebula(root)['activity'][0]['project'])

    def test_recent_activity_cap_marks_detail_coverage(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                for i in range(101): store.audit('retained', {'sequence':i})
            report = snapshot_nebula(root)
            self.assertEqual(len(report['activity']), 100)
            self.assertFalse(report['coverage']['details_complete'])
            self.assertTrue(any('activity' in w.lower() for w in report['warnings']))
