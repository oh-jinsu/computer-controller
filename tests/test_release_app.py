"""Release lifecycle unit tests. No real updater installation or user Keychain access."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from mac_bridge.activity import Activity, exclusive_lock, heartbeat_safe
from mac_bridge.app_control import configure, import_legacy, status, environment
from mac_bridge.policy import MacError, Policy, private_write


class ReleaseAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name).resolve()
        self.data = self.parent / 'app-data'; self.data.mkdir()
        self.workspace = self.parent / 'dev'; self.workspace.mkdir()
        self.source = self.workspace / 'mac-bridge'; self.source.mkdir()
        self.old = self.source / '.state'; self.old.mkdir()
        (self.old / 'settings.json').write_text(json.dumps({'tunnel_id': 'tunnel_release12345678', 'mcp_command': '/OLD/DO/NOT/EXECUTE', 'api_key': 'NEVER_COPY'}))
        (self.old / 'mac-settings.json').write_text(json.dumps({'workspace': str(self.workspace)}))
        (self.old / 'approval-settings.json').write_text('{"schema":1,"mode":"always"}')

    def tearDown(self): self.tmp.cleanup()

    def test_migration_preserves_approval_without_copying_secret_or_command(self):
        before = (self.old / 'settings.json').read_bytes()
        result = import_legacy(self.source, self.data)
        self.assertEqual(result['approval_mode'], 'always')
        self.assertEqual((self.old / 'settings.json').read_bytes(), before)
        saved = (self.data / '.state/settings.json').read_text()
        self.assertNotIn('NEVER_COPY', saved); self.assertNotIn('/OLD/', saved)
        self.assertTrue(status(self.data)['configured'])

    def test_migration_refuses_overwrite(self):
        import_legacy(self.source, self.data)
        with self.assertRaises(MacError): import_legacy(self.source, self.data)

    def test_migration_keeps_paused_state(self):
        (self.old / 'MAC_PAUSED').write_text('paused')
        import_legacy(self.source, self.data)
        self.assertTrue(status(self.data)['paused'])

    def test_migration_rejects_invalid_mode_before_writing(self):
        (self.old / 'approval-settings.json').write_text('{"schema":1,"mode":"wrong"}')
        with self.assertRaises(MacError): import_legacy(self.source, self.data)
        self.assertFalse((self.data / '.state/settings.json').exists())

    def test_source_is_editable_with_independent_data_root(self):
        file = self.source / 'example.py'; file.write_text('old')
        policy = Policy(self.data, self.workspace)
        allowed = policy.path(str(file), file_only=True)
        allowed.write_text('new')
        self.assertEqual(file.read_text(), 'new')

    def test_build_output_protected_without_blocking_source(self):
        policy = Policy(self.data, self.workspace)
        bundle = self.source / 'dist/Computer Controller.app'
        policy.protected_roots += (bundle,)
        with self.assertRaises(MacError): policy.path(str(bundle / 'Contents/Resources/engine/server.py'))
        self.assertEqual(policy.path(str(self.source / 'README.md')), self.source / 'README.md')

    def test_sensitive_data_not_exposed(self):
        policy = Policy(self.data, self.workspace)
        with self.assertRaises(MacError): policy.path(str(self.data / '.state/settings.json'))
        with self.assertRaises(MacError): policy.path(str(self.source / '.env'))

    def test_no_settings_is_unconfigured_not_an_error(self):
        self.assertFalse(status(self.data)['configured'])

    def test_configure_key_not_serialized(self):
        with mock.patch('keyring.set_password') as save:
            configure(self.data, {'tunnel_id': 'tunnel_release12345678', 'workspace': str(self.workspace), 'runtime_key': 'test-key', 'approval_mode': 'always', 'browser_mode': 'personal'})
        save.assert_called_once()
        self.assertNotIn('test-key', ''.join(p.read_text() for p in (self.data / '.state').glob('*.json')))

    def test_empty_key_reuses_keychain_and_new_install_defaults_always(self):
        with mock.patch('keyring.set_password') as save:
            configure(self.data, {'tunnel_id': 'tunnel_release12345678', 'workspace': str(self.workspace), 'runtime_key': ''})
        save.assert_not_called()
        self.assertEqual(status(self.data)['approval_mode'], 'always')

    def test_unknown_settings_rejected(self):
        with self.assertRaises(MacError): configure(self.data, {'shell_command': 'x'})

    def test_environment_does_not_inherit_runtime_secrets(self):
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'x', 'GH_TOKEN': 'y', 'NODE_OPTIONS': 'z', 'DYLD_INSERT_LIBRARIES': 'bad'}):
            env = environment()
        for name in ['OPENAI_API_KEY', 'GH_TOKEN', 'NODE_OPTIONS', 'DYLD_INSERT_LIBRARIES']:
            self.assertNotIn(name, env)
        self.assertNotIn('/opt/homebrew', env['PATH'])

    def test_lock_refuses_two_servers(self):
        with exclusive_lock(self.data / '.state/launch.lock'):
            with self.assertRaises(MacError):
                with exclusive_lock(self.data / '.state/launch.lock'): pass

    def test_activity_drains_new_work_but_allows_cleanup(self):
        activity = Activity(self.data)
        private_write(activity.drain, b'1')
        with self.assertRaises(MacError): activity.enter('start_process')
        self.assertEqual(activity.count, 0)
        activity.enter('browser_close'); activity.leave()
        self.assertEqual(activity.count, 0)

    def test_busy_heartbeat_never_safe(self):
        activity = Activity(self.data); activity.enter('browser_click')
        private_write(activity.drain, b'1'); activity.write(external_busy=False)
        value = json.loads(activity.heartbeat.read_text()); value['last_operation'] = time.time()-100
        self.assertFalse(heartbeat_safe(value, now=time.time()))

    def test_idle_requires_fresh_draining_heartbeat_and_quiet_time(self):
        value = {'schema': 1, 'pid': 100, 'busy': False, 'draining': True, 'written_at': 200, 'last_operation': 150}
        self.assertTrue(heartbeat_safe(value, now=201))
        for key, new in [('written_at', 0), ('written_at', 999), ('last_operation', 198), ('draining', False), ('busy', True), ('pid', '100')]:
            self.assertFalse(heartbeat_safe({**value, key: new}, now=201), key)

    def test_missing_or_invalid_heartbeat_not_safe(self):
        for value in [None, {}, [], {'schema': 1}]: self.assertFalse(heartbeat_safe(value, now=100))

    def test_external_session_blocks_update(self):
        activity = Activity(self.data); private_write(activity.drain, b'1')
        activity.last_operation = time.time()-100
        activity.write(external_busy=True)
        self.assertFalse(heartbeat_safe(json.loads(activity.heartbeat.read_text()), now=time.time()))

    def test_development_server_does_not_write_release_heartbeat(self):
        activity = Activity(self.data, enabled=False)
        activity.enter('read'); activity.leave(); activity.write(external_busy=True)
        self.assertFalse(activity.heartbeat.exists())

    def test_finish_removes_only_own_heartbeat(self):
        activity = Activity(self.data); activity.write(external_busy=False)
        activity.finish(); self.assertFalse(activity.heartbeat.exists())
        private_write(activity.heartbeat, b'{"pid":-100}')
        activity.finish(); self.assertTrue(activity.heartbeat.exists())

if __name__ == '__main__': unittest.main()
