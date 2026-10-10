# Nebula: phase 1 design for review

Status: design approved by the user on 2026-10-07; phase-1 utility and shared skill implemented. Full live Claude/Codex acceptance validation remains pending host login/trust and direct user input; see examples/results/README.md.
Updated 2026-10-07 to reflect the user's scope correction: disk cleanup is an
illustrative scenario, not the product scope or a required subsystem.

## Purpose and scope

Build a personal learning layer for Claude Code and Codex. A user enables a
nebula at a parent folder containing related projects. The agent learns from
attributable human choices in sessions across those projects, remembers the
context and reasoning behind the choices, and uses relevant lessons in later
situations. The intention is to increasingly reflect how the user works and
makes decisions within that nebula.

Phase 1 delivers the general observation, lesson extraction, memory, maturity,
confidence, suggestion, application, and correction loop. Learned behaviors
can include preferences, project conventions, decision heuristics, and
multi-step workflows. There is no predefined list of three action types.
Disk cleanup is one possible behavior the user supplied to explain this loop;
it does not require disk monitoring, cleanup executors, resource thresholds,
Docker integration, Rust integration, or Trash integration in phase 1.

User requirements:

- Enable learning from the parent folder of related projects.
- Share relevant learning across its selected descendant projects.
- Default every new behavior to mature=false.
- Require enough independent evidence before observational maturity.
- Accepting a suggestion immediately marks its specific behavior mature and
  raises its confidence above 0.75 through explicit user confirmation.
- Apply mature behaviors automatically when confidence is strictly greater
  than 0.75 and the situation matches; suggest otherwise.
- Minimize token use, execution overhead, and storage consumption.
- Support both Claude Code and Codex.

Confirmed observation source: Claude Code and Codex sessions only. Ordinary
terminal activity and manual actions outside those sessions are not captured.
The design uses active agent sessions for learning and application in phase 1.
Operating while both agents are closed is deferred. It does not train model
weights or claim exponential improvement. Proposed numerical defaults below
remain implementation choices for review.

## Architecture choice

Recommended: a shared Nebula skill, host-specific event hooks, and a small local
evidence and scoring utility. Claude or Codex remains the reasoning agent.

The skill directs the active agent to interpret experience, extract candidate
lessons, match lessons to the current situation, explain suggestions, and
apply qualifying behavior through the host's existing tools. It draws on the
current session context rather than starting a separate background model.

The utility stores structured records, deduplicates samples, calculates
maturity and confidence, retrieves bounded relevant candidates, and records
feedback. Python's standard library and SQLite are proposed implementation
choices for this bookkeeping; the utility is not a separate AI agent and does
not reason, invent actions, or execute arbitrary learned commands.

A skill with only Markdown memory would be simpler initially but leave
counting, deduplication, and scoring to the model. A standalone model daemon
would enable operation outside sessions but add scheduling and continuing
resource and token costs. Neither is needed for the proposed active-session
architecture.

Components are the shared skill, two observation adapters, evidence store,
lesson store, scoring/retrieval utility, and CLI/lifecycle support. The boundary
is explicit: the agent interprets and acts; the utility handles bookkeeping.

## Agent integration and discovery

Both hosts document command hooks for UserPromptSubmit, PreToolUse,
PostToolUse, and session lifecycle events. Versions inspected on 2026-10-06
were Claude Code 2.1.285 and Codex CLI 0.160.0; the latter reported hooks
enabled. These are historical inspection results, not a guarantee of working
Nebula integration. Actual event payload capture must be tested on both hosts.

Prompt events and explicit feedback establish human intent. Tool events supply
execution evidence, not proof of human preference by themselves. Adapters
emit the same bounded schema and identify human, assistant, subagent, and
system-generated events where the host provides that distinction. Unknown
provenance cannot mature a lesson. The skill associates interpretations with
captured event IDs; model assertions alone do not create human acceptance.

Hook payloads are the primary interface. Transcript parsing is not required
for the first release because Codex documents its transcript format as
unstable. A small amount of structured learning is extracted during existing
agent turns; hooks do not invoke a model for every tool call.

Agent discovery can stop at a child repository's root. Setup must make the
shared skill and relevant hooks discoverable from every selected child
workspace. It preserves existing configuration and removes only Nebula-owned
entries on uninstall. Links, copies, or a supported installation mechanism are
selected and verified in the implementation plan. The user enables a nebula
once from its parent folder; setup handles registration for selected children.

Official interface references:

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/skills
- https://developers.openai.com/codex/hooks/
- https://developers.openai.com/codex/skills/

## Nebula identity and lifecycle

- Initialization records the canonical parent root and selected child projects.
  Discovery avoids indexing entire source trees or importing old transcripts.
- Configuration, structured evidence, and lessons live in a private .nebula
  directory at the parent root, excluded from version control.
- ON enables session capture, lesson retrieval, and the learning workflow.
  OFF disables capture and automatic lesson application while retaining memory.
- Status reports participating projects, lessons, evidence coverage, maturity,
  confidence, pending suggestions, and storage usage.
- Concurrent Claude and Codex sessions share the store using transactional
  writes and idempotent event IDs. Session restarts retain learning.
- Missing or corrupt state disables automatic learned application and reports
  a diagnostic without blocking ordinary agent work.
- Nested nebulas use the nearest registered ancestor. An event belongs to one
  nebula; unrelated nebulas do not implicitly share evidence or lessons.

Proposed CLI operations: init, on, off, status, observe, record-lesson, recall,
feedback, and inspect. Exact command syntax belongs in the implementation plan.
These are supporting operations invoked through the skill and adapters.

## Evidence and lesson extraction

Folders establish the nebula boundary and provide project context; their
contents alone cannot establish why the user made a choice. Phase 1 learns
from new session evidence, explicit teaching, and corrections. Historical
session import is deferred.

Evidence includes an event ID, time, nebula/project/session identity, decision
episode, source role, observed situation, selected behavior, and outcome when
known. Record human-provided reasoning when available; inferred reasoning is
marked as inferred and cannot be presented as something the user said.

At a completed decision episode or an explicit teaching/correction moment, the
active agent can extract a small structured lesson. The lesson contains:

- ID and version;
- kind: preference, convention, decision heuristic, or workflow;
- trigger conditions and relevant context;
- action or procedure, including its intended result;
- exceptions and applicability scope;
- human-stated rationale or explicitly labeled inferred rationale;
- supporting and contradicting evidence IDs;
- observational maturity/confidence and effective maturity/confidence;
- explicit confirmation state, if any.

The agent merges equivalent lessons and keeps conflicting contexts distinct.
A workflow and its individual steps do not automatically share maturity.
Changing a lesson's trigger, action, or target scope materially creates a new
version that must qualify again; confirmation is not silently transferred.

A positive sample requires an attributable human choice or explicit acceptance.
A negative sample requires an explicit correction, withdrawal, disable, or
attributed negative choice in comparable context. A suggestion rejection is
task-specific feedback with a separate confidence penalty; an explicit exception
adds no penalty. Neither replaces existing observational samples. Silence and
successful agent tool execution do not imply preference.
Autonomous applications cannot create positive preference samples. Outcomes
are separate evidence: failures or ambiguous results do not become successes.

Store concise structured metadata and source references, not whole transcripts,
source trees, or full tool output. Inspecting a lesson shows what was observed,
what was inferred, and what the user explicitly confirmed.

## Maturity and confidence

New lessons start with mature=false. Two paths can make a lesson mature:
repeated independent observation or explicit acceptance of a suggestion.

Proposed observational maturity rule:

- At least five independent decision episodes with attributable human choices.
- Evidence spans at least three sessions and two selected child projects.
- At least three supporting applications have verified suitable outcomes,
  through objective checks where available or explicit human feedback.
- Recompute this maturity as evidence changes or expires.

Retries and multiple tool calls within one decision episode do not create
independent samples. Suggestion acceptance and its resulting application
count as one sample. Evidence from one project is not duplicated across all
projects merely because the behavior has nebula-wide applicability.

Proposed observational confidence formula:

    confidence = (positive + 1) / (positive + negative + 2)

This is a smoothed preference-consistency score, not a calibrated probability
of correctness or of matching every future situation. Five positives and no
negatives yield approximately 0.857. Current applicability must be assessed
separately; high historical confidence alone does not establish a context match.

User-confirmed maturity:

- Explicit acceptance of an identified suggestion immediately sets mature=true,
  bypassing the observational sample requirements.
- Effective confidence becomes max(observational confidence, 0.80) while that
  scoped confirmation is active, minus accumulated rejection penalties. Each
  independently rejected decision subtracts 0.02 after the floor, clamped to
  0–1. Acceptance resets the penalties, implementing confidence strictly greater
  than 0.75 immediately after acceptance. Duplicate receipts, context fingerprints,
  or suggestions within the same lesson version/session/episode do not add penalties.
- Persist suggestion ID, lesson version, accepted context/scope, source event,
  session, time, and human initiator. Assistant text or system continuations
  cannot create this confirmation.
- Confirmation survives session restarts and raw-evidence expiry. Retain its
  compact record separately from expiring observations.
- Later rejection retains confirmation and maturity but lowers effective confidence.
  An explicit task exception retains confidence and records the user's reason
  and context, without automatically generalizing it into a lesson-wide rule.
  Correction or withdrawal revokes confirmation and its floor; recompute
  observational maturity/confidence. An explicit disable takes effect immediately.
- Rejection/exception blocks that decision episode even when effective confidence
  remains above 0.75. The block survives later acceptance and retention. A later
  exception does not refund a prior rejection penalty; acceptance of a new
  suggestion resets penalties. Penalty count is capped at 50 (a deduction of 1.0).

## Retrieval and application

At session start and meaningful task changes, retrieve a compact shortlist of
lessons relevant to the current project and task. Proposed default: up to six
lesson summaries, ranked by scope, trigger relevance, and confidence. Fetch
full evidence only when explaining, resolving a conflict, or inspecting.

The active agent compares retrieved triggers, exceptions, and scope against
the current situation. It does not treat every retrieved lesson as applicable.
If the match is ambiguous, it asks through a suggestion rather than acting on
the historical confidence score alone.

Decision rules:

1. No relevant lesson: perform ordinary agent work and collect attributable
   evidence when a decision episode provides it.
2. Applicable lesson that is immature or confidence <= 0.75: suggest the
   behavior and explain its supporting learning.
3. Explicit suggestion acceptance: persist user-confirmed maturity/confidence,
   then recheck the current situation before applying the behavior.
4. Applicable mature lesson with confidence > 0.75: apply it without an
   additional Nebula preference-confirmation step, through the host's tools
   within the current task, configured scope, and existing permissions.
5. Conflict, uncertain applicability, stale targets, missing permission, or
   blocked tool: explain the specific issue and suggest the next step.

Learned procedures describe intent and steps. The agent resolves current files,
parameters, and tool calls when applying them; the utility never blindly
replays a recorded shell command. Existing host permissions and higher-priority
user/project instructions continue to apply. Learning does not broaden them.

Track application by lesson version, session, and decision episode so hook
reentry or repeated retrieval does not cause duplicate actions. After an
application, record outcomes and any correction. A failure suspends automatic
application of that lesson until reviewed, without pretending it disproves
the user's preference by itself.

## Suggestions and feedback

A suggestion states the current situation, proposed behavior and scope, relevant
reasoning, sample coverage, maturity, confidence, and uncertainty. It says that
acceptance confirms the specific lesson for future matching situations.

Users can accept, reject, declare an explicit exception, correct, withdraw,
inspect, or disable. Acceptance immediately sets mature=true and confidence to
at least 0.80. Rejection adds a 0.02 penalty; exception requires a human reason
of 1–512 characters and adds no penalty. Correction/withdrawal revoke prior
confirmation as described above. An ambiguous response is not assigned to an
arbitrary pending suggestion, and rejection alone does not imply an exception.

Bound rejection/exception metadata is retained with the decision block, including
source references, context and human reason. Inspect returns the latest six
feedback records; each decision retains six feedback and six exception snapshots
separately, so later refusals do not displace its retained exceptions. Each
snapshot owns its project identity. Recall can include six recent exception contexts within its
existing byte budget. An exception that should become a general lesson boundary
must be taught explicitly through a material lesson update, creating a new version.

Suggestions are delivered in the active Claude/Codex conversation. Persist an
unresolved suggestion for later recall, but do not repeatedly ask within the
same episode without a material change. No always-on notifications or operation
outside agent sessions are required for phase 1.

## Token, speed, and storage budgets

- No model calls for persistence, deduplication, scoring, or basic filtering.
- Interpretation and contextual application use the active host model. These
  consume some tokens; minimize them through concise structured lessons and
  extraction at decision boundaries instead of every tool event.
- No separate model daemon, idle polling, or repeated full-project scans.
- Adapter capture has bounded payloads and an execution deadline; failure must
  not interrupt the user's ordinary task.
- Retain at most 10,000 raw metadata events with a 14-day window. Deduplicated
  observational decision evidence has a proposed 90-day window. Expired samples
  leave observational maturity/confidence; active confirmations persist.
- Bound lesson bodies and diagnostics. Proposed total storage budget, including
  SQLite sidecars: 32 MiB soft limit and 64 MiB hard cap. When the hard cap is
  reached, pause capture and learned automatic application and report it.
- Proposed p95 capture target on this machine: <= 50 ms, to be measured.
- No persistent Nebula process is required while the host agents are closed.

Zero overhead cannot be promised. Report capture latency, retrieval latency,
storage size, and added model-context size during verification. The user's
speed and space goals are addressed with measured bounds.

## Verification and acceptance criteria

Meaningful checks cover:

- shared learning across sibling projects and isolation across nebulas;
- compatible Claude and Codex event normalization and skill discovery;
- independent samples, source provenance, and no autonomous self-reinforcement;
- extraction of lessons with context, rationale, scope, and evidence references;
- preserving different behaviors for different situations rather than merging
  superficially similar observations;
- observational maturity, confidence exactly 0.75, expiry, and negative feedback;
- immediate mature=true and confidence >= 0.80 on a single explicit acceptance;
- scoped confirmation persistence, revocation, and lesson-version changes;
- rejection of assistant-originated, ambiguous, replayed, or mismatched approvals;
- retrieving relevant lessons without applying unrelated or conflicting ones;
- suggestions for immature/uncertain behaviors and automatic application of
  mature qualifying behaviors within existing host permissions;
- OFF behavior, concurrent writes, restart recovery, and duplicate prevention;
- bounded storage and measured capture/retrieval/context overhead.

Use disposable projects and harmless task workflows for integration checks.
A test can show that a learned convention or verification workflow transfers
between related projects; no real disk cleanup is required. Deterministic
utility tests use fixtures. Agent-based checks report the model, input, and
observed output; passing fixtures alone do not prove general reasoning quality.

Phase 1 is usable when a nebula can be enabled from its parent, both host
integrations contribute evidence, a contextual lesson is extracted and recalled
across child projects, immature behavior is suggested, acceptance immediately
promotes it, and a later matching task applies it automatically with correction
and revocation working. Synthetic demonstrations are labeled as such rather
than presented as genuine user history.

## Deferred scope

Operation while agent sessions are closed, arbitrary computer/terminal activity
capture, historical transcript mining, model-weight training, cross-nebula
transfer, automatic rewriting of the skill itself, standalone background
models, cloud services, and dashboards are deferred. New learned behavior
categories do not require a dedicated executor for each example; application
uses the existing agent tool interfaces.

## Review handoff

Confirmed: Claude and Codex sessions are the observation source; accepting a
suggestion immediately promotes that lesson; disk cleanup is only an example.
This revision also incorporates the earlier architecture correction: the host
agent reasons and acts, while the local utility handles memory and scoring.
The user approved the revised design, including the proposed sample thresholds,
active-session scope, and resource budgets. Proceed to the implementation plan.
This directory is not currently a Git
repository; the design is saved without initializing or committing one.
