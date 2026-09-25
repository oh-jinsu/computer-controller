"""Windows-only portability checks. Real packaged MCP/browser/video tests run separately."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from mac_bridge import app_control
from mac_bridge.activity import process_exists
from mac_bridge.filelock import locked_path
from mac_bridge.native_windows import screen_permission
from mac_bridge.platform_support import (app_data_dir, command_line, default_shell,
                                         executable_name, shell_command, tunnel_command_line)


@unittest.skipUnless(sys.platform == "win32", "Windows-only portability checks")
class WindowsPortabilityTests(unittest.TestCase):
    def test_app_data_uses_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            self.assertEqual(app_data_dir(), Path(tmp) / "Mac Bridge")

    def test_windows_executable_and_shell_helpers(self):
        self.assertEqual(executable_name("node"), "node.exe")
        self.assertEqual(executable_name("ffmpeg.exe"), "ffmpeg.exe")
        self.assertEqual(default_shell(), "cmd.exe")
        wrapped, shell = shell_command(Path(r"C:\Users\Tester\dev\game"), "git status --short")
        self.assertEqual(shell, "cmd.exe")
        self.assertTrue(wrapped.startswith("powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "))
        encoded = wrapped.rsplit(" ", 1)[1]
        script = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("Set-Location -LiteralPath", script)
        self.assertIn(r"C:\Users\Tester\dev\game", script)
        self.assertIn("git status --short", script)
        self.assertEqual(command_line(["tool.exe", "hello world"]), "& 'tool.exe' 'hello world'")
        tunnel = tunnel_command_line([r"C:\Program Files\Mac Bridge\Mac Bridge.exe", "--worker",
                                      "--data", r"C:\Users\Tester\AppData\Local\Mac Bridge"])
        self.assertEqual(tunnel, '"C:/Program Files/Mac Bridge/Mac Bridge.exe" --worker --data '
                                 '"C:/Users/Tester/AppData/Local/Mac Bridge"')

    def test_cross_platform_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.lock"
            with locked_path(path, blocking=False):
                with self.assertRaises(BlockingIOError):
                    with locked_path(path, blocking=False):
                        pass

    def test_windows_capture_does_not_require_tcc(self):
        self.assertTrue(screen_permission())
        self.assertTrue(screen_permission(request=True))

    def test_windows_process_existence_check(self):
        self.assertTrue(process_exists(os.getpid()))
        self.assertFalse(process_exists(0))

    def test_packaged_app_uses_platform_data_root(self):
        self.assertEqual(app_control.DEFAULT_DATA, app_data_dir())

    def test_runtime_manifest_is_pinned(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "packaging/windows/runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["architecture"], "x64")
        for key in ("node", "tunnel_client", "deno", "ffmpeg"):
            value = manifest[key]
            self.assertTrue(value["url"].startswith("https://"))
            self.assertRegex(value["sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("windows-amd64", manifest["tunnel_client"]["url"])
        self.assertIn("win-x64", manifest["node"]["url"])

    def test_windows_packaging_sources_exist(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "packaging/windows/build_windows.py",
            "packaging/windows/smoke_windows.py",
            "packaging/windows/entry.py",
            "packaging/windows/hooks/hook-mcp.py",
            "mac_bridge/windows_app.py",
            "mac_bridge/native_windows.py",
        ):
            self.assertTrue((root / name).is_file(), name)
        builder = (root / "packaging/windows/build_windows.py").read_text(encoding="utf-8")
        self.assertIn("--additional-hooks-dir", builder)
        self.assertNotIn('"--collect-all", "mcp"', builder)
        self.assertIn('"--console"', builder)
        self.assertNotIn('"--windowed"', builder)
        app = (root / "mac_bridge/windows_app.py").read_text(encoding="utf-8")
        self.assertIn("_hide_console_for_gui()", app)


if __name__ == "__main__":
    unittest.main()
