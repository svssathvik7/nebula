import unittest
from dataclasses import replace
from nebula.store import Store
from nebula.lifecycle import init_nebula, set_mode
from nebula.feedback import suggest, apply_feedback
from tests.support import workspace, lesson, event, NOW

class FeedbackTests(unittest.TestCase):
    def setup_state(self, root, a, b):
        init_nebula(root,[a,b]); set_mode(root,'full')
        store=Store(root); value=lesson(); store.put_lesson(value)
        pending=suggest(store,value,session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW)
        return store,value,pending

    def receipt(self, store, pending, verb, key='accept-1', **changes):
        source=event(event_id=key,project=pending.project,session_id=pending.session_id,episode_id=pending.episode_id,**changes)
        store.put_event(source)
        store.put_receipt(key,'verified-host-submission',{'verb':verb,'suggestion_id':pending.suggestion_id})
        return key

    def apply(self,store,pending,key,verb):
        return apply_feedback(store,suggestion_id=pending.suggestion_id,source_event_id=key,verdict=verb,now=NOW)

    def test_acceptance_restart_and_idempotence(self):
        with workspace() as (root,a,b):
            store,value,pending=self.setup_state(root,a,b)
            key=self.receipt(store,pending,'accept')
            result=self.apply(store,pending,key,'accept')
            self.assertTrue(result.mature); self.assertEqual(result.confidence,.8)
            self.assertEqual(result.successful_episodes,0)
            self.assertEqual(result,self.apply(store,pending,key,'accept'))
            self.assertEqual(len(store.samples(value.lesson_id,1)),1)
            store.close()
            with Store(root) as store:
                self.assertTrue(store.confirmed(value.lesson_id,1))
                self.assertEqual(store.pending_suggestions('s1'),[])
                self.assertEqual(store.confirmation(value.lesson_id,1)['source_digest'],'digest-1')

    def test_correction_withdraw_and_disable(self):
        for verb in ('correct','withdraw','disable'):
            with self.subTest(verb=verb),workspace() as (root,a,b):
                with self.setup_state(root,a,b)[0] as store:
                    pending=store.pending_suggestions('s1')[0]
                    self.apply(store,pending,self.receipt(store,pending,'accept'),'accept')
                    result=self.apply(store,pending,self.receipt(store,pending,verb,key='later'),verb)
                    self.assertFalse(result.mature); self.assertFalse(store.confirmed('layout',1))
                    self.assertEqual(result.negatives,1)
                    if verb=='disable': self.assertTrue(store.get_lesson('layout').disabled)

    def test_new_acceptance_cannot_reuse_completed_suggestion(self):
        with workspace() as (root,a,b):
            with self.setup_state(root,a,b)[0] as store:
                pending=store.pending_suggestions('s1')[0]
                self.apply(store,pending,self.receipt(store,pending,'accept'),'accept')
                with self.assertRaises(ValueError):
                    self.apply(store,pending,self.receipt(store,pending,'accept',key='again'),'accept')

    def test_unknown_quoted_ambiguous_wrong_binding_and_stale_version(self):
        for scenario in ('unknown','missing','verb','id','session','project','version'):
            with self.subTest(scenario=scenario), workspace() as (root,a,b):
                with self.setup_state(root,a,b)[0] as store:
                    pending=store.pending_suggestions('s1')[0]
                    changes={}
                    if scenario=='unknown': changes['origin']='unknown'
                    if scenario=='session': pending_for_receipt=replace(pending,session_id='other')
                    elif scenario=='project': pending_for_receipt=replace(pending,project=str(b))
                    else: pending_for_receipt=pending
                    key=self.receipt(store,pending_for_receipt,'reject' if scenario=='verb' else 'accept',**changes)
                    if scenario=='id':
                        store.connection.execute('DELETE FROM receipts')
                        store.put_receipt(key,'verified-host-submission',{'verb':'accept','suggestion_id':'other'})
                    if scenario=='missing': store.connection.execute('DELETE FROM receipts')
                    if scenario=='version': store.put_lesson(lesson(version=2))
                    with self.assertRaises(ValueError): self.apply(store,pending,key,'accept')
                    self.assertFalse(store.confirmed('layout',1))

    def test_suggestions_scope_deduplicate_and_different_context(self):
        with workspace() as (root,a,b):
            with self.setup_state(root,a,b)[0] as store:
                value=store.get_lesson('layout'); pending=store.pending_suggestions('s1')[0]
                self.assertEqual(pending,suggest(store,value,session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW))
                suggest(store,value,session_id='s1',episode_id='e1',project=str(a),context_digest='other',now=NOW)
                self.assertEqual(len(store.pending_suggestions('s1')),2)
                with self.assertRaises(ValueError):
                    suggest(store,replace(value,scope_projects=(str(b),)),session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW)
