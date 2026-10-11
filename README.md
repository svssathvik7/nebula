# Nebula phase 1

Nebula helps Claude Code and Codex reuse your preferences across a selected group
of related projects. A shared skill handles interpretation and current task
reasoning; a local Python/SQLite utility stores compact evidence, lessons and
feedback. No separate model, embeddings, transcript importer or idle daemon runs.
It learns conventions, decision heuristics, preferences and workflows. Disk
cleanup is an example you could teach later, not a built-in feature.

**Status:** the utility and synthetic learning loop are implemented. Actual host
integration and manual acceptance are separate validation gates; see
[results](examples/results/README.md) for verified stages and limitations. This
is not a claim of exponential improvement or a trained clone of your judgment.

Requires Python 3.11+, standard library only. Tested locally on macOS with Python
3.14.5. Runtime paths and skill registration use symlinks; keep this checkout
available after installation. Configuration lives in `.nebula/` at the canonical
parent. You choose the child projects; source files alone do not teach intent.

```sh
NEBULA_ENGINE=/Users/svssathvik/Desktop/sathvik/my-projects/SLA/scripts/nebula.py
python3 "$NEBULA_ENGINE" init /path/to/folder_bitcoin \
  --project /path/to/folder_bitcoin/folder_1 \
  --project /path/to/folder_bitcoin/folder_2
python3 "$NEBULA_ENGINE" install --root /path/to/folder_bitcoin \
  --project /path/to/folder_bitcoin/folder_1 \
  --project /path/to/folder_bitcoin/folder_2 \
  --host claude --host codex --dry-run
```

Review the changes, run the same installation command without `--dry-run`, then
`on observe --root /path/to/folder_bitcoin` for passive learning or
`on --root /path/to/folder_bitcoin` for full operation. Start a fresh Claude/Codex session in a child,
review the host’s native hook trust, and invoke its Nebula skill. The skill
coordinates recall, contextual assessment, suggestions, learning and outcomes.
For first activation from a parent before the skill is installed, ask your agent
to read the shared `skills/nebula/SKILL.md` by absolute path and enable Nebula for
the selected children; the CLI sequence above is the equivalent manual setup.
The installation only edits selected child settings; it preserves user settings
and adds skill links at child roots to survive Git discovery boundaries.

### Learn quietly before enabling learned behavior

Invoke `/nebula on observe` in an installed parent or selected child to record
observations and candidate lessons while you continue ordinary work. Nebula
does not propose suggestions, ask for confirmation or apply learned behavior
in this mode, including mature lessons. Its engine refuses suggestions and
new application claims. Use `/nebula status` and `/nebula inspect` to review
what it has learned; the agent maps these to the utility's `status` and
`inspect --lesson ID` commands. Switch to `/nebula on` when ready for full mode.
This preserves memory and does not automatically qualify candidate lessons.

| Skill request | Utility command | Behavior |
| --- | --- | --- |
| `/nebula on` | `on --root PARENT` | Select full mode; recall, suggest and apply qualifying lessons |
| `/nebula on full` | `on full --root PARENT` | Explicitly select full mode |
| `/nebula on observe` | `on observe --root PARENT` | Capture evidence and record candidates quietly |
| `/nebula off` | `off --root PARENT` | Stop capture and learned application; retain memory |

Bare `on` always selects full, including after observation mode. Unsupported
mode values are rejected without changing configuration. The low-level
`mode off|observe|full` command remains an alias. For automatic mode checks,
the skill uses `status --summary`, which returns only current `mode` and
`enabled` regardless of lesson count. Detailed `status` remains available
when you ask to inspect the lesson catalog, health and recent evidence.

Observation writes only Nebula's learning state through its existing session
workflow; it adds no daemon, polling or model calls. Hooks store metadata and
digests, not full transcripts. Unknown-origin prompts can support candidates
but cannot count toward observational maturity without explicit attribution.
This mode limits Nebula's learned behavior; your agent still performs the
ordinary work you request. It cannot cancel a host action already running.
Update both runtime and skill before using it; older runtimes understand only
`enabled` and do not enforce observation mode. The CLI's existing
`observe --host HOST` command remains event ingestion, not mode selection.

`off --root PARENT` retains memory and stops capture/automatic application.
`status`, `inspect --lesson ID`, `maintain`, and `uninstall --project CHILD --host
HOST` are available through the same launcher. Uninstall leaves edited managed
entries in place and reports them. It does not erase learned state.

Lessons start immature. Observational maturity requires five independent human
choice episodes, three sessions, two projects, and three verified suitable
outcomes. Confidence is `(positives + 1)/(positives + negatives + 2)`; this is a
consistency score, not a calibrated probability of correctness. Repeated tool
calls and the agent’s own successful execution do not add preference samples.

Accepting an identified suggestion immediately sets effective maturity and a
confidence floor of .80 for that version and scope and resets rejection penalties.
A rejection preserves maturity/confirmation and subtracts .02 from effective
confidence once per decision episode, after the floor. An explicit
`exception --reason "..."` adds no penalty and records the human reason/context.
Both block the current decision; confidence above .75 does not override refusal.
Correction or withdrawal removes confirmation; disable stops automatic application.
Material changes require qualification again. Rejection penalties and decision
blocks survive raw expiry; a new acceptance resets penalties but not old blocks.
Automatic application needs confidence strictly above .75, maturity, a current
context match, scope and ordinary host permission. Failures suspend the version
until explicit user review. The utility never executes learned action strings.

**Current acceptance limitation:** host prompt hooks do not reliably distinguish
human submissions from generated turns. Prompt evidence remains unknown-origin.
Use the displayed `confirm --suggestion ID --verdict accept` command yourself in
an interactive terminal and type `NEBULA ACCEPT ID`. The agent must not simulate
that input. `attest` attributes a captured human choice/outcome for observational
learning; `review` reviews a failed application. These are operational user input
boundaries, not cryptographic authentication against malicious local code.
This fallback adds user interaction; ordinary chat acceptance alone currently
does not promote a lesson.

Raw evidence expires after 14 days and is capped at 10,000 events; observational
samples expire after 90 days. Compact confirmations survive raw expiry. Recall
returns at most six summaries and 8 KiB. Storage soft/hard budgets are 32/64 MiB,
including sidecars. Capture and automatic application stop before consuming the
feedback reserve; bounded essential feedback remains available within that reserve.
Active confirmation controls survive ordinary suggestion expiry. Maintenance runs at session interaction, not idle polling.
Compact rejection/exception decision blocks also persist; `inspect` shows recent
feedback and recall includes recent explicit exception contexts within its byte budget.
Schema v2 retains compact sample attribution for inspection after raw expiry.
A v1 upgrade preserves old rows but withholds unverified observational evidence;
it reconstructs confirmation only from matching captured receipt/suggestion.
Missing/corrupt/full state withholds learned application and leaves ordinary host
work running.

Local benchmark: 1,000 events, 100 lessons, 100 hook subprocess runs including
Python cold start: p50 **38.429 ms**, p95 **39.452 ms** (50 ms target met); in-process
insertion p95 .142 ms; recall p95 1.900 ms; state 684,376 bytes; shortlist 2,577
UTF-8 bytes. These are this machine’s measurements, not zero overhead or an exact
token count. Hook utilities make no model calls; the skill uses context in existing
agent turns. Validate overhead on your actual workload.

```sh
python3 -m unittest discover -s tests -v
python3 examples/demo.py
python3 scripts/benchmark.py --events 1000 --lessons 100 --runs 100
```

The demo uses temporary sibling projects and **synthetic receipts**. It exercises
candidate → suggestion → acceptance → sibling application → exception →
withdrawal and verifies a harmless artifact, without changing host settings.

See the [approved design](docs/superpowers/specs/2026-10-06-nebula-phase-1-design.md),
[implementation plan](docs/superpowers/plans/2026-10-07-nebula-phase-1.md),
[shared skill](skills/nebula/SKILL.md), [records](skills/nebula/references/records.md)
and [integration boundaries](skills/nebula/references/integration.md).

Interested in contributing? Read the [contributor guide](contribution.md) for
setup, tests, live host validation, bug reports, and pull request guidance.
