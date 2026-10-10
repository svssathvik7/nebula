# Multi-Nebula Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user previously selected Native execution; preserve that choice. Steps use checkbox syntax for tracking.

**Goal:** Generate a local interactive HTML dashboard showing learning, feedback, and application outcomes across independent Nebulas beneath a requested folder.

**Architecture:** A bounded directory walker discovers independent roots. Existing engine transactions record durable metrics, while a separate read-only reader builds consistent per-root snapshots. A standard-library renderer bundles HTML, CSS, JavaScript, and escaped data into a standalone report; the CLI and shared skill expose generation on demand.

**Tech Stack:** Python 3.11+, SQLite, unittest, standalone HTML/CSS/JavaScript. No added runtime dependencies, model calls, frontend build, or server.

**Spec:** [Approved analytics design](../specs/2026-10-10-nebula-analytics-design.md).

## Global constraints

- Work on the user-created `feat/analytics` branch. Use atomic commits and stage only task-owned files.
- Preserve existing learning, scoring, refusal, feedback attribution, project scope, and execution permission semantics.
- Time savings estimates are deferred. Report recorded successful applications without assigning saved minutes.
- Counter updates and their source operations commit or roll back together. Replayed operations do not inflate metrics.
- All selected children remain descendants of their own Nebula root; the report ancestor need not be a Nebula.
- Stats uses read-only SQLite access: no migration, maintenance, checkpoint, scoring mutation, or background activity.
- Support report reads for schemas 1, 2, and 3. Normal engine use performs migration; stats does not.
- Discovery limits: 10,000 directories, depth 12, 100 candidate Nebulas. Never follow descendant directory symlinks.
- Rendering limits: 1,000 lesson versions per Nebula, 100 recent activity records per Nebula, 8 MiB serialized payload. Report incompleteness explicitly.
- Keep existing 32/64 MiB storage budgets and the feedback reserve. No permanent per-event analytics log.
- Reports contain no remote resources. Escape data, use text nodes, refuse output collisions/symlinks, and create owner-only files.
- CI remains Ubuntu 24.04 with Python 3.11–3.14. Document platform limitations instead of claiming untested compatibility.

## Review focus

1. A second valid receipt repeats a verdict already counted for the same suggestion: count once even after the first receipt expires (Task 2).
2. A real execution and refusal bookkeeping share the applications table: feedback-only rows must never become executions (Tasks 2 and 4).
3. A root changes or becomes unreadable during traversal: return available results with accurate completeness warnings (Task 3).
4. A live WAL writer changes one root during reporting: retain per-root snapshot consistency without promising global consistency (Task 4).
5. Lesson text contains script terminators, markup, Unicode, or unusually large data: render inert text and mark truncation (Tasks 5 and 6).

## File map and report contract

Create `nebula/analytics/` with these focused modules:

| File | Responsibility |
| --- | --- |
| `__init__.py` | Package declaration |
| `tracking.py` | Schema creation, counter increments, feedback verdict deduplication, metric reads |
| `discovery.py` | Bounded root discovery and traversal diagnostics |
| `snapshot.py` | Read-only state adapter and one-root analytics snapshot |
| `report.py` | Discovery/snapshot orchestration and cross-root aggregates |
| `render.py` | Safe payload embedding and exclusive report creation |
| `templates/dashboard.html` | Document structure and local-report notices |
| `templates/dashboard.css` | Responsive styles and focus states |
| `templates/dashboard.js` | Search, filters, detail expansion, and count bars |

Modify `nebula/store.py`, `nebula/feedback.py`, `nebula/application.py`,
`nebula/maintenance.py`, and `nebula/cli.py` only for the relevant interfaces.
Update the README, shared skill, integration reference, and record reference.
Add focused `tests/test_analytics_*.py` modules and a synthetic
`examples/analytics_demo.py` for browser verification.

Normalized data contract:

```python
report = {
    'format_version': 1,
    'generated_at': utcnow(),
    'scan_root': str(root),
    'discovery': {'complete': True, 'visited': 0, 'exclusions': [], 'warnings': []},
    'summary': {
        'discovered_nebulas': 0, 'available_nebulas': 0,
        'selected_projects': 0, 'current_lessons': 0, 'mature_lessons': 0,
        'disabled_lessons': 0, 'suspended_lessons': 0,
        'tracked_metrics': {}, 'tracked_nebulas': 0,
    },
    'nebulas': [],
    'warnings': [],
}
```

Available Nebula records contain `root`, `available=True`, `nebula_id`,
`enabled`, `projects`, `schema`, `snapshot_at`, `storage_bytes`,
`analytics_since` (null for legacy), `coverage`, `counts`, `tracked_metrics`,
`metric_rows`, `lessons`, `activity`, and `warnings`. A lesson entry contains
`lesson` (serialized Lesson), `score` (serialized Score), `confirmed`,
`suspended`, `tracked_metrics`, `unfinished_applications`, and retained
`feedback`. Keep lesson versions explicit; current-version status is an
`is_current` boolean. Unavailable records contain `root`, `available=False`,
and `diagnostic`; they do not have invented zero metrics.

`coverage` includes `tracking_initialized`, `details_complete`,
`historical_complete=False`, and explanatory labels. Metric rows are grouped
by `lesson_id`, `version`, `project`; filtering sums those rows, not lesson scope.

## Task 1: Versioned compact analytics storage

**Files:** Create `nebula/analytics/__init__.py`, `nebula/analytics/tracking.py`, and `tests/test_analytics_tracking.py`; modify `nebula/store.py`, `nebula/maintenance.py`, and `tests/test_review_regressions.py`.

**Interfaces produced:**

```python
METRICS = ('suggestions', 'accepted', 'rejected', 'exceptions', 'corrected',
           'withdrawn', 'disabled', 'claims', 'successful', 'failed', 'unknown')
VERDICT_METRIC = {'accept': 'accepted', 'reject': 'rejected',
                 'exception': 'exceptions', 'correct': 'corrected',
                 'withdraw': 'withdrawn', 'disable': 'disabled'}

def create_tracking(connection, *, since: str) -> None: ...
def increment(connection, *, lesson_id: str, version: int,
              project: str, metric: str) -> None: ...
def record_feedback(connection, suggestion, verdict: str) -> bool: ...
def read_counters(connection, *, lesson_id=None,
                  version=None, project=None) -> dict: ...
```

The implementation fills these declared signatures; the bodies below define
the core SQL contract. All metric names come from fixed allowlists.

- [ ] Write failing tests for schema 3 initialization, v2 migration, v1 provenance preservation, zero initial counters, bad metric rejection, and rollback. Build legacy fixtures by dropping all three analytics tables before setting `user_version=2`; for v1 also drop `sample_provenance`. Do not relabel a live v3 schema as v1 without removing the new tables.

```python
def test_analytics_initializes_without_backfilling(self):
    with workspace() as (root, a, b):
        init_nebula(root, [a, b])
        with Store(root) as store:
            self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(read_counters(store.connection)['accepted'], 0)
            since = store.connection.execute(
                "SELECT value FROM analytics_meta WHERE key='since'"
            ).fetchone()[0]
            self.assertIsNotNone(timestamp(since))
```

- [ ] Run `python3 -m unittest tests.test_analytics_tracking -v` and confirm the new behavior fails before implementation.
- [ ] Create tables with primary keys and nonnegative integer metric columns:

```sql
CREATE TABLE analytics_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE analytics_feedback(suggestion_id TEXT PRIMARY KEY,verdict_mask INTEGER NOT NULL);
CREATE TABLE analytics_counters(
  lesson_id TEXT,version INTEGER,project TEXT,
  suggestions INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,exceptions INTEGER NOT NULL DEFAULT 0,
  corrected INTEGER NOT NULL DEFAULT 0,withdrawn INTEGER NOT NULL DEFAULT 0,
  disabled INTEGER NOT NULL DEFAULT 0,claims INTEGER NOT NULL DEFAULT 0,
  successful INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0,
  unknown INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(lesson_id,version,project)
);
```

Store `since` with a validated timezone-aware UTC timestamp. Add integer/check
constraints in the implementation. Use INSERT/UPSERT for metric increments:

```python
if metric not in METRICS:
    raise ValueError('unsupported analytics metric')
connection.execute(
    f'INSERT INTO analytics_counters(lesson_id,version,project,{metric}) '
    f'VALUES(?,?,?,1) ON CONFLICT(lesson_id,version,project) '
    f'DO UPDATE SET {metric}={metric}+1',
    (lesson_id, version, project),
)
```

- [ ] Extend Store schema validation to recognize versions 1/2/3 and the v3 tables. New initialization creates v3 in its schema transaction. `_migrate_v2()` validates old state, creates tracking with zero counters in one transaction, then sets `user_version=3`; v1 proceeds through the existing v1-to-v2 provenance migration first. Existing analytics table collisions in a claimed v2 schema are an error rather than silently resetting counters.
- [ ] Use a fixed six-bit verdict mask in `analytics_feedback`. `record_feedback` returns false when the suggestion/verdict bit exists; otherwise persist the bit and increment its project/version metric. Callers own the transaction.
- [ ] Prune markers only after their suggestions expire; retain counters and `since`. Update health's schema reporting and the existing v1 regression fixture/expected version to 3. Retain the original attribution assertions.
- [ ] Run `python3 -m unittest tests.test_analytics_tracking tests.test_review_regressions tests.test_roots_store tests.test_maintenance -v` and `git diff --check`.
- [ ] Commit owned files: `feat: add versioned analytics tracking storage`.

## Task 2: Instrument successful state transitions

**Files:** Modify `nebula/feedback.py`, `nebula/application.py`; extend `tests/test_analytics_tracking.py`.

**Consumes:** Task 1's `increment` and `record_feedback`. Uses existing `suggest`, `apply_feedback`, `claim_application`, and `finish_application` APIs without changing their signatures.

- [ ] Add failing tests using existing `tests.support` receipts/events and feedback fixtures. Cover suggestion replay, acceptance replay, repeat reject with a new verified receipt, changed exception reasons, later withdrawal, refusal-only rows, and completion replay.

```python
def test_suggestion_replay_counts_once(self):
    with workspace() as (root, a, b):
        init_nebula(root, [a, b])
        with Store(root) as store:
            value = lesson()
            store.put_lesson(value)
            fields = dict(session_id='s1', episode_id='e1', project=str(a),
                          context_digest='context', now=NOW)
            first = suggest(store, value, **fields)
            self.assertEqual(suggest(store, value, **fields), first)
            self.assertEqual(read_counters(store.connection)['suggestions'], 1)
```

- [ ] Run `python3 -m unittest tests.test_analytics_tracking -v` and confirm replay/counter expectations fail.
- [ ] Increment `suggestions` after a new suggestion is stored, before its transaction commits. Run `record_feedback` after validated feedback changes, inside its transaction; retain all existing receipt/replay and penalty guards. Increment claims only after a successful claim insert. Increment one outcome only after the claimed-to-completed update, before commit:

```python
metric = {'suitable': 'successful', 'failed': 'failed', 'unknown': 'unknown'}[outcome]
increment(store.connection, lesson_id=lesson_id, version=version,
          project=application['project'], metric=metric)
```

- [ ] Add failure injection after an analytics increment; verify the entire source transaction rolls back. Exercise two writers claiming the same decision and feedback repeated after raw receipt cleanup using a fresh valid receipt. Use SQLite transaction/replay results as the concurrency oracle.
- [ ] Verify metrics never change `score`, do not add samples, and continue respecting capacity/refusal guards. Run `python3 -m unittest discover -s tests -v` and `python3 examples/demo.py`.
- [ ] Commit owned files: `feat: track feedback and application outcomes atomically`.

## Task 3: Bounded multi-root discovery

**Files:** Create `nebula/analytics/discovery.py` and `tests/test_analytics_discovery.py`.

**Interface produced:**

```python
def discover_roots(root: Path, *, max_directories=10000,
                   max_depth=12, max_nebulas=100) -> dict:
    # {'roots': [Path, ...], 'complete': bool, 'visited': int,
    #  'exclusions': [str, ...], 'warnings': [str, ...]}
    ...
```

- [ ] Write failing tests for a common ancestor, the root itself, nested Nebulas, no roots, symlink loops, skipped dependency directories, depth/directory/root limits, and permission/race failures. Inject `os.scandir` failure rather than relying on root-user permission behavior.

```python
def test_discovers_independent_roots_beneath_plain_ancestor(self):
    with tempfile.TemporaryDirectory() as temporary:
        ancestor = Path(temporary)
        expected = []
        for name in ('bitcoin', 'trading'):
            root = ancestor / name
            child = root / 'project'
            child.mkdir(parents=True)
            init_nebula(root, [child])
            expected.append(root.resolve())
        result = discover_roots(ancestor)
        self.assertEqual(result['roots'], expected)
        self.assertTrue(result['complete'])
```

- [ ] Run `python3 -m unittest tests.test_analytics_discovery -v` and confirm missing discovery behavior fails.
- [ ] Implement deterministic sorted traversal with a stack and `os.scandir`. Detect candidate `.nebula` entries without entering state directories; a candidate may later prove invalid. Record canonical unique roots, never resolve/follow descendant symlinks, and continue below valid roots to find nested ones. Bound work before adding/traversing more nodes, including bounded enumeration of very wide directories; do not sort an unbounded entry list.
- [ ] Apply the exact skip list from the spec. Treat missing/non-directory starting roots as command errors; treat descendant I/O problems and exhausted limits as incomplete discovery warnings. Avoid global filesystem scans.
- [ ] Run `python3 -m unittest tests.test_analytics_discovery -v` and `git diff --check`.
- [ ] Commit owned files: `feat: discover nebula roots within bounded scope`.

## Task 4: Read-only snapshots and accurate aggregation

**Files:** Create `nebula/analytics/snapshot.py`, `nebula/analytics/report.py`, and `tests/test_analytics_report.py`; adjust shared read/schema helpers in `nebula/store.py` only if needed.

**Interfaces produced:**

```python
def snapshot_nebula(root: Path, *, lesson_limit=1000,
                    activity_limit=100) -> dict: ...
def build_report(root: Path, *, now=None) -> dict: ...
```

**Consumes:** `discover_roots`, `read_counters`, the report contract, `current_score`, `usage_bytes`, and shared record validation.

- [ ] Write failing tests for v3 tracked metrics, schema 1/2 reads without upgrade, unavailable-root diagnostics, project/version grouping, current-lesson totals despite capped details, refusal-only application rows, and historical coverage labels. Capture `connection.iterdump()` and config bytes before and after stats to assert logical state equality.

```python
def test_legacy_stats_does_not_migrate(self):
    with workspace() as (root, a, b):
        init_nebula(root, [a, b])
        with Store(root) as store:
            for table in ('analytics_counters', 'analytics_feedback', 'analytics_meta'):
                store.connection.execute(f'DROP TABLE {table}')
            store.connection.execute('PRAGMA user_version=2')
        result = snapshot_nebula(root)
        self.assertTrue(result['available'])
        self.assertIsNone(result['analytics_since'])
        with sqlite3.connect(root / '.nebula/state.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
```

- [ ] Run `python3 -m unittest tests.test_analytics_report -v` and confirm the new reader/aggregates fail.
- [ ] Use SQLite URI `mode=ro`, `query_only=ON`, a short busy timeout, and explicit `BEGIN` per root. Validate root identity/schema and read-only metadata before scoring. Reuse Store read methods through a read-only adapter that bypasses the writable constructor; v1 has no provenance and its confirmations remain unverified. Never call health's writable Store path.

```python
uri = (root / '.nebula/state.sqlite3').as_uri() + '?mode=ro'
db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0.1)
db.row_factory = sqlite3.Row
db.execute('PRAGMA query_only=ON')
db.execute('BEGIN')
```

- [ ] Validate counter integers and tracking metadata; reject malformed tracked state with a per-root diagnostic. Sum counters directly with SQL so capped lesson details cannot truncate totals. Keep current lesson counts and older-version counters distinct. Refusal records have status `reject`/`exception` or feedback state, not application outcomes. Show genuine claimed records as unfinished, not claims-minus-outcomes.
- [ ] Read bounded recent activity with labels explaining retention; unresolved old suggestion references remain unattributed instead of inventing a lesson/project. Retrieve current state and version metadata using bounded queries. Report detail truncation, omitted records, and read failures separately from aggregate completeness.
- [ ] Exercise a concurrent WAL writer: establish a reader snapshot, change tracked state through a writer, and prove the established snapshot remains coherent while a subsequent snapshot sees the change. Preserve application tests' existing receipt identities and outcomes.
- [ ] Build summary counts only from available snapshots, with `tracked_nebulas` coverage. Do not sum legacy retained counts into tracked totals. Serialize compactly and enforce the payload budget by removing detail/activity deterministically while retaining counters and completeness notices; if mandatory summary data alone exceeds the cap, return a generation error rather than silently exceed it.
- [ ] Run `python3 -m unittest tests.test_analytics_report tests.test_lessons_scoring tests.test_roots_store -v`.
- [ ] Commit owned files: `feat: aggregate read-only analytics snapshots`.

## Task 5: Standalone interactive HTML dashboard

**Files:** Create `nebula/analytics/render.py`, the three template files, `tests/test_analytics_render.py`, and `examples/analytics_demo.py`.

**Interfaces produced:**

```python
def render_html(report: dict) -> str: ...
def write_report(report: dict, *, scan_root: Path,
                 output: Path | None = None) -> Path: ...
```

- [ ] Write failing tests for empty/partial reports, legacy coverage, all feedback/outcome labels, Unicode, hostile script terminators, bounded payloads, symlink destinations/parents, existing-file collisions, state-directory output rejection, and mode 0600.

```python
def test_hostile_lesson_text_stays_inert(self):
    payload = '</script><script>alert("x")</script>'
    report = empty_report_fixture()
    report['warnings'] = [payload]
    document = render_html(report)
    self.assertNotIn(payload, document)
    encoded = re.search(r'<script id="nebula-data" type="application/json">(.*?)</script>',
                        document, re.S).group(1)
    self.assertEqual(json.loads(encoded)['warnings'], [payload])
```

Define `empty_report_fixture()` in this test module with the complete report
contract above; do not depend on fixtures hidden in another test task.

- [ ] Run `python3 -m unittest tests.test_analytics_render -v` and confirm rendering/output expectations fail.
- [ ] Render a semantic document with overview cards, a Nebula selector, project/kind/maturity filters, search, expandable lesson/version details, feedback/outcome bars, and recent activity. Use responsive CSS, visible labels/focus rings, keyboard-native controls, and neutral empty states. Keep current-version maturity distinct from lifetime counters.
- [ ] Embed report JSON in a non-executable data block, escape script-sensitive characters, and use `textContent`/DOM creation for all user data:

```python
encoded = json.dumps(report, ensure_ascii=False, separators=(',', ':'))
encoded = encoded.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
encoded = encoded.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
```

```javascript
const report = JSON.parse(document.getElementById('nebula-data').textContent);
const label = document.createElement('span');
label.textContent = lesson.action;
```

- [ ] Bundle template assets with no network requests. Project filtering sums `metric_rows` using recorded projects; unrestricted lesson scope never assigns an execution to a guessed project. Hide or explain unavailable details when filters depend on capped data.
- [ ] Write a same-directory temporary file with mode 0600, flush/fsync, then publish without replacing an existing target using an exclusive filesystem operation. Remove the temporary after success or failure. Reject symlinked destination ancestors and `.nebula` output paths before writing; handle a target created after the precheck as a collision. Generate a unique UTC timestamped default filename.
- [ ] Add `examples/analytics_demo.py --output PATH`: create multiple disposable Nebulas with explicitly synthetic receipts, tracked responses, outcomes, and contrasting versions; build/write the report before cleaning up temporary state. No real host settings or interactive acknowledgement are changed.
- [ ] Run renderer tests and generate the example outside `.nebula`. Inspect it with an available browser tool: check search, all filters, details, mobile layout, keyboard access, and zero external requests. If browser access is unavailable, document that limitation without asserting UI validation.
- [ ] Commit owned files: `feat: render standalone analytics dashboard`.

## Task 6: Expose stats, document semantics, and deliver the PR

**Files:** Modify `nebula/cli.py`, `skills/nebula/SKILL.md`, `skills/nebula/references/integration.md`, `skills/nebula/references/records.md`, and `README.md`; create `tests/test_analytics_cli.py`; modify `scripts/benchmark.py` or add `scripts/benchmark_analytics.py` for narrowly scoped measurements.

**Consumes:** `build_report`, `write_report`.

- [ ] Add failing subprocess tests: stats from a plain ancestor and with explicit `--root`, empty report, unavailable root, output collisions, missing root, compact JSON output, and `--open` success/failure. Use mocks for browser opening; do not spawn real browsers in unittest.

```python
def test_stats_works_without_selected_nebula_context(self):
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run(
            [sys.executable, str(RUNTIME / 'scripts/nebula.py'), 'stats'],
            cwd=temporary, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result_data = json.loads(result.stdout)
        self.assertEqual(result_data['discovered_nebulas'], 0)
        self.assertTrue(Path(result_data['output']).is_file())
```

- [ ] Run `python3 -m unittest tests.test_analytics_cli -v` and confirm missing stats behavior fails.
- [ ] Add stats parsing outside normal Nebula context resolution. Use `--root`, `--output`, `--open`; default root to `Path.cwd()`. Avoid expanding full report data into stdout.

```python
stats = sub.add_parser('stats')
stats.add_argument('--root', type=Path)
stats.add_argument('--output', type=Path)
stats.add_argument('--open', action='store_true')
```

- [ ] Generate first, then use the standard-library `webbrowser.open(path.as_uri())` for optional opening. Opening failure is a warning with the saved path, not a lost report. Invalid arguments/write failures return nonzero; partial discovery produces a useful report and warnings. Include stats in CLI error handling without constructing a writable Store.
- [ ] Update the shared skill: a stats request runs the bundled launcher at the requested ancestor and reports only output location/coverage. It requires no Nebula ON, no initialization, no teaching, and no acceptance. Add README examples, filters, exclusions/limits, snapshot privacy, metric semantics, analytics tracking start, read-only legacy behavior, and deferred time savings. Update record/integration references for schema 3 while preserving phase-one compatibility limitations.
- [ ] Measure a fixed synthetic fixture's suggestion/feedback/completion overhead and multi-root report generation using `perf_counter`, counts, environment, and serialized bytes. Compare equivalent workloads and record results in the PR; do not infer user time savings from timings.
- [ ] Run final commands and inspect every result:

```sh
python3 -m compileall -q nebula scripts examples tests
python3 -m unittest discover -s tests -v
python3 examples/demo.py
NEBULA_REVIEW_DIR="$(mktemp -d)"
python3 examples/analytics_demo.py --output "$NEBULA_REVIEW_DIR/report.html"
git diff --check
```

Use the new temporary output directory; do not bypass collision protection.
Confirm documentation links resolve. Review the whole
branch diff against the spec and validate that unrelated behavior is unchanged.

- [ ] Commit owned files: `feat: expose stats through cli and shared skill`.
- [ ] Push `feat/analytics` to origin and open the first PR against `main`, titled `feat: add multi-nebula analytics dashboard`. Use the PR description to explain discovered roots, durable tracked counts versus retained history, successful outcomes without time estimates, migration, limits, and actual validation. Attach the created PR to this chat using the app artifact tool.
- [ ] Wait for GitHub CI on the PR head. Fix failures in atomic follow-up commits and rerun affected checks. Report the PR URL, latest commit, CI result, manual UI validation, and remaining live-host limitations. Do not merge automatically.

## Plan review and execution

This plan implements the approved spec without adding time estimates or a
server. Native execution is retained. Implementation begins after the user
reviews this written plan; execute slices sequentially with fresh verification
before each commit. Update checkboxes to reflect completed work and record any
necessary departures from the spec explicitly.
