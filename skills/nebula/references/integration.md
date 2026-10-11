# Integration status and boundaries

Claude Code project skills: `.claude/skills/nebula`; hooks:
`.claude/settings.local.json`. Codex project skills: `.agents/skills/nebula`;
hooks: `.codex/hooks.json` beside `.codex/config.toml`. Setup links each selected
child separately so nested Git boundaries do not hide the parent skill.
Registration preserves unrelated configuration and creates no user-wide settings
or trust records. A fresh session and native host trust review may be required.

Commands run the selected absolute Python interpreter and a quoted absolute
launcher. Both adapters ingest SessionStart/UserPromptSubmit/PreToolUse/
PostToolUse/Stop. Tool matchers capture all tool names because namespaces differ
between clients. Hooks exit 0 on malformed input, missing/corrupt state or capture
failure; they return advisory additionalContext only on start/prompt events.
Metadata persists event/session/turn/project identity and a digest, never full
prompts, command arguments or tool output.

Mode is shared by all selected children of the canonical parent. Both hosts
emit passive OBSERVE guidance on start/prompt events in observation mode;
full mode emits ON guidance. OFF stops capture. Update the installed runtime
and skill together before selecting observation mode: older runtimes that
only check `enabled` do not enforce this mode. Existing symlink registrations
follow that runtime checkout; use fresh sessions when updating skill content.
The utility gates new suggestions/application claims using current mode inside
their write transaction, rather than relying on a session's cached status.
It cannot cancel host tool actions already executing when the mode changes.

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
