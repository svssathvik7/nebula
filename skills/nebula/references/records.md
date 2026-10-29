# Utility records

All commands accept `--root PARENT`; stdin is JSON objects bounded to 64 KiB.
The utility returns JSON. `status --summary` returns only current `mode` and
`enabled` for automatic session/task/application checks; its output does not
grow with lesson count. Detailed `status` lists lessons/scores, health and
recent event IDs, session and episode identities. Captured metadata contains no full prompts or tool output.

`on [full|observe]` activates Nebula: bare `on` and `on full` select full
operation, even after observe; `on observe` selects persistent passive learning.
Unsupported activation modes are rejected without changing configuration.
`off` stops capture. The low-level `mode off|observe|full` selector remains an
alias. Detailed `status` and its health object expose `mode`; `enabled` remains
true for observe and full.
The existing `observe --host claude|codex` command ingests one hook payload from
stdin and does not change the mode. Legacy configurations with only `enabled`
resolve to full or off without rewriting on reads.

In observation mode, hooks capture bounded metadata and the skill can record
candidate lessons. No suggestions or new application claims are allowed,
including suggestion replays and already mature lessons. Explicit inspection
and user-initiated attribution/feedback remain available; they never override
the application gate. Finishing a claim made earlier remains bookkeeping.
Selecting full mode preserves candidates and their existing scores; unknown
prompt evidence still does not become verified human evidence.

`stats --root ANCESTOR [--output NEW_FILE.html] [--open]` returns a saved
HTML path and compact coverage/warnings, rather than full records on stdout.
It can read multiple independent roots beneath a plain folder, including OFF
roots. Schema 3 adds transactional analytics counters; schemas 1/2 remain
readable without migration or fabricated historic counts. See
[analytics semantics](analytics.md) for metrics, retention and filters.

`record-lesson --stdin`:
```json
{"lesson_id":"module-layout","version":1,"kind":"convention","trigger":"when adding a module","action":"Place it in src/modules.","context_tags":["module"],"exceptions":["generated code"],"scope_projects":[],"rationale":"Keep handwritten modules together.","rationale_source":"inferred","evidence_ids":["ev-actual-captured-id"],"disabled":false}
```
An empty scope means all selected child projects in this nebula. Explicit scope
contains canonical selected paths. Version is utility-managed; material changes
reset qualification. Kinds: preference, convention, decision-heuristic, workflow.

`suggest --stdin`:
```json
{"lesson_id":"module-layout","session_id":"actual-session","episode_id":"actual-episode","project":"/canonical/parent/child","context_digest":"concise-task-fingerprint"}
```
Read the resulting suggestion ID before asking. Confirm the exact version/scope.
`confirm --suggestion ID --verdict accept` requires the user’s terminal input.
The utility does not treat a CLI argument naming an event as a human receipt.

Feedback verdicts: accept, reject, exception, correct, withdraw, disable.
Acceptance records one positive choice episode with outcome unknown, confirms
the lesson and resets penalties; it does not establish observational coverage
or a suitable outcome. Multiple acknowledgements do not multiply that episode.
`reject` subtracts 0.02 from effective confidence, once per lesson
version/session/episode, without removing maturity or confirmation. Acceptance
of a new suggestion resets accumulated penalties. Penalties apply after the
acceptance floor and confidence stays within 0–1; repeated refusals can move it
to or below .75. Replaying feedback does not create another penalty.

For an explicit task exception, the user runs:
```sh
python3 <absolute-skill-path>/scripts/nebula.py confirm --root PARENT \
  --suggestion ID --verdict exception --reason "This is generated code."
```
The preview includes the reason; type the displayed `NEBULA EXCEPTION ID`
acknowledgement directly in the terminal. A verified `feedback` receipt must
bind the same reason. Exceptions add no penalty. Both rejection and exception
block application for that decision episode, even if confidence remains high.
They preserve existing observations rather than adding negative samples.
The decision block survives restarts, maintenance and later acceptance.

Each decision retains up to six recent feedback snapshots and six explicit
exception snapshots, so later rejections cannot erase its retained exceptions.
`inspect --lesson ID` includes the latest six feedback records, with human
reason, source references, context and episode identity. Recall includes up to
six recent explicit exception contexts within its existing byte budget. These
are task-specific evidence, not automatically generalized lesson exceptions.
Repeated exception feedback does not refund a penalty already incurred by a
rejection; a new explicit acceptance resets penalties. Correction and withdrawal
still remove confirmation; disable takes effect immediately.

`application claim --stdin`:
```json
{"lesson_id":"module-layout","version":1,"session_id":"actual-session","episode_id":"actual-episode","project":"/canonical/parent/child","context_match":true,"permissions_ok":true}
```
A result of false withholds application (qualification/scope/OFF/OBSERVE/duplicate or
an explicit rejection/exception for that episode).
`application finish --stdin`:
```json
{"lesson_id":"module-layout","version":1,"session_id":"actual-session","episode_id":"actual-episode","outcome":"suitable","source_event_ids":["ev-captured-tool-result"]}
```
Outcomes: suitable, failed, unknown. Finish requires captured evidence from the
same session/project and a prior claim; records never execute action strings.

`record-sample --stdin` has lesson_id/version/episode_id/session_id/project,
source_event_id, verdict (positive/negative), outcome and UTC timestamp.
Only attributable human choices count. Suitable outcomes need a verified receipt.
When host prompts are unknown-origin, the user can attribute a captured prompt:
`attest --event EVENT --lesson ID --verdict positive --outcome suitable`.
It displays the candidate and event identity and requires an exact terminal
acknowledgement. The user is responsible for recognizing the referenced choice;
raw prompt text is not stored. Repeated source episodes do not increase counts.

After an application failure: `review --lesson ID --version 1 --event EVENT`.
The user supplies direct terminal acknowledgement; an agent cannot clear it via
an unbound assertion.
