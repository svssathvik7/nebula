import os

def origin(payload):
    if payload.get('agent_id'): return 'subagent'
    if payload.get('hook_event_name') in ('PreToolUse','PostToolUse','PostToolUseFailure'): return 'assistant'
    if payload.get('hook_event_name')!='UserPromptSubmit': return 'system'
    # UserPromptSubmit can also represent autonomous turns. Its name alone
    # does not establish human authorship.
    if payload.get('stop_hook_active') or os.environ.get('NEBULA_AUTOMATED')=='1': return 'system'
    return 'unknown'
