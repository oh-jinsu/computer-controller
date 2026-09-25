"""Small OS abstractions shared by the macOS and Windows packages."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shlex
import subprocess
import sys


IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def executable_name(name: str) -> str:
    if IS_WINDOWS and not name.lower().endswith(".exe"):
        return name + ".exe"
    return name


def app_data_dir() -> Path:
    """Use the new product directory for fresh installs, but keep an existing legacy install in place.

    Avoiding an automatic move here preserves rollback compatibility with Mac Bridge builds while the
    product name migrates. The existing tunnel ID, approval mode, browser profile, backups and contexts
    therefore remain available without copying state.
    """
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
        current = base / "Computer Controller"
        legacy = base / "Mac Bridge"
    elif IS_MAC:
        base = Path.home() / "Library/Application Support"
        current = base / "Computer Controller"
        legacy = base / "Mac Bridge"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
        current = base / "computer-controller"
        legacy = base / "mac-bridge"
    if current.exists():
        return current
    if legacy.exists():
        return legacy
    return current


def default_shell() -> str:
    # Desktop Commander manages cmd.exe reliably as a one-shot process. The
    # user's command itself is still executed by non-interactive PowerShell.
    return "cmd.exe" if IS_WINDOWS else "/bin/sh"


def path_separator() -> str:
    return os.pathsep


def bundled_python_bin(resources: Path) -> Path:
    return resources / ("python" if not IS_WINDOWS else "python")


def command_line(argv: list[str]) -> str:
    """Command text intended for the user's configured shell."""
    if not IS_WINDOWS:
        return shlex.join(argv)
    # PowerShell needs the call operator when the executable path is quoted.
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
    return "& " + " ".join(quote(value) for value in argv)


def tunnel_command_line(argv: list[str]) -> str:
    """Command string consumed by tunnel-client's own argv parser.

    Its parser treats backslash as an escape even on Windows, so Windows paths are
    rendered with forward slashes (accepted by CreateProcess) before quoting.
    """
    if not IS_WINDOWS:
        return shlex.join(argv)
    parts = []
    for raw in argv:
        value = raw.replace("\\", "/")
        if not value or any(ch.isspace() for ch in value) or any(ch in value for ch in '"\\'):
            value = '"' + value.replace('"', '\\"') + '"'
        parts.append(value)
    return " ".join(parts)


def shell_command(workspace: Path, command: str) -> tuple[str, str]:
    """Return (wrapped command, shell executable) without interpolating untrusted paths unsafely."""
    if IS_WINDOWS:
        # Keep cmd.exe as Desktop Commander's lifecycle shell, but preserve
        # PowerShell semantics for user commands. EncodedCommand avoids cmd.exe
        # quoting problems for spaces, Unicode and embedded quotes/semicolons.
        target = str(workspace).replace("'", "''")
        script = f"Set-Location -LiteralPath '{target}'; {command}"
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        wrapped = f"powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}"
        return wrapped, "cmd.exe"
    if IS_MAC:
        shell = "/bin/zsh"
        shell_args = "-f -c"
    else:
        shell = "/bin/bash" if Path("/bin/bash").is_file() else "/bin/sh"
        shell_args = "--noprofile --norc -c" if shell.endswith("bash") else "-c"
    wrapped = (f"cd {shlex.quote(str(workspace))} && "
               f"HOME={shlex.quote(str(Path.home()))} {shlex.quote(shell)} {shell_args} {shlex.quote(command)}")
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
