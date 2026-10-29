import json
import unittest
from nebula import lifecycle
from nebula.roots import read_config, resolve_context
from nebula.store import Store, StateUnavailable
from tests.support import workspace


class ModeTests(unittest.TestCase):
    def test_old_configs_resolve_off_and_full_without_rewriting(self):
        with workspace() as (root, a, b):
            lifecycle.init_nebula(root, [a, b])
            path = root/'.nebula/config.json'
            for enabled, expected in ((False, 'off'), (True, 'full')):
                data = json.loads(path.read_text()); data.pop('mode', None)
                data['enabled'] = enabled; path.write_text(json.dumps(data))
                before = path.read_bytes()
                self.assertEqual(read_config(root)['mode'], expected)
                self.assertEqual(resolve_context(a).mode, expected)
                self.assertEqual(path.read_bytes(), before)

    def test_observe_persists_and_on_off_preserve_memory(self):
        with workspace() as (root, a, b):
            lifecycle.init_nebula(root, [a, b])
            with Store(root) as store: store.set_meta('retained', 'keep')
            lifecycle.set_mode(root, 'observe')
            self.assertEqual(resolve_context(a).mode, 'observe')
            self.assertTrue(resolve_context(a).enabled)
            self.assertEqual(json.loads((root/'.nebula/config.json').read_text())['mode'], 'observe')
            lifecycle.set_enabled(root, False)
            self.assertEqual(read_config(root)['mode'], 'off')
            lifecycle.set_enabled(root, True)
            self.assertEqual(read_config(root)['mode'], 'full')
            with Store(root) as store: self.assertEqual(store.get_meta('retained'), 'keep')

    def test_invalid_or_conflicting_modes_fail_closed(self):
        with workspace() as (root, a, b):
            lifecycle.init_nebula(root, [a, b])
            path = root/'.nebula/config.json'; original = json.loads(path.read_text())
            for mode, enabled in (('broken', True), (None, True), ('observe', False), ('off', True)):
                with self.subTest(mode=mode, enabled=enabled):
                    path.write_text(json.dumps({**original, 'mode':mode, 'enabled':enabled}))
                    with self.assertRaises(StateUnavailable): read_config(root)

    def test_invalid_mode_update_leaves_configuration_unchanged(self):
        with workspace() as (root, a, b):
            lifecycle.init_nebula(root, [a, b])
            path = root/'.nebula/config.json'; before = path.read_bytes()
            with self.assertRaises(ValueError): lifecycle.set_mode(root, 'broken')
            self.assertEqual(path.read_bytes(), before)
