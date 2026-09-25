from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mac_bridge.batch_files import (
    BatchDelete,
    BatchEdit,
    BatchMkdir,
    BatchMove,
    BatchWrite,
    execute_batch,
    prepare_batch,
)
from mac_bridge.policy import MacError, Policy


class BatchFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / 'bridge'
        self.project = base / 'project'
        (self.root / '.state').mkdir(parents=True)
        self.project.mkdir()
        self.policy = Policy(self.root, self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_mixed_batch_and_recoverable_delete(self):
        existing = self.project / 'existing.txt'
        existing.write_text('alpha old omega', encoding='utf-8')
        moving = self.project / 'move.txt'
        moving.write_text('move me', encoding='utf-8')
        deleting = self.project / 'delete.txt'
        deleting.write_text('delete me', encoding='utf-8')

        operations = [
            BatchMkdir(op='mkdir', path='nested/path'),
            BatchWrite(op='write', path='nested/path/new.txt', content='created'),
            BatchEdit(op='edit', path='existing.txt', old_string='old', new_string='new'),
            BatchMove(op='move', source='move.txt', destination='nested/path/moved.txt'),
            BatchDelete(op='delete', path='delete.txt'),
        ]
        plan = prepare_batch(self.policy, operations)
        report, failed = execute_batch(self.policy, plan)

        self.assertFalse(failed, report)
        self.assertTrue(report['ok'])
        self.assertEqual((self.project / 'nested/path/new.txt').read_text(), 'created')
        self.assertEqual(existing.read_text(), 'alpha new omega')
        self.assertFalse(moving.exists())
        self.assertEqual((self.project / 'nested/path/moved.txt').read_text(), 'move me')
        self.assertFalse(deleting.exists())
        self.assertEqual(report['recoverable_deletes'], 1)
        self.assertGreaterEqual(report['backups_created'], 1)
        trash = list((self.root / '.state/batch-trash').rglob('delete.txt'))
        self.assertEqual(len(trash), 1)
        self.assertEqual(trash[0].read_text(), 'delete me')

    def test_multiple_edits_same_file_apply_sequentially(self):
        target = self.project / 'a.txt'
        target.write_text('one two three', encoding='utf-8')
        operations = [
            BatchEdit(op='edit', path='a.txt', old_string='one', new_string='ONE'),
            BatchEdit(op='edit', path='a.txt', old_string='two', new_string='TWO'),
        ]
        plan = prepare_batch(self.policy, operations)
        report, failed = execute_batch(self.policy, plan)
        self.assertFalse(failed, report)
        self.assertEqual(target.read_text(), 'ONE TWO three')

    def test_failure_rolls_back_prior_changes(self):
        first = self.project / 'first.txt'
        second = self.project / 'second.txt'
        first.write_text('before-1', encoding='utf-8')
        second.write_text('before-2', encoding='utf-8')
        plan = prepare_batch(self.policy, [
            BatchWrite(op='write', path='first.txt', content='after-1'),
            BatchWrite(op='write', path='second.txt', content='after-2'),
        ])

        from mac_bridge import batch_files
        real_write = batch_files._write_text
        calls = 0

        def flaky(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('synthetic write failure')
            return real_write(path, content)

        with mock.patch.object(batch_files, '_write_text', side_effect=flaky):
            report, failed = execute_batch(self.policy, plan)

        self.assertTrue(failed)
        self.assertTrue(report['rollback_performed'])
        self.assertEqual(report['rollback_failures'], [])
        self.assertEqual(first.read_text(), 'before-1')
        self.assertEqual(second.read_text(), 'before-2')

    def test_mixed_failure_rolls_back_move_delete_and_created_directories(self):
        moving = self.project / 'moving.txt'
        deleting = self.project / 'deleting.txt'
        target = self.project / 'target.txt'
        moving.write_text('move-original', encoding='utf-8')
        deleting.write_text('delete-original', encoding='utf-8')
        target.write_text('target-original', encoding='utf-8')
        plan = prepare_batch(self.policy, [
            BatchMkdir(op='mkdir', path='created'),
            BatchMove(op='move', source='moving.txt', destination='created/moved.txt'),
            BatchDelete(op='delete', path='deleting.txt'),
            BatchWrite(op='write', path='target.txt', content='target-new'),
        ])

        from mac_bridge import batch_files
        with mock.patch.object(batch_files, '_write_text', side_effect=OSError('synthetic final failure')):
            report, failed = execute_batch(self.policy, plan)

        self.assertTrue(failed)
        self.assertEqual(report['rollback_failures'], [])
        self.assertEqual(moving.read_text(), 'move-original')
        self.assertEqual(deleting.read_text(), 'delete-original')
        self.assertEqual(target.read_text(), 'target-original')
        self.assertFalse((self.project / 'created').exists())

    def test_preflight_rejects_ambiguous_edit_move_overwrite_and_directory_delete(self):
        (self.project / 'ambiguous.txt').write_text('x x', encoding='utf-8')
        with self.assertRaisesRegex(MacError, 'exactly once'):
            prepare_batch(self.policy, [
                BatchEdit(op='edit', path='ambiguous.txt', old_string='x', new_string='y')
            ])

        (self.project / 'source.txt').write_text('s', encoding='utf-8')
        (self.project / 'destination.txt').write_text('d', encoding='utf-8')
        with self.assertRaisesRegex(MacError, 'destination already exists'):
            prepare_batch(self.policy, [
                BatchMove(op='move', source='source.txt', destination='destination.txt')
            ])

        directory = self.project / 'dir'
        directory.mkdir()
        with self.assertRaisesRegex(MacError, 'regular files'):
            prepare_batch(self.policy, [BatchDelete(op='delete', path='dir')])

    def test_create_only_and_project_guardrails(self):
        (self.project / 'exists.txt').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(MacError, 'create_only'):
            prepare_batch(self.policy, [
                BatchWrite(op='write', path='exists.txt', content='new', create_only=True)
            ])
        with self.assertRaisesRegex(MacError, 'outside'):
            prepare_batch(self.policy, [
                BatchWrite(op='write', path='../outside.txt', content='no')
            ])

    def test_changed_path_after_preflight_executes_nothing(self):
        target = self.project / 'watched.txt'
        target.write_text('before', encoding='utf-8')
        plan = prepare_batch(self.policy, [
            BatchWrite(op='write', path='watched.txt', content='after')
        ])
        target.write_text('user edit', encoding='utf-8')
        report, failed = execute_batch(self.policy, plan)
        self.assertTrue(failed)
        self.assertIn('changed after preflight', report['error'])
        self.assertEqual(target.read_text(), 'user edit')


if __name__ == '__main__':
    unittest.main()
