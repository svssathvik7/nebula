import json
from pathlib import Path
import os
import subprocess
import sys
import unittest
from tests.support import workspace, event, lesson

class RootsStoreTests(unittest.TestCase):
    def test_identity_selection_and_restart(self):
        from nebula.lifecycle import init_nebula, set_enabled
        from nebula.roots import resolve_context
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            self.assertFalse(resolve_context(a).enabled)
            set_enabled(root,True)
            self.assertEqual(resolve_context(a).nebula_id,resolve_context(b).nebula_id)
            self.assertTrue(resolve_context(a).enabled)
            self.assertEqual(os.stat(root/'.nebula').st_mode & 0o777,0o700)

    def test_unselected_symlink_and_nested_boundary(self):
        from nebula.lifecycle import init_nebula
        from nebula.roots import resolve_context
        with workspace() as (root,a,b):
            init_nebula(root,[a])
            self.assertIsNone(resolve_context(b))
            outside=root.parent/'outside'; outside.mkdir()
            (a/'escape').symlink_to(outside,target_is_directory=True)
            self.assertIsNone(resolve_context(a/'escape'))
            child=a/'nested'; child.mkdir()
            init_nebula(a,[child])
            self.assertNotEqual(resolve_context(child).nebula_id,resolve_context(root).nebula_id)
            self.assertIsNone(resolve_context(a/'other'))

    def test_event_idempotence_digest_and_lesson_versions(self):
        from nebula.lifecycle import init_nebula
        from nebula.store import Store
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                first=event(project=str(a))
                self.assertTrue(store.put_event(first))
                self.assertFalse(store.put_event(first))
                self.assertEqual(store.get_event(first.event_id),first)
                with self.assertRaises(ValueError): store.put_event(event(project=str(a),digest='different'))
                store.put_lesson(lesson())
                store.put_lesson(lesson(version=2,action='different'))
                self.assertEqual(store.get_lesson('layout').version,2)
                self.assertEqual(store.get_lesson('layout',1).version,1)

    def test_corrupt_database_is_not_replaced(self):
        from nebula.lifecycle import init_nebula
        from nebula.store import Store, StateUnavailable
        with workspace() as (root,a,b):
            init_nebula(root,[a])
            db=root/'.nebula/state.sqlite3'; db.write_bytes(b'broken')
            with self.assertRaises(StateUnavailable):
                with Store(root): pass
            self.assertEqual(db.read_bytes(),b'broken')

    def test_atomic_rollback_and_two_process_writers(self):
        from nebula.lifecycle import init_nebula
        from nebula.store import Store
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                with self.assertRaises(RuntimeError):
                    with store.transaction():
                        store.put_event(event(project=str(a)))
                        raise RuntimeError('rollback')
                self.assertIsNone(store.get_event('event-1'))
            code='from pathlib import Path; from nebula.store import Store; from tests.support import event; import sys; s=Store(Path(sys.argv[1])); s.put_event(event(event_id=sys.argv[2],digest=sys.argv[2])); s.close()'
            workers=[subprocess.Popen([sys.executable,'-c',code,str(root),f'process-{i}']) for i in range(2)]
            self.assertEqual([p.wait() for p in workers],[0,0])
            with Store(root) as store: self.assertEqual(store.status()['events'],2)

    def test_existing_state_and_invalid_config_are_not_overwritten(self):
        from nebula.lifecycle import init_nebula
        from nebula.roots import resolve_context
        from nebula.store import StateUnavailable
        with workspace() as (root,a,b):
            init_nebula(root,[a])
            with self.assertRaises(ValueError): init_nebula(root,[b])
            (root/'.nebula/config.json').write_text('{')
            with self.assertRaises(StateUnavailable): resolve_context(a)
