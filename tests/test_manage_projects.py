import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from nebula.install import install, plan_install, uninstall
from nebula.lifecycle import add_projects, init_nebula, remove_projects, set_mode
from nebula.roots import read_config
from nebula.store import Store
from tests.support import workspace, lesson

RUNTIME = Path(__file__).resolve().parents[1]


class AddProjectTests(unittest.TestCase):
    def test_add_keeps_memory_and_mode_and_allows_install(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'observe')
            with Store(root) as store: store.put_lesson(lesson())
            result = add_projects(root, [b])
            self.assertEqual(result, {'added': [str(b)], 'already_selected': [], 'projects': [str(a), str(b)]})
            config = read_config(root)
            self.assertEqual(config['projects'], [str(a), str(b)])
            self.assertEqual(config['mode'], 'observe')
            with Store(root) as store: self.assertIsNotNone(store.get_lesson('layout'))
            self.assertTrue(plan_install(root, [b], ['claude'], RUNTIME))

    def test_already_selected_project_is_reported_not_duplicated(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            result = add_projects(root, [a, b, b])
            self.assertEqual(result['added'], [str(b)])
            self.assertEqual(result['already_selected'], [str(a)])
            self.assertEqual(read_config(root)['projects'], [str(a), str(b)])

    def test_invalid_projects_leave_config_unchanged(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            outside = root.parent / 'outside'; outside.mkdir()
            afile = root / 'notes.txt'; afile.write_text('x')
            for bad in (outside, root, root / 'missing', afile):
                with self.subTest(bad=bad), self.assertRaises((ValueError, OSError)):
                    add_projects(root, [b, bad])
            self.assertEqual(read_config(root)['projects'], [str(a)])

    def test_add_requires_an_existing_nebula(self):
        with workspace() as (root, a, b):
            with self.assertRaises(Exception):
                add_projects(root, [a])
            self.assertFalse((root / '.nebula').exists())


class RemoveProjectTests(unittest.TestCase):
    def test_remove_keeps_lessons_and_reports_ones_scoped_only_to_it(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                store.put_lesson(lesson(lesson_id='only-b', scope_projects=(str(b),)))
                store.put_lesson(lesson(lesson_id='a-and-b', scope_projects=(str(a), str(b))))
                store.put_lesson(lesson(lesson_id='everywhere'))
            result = remove_projects(root, [b])
            self.assertEqual(result['removed'], [str(b)])
            self.assertEqual(result['projects'], [str(a)])
            self.assertEqual(result['lessons_scoped_only_to_removed'], ['only-b'])
            self.assertEqual(read_config(root)['projects'], [str(a)])
            with Store(root) as store:
                self.assertEqual({v.lesson_id for v in store.lessons()}, {'only-b', 'a-and-b', 'everywhere'})

    def test_remove_works_after_project_folder_is_deleted(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            shutil.rmtree(b)
            self.assertEqual(remove_projects(root, [b])['removed'], [str(b)])
            self.assertEqual(read_config(root)['projects'], [str(a)])

    def test_cannot_remove_last_or_unselected_project(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            with self.assertRaisesRegex(ValueError, 'at least one'):
                remove_projects(root, [a])
            with self.assertRaisesRegex(ValueError, 'not selected'):
                remove_projects(root, [b])
            self.assertEqual(read_config(root)['projects'], [str(a)])

    def test_installed_project_must_be_uninstalled_first(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            install(plan_install(root, [b], ['claude'], RUNTIME))
            with self.assertRaisesRegex(ValueError, 'uninstall'):
                remove_projects(root, [b])
            self.assertEqual(read_config(root)['projects'], [str(a), str(b)])
            uninstall(root, b, 'claude')
            self.assertEqual(remove_projects(root, [b])['removed'], [str(b)])


class ManageProjectsCliTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run([sys.executable, str(RUNTIME / 'scripts/nebula.py'), *map(str, args)],
                              cwd=cwd, text=True, capture_output=True)

    def test_add_and_remove_from_a_selected_child(self):
        with workspace() as (root, a, b):
            self.assertEqual(self.run_cli(a, 'init', root, '--project', a).returncode, 0)
            added = self.run_cli(a, 'add-project', '--project', b)
            self.assertEqual(added.returncode, 0, added.stderr)
            self.assertEqual(json.loads(added.stdout)['added'], [str(b)])
            removed = self.run_cli(a, 'remove-project', '--project', b)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual(json.loads(removed.stdout)['projects'], [str(a)])
            refused = self.run_cli(a, 'remove-project', '--project', a)
            self.assertEqual(refused.returncode, 1)
            self.assertIn('at least one', json.loads(refused.stderr)['message'])


if __name__ == '__main__':
    unittest.main()
