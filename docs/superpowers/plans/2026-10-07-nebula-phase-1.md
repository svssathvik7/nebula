# Nebula Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Recommended execution for this project: native implementation in the current session, with a final independent review if authorized.

**Goal:** Give Claude Code and Codex shared contextual learning across a parent folder's selected projects, with evidence-based maturity, confidence, suggestions, immediate promotion on acceptance, and correction.

**Architecture:** A shared skill keeps the existing host agent responsible for lesson extraction and contextual application. Host hooks capture bounded session evidence; a Python/SQLite utility handles persistence, deduplication, retrieval, scoring, and feedback. No standalone reasoning agent, background monitor, or predefined cleanup subsystem is built.

**Tech Stack:** Python 3.11+ standard library, SQLite, `unittest`, JSON, Markdown Agent Skills, Claude/Codex command hooks. No runtime third-party Python dependencies, API keys, network services, or additional model calls from the utility. Python 3.11 is an implementation floor, not an existing spec requirement; this machine currently has Python 3.14.5.

**Spec:** [Approved design](../specs/2026-10-06-nebula-phase-1-design.md).

## Global Constraints

- Observation source: Claude Code and Codex sessions only; application occurs during active sessions.
- A nebula is a canonical parent root with explicitly selected child projects; unrelated nebulas do not share evidence.
- New behaviors default to `mature=false`.
- Observational maturity: five independent human-choice episodes, three sessions, two selected projects, and three verified suitable outcomes.
- Observational confidence: `(positive + 1) / (positive + negative + 2)`.
- Explicit acceptance immediately makes the specific lesson mature and sets effective confidence to `max(observational_confidence, 0.80)`.
- Automatic learned application requires maturity and confidence strictly greater than `0.75`, a current context match, and existing host permissions.
- Retraction/correction revokes confirmation; material lesson changes do not inherit it.
- Silence, model assertions, and autonomous executions are not positive human-choice evidence.
- Retrieve at most six lesson summaries by default; full evidence is on demand.
- At most 10,000 raw metadata events, a 14-day raw-event window, and a 90-day observational decision-evidence window. Active confirmations survive these windows.
- Total `.nebula` budget: 32 MiB soft limit and 64 MiB hard cap, including database sidecars.
- Proposed p95 hook capture target: <= 50 ms on this machine; actual latency and context overhead must be measured.
- Preserve existing agent configuration. Uninstall removes only unchanged Nebula-owned entries.
- General lesson/workflow learning is the scope. Disk cleanup is an example and is not a required integration.
- No product code, dependency installation, agent registration, or changes to user-wide settings before plan review.
- This workspace has no Git repository. Do not initialize one just to satisfy commit steps. If Git is available at execution time, stage only the named task files and commit; otherwise record completed task checks in this plan.

## Review Focus

1. A generated continuation or quoted acknowledgement must not be mistaken for a human confirming a suggestion. Task 2 tests event origin handling; Task 4 tests acknowledgement binding and replay rejection.
2. Identical commands in repeated retries, parallel sessions, or sibling paths must not inflate evidence. Tasks 1 and 3 test canonical identity, transactional idempotence, and independent-episode counting.
3. Contextually different preferences must remain separate, and a new lesson version must lose the prior confirmation. Tasks 3 and 5 test context fingerprints, versioning, and conflicting retrieval.
4. Existing settings edited after installation must survive uninstall, and a child Git root must not hide the skill. Task 6 tests partial configuration edits, discovery, and installation repair.
5. Long-running usage, incomplete writes, and storage pressure must preserve confirmations and stop automatic learned application when evidence becomes unavailable. Tasks 1 and 7 test recovery, retention, sidecar accounting, and capacity enforcement.

## Delivery boundaries and repository layout

Implement one cohesive phase-1 product in eight sequential tasks. Each task has an independent verification gate. The final two tasks connect the already tested pieces and demonstrate host behavior; fixtures alone do not establish agent reasoning quality.

```text
nebula/
  __init__.py          package marker and version
  __main__.py          CLI entry point
  models.py            bounded validated record types
  roots.py             nebula discovery and scope resolution
  store.py             SQLite schema, transactions, and record operations
  capture.py           bounded event ingestion and provenance classification
  lessons.py           lesson validation, sample attribution, and versioning
  scoring.py           pure maturity/confidence calculation
  feedback.py          suggestion creation and bound human feedback
  recall.py            shortlist ranking and context decisions
  application.py       idempotent application claims and outcomes
  lifecycle.py         init, on, off, status
  maintenance.py       retention, capacity limits, integrity checks
  install.py           managed child-workspace registration/uninstall
  cli.py               argparse commands and compact JSON output
  adapters/
    __init__.py
    claude.py          Claude input/output normalization
    codex.py           Codex input/output normalization
scripts/
  nebula.py            location-independent utility launcher
  nebula_hook.py       location-independent hook launcher
  benchmark.py         repeatable capture/retrieval/storage measurements
skills/nebula/
  SKILL.md             shared reasoning workflow and invocation surface
  references/records.md  bounded event, lesson, suggestion, feedback formats
  references/integration.md  setup and host-owned hook trust instructions
  scripts/nebula.py    skill-relative utility launcher
  scripts/hook.py      skill-relative hook launcher
schemas/
  lesson.example.json example of a contextual lesson, not learned history
  feedback.example.json example of explicitly bound feedback
examples/
  demo.py              synthetic fixture demonstration using temporary roots
  agent-prompts.json   harmless live-host evaluation prompts and criteria
  results/README.md    result format and synthetic/live distinction
tests/
  __init__.py
  support.py           shared temporary workspace and record factories
  test_roots_store.py
  test_capture.py
  test_lessons_scoring.py
  test_feedback.py
  test_recall_application.py
  test_cli_install.py
  test_maintenance.py
  test_demo.py
README.md
.gitignore
```

Scripts must resolve the package from `__file__`, not from the caller's working directory. The skill-relative launchers resolve the canonical skill source after following its symlink. Copies must include their runnable package reference in the owned installation manifest.

## Shared data and API contracts

Use frozen dataclasses and JSON serialization in `nebula/models.py`. All timestamps are timezone-aware UTC ISO strings. Public JSON accepts only declared fields. Text is bounded; no arbitrary executable payload is evaluated by the utility.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Host = Literal['claude', 'codex']
Origin = Literal['human', 'assistant', 'subagent', 'system', 'unknown']
Verdict = Literal['positive', 'negative']
Outcome = Literal['suitable', 'failed', 'unknown']

@dataclass(frozen=True)
class Context:
    root: Path
    project: Path
    nebula_id: str
    enabled: bool

@dataclass(frozen=True)
class Event:
    event_id: str
    host: Host
    session_id: str
    turn_id: str
    episode_id: str
    project: str
    timestamp: str
    kind: str
    origin: Origin
    hint: str             # <= 512 characters; relevant bounded metadata
    digest: str           # canonical source-payload digest

@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    version: int
    kind: str             # preference/convention/decision-heuristic/workflow
    trigger: str          # <= 512 characters
    action: str           # <= 1024 characters; description, not an executor
    context_tags: tuple[str, ...]
    exceptions: tuple[str, ...]
    scope_projects: tuple[str, ...]  # empty means selected nebula projects
    rationale: str
    rationale_source: str # human/inferred/unspecified
    evidence_ids: tuple[str, ...]
    disabled: bool = False

@dataclass(frozen=True)
class Sample:
    lesson_id: str
    version: int
    episode_id: str
    session_id: str
    project: str
    source_event_id: str
    verdict: Verdict
    outcome: Outcome
    timestamp: str

@dataclass(frozen=True)
class Score:
    observational_mature: bool
    observational_confidence: float
    mature: bool
    confidence: float
    positives: int
    negatives: int
    successful_episodes: int

@dataclass(frozen=True)
class Suggestion:
    suggestion_id: str
    lesson_id: str
    version: int
    session_id: str
    episode_id: str
    project: str
    context_digest: str
    created_at: str
    status: str           # pending/accepted/rejected/superseded

@dataclass(frozen=True)
class Decision:
    mode: str             # none/suggest/apply/blocked
    reason: str
    lesson_id: str
    version: int
    score: Score | None
```

Test snippets below use standard `unittest.TestCase`. Each owning module imports `unittest`, its declared production interfaces, and the needed `tests.support` factories; subprocess/install tests also import `json` and `Path`.

`tests/support.py` supplies `workspace()` as a temporary-directory context manager yielding `(root, project_a, project_b)`, `event(...)`, `lesson(...)`, `sample(...)`, and `mature_samples(...)` factories returning these dataclasses with valid fixed defaults. `mature_samples()` yields five independent positive episodes across three sessions and two projects with at least three suitable outcomes; keyword overrides vary specific fields without silently adding evidence.

SQLite tables: `meta`, `events`, `receipts`, `lessons`, `samples`, `suggestions`, `confirmations`, `applications`, `installations`, `audit`. Index timestamps and lesson/version/context keys. Unique sample key: `(lesson_id, version, episode_id)`; unique application key: `(lesson_id, version, session_id, episode_id)`. A sample is corrected with audit metadata instead of creating a second sample for the same decision. Store IDs, hashes, excerpts, and lesson records; do not persist full source payloads or transcripts. Samples, confirmations, and audit rows keep their compact source provenance independently of expiring raw events; expiry must not cascade-delete an active confirmation. Use bounded transactions, `busy_timeout=100`, WAL, and a schema version. Use parameterized SQL only.

## Task 1: Nebula identity, lifecycle, and transactional storage

**Files:** Create `nebula/{__init__,models,roots,store,lifecycle}.py`, `tests/{__init__,support,test_roots_store}.py`, `.gitignore`.

**Interfaces:**

- `init_nebula(root: Path, projects: list[Path]) -> Context`; starts disabled.
- `resolve_context(cwd: Path) -> Context | None`; nearest canonical selected ancestor, including nested-nebula shadowing.
- `set_enabled(root: Path, enabled: bool) -> None`.
- `Store(root: Path)` context manager with `put_event(Event) -> bool`, `get_event(str) -> Event | None`, `put_lesson(Lesson) -> None`, `get_lesson(str, int | None = None) -> Lesson | None`, `put_sample(Sample) -> bool`, `samples(str, int) -> list[Sample]`, `lessons() -> list[Lesson]`, `status() -> dict`.
- Schema operations are internal to `Store`; later modules use methods rather than reaching into an undocumented connection.

- [ ] **Step 1: Add failing integration tests with temporary roots.**

```python
class RootsStoreTests(unittest.TestCase):
    def test_shared_parent_and_idempotent_event(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            set_enabled(root, True)
            self.assertEqual(resolve_context(a).nebula_id,
                             resolve_context(b).nebula_id)
            with Store(root) as store:
                first = event(project=str(a))
                self.assertTrue(store.put_event(first))
                self.assertFalse(store.put_event(first))
                self.assertEqual(store.get_event(first.event_id), first)

    def test_unselected_and_symlink_escape_are_not_selected(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a])
            self.assertIsNone(resolve_context(b))
            outside = root.parent / 'outside'
            outside.mkdir()
            (a / 'escape').symlink_to(outside, target_is_directory=True)
            self.assertIsNone(resolve_context(a / 'escape'))
```

Also test that a nested nebula shadows its outer nebula, separate roots have different identities, disabled state survives restart, same event ID/different digest is rejected, two subprocess writers insert independent events without loss, and a corrupt database returns a named state-unavailable error rather than recreating empty learned history.

- [ ] **Step 2: Run `python3 -m unittest tests.test_roots_store -v`; verify the new behavior fails before implementation.**
- [ ] **Step 3: Implement canonical discovery, bounded record validation, and storage.** Identity uses SHA-256 of the canonical parent path; project names are canonical paths, never substring matches. Create `.nebula/config.json` and `.nebula/state.sqlite3` with private permissions and a `.nebula/.gitignore` containing `*`. Do not overwrite a conflicting existing `.nebula`. Set `PRAGMA user_version=1`, create the declared tables/indexes, and use transactions for unique inserts.

```python
# Required core algorithms; incorporate validation and named errors around them.
canonical_root = root.resolve(strict=True)
canonical_project = project.resolve(strict=True)
canonical_project.relative_to(canonical_root)  # ValueError rejects escape
confidence_key = (lesson_id, version, episode_id)
# Event insert: ON CONFLICT(event_id) DO NOTHING, then compare existing digest.
# Missing/corrupt schema: raise StateUnavailable; never reset existing evidence.
```

- [ ] **Step 4: Run the task suite and inspect `.nebula` permissions within fixtures; all tests pass.**
- [ ] **Step 5: If Git is present, commit only this task's created files with `feat: add nebula identity and evidence store`; otherwise mark the task gate completed here.**

## Task 2: Host hooks, bounded evidence, and actual payload characterization

**Files:** Create `nebula/{capture,adapters/__init__,adapters/claude,adapters/codex}.py`, `scripts/nebula_hook.py`, `tests/test_capture.py`; extend `nebula/store.py` with bounded capture and hook-receipt operations.

**Interfaces:**

- `normalize(host: Host, payload: dict, *, now: str) -> Event | None` in `capture.py`, delegating host differences to adapters.
- `capture_event(root: Path, host: Host, payload: dict, *, now: str) -> str | None` validates selected context, records the event once, and returns its ID.
- `run_hook(host: Host, stream: BinaryIO, output: TextIO) -> int` reads at most 64 KiB, exits 0 without blocking host work on capture errors, and emits at most 2 KiB supported additional context for start/prompt events.
- `Store.put_receipt(event_id: str, source: str, acknowledgement: dict | None) -> None` and `Store.receipt(event_id: str) -> dict | None`; callers cannot set human origin through lesson or feedback arguments.

- [ ] **Step 1: Write tests for both documented host shapes and unknown provenance.**

```python
class CaptureTests(unittest.TestCase):
    def test_tool_execution_is_not_a_human_choice(self):
        for host in ('claude', 'codex'):
            payload = {'session_id': 's1', 'cwd': '/fixture/project',
                       'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                       'tool_input': {'command': 'echo okay'},
                       'tool_response': {'exit_code': 0}}
            normalized = normalize(host, payload, now='2026-10-07T00:00:00Z')
            self.assertNotEqual(normalized.origin, 'human')

    def test_subagent_and_unknown_prompt_origin_are_not_confirmation(self):
        for host in ('claude', 'codex'):
            payload = {'session_id': 's1', 'cwd': '/fixture/project',
                       'hook_event_name': 'UserPromptSubmit',
                       'prompt': 'NEBULA ACCEPT suggestion-1', 'agent_id': 'a1'}
            normalized = normalize(host, payload, now='2026-10-07T00:00:00Z')
            self.assertIn(normalized.origin, ('subagent', 'unknown'))
```

Test malformed JSON, oversized input, null optional fields, unknown hook event names, same tool event delivered twice, a generated continuation, no nebula, OFF, and a non-UTF-8 payload. Exercise emitted JSON against each host's event-specific output shape; never return a block/continue directive or exit 2. Tool output is reduced to outcome metadata, not retained wholesale.

- [ ] **Step 2: Run `python3 -m unittest tests.test_capture -v` and confirm the new cases fail.**
- [ ] **Step 3: Implement bounded normalization and capture, then characterize live payloads in disposable child repositories.** Run the hook launcher from a different CWD using an absolute path. Distinguish direct user submissions from tool/assistant/subagent evidence, known generated `Stop` continuations, and programmatic sessions. Preserve stable host IDs where supplied; hash canonical event content with session/turn/tool identifiers otherwise. Missing origin evidence becomes `unknown`; do not invent a documented human-origin field.

```python
raw = stream.read(65537)
if len(raw) > 65536:
    return 0
# For a direct acknowledgement, recognize the ENTIRE submitted prompt, not
# quoted substrings: NEBULA ACCEPT <id>, NEBULA REJECT <id>, NEBULA DISABLE <id>,
# NEBULA WITHDRAW <id>, and NEBULA CORRECT <id>. The id binds a suggestion.
# NEBULA REVIEW <lesson-id> <version> binds explicit suspension review.
# Generic 'yes' is resolved only with one pending suggestion in the same session
# and verified direct-user submission; otherwise leave it unresolved.
```

Record the real field names and source classification in `skills/nebula/references/integration.md` in Task 6. Test a manually submitted prompt, a tool result, a subagent event, and a generated continuation on each installed host. Hooks provide host-event provenance, not cryptographic authentication of a person. If a host cannot distinguish a submission source, keep it unknown and report the capture limitation; do not silently promote it. The release gate requires a demonstrated direct-user acceptance path on each host. Use an explicit bound acknowledgement when free-form acceptance cannot be attributed reliably; this is a concrete fallback, not an inferred approval.

- [ ] **Step 4: Rerun the capture suite; save a sanitized live-payload report in the integration reference, omitting raw personal prompts.**
- [ ] **Step 5: If Git is present, commit this task's files with `feat: capture bounded claude and codex evidence`.**

## Task 3: General lessons, independent evidence, and observational scoring

**Files:** Create `nebula/{lessons,scoring}.py`, `schemas/lesson.example.json`, `tests/test_lessons_scoring.py`; extend `store.py` for versioned lesson/sample operations.

**Interfaces:**

- `record_lesson(store: Store, draft: dict) -> Lesson`; validates evidence IDs and rationale provenance, produces version 1 or a changed version.
- `record_sample(store: Store, value: Sample) -> bool`; source event must be attributable and belong to the sample's session/project/episode.
- `score(samples: list[Sample], *, confirmed: bool = False, disabled: bool = False) -> Score`; pure calculation after retention filtering.
- `Store.put_sample` deduplicates one sample per lesson/version/episode; explicit corrections replace its verdict with audit metadata.

- [ ] **Step 1: Write the evidence/scoring tests.**

```python
class ScoringTests(unittest.TestCase):
    def test_five_independent_choices_mature(self):
        result = score(mature_samples())
        self.assertTrue(result.mature)
        self.assertAlmostEqual(result.confidence, 6 / 7)

    def test_high_score_does_not_replace_evidence_coverage(self):
        same_session = mature_samples(session_id='only-session')
        self.assertFalse(score(same_session).mature)

    def test_boundary_is_exactly_three_quarters(self):
        result = score([sample(episode_id=f'p{i}') for i in range(5)] +
                       [sample(episode_id='n1', verdict='negative')])
        self.assertEqual(result.confidence, 0.75)
```

Also test five choices with fewer than three suitable outcomes, single-project observations, conflicting context tags that remain separate lessons, unavailable evidence IDs, fabricated human rationale, autonomous source events, repeated retry episodes, and edits to action/trigger/scope producing a new unconfirmed version.

- [ ] **Step 2: Run `python3 -m unittest tests.test_lessons_scoring -v` and verify failure.**
- [ ] **Step 3: Implement pure scoring and lesson persistence.** Use exact episode/session/project counts; negative feedback contributes to confidence but does not satisfy positive-outcome coverage. Allow `rationale_source='human'` only with referenced direct-user evidence; otherwise retain `inferred`/`unspecified`. Equivalent drafts with identical material fingerprints reuse the version; changed trigger/action/exception/scope creates a new version without copied confirmation. Do not merge different triggers solely because their action text matches.

```python
positive = sum(s.verdict == 'positive' for s in samples)
negative = sum(s.verdict == 'negative' for s in samples)
observational_confidence = (positive + 1) / (positive + negative + 2)
observational_mature = (
    len({s.episode_id for s in samples}) >= 5
    and len({s.session_id for s in samples}) >= 3
    and len({s.project for s in samples}) >= 2
    and sum(s.verdict == 'positive' and s.outcome == 'suitable'
            for s in samples) >= 3
)
effective_mature = (observational_mature or confirmed) and not disabled
effective_confidence = max(observational_confidence, 0.80) if confirmed else observational_confidence
```

- [ ] **Step 4: Run the task suite and earlier storage/capture suites; all pass.**
- [ ] **Step 5: If Git is present, commit this task's files with `feat: learn contextual lessons with evidence scoring`.**

## Task 4: Suggestions, immediate confirmation, correction, and revocation

**Files:** Create `nebula/feedback.py`, `schemas/feedback.example.json`, `tests/test_feedback.py`; extend `store.py` with suggestion/confirmation operations.

**Interfaces:**

- `suggest(store: Store, lesson: Lesson, *, session_id: str, episode_id: str, project: str, context_digest: str, now: str) -> Suggestion`.
- `apply_feedback(store: Store, *, suggestion_id: str, source_event_id: str, verdict: str, now: str) -> Score`; accepts `accept/reject/correct/withdraw/disable`, verifies bound hook receipt, and records feedback transactionally.
- `Store.get_suggestion(str) -> Suggestion | None`, `Store.pending_suggestions(session_id: str) -> list[Suggestion]`, `Store.confirmed(lesson_id: str, version: int) -> bool`, and `Store.confirmation(lesson_id: str, version: int) -> dict | None`.

- [ ] **Step 1: Write immediate acceptance and negative-feedback tests.**

```python
class FeedbackTests(unittest.TestCase):
    def test_single_acceptance_promotes_without_five_samples(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with Store(root) as store:
                value = lesson()
                store.put_lesson(value)
                pending = suggest(store, value, session_id='s1',
                                  episode_id='e1', project=str(a),
                                  context_digest='context-a',
                                  now='2026-10-07T00:00:00Z')
                receipt_event = event(event_id='accept-1', origin='human',
                                      project=str(a), session_id='s1', episode_id='e1')
                store.put_event(receipt_event)
                store.put_receipt('accept-1', 'verified-host-submission',
                                  {'verb': 'accept', 'suggestion_id': pending.suggestion_id})
                result = apply_feedback(store, suggestion_id=pending.suggestion_id,
                                        source_event_id='accept-1', verdict='accept',
                                        now='2026-10-07T00:01:00Z')
                self.assertTrue(result.mature)
                self.assertGreaterEqual(result.confidence, 0.80)
```

Fixture receipts represent the actual Task 2 hook path; the public CLI must not expose receipt creation or accept a caller-supplied human-origin flag. Add cases for ambiguous `yes` with two pending suggestions, quoted acceptance text, unknown origin, different session, stale lesson version, repeated acceptance event, acceptance with scope mismatch, subsequent rejection, restart, and retention of confirmation after observational evidence expires. A repeated identical acceptance is idempotent, not a new sample; a different receipt attempting to reuse a completed suggestion is rejected.

- [ ] **Step 2: Run `python3 -m unittest tests.test_feedback -v`; confirm failure.**
- [ ] **Step 3: Implement a transaction that validates suggestion + receipt, updates its status, records one episode sample, and persists the scoped confirmation.** Rejection/correction/withdrawal revokes the floor. Disable sets the lesson disabled immediately. No guessed matching to old suggestions. An explicitly scoped confirmation can be used in a later matching child project but does not expand the lesson's declared scope.

```python
# Store must load the captured receipt, not trust an origin in feedback JSON.
if receipt is None or receipt['verb'] != verdict:
    raise ValueError('feedback requires matching captured user acknowledgement')
if receipt['suggestion_id'] != suggestion.suggestion_id:
    raise ValueError('acknowledgement does not identify this suggestion')
# Inside one transaction: update suggestion, sample, confirmation, audit record.
```

- [ ] **Step 4: Run feedback and scoring suites, including confidence 0.75 and revoked-confirmation cases; all pass.**
- [ ] **Step 5: If Git is present, commit with `feat: promote accepted suggestions and revoke corrections`.**

## Task 5: Bounded recall, contextual decisions, and application tracking

**Files:** Create `nebula/{recall,application}.py`, `tests/test_recall_application.py`; extend `store.py` with application operations.

**Interfaces:**

- `recall(store: Store, *, project: str, query: str, limit: int = 6) -> list[dict]`; summaries include IDs, trigger/action, exceptions, scope, score, and status.
- `decide(lesson: Lesson, score: Score, *, enabled: bool, context_match: bool | None, permissions_ok: bool, suspended: bool = False) -> Decision`; the host agent supplies its contextual assessment, and the result does not constitute tool permission.
- `claim_application(store: Store, *, lesson_id: str, version: int, session_id: str, episode_id: str, project: str) -> bool`; rejects duplicate/out-of-scope/nonqualifying/disabled applications.
- `finish_application(store: Store, *, lesson_id: str, version: int, session_id: str, episode_id: str, outcome: Outcome, source_event_ids: list[str]) -> None`; records outcome and suspends on failure, without adding positive preference evidence.
- `review_application(store: Store, *, lesson_id: str, version: int, source_event_id: str) -> None`; clears suspension only with captured explicit user review, not an agent assertion.

- [ ] **Step 1: Write decision and retrieval tests.**

```python
class RecallTests(unittest.TestCase):
    def test_uncertain_context_still_suggests_after_confirmation(self):
        confirmed_score = score([], confirmed=True)
        result = decide(lesson(), confirmed_score, enabled=True,
                        context_match=None, permissions_ok=True)
        self.assertEqual(result.mode, 'suggest')

    def test_mature_matching_lesson_applies(self):
        result = decide(lesson(), score(mature_samples()), enabled=True,
                        context_match=True, permissions_ok=True)
        self.assertEqual(result.mode, 'apply')

    def test_boundary_does_not_apply(self):
        boundary = score([sample(episode_id=f'p{i}') for i in range(5)] +
                         [sample(episode_id='n', verdict='negative')])
        result = decide(lesson(), boundary, enabled=True,
                        context_match=True, permissions_ok=True)
        self.assertNotEqual(result.mode, 'apply')
```

Also test OFF, failed/suspended application, wrong scope, two opposing lessons with the same query, case-normalized whole-word ranking, more than six candidates, empty query, long query truncation, disabled current lesson version, and duplicate application claims across concurrent writers. Scope filtering must happen before ranking; confidence alone must not select an unrelated lesson.

- [ ] **Step 2: Run `python3 -m unittest tests.test_recall_application -v`; confirm failure.**
- [ ] **Step 3: Implement shortlist filtering and deterministic ranking without embeddings or a network call.** Scope match first, token overlap with trigger/context second, then confidence and lesson ID for stable ordering. Truncate each summary and bound aggregate output to 8 KiB. Return conflicting candidates with an explicit conflict flag; the skill resolves them or suggests clarification. `context_match=False` yields `none`, unknown yields `suggest`, unavailable permissions/suspended state yields `blocked`, and OFF yields `none`.

```python
# Apply only after the host's separate context/permission checks.
if not enabled or context_match is False:
    mode = 'none'
elif context_match is None:
    mode = 'suggest'
elif suspended or not permissions_ok:
    mode = 'blocked'
elif value.mature and value.confidence > 0.75:
    mode = 'apply'
else:
    mode = 'suggest'
```

The utility never runs a lesson's action string. The skill translates descriptions to current host tools and records outcomes. A no-match case can still provide evidence for a new lesson during normal task work.

- [ ] **Step 4: Run task and prior scoring/feedback suites; verify no autonomous application changes the positive sample count.**
- [ ] **Step 5: If Git is present, commit with `feat: recall relevant lessons and track contextual application`.**

## Task 6: Usable CLI, shared skill, and reversible child registration

**Files:** Create `nebula/{__main__,cli,install}.py`, `scripts/nebula.py`, `skills/nebula/{SKILL.md,references/records.md,references/integration.md,scripts/nebula.py,scripts/hook.py}`, `tests/test_cli_install.py`, `README.md`.

**Interfaces:**

- `main(argv: list[str] | None = None) -> int` returns compact JSON or a clear named error.
- `plan_install(root: Path, projects: list[Path], hosts: list[Host], runtime: Path) -> list[dict]` generates a reviewable local changeset.
- `install(changeset: list[dict]) -> dict`, `uninstall(root: Path, project: Path, host: Host) -> dict`; manifest-owned changes only, skip modified owned files and report them.
- CLI: `init ROOT --project PATH` (repeatable), `on/off/status --root ROOT`, `observe --host HOST` (bounded stdin metadata, not a human-origin override), `record-lesson --stdin`, `record-sample --stdin`, `recall --project PATH --query TEXT`, `suggest --stdin`, `feedback --suggestion ID --source-event ID --verdict VERDICT`, `inspect --lesson ID`, `application claim/finish/review --stdin`, `install --host HOST --project PATH --dry-run`, `uninstall --host HOST --project PATH`, `maintain --root ROOT`.
- Public `observe` records untrusted metadata only and cannot create human receipts; only the configured host-hook ingestion path creates captured receipts. Supporting receipt APIs are not exposed as user-configurable CLI fields. Explicit argumentless `--root` resolution uses the nearest registered ancestor; it never broadens to unrelated directories.

- [ ] **Step 1: Write subprocess CLI and configuration-preservation tests.**

```python
class InstallTests(unittest.TestCase):
    def test_install_uninstall_preserves_existing_hook(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            settings = a / '.claude' / 'settings.local.json'
            settings.parent.mkdir()
            original = {'hooks': {'Stop': [{'hooks': [
                {'type': 'command', 'command': 'echo existing'}]}]}}
            settings.write_text(json.dumps(original))
            install(plan_install(root, [a], ['claude'], Path.cwd()))
            uninstall(root, a, 'claude')
            self.assertEqual(json.loads(settings.read_text()), original)
```

Test paths containing spaces/quotes, a preexisting `nebula` skill folder, malformed existing JSON, a `.codex/hooks.json` plus existing inline hooks (no duplicate equivalent hooks), symlinked runtime relocation, modified managed entries on uninstall, repeated install, interrupted setup, and discoverable skills from a nested child Git repository. Test CLI operation from an unrelated CWD using the absolute launcher.

- [ ] **Step 2: Run `python3 -m unittest tests.test_cli_install -v`; confirm failure.**
- [ ] **Step 3: Implement child registration and CLI.** Claude uses `.claude/skills/nebula` and merges `.claude/settings.local.json`; Codex uses `.agents/skills/nebula` and `.codex/hooks.json` beside an active project config layer. Reuse an existing trusted `.codex/config.toml`, or create a managed empty config layer only when absent. Do not edit user-wide settings, write host trust records, or bypass hook trust. Symlink the shared skill source on this macOS host; reject collisions, record canonical target, and report unsupported symlinks without silently substituting a broken skill. Use `shlex.quote` for generated command arguments, with an absolute selected interpreter and skill hook launcher.

```python
import shlex
import sys
from pathlib import Path

def hook_groups(runtime: Path, host: Host) -> dict:
    launcher = runtime.resolve() / 'scripts' / 'nebula_hook.py'
    command = ' '.join(shlex.quote(arg) for arg in (
        sys.executable, str(launcher), '--host', host))
    groups = {}
    for name in ('SessionStart', 'UserPromptSubmit', 'PreToolUse',
                 'PostToolUse', 'Stop'):
        group = {'hooks': [{'type': 'command', 'command': command, 'timeout': 1}]}
        if name in ('PreToolUse', 'PostToolUse'):
            group['matcher'] = 'Bash|Edit|Write|apply_patch|mcp__.*'
        groups[name] = [group]
    return {'hooks': groups}
```

`hook_groups(runtime: Path, host: Host) -> dict` is an internal installation
helper. The generated command is literal and fully quoted; no Git command
substitution or guessed relative runtime path is used. Adapt tool matchers
from measured host payloads. Capture failure is advisory; no learning hook
blocks normal work. Registration needs a fresh session and host-owned trust
review as documented in the integration reference.

Before authoring the actual skill, invoke the writing-skills skill. The shared `SKILL.md` must teach this exact sequence: ON from parent -> selected projects -> recall at start/task change -> assess trigger/exception/scope -> suggest if immature/uncertain -> record captured acceptance -> apply eligible lesson through ordinary host tools -> record outcome -> extract bounded lessons at completed decision boundaries. Teach `NEBULA ACCEPT <suggestion-id>` as an unambiguous acknowledgement and allow natural acceptance only when its captured source and suggestion binding are verified. Explicitly separate observed human reasoning from inferred rationale. Include one convention example and one tradeoff/workflow example, rather than cleanup commands. It must not turn an ON instruction into authorization to change unrelated settings or projects.

- [ ] **Step 4: Run the CLI/installation suite and the complete utility suite. Verify `python3 scripts/nebula.py --help` from a temporary unrelated directory.**
- [ ] **Step 5: If Git is present, commit with `feat: add shared nebula skill and reversible host setup`.**

## Task 7: Retention, capacity enforcement, recovery, and overhead measurements

**Files:** Create `nebula/maintenance.py`, `scripts/benchmark.py`, `tests/test_maintenance.py`; integrate preflight into store/capture/recall/status without introducing idle polling.

**Interfaces:**

- `maintain(root: Path, *, now: str) -> dict` expires raw events/observational samples, keeps active confirmations, checkpoints/compacts safely, and reports counts and bytes.
- `usage_bytes(root: Path) -> int` counts `.nebula` files and SQLite sidecars without escaping through symlinks.
- `capacity_state(root: Path) -> str` yields `normal/soft-limit/hard-limit`.
- `health(root: Path) -> dict` includes schema, integrity, writable/enabled state, and evidence completeness. Capture/automatic application is blocked at the hard cap or unavailable evidence; ordinary agent work continues.

- [ ] **Step 1: Write retention and resource-bound tests with an injected clock.**

```python
class MaintenanceTests(unittest.TestCase):
    def test_hard_limit_counts_sidecars(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            with (root / '.nebula' / 'large-sidecar').open('wb') as stream:
                stream.truncate(64 * 1024 * 1024)
            self.assertEqual(capacity_state(root), 'hard-limit')
```

Also test 10,001 raw events, 14-day and 90-day boundaries, a confirmed lesson with all raw sources expired, open concurrent readers during compaction, missing/corrupt state, interrupted transaction rollback, and disabled state. Confirmation retains its small provenance digest/summary rather than a dangling mandatory raw-record dependency. Use test-configured tiny budgets where appropriate; do not allocate large physical files needlessly.

- [ ] **Step 2: Run `python3 -m unittest tests.test_maintenance -v`; confirm failure.**
- [ ] **Step 3: Implement periodic maintenance at bounded interaction intervals.** Check cheap database/page counts on capture, enforce input/record size before writes, reserve capacity for essential feedback/confirmation records, and count all actual `.nebula` bytes before an application decision. Run full maintenance at most once per session unless the soft cap triggers it. WAL checkpoints respect active readers; do not pretend a failed checkpoint freed storage. Recompute scores from unexpired samples.

```python
soft = 32 * 1024 * 1024
hard = 64 * 1024 * 1024
state = 'hard-limit' if total_bytes >= hard else (
    'soft-limit' if total_bytes >= soft else 'normal')
# Full cap is enforced against measured DB/sidecars, not the DB file alone.
```

- [ ] **Step 4: Run complete tests, then `python3 scripts/benchmark.py --events 1000 --lessons 100 --runs 100`.** Report p50/p95 full hook subprocess latency, in-process insertion/retrieval latency, database+sidecar size, and maximum recall bytes. Include interpreter cold-start time in capture latency. Record character/byte counts rather than falsely equating them to exact tokens; host usage measurements provide actual added tokens when available. If p95 exceeds 50 ms, optimize measured bottlenecks or report the miss explicitly; do not replace the target with an unmeasured claim.
- [ ] **Step 5: If Git is present, commit with `perf: bound nebula retention and measure hook overhead`.**

## Task 8: Synthetic demonstration and live Claude/Codex acceptance tests

**Files:** Create `examples/{demo.py,agent-prompts.json,results/README.md}`, `tests/test_demo.py`; update `README.md` and the integration reference with verified behavior and limitations.

**Interfaces:** `run_demo() -> dict` creates disposable nebula/project roots, demonstrates the full fixture loop, cleans up, and labels output `synthetic=true`. Live evaluation records use `host`, `host_version`, `model`, `scenario`, `input`, `observed_behavior`, `event_ids`, `lesson_version`, `passed`, and `limitations`; they do not store secrets or full session exports.

- [ ] **Step 1: Write a failing full-loop fixture test.**

```python
class DemoTests(unittest.TestCase):
    def test_full_loop_is_general_and_correction_works(self):
        result = run_demo()
        self.assertTrue(result['synthetic'])
        self.assertEqual(result['initial_mode'], 'suggest')
        self.assertTrue(result['after_acceptance']['mature'])
        self.assertGreater(result['after_acceptance']['confidence'], 0.75)
        self.assertEqual(result['matching_sibling_mode'], 'apply')
        self.assertNotEqual(result['different_context_mode'], 'apply')
        self.assertFalse(result['after_withdrawal']['confirmed'])
```

- [ ] **Step 2: Run `python3 -m unittest tests.test_demo -v`; confirm failure.**
- [ ] **Step 3: Implement a harmless demonstration around a learned convention and verification workflow.** Use two disposable sibling projects. Teach a convention about where to put a new module, suggest it while immature, accept the bound suggestion, recall/apply it in the matching sibling task, avoid applying it in a deliberately different context, and revoke it after correction. All synthetic receipts are test-only; they cannot be imported as real human history through the public CLI.
- [ ] **Step 4: Run `python3 examples/demo.py` and `python3 -m unittest discover -s tests -v`; require both to pass.**
- [ ] **Step 5: Run live sessions on both installed hosts in disposable repositories using the Task 6 registration.** Use native host trust review; never bypass it. Confirm: skill discovered; actual prompt/tool event captured; contextual lesson created with real evidence references; immature lesson suggested; direct-user acceptance immediately promoted it; sibling task applied it through the host tools; differing context withheld it; correction revoked confirmation; OFF stopped capture/application. Use direct user interaction for the acceptance stage. Programmatic `claude -p`/`codex exec` runs can verify tooling and reasoning but must not be presented as human-origin evidence. If a live stage requires user-owned hook trust or manual acceptance, complete the preparation and provide the exact reviewable step instead of fabricating that stage.
- [ ] **Step 6: Run final review against the spec and five Review Focus items.** Report tested behavior separately from unverified live stages. Both-host compatibility is complete only after live host registration/payload tests pass, and human acceptance behavior is complete only after a verified direct-user path is demonstrated. A model's verbal claim is not sufficient; inspect the stored record and actual harmless artifact.
- [ ] **Step 7: If Git is present, commit only final demo/docs/tests with `test: demonstrate contextual nebula learning across hosts`.**

## Sources checked for integration planning

- [Claude hook reference](https://code.claude.com/docs/en/hooks): event handlers receive JSON; settings can hold command hooks. Event/output compatibility is tested rather than assumed.
- [Codex hook reference](https://developers.openai.com/codex/hooks/): project `hooks.json` sits beside an active configuration layer; hook definitions require host-owned trust; `Stop` can create generated continuations. Transcript format is not a stable hook interface.
- [Codex skill discovery](https://developers.openai.com/codex/skills/): repository `.agents/skills` discovery can stop at the repository boundary, so selected children receive discoverable links.
- [Claude skill reference](https://code.claude.com/docs/en/skills): project skills use `.claude/skills`, separate from hook registration.

## Self-review and execution handoff

Spec coverage: Tasks 1/6 cover identity/lifecycle/discovery; Task 2 covers both adapters/provenance; Task 3 covers general lesson extraction records/scoring; Task 4 covers acceptance/revocation; Task 5 covers contextual retrieval/application; Task 7 covers resource limits; Task 8 covers actual host behavior and demonstrations. No disk-cleanup component or background reasoning service is introduced.

The agent's extraction/reasoning workflow is implemented in Task 6's skill and tested with live scenarios in Task 8; utility tests alone do not prove it. Human-source classification is characterized in Task 2 and cannot be silently assumed from a tool exit status. Task 8 explicitly distinguishes human interactions from automation.

Execution recommendation: **native implementation in this chat** because these tasks share tightly coupled evidence, versioning, and feedback interfaces, and the user prioritizes token efficiency. Independent review can be delegated after implementation only if authorized. Subagent-driven execution remains an option if the user prefers per-task independent implementation/review and accepts its higher context cost.

Implementation begins after the user reviews this plan and selects the execution approach, as required by the planning skill. No product dependencies or user agent settings have been changed during planning.
