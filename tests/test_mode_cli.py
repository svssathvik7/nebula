import json
import subprocess
import sys
import unittest
from pathlib import Path

from nebula.roots import read_config
from nebula.store import Store
from tests.support import workspace

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
