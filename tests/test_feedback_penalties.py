"""A task-specific override must not erase a generally useful preference."""
from contextlib import contextmanager
from dataclasses import asdict
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

from nebula.application import claim_application, finish_application
from nebula.feedback import VERDICTS, apply_feedback, suggest
from nebula.lessons import record_lesson, record_sample
from nebula.lifecycle import init_nebula, set_enabled
from nebula.maintenance import maintain
from nebula.interactive import confirm
from nebula.recall import recall
from nebula.scoring import current_score
from nebula.store import StateUnavailable, Store
from tests.support import NOW, event, lesson, mature_samples, sample, workspace
from tests.test_interactive import SimulatedTerminal

RUNTIME = Path(__file__).resolve().parents[1]


class FeedbackPenaltyTests(unittest.TestCase):
    @contextmanager
    def state(self):
        with workspace() as (root, a, b):
            init_nebula(root, [a, b])
            set_enabled(root, True)
            with Store(root) as store:
                value = lesson()
                store.put_lesson(value)
                yield root, a, b, store, value

    def suggestion(self, store, value, project, episode, context='context'):
        return suggest(store, value, session_id='session', episode_id=episode,
                       project=str(project), context_digest=context, now=NOW)

    def feedback(self, store, pending, verdict, key, reason=None):
        source = event(event_id=key, digest=key, project=pending.project,
                       session_id=pending.session_id, episode_id=pending.episode_id)
        store.put_event(source)
        receipt = {'verb': verdict, 'suggestion_id': pending.suggestion_id}
        kwargs = {}
        if reason is not None:
            receipt['reason'] = reason
            kwargs['reason'] = reason
        store.put_receipt(key, 'verified-host-submission', receipt)
        return apply_feedback(store, suggestion_id=pending.suggestion_id,
                              source_event_id=key, verdict=verdict, now=NOW, **kwargs)

    def claim(self, store, value, project, episode):
        return claim_application(store, lesson_id=value.lesson_id, version=value.version,
                                 session_id='session', episode_id=episode, project=str(project),
                                 context_match=True, permissions_ok=True)

    def test_single_rejection_keeps_confirmation_and_does_not_double_penalize(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'one')
            self.feedback(store, pending, 'accept', 'accept')
            result = self.feedback(store, pending, 'reject', 'reject')
            self.assertTrue(result.mature)
            self.assertTrue(store.confirmed(value.lesson_id, 1))
            self.assertAlmostEqual(result.confidence, 0.78)
            self.assertEqual((result.positives, result.negatives), (1, 0))
            self.assertEqual(result, self.feedback(store, pending, 'reject', 'repeat'))
            apply_feedback(store, suggestion_id=pending.suggestion_id,
                           source_event_id='repeat', verdict='reject', now=NOW)
            self.assertAlmostEqual(current_score(store, value).confidence, 0.78)

    def test_rejection_preserves_observational_maturity_and_successes(self):
        with self.state() as (root, a, b, store, value):
            for item in mature_samples():
                store.put_sample(item)
            pending = self.suggestion(store, value, a, 'one')
            result = self.feedback(store, pending, 'reject', 'reject')
            self.assertTrue(result.observational_mature)
            self.assertTrue(result.mature)
            self.assertEqual(result.successful_episodes, 5)
            self.assertAlmostEqual(result.confidence, 6 / 7 - 0.02)

    def test_rejection_blocks_current_episode_but_allows_a_future_matching_one(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            rejected = self.suggestion(store, value, a, 'rejected')
            self.feedback(store, rejected, 'reject', 'reject')
            self.assertTrue(self.claim(store, value, b, 'future'))
            self.assertFalse(self.claim(store, value, a, 'rejected'))
            # Changing a task fingerprint is not a new decision episode.
            other = self.suggestion(store, value, a, 'rejected', context='other')
            self.feedback(store, other, 'reject', 'again')
            self.assertAlmostEqual(current_score(store, value).confidence, 0.78)

    def test_repeated_independent_rejections_lower_confidence_and_acceptance_recovers(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, pending, 'accept', 'accept')
            for i, expected in enumerate((0.78, 0.76, 0.74)):
                pending = self.suggestion(store, value, a, f'rejected-{i}')
                result = self.feedback(store, pending, 'reject', f'reject-{i}')
                self.assertTrue(result.mature)
                self.assertAlmostEqual(result.confidence, expected)
            self.assertFalse(self.claim(store, value, a, 'future'))
            accepted = self.suggestion(store, value, a, 'accepted-again')
            recovered = self.feedback(store, accepted, 'accept', 'accept-again')
            self.assertAlmostEqual(recovered.confidence, 0.80)
            self.assertTrue(self.claim(store, value, a, 'future'))
            self.assertFalse(self.claim(store, value, a, 'rejected-0'))

    def test_explicit_exception_keeps_confidence_and_records_the_human_reason(self):
        self.assertIn('exception', VERDICTS)
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, pending, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'special')
            reason = 'This is generated code; keep the generator layout.'
            result = self.feedback(store, pending, 'exception', 'exception', reason=reason)
            self.assertTrue(result.mature)
            self.assertAlmostEqual(result.confidence, 0.80)
            self.assertFalse(self.claim(store, value, a, 'special'))
            self.assertTrue(self.claim(store, value, a, 'future'))
            record = store.application(value.lesson_id, 1, 'session', 'special')
            self.assertEqual(record['reason'], reason)

    def test_soft_rejection_cannot_be_reinterpreted_as_a_negative_sample(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'one')
            self.feedback(store, pending, 'accept', 'accept')
            self.feedback(store, pending, 'reject', 'reject')
            with self.assertRaises(ValueError):
                record_sample(store, sample(project=str(a), session_id='session',
                                           episode_id='one', source_event_id='reject',
                                           verdict='negative', outcome='unknown'))
            self.assertTrue(store.confirmed(value.lesson_id, 1))

    def test_penalty_and_current_decision_block_survive_restart_and_retention(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, pending, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'rejected')
            self.feedback(store, pending, 'reject', 'reject')
            maintain(root, now='2027-01-07T00:00:00Z')
            with Store(root) as reopened:
                result = current_score(reopened, value, now='2027-01-07T00:00:00Z')
                self.assertTrue(result.mature)
                self.assertAlmostEqual(result.confidence, 0.78)
                self.assertFalse(self.claim(reopened, value, a, 'rejected'))

    def test_exception_reason_is_bound_to_the_interactive_acknowledgement(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'special')
            reason = 'Generated modules use their generator layout.'
            # First show that the operational acknowledgement boundary still holds.
            with self.assertRaises(ValueError):
                confirm(store, suggestion_id=pending.suggestion_id, verdict='exception',
                        reason=reason, stream=io.StringIO('yes'), out=io.StringIO())
            preview = io.StringIO()
            result = confirm(store, suggestion_id=pending.suggestion_id, verdict='exception',
                             reason=reason, stream=SimulatedTerminal(
                                 f'NEBULA EXCEPTION {pending.suggestion_id}\n'), out=preview)
            self.assertAlmostEqual(result.confidence, 0.80)
            self.assertIn(reason, preview.getvalue())
            record = store.application(value.lesson_id, 1, 'session', 'special')
            self.assertEqual(store.receipt(record['source_event_id'])['reason'], reason)
            with self.assertRaises(ValueError):
                apply_feedback(store, suggestion_id=pending.suggestion_id,
                               source_event_id=record['source_event_id'], verdict='exception',
                               reason='A different reason', now=NOW)

    def test_cli_exception_reason_and_inspection(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'special')
            reason = 'Generated code uses a separate layout.'
            store.put_event(event(event_id='exception', digest='exception',
                                  session_id='session', episode_id='special', project=str(a)))
            store.put_receipt('exception', 'verified-host-submission',
                              {'verb': 'exception', 'suggestion_id': pending.suggestion_id,
                               'reason': reason})
            result = subprocess.run(
                [sys.executable, str(RUNTIME / 'scripts/nebula.py'), 'feedback',
                 '--root', str(root), '--suggestion', pending.suggestion_id,
                 '--source-event', 'exception', '--verdict', 'exception', '--reason', reason],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertAlmostEqual(json.loads(result.stdout)['confidence'], 0.80)
            result = subprocess.run(
                [sys.executable, str(RUNTIME / 'scripts/nebula.py'), 'inspect',
                 '--root', str(root), '--lesson', value.lesson_id], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['feedback'][0]['reason'], reason)

    def test_recall_exposes_explicit_exception_context_within_its_byte_budget(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, pending, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'special')
            self.feedback(store, pending, 'exception', 'exception', reason='Generated modules.')
            result = recall(store, project=str(a), query='module')
            self.assertEqual(result[0]['exception_feedback'][0]['reason'], 'Generated modules.')
            self.assertLessEqual(len(json.dumps(result).encode()), 8192)

    def test_invalid_exception_reason_does_not_change_confirmation_or_score(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            for i, reason in enumerate((None, '', '   ', 'x' * 513, 42)):
                pending = self.suggestion(store, value, a, f'bad-{i}')
                with self.subTest(reason=reason), self.assertRaises(ValueError):
                    self.feedback(store, pending, 'exception', f'bad-{i}', reason=reason)
                self.assertIsNone(store.application(value.lesson_id, 1, 'session', f'bad-{i}'))
                self.assertAlmostEqual(current_score(store, value).confidence, 0.80)

    def test_strong_feedback_after_rejection_still_revokes_confirmation(self):
        for verdict in ('correct', 'withdraw', 'disable'):
            with self.subTest(verdict=verdict), self.state() as (root, a, b, store, value):
                pending = self.suggestion(store, value, a, 'one')
                self.feedback(store, pending, 'accept', 'accept')
                self.feedback(store, pending, 'reject', 'reject')
                result = self.feedback(store, pending, verdict, 'strong')
                self.assertFalse(store.confirmed(value.lesson_id, 1))
                self.assertFalse(result.mature)
                self.assertFalse(self.claim(store, value, a, 'future'))

    def test_changed_lesson_version_does_not_inherit_rejection_penalties(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'one')
            self.feedback(store, pending, 'accept', 'accept')
            self.feedback(store, pending, 'reject', 'reject')
            draft = asdict(value)
            draft.update(action='Place modules in src/components.', evidence_ids=['accept'])
            changed = record_lesson(store, draft)
            self.assertEqual(changed.version, 2)
            result = current_score(store, changed)
            self.assertFalse(result.mature)
            self.assertAlmostEqual(result.confidence, 0.50)
            self.assertAlmostEqual(result.rejection_penalty, 0.0)

    def test_feedback_transaction_rolls_back_penalty_and_decision_block_together(self):
        import sqlite3
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'one')
            self.feedback(store, pending, 'accept', 'accept')
            store.connection.execute("CREATE TRIGGER fail_feedback BEFORE INSERT ON audit "
                                     "WHEN NEW.kind='feedback' BEGIN "
                                     "SELECT RAISE(ABORT,'interrupted feedback'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.feedback(store, pending, 'reject', 'reject')
            self.assertIsNone(store.application(value.lesson_id, 1, 'session', 'one'))
            self.assertAlmostEqual(current_score(store, value).confidence, 0.80)
            self.assertEqual(store.get_suggestion(pending.suggestion_id).status, 'accept')

    def test_corrupt_penalty_state_withholds_application(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'one')
            self.feedback(store, pending, 'accept', 'accept')
            store.set_meta('rejection-count:layout:1', 'not-an-integer')
            with self.assertRaises(StateUnavailable):
                self.claim(store, value, a, 'future')

    def test_many_rejections_keep_confidence_in_range(self):
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, pending, 'accept', 'accept')
            for i in range(51):
                pending = self.suggestion(store, value, a, f'rejected-{i}')
                result = self.feedback(store, pending, 'reject', f'reject-{i}')
            self.assertTrue(result.mature)
            self.assertEqual(result.confidence, 0.0)
            self.assertFalse(self.claim(store, value, a, 'future'))

    def test_later_rejection_retains_explicit_exception_reason_and_source(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'special')
            self.feedback(store, pending, 'exception', 'exception', reason='Generated modules.')
            self.feedback(store, pending, 'reject', 'reject')
            contexts = recall(store, project=str(a), query='module')[0].get('exception_feedback', [])
            self.assertTrue(contexts)
            self.assertEqual(contexts[0]['reason'], 'Generated modules.')
            history = store.feedback_history(value.lesson_id, 1)
            self.assertEqual({entry['feedback_verdict'] for entry in history}, {'reject', 'exception'})
            exception = next(entry for entry in history if entry['feedback_verdict'] == 'exception')
            self.assertEqual(exception['source_digest'], 'exception')
            maintain(root, now='2027-01-07T00:00:00Z')
            self.assertEqual(store.feedback_history(value.lesson_id, 1, exceptions_only=True)[0]['reason'],
                             'Generated modules.')

    def test_same_episode_exceptions_keep_their_own_project_and_reason(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            first = self.suggestion(store, value, a, 'special', context='A')
            self.feedback(store, first, 'exception', 'exception-A', reason='Reason A.')
            second = self.suggestion(store, value, b, 'special', context='B')
            self.feedback(store, second, 'exception', 'exception-B', reason='Reason B.')
            contexts = recall(store, project=str(b), query='module')[0]['exception_feedback']
            self.assertIn({'project': str(b), 'context_digest': 'B', 'reason': 'Reason B.'}, contexts)
            self.assertIn({'project': str(a), 'context_digest': 'A', 'reason': 'Reason A.'}, contexts)

    def test_exception_does_not_change_an_existing_claims_execution_project(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            self.assertTrue(self.claim(store, value, a, 'special'))
            pending = self.suggestion(store, value, b, 'special', context='B')
            self.feedback(store, pending, 'exception', 'exception', reason='Reason B.')
            application = store.application(value.lesson_id, 1, 'session', 'special')
            self.assertEqual(application['project'], str(a))
            self.assertEqual(application['status'], 'claimed')
            self.assertEqual(store.feedback_history(value.lesson_id, 1)[0]['project'], str(b))
            store.put_event(event(event_id='tool', digest='tool', project=str(a),
                                  origin='assistant', session_id='session', episode_id='special'))
            finish_application(store, lesson_id=value.lesson_id, version=1, session_id='session',
                               episode_id='special', outcome='unknown', source_event_ids=['tool'])

    def test_repeated_rejections_do_not_displace_an_explicit_exception(self):
        with self.state() as (root, a, b, store, value):
            accepted = self.suggestion(store, value, a, 'accepted')
            self.feedback(store, accepted, 'accept', 'accept')
            pending = self.suggestion(store, value, a, 'special')
            self.feedback(store, pending, 'exception', 'exception', reason='Generated modules.')
            for i in range(8):
                pending = self.suggestion(store, value, a, 'special', context=f'retry-{i}')
                self.feedback(store, pending, 'reject', f'reject-{i}')
            self.assertEqual(store.feedback_history(value.lesson_id, 1, exceptions_only=True)[0]['reason'],
                             'Generated modules.')
            self.assertAlmostEqual(current_score(store, value).confidence, 0.78)

    def test_updating_a_compact_exception_preserves_its_reason_and_source(self):
        from nebula.models import dump
        with self.state() as (root, a, b, store, value):
            pending = self.suggestion(store, value, a, 'special')
            self.feedback(store, pending, 'exception', 'exception', reason='Generated modules.')
            data = store.application(value.lesson_id, 1, 'session', 'special')
            for field in ('feedback_history', 'exception_history', 'feedback_project'):
                data.pop(field)
            store.connection.execute('UPDATE applications SET data=?', (dump(data),))
            self.assertEqual(store.feedback_history(value.lesson_id, 1, exceptions_only=True)[0]['reason'],
                             'Generated modules.')
            self.feedback(store, pending, 'reject', 'reject')
            history = store.feedback_history(value.lesson_id, 1, exceptions_only=True)
            self.assertTrue(history)
            self.assertEqual(history[0]['reason'], 'Generated modules.')
            self.assertEqual(history[0]['source_digest'], 'exception')
