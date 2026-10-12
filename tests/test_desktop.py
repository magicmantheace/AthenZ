"""Headless desktop service tests: no GUI, Ollama network or private data in Git."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from athenz.desktop import DesktopService, DesktopError, _validate_session
from athenz.experience import ExperienceStore


class FakeModel:
    model = 'qwen-local-test'
    def __init__(self, *_, **__):
        pass
    def generate(self, messages, **kwargs):
        return 'Synthetic model reply'


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)/'private'
        self.s=DesktopService(self.home)
        store=ExperienceStore(self.home)
        store.propose('preference','Synthetic approved preference',source='owner',approved=True)
        store.propose('identity','Synthetic unapproved secret',source='unknown')
        self.pending=store.list_items('identity','pending')[0]['id']
        store.close()

    def test_session_mode_validation_and_empty_history(self):
        self.assertEqual(self.s.history('desktop','agent'),[])
        for session,mode in [('../bad','agent'),('desktop','developer'),('','twin')]:
            with self.assertRaises(DesktopError):
                _validate_session(session,mode)
        with self.assertRaises(DesktopError):
            self.s.send('desktop','agent',' '*3)

    def test_successful_message_is_local_persisted_per_mode_session(self):
        with mock.patch('athenz.desktop.OllamaClient',FakeModel):
            r=self.s.send('work','agent','Synthetic question')
        self.assertEqual(r['reply'],'Synthetic model reply')
        self.assertIsInstance(r['reply_id'],int)
        history=self.s.history('work','agent')
        self.assertEqual([x['role'] for x in history],['user','assistant'])
        self.assertEqual(self.s.history('work','twin'),[])
        self.assertEqual(self.s.history('other','agent'),[])

    def test_model_failure_does_not_write_private_history(self):
        with mock.patch('athenz.desktop.OllamaClient',FakeModel), \
             mock.patch('athenz.desktop.answer',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                self.s.send('desktop','twin','not saved')
        self.assertEqual(self.s.history('desktop','twin'),[])

    def test_routing_change_discards_response_without_persist(self):
        with mock.patch('athenz.desktop.OllamaClient',FakeModel), \
             mock.patch('athenz.desktop.checked_active_tag',side_effect=[None,'changed']):
            with self.assertRaisesRegex(DesktopError,'changed during inference'):
                self.s.send('desktop','agent','question')
        self.assertEqual(self.s.history('desktop','agent'),[])

    def test_pending_never_auto_approves_and_requires_current_state(self):
        listed=self.s.pending()
        self.assertEqual(len(listed),1)
        self.assertEqual(listed[0]['id'],self.pending)
        with self.assertRaises(DesktopError):
            self.s.review('messages',self.pending,'approved')
        self.assertTrue(self.s.review('identity',self.pending,'approved',
            review_sha256=self.s.review_detail('identity',self.pending)['review_sha256']))
        self.assertEqual(self.s.pending(),[])
        with self.assertRaisesRegex(DesktopError,'changed since review'):
            self.s.review('identity',self.pending,'approved',review_sha256='0'*64)

    def test_full_review_requires_pending_and_stays_local(self):
        detail=self.s.review_detail('identity',self.pending)
        self.assertEqual(detail['text'],'Synthetic unapproved secret')
        self.s.review('identity',self.pending,'rejected',
            review_sha256=detail['review_sha256'])
        with self.assertRaisesRegex(DesktopError,'no longer pending'):
            self.s.review_detail('identity',self.pending)

    def test_feedback_creates_pending_pair_and_rejects_wrong_session(self):
        with mock.patch('athenz.desktop.OllamaClient',FakeModel):
            result=self.s.send('work','agent','Instruction')
        with self.assertRaisesRegex(DesktopError,'does not exist'):
            self.s.feedback('other','agent',result['reply_id'],'up')
        saved=self.s.feedback('work','agent',result['reply_id'],'down','Better correction')
        self.assertEqual(saved['training'],'pending-owner-review')
        candidates=[r for r in self.s.pending() if r['table']=='train_pairs']
        self.assertEqual(len(candidates),1)
        record=self.s.review_detail('train_pairs',candidates[0]['id'])
        self.assertEqual(record['ideal_answer'],'Better correction')
        self.assertEqual(record['status'],'pending')

    def test_tasks_are_read_only_projection(self):
        store=ExperienceStore(self.home)
        try:
            store.checkpoint('synthetic_task','Synth task',{'private':'not shown'},status='paused')
        finally:
            store.close()
        rows=self.s.tasks()
        entry=next(r for r in rows if r['task_key']=='synthetic_task')
        self.assertEqual(entry['status'],'paused')
        self.assertNotIn('private',str(rows))

    def test_review_episodes_and_reject_training_candidate(self):
        store=ExperienceStore(self.home)
        episode=store.observe('Synthetic code practice','Use tests',tags=['testing'],source='synthetic')
        store.add_message('session','agent','user','Synthetic instruction')
        response=store.add_message('session','agent','assistant','Synthetic reply')
        store.add_feedback(response,'up')
        candidate=store.list_items('train_pairs','pending')[0]['id']
        store.close()
        self.assertTrue(self.s.review('episodes',episode,'approved',
            review_sha256=self.s.review_detail('episodes',episode)['review_sha256']))
        self.assertTrue(self.s.review('train_pairs',candidate,'rejected',
            review_sha256=self.s.review_detail('train_pairs',candidate)['review_sha256']))
        self.assertFalse(any(x['table']=='episodes' for x in self.s.pending()))

    def test_review_requires_full_record_digest_and_rejects_stale_content(self):
        viewed = self.s.review_detail('identity', self.pending)
        with self.assertRaisesRegex(DesktopError, 'full record'):
            self.s.review('identity', self.pending, 'approved')
        store = ExperienceStore(self.home)
        try:
            with store.db:
                store.db.execute("UPDATE identity SET text='Synthetic changed fact' WHERE id=?",
                                 (self.pending,))
        finally:
            store.close()
        with self.assertRaisesRegex(DesktopError, 'changed after review'):
            self.s.review('identity', self.pending, 'approved',
                          review_sha256=viewed['review_sha256'])
        self.assertTrue(self.s.review('identity', self.pending, 'approved',
            review_sha256=self.s.review_detail('identity',self.pending)['review_sha256']))

    def test_review_digest_pins_provenance_and_is_not_reused(self):
        viewed = self.s.review_detail('identity', self.pending)
        store = ExperienceStore(self.home)
        try:
            with store.db:
                store.db.execute("UPDATE identity SET source_ref='new provenance' WHERE id=?",
                                 (self.pending,))
        finally:
            store.close()
        with self.assertRaisesRegex(DesktopError, 'changed after review'):
            self.s.review('identity', self.pending, 'rejected',
                          review_sha256=viewed['review_sha256'])
        self.s.review('identity', self.pending, 'rejected',
                      review_sha256=self.s.review_detail('identity', self.pending)['review_sha256'])
        with self.assertRaisesRegex(DesktopError, 'changed since review'):
            self.s.review('identity', self.pending, 'approved',
                          review_sha256=viewed['review_sha256'])

    def test_import_is_headless_and_cli_parser_does_not_spawn_window(self):
        from athenz.desktop import main
        with self.assertRaises(SystemExit) as ctx:
            main(['--help'])
        self.assertEqual(ctx.exception.code,0)

if __name__=='__main__':
    unittest.main()
