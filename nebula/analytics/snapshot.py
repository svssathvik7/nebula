"""Independent, read-only SQLite snapshots. Never call Store's write constructor."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from ..application import suspension_key
from ..maintenance import usage_bytes, HARD
from ..models import Lesson, load, utcnow
from ..roots import read_config
from ..scoring import current_score
from ..store import Store, StateUnavailable
from .tracking import read_counters, validate_tracking


class ReadOnlyStore(Store):
    def __init__(self, root):
        self.connection = None
        self.root = Path(root).absolute()
        if self.root.resolve() != self.root:
            raise StateUnavailable('stats root changed or is symlinked')
        self.directory = self.root / '.nebula'
        self.path = self.directory / 'state.sqlite3'
        if self.directory.is_symlink() or self.path.is_symlink():
            raise StateUnavailable('nebula state must not be a symlink')
        try:
            self.connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                              isolation_level=None, timeout=0.1)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA query_only=ON')
            self.connection.execute('BEGIN')
            self.schema_version = self.connection.execute('PRAGMA user_version').fetchone()[0]
            if self.schema_version not in (1, 2, 3):
                raise StateUnavailable('unsupported or missing nebula schema')
            self._validate_schema(self.schema_version)
        except BaseException:
            self.close()
            raise

    def sample_provenance(self, key, version, episode_id):
        if self.schema_version == 1:
            return None
        return super().sample_provenance(key, version, episode_id)

    def confirmed(self, key, version):
        return self.schema_version >= 2 and super().confirmed(key, version)


def snapshot_nebula(root, *, lesson_limit=1000, activity_limit=100):
    root = Path(root).absolute()
    try:
        config = read_config(root)
        size = usage_bytes(root)
        if size >= HARD:
            raise StateUnavailable('state exceeds bounded reporting budget')
        now = utcnow()
        with ReadOnlyStore(root) as store:
            db = store.connection
            tracked = store.schema_version == 3
            since = validate_tracking(db) if tracked else None
            result = {
                'root': str(root), 'available': True, 'nebula_id': config['nebula_id'],
                'enabled': config['enabled'], 'projects': config['projects'],
                'schema': store.schema_version, 'snapshot_at': now, 'storage_bytes': size,
                'analytics_since': since,
                'coverage': {'tracking_initialized': tracked, 'historical_complete': False,
                             'details_complete': True,
                             'label': 'Counters tracked since analytics initialization; earlier history incomplete' if tracked
                                      else 'Analytics not initialized; retained records only, not lifetime totals'},
                'counts': {'selected_projects': len(config['projects']), 'current_lessons': 0,
                           'mature_lessons': 0, 'disabled_lessons': 0, 'suspended_lessons': 0,
                           'unfinished_applications': 0},
                'tracked_metrics': read_counters(db) if tracked else None,
                'metric_rows': [], 'lessons': [], 'activity': [], 'warnings': [],
            }
            # Compute full current-state totals independently of the detail cap.
            current_sql = 'SELECT data FROM lessons l WHERE version=(SELECT max(version) FROM lessons WHERE id=l.id) ORDER BY id'
            for row in db.execute(current_sql):
                value = load(Lesson, row[0])
                score = current_score(store, value, now=now)
                result['counts']['current_lessons'] += 1
                result['counts']['mature_lessons'] += int(score.mature)
                result['counts']['disabled_lessons'] += int(value.disabled)
                result['counts']['suspended_lessons'] += int(bool(store.get_meta(suspension_key(value.lesson_id, value.version), False)))
            result['counts']['unfinished_applications'] = db.execute("SELECT count(*) FROM applications WHERE json_extract(data,'$.status')='claimed'").fetchone()[0]
            version_count = db.execute('SELECT count(*) FROM lessons').fetchone()[0]
            for row in db.execute('SELECT data FROM lessons ORDER BY id,version DESC LIMIT ?', (lesson_limit,)):
                value = load(Lesson, row[0])
                unfinished = db.execute("SELECT count(*) FROM applications WHERE lesson_id=? AND version=? AND json_extract(data,'$.status')='claimed'", (value.lesson_id, value.version)).fetchone()[0]
                result['lessons'].append({
                    'lesson': asdict(value), 'is_current': store.get_lesson(value.lesson_id).version == value.version,
                    'score': asdict(current_score(store, value, now=now)),
                    'confirmed': store.confirmed(value.lesson_id, value.version),
                    'suspended': bool(store.get_meta(suspension_key(value.lesson_id, value.version), False)),
                    'tracked_metrics': read_counters(db, lesson_id=value.lesson_id, version=value.version) if tracked else None,
                    'unfinished_applications': unfinished,
                    'feedback': store.feedback_history(value.lesson_id, value.version),
                })
            if version_count > lesson_limit:
                result['coverage']['details_complete'] = False
                result['warnings'].append(f'Lesson details capped at {lesson_limit} of {version_count} versions; totals include all versions')
            if tracked:
                row_limit = max(1, lesson_limit * 32)
                result['metric_rows'] = [dict(row) for row in db.execute('SELECT * FROM analytics_counters ORDER BY lesson_id,version,project LIMIT ?', (row_limit,))]
                if db.execute('SELECT count(*) FROM analytics_counters').fetchone()[0] > row_limit:
                    result['coverage']['details_complete'] = False
                    result['warnings'].append('Project/version metric detail capped; global counters remain complete')
            for row in db.execute('SELECT timestamp,kind,data FROM audit ORDER BY id DESC LIMIT ?', (activity_limit,)):
                data = json.loads(row['data'])
                suggestion_id = data.get('suggestion_id', data.get('id'))
                pending = store.get_suggestion(suggestion_id) if suggestion_id else None
                result['activity'].append({'timestamp': row['timestamp'], 'kind': row['kind'],
                                           'data': data, 'project': pending.project if pending else None})
            result['retained_suggestion_states'] = {row[0] or 'unknown': row[1] for row in db.execute("SELECT json_extract(data,'$.status'),count(*) FROM suggestions GROUP BY 1")}
            return result
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, StateUnavailable) as exc:
        return {'root': str(root), 'available': False, 'diagnostic': str(exc)}
