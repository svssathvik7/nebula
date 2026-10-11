# Nebula

**A self-learning memory layer for Claude Code and Codex.**

Nebula helps your coding agent learn from how you work: the decisions you make,
the corrections you give, and the workflows you repeat. It turns evidence from
your sessions and explicit feedback into persistent lessons, then makes those
lessons available across the related projects you select. Each lesson keeps its
context, rationale, and exceptions so the agent can assess when to suggest or
apply it.

Your disk is nearly full. You ask your agent to free up space in a project. It
finds 20 GB of build caches and a 40 GB dataset. You tell it:
**“Clear the caches. Keep the dataset—I need it when I'm offline.”**

Nebula can learn both the choice and the reason: prefer clearing files you can
regenerate, and preserve datasets you need offline. Once that lesson qualifies,
the next cleanup request in a selected project can start with those priorities,
without making you explain them again. If you later say a dataset is disposable,
that explicit instruction takes precedence.

Your agent performs the cleanup through its usual tools and permissions; Nebula
provides the remembered context.

**Current status:** the local engine and synthetic learning demo are implemented.
End-to-end use in both hosts is still being validated. See the
[validation results](examples/results/README.md) for completed and pending stages.

[Get started](#get-started) · [Everyday use](#everyday-use) ·
[How it works](#how-it-works) · [Documentation](#documentation) ·
[Contributing](contribution.md)

## What you can do

- **Build memory from your behavior and feedback** so lessons from earlier
  sessions can guide later work.
- **Share conventions and preferences** across a selected group of projects.
- **Keep the reasons and exceptions** alongside a lesson, rather than saving
  an unconditional instruction.
- **Inspect and correct memory** through explicit acceptance, rejection,
  exceptions, correction, withdrawal, and disabling.
- **Pause learning and application** without deleting what you have taught.

The agent handles interpretation and reasoning in your existing session.
Nebula's Python/SQLite engine stores evidence, lessons, and feedback locally.
It uses only the Python standard library and makes no model calls of its own.
There is no separate model, embeddings service, or background daemon.

## Get started

You need **Python 3.11 or newer**, Git, and Claude Code or Codex for the agent
workflow. The engine and demo can run without either host. Local testing has
used macOS; [CI](.github/workflows/ci.yml) runs the engine tests and demo on
Ubuntu with Python 3.11–3.14. Host-specific validation is recorded separately.

### 1. Clone the repository

```sh
git clone https://github.com/svssathvik7/nebula.git
cd nebula
NEBULA_ENGINE="$PWD/scripts/nebula.py"
```

No Python packages need to be installed. Keep this checkout at the same location
after setup: installed skills and hooks point back to it.

To try the learning loop before connecting your projects:

```sh
python3 examples/demo.py
```

The demo uses temporary projects and synthetic acceptance receipts. It walks
through a lesson, acceptance, application in a sibling project, an exception,
and withdrawal. It does not change your Claude or Codex settings.

### 2. Choose the projects that share memory

A **Nebula** is a parent directory plus the child projects you explicitly select.
For example, suppose these projects already exist:

```text
projects/
├── api/          ← selected
├── worker/       ← selected
└── unrelated/    ← not selected
```

Replace the path below with your existing parent directory. All selected
projects must be inside it; repeat `--project` to select more children.
Run these commands in the same shell as step 1.

```sh
NEBULA_ROOT="/absolute/path/to/projects"

python3 "$NEBULA_ENGINE" init "$NEBULA_ROOT" \
  --project "$NEBULA_ROOT/api" \
  --project "$NEBULA_ROOT/worker"
```

This creates local state in `projects/.nebula/`, initially OFF. Initialization
refuses to overwrite an existing Nebula; for one already set up, use `status`
and `on` instead.

### 3. Connect your coding agents and turn it on

Preview the project settings and skill links Nebula will add:

```sh
python3 "$NEBULA_ENGINE" install --root "$NEBULA_ROOT" \
  --project "$NEBULA_ROOT/api" \
  --project "$NEBULA_ROOT/worker" \
  --host claude --host codex --dry-run
```

Use only `--host claude` or `--host codex` if you use one host. After reviewing
the preview, run the installation without `--dry-run`, then enable Nebula:

```sh
python3 "$NEBULA_ENGINE" install --root "$NEBULA_ROOT" \
  --project "$NEBULA_ROOT/api" \
  --project "$NEBULA_ROOT/worker" \
  --host claude --host codex

python3 "$NEBULA_ENGINE" on --root "$NEBULA_ROOT"
python3 "$NEBULA_ENGINE" status --root "$NEBULA_ROOT"
```

To start with passive learning, use `on observe` instead of `on`. Bare `on`
selects full operation; see the mode commands under [everyday use](#everyday-use).

Installation adds registrations to the selected child projects and preserves
unrelated settings. It does not change user-wide configuration.

Start a **fresh Claude Code or Codex session inside a selected project**, review
project and hook trust through the host's native flow, and invoke the Nebula
skill (`/nebula` in Claude Code). Follow the
[host integration guide](skills/nebula/references/integration.md) if skills or
hooks are not discovered.

You can also ask your agent to do the setup. Before the skill is installed,
give it the absolute path to this checkout's `skills/nebula/SKILL.md` and name
the parent directory and child projects you want to include.

## Everyday use

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

In full mode, work normally in a selected project with the Nebula skill active. Teach
preferences explicitly and include the reason or an exception when it matters:

> When I ask you to free up space, start with build caches and files we can
> regenerate. Keep my datasets because I work offline, unless I explicitly
> tell you a particular dataset can go.

The agent can record a candidate lesson and suggest it when relevant. Once the
lesson qualifies, it can apply the preference in matching situations across
selected projects, subject to your current instructions and host permissions.
Source files alone do not teach Nebula your intent.

**Acceptance currently requires a terminal step.** Host prompt hooks cannot
reliably distinguish human submissions from generated turns, so saying “yes”
in chat alone does not confirm a lesson. When the agent presents a suggestion,
run the command it displays yourself, for example:

```sh
python3 "$NEBULA_ENGINE" confirm --root "$NEBULA_ROOT" \
  --suggestion SUGGESTION_ID --verdict accept
```

Replace `SUGGESTION_ID` with that suggestion's ID and type the requested
`NEBULA ACCEPT <suggestion-id>` acknowledgement in the interactive terminal.
The agent must not type or simulate it for you.

You can reject a suggestion, state an exception with a reason, correct or
withdraw a lesson, or disable its automatic application. A rejection or
exception blocks the current decision even if the lesson remains confident.
See the [shared skill](skills/nebula/SKILL.md#acceptance-and-correction) for the
feedback workflow.

Useful commands, using the variables from setup:

| Action | Command |
| --- | --- |
| Check activation, lessons, and recent events | `python3 "$NEBULA_ENGINE" status --root "$NEBULA_ROOT"` |
| Inspect a lesson and its evidence | `python3 "$NEBULA_ENGINE" inspect --root "$NEBULA_ROOT" --lesson LESSON_ID` |
| Pause capture and automatic application; keep memory | `python3 "$NEBULA_ENGINE" off --root "$NEBULA_ROOT"` |
| Resume full operation | `python3 "$NEBULA_ENGINE" on --root "$NEBULA_ROOT"` |
| Learn quietly without learned application | `python3 "$NEBULA_ENGINE" on observe --root "$NEBULA_ROOT"` |
| Check current mode with bounded output | `python3 "$NEBULA_ENGINE" status --summary --root "$NEBULA_ROOT"` |
| Run retention and storage maintenance | `python3 "$NEBULA_ENGINE" maintain --root "$NEBULA_ROOT"` |
| See available commands | `python3 "$NEBULA_ENGINE" --help` |

To remove a host's registration from a selected project:

```sh
python3 "$NEBULA_ENGINE" uninstall --root "$NEBULA_ROOT" \
  --project "$NEBULA_ROOT/api" --host claude
```

Repeat for other projects and hosts as needed. Uninstall removes unchanged
Nebula-owned registrations, leaves modified entries in place and reports them,
and keeps learned state.

## How it works

The learning loop is **capture → candidate lesson → suggestion → qualification
→ recall and application → feedback**. The shared skill guides the agent;
the engine stores records and checks whether a lesson is eligible to apply.
It never executes stored action text itself.

Lessons begin immature. They qualify through repeated, attributable human
choices and verified outcomes across sessions and projects, or through your
explicit acceptance of an identified suggestion. Automatic application also
requires confidence above 0.75, matching context and scope, and ordinary host
permission. A failed application suspends that lesson version until review.
Confidence measures preference consistency, not the probability that a choice
is correct.

Memory is bounded: raw evidence expires after 14 days, observational samples
after 90 days, and recall returns at most six summaries within 8 KiB. Compact
confirmations and decision blocks survive raw evidence expiry. Maintenance runs
during session interaction. Missing, corrupt, or full state withholds learned
application while ordinary host work continues.

Capture stores event metadata and digests rather than full prompts, command
arguments, or tool output. Lessons and feedback still contain project context
and human reasons, so inspect local state before sharing it. Nebula does not
import old transcripts or train a model on your history.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Shared agent skill](skills/nebula/SKILL.md) | Setup, recall, teaching, feedback, and application workflow |
| [Host integration](skills/nebula/references/integration.md) | Claude/Codex registration, trust, capture, and input boundaries |
| [Record formats](skills/nebula/references/records.md) | Record schemas, evidence, feedback, and application commands |
| [Validation results](examples/results/README.md) | Verified stages, pending live tests, and local benchmark evidence |
| [Example scenarios](examples/agent-prompts.json) | Prompts for exercising the learning workflow |
| [Design](docs/superpowers/specs/2026-10-06-nebula-phase-1-design.md) | Architecture, qualification rules, scoring, and storage limits |

## Contributing

Bug reports, clearer examples, documentation improvements, tests, and host
integration fixes are welcome. Read the [contributor guide](contribution.md)
for development setup, validation commands, and pull request guidance.
