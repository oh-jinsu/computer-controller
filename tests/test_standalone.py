"""Standalone/migration tests. Tunnel commands and Keychain are mocked, not real integrations."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mac_bridge import local
from mac_bridge.migration import migrate_settings, read_settings, valid_tunnel_id, valid_workspace
from mac_bridge.policy import MacError

ROOT = Path(__file__).resolve().parents[1]


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name).resolve()
        self.root = self.parent / 'new checkout with spaces'
        self.old = self.parent / 'old scene-bridge'
        self.project = self.parent / 'project'
        for d in [self.root, self.old / '.state', self.project]:
            d.mkdir(parents=True)
        self.config = {'tunnel_id': 'tunnel_test12345678', 'profile': 'scene-bridge-old',
                       'initialized': True, 'mcp_command': '/OLD/python /OLD/run_server.py',
                       'api_key': 'DO_NOT_COPY_THIS_SENTINEL'}
        (self.old / '.state/settings.json').write_text(json.dumps(self.config))
        (self.old / '.state/mac-settings.json').write_text(json.dumps({'workspace': str(self.project)}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrates_only_non_secret_settings(self):
        result = migrate_settings(self.old, self.root)
        cfg = read_settings(self.root / '.state/settings.json')
        self.assertEqual(cfg, {'tunnel_id': self.config['tunnel_id'], 'initialized': False, 'schema': 1})
        self.assertTrue(result['workspace_imported'])
        self.assertEqual(read_settings(self.root / '.state/mac-settings.json')['workspace'], str(self.project))
        raw = ''.join(p.read_text() for p in (self.root / '.state').glob('*.json'))
        self.assertNotIn('DO_NOT_COPY_THIS_SENTINEL', raw)
        self.assertNotIn('/OLD/', raw)

    def test_source_unchanged(self):
        before = {p.name: p.read_bytes() for p in (self.old / '.state').iterdir()}
        migrate_settings(self.old, self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.old / '.state').iterdir()})

    def test_old_folder_not_needed_after_import(self):
        migrate_settings(self.old, self.root)
        shutil.rmtree(self.old)
        with mock.patch.object(local.subprocess, 'run') as run:
            saved, changed = local.bind_profile(self.root, read_settings(self.root / '.state/settings.json'),
                                                '/bin/tunnel-client', {'CONTROL_PLANE_API_KEY': 'NOT_PERSISTED'})
        self.assertTrue(changed)
        self.assertEqual(saved['tunnel_id'], self.config['tunnel_id'])
        self.assertIn(str(self.root / 'run_server.py'), shlex.split(saved['mcp_command']))
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('NOT_PERSISTED', (self.root / '.state/settings.json').read_text())

    def test_original_video_only_settings_supported(self):
        (self.old / '.state/mac-settings.json').unlink()
        result = migrate_settings(self.old, self.root)
        self.assertFalse(result['workspace_imported'])
        self.assertFalse((self.root / '.state/mac-settings.json').exists())

    def test_never_overwrites_destination_settings(self):
        migrate_settings(self.old, self.root)
        path = self.root / '.state/settings.json'
        before = path.read_bytes()
        with self.assertRaises(MacError):
            migrate_settings(self.old, self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_never_overwrites_existing_workspace(self):
        (self.root / '.state').mkdir()
        path = self.root / '.state/mac-settings.json'
        path.write_text('{"keep": true}')
        with self.assertRaises(MacError):
            migrate_settings(self.old, self.root)
        self.assertEqual(path.read_text(), '{"keep": true}')

    def test_symlinked_source_settings_rejected(self):
        path = self.old / '.state/settings.json'
        data = path.read_bytes()
        path.unlink()
        external = self.parent / 'settings.json'
        external.write_bytes(data)
        path.symlink_to(external)
        with self.assertRaises(MacError):
            migrate_settings(self.old, self.root)

    def test_symlinked_source_state_rejected(self):
        (self.old / '.state').rename(self.old / 'moved')
        (self.old / '.state').symlink_to(self.old / 'moved', target_is_directory=True)
        with self.assertRaises(MacError):
            migrate_settings(self.old, self.root)

    def test_bad_json_rejected(self):
        p = self.old / '.state/settings.json'
        for text in ['[]', 'null', '{} garbage']:
            p.write_text(text)
            with self.assertRaises(MacError):
                read_settings(p)

    def test_invalid_id_rejected(self):
        for value in ['', None, 12, 'another_name', 'tunnel_short', 'tunnel_12345678\n']:
            with self.assertRaises(MacError):
                valid_tunnel_id(value)

    def test_home_and_filesystem_workspace_rejected(self):
        for value in [str(Path.home()), '/', str(self.root)]:
            with self.assertRaises(MacError):
                valid_workspace(self.root, value)

    def test_development_parent_permitted(self):
        self.assertEqual(valid_workspace(self.root, str(self.parent)), self.parent)

    def test_profile_rebind_keeps_tunnel_and_venv_path(self):
        migrate_settings(self.old, self.root)
        cfg = read_settings(self.root / '.state/settings.json')
        interpreter = str(self.root / '.venv/bin/python')
        with mock.patch.object(local.sys, 'executable', interpreter), mock.patch.object(local.subprocess, 'run') as run:
            saved, changed = local.bind_profile(self.root, cfg, '/bin/tunnel-client', {'CONTROL_PLANE_API_KEY': 'NO_LOG'})
        self.assertTrue(changed)
        self.assertEqual(shlex.split(saved['mcp_command']), [interpreter, str(self.root / 'run_server.py')])
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv[argv.index('--tunnel-id') + 1], self.config['tunnel_id'])
        self.assertNotIn('NO_LOG', repr(argv))
        self.assertTrue(saved['profile'].startswith('mac-bridge-'))

    def test_profile_unchanged_on_normal_restart(self):
        cfg = {'initialized': True, 'tunnel_id': self.config['tunnel_id'],
               'profile': 'mac-bridge-123456789abc',
               'mcp_command': shlex.join([sys.executable, str(self.root / 'run_server.py')])}
        with mock.patch.object(local.subprocess, 'run') as run:
            result, changed = local.bind_profile(self.root, cfg, '/bin/tunnel-client', {})
        self.assertFalse(changed)
        run.assert_not_called()

    def test_failed_doctor_does_not_persist_rebinding(self):
        migrate_settings(self.old, self.root)
        p = self.root / '.state/settings.json'
        before = p.read_bytes()
        with mock.patch.object(local.subprocess, 'run', side_effect=[None, subprocess.CalledProcessError(1, 'doctor')]):
            with self.assertRaises(subprocess.CalledProcessError):
                local.bind_profile(self.root, read_settings(p), '/bin/tunnel-client', {})
        self.assertEqual(before, p.read_bytes())

    def test_same_checkout_cannot_start_twice(self):
        with local.launch_lock(self.root):
            with self.assertRaises(MacError):
                with local.launch_lock(self.root):
                    pass

    def test_legacy_keychain_service_preserved(self):
        self.assertEqual(local.SERVICE, 'scene-bridge-tunnel')

    def test_git_ignores_state_media_and_runtime(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        shutil.copy2(ROOT / '.gitignore', self.root / '.gitignore')
        protected = ['.state/settings.json', '.state/mac-settings.json', '.state/mac-audit.jsonl',
                     '.runtime/desktop-commander/node_modules/a.js', '.venv/bin/python',
                     'input/private.mp4', 'output/abc/frame.jpg', '.env', 'secret.pem']
        for name in protected:
            proc = subprocess.run(['git', '-C', str(self.root), 'check-ignore', '-q', name])
            self.assertEqual(proc.returncode, 0, name)
        proc = subprocess.run(['git', '-C', str(self.root), 'check-ignore', '-q', 'input/README.txt'])
        self.assertEqual(proc.returncode, 1)

    def test_standalone_tree_has_all_runtime_sources(self):
        for name in ['run_server.py', 'mac_bridge/server.py', 'mac_bridge/local.py',
                     'mac_bridge/dc_entry.mjs', 'scene_bridge/core.py', 'scene_bridge/server.py']:
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertFalse((ROOT / 'payload').exists())
        self.assertFalse((ROOT / 'updater.py').exists())


if __name__ == '__main__':
    unittest.main()
