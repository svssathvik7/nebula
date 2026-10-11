import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from nebula.cli import main

RUNTIME = Path(__file__).resolve().parents[1]


class AnalyticsCliTests(unittest.TestCase):
    def cli(self, root, *args):
        return subprocess.run([sys.executable, str(RUNTIME/'scripts/nebula.py'), 'stats', *map(str,args)],
                              cwd=root, text=True, capture_output=True)

    def test_plain_ancestor_defaults_and_small_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.cli(temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['discovered_nebulas'], 0)
            self.assertTrue(Path(value['output']).is_file())
            self.assertLess(len(result.stdout.encode()), 8192)

    def test_partial_and_explicit_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root/'bad/.nebula').mkdir(parents=True)
            output = root/'report.html'
            result = self.cli(root, '--root', root, '--output', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['discovered_nebulas'], 1)
            self.assertEqual(value['available_nebulas'], 0)
            self.assertTrue(value['warnings'])
            self.assertTrue(output.is_file())

    def test_bad_root_and_collision_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); output=root/'report.html'
            output.write_text('keep')
            for args in (('--root',root/'missing'),('--output',output)):
                with self.subTest(args=args):
                    result = self.cli(root, *args)
                    self.assertEqual(result.returncode, 1)
            self.assertEqual(output.read_text(), 'keep')

    def test_browser_failure_keeps_report_and_success_uses_uri(self):
        for answer in (False, True, OSError('no browser')):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); output=root/'report.html'
                options = {'side_effect': answer} if isinstance(answer,Exception) else {'return_value':answer}
                with patch('nebula.cli.webbrowser.open', **options) as opener, contextlib.redirect_stdout(io.StringIO()) as stdout:
                    code = main(['stats','--root',str(root),'--output',str(output),'--open'])
                self.assertEqual(code, 0)
                self.assertTrue(output.is_file())
                opener.assert_called_once_with(output.as_uri())
                value=json.loads(stdout.getvalue())
                self.assertEqual(bool(value['warnings']), answer is not True)
