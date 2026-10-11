from dataclasses import asdict
import io
import json
import unittest
from nebula.application import claim_application, finish_application
from nebula.capture import capture_event, run_hook
from nebula.feedback import suggest
from nebula.lessons import record_lesson
from nebula.lifecycle import init_nebula, set_mode
from nebula.models import utcnow
from nebula.scoring import current_score
from nebula.store import Store
from tests.support import workspace, lesson, event


class ObservationTests(unittest.TestCase):
    def payload(self, project, **changes):
        return {'cwd':str(project),'session_id':'observation','turn_id':'turn',
                'hook_event_name':'UserPromptSubmit','prompt':'private task context', **changes}

    def test_both_hosts_emit_passive_guidance_and_capture_without_receipts(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'observe')
            for host in ('claude','codex'):
                output = io.StringIO()
                run_hook(host, io.BytesIO(json.dumps(self.payload(a)).encode()), output)
                message = json.loads(output.getvalue())['hookSpecificOutput']['additionalContext']
                self.assertIn('OBSERVE', message)
                self.assertIn('Do not suggest', message)
                with Store(root) as store:
                    rows = store.connection.execute('SELECT id FROM events').fetchall()
                    self.assertTrue(rows)
                    self.assertTrue(all(store.receipt(row[0]) is None for row in rows))
            self.assertIsNone(capture_event(root,'claude',self.payload(b),now=utcnow()))

    def test_candidate_learning_does_not_confirm_or_apply(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'observe')
            key = capture_event(root, 'claude', self.payload(a), now=utcnow())
            with Store(root) as store:
                candidate = record_lesson(store, asdict(lesson(evidence_ids=(key,))))
                score = current_score(store, candidate)
                self.assertFalse(score.mature)
                self.assertFalse(store.confirmed(candidate.lesson_id, candidate.version))
                self.assertEqual(store.status()['samples'], 0)
                self.assertEqual(store.status()['applications'], 0)

    def test_observe_blocks_new_and_replayed_suggestions_without_side_effects(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root, 'full')
            with Store(root) as store:
                value=lesson(); store.put_lesson(value)
                fields=dict(session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=utcnow())
                suggest(store,value,**fields)
                set_mode(root,'observe'); before=store.status()
                for context in ('context','new'):
                    with self.subTest(context=context), self.assertRaises(ValueError):
                        suggest(store,value,**(fields|{'context_digest':context}))
                self.assertEqual(store.status(),before)

    def test_mature_claim_blocked_even_in_an_existing_store_then_full_restores(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a]); set_mode(root,'full')
            with Store(root) as store:
                value=lesson(); store.put_lesson(value)
                store.connection.execute('INSERT INTO confirmations VALUES(?,?,?)',('layout',1,'{}'))
                fields=dict(lesson_id='layout',version=1,session_id='s1',episode_id='e1',
                            project=str(a),context_match=True,permissions_ok=True)
                self.assertTrue(current_score(store,value).mature)
                set_mode(root,'observe'); before=store.status()
                self.assertFalse(claim_application(store,**fields))
                self.assertEqual(store.status(),before)
                set_mode(root,'full')
                self.assertTrue(claim_application(store,**fields))

    def test_finish_existing_claim_is_bookkeeping_not_a_new_action(self):
        with workspace() as (root, a, b):
            init_nebula(root,[a]); set_mode(root,'full')
            with Store(root) as store:
                store.put_lesson(lesson())
                store.connection.execute('INSERT INTO confirmations VALUES(?,?,?)',('layout',1,'{}'))
                fields=dict(lesson_id='layout',version=1,session_id='s1',episode_id='e1')
                self.assertTrue(claim_application(store,**fields,project=str(a),context_match=True,permissions_ok=True))
                store.put_event(event(event_id='outcome',project=str(a),origin='assistant',timestamp=utcnow()))
                set_mode(root,'observe')
                finish_application(store,**fields,outcome='suitable',source_event_ids=['outcome'])
                self.assertEqual(store.application('layout',1,'s1','e1')['status'],'suitable')
                self.assertFalse(claim_application(store,**(fields|{'episode_id':'new'}),project=str(a),context_match=True,permissions_ok=True))
