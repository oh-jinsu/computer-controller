"""Offline tests: real filesystem/image transforms + mocked macOS boundary. Not an MCP integration test."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from mac_bridge.policy import MacError, Policy, clean_env, private_write
from mac_bridge.native import NativeApproval, capture_window, resize_capture


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name)
        self.root, self.project = p / 'bridge', p / 'project'
        self.root.mkdir(); self.project.mkdir()
        self.policy = Policy(self.root, self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_relative_path(self):
        self.assertEqual(self.policy.path('a.txt'), self.project / 'a.txt')

    def test_parent_traversal(self):
        with self.assertRaises(MacError): self.policy.path('../outside')

    def test_absolute_outside(self):
        with self.assertRaises(MacError): self.policy.path('/etc/passwd')

    def test_sibling_prefix(self):
        with self.assertRaises(MacError): self.policy.path(str(self.project) + 'other/file')

    def test_symlink_outside(self):
        (self.project / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(MacError): self.policy.path('link/run_server.py')

    def test_symlink_inside(self):
        (self.project / 'real').mkdir()
        (self.project / 'link').symlink_to(self.project / 'real', target_is_directory=True)
        with self.assertRaises(MacError): self.policy.path('link/file')

    def test_environment_and_key_files(self):
        for name in ['.env', '.env.production', '.ssh/secret', '.git/config', 'a.pem', 'a.key']:
            with self.subTest(name=name), self.assertRaises(MacError): self.policy.path(name)

    def test_urls_rejected(self):
        for value in ['https://example.org/a', 'file:///etc/passwd', '\x00x']:
            with self.subTest(value=value), self.assertRaises(MacError): self.policy.path(value)

    def test_special_file_rejected(self):
        fifo = self.project / 'pipe'
        os.mkfifo(fifo)
        with self.assertRaises(MacError): self.policy.path(str(fifo), file_only=True)

    def test_bridge_not_exposed_when_inside_project(self):
        nested = self.project / 'bridge'
        nested.mkdir()
        p = Policy(nested, self.project)
        with self.assertRaises(MacError): p.path('bridge/run_server.py')

    def test_shell_command_is_single_quoted_argument(self):
        command = "printf '%s' 'quoted'; echo \"$(uname)\"\n# test"
        s = self.policy.shell(command)
        self.assertEqual(shlex.split(s)[-1], command)
        self.assertEqual(shlex.split(s)[1], str(self.project))

    def test_shell_size_rejected(self):
        for command in ['', 'x' * 8001, 'a\x00b']:
            with self.assertRaises(MacError): self.policy.shell(command)

    def test_clean_environment(self):
        with mock.patch.dict(os.environ, {'CONTROL_PLANE_API_KEY': 'SECRET', 'AWS_SECRET_ACCESS_KEY': 'SECRET', 'NODE_OPTIONS': '--inspect', 'OPENAI_API_KEY': 'SECRET'}):
            e = clean_env(self.root)
        self.assertNotIn('CONTROL_PLANE_API_KEY', e)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', e)
        self.assertNotIn('NODE_OPTIONS', e)
        self.assertNotIn('OPENAI_API_KEY', e)
        self.assertEqual(e['HOME'], str(self.root))

    def test_pause(self):
        self.policy.require_active(); self.policy.pause()
        with self.assertRaises(MacError): self.policy.require_active()

    def test_private_write_symlink_refused(self):
        out = self.root / 'output'
        out.write_text('original')
        link = self.root / 'link'
        link.symlink_to(out)
        with self.assertRaises(MacError): private_write(link, b'new')
        self.assertEqual(out.read_text(), 'original')

    def test_audit_redacts_arguments(self):
        self.policy.record('run', {'command': 'SECRET_API_TOKEN_abcdef'}, 'denied')
        raw = (self.policy.state / 'mac-audit.jsonl').read_text()
        self.assertNotIn('SECRET_API', raw)
        self.assertEqual(self.policy.history()[0]['state'], 'denied')

    def test_audit_rotation(self):
        (self.policy.state / 'mac-audit.jsonl').write_text(' ' * 2_000_001)
        self.policy.record('status', {}, 'ok')
        self.assertTrue((self.policy.state / 'mac-audit.previous.jsonl').exists())
        self.assertEqual(len(self.policy.history()), 1)

    def test_snapshot_and_backup(self):
        p = self.project / 'source.txt'; p.write_bytes(b'original')
        h, raw = self.policy.snapshot(p)
        self.assertEqual(h, hashlib.sha256(b'original').hexdigest())
        backup = self.policy.backup(p, raw)
        self.assertEqual(Path(backup).read_bytes(), b'original')

    def test_snapshot_too_large(self):
        p = self.project / 'large'; p.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with self.assertRaises(MacError): self.policy.snapshot(p)

    def test_approval_not_available_on_linux(self):
        with mock.patch('mac_bridge.native.sys.platform', 'linux'):
            with self.assertRaises(MacError): NativeApproval(self.policy).approve('run', {})

    def test_native_approval_uses_argv_not_code_interpolation(self):
        attack = 'x\"\ndo shell script \"bad\"'
        done = subprocess.CompletedProcess([], 0, stdout='ALLOW\n', stderr='')
        with mock.patch('mac_bridge.native.sys.platform', 'darwin'), mock.patch('mac_bridge.native.subprocess.run', return_value=done) as run:
            self.assertTrue(NativeApproval(self.policy).approve('run', {'command': attack}))
            argv = run.call_args.args[0]
            self.assertNotIn(attack, argv[2])
            self.assertEqual(argv[3], '--')
            self.assertIn('bad', argv[4])

    def test_native_approval_denial(self):
        done = subprocess.CompletedProcess([], 1, stdout='', stderr='User canceled')
        with mock.patch('mac_bridge.native.sys.platform', 'darwin'), mock.patch('mac_bridge.native.subprocess.run', return_value=done):
            self.assertFalse(NativeApproval(self.policy).approve('run', {}))

    def test_native_approval_timeout(self):
        with mock.patch('mac_bridge.native.sys.platform', 'darwin'), mock.patch('mac_bridge.native.subprocess.run', side_effect=subprocess.TimeoutExpired('osascript', 40)):
            self.assertFalse(NativeApproval(self.policy).approve('run', {}))

    def test_resize_preserves_portrait_aspect(self):
        buffer = io.BytesIO(); Image.new('RGB', (800, 1600)).save(buffer, 'PNG')
        raw, meta = resize_capture(buffer.getvalue(), 1000)
        with Image.open(io.BytesIO(raw)) as image:
            image.load(); self.assertEqual(image.size, (500, 1000))
        self.assertEqual(meta['original_size'], [800, 1600])

    def test_capture_closed_window_no_screen_fallback(self):
        with mock.patch('mac_bridge.native.windows', return_value=[]), mock.patch('mac_bridge.native.subprocess.run') as run:
            with self.assertRaises(MacError): capture_window(self.policy, 'Godot', 123, 456)
            run.assert_not_called()

    def test_capture_pid_mismatch(self):
        with mock.patch('mac_bridge.native.windows', return_value=[{'window_id': 123, 'owner_pid': 999}]), mock.patch('mac_bridge.native.subprocess.run') as run:
            with self.assertRaises(MacError): capture_window(self.policy, 'Godot', 123, 456)
            run.assert_not_called()

    def test_capture_targets_window_and_decodes(self):
        row = {'window_id': 123, 'owner_pid': 456, 'app_name': 'Godot', 'title': 'Test'}
        def capture(argv, **kwargs):
            self.assertEqual(argv[:6], ['/usr/sbin/screencapture', '-x', '-o', '-l', '123', '-t'])
            Image.new('RGB', (640, 360)).save(argv[-1], 'PNG')
            return subprocess.CompletedProcess(argv, 0, stdout=b'', stderr=b'')
        with mock.patch('mac_bridge.native.windows', return_value=[row]), mock.patch('mac_bridge.native.subprocess.run', side_effect=capture):
            meta, raw = capture_window(self.policy, 'Godot', 123, 456)
        with Image.open(io.BytesIO(raw)) as img: img.load(); self.assertEqual(img.size, (640, 360))
        self.assertEqual(meta['source'], 'actual macOS window capture')  # metadata contract, source here is mocked

    def test_capture_identity_changes_discarded(self):
        row = {'window_id': 123, 'owner_pid': 456}
        def capture(argv, **kwargs):
            Image.new('RGB', (640, 360)).save(argv[-1], 'PNG')
            return subprocess.CompletedProcess(argv, 0, stdout=b'', stderr=b'')
        with mock.patch('mac_bridge.native.windows', side_effect=[[row], []]), mock.patch('mac_bridge.native.subprocess.run', side_effect=capture):
            with self.assertRaises(MacError): capture_window(self.policy, 'Godot', 123, 456)


if __name__ == '__main__': unittest.main()
