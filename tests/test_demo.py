import unittest
from examples.demo import run_demo

class DemoTests(unittest.TestCase):
    def test_full_loop_is_general_and_correction_works(self):
        result=run_demo()
        self.assertTrue(result['synthetic']); self.assertEqual(result['initial_mode'],'suggest')
        self.assertTrue(result['after_acceptance']['mature']); self.assertGreater(result['after_acceptance']['confidence'],.75)
        self.assertEqual(result['matching_sibling_mode'],'apply'); self.assertNotEqual(result['different_context_mode'],'apply')
        self.assertFalse(result['after_withdrawal']['confirmed']); self.assertTrue(result['artifact_verified'])
