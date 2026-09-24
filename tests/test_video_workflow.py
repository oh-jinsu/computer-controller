"""Video recipe tests: filesystem/scheduling/cancellation. Network resolver is mocked.
The real MCP -> process -> FFmpeg -> ordinary image reader path is in smoke_mcp.py.
"""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from PIL import Image

from mac_bridge import video
from scene_bridge.core import BridgeError, Media

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.youtube.com/watch?v=abcdefghijk'


class FakeBackend:
    def __init__(self, _root): self.calls = []
    def resolve(self, _source):
        return Media('https://private-signed.example/SECRET',
                     {'duration_seconds': 8.0, 'title': 'untrusted title', 'kind': 'youtube'}, True)
    def extract(self, _media, seconds, edge, dest, timeout):
        import hashlib
        self.calls.append(seconds)
        Image.new('RGB', (320, 180), 'gray').save(dest)
        return {'filename': dest.name, 'requested_seconds': seconds,
                'requested_timecode': str(seconds), 'decoded_source_pts_seconds': seconds,
                'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'width': 320, 'height': 180}


class VideoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.out = self.root / 'artifacts'
        self.events = []
        self.backend = FakeBackend(self.root)
        self.patch = mock.patch.object(video, 'Backend', return_value=self.backend)
        self.patch.start()
    def tearDown(self): self.patch.stop(); self.temp.cleanup()

    def run_recipe(self, **kwargs):
        return video.extract(URL, self.out, progress=self.events.append, **kwargs)

    def test_complete_is_atomic_and_contains_common_file_paths(self):
        result = self.run_recipe(count=3)
        self.assertEqual(result['frames_count'], 3)
        self.assertEqual(self.events[-1]['event'], 'complete')
        self.assertEqual(len([e for e in self.events if e.get('frames_ready')]), 3)
        self.assertTrue(Path(result['manifest_path']).is_file())
        self.assertTrue(Path(result['sheet_path']).is_file())
        self.assertEqual(len(result['frame_paths']), 3)
        self.assertFalse(list(self.out.glob('.partial-*')))
        self.assertEqual(Path(result['manifest_path']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(result['output_directory']).stat().st_mode & 0o777, 0o700)

    def test_manifest_records_real_metadata_and_hashes_not_stream_urls(self):
        import hashlib
        result = self.run_recipe(timestamps=[3, 1])
        manifest = json.loads(Path(result['manifest_path']).read_text())
        self.assertEqual(self.backend.calls, [1.0, 3.0])
        self.assertIn('not frame-perfect', manifest['timestamp_note'])
        self.assertNotIn('SECRET', json.dumps(self.events) + json.dumps(manifest))
        for frame in manifest['frames']:
            self.assertEqual(frame['sha256'], hashlib.sha256((Path(result['output_directory']) / frame['filename']).read_bytes()).hexdigest())

    def test_each_run_preserves_previous_results_and_unrelated_files(self):
        self.out.mkdir(); keep = self.out / 'keep.txt'; keep.write_text('owner')
        first = self.run_recipe(count=1); before = Path(first['manifest_path']).read_bytes()
        second = self.run_recipe(count=1)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(before, Path(first['manifest_path']).read_bytes())
        self.assertEqual(keep.read_text(), 'owner')

    def test_failure_removes_partial_not_previous_results(self):
        first = self.run_recipe(count=1)
        self.backend.extract = mock.Mock(side_effect=BridgeError('failed'))
        with self.assertRaises(BridgeError): self.run_recipe()
        self.assertTrue(Path(first['sheet_path']).is_file())
        self.assertFalse(list(self.out.glob('.partial-*')))
        self.assertEqual(len(list(self.out.glob('video-*'))), 1)

    def test_cancel_removes_incomplete_output(self):
        self.backend.extract = mock.Mock(side_effect=video.Cancelled(signal.SIGTERM))
        with self.assertRaises(video.Cancelled): self.run_recipe()
        self.assertFalse(list(self.out.glob('.partial-*')))
        self.assertFalse(list(self.out.glob('video-*')))

    def test_local_path_needs_no_input_copy(self):
        path = self.root / 'user video.mp4'; path.write_bytes(b'fixture')
        request, backend, local = video.source_request(str(path))
        self.assertEqual(request.source, 'local:user video.mp4')
        self.assertEqual(local, path)
        self.assertIs(backend, self.backend)

    def test_changed_local_input_discards_result(self):
        path = self.root / 'video.mp4'; path.write_bytes(b'a')
        original = self.backend.extract
        def change(*args, **kwargs):
            path.write_bytes(b'different'); return original(*args, **kwargs)
        self.backend.extract = change
        with self.assertRaisesRegex(BridgeError, '변경'):
            video.extract(str(path), self.out, progress=self.events.append, count=1)
        self.assertFalse(list(self.out.glob('video-*')))
        self.assertEqual(path.read_bytes(), b'different')

    def test_no_url_playlist_credentials_or_invalid_source(self):
        for source in ['https://example.com/video', 'http://youtube.com/watch?v=abcdefghijk',
                       'https://user:password@youtube.com/watch?v=abcdefghijk', 'local:video.mp4']:
            with self.subTest(source=source), self.assertRaises(BridgeError):
                video.source_request(source)

    def test_input_symlink_refused(self):
        real = self.root / 'real.mp4'; real.write_bytes(b'test')
        link = self.root / 'link.mp4'; link.symlink_to(real)
        with self.assertRaises(BridgeError): video.source_request(str(link))

    def test_output_symlink_refused(self):
        target = self.root / 'other'; target.mkdir(); self.out.symlink_to(target)
        with self.assertRaises(BridgeError): self.run_recipe()
        self.assertEqual(list(target.iterdir()), [])

    def test_app_bundle_output_refused(self):
        with self.assertRaises(BridgeError):
            video.extract(URL, self.root / 'Sample.app/output', progress=self.events.append)

    def test_same_output_serialized_without_another_queue(self):
        with video.output_lock(self.out):
            with self.assertRaisesRegex(BridgeError, '진행 중'): self.run_recipe()
        self.run_recipe(count=1)

    def test_output_budget_refuses_without_deleting_old_files(self):
        first = self.run_recipe(count=1)
        with mock.patch.object(video, 'CACHE_BYTES', 1), self.assertRaisesRegex(BridgeError, '한도'):
            self.run_recipe()
        self.assertTrue(Path(first['sheet_path']).exists())

    def test_time_budget(self):
        with mock.patch.object(video, 'MAX_RUN_SECONDS', 0), self.assertRaisesRegex(BridgeError, '시간 제한'):
            self.run_recipe()
        self.assertFalse(list(self.out.glob('.partial-*')))

    def test_frame_bounds_and_conflicting_time_options(self):
        for opts in [{'count': 13}, {'max_edge': 10}, {'timestamps': [1], 'start_seconds': 2}]:
            with self.subTest(opts=opts), self.assertRaises(BridgeError): self.run_recipe(**opts)
        self.assertFalse(self.out.exists())

    def test_help_does_not_install_or_call_network(self):
        result = subprocess.run([sys.executable, '-B', ROOT / 'mac_bridge/video.py', '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--timestamps', result.stdout)
        self.assertIn('--output', result.stdout)

    def test_status_discloses_executable_path_not_credentials(self):
        status = video.workflow_status()
        import shlex
        command = shlex.split(status['command'])
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[-1]).name, 'video.py')
        self.assertFalse(status['dedicated_mcp_tools'])
        self.assertEqual(status['result_reader'], 'mac_read_file')

    def test_cli_errors_are_json_no_traceback(self):
        result = subprocess.run([sys.executable, '-B', ROOT / 'mac_bridge/video.py', 'https://127.0.0.1/private'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['event'], 'error')
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(self.out.exists())

    def test_cancellation_terminates_and_reaps_active_decoder(self):
        # An isolated parent/child proves the core reaps subprocesses on SIGTERM.
        marker = self.root / 'decoder.pid'
        child = f"import os,time;open({str(marker)!r},'w').write(str(os.getpid()));time.sleep(60)"
        parent = ('import sys,signal;from mac_bridge.video import cancellation_signals,Cancelled;'
                  'from scene_bridge.core import run_process\n'
                  'try:\n with cancellation_signals():\n  run_process([sys.executable,"-c",' + repr(child) + '],60,purpose="test")\n'
                  'except Cancelled: sys.exit(143)\n')
        proc = subprocess.Popen([sys.executable, '-B', '-c', parent], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        decoder = None
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(marker.exists(), 'child was not started')
            decoder = int(marker.read_text())
            proc.terminate(); out, err = proc.communicate(timeout=6)
            self.assertEqual(proc.returncode, 143, err)
            with self.assertRaises(ProcessLookupError): os.kill(decoder, 0)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate()
            if decoder:
                try: os.kill(decoder, signal.SIGTERM)
                except ProcessLookupError: pass


if __name__ == '__main__': unittest.main()
