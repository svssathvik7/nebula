from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nebula.lifecycle import init_nebula
from nebula.analytics.discovery import discover_roots


class DiscoveryTests(unittest.TestCase):
    def create(self, root):
        child = root / 'project'
        child.mkdir(parents=True)
        init_nebula(root, [child])
        return root.resolve()

    def test_plain_ancestor_self_and_nested_nebulas(self):
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary).resolve()
            a = self.create(ancestor / 'bitcoin')
            nested = self.create(a / 'project/nested')
            b = self.create(ancestor / 'trading')
            result = discover_roots(ancestor)
            self.assertEqual(result['roots'], [a, nested, b])
            self.assertTrue(result['complete'])
            self.assertEqual(discover_roots(a)['roots'], [a, nested])

    def test_symlinks_and_excluded_directories_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary).resolve()
            hidden = self.create(ancestor / 'node_modules/hidden')
            (ancestor / 'loop').symlink_to(ancestor, target_is_directory=True)
            (ancestor / 'alias').symlink_to(hidden, target_is_directory=True)
            result = discover_roots(ancestor)
            self.assertEqual(result['roots'], [])
            self.assertTrue(result['complete'])
            self.assertEqual(discover_roots(hidden)['roots'], [hidden])

    def test_limits_are_visible_and_preserve_found_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary).resolve()
            a = self.create(ancestor / 'a')
            self.create(ancestor / 'b')
            for options in ({'max_nebulas':1}, {'max_directories':2}, {'max_depth':0}, {'max_entries':1}):
                with self.subTest(options=options):
                    result = discover_roots(ancestor, **options)
                    self.assertFalse(result['complete'])
                    self.assertTrue(result['warnings'])
                    if options == {'max_nebulas':1}:
                        self.assertEqual(result['roots'], [a])

    def test_io_failure_is_partial_and_invalid_start_is_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.create(Path(temporary).resolve() / 'nebula')
            with patch('nebula.analytics.discovery.os.scandir', side_effect=PermissionError('denied')):
                result = discover_roots(root)
            self.assertEqual(result['roots'], [root])
            self.assertFalse(result['complete'])
            with self.assertRaises(ValueError):
                discover_roots(root / 'missing')

    def test_empty_and_malformed_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(discover_roots(root)['roots'], [])
            (root / '.nebula').write_text('malformed')
            self.assertEqual(discover_roots(root)['roots'], [root])

    def test_queued_directory_changed_to_symlink_is_incomplete(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary).resolve()
            a = self.create(ancestor/'a'); b = self.create(ancestor/'b')
            real_scan = os.scandir
            def changing_scan(path):
                if path == a:
                    b.rename(ancestor/'moved')
                    b.symlink_to(ancestor/'moved', target_is_directory=True)
                return real_scan(path)
            with patch('nebula.analytics.discovery.os.scandir', side_effect=changing_scan):
                result = discover_roots(ancestor)
            self.assertEqual(result['roots'], [a])
            self.assertFalse(result['complete'])
            self.assertTrue(any(str(b) in warning for warning in result['warnings']))
