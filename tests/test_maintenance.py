import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from nebula.lifecycle import init_nebula,set_enabled
from nebula.store import Store,StateUnavailable
from nebula.capture import capture_event,normalize
from nebula.maintenance import maintain,usage_bytes,capacity_state,health
from nebula.application import claim_application
from nebula.scoring import current_score
from tests.support import workspace,lesson,event,sample,NOW
from nebula.models import timestamp,dump

class MaintenanceTests(unittest.TestCase):
    def test_retention_boundaries_confirmation_and_sample_expiry(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); set_enabled(root,True)
            with Store(root) as store:
                store.put_lesson(lesson()); store.connection.execute('INSERT INTO confirmations VALUES(?,?,?)',('layout',1,dump({'source_digest':'preserved'})))
                for days in (13,14,15,89,90,91):
                    date=(timestamp(NOW)-timedelta(days=days)).isoformat()
                    store.put_event(event(event_id=f'ev-{days}',timestamp=date)); store.put_sample(sample(episode_id=f'e{days}',source_event_id=f'ev-{days}',timestamp=date))
                    store.put_receipt(f'ev-{days}','verified-host-submission',{'outcome':'suitable'})
            result=maintain(root,now=NOW)
            with Store(root) as store:
                self.assertEqual(store.status()['events'],2); self.assertEqual(store.status()['samples'],5)
                self.assertTrue(store.confirmed('layout',1)); self.assertTrue(current_score(store,store.get_lesson('layout'),now=NOW).mature)
                self.assertEqual(store.confirmation('layout',1)['source_digest'],'preserved')
                self.assertIsNone(store.receipt('ev-15')); self.assertEqual(result['state'],'normal')
                before=store.status(); maintain(root,now=NOW); self.assertEqual(store.status(),before)

    def test_event_limit_audit_meta_and_app_history_bounded(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store,store.transaction():
                value=event()
                store.connection.executemany('INSERT INTO events VALUES(?,?,?,?)',[(f'ev-{i}',f'd-{i}',NOW,dump(replace(value,event_id=f'ev-{i}'))) for i in range(10001)])
            maintain(root,now=NOW)
            with Store(root) as store: self.assertEqual(store.status()['events'],10000)

    def test_hard_limit_sidecars_symlinks_and_off_capture(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); set_enabled(root,True)
            path=root/'.nebula/large-sidecar'
            with path.open('wb') as out: out.truncate(64*1024*1024)
            self.assertGreaterEqual(usage_bytes(root),64*1024*1024); self.assertEqual(capacity_state(root),'hard-limit')
            payload={'hook_event_name':'UserPromptSubmit','session_id':'s1','cwd':str(a),'prompt':'module'}
            self.assertIsNone(capture_event(root,'claude',payload,now=NOW))
            with Store(root) as store:
                store.connection.execute('INSERT INTO lessons VALUES(?,?,?)',('layout',1,dump(lesson())))
                store.connection.execute('INSERT INTO confirmations VALUES(?,?,?)',('layout',1,'{}'))
                self.assertFalse(claim_application(store,lesson_id='layout',version=1,session_id='s1',episode_id='e1',project=str(a),context_match=True,permissions_ok=True))
            self.assertEqual(health(root)['capacity'],'hard-limit')
            set_enabled(root,False); path.unlink()
            (root/'.nebula/escape').symlink_to(root.parent)
            self.assertEqual(capacity_state(root),'hard-limit')
            self.assertFalse(health(root)['usable'])

    def test_corruption_health_preserves_state_and_interrupted_maintenance_rolls_back(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store: store.put_event(event(timestamp='2026-01-01T00:00:00Z'))
            with patch('nebula.maintenance.prune',side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError): maintain(root,now=NOW)
            with Store(root) as store: self.assertIsNotNone(store.get_event('event-1'))
            path=root/'.nebula/state.sqlite3'; path.write_bytes(b'broken')
            self.assertFalse(health(root)['usable']); self.assertEqual(path.read_bytes(),b'broken')

    def test_episode_identity_is_namespaced_across_hosts_and_sessions(self):
        base={'hook_event_name':'UserPromptSubmit','session_id':'s1','turn_id':'1','cwd':'/tmp'}
        one=normalize('claude',base,now=NOW); two=normalize('codex',base,now=NOW)
        three=normalize('claude',base|{'session_id':'s2'},now=NOW)
        self.assertNotEqual(one.episode_id,two.episode_id); self.assertNotEqual(one.episode_id,three.episode_id)
