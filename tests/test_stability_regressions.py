"""Regression tests for the defects found in the October 2026 stability audit."""
import io,json,os,sqlite3,stat,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from nebula.capture import capture_event, run_hook
from nebula.feedback import suggest
from nebula.install import plan_install, install, uninstall
from nebula.lifecycle import init_nebula, set_mode
from nebula.models import utcnow
from nebula.store import Store
from tests.support import workspace, lesson, NOW

RUNTIME=Path(__file__).resolve().parents[1]
HOOK=RUNTIME/'scripts/nebula_hook.py'

def payload(project, session, **changes):
    return {'hook_event_name':'SessionStart','session_id':session,'cwd':str(project),**changes}

def stored_sessions(root):
    with Store(root) as store:
        rows=store.connection.execute('SELECT data FROM events').fetchall()
    return {json.loads(row['data'])['session_id'] for row in rows}


class ConcurrentCaptureTests(unittest.TestCase):
    def test_failed_session_maintenance_still_captures_event(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'full')
            with patch('nebula.maintenance.session_maintenance', side_effect=sqlite3.OperationalError('database is locked')):
                key = capture_event(root, 'claude', payload(a, 'locked'), now=utcnow())
            self.assertIsNotNone(key)
            self.assertIn('locked', stored_sessions(root))

    def test_simultaneous_hook_processes_store_every_event(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'full')
            count = 40
            processes = [subprocess.Popen([sys.executable, str(HOOK), '--host', 'claude'],
                                          stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                         for _ in range(count)]
            for index, process in enumerate(processes):
                process.stdin.write(json.dumps(payload(a, f'concurrent-{index}')).encode()); process.stdin.close()
            for process in processes: self.assertEqual(process.wait(timeout=60), 0)
            self.assertEqual({s for s in stored_sessions(root) if s.startswith('concurrent-')},
                             {f'concurrent-{i}' for i in range(count)})


class OffModeSuggestionTests(unittest.TestCase):
    def test_suggestions_are_rejected_while_off(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            with Store(root) as store:
                value = lesson(); store.put_lesson(value)
                with self.assertRaisesRegex(ValueError, 'off'):
                    suggest(store, value, session_id='s1', episode_id='e1', project=str(a), context_digest='context', now=NOW)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM suggestions').fetchone()[0], 0)
            set_mode(root, 'full')
            with Store(root) as store:
                pending = suggest(store, store.get_lesson('layout'), session_id='s1', episode_id='e1', project=str(a), context_digest='context', now=NOW)
                self.assertEqual(pending.status, 'pending')


class MalformedInputTests(unittest.TestCase):
    NESTED = b'{"a":' + b'[' * 20000 + b']' * 20000 + b'}'

    def test_hook_exits_cleanly_on_deeply_nested_json(self):
        self.assertEqual(run_hook('claude', io.BytesIO(self.NESTED), io.StringIO()), 0)
        result = subprocess.run([sys.executable, str(HOOK), '--host', 'codex'], input=self.NESTED, capture_output=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))

    def test_cli_reports_deeply_nested_json_as_an_error(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            result = subprocess.run([sys.executable, str(RUNTIME/'scripts/nebula.py'), 'record-lesson', '--root', str(root), '--stdin'],
                                    input=self.NESTED, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stderr)['error'], 'RecursionError')
            self.assertNotIn(b'Traceback', result.stderr)


class UninstallMalformedSettingsTests(unittest.TestCase):
    def test_uninstall_skips_unusable_settings_and_removes_other_entries(self):
        for content in ('[]', '{"hooks":[]}', '{"hooks":{"Stop":{"x":1}}}'):
            with self.subTest(content=content), workspace() as (root, a, b):
                init_nebula(root, [a]); install(plan_install(root, [a], ['claude'], RUNTIME))
                settings = a/'.claude/settings.local.json'; settings.write_text(content)
                result = uninstall(root, a, 'claude')
                self.assertIn(str(settings), result['skipped'])
                self.assertEqual(settings.read_text(), content)
                self.assertFalse((a/'.claude/skills/nebula').exists())


class SettingsPreservationTests(unittest.TestCase):
    def test_roundtrip_restores_original_bytes_mode_and_empty_keys(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            settings = a/'.claude/settings.local.json'; settings.parent.mkdir()
            original = ('{\n    "permissions": {"allow": ["Bash(ls)"]},\n    "hooks": {\n'
                        '        "PreToolUse": [],\n        "Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]\n    }\n}\n')
            settings.write_text(original); os.chmod(settings, 0o644)
            install(plan_install(root, [a], ['claude'], RUNTIME))
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o644)
            installed = json.loads(settings.read_text())
            self.assertEqual(list(installed), ['permissions', 'hooks'])
            self.assertEqual(installed['hooks']['Stop'][0]['hooks'][0]['command'], 'echo mine')
            uninstall(root, a, 'claude')
            self.assertEqual(settings.read_text(), original)
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o644)

    def test_user_edit_after_install_keeps_order_and_empty_keys(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            settings = a/'.claude/settings.local.json'; settings.parent.mkdir()
            settings.write_text(json.dumps({'permissions': {}, 'hooks': {'PreToolUse': []}}, indent=2))
            install(plan_install(root, [a], ['claude'], RUNTIME))
            data = json.loads(settings.read_text()); data['env'] = {'ADDED': '1'}
            settings.write_text(json.dumps(data, indent=2))
            uninstall(root, a, 'claude')
            result = json.loads(settings.read_text())
            self.assertEqual(result, {'permissions': {}, 'hooks': {'PreToolUse': []}, 'env': {'ADDED': '1'}})
            self.assertEqual(list(result), ['permissions', 'hooks', 'env'])


if __name__ == '__main__':
    unittest.main()
