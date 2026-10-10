import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from nebula.lifecycle import init_nebula,set_enabled
from nebula.store import Store
from nebula.models import dump
from nebula.scoring import score
from nebula.recall import recall
from nebula.application import decide,claim_application,finish_application,review_application
from tests.support import workspace,lesson,event,sample,mature_samples,NOW

class RecallApplicationTests(unittest.TestCase):
    def test_decision_matrix(self):
        for mature in (False,True):
            value=score([],confirmed=mature)
            cases=[(False,True,True,False,'none'),(True,False,True,False,'none'),(True,None,True,False,'suggest'),
                   (True,True,False,False,'blocked'),(True,True,True,True,'blocked'),
                   (True,True,True,False,'apply' if mature else 'suggest')]
            for enabled,match,permissions,suspended,expected in cases:
                self.assertEqual(decide(lesson(),value,enabled=enabled,context_match=match,permissions_ok=permissions,suspended=suspended).mode,expected)
        boundary=score(mature_samples()+[sample(episode_id='negative',verdict='negative')])
        self.assertEqual(boundary.confidence,.75)
        self.assertEqual(decide(lesson(),boundary,enabled=True,context_match=True,permissions_ok=True).mode,'suggest')
        self.assertNotEqual(decide(lesson(disabled=True),score([],confirmed=True),enabled=True,context_match=True,permissions_ok=True).mode,'apply')

    def test_recall_scope_words_conflicts_and_bytes(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); set_enabled(root,True)
            with Store(root) as store:
                store.put_lesson(lesson(lesson_id='scope',scope_projects=(str(b),)))
                store.put_lesson(lesson(lesson_id='disabled',disabled=True))
                for i in range(9): store.put_lesson(lesson(lesson_id=f'layout-{i}',action=f'Place module {i}.',rationale='x'*2000))
                results=recall(store,project=str(a),query='ADDING MODULE')
                self.assertEqual(len(results),6); self.assertTrue(all(r['conflict'] for r in results))
                self.assertLessEqual(len(dump(results).encode()),8192)
                self.assertNotIn('scope',[r['lesson_id'] for r in results]); self.assertNotIn('disabled',[r['lesson_id'] for r in results])
                self.assertEqual(recall(store,project=str(a),query='modules'),[])
                self.assertEqual(recall(store,project=str(a),query=''),[])
                self.assertEqual(recall(store,project=str(root),query='module'),[])
                self.assertLessEqual(len(recall(store,project=str(a),query='module '*2000,limit=999)),6)
                set_enabled(root,False); self.assertEqual(recall(store,project=str(a),query='module'),[])

    def setup_state(self,root,a,b):
        init_nebula(root,[a,b]); set_enabled(root,True)
        with Store(root) as store:
            store.put_lesson(lesson(scope_projects=(str(a),)))
            for s in mature_samples(project=str(a)): store.put_sample(replace(s,project=str(a if int(s.episode_id[1:])%2 else b)))
            # Fixture confirmation is separate from sample coverage.
            store.connection.execute('INSERT INTO confirmations VALUES(?,?,?)',('layout',1,'{}'))

    def claim(self,store,a,**changes):
        args=dict(lesson_id='layout',version=1,session_id='s1',episode_id='e1',project=str(a),context_match=True,permissions_ok=True)
        return claim_application(store,**(args|changes))

    def test_application_claim_concurrent_and_context_guards(self):
        with workspace() as (root,a,b):
            self.setup_state(root,a,b)
            def writer(_):
                with Store(root) as store: return self.claim(store,a)
            with ThreadPoolExecutor(2) as pool: self.assertEqual(sorted(pool.map(writer,range(2))),[False,True])
            with Store(root) as store:
                for changes in ({'project':str(b)},{'version':2},{'context_match':None},{'permissions_ok':False}):
                    self.assertFalse(self.claim(store,a,episode_id='other',**changes))
                set_enabled(root,False); self.assertFalse(self.claim(store,a,episode_id='off'))

    def test_failure_requires_human_review_and_no_self_reinforcement(self):
        with workspace() as (root,a,b):
            self.setup_state(root,a,b)
            with Store(root) as store:
                self.assertTrue(self.claim(store,a)); before=len(store.samples('layout',1))
                source=event(event_id='tool',project=str(a),origin='assistant'); store.put_event(source)
                finish_application(store,lesson_id='layout',version=1,session_id='s1',episode_id='e1',outcome='failed',source_event_ids=['tool'])
                self.assertFalse(self.claim(store,a,episode_id='e2'))
                self.assertEqual(len(store.samples('layout',1)),before)
                with self.assertRaises(ValueError): review_application(store,lesson_id='layout',version=1,source_event_id='tool')
                user=event(event_id='review',project=str(a)); store.put_event(user)
                store.put_receipt('review','verified-host-submission',{'verb':'review','lesson_id':'layout','version':1,'failure_id':store.get_meta('suspended:layout:1')['failure_id']})
                review_application(store,lesson_id='layout',version=1,source_event_id='review')
                self.assertTrue(self.claim(store,a,episode_id='e2'))
                with self.assertRaises(ValueError): finish_application(store,lesson_id='layout',version=1,session_id='s1',episode_id='e2',outcome='suitable',source_event_ids=['missing'])
