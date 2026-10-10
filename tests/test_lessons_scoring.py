from dataclasses import replace, asdict
import unittest
from tests.support import workspace,event,lesson,sample,mature_samples,NOW
from nebula.lifecycle import init_nebula
from nebula.store import Store

class ScoringTests(unittest.TestCase):
    def test_maturity_coverage_successes_and_boundary(self):
        from nebula.scoring import score
        good=score(mature_samples())
        self.assertTrue(good.mature); self.assertAlmostEqual(good.confidence,6/7)
        for changes in ({'session_id':'one'},{'project':'one'},{'outcome':'unknown'}):
            self.assertFalse(score(mature_samples(**changes)).mature)
        boundary=score(mature_samples()+[sample(episode_id='negative',verdict='negative')])
        self.assertEqual(boundary.confidence,0.75)
        self.assertTrue(boundary.mature)

    def test_confirmation_does_not_fake_observation_and_disable_blocks(self):
        from nebula.scoring import score
        value=score([],confirmed=True)
        self.assertTrue(value.mature); self.assertEqual(value.confidence,0.80)
        self.assertFalse(value.observational_mature); self.assertEqual(value.positives,0)
        self.assertFalse(score([],confirmed=True,disabled=True).mature)

    def test_duplicate_episode_does_not_inflate_score(self):
        from nebula.scoring import score
        self.assertEqual(score([sample()]*20).positives,1)
        self.assertFalse(score([sample()]*20).mature)

    def test_material_change_versions_without_merging_context(self):
        from nebula.lessons import record_lesson
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_event(event(project=str(a)))
                draft=asdict(lesson(evidence_ids=('event-1',)))
                one=record_lesson(store,draft)
                self.assertEqual(record_lesson(store,draft).version,1)
                two=record_lesson(store,dict(draft,trigger='when adding a production module'))
                self.assertEqual(two.version,2)
                self.assertEqual(store.get_lesson('layout',1).trigger,'when adding a module')
                other=record_lesson(store,dict(draft,lesson_id='experiment-layout',trigger='when experimenting'))
                self.assertEqual(other.version,1)

    def test_unavailable_evidence_and_inferred_rationale_cannot_be_human(self):
        from nebula.lessons import record_lesson
        with workspace() as (root,a,b):
            init_nebula(root,[a])
            with Store(root) as store:
                draft=asdict(lesson(evidence_ids=('missing',)))
                with self.assertRaises(ValueError): record_lesson(store,draft)
                store.put_event(event(project=str(a),origin='unknown'))
                draft.update(evidence_ids=['event-1'],rationale_source='human')
                with self.assertRaises(ValueError): record_lesson(store,draft)
                draft['rationale_source']='inferred'
                self.assertEqual(record_lesson(store,draft).rationale_source,'inferred')

    def test_samples_require_attribution_and_outcome_evidence(self):
        from nebula.lessons import record_sample
        with workspace() as (root,a,b):
            init_nebula(root,[a])
            with Store(root) as store:
                store.put_lesson(lesson())
                store.put_event(event(project=str(a),origin='unknown'))
                with self.assertRaises(ValueError): record_sample(store,sample(project=str(a)))
                store.put_event(event(event_id='human',digest='human',project=str(a)))
                candidate=sample(project=str(a),source_event_id='human',outcome='unknown')
                self.assertTrue(record_sample(store,candidate))
                self.assertFalse(record_sample(store,candidate))
                with self.assertRaises(ValueError): record_sample(store,replace(candidate,outcome='suitable'))
                store.put_receipt('human','interactive-terminal',{'verb':'observe','lesson_id':'layout','version':1,'verdict':'positive','outcome':'suitable'})
                record_sample(store,replace(candidate,outcome='suitable'))
                self.assertEqual(len(store.samples('layout',1)),1)
                self.assertEqual(store.samples('layout',1)[0].outcome,'suitable')

    def test_sample_scope_and_identity_must_match_captured_event(self):
        from nebula.lessons import record_sample
        with workspace() as (root,a,b):
            init_nebula(root,[a,b])
            with Store(root) as store:
                store.put_lesson(lesson(scope_projects=(str(a),)))
                store.put_event(event(project=str(a)))
                for changes in ({'project':str(b)},{'session_id':'other'},{'episode_id':'other'}):
                    with self.assertRaises(ValueError):
                        record_sample(store,sample(project=str(a),outcome='unknown',**{k:v for k,v in changes.items() if k!='project'}) if 'project' not in changes else sample(project=str(b),outcome='unknown'))
