"""Bundle an offline dashboard and publish a new private file without replacing one."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from .report import MAX_PAYLOAD_BYTES

TEMPLATES = Path(__file__).parent / 'templates'


def render_html(report):
    encoded = json.dumps(report, ensure_ascii=False, separators=(',', ':'))
    encoded = encoded.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    encoded = encoded.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    if len(encoded.encode('utf-8')) > MAX_PAYLOAD_BYTES:
        raise ValueError('Encoded report exceeds payload budget')
    document = (TEMPLATES / 'dashboard.html').read_text(encoding='utf-8')
    document = document.replace('@@CSS@@', (TEMPLATES / 'dashboard.css').read_text(encoding='utf-8'))
    document = document.replace('@@JS@@', (TEMPLATES / 'dashboard.js').read_text(encoding='utf-8'))
    return document.replace('@@DATA@@', encoded)


def write_report(report, *, scan_root, output=None):
    if output is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output = Path(scan_root).resolve() / f'nebula-stats-{stamp}.html'
    target = Path(output).absolute()
    if '.nebula' in target.parts:
        raise ValueError('Report output cannot be inside Nebula state')
    if any(parent.is_symlink() for parent in (target, *target.parents)):
        raise ValueError('Report output cannot traverse a symlink')
    if target.exists():
        raise FileExistsError('Report output already exists: ' + str(target))
    if not target.parent.is_dir():
        raise ValueError('Report output parent must exist')
    document = render_html(report)
    fd, temporary = tempfile.mkstemp(prefix='.nebula-report-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        # A same-filesystem hard link publishes atomically and fails if another
        # process created the destination; replace() would overwrite that file.
        os.link(temporary, target)
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)
