"""Aggregate independent snapshots; retained history is never a lifetime total."""
import json
from pathlib import Path
from ..models import utcnow, timestamp
from .discovery import discover_roots
from .snapshot import snapshot_nebula
from .tracking import METRICS

MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


def bound_payload(report, *, max_bytes=MAX_PAYLOAD_BYTES):
    def size():
        return len(json.dumps(report, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    if size() <= max_bytes:
        return report
    report['warnings'].append('Report detail truncated to fit the payload budget; aggregate totals retained')
    # Remove largest details first, retaining summary and coverage information.
    for field in ('activity', 'lessons', 'metric_rows'):
        roots = sorted((n for n in report['nebulas'] if n['available']),
                       key=lambda n: len(json.dumps(n.get(field, []))), reverse=True)
        for nebula in roots:
            if not nebula.get(field):
                continue
            nebula[field] = []
            nebula['coverage']['details_complete'] = False
            if size() <= max_bytes:
                return report
    if size() > max_bytes:
        raise ValueError('Report summary alone exceeds the payload budget')
    return report


def build_report(root, *, now=None):
    root = Path(root).resolve()
    generated = now or utcnow()
    timestamp(generated)
    discovery = discover_roots(root)
    roots = discovery.pop('roots')
    report = {'format_version': 1, 'generated_at': generated, 'scan_root': str(root),
              'discovery': discovery, 'nebulas': [], 'warnings': [],
              'summary': {'discovered_nebulas': len(roots), 'available_nebulas': 0,
                          'selected_projects': 0, 'current_lessons': 0, 'mature_lessons': 0,
                          'disabled_lessons': 0, 'suspended_lessons': 0,
                          'tracked_metrics': dict.fromkeys(METRICS, 0), 'tracked_nebulas': 0}}
    for nebula_root in roots:
        snapshot = snapshot_nebula(nebula_root)
        report['nebulas'].append(snapshot)
        if not snapshot['available']:
            report['warnings'].append(f"Unavailable Nebula: {snapshot['root']}: {snapshot['diagnostic']}")
            continue
        summary = report['summary']
        summary['available_nebulas'] += 1
        for key in ('selected_projects', 'current_lessons', 'mature_lessons', 'disabled_lessons', 'suspended_lessons'):
            summary[key] += snapshot['counts'][key]
        if snapshot['analytics_since'] is not None:
            summary['tracked_nebulas'] += 1
            for metric in METRICS:
                summary['tracked_metrics'][metric] += snapshot['tracked_metrics'][metric]
    return bound_payload(report)
