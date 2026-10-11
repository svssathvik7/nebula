# Nebula analytics design

Status: written design approved by the user on 2026-10-10; implementation pending
plan review. Native execution preference retained from the existing session.
Date: 2026-10-10.
Branch: `feat/analytics`.

## Purpose and agreed scope

A user may have multiple independent Nebulas beneath a common ancestor folder.
Running `nebula stats` through the skill from that folder should produce a local,
interactive HTML report showing each Nebula's learned behaviors, scenarios,
feedback, and recorded application outcomes.

The user selected successful application reporting for this release, with time
savings estimates deferred. This release must not assign invented minutes or
equate successful applications with verified time savings.

Preserve the original goals: low token consumption, small storage overhead,
no idle work, and compatibility with the shared Claude/Codex skill. Generating
a report makes no model calls. Analytics must not alter learning decisions.

## Architecture

Use Python's standard library to discover roots, query local SQLite state, and
render one standalone HTML file containing CSS, JavaScript, and report data.
No frontend build, web server, CDN, external scripts, telemetry, or account is
required. The user opens a generated file locally; optional browser opening is
a convenience after generation succeeds.

Separate responsibilities:

- Discovery finds candidate Nebula roots within a requested filesystem scope.
- Analytics recording updates compact counters during existing transactions.
- Analytics reading produces a normalized report from independent snapshots.
- Rendering turns that report into a self-contained interactive document.
- The CLI coordinates generation and reports its output path and diagnostics.
- The shared skill maps the user's stats request to the CLI without manually
  reading every project or summarizing all lessons into model context.

No global registry or installation changes are needed. Each Nebula remains
independent and owns its own counters.

## CLI and discovery

Add a command usable even when the ancestor is not a selected Nebula project:

```sh
python3 <launcher> stats --root /path/to/my-projects --open
```

`--root` defaults to the working directory. It defines the discovery boundary,
not a requirement that the directory contain `.nebula/config.json`. Report the
root itself when it is a Nebula and continue looking for independent descendant
Nebulas. Nested roots are distinct; count each canonical root once.

Discovery reads directory names and Nebula metadata, never project source files
or transcripts. Do not follow descendant directory symlinks. Skip `.git`,
`.nebula`, `.nebula-reports`, `.superpowers`, `.venv`, `venv`, `node_modules`,
`target`, `dist`, `build`, and `__pycache__`. Inspect the starting directory even
when its own name is on the skip list. Skipped names are documented and reported
as discovery exclusions; users can run stats directly at an excluded root.

Bound discovery to 10,000 visited directories, depth 12 below the starting root,
and 100 candidate Nebulas. When a limit is reached, preserve collected results
and prominently mark discovery as incomplete. Catch permission errors per path.
Validate candidate root/config identity and reject symlinked state/config files.
Malformed, unsupported, missing, or unreadable databases appear as unavailable
Nebulas with diagnostics instead of failing the entire report.

Command options:

- `--output PATH`: choose a new report file. Refuse to overwrite an existing
  destination or write through a symlink. Require the destination parent to
  exist and reject output inside a `.nebula` state directory.
- `--open`: ask the platform browser opener to display the completed report.
  If opening fails, retain the report and return its path with a warning.

The default output is a uniquely named `nebula-stats-<UTC timestamp>.html` in
the starting directory. Reports are snapshots and do not auto-refresh. The CLI
prints a compact JSON summary with output path, discovered/available root counts,
generation timestamp, completeness flags, and warnings. It does not emit all
lesson content into the conversation.

No roots found produces a useful empty report. Partial discovery/database
failures produce a report with warnings and a successful generation result.
Invalid arguments or inability to write the report fail the command.

## Dashboard contents

The overview shows discovered and available Nebulas, selected project counts,
current lesson counts, mature lessons, disabled/suspended lessons, and tracked
successful applications. Unavailable roots do not contribute zero-valued
statistics; totals explicitly cover only available roots.

Each Nebula section includes its canonical path, enabled state, selected
projects, schema version, state size, report coverage, and tracking start time.
Storage measurement respects the existing bounded storage traversal and never
creates state.

Each current lesson shows:

- ID, current version, kind, trigger/scenario, action, and project scope.
- Context tags, exceptions, rationale, and rationale attribution.
- Effective maturity/confidence and observational maturity/confidence.
- Confirmed, disabled, and suspended state, with appropriate explanatory labels.
- Tracked suggestions, feedback counts, claims, and completed outcome counts.
- Retained recent activity and explicit exception reasons where available.

Confidence is labeled as a consistency score, not a probability of correctness.
Maturity alone is not labeled permission to execute: context, refusals, scope,
and host permissions remain application conditions.

Keep version-specific counters separate. Default lesson details show the current
version, with a versions view for older versions. Nebula totals include all
tracked versions. Per-project filters use recorded execution/feedback project
identity rather than guessing from the current lesson's scope.

Provide search across lesson descriptions and filters for Nebula, project,
lesson kind, and maturity. Use expandable lesson details, summary cards, and
simple feedback/outcome bars. No time savings card or estimated minutes appears.
Recent activity reflects retained records and is not a lifetime activity log.

## Metric definitions

All persistent metrics are counts tracked since analytics initialization,
grouped by lesson ID, version, and project:

| Metric | Increment condition |
| --- | --- |
| Suggestions | A new suggestion is persisted; returning an existing suggestion does not increment |
| Accepted | First valid acceptance for a suggestion |
| Rejected | First valid rejection for a suggestion |
| Exceptions | First explicit exception verdict for a suggestion |
| Corrected, withdrawn, disabled | First corresponding valid verdict for a suggestion |
| Application claims | A new eligible application claim succeeds |
| Successful applications | A claimed application first finishes with outcome `suitable` |
| Failed applications | A claimed application first finishes with outcome `failed` |
| Unknown outcomes | A claimed application first finishes with outcome `unknown` |

Feedback counts represent suggestions that received each response category.
A suggestion accepted and later withdrawn contributes once to both categories.
Repeated acknowledgement, even with a new source event, does not increment the
same suggestion/verdict pair again. Exception reasons remain bounded contextual
records; changing a reason does not create another exception count.

These analytics definitions do not change existing rejection penalty semantics,
which apply once per decision episode. Successful applications are recorded
engine outcomes with existing captured evidence requirements; they are not
additional human preference samples or proof of user-verified utility.

Unfinished applications are a current-state count of actual `claimed` records.
Feedback-only application rows used for refusal bookkeeping are not executions.
Do not infer historical unfinished counts by subtracting completed outcomes from
tracked claims: an application may have begun before tracking initialization.

## Persistence, migration, and retention

Introduce schema version 3 with compact counter rows and per-suggestion verdict
deduplication state. Record an `analytics_since` UTC timestamp. Counter updates
and deduplication markers occur in the same SQLite transaction as their source
operation, so failures roll back together. A replay must neither inflate counters
nor alter execution behavior.

Counter cardinality follows existing lesson-version/project identities, not
individual hook events. Store integers and identifiers, not additional prompts,
tool outputs, reasons, or transcripts. Existing storage budgets apply. Analytics
does not bypass the feedback reserve or weaken essential refusal handling.

Suggestion deduplication records expire only when their suggestion is removed.
An expired suggestion cannot accept new feedback through the existing API.
Completed-application deduplication uses its existing completion state and replay
guard. Preserve aggregate counters when audit, raw events, samples, suggestions,
and completed applications expire. No permanent per-event analytics log is added.

Normal engine use performs the transactional v2-to-v3 migration after existing
schema validation. A v1 engine upgrade follows the existing provenance migration
before analytics initialization. New Nebulas initialize tracking immediately.
Do not manufacture counts from old rows during migration: older history may
have expired or had its status replaced. Tracking starts from zero with an
explicit start timestamp.

Legacy v1/v2 reports remain readable without a migration. Show retained evidence
and available state with an `analytics not initialized` notice. Old databases
have no tracked lifetime totals, not zero lifetime activity. V1 evidence without
provenance is explicitly unverified. After migration, retain the distinction
between tracked counters and available historical records; never add them
together as if they represented disjoint complete history.

## Read-only reporting and rendering

Use dedicated SQLite read-only connections and short read transactions. Do not
construct the normal writable `Store`, run migrations/maintenance, update
timestamps, or write analytical records during reporting. Adapt shared scoring
queries to a read-only interface so reports use the engine's score definitions.
SQLite may manage coordination sidecars for an active WAL database; the guarantee
is no logical state mutation, migration, checkpoint, or maintenance by stats.

Each Nebula is read from a consistent snapshot. The cross-Nebula report is not
a globally atomic snapshot; record its generation time and each snapshot time.
Handle a busy database with a short timeout and a per-root warning.

Bound rendering to 1,000 lesson versions per Nebula, 100 recent activity records
per Nebula, and an 8 MiB serialized report payload. Mark truncation explicitly
and omit detail beyond limits without presenting incomplete totals as complete.
Track full aggregates independently of capped detail queries. No unbounded
transcript reconstruction or filesystem indexing occurs.

Escape all dynamic HTML. Embed JSON safely so lesson text such as `</script>`
cannot end a script block. Render user data with text nodes, never HTML insertion.
The report fetches no remote resources. Write report files atomically with owner
read/write permissions and refuse destination collisions. They contain private
local paths and learned preferences, so documentation explains their contents
before users share them.

## Verification and delivery

Tests cover multiple/nested roots, ancestor discovery, symlink loops, skipped
directories, traversal limits, unavailable state, and the no-roots case.
Verify logical state remains unchanged during stats, including legacy schemas.

Counter tests exercise all metric definitions, feedback replay, repeated verdicts
with new receipts, exception reason changes, completed application replay,
transaction rollback, concurrent writers, migration, and retention. Confirm
feedback-only rows do not become execution statistics. Existing learning and
feedback regressions must continue to pass.

Renderer/CLI tests cover empty and partial reports, legacy coverage labels,
version/project aggregation, Unicode and hostile HTML/script text, payload caps,
output collisions, stdout size, and browser-opening failure. Manually open a
synthetic multi-Nebula report to verify layout, keyboard controls, search, and
filters. Label all synthetic evidence accurately.

Update the README, CLI help, and shared skill with stats usage and metric
definitions. Document exclusions, counters' tracking start, history limitations,
and the deferred time savings feature. Benchmark counter updates and reporting
separately; report measured overhead without promising zero cost.

Implement in atomic slices on `feat/analytics`, run the existing CI checks and
new regression tests, then push and open a PR against `main`. Attach the PR to
this chat. The description states actual verification and any live-host stages
not exercised. Creating a report does not establish new host compatibility.
