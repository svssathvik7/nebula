# Validation results

Run date: 2026-10-07. [Benchmark](benchmark.json) includes full Python subprocess
startup, 1,000 events, 100 lessons and 100 runs. [Live stage records](live.json)
are sanitized summaries, not session exports.

| Gate | Observed result |
|---|---|
| Utility tests | 59 tests pass after the independent review fix pass |
| Synthetic general learning loop | Passed; candidate → accept → .80 → sibling artifact → different context withheld → withdraw |
| Skill behavioral baseline/guided scenario | Without skill, actual protocol unknown; with skill, correct commands, provenance and review steps |
| Claude 2.1.285 project hook registration | Actual SessionStart/UserPromptSubmit captured from print-mode test; programmatic origin system |
| Claude reasoning/tool workflow | Pending: outside-sandbox run reported expired OAuth session unable to refresh |
| Codex 0.160.0 skill discovery and CLI | Actual ephemeral agent read shared skill and ran status/recall; withheld unrelated Claude evidence |
| Codex actual project hook capture | Pending: no Codex hook event captured; native project/hook trust requires user review |
| Direct user acceptance on both hosts | Pending; no synthetic or simulated terminal acknowledgement passed off as human evidence |
| Host sibling application, exception, correction and OFF | Pending live tests after the trust/login/input stages; utility fixtures already cover them |

Both-host compatibility is **not yet fully validated**. The prepared, local test
nebula is at:
`/Users/svssathvik/Desktop/sathvik/my-projects/SLA/.superpowers/sdd/2026-10-07-nebula-phase-1/live/nebula`.
It contains only disposable Claude/Codex child projects and registered skill
links/hooks. No user-wide configuration or trust records were changed by setup.

To finish live validation yourself:

1. From `claude-project`, launch `claude`, run `/login` if required, and invoke
   `/nebula`. Review project trust through Claude’s normal flow.
2. From `codex-project`, launch `codex`, review project trust and open `/hooks` to
   review the concrete Nebula command definitions. Start a fresh session after
   trusting hooks and invoke the Nebula skill.
3. Use the tooling/candidate scenario in [agent prompts](../agent-prompts.json).
   Check actual stored event IDs for that host/session, the candidate lesson,
   and its pending suggestion. A verbal claim alone does not pass this gate.
4. Run the displayed `confirm --root PARENT --suggestion ID --verdict accept`
   command yourself and type the exact `NEBULA ACCEPT ID` acknowledgement.
   Inspect that version: mature=true, confidence >= .80, one preference sample.
5. Request a matching handwritten module in the sibling project. Inspect the
   application claim, actual artifact and outcome. Then request generated code
   to exercise the exception, withdraw the bound suggestion, and turn OFF.
   Verify a later session does not add capture or apply learned behavior.

The local terminal fallback is explicit human interaction, not authentication
against hostile local code. Agents must never drive those acknowledgements.
Project/hook trust is host-owned and must not be fabricated or bypassed.
