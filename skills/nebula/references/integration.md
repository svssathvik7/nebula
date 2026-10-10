# Integration status and boundaries

Claude Code project skills: `.claude/skills/nebula`; hooks:
`.claude/settings.local.json`. Codex project skills: `.agents/skills/nebula`;
hooks: `.codex/hooks.json` beside `.codex/config.toml`. Setup links each selected
child separately so nested Git boundaries do not hide the parent skill.
Registration preserves unrelated configuration and creates no user-wide settings
or trust records. A fresh session and native host trust review may be required.

The shared skill also routes `stats` to the bundled local engine. Reports need
no host hooks, model calls, frontend build or running server. Normal engine use
upgrades valid older state to schema 3 with zero initial analytics counters;
stats reads schemas 1/2/3 without upgrading or enabling them. The dashboard is
an on-demand file snapshot, not background monitoring. See
[analytics semantics](analytics.md) for coverage and privacy.

Commands run the selected absolute Python interpreter and a quoted absolute
launcher. Both adapters ingest SessionStart/UserPromptSubmit/PreToolUse/
PostToolUse/Stop. Tool matchers capture all tool names because namespaces differ
between clients. Hooks exit 0 on malformed input, missing/corrupt state or capture
failure; they return advisory additionalContext only on start/prompt events.
Metadata persists event/session/turn/project identity and a digest, never full
prompts, command arguments or tool output.

Documented UserPromptSubmit payloads supply no authenticated human-origin field.
Codex Stop may create generated prompt turns. Prompts remain unknown; tool calls
are assistant, explicit agent_id is subagent and lifecycle is system. The
NEBULA_AUTOMATED=1 environment additionally marks automated prompts system.
Public observe cannot override role or mint receipts. Programmatic sessions
verify tooling only, not direct human acceptance.

The local `confirm`, `attest`, `review` fallback requires direct interactive
terminal input. This is an operational user input boundary, not cryptographic
proof of physical identity or a defense against malicious local code. An agent
must display the command for the user and must never drive the terminal response.
Unknown chat acceptance stays unverified until this explicit path is used. The
source event host on local feedback is recorded from the initiating suggestion
session where available; no fake undocumented host field is accepted.

Installed versions inspected during planning: Claude Code 2.1.285, Codex CLI
0.160.0 (hooks enabled). Live validation results are recorded separately in
`examples/results`; documented support and unit fixtures do not establish live
compatibility. Hook trust belongs to each host and must be reviewed there.

Primary references:
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Claude skills](https://code.claude.com/docs/en/skills)
- [Codex hooks](https://developers.openai.com/codex/hooks/)
- [Codex skills](https://developers.openai.com/codex/skills/)
