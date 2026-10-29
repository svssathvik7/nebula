import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nebula.doctor import doctor
from nebula.install import install, plan_install
from nebula.lifecycle import init_nebula, set_mode
from tests.support import workspace

RUNTIME = Path(__file__).resolve().parents[1]


def statuses(report):
    return {check['check']: check['status'] for check in report['checks']}


def problem(report, name):
    return next(check for check in report['checks'] if check['check'] == name)


class DoctorTests(unittest.TestCase):
    def test_healthy_nebula_passes_and_flags_uninstalled_project(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b]); set_mode(root, 'full')
            install(plan_install(root, [a], ['claude', 'codex'], RUNTIME))
            report = doctor(root, runtime=RUNTIME, all_checks=True)
            self.assertTrue(report['ok'], report)
            found = statuses(report)
            self.assertEqual(found['config'], 'ok')
            self.assertEqual(found['state'], 'ok')
            self.assertEqual(found['mode'], 'ok')
            self.assertEqual(found['project a'], 'ok')
            self.assertEqual(found['claude in a'], 'ok')
            self.assertEqual(found['codex in a'], 'ok')
            self.assertEqual(found['project b'], 'warn')
            self.assertIn('/nebula', problem(report, 'project b')['fix'])
            self.assertEqual(report['summary'], {'ok': 6, 'warn': 1, 'fail': 0})

    def test_off_mode_is_a_warning(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            report = doctor(root, runtime=RUNTIME)
            self.assertTrue(report['ok'])
            self.assertEqual(problem(report, 'mode')['status'], 'warn')
            self.assertIn('/nebula on', problem(report, 'mode')['fix'])

    def test_missing_project_folder_fails(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b]); set_mode(root, 'full')
            shutil.rmtree(b)
            report = doctor(root, runtime=RUNTIME)
            self.assertFalse(report['ok'])
            self.assertEqual(problem(report, 'project b')['status'], 'fail')

    def test_moved_checkout_breaks_skill_link_and_hooks(self):
        with workspace() as (root, a, b), tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp).resolve() / 'old-checkout'
            (old / 'skills/nebula').mkdir(parents=True)
            (old / 'skills/nebula/SKILL.md').write_text('---\nname: nebula\n---\n')
            init_nebula(root, [a]); set_mode(root, 'full')
            install(plan_install(root, [a], ['claude'], old))
            shutil.rmtree(old)
            report = doctor(root, runtime=RUNTIME)
            self.assertFalse(report['ok'])
            check = problem(report, 'claude in a')
            self.assertEqual(check['status'], 'fail')
            self.assertIn('skill link', check['detail'])
            self.assertIn('hook script', check['detail'])
            self.assertIn('/nebula', check['fix'])

    def test_hooks_removed_by_hand_are_reported(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'full')
            install(plan_install(root, [a], ['claude'], RUNTIME))
            (a / '.claude/settings.local.json').write_text('{}\n')
            check = problem(doctor(root, runtime=RUNTIME), 'claude in a')
            self.assertEqual(check['status'], 'fail')
            self.assertIn('hooks', check['detail'])

    def test_other_checkout_is_a_warning(self):
        with workspace() as (root, a, b), tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp).resolve() / 'other'
            shutil.copytree(RUNTIME / 'skills', other / 'skills', symlinks=True)
            (other / 'scripts').mkdir(); shutil.copy(RUNTIME / 'scripts/nebula_hook.py', other / 'scripts')
            init_nebula(root, [a]); set_mode(root, 'full')
            install(plan_install(root, [a], ['claude'], other))
            check = problem(doctor(root, runtime=RUNTIME), 'claude in a')
            self.assertEqual(check['status'], 'warn')
            self.assertIn(str(other), check['detail'])

    def test_interrupted_install_is_reported(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'full')
            link = a / '.claude/skills/nebula'
            entry = {'root': str(root), 'project': str(a), 'host': 'claude', 'kind': 'skill',
                     'path': str(link), 'before': None, 'after': {'link': str(RUNTIME / 'skills/nebula')}}
            (root / '.nebula/install-recovery.json').write_text(json.dumps([entry]))
            check = problem(doctor(root, runtime=RUNTIME), 'interrupted install')
            self.assertEqual(check['status'], 'warn')

    def test_broken_config_is_reported_without_raising(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            (root / '.nebula/config.json').write_text('{not json')
            report = doctor(root, runtime=RUNTIME, all_checks=True)
            self.assertFalse(report['ok'])
            self.assertEqual(statuses(report), {'config': 'fail'})

    def test_default_output_lists_only_problems_failures_first_and_bounded(self):
        with workspace() as (root, a, b):
            for i in range(30): (root / f'p{i}').mkdir()
            init_nebula(root, [a, b, *(root / f'p{i}' for i in range(30))]); set_mode(root, 'full')
            shutil.rmtree(b)
            report = doctor(root, runtime=RUNTIME)
            self.assertEqual(report['summary'], {'ok': 3, 'warn': 31, 'fail': 1})
            self.assertEqual(report['checks'][0]['check'], 'project b')
            self.assertEqual(len(report['checks']), 20)
            self.assertEqual(report['problems_omitted'], 12)
            self.assertNotIn('ok', {c['status'] for c in report['checks']})

    def test_doctor_does_not_write(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'full')
            install(plan_install(root, [a], ['claude'], RUNTIME))
            files = sorted(root.rglob('*'))
            before = {p: p.read_bytes() for p in files if p.is_file() and not p.is_symlink() and 'state.sqlite3' not in p.name}
            doctor(root, runtime=RUNTIME)
            self.assertEqual(sorted(root.rglob('*')), files)
            self.assertEqual({p: p.read_bytes() for p in before}, before)


class DoctorCliTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run([sys.executable, str(RUNTIME / 'scripts/nebula.py'), *map(str, args)],
                              cwd=cwd, text=True, capture_output=True)

    def test_runs_from_a_child_even_with_broken_config(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            healthy = self.run_cli(a, 'doctor')
            self.assertEqual(healthy.returncode, 0, healthy.stderr)
            self.assertTrue(json.loads(healthy.stdout)['ok'])
            (root / '.nebula/config.json').write_text('{not json')
            broken = self.run_cli(a, 'doctor')
            self.assertEqual(broken.returncode, 1)
            self.assertEqual(json.loads(broken.stdout)['checks'][0]['check'], 'config')

    def test_outside_any_nebula_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(tmp, 'doctor')
            self.assertEqual(result.returncode, 1)
            self.assertIn('no nebula', json.loads(result.stderr)['message'])


if __name__ == '__main__':
    unittest.main()
