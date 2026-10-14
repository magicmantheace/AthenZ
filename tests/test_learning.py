import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from athenz.chat import answer, main as chat_main, OllamaClient
from athenz.cli import main, private_export
from athenz.importers import parse_chatgpt_export, import_samples
from athenz.learning import LearningStore
from athenz.prompting import build_messages


class StubModel:
    def __init__(self, text='answer'):
        self.text = text
        self.calls = []
    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return self.text


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'private'
        self.store = LearningStore(self.home)
        self.addCleanup(self.store.close)

    def test_approval_gate_training_and_forget_cascade(self):
        self.store.add_message('s', 'agent', 'user', 'What should I do?')
        rid = self.store.add_message('s', 'agent', 'assistant', 'An imperfect answer')
        fid = self.store.add_feedback(rid, 'down', 'An owner-approved correction')
        rows = self.store.list_items('train_pairs')
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertEqual(self.store.approved_training_pairs(), [])
        self.assertTrue(self.store.set_review('train_pairs', rows[0]['id'], 'approved'))
        self.assertEqual(self.store.approved_training_pairs()[0]['output'], 'An owner-approved correction')
        self.assertTrue(self.store.forget_runtime('feedback', fid))
        self.assertEqual(self.store.list_items('train_pairs'), [])

    def test_session_modes_are_separate_and_survive_restart(self):
        self.store.add_message('same', 'twin', 'user', 'Twin private text')
        self.store.add_message('same', 'agent', 'user', 'Agent private text')
        reopened = LearningStore(self.home)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.conversation('same', 'twin')), 1)
        self.assertNotIn('Agent private text', str(reopened.conversation('same', 'twin')))
        self.assertEqual(reopened.delete_session('same'), 2)
        self.assertEqual(reopened.conversation('same', 'agent'), [])

    def test_only_owner_authored_export_samples_and_import_confirm(self):
        path = self.root / 'conversations.json'
        path.write_text(json.dumps([{'mapping': {
            'u': {'message': {'author': {'role': 'user'}, 'create_time': 8,
                'content': {'content_type': 'text', 'parts': ['A personal writing sample of sufficient length to train my style.']}}},
            'a': {'message': {'author': {'role': 'assistant'}, 'create_time': 9,
                'content': {'content_type': 'text', 'parts': ['Assistant-generated text should never get imported into the owner dataset.']}}}
        }}]), encoding='utf-8')
        main(['--home', str(self.home), 'import-chatgpt', str(path), '--source-ref', 'test-export'])
        self.assertEqual(self.store.list_items('writing_samples'), [])
        samples = parse_chatgpt_export(path)
        self.assertEqual(len(samples), 1)
        self.assertEqual(import_samples(self.store, samples, 'chatgpt:export', 'test-export'), 1)
        self.assertEqual(import_samples(self.store, samples, 'chatgpt:export', 'test-export'), 0)
        self.assertEqual(self.store.list_items('writing_samples')[0]['status'], 'pending')
        self.assertNotIn(samples[0], str(build_messages(self.store, 'Hi', mode='twin')))
        self.assertTrue(self.store.set_review('writing_samples', 1, 'approved'))
        self.assertEqual(self.store.purge_source('chatgpt:export', 'test-export')['writing_samples'], 1)

    def test_failing_experience_cannot_become_procedural_prompt(self):
        pid = self.store.new_proposal('/fake', 'Synthetic task', [{'path': 'x.py'}], 'model proposed')
        self.store.update_proposal(pid, 'proposed', 'applied')
        tid = self.store.record_test(pid, 'test-command', 1, 'Failure', 'hash-files', 'Failed lesson')
        self.assertEqual(tid, 1)
        eid = self.store.list_items('experiences')[0]['id']
        with self.assertRaises(ValueError):
            self.store.set_review('experiences', eid, 'approved')
        self.assertNotIn('Failed lesson', str(build_messages(self.store, 'Synthetic task lesson', 'agent')))
        self.store.record_test(pid, 'test-command', 0, 'PASS', 'hash-files', 'Owner reviewed valid lesson')
        eid = self.store.list_items('experiences')[0]['id']
        self.store.set_review('experiences', eid, 'approved')
        self.assertIn('Owner reviewed valid lesson', str(build_messages(self.store, 'Synthetic task lesson', 'agent')))
        self.assertNotIn('Owner reviewed valid lesson', str(build_messages(self.store, 'Synthetic task lesson', 'twin')))
        self.store.forget_runtime('proposals', pid)
        self.assertNotIn('Owner reviewed valid lesson', str(build_messages(self.store, 'Synthetic task lesson', 'agent')))

    def test_superseded_and_failed_tests_revoke_procedures(self):
        pid = self.store.new_proposal('/fake', 'Synthetic task', [{'path': 'x.py'}], 'proposed')
        self.store.update_proposal(pid, 'proposed', 'applied')
        self.store.record_test(pid, 'compile', 0, 'pass', 'files-hash', 'First passed')
        e1 = self.store.list_items('experiences')[0]['id']
        self.store.record_test(pid, 'unittest', 0, 'pass', 'files-hash', 'More thorough passed')
        with self.assertRaises(ValueError):
            self.store.set_review('experiences', e1, 'approved')
        self.store.set_review('experiences', self.store.list_items('experiences')[0]['id'], 'approved')
        self.store.record_test(pid, 'unittest', 1, 'failure', 'files-hash', 'Failure observed')
        self.assertEqual(self.store.approved_experiences(), [])

    def test_private_exports_refuse_git_and_refuse_overwrite(self):
        gitroot = self.root / 'project'
        gitroot.mkdir()
        (gitroot / '.git').mkdir()
        with self.assertRaises(ValueError):
            private_export(gitroot / 'train.json', [{'sensitive': 'data'}])
        outside = self.root / 'training.json'
        private_export(outside, self.store.approved_training_pairs())
        with self.assertRaises(FileExistsError):
            private_export(outside, {})

    def test_chat_response_uses_persistent_session_history(self):
        self.store.add_message('one', 'agent', 'user', 'A previous question')
        self.store.add_message('one', 'agent', 'assistant', 'A previous answer')
        stub = StubModel()
        got = answer(self.store, stub, 'New question', 'agent', self.store.conversation('one', 'agent'))
        self.assertEqual(got, 'answer')
        self.assertIn('A previous answer', str(stub.calls))

    def test_v1_database_is_migrated_without_deleting_owner_data(self):
        # Build the historical v1 schema using its actual SQL to test upgrade.
        original = self.root / 'old' / 'identity.sqlite3'
        original.parent.mkdir()
        db = sqlite3.connect(original)
        db.executescript('''
        CREATE TABLE identity (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL,
            source TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE identity_revisions (id INTEGER PRIMARY KEY,identity_id INTEGER NOT NULL,
            prior_text TEXT NOT NULL,new_text TEXT NOT NULL,reason TEXT NOT NULL,changed_at TEXT NOT NULL);
        CREATE TABLE decisions (id INTEGER PRIMARY KEY,scenario TEXT NOT NULL,choice TEXT NOT NULL,
            rationale TEXT NOT NULL, exception TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,
            source_ref TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE writing_samples (id INTEGER PRIMARY KEY,text TEXT NOT NULL,source TEXT NOT NULL,
            source_ref TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE TABLE events (id INTEGER PRIMARY KEY,operation TEXT NOT NULL,subject_type TEXT NOT NULL,
            subject_id INTEGER,created_at TEXT NOT NULL);
        INSERT INTO identity(kind,text,source,confidence,status,created_at,updated_at)
            VALUES ('value','retain me','owner',1,'approved','t','t');
        PRAGMA user_version=1;
        ''')
        db.close()
        upgraded = LearningStore(original.parent)
        self.addCleanup(upgraded.close)
        self.assertEqual(upgraded.db.execute('PRAGMA user_version').fetchone()[0], 6)
        self.assertEqual(upgraded.context()['identity'][0]['text'], 'retain me')
        self.assertEqual(upgraded.conversation('session', 'agent'), [])


if __name__ == '__main__':
    unittest.main()
