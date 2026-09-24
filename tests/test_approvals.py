"""Persistent approval configuration; filesystem real, launch/tunnel integration mocked."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mac_bridge.approvals import approval_mode, set_approval_mode, validate_mode
from mac_bridge import local
from mac_bridge.policy import MacError, Policy


class ApprovalSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'bridge'
        self.project = self.root.parent / 'project'
        (self.root / '.state').mkdir(parents=True)
        self.project.mkdir()
        self.workspace = self.root / '.state/mac-settings.json'
        self.workspace.write_text(json.dumps({'workspace': str(self.project), 'keep': 42}))
        self.tunnel = self.root / '.state/settings.json'
        self.tunnel.write_text('{"tunnel_id": "tunnel_12345678", "keep": true}')
        self.path = self.root / '.state/approval-settings.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_install_default_always_does_not_create_settings(self):
        self.assertEqual(approval_mode(self.root), 'always')
        self.assertFalse(self.path.exists())

    def test_always_persists_without_scope_or_expiration(self):
        set_approval_mode(self.root, 'always')
        self.assertEqual(json.loads(self.path.read_text()), {'schema': 1, 'mode': 'always'})
        self.assertEqual(approval_mode(Path(str(self.root))), 'always')
        with mock.patch('time.time', return_value=999999999999):
            self.assertEqual(approval_mode(self.root), 'always')

    def test_revoke_to_ask(self):
        set_approval_mode(self.root, 'always')
        set_approval_mode(self.root, 'ask')
        self.assertEqual(approval_mode(self.root), 'ask')

    def test_unrelated_settings_byte_identical(self):
        before = self.workspace.read_bytes(), self.tunnel.read_bytes()
        set_approval_mode(self.root, 'always')
        self.assertEqual(before, (self.workspace.read_bytes(), self.tunnel.read_bytes()))

    def test_does_not_resume_pause(self):
        p = Policy(self.root, self.project)
        p.pause()
        set_approval_mode(self.root, 'always')
        with self.assertRaises(MacError):
            p.require_active()

    def test_setting_and_audit_are_private(self):
        set_approval_mode(self.root, 'always')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        rows = Policy(self.root, self.project).history()
        self.assertEqual(rows[-1]['state'], 'saved_always')
        self.assertNotIn(str(self.project), json.dumps(rows))

    def test_repeated_choice_is_noop(self):
        set_approval_mode(self.root, 'always')
        before = self.path.read_bytes(), (self.root / '.state/mac-audit.jsonl').read_bytes()
        set_approval_mode(self.root, 'always')
        self.assertEqual(before, (self.path.read_bytes(), (self.root / '.state/mac-audit.jsonl').read_bytes()))

    def test_bad_modes_refused(self):
        for mode in (None, True, 1, {}, [], 'yes', 'ALWAYS', 'always '):
            with self.subTest(mode=mode), self.assertRaises(MacError):
                validate_mode(mode)
        self.assertFalse(self.path.exists())

    def test_corrupt_unknown_or_missing_schema_fails_closed(self):
        for text in ('not json', '[]', '{}', '{"schema":1}',
                     '{"schema":2,"mode":"always"}', '{"schema":true,"mode":"always"}',
                     '{"schema":1,"mode":true}', '{"schema":1,"mode":"trust"}'):
            self.path.write_text(text)
            with self.subTest(text=text), self.assertRaises(MacError):
                approval_mode(self.root)

    def test_oversized_settings_refused(self):
        self.path.write_text(' ' * 16385)
        with self.assertRaises(MacError):
            approval_mode(self.root)

    def test_symlink_settings_refused_even_when_dangling(self):
        external = self.root.parent / 'external.json'
        for exists in (False, True):
            if exists:
                external.write_text('{"schema":1,"mode":"always"}')
            self.path.symlink_to(external)
            with self.assertRaises(MacError):
                approval_mode(self.root)
            with self.assertRaises(MacError):
                set_approval_mode(self.root, 'always')
            self.path.unlink()

    def test_symlink_state_refused(self):
        state = self.root / '.state'
        state.rename(self.root / 'moved')
        state.symlink_to(self.root / 'moved', target_is_directory=True)
        with self.assertRaises(MacError):
            approval_mode(self.root)

    def test_environment_does_not_override_default(self):
        with mock.patch.dict(os.environ, {'MAC_BRIDGE_APPROVAL_MODE': 'ask', 'AUTO_APPROVE': 'false'}):
            self.assertEqual(approval_mode(self.root), 'always')

    def test_failed_save_keeps_prior_choice(self):
        set_approval_mode(self.root, 'always')
        with mock.patch('mac_bridge.approvals.private_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                set_approval_mode(self.root, 'ask')
        self.assertEqual(approval_mode(self.root), 'always')

    def test_start_flag_routes_explicit_choice(self):
        with mock.patch.object(local.sys, 'platform', 'darwin'), \
             mock.patch.object(local.sys, 'argv', ['local', 'start', '--approval-mode', 'always']), \
             mock.patch.object(local, 'start', return_value=0) as start:
            self.assertEqual(local.main(), 0)
            self.assertEqual(start.call_args.kwargs['selected_approval_mode'], 'always')

    def test_cli_can_show_or_set_without_tunnel_start(self):
        with mock.patch.object(local, 'ROOT', self.root), \
             mock.patch.object(local.sys, 'platform', 'darwin'), \
             mock.patch('builtins.print'), mock.patch.object(local, 'start') as start:
            for args in (['approval', '--mode', 'always'], ['approval']):
                with mock.patch.object(local.sys, 'argv', ['local', *args]):
                    self.assertEqual(local.main(), 0)
            start.assert_not_called()
            self.assertEqual(approval_mode(self.root), 'always')

    def test_flag_not_accepted_for_other_actions(self):
        for args in (['pause', '--approval-mode', 'always'], ['start', '--mode', 'always']):
            with mock.patch.object(local.sys, 'argv', ['local', *args]), \
                 mock.patch('sys.stderr'), self.assertRaises(SystemExit) as caught:
                local.main()
            self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
