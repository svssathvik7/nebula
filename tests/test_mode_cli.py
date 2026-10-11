import json
import subprocess
import sys
import unittest
from pathlib import Path
from dataclasses import asdict

from nebula.roots import read_config
from nebula.store import Store
from nebula.lessons import record_lesson
from tests.support import workspace, event, lesson

RUNTIME = Path(__file__).resolve().parents[1]


class ModeCliTests(unittest.TestCase):
    def run_cli(self, cwd, *args, input=None, skill=False):
        launcher = RUNTIME / ('skills/nebula/scripts/nebula.py' if skill else 'scripts/nebula.py')
        return subprocess.run([sys.executable, str(launcher), *map(str, args)],
                              cwd=cwd, input=input, text=True, capture_output=True)

    def test_observe_capture_review_and_full_roundtrip_from_child(self):
        with workspace() as (root, a, b):
            initialized = self.run_cli(a, 'init', root, '--project', a)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            selected = self.run_cli(a, 'mode', 'observe', skill=True)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertEqual(json.loads(selected.stdout), {'mode': 'observe', 'enabled': True})
            payload = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(a),
                       'session_id': 'passive', 'prompt': 'Keep testing modules locally.'}
            captured = self.run_cli(a, 'observe', '--host', 'codex', input=json.dumps(payload))
            self.assertEqual(captured.returncode, 0, captured.stderr)
            key = json.loads(captured.stdout)['event_id']
            self.assertIsNotNone(key)
            status = self.run_cli(a, 'status')
            self.assertEqual(status.returncode, 0, status.stderr)
            value = json.loads(status.stdout)
            self.assertEqual(value['mode'], 'observe')
            self.assertEqual(value['health']['mode'], 'observe')
            self.assertEqual(value['recent_events'][0]['event_id'], key)
            with Store(root) as store:
                store.set_meta('candidate-note', 'retained')
                self.assertIsNone(store.receipt(key))
            for command, expected in [('off', 'off'), ('on', 'full')]:
                changed = self.run_cli(a, command)
                self.assertEqual(changed.returncode, 0, changed.stderr)
                self.assertEqual(json.loads(changed.stdout)['mode'], expected)
            with Store(root) as store:
                self.assertIsNotNone(store.get_event(key))
                self.assertEqual(store.get_meta('candidate-note'), 'retained')
            self.assertEqual(read_config(root)['mode'], 'full')

    def test_invalid_mode_and_unselected_workspace_do_not_change_state(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            before = (root / '.nebula/config.json').read_bytes()
            for cwd, args in [(a, ('mode', 'broken')), (b, ('mode', 'observe'))]:
                result = self.run_cli(cwd, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / '.nebula/config.json').read_bytes(), before)
            for mode in ('observe', 'off', 'full'):
                result = self.run_cli(b, 'mode', mode, '--root', root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(read_config(root)['mode'], mode)


    def test_on_modes_preserve_captured_evidence_and_candidate_lessons(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            self.assertEqual(self.run_cli(a, 'mode', 'observe').returncode, 0)
            payload = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(a),
                       'session_id': 'passive', 'prompt': 'Keep testing modules locally.'}
            captured = self.run_cli(a, 'observe', '--host', 'codex', input=json.dumps(payload))
            self.assertEqual(captured.returncode, 0, captured.stderr)
            key = json.loads(captured.stdout)['event_id']
            with Store(root) as store:
                record_lesson(store, asdict(lesson(evidence_ids=(key,))))
                before_event = store.get_event(key)
                before_lesson = store.get_lesson('layout')
            for args, expected in [(('on',), 'full'), (('on', 'observe'), 'observe'),
                                   (('on', 'full'), 'full'), (('off',), 'off'),
                                   (('on', 'observe'), 'observe'), (('on',), 'full')]:
                with self.subTest(args=args):
                    changed = self.run_cli(a, *args, skill=True)
                    self.assertEqual(changed.returncode, 0, changed.stderr)
                    self.assertEqual(json.loads(changed.stdout),
                                     {'mode': expected, 'enabled': expected != 'off'})
                    self.assertEqual(read_config(root)['mode'], expected)
                    with Store(root) as store:
                        self.assertEqual(store.get_event(key), before_event)
                        self.assertEqual(store.get_lesson('layout'), before_lesson)
                        self.assertIsNone(store.confirmation('layout', 1))
                        self.assertEqual(store.samples('layout', 1), [])

    def test_on_invalid_modes_leave_configuration_and_audit_unchanged(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            self.assertEqual(self.run_cli(a, 'mode', 'observe').returncode, 0)
            before = (root / '.nebula/config.json').read_bytes()
            with Store(root) as store:
                audit_count = store.connection.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
            for mode in ('off', 'broken', '', 'OBSERVE'):
                with self.subTest(mode=mode):
                    result = self.run_cli(a, 'on', mode)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual((root / '.nebula/config.json').read_bytes(), before)
                    with Store(root) as store:
                        self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM audit').fetchone()[0],
                                         audit_count)

    def test_status_summary_stays_bounded_as_lesson_catalog_grows(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            self.assertEqual(self.run_cli(a, 'mode', 'observe').returncode, 0)
            outputs = []
            for count in (0, 1, 1000):
                with Store(root) as store:
                    store.put_event(event(project=str(a)))
                    for i in range(count):
                        store.put_lesson(lesson(lesson_id=f'candidate-{i}', evidence_ids=('event-1',)))
                result = self.run_cli(a, 'status', '--summary', skill=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'mode': 'observe', 'enabled': True})
                self.assertLess(len(result.stdout.encode()), 128)
                outputs.append(result.stdout)
            self.assertEqual(len(set(outputs)), 1)
            detailed = self.run_cli(a, 'status')
            self.assertEqual(detailed.returncode, 0, detailed.stderr)
            value = json.loads(detailed.stdout)
            self.assertEqual(len(value['lessons']), 1000)
            self.assertEqual(value['recent_events'][0]['event_id'], 'event-1')
            self.assertEqual(value['health']['mode'], 'observe')

    def test_status_summary_refreshes_modes_and_reads_legacy_without_rewriting(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            for mode in ('off', 'observe', 'full', 'observe'):
                self.assertEqual(self.run_cli(a, 'mode', mode).returncode, 0)
                result = self.run_cli(b, 'status', '--summary', '--root', root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'mode': mode, 'enabled': mode != 'off'})
            path = root / '.nebula/config.json'
            for enabled, expected in ((False, 'off'), (True, 'full')):
                data = json.loads(path.read_text())
                data.pop('mode', None)
                data['enabled'] = enabled
                path.write_text(json.dumps(data))
                before = path.read_bytes()
                result = self.run_cli(a, 'status', '--summary')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'mode': expected, 'enabled': enabled})
                self.assertEqual(path.read_bytes(), before)

    def test_status_summary_withholds_mode_for_unavailable_state(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            path = root / '.nebula/config.json'
            original = path.read_text()
            data = json.loads(original)
            data['mode'] = 'observe'  # enabled is still false: inconsistent state.
            path.write_text(json.dumps(data))
            result = self.run_cli(a, 'status', '--summary', '--root', root)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
            path.write_text(original)
            (root / '.nebula/state.sqlite3').unlink()
            result = self.run_cli(a, 'status', '--summary', '--root', root)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, '')
