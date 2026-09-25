"""Small OS abstractions shared by the macOS and Windows packages."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys


IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def executable_name(name: str) -> str:
    if IS_WINDOWS and not name.lower().endswith(".exe"):
        return name + ".exe"
    return name


def app_data_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Mac Bridge"
        return Path.home() / "AppData/Local/Mac Bridge"
    return Path.home() / "Library/Application Support/Mac Bridge"


def default_shell() -> str:
    return "powershell.exe" if IS_WINDOWS else "/bin/sh"


def path_separator() -> str:
    return os.pathsep


def bundled_python_bin(resources: Path) -> Path:
    return resources / ("python" if not IS_WINDOWS else "python")


def command_line(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if IS_WINDOWS else shlex.join(argv)


def shell_command(workspace: Path, command: str) -> tuple[str, str]:
    """Return (wrapped command, shell executable) without interpolating untrusted paths unsafely."""
    if IS_WINDOWS:
        # PowerShell single-quoted strings escape a literal apostrophe by doubling it.
        target = str(workspace).replace("'", "''")
        wrapped = f"Set-Location -LiteralPath '{target}'; {command}"
        return wrapped, "powershell.exe"
    wrapped = (f"cd {shlex.quote(str(workspace))} && "
               f"HOME={shlex.quote(str(Path.home()))} /bin/zsh -f -c {shlex.quote(command)}")
    return wrapped, "/bin/sh"


def packaged_worker_command(assets: Path, data: Path) -> list[str]:
    """Worker command accepted by tunnel-client for each platform/package type."""
    if IS_WINDOWS and getattr(sys, "frozen", False):
        return [sys.executable, "--worker", "--data", str(data)]
    return [sys.executable, str(assets / "app_entry.py"), "worker", "--data", str(data)]


def packaged_video_command(video_file: Path) -> list[str]:
    if IS_WINDOWS and getattr(sys, "frozen", False):
        return [sys.executable, "--video"]
    return [sys.executable, "-B", str(video_file)]
