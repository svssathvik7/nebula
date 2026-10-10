"""Simulated terminal fixtures exercise parsers, not real human provenance."""
import io,unittest
from nebula.lifecycle import init_nebula
from nebula.store import Store
from nebula.feedback import suggest
from nebula.interactive import confirm,attest,review
from nebula.scoring import current_score
from tests.support import workspace,event,lesson,NOW

class SimulatedTerminal(io.StringIO):
    def isatty(self): return True

class InteractiveTests(unittest.TestCase):
    def test_acknowledgement_matches_and_preserves_initiating_host(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_lesson(lesson()); store.put_event(event(origin='unknown',project=str(a)))
                pending=suggest(store,store.get_lesson('layout'),session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW)
                result=confirm(store,suggestion_id=pending.suggestion_id,verdict='accept',stream=SimulatedTerminal('NEBULA ACCEPT '+pending.suggestion_id+'\n'),out=io.StringIO())
                self.assertTrue(result.mature); self.assertEqual(result.confidence,.8)
                snapshot=store.confirmation('layout',1)
                source=store.get_event(snapshot['source_event_id'])
                self.assertEqual(source.host,'claude')
                self.assertEqual(snapshot['suggestion_id'],pending.suggestion_id)
                self.assertEqual(snapshot['session_id'],'s1')

    def test_pipe_wrong_text_and_quoted_text_cannot_confirm(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_lesson(lesson())
                pending=suggest(store,store.get_lesson('layout'),session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW)
                for stream in (io.StringIO('NEBULA ACCEPT '+pending.suggestion_id+'\n'),SimulatedTerminal('yes\n'),SimulatedTerminal('"NEBULA ACCEPT '+pending.suggestion_id+'"\n')):
                    with self.assertRaises(ValueError): confirm(store,suggestion_id=pending.suggestion_id,verdict='accept',stream=stream,out=io.StringIO())
                self.assertFalse(store.confirmed('layout',1)); self.assertEqual(store.status()['events'],0)

    def test_local_attribution_deduplicates_original_episode(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_lesson(lesson()); store.put_event(event(project=str(a),origin='unknown'))
                for _ in range(2):
                    result=attest(store,event_id='event-1',lesson_id='layout',verdict='positive',outcome='suitable',stream=SimulatedTerminal('NEBULA OBSERVE layout event-1 positive suitable\n'),out=io.StringIO())
                    self.assertTrue(result['sample_recorded'])
                self.assertEqual(len(store.samples('layout',1)),1)
                self.assertFalse(current_score(store,store.get_lesson('layout')).mature)

    def test_negative_attestation_uses_reserved_feedback_capacity(self):
        from nebula.maintenance import HARD,usage_bytes
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_lesson(lesson()); store.put_event(event(project=str(a),origin='unknown'))
                pending=suggest(store,store.get_lesson('layout'),session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW)
                confirm(store,suggestion_id=pending.suggestion_id,verdict='accept',stream=SimulatedTerminal('NEBULA ACCEPT '+pending.suggestion_id+'\n'),out=io.StringIO())
                with (root/'.nebula/pressure').open('wb') as out: out.truncate(HARD-65536-usage_bytes(root))
                result=attest(store,event_id='event-1',lesson_id='layout',verdict='negative',outcome='unknown',stream=SimulatedTerminal('NEBULA OBSERVE layout event-1 negative unknown\n'),out=io.StringIO())
                self.assertTrue(result['sample_recorded']); self.assertFalse(store.confirmed('layout',1))
