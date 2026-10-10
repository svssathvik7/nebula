# Contributing to Nebula

Contributions are welcome: bug reports, documentation, tests, host integration
fixes, and improvements to the learning workflow. You do not need a large feature
to get started. A reproducible bug or a clearer example is useful work.

## Get started

Fork [svssathvik7/nebula](https://github.com/svssathvik7/nebula) on GitHub, clone
your fork, and create a branch for your change:

```sh
git clone https://github.com/YOUR_USERNAME/nebula.git
cd nebula
git switch -c fix/describe-your-change
```

Use Python 3.11 or newer. The engine and test suite use only the Python standard
library; there are no Python dependencies to install. Run commands below from
the repository root. A virtual environment is optional:

```sh
python3 -m venv .venv
source .venv/bin/activate
```

If you create a virtual environment inside the checkout, keep it out of your
commit. You can add `.venv/` to your local `.git/info/exclude`.

## Understand the project

Start with the [README](README.md) and the [shared skill](skills/nebula/SKILL.md).
Claude Code or Codex interprets a task, proposes lessons, and applies appropriate
preferences. The Python utility stores evidence, computes scores, and guards
applications. It makes no model calls and does not execute learned action text.

| Location | Responsibility |
| --- | --- |
| `skills/nebula/` | Shared agent instructions, record formats, and skill launchers |
| `nebula/cli.py`, `scripts/` | CLI commands, hook entry point, and benchmark |
| `nebula/adapters/`, `nebula/capture.py` | Host payload normalization and bounded evidence capture |
| `nebula/lessons.py`, `nebula/scoring.py`, `nebula/feedback.py` | Lesson versions, maturity, confidence, and feedback |
| `nebula/recall.py`, `nebula/application.py` | Retrieval and application eligibility |
| `nebula/store.py`, `nebula/maintenance.py` | SQLite persistence, retention, and storage limits |
| `nebula/roots.py`, `nebula/lifecycle.py`, `nebula/install.py` | Project scope, activation, and host registration |
| `tests/`, `examples/` | Regression tests, synthetic demo, and validation evidence |

For changes to learning or feedback, also read the
[design](docs/superpowers/specs/2026-10-06-nebula-phase-1-design.md) and
[record formats](skills/nebula/references/records.md).

## Choose and report a change

Check existing [issues](https://github.com/svssathvik7/nebula/issues) and
[pull requests](https://github.com/svssathvik7/nebula/pulls) before starting.
For a substantial change to scoring, storage, host support, or the architecture,
open an issue describing the problem and proposed behavior so the tradeoffs can
be discussed early. Small fixes and documentation improvements can go directly
to a pull request.

A useful bug report includes:

- Expected behavior and actual behavior.
- Minimal steps to reproduce, including the failing command when relevant.
- Operating system, Python version, Nebula commit, and Claude/Codex version for
  host integration problems.
- Relevant error output and whether the failure occurs in a fresh disposable
  Nebula.

Remove secrets and private project data from reports. Share minimal sanitized
examples instead of full transcripts, databases, or personal host settings.

## Validate your work

For a code change, start with the relevant test module, for example:

```sh
python3 -m unittest tests.test_feedback_penalties -v
```

Add a regression test that reproduces a bug before fixing it. Tests should check
observable behavior, including failure cases where relevant. Use temporary
directories and platform-neutral paths; tests must not depend on your home
directory or modify your real host configuration.

Before submitting a code change, run the same commands as CI:

```sh
python3 -m compileall -q nebula scripts examples tests
python3 -m unittest discover -s tests -v
python3 examples/demo.py
git diff --check
```

[CI](.github/workflows/ci.yml) runs compilation, the test suite, and the synthetic
demo on Ubuntu 24.04 with Python 3.11, 3.12, 3.13, and 3.14. It runs for pull
requests and pushes to `main`. It does not currently enforce linting, coverage,
or performance thresholds. For documentation-only changes, check the affected
commands, links, and examples; new unit tests are usually unnecessary.

For changes affecting latency or storage, measure the relevant workload:

```sh
python3 scripts/benchmark.py --events 1000 --lessons 100 --runs 100
```

Report your environment and measurements. A benchmark on one machine does not
establish performance on every supported environment.

## Test Claude and Codex integration

Engine tests and the synthetic demo do not establish live host compatibility.
Changes to hooks, adapters, installation, or skill behavior also need testing
in actual host sessions. Read the
[integration boundaries](skills/nebula/references/integration.md) and
[recorded live validation stages](examples/results/README.md).

Use disposable projects **inside** a separate parent directory. All selected
children must be descendants of the Nebula root. From the repository root, this
example prepares an isolated test parent and previews registration:

```sh
NEBULA_ENGINE="$PWD/scripts/nebula.py"
NEBULA_TEST_ROOT="$(mktemp -d)"
mkdir -p "$NEBULA_TEST_ROOT/project-a" "$NEBULA_TEST_ROOT/project-b"

python3 "$NEBULA_ENGINE" init "$NEBULA_TEST_ROOT" \
  --project "$NEBULA_TEST_ROOT/project-a" \
  --project "$NEBULA_TEST_ROOT/project-b"

python3 "$NEBULA_ENGINE" install --root "$NEBULA_TEST_ROOT" \
  --project "$NEBULA_TEST_ROOT/project-a" \
  --project "$NEBULA_TEST_ROOT/project-b" \
  --host claude --host codex --dry-run
```

After reviewing the preview, rerun `install` without `--dry-run`, enable it with
`on --root "$NEBULA_TEST_ROOT"`, and start fresh host sessions in the selected
children. Keep the checkout available: installed skill links and hook commands
refer to it. Review trust through each host's native flow.

Verify skill discovery, actual event capture, candidate creation, suggestion,
acceptance, and transfer to a sibling project. Also check a different context,
rejection or exception, withdrawal, OFF behavior, and uninstall preservation of
unrelated settings. The [example scenarios](examples/agent-prompts.json) provide
starting points.

Current prompt hooks classify submissions as unknown-origin. Chat acceptance
alone cannot promote a lesson. A human must personally run the displayed
interactive `confirm` command and type its exact acknowledgement. Agents must
not pipe, automate, or simulate this input. Apply the same boundary to `attest`
and `review`. Label synthetic receipts and programmatic sessions accurately,
and report any live stages you could not test.

## Keep these guarantees intact

- Preserve the distinction between observation, inference, and confirmation.
  Repeated retries and an agent's own successful action must not inflate human
  preference evidence.
- Respect selected project scope, lesson versions, exceptions, refusal,
  disabled state, and ordinary host permissions.
- Keep raw evidence, storage, and recall bounded. Avoid storing full prompts,
  command arguments, tool output, or secrets.
- Preserve unrelated host configuration. Uninstall removes only unchanged
  Nebula-owned registrations.
- Missing, corrupt, or full state must withhold learned application while
  ordinary host work can continue.

Document intentional changes to these guarantees and include tests explaining
their consequences. Avoid adding runtime dependencies or extra model calls
without explaining the need, cost, and compatibility impact.

## Submit a pull request

Keep each pull request focused on one problem. Use small, coherent commits and
stage only intended files. Exclude `.nebula/` state, local environments, host
settings, credentials, and session artifacts.

In the pull request description, explain:

- The problem and resulting behavior, with a before/after example if useful.
- The approach and any compatibility or data migration implications.
- The commands you ran and their results.
- For host changes, which host versions and live stages you tested, including
  limitations.

Update documentation when commands, behavior, or supported workflows change.
Wait for CI and address review feedback with follow-up commits. AI-assisted
contributions are welcome; contributors remain responsible for understanding
the change, checking generated code, and reporting verification honestly.
