"""Compact counters. Callers own the transaction and operation replay guards."""
from ..models import timestamp

METRICS = ('suggestions', 'accepted', 'rejected', 'exceptions', 'corrected',
           'withdrawn', 'disabled', 'claims', 'successful', 'failed', 'unknown')
VERDICT_METRIC = dict(zip(('accept', 'reject', 'exception', 'correct', 'withdraw', 'disable'), METRICS[1:7]))
TABLES = {
    'analytics_meta': ('key', 'value'),
    'analytics_feedback': ('suggestion_id', 'verdict_mask'),
    'analytics_counters': ('lesson_id', 'version', 'project', *METRICS),
}


def create_tracking(connection, *, since):
    timestamp(since)
    connection.execute('CREATE TABLE analytics_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    connection.execute('CREATE TABLE analytics_feedback(suggestion_id TEXT PRIMARY KEY,verdict_mask INTEGER NOT NULL CHECK(verdict_mask BETWEEN 0 AND 63))')
    columns = ','.join(f'{name} INTEGER NOT NULL DEFAULT 0 CHECK(typeof({name})=\'integer\' AND {name}>=0)' for name in METRICS)
    connection.execute('CREATE TABLE analytics_counters(lesson_id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),project TEXT NOT NULL,' + columns + ',PRIMARY KEY(lesson_id,version,project))')
    connection.execute("INSERT INTO analytics_meta VALUES('since',?)", (since,))


def increment(connection, *, lesson_id, version, project, metric):
    if metric not in METRICS:
        raise ValueError('unsupported analytics metric')
    connection.execute(
        f'INSERT INTO analytics_counters(lesson_id,version,project,{metric}) VALUES(?,?,?,1) '
        f'ON CONFLICT(lesson_id,version,project) DO UPDATE SET {metric}={metric}+1',
        (lesson_id, version, project),
    )


def record_feedback(connection, suggestion, verdict):
    metric = VERDICT_METRIC[verdict]
    bit = 1 << tuple(VERDICT_METRIC).index(verdict)
    row = connection.execute('SELECT verdict_mask FROM analytics_feedback WHERE suggestion_id=?', (suggestion.suggestion_id,)).fetchone()
    mask = row[0] if row else 0
    if type(mask) is not int or not 0 <= mask <= 63:
        raise ValueError('invalid analytics verdict state')
    if mask & bit:
        return False
    connection.execute('INSERT INTO analytics_feedback VALUES(?,?) ON CONFLICT(suggestion_id) DO UPDATE SET verdict_mask=excluded.verdict_mask', (suggestion.suggestion_id, mask | bit))
    increment(connection, lesson_id=suggestion.lesson_id, version=suggestion.version,
              project=suggestion.project, metric=metric)
    return True


def validate_tracking(connection):
    row = connection.execute("SELECT value FROM analytics_meta WHERE key='since'").fetchone()
    if row is None:
        raise ValueError('analytics tracking start missing')
    timestamp(row[0])
    invalid = ' OR '.join(f"typeof({m})!='integer' OR {m}<0" for m in METRICS)
    if connection.execute(f'SELECT 1 FROM analytics_counters WHERE {invalid} LIMIT 1').fetchone():
        raise ValueError('invalid analytics counters')
    return row[0]


def read_counters(connection, *, lesson_id=None, version=None, project=None):
    conditions, values = [], []
    for name, value in (('lesson_id', lesson_id), ('version', version), ('project', project)):
        if value is not None:
            conditions.append(name + '=?')
            values.append(value)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    columns = ','.join(f'COALESCE(sum({m}),0)' for m in METRICS)
    row = connection.execute('SELECT ' + columns + ' FROM analytics_counters' + where, values).fetchone()
    if any(type(value) is not int or value < 0 for value in row):
        raise ValueError('invalid analytics totals')
    return dict(zip(METRICS, row))
