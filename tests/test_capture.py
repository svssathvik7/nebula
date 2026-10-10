import io
import json
from dataclasses import replace
from pathlib import Path
import unittest
from tests.support import workspace, NOW
from nebula.lifecycle import init_nebula, set_enabled
from nebula.store import Store

class CaptureTests(unittest.TestCase):
    def payload(self,a,**kw):
        return dict(session_id='session',turn_id='turn',cwd=str(a),
                    hook_event_name='UserPromptSubmit',prompt='choose a module layout',**kw)

    def test_tool_and_unknown_origin_cannot_confirm(self):
        from nebula.capture import normalize
        for host in ('claude','codex'):
            p={'session_id':'s1','cwd':'/fixture','hook_event_name':'PostToolUse',
               'tool_name':'Bash','tool_input':{'command':'echo okay'},'tool_response':{'exit_code':0}}
            self.assertEqual(normalize(host,p,now=NOW).origin,'assistant')
            p.update(hook_event_name='UserPromptSubmit',prompt='NEBULA ACCEPT s1')
            self.assertEqual(normalize(host,p,now=NOW).origin,'unknown')
            p['agent_id']='agent'
            self.assertEqual(normalize(host,p,now=NOW).origin,'subagent')

    def test_capture_is_idempotent_scoped_and_off(self):
        from nebula.capture import capture_event
        with workspace() as (root,a,b):
            init_nebula(root,[a]); set_enabled(root,True)
            p=self.payload(a)
            first=capture_event(root,'claude',p,now=NOW)
            self.assertEqual(first,capture_event(root,'claude',p,now=NOW))
            with Store(root) as store: self.assertEqual(store.status()['events'],1)
            self.assertIsNone(capture_event(root,'claude',self.payload(b),now=NOW))
            set_enabled(root,False)
            self.assertIsNone(capture_event(root,'claude',p,now=NOW))

    def test_unknown_and_generated_events_do_not_create_receipts(self):
        from nebula.capture import capture_event
        with workspace() as (root,a,b):
            init_nebula(root,[a]); set_enabled(root,True)
            for host in ('claude','codex'):
                key=capture_event(root,host,self.payload(a),now=NOW)
                with Store(root) as store:
                    self.assertEqual(store.get_event(key).origin,'unknown')
                    self.assertIsNone(store.receipt(key))

    def test_hook_json_limits_and_fail_open(self):
        from nebula.capture import run_hook
        for data in (b'{',b'x'*65537,b'\xff',b'null'):
            output=io.StringIO()
            self.assertEqual(run_hook('codex',io.BytesIO(data),output),0)
            self.assertEqual(output.getvalue(),'')
        with workspace() as (root,a,b):
            init_nebula(root,[a]); set_enabled(root,True)
            for host in ('claude','codex'):
                p=self.payload(a)
                output=io.StringIO()
                self.assertEqual(run_hook(host,io.BytesIO(json.dumps(p).encode()),output),0)
                result=json.loads(output.getvalue())
                self.assertEqual(result['hookSpecificOutput']['hookEventName'],'UserPromptSubmit')
                self.assertNotIn('decision',result)
                with Store(root) as store: self.assertEqual(store.status()['events'], 1 if host=='claude' else 2)

    def test_no_full_prompt_or_tool_output_is_stored(self):
        from nebula.capture import normalize
        p={'session_id':'s','cwd':'/fixture','hook_event_name':'PostToolUse',
           'tool_name':'Bash','tool_response':'SECRET-CONTENT'*10000}
        item=normalize('claude',p,now=NOW)
        self.assertNotIn('SECRET-CONTENT',item.hint)
        self.assertLessEqual(len(item.hint),512)
        self.assertIsNone(normalize('claude',dict(p,hook_event_name='Imaginary'),now=NOW))

    def test_payload_field_types_and_null_optionals(self):
        from nebula.capture import normalize
        p={'session_id':'s','cwd':'/fixture','hook_event_name':'Stop', 'last_assistant_message':None}
        self.assertIsNotNone(normalize('codex',p,now=NOW))
        self.assertIsNone(normalize('codex',dict(p,session_id=[]),now=NOW))
