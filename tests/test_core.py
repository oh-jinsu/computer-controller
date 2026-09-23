"""Core regression tests; real FFmpeg tests do not need YouTube or MCP installed."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scene_bridge.core import (
    Backend, BridgeError, CACHE_TTL, Jobs, MAX_PENDING, Media, Request,
    canonical_youtube_url, integer, local_source, number, run_process,
    schedule, timecode, validate_media_url,
)

URL = "https://www.youtube.com/watch?v=abcdefghijk"


class ValidationTests(unittest.TestCase):
    def test_youtube_normalization(self):
        for source in [URL, "https://youtu.be/abcdefghijk?t=30", "https://m.youtube.com/watch?v=abcdefghijk&list=ignored",
                       "https://www.youtube.com/shorts/abcdefghijk", "https://youtube.com/embed/abcdefghijk",
                       "https://youtube.com/live/abcdefghijk", "https://www.youtube.com:443/watch?v=abcdefghijk"]:
            with self.subTest(source=source):
                self.assertEqual(canonical_youtube_url(source), URL)

    def test_youtube_rejects_arbitrary_or_ambiguous_urls(self):
        for source in ["http://youtube.com/watch?v=abcdefghijk", "https://127.0.0.1/",
                       "https://youtube.com.evil.test/watch?v=abcdefghijk", "file:///etc/passwd",
                       "https://user:pass@youtube.com/watch?v=abcdefghijk", "https://youtube.com:444/watch?v=abcdefghijk",
                       "https://youtube.com/watch?v=abcdefghijk&v=lmnopqrstuv", "https://youtube.com/playlist?list=abc",
                       "https://youtu.be/short", "https://youtu.be/abcdefghijk/extra", "https://youtu.be/abcdefghijk\n",
                       "https://youtube.com:bad/watch?v=abcdefghijk", "https://[broken"]:
            with self.subTest(source=source):
                with self.assertRaises(BridgeError):
                    canonical_youtube_url(source)

    def test_numeric_validation(self):
        for value in [True, False, "1", float("nan"), float("inf"), -1, 101]:
            with self.subTest(value=value), self.assertRaises(BridgeError):
                number(value, "x", 0, 100)
        for value in [True, 1.5, "2", 0, 13]:
            with self.subTest(value=value), self.assertRaises(BridgeError):
                integer(value, "x", 1, 12)
        self.assertEqual(number(1, "x", 0, 2), 1.0)
        self.assertEqual(integer(12, "x", 1, 12), 12)

    def test_request_validation(self):
        invalid = [dict(count=0), dict(count=13), dict(max_edge=319), dict(max_edge=1921),
                   dict(start_seconds=10, end_seconds=5), dict(timestamps=[]),
                   dict(timestamps=[float("nan")]), dict(timestamps=[-1]),
                   dict(timestamps=[1], start_seconds=1), dict(timestamps=[1], end_seconds=2),
                   dict(timestamps=[1] * 13), dict(timestamps="1,2"), dict(count=True)]
        for kw in invalid:
            with self.subTest(kw=kw), self.assertRaises(BridgeError):
                Request.build(URL, **kw)
        req = Request.build(URL, timestamps=[2, 1, 2])
        self.assertEqual(req.timestamps, (1.0, 2.0))

    def test_schedule_uses_interval_midpoints(self):
        self.assertEqual(schedule(60, 0, None, 6, None), [5, 15, 25, 35, 45, 55])
        self.assertEqual(schedule(60, 10, 30, 2, None), [15, 25])
        self.assertEqual(schedule(60, 0, None, 6, (20, 10, 20)), [10, 20])
        self.assertEqual(timecode(3661.234), "01:01:01.234")

    def test_schedule_rejects_eof_and_bad_duration(self):
        for args in [(0, 0, None, 6, None), (14401, 0, None, 6, None),
                     (10, 0, 11, 2, None), (10, 10, None, 1, None), (10, 0, None, 1, (10,))]:
            with self.subTest(args=args), self.assertRaises(BridgeError):
                schedule(*args)

    def test_cdn_rejects_private_dns(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.1.1", 443))]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        source = "https://rr1---sn-test.googlevideo.com/videoplayback?expire=1"
        with patch("scene_bridge.core.socket.getaddrinfo", return_value=public):
            self.assertEqual(validate_media_url(source), source)
        with patch("scene_bridge.core.socket.getaddrinfo", return_value=private):
            with self.assertRaises(BridgeError):
                validate_media_url(source)
        for source in ["https://127.0.0.1/a", "http://rr1.googlevideo.com/a", "https://googlevideo.com.evil.test/a",
                       "https://user@rr1.googlevideo.com/a", "https://rr1.googlevideo.com:444/a"]:
            with self.subTest(source=source), self.assertRaises(BridgeError):
                validate_media_url(source)

    def test_local_files_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "input"
            root.mkdir()
            (root / "sample.mp4").write_bytes(b"not needed")
            (root / "secret.txt").write_bytes(b"private")
            (root / "link.mp4").symlink_to(root / "sample.mp4")
            self.assertEqual(local_source("local:sample.mp4", root), root / "sample.mp4")
            for source in ["local:../sample.mp4", "local:sub/sample.mp4", "local:sub\\sample.mp4", "local:secret.txt",
                           "local:link.mp4", "local:missing.mp4", "local:/etc/passwd", "sample.mp4"]:
                with self.subTest(source=source), self.assertRaises(BridgeError):
                    local_source(source, root)

    def test_subprocess_no_shell(self):
        payload = "hello; echo SHOULD_NOT_EXECUTE"
        out, _ = run_process([sys.executable, "-c", "import sys;print(sys.argv[1])", payload], 3, purpose="test")
        self.assertEqual(out.strip(), payload)

    def test_subprocess_timeout(self):
        before = time.monotonic()
        with self.assertRaises(BridgeError):
            run_process([sys.executable, "-c", "import time;time.sleep(5)"], 0.15, purpose="test")
        self.assertLess(time.monotonic() - before, 3)

    def test_subprocess_oversized_output(self):
        with self.assertRaises(BridgeError):
            run_process([sys.executable, "-c", "print('a'*10000)"], 3, purpose="test", limit=100)

    def test_subprocess_errors_do_not_leak_stderr(self):
        with self.assertRaises(BridgeError) as caught:
            run_process([sys.executable, "-c", "import sys;sys.stderr.write('SIGNED_URL_AND_SECRET');sys.exit(1)"],
                        3, purpose="YouTube 읽기")
        self.assertNotIn("SIGNED_URL_AND_SECRET", str(caught.exception))


class FakeBackend:
    def __init__(self, *, hold: threading.Event | None = None, fail: bool = False):
        self.hold = hold
        self.fail = fail
        self.calls = 0

    def resolve(self, source):
        if self.hold:
            self.hold.wait(10)
        return Media("unused", {"source": source, "duration_seconds": 10, "kind": "test"}, False)

    def extract(self, media, seconds, max_edge, dest, timeout):
        self.calls += 1
        if self.fail:
            dest.write_bytes(b"partial")
            raise BridgeError("intentional test failure")
        Image.new("RGB", (320, 180), (20, 50, 90)).save(dest)
        return {"filename": dest.name, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                "requested_seconds": seconds, "requested_timecode": timecode(seconds),
                "decoded_source_pts_seconds": seconds, "width": 320, "height": 180}


def await_job(jobs, job_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = jobs.get(job_id, wait_seconds=1)
        if result["state"] in {"complete", "failed"}:
            return result
    raise AssertionError("local test job timed out")


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.backend = FakeBackend()
        self.jobs = Jobs(self.root, self.backend)

    def tearDown(self):
        self.jobs.close()
        self.tmp.cleanup()

    def test_job_complete_and_reuse(self):
        req = Request.build(URL, count=2)
        first = self.jobs.submit(req)
        result = await_job(self.jobs, first["job_id"])
        self.assertEqual(result["state"], "complete", result)
        second = self.jobs.submit(req)
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["reused"])
        self.assertEqual(self.backend.calls, 2)
        with Image.open(io.BytesIO(self.jobs.image_bytes(first["job_id"]))) as im:
            im.load()
            self.assertEqual(im.size, (984, 312))
        meta = json.loads((self.root / "output" / first["job_id"] / "metadata.json").read_text())
        self.assertEqual(meta["frames"][0]["requested_seconds"], 2.5)

    def test_corrupt_image_rejected_and_not_reused(self):
        req = Request.build(URL, count=1)
        first = self.jobs.submit(req)
        await_job(self.jobs, first["job_id"])
        p = self.root / "output" / first["job_id"] / "frame-01.jpg"
        p.write_bytes(b"corrupted")
        with self.assertRaises(BridgeError):
            self.jobs.image_bytes(first["job_id"], 1)
        second = self.jobs.submit(req)
        self.assertNotEqual(first["job_id"], second["job_id"])
        self.assertEqual(await_job(self.jobs, second["job_id"])["state"], "complete")

    def test_frame_index_and_job_id_validation(self):
        first = self.jobs.submit(Request.build(URL, count=1))
        await_job(self.jobs, first["job_id"])
        for index in [-1, 2, True]:
            with self.assertRaises(BridgeError):
                self.jobs.image_bytes(first["job_id"], index)
        for job_id in ["../../etc/passwd", "missing", "a"*32]:
            with self.assertRaises(BridgeError):
                self.jobs.get(job_id)

    def test_failure_deletes_partial_files(self):
        self.backend.fail = True
        first = self.jobs.submit(Request.build(URL, count=1))
        result = await_job(self.jobs, first["job_id"])
        self.assertEqual(result["state"], "failed")
        # Failure status is visible before cleanup completes; close waits for the worker.
        self.jobs.close()
        self.assertFalse((self.root / "output" / first["job_id"]).exists())
        with self.assertRaises(BridgeError):
            self.jobs.image_bytes(first["job_id"])

    def test_queued_jobs_are_bounded_and_deduplicated(self):
        hold = threading.Event()
        self.backend.hold = hold
        try:
            ids = [self.jobs.submit(Request.build(URL, count=n))["job_id"] for n in range(1, MAX_PENDING+1)]
            duplicate = self.jobs.submit(Request.build(URL, count=1))
            self.assertEqual(duplicate["job_id"], ids[0])
            with self.assertRaises(BridgeError):
                self.jobs.submit(Request.build(URL, count=MAX_PENDING+1))
        finally:
            hold.set()

    def test_local_listing_does_not_traverse_directories(self):
        (self.root / "input" / "video.mp4").write_bytes(b"video")
        (self.root / "input" / "private.txt").write_bytes(b"private")
        (self.root / "input" / "nested").mkdir()
        (self.root / "input" / "nested" / "hidden.mp4").write_bytes(b"hidden")
        (self.root / "input" / "linked.mp4").symlink_to(self.root / "input" / "video.mp4")
        self.assertEqual(self.jobs.local_videos(), [{"source": "local:video.mp4", "bytes": 5}])

    def test_changed_local_identity_gets_new_job(self):
        file = self.root / "input" / "video.mp4"
        file.write_bytes(b"first")
        req = Request.build("local:video.mp4", count=1)
        first = self.jobs.submit(req)
        await_job(self.jobs, first["job_id"])
        file.write_bytes(b"different content")
        second = self.jobs.submit(req)
        self.assertNotEqual(first["job_id"], second["job_id"])
        await_job(self.jobs, second["job_id"])

    def test_cleanup_preserves_input_and_unrelated_output(self):
        old = self.root / "output" / ("b"*32)
        old.mkdir()
        (old / "test.jpg").write_bytes(b"derived")
        stamp = time.time() - CACHE_TTL - 10
        os.utime(old, (stamp, stamp))
        unrelated = self.root / "output" / "my-files"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_bytes(b"keep")
        original = self.root / "input" / "keep.mp4"
        original.write_bytes(b"original")
        self.jobs.cleanup()
        self.assertFalse(old.exists())
        self.assertTrue((unrelated / "keep.txt").exists())
        self.assertEqual(original.read_bytes(), b"original")

    def test_symlink_roots_rejected(self):
        other = self.root / "other"
        other.mkdir()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "input").symlink_to(other, target_is_directory=True)
            with self.assertRaises(BridgeError):
                Jobs(root)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg not installed")
class RealFFmpegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.root / "input").mkdir()
        cls.video = cls.root / "input" / "test.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=640x360:rate=10", "-t", "4", "-c:v", "mpeg4", "-y", str(cls.video)],
                       check=True, timeout=20)
        cls.portrait = cls.root / "input" / "portrait.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=240x420:rate=10", "-t", "2", "-c:v", "mpeg4", "-y", str(cls.portrait)],
                       check=True, timeout=20)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_real_mp4_frames_and_pts(self):
        jobs = Jobs(self.root)
        try:
            start = jobs.submit(Request.build("local:test.mp4", timestamps=[0.5, 1.5, 2.5], max_edge=320))
            result = await_job(jobs, start["job_id"])
            self.assertEqual(result["state"], "complete", result)
            self.assertEqual(result["video"]["duration_seconds"], 4)
            self.assertEqual(len(result["frames"]), 3)
            for frame in result["frames"]:
                self.assertEqual((frame["width"], frame["height"]), (320, 180))
                self.assertIsNotNone(frame["decoded_source_pts_seconds"])
                self.assertAlmostEqual(frame["requested_seconds"], frame["decoded_source_pts_seconds"], places=2)
                with Image.open(io.BytesIO(jobs.image_bytes(start["job_id"], frame["index"]))) as im:
                    im.load()
                    self.assertEqual(im.size, (320, 180))
            self.assertEqual(len({f["sha256"] for f in result["frames"]}), 3)
        finally:
            jobs.close()

    def test_no_upscale(self):
        backend = Backend(self.root / "input")
        media = backend.resolve("local:test.mp4")
        frame = backend.extract(media, 0.5, 1280, self.root / "no-upscale.jpg", 10)
        self.assertEqual((frame["width"], frame["height"]), (640, 360))

    def test_portrait_aspect(self):
        backend = Backend(self.root / "input")
        media = backend.resolve("local:portrait.mp4")
        frame = backend.extract(media, 0.5, 320, self.root / "portrait.jpg", 10)
        self.assertEqual(frame["height"], 320)
        self.assertLessEqual(abs(frame["width"] / frame["height"] - 240/420), 1/320)

    def test_real_request_past_eof_fails(self):
        jobs = Jobs(self.root)
        try:
            start = jobs.submit(Request.build("local:test.mp4", timestamps=[4]))
            result = await_job(jobs, start["job_id"])
            self.assertEqual(result["state"], "failed")
        finally:
            jobs.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
