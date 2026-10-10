import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from nebula.analytics.report import build_report
from nebula.analytics.render import render_html, write_report


class RenderTests(unittest.TestCase):
    def test_hostile_unicode_text_stays_inert(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_report(Path(temporary))
            payload = '</script><script>alert("x")</script> & 日本語 \u2028'
            report['warnings'] = [payload]
            document = render_html(report)
            self.assertNotIn(payload, document)
            encoded = re.search(r'<script id="nebula-data" type="application/json">(.*?)</script>', document, re.S).group(1)
            self.assertEqual(json.loads(encoded)['warnings'], [payload])
            self.assertNotRegex(document, r'(?:src|href)=["\']https?://')

    def test_empty_document_and_owner_only_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = write_report(build_report(root), scan_root=root)
            self.assertIn('Nebula analytics', output.read_text())
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            self.assertTrue(output.name.startswith('nebula-stats-'))

    def test_output_collision_symlinks_and_state_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            report = build_report(root)
            output = root / 'existing.html'; output.write_text('keep')
            with self.assertRaises(FileExistsError):
                write_report(report, scan_root=root, output=output)
            self.assertEqual(output.read_text(), 'keep')
            (root / 'link').symlink_to(root, target_is_directory=True)
            (root / '.nebula').mkdir()
            for invalid in (root/'link/report.html', root/'.nebula/report.html'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    write_report(report, scan_root=root, output=invalid)

    def test_collision_after_precheck_preserves_racing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); target = root/'report.html'
            report = build_report(root)
            real_link = os.link
            def collide(source, destination):
                target.write_text('racing owner')
                return real_link(source, destination)
            with patch('nebula.analytics.render.os.link', side_effect=collide):
                with self.assertRaises(FileExistsError):
                    write_report(report, scan_root=root, output=target)
            self.assertEqual(target.read_text(), 'racing owner')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['report.html'])

    def test_render_budget_rejects_oversized_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_report(Path(temporary))
            report['warnings'] = ['x'*(8*1024*1024)]
            with self.assertRaises(ValueError):
                render_html(report)
