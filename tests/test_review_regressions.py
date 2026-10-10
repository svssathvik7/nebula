import json,subprocess,sys,unittest
from pathlib import Path
from dataclasses import replace,asdict
from datetime import timedelta
from nebula.store import Store,StateUnavailable
from nebula.lifecycle import init_nebula,set_enabled
from nebula.models import dump,timestamp,utcnow,Sample
from nebula.lessons import record_sample,record_lesson
from nebula.feedback import suggest,apply_feedback
from nebula.application import claim_application,finish_application,review_application
from nebula.maintenance import maintain,health,HARD,usage_bytes
from nebula.install import plan_install,install,uninstall
from nebula.capture import capture_event
from nebula.recall import recall
from tests.support import workspace,lesson,event,sample,NOW

RUNTIME=Path(__file__).resolve().parents[1]

class ReviewRegressionTests(unittest.TestCase):
    def state(self,root,a,b):
        init_nebula(root,[a,b]); set_enabled(root,True)
        store=Store(root); store.put_lesson(lesson())
        pending=suggest(store,store.get_lesson('layout'),session_id='s1',episode_id='e1',project=str(a),context_digest='context',now=NOW)
        self.user_receipt(store,a,'accept','accept',suggestion_id=pending.suggestion_id)
        apply_feedback(store,suggestion_id=pending.suggestion_id,source_event_id='accept',verdict='accept',now=NOW)
        return store,pending

    def user_receipt(self,store,a,key,verb,**binding):
        store.put_event(event(event_id=key,project=str(a),timestamp=NOW))
        store.put_receipt(key,'verified-host-submission',{'verb':verb,**binding})

    def claim(self,store,a,episode,**changes):
        return claim_application(store,**(dict(lesson_id='layout',version=1,session_id='s1',episode_id=episode,project=str(a),context_match=True,permissions_ok=True)|changes))

    def test_sample_receipt_choice_version_lesson_time_binding_and_revoke(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store:
                self.user_receipt(store,a,'observed','observe',lesson_id='layout',version=1,verdict='negative',outcome='suitable')
                value=sample(project=str(a),source_event_id='observed',verdict='negative',timestamp=NOW)
                for changes in ({'verdict':'positive'},{'lesson_id':'other'},{'timestamp':'2099-01-01T00:00:00Z'},{'outcome':'unknown'}):
                    if changes.get('lesson_id')=='other': store.put_lesson(lesson(lesson_id='other'))
                    with self.assertRaises(ValueError): record_sample(store,replace(value,**changes))
                record_sample(store,value); self.assertFalse(store.confirmed('layout',1))
                store.put_lesson(lesson(version=2))
                with self.assertRaises(ValueError): record_sample(store,replace(value,version=2))
                stored=store.sample_provenance('layout',1,'e1')
                self.assertEqual(stored['source_digest'],'digest-1'); self.assertEqual(stored['verdict'],'negative')

    def test_review_cannot_clear_a_later_failure(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store:
                for episode in ('failure-a','failure-b'):
                    self.assertTrue(self.claim(store,a,episode))
                    tool=event(event_id=episode,project=str(a),origin='assistant'); store.put_event(tool)
                    finish_application(store,lesson_id='layout',version=1,session_id='s1',episode_id=episode,outcome='failed',source_event_ids=[episode])
                    if episode=='failure-a':
                        self.user_receipt(store,a,'review','review',lesson_id='layout',version=1,failure_id=store.get_meta('suspended:layout:1')['failure_id'])
                        review_application(store,lesson_id='layout',version=1,source_event_id='review')
                        review_application(store,lesson_id='layout',version=1,source_event_id='review')
                with self.assertRaises(ValueError): review_application(store,lesson_id='layout',version=1,source_event_id='review')
                self.assertFalse(self.claim(store,a,'later'))

    def test_reserved_region_allows_withdraw_but_withholds_applications(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store:
                pending=store.get_suggestion(store.connection.execute('SELECT id FROM suggestions').fetchone()[0])
                self.user_receipt(store,a,'withdraw','withdraw',suggestion_id=pending.suggestion_id)
                file=root/'.nebula/pressure'
                with file.open('wb') as stream: stream.truncate(HARD-65536-usage_bytes(root))
                self.assertFalse(self.claim(store,a,'under-pressure'))
                apply_feedback(store,suggestion_id=pending.suggestion_id,source_event_id='withdraw',verdict='withdraw',now=NOW)
                self.assertFalse(store.confirmed('layout',1)); self.assertLess(usage_bytes(root),HARD)

    def test_confirmation_binding_survives_suggestion_expiry(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store:
                pending=store.connection.execute('SELECT id FROM suggestions').fetchone()[0]
            maintain(root,now='2027-01-07T00:00:00Z')
            with Store(root) as store:
                self.assertIsNotNone(store.get_suggestion(pending))
                confirmation=store.confirmation('layout',1)
                self.assertEqual(confirmation['suggestion_id'],pending)
                self.assertEqual(confirmation['session_id'],'s1'); self.assertEqual(confirmation['context_digest'],'context')
                self.user_receipt(store,a,'withdraw-later','withdraw',suggestion_id=pending)
                result=apply_feedback(store,suggestion_id=pending,source_event_id='withdraw-later',verdict='withdraw',now='2027-01-07T00:00:00Z')
                self.assertFalse(store.confirmed('layout',1)); self.assertFalse(result.mature)

    def test_missing_schema_withholds_health_and_claim(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store: store.connection.execute('DROP TABLE events')
            self.assertFalse(health(root)['usable'])
            with self.assertRaises(StateUnavailable): Store(root)

    def test_install_repairs_missing_owned_link_and_layer(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); install(plan_install(root,[a],['codex'],RUNTIME))
            (a/'.agents/skills/nebula').unlink(); (a/'.codex/config.toml').unlink()
            changes=plan_install(root,[a],['codex'],RUNTIME); self.assertTrue(changes)
            install(changes); self.assertTrue((a/'.agents/skills/nebula').is_symlink()); self.assertTrue((a/'.codex/config.toml').is_file())
            uninstall(root,a,'codex'); self.assertFalse((a/'.codex/hooks.json').exists())

    def test_install_recovers_abrupt_exit_before_manifest_commit(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            code='''import os,sys
from pathlib import Path
import nebula.install as m
real=m.write_atomic
def crash(path,text):
    real(path,text)
    if str(path).endswith('settings.local.json'): os._exit(71)
m.write_atomic=crash
m.install(m.plan_install(Path(sys.argv[1]),[Path(sys.argv[2])],['claude'],Path(sys.argv[3])))
'''
            result=subprocess.run([sys.executable,'-c',code,str(root),str(a),str(RUNTIME)],cwd=RUNTIME,capture_output=True)
            self.assertEqual(result.returncode,71,result.stderr)
            self.assertTrue((a/'.claude/skills/nebula').exists())
            changes=plan_install(root,[a],['claude'],RUNTIME); install(changes)
            with Store(root) as store: self.assertTrue(store.installation(str(a),'claude'))
            uninstall(root,a,'claude'); self.assertFalse((a/'.claude/skills/nebula').exists()); self.assertFalse((a/'.claude/settings.local.json').exists())

    def test_public_context_assessment_requires_exact_boolean(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store:
                for invalid in (0,1,'true',[],{},'false'):
                    with self.assertRaises(ValueError): self.claim(store,a,'invalid',context_match=invalid)
                self.assertFalse(self.claim(store,a,'unknown',context_match=None))

    def test_oversized_recall_requires_inspection_and_keeps_other_candidates(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); set_enabled(root,True)
            with Store(root) as store:
                store.put_lesson(lesson(lesson_id='a-large',exceptions=tuple('x'*1024 for _ in range(9))))
                store.put_lesson(lesson(lesson_id='b-small'))
                results=recall(store,project=str(a),query='adding module')
                self.assertEqual([v['lesson_id'] for v in results],['a-large','b-small'])
                self.assertTrue(results[0]['requires_inspection']); self.assertLessEqual(len(dump(results).encode()),8192)

    def test_capture_enforces_count_and_expiry_in_same_session(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); set_enabled(root,True)
            with Store(root) as store,store.transaction():
                value=event(timestamp=utcnow())
                store.connection.executemany('INSERT INTO events VALUES(?,?,?,?)',[(f'ev-{i}',f'd-{i}',value.timestamp,dump(replace(value,event_id=f'ev-{i}'))) for i in range(10000)])
                store.set_meta('maintenance-sessions',['ongoing'])
            payload={'hook_event_name':'PostToolUse','session_id':'ongoing','cwd':str(a),'tool_name':'Bash'}
            for turn in ('a','b'): capture_event(root,'claude',payload|{'tool_use_id':turn},now=utcnow())
            with Store(root) as store:
                self.assertEqual(store.status()['events'],10000)
                store.connection.execute("UPDATE events SET timestamp='2026-01-01T00:00:00Z' WHERE id='ev-9999'")
            capture_event(root,'claude',payload|{'tool_use_id':'c'},now=utcnow())
            with Store(root) as store: self.assertIsNone(store.get_event('ev-9999'))

    def test_typed_record_rejection_does_not_poison_lessons(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_event(event())
                draft=asdict(lesson(evidence_ids=('event-1',)))
                for changes in ({'trigger':1},{'rationale':{'large':'object'}},{'disabled':0},{'action':None},{'context_tags':[1]}):
                    with self.assertRaises(ValueError): record_lesson(store,draft|changes)
                self.assertEqual(store.lessons(),[])

    def test_all_event_writers_respect_count_bound(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store,store.transaction():
                value=event(timestamp=utcnow())
                store.connection.executemany('INSERT INTO events VALUES(?,?,?,?)',[(f'ev-{i}',f'd-{i}',value.timestamp,dump(replace(value,event_id=f'ev-{i}'))) for i in range(10000)])
                store.put_event(event(event_id='local-ack',timestamp=utcnow()))
                self.assertEqual(store.status()['events'],10000)

    def test_v1_upgrade_retains_history_without_inventing_provenance(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0] as store:
                store.connection.execute('DROP TABLE sample_provenance')
                store.connection.execute('PRAGMA user_version=1')
            with Store(root) as store:
                self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0],2)
                self.assertEqual(len(store.samples('layout',1)),1)
                self.assertIsNone(store.sample_provenance('layout',1,'e1'))
                self.assertTrue(store.confirmed('layout',1))

    def test_inspect_exposes_retained_attribution_after_raw_expiry(self):
        with workspace() as (root,a,b):
            with self.state(root,a,b)[0]: pass
            maintain(root,now='2026-10-22T00:00:00Z')
            result=subprocess.run([sys.executable,str(RUNTIME/'scripts/nebula.py'),'inspect','--root',str(root),'--lesson','layout'],cwd='/private/tmp',capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(result.stdout)
            self.assertEqual(data['sample_provenance'][0]['source_digest'],'digest-1')
            self.assertTrue(data['evidence']==[] or all(e.get('expired_or_missing') for e in data['evidence']))
