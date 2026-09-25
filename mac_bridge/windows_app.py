"""Windows desktop launcher for the packaged Mac Bridge runtime."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser

from . import __version__
from . import app_control
from .browser_connection import SETTINGS_URL, chrome_executable
from .migration import read_settings
from .policy import MacError
from .platform_support import app_data_dir


DATA = app_data_dir()
LOG_DIR = DATA / "logs"
LOG_FILE = LOG_DIR / "app.log"
RELEASES_URL = "https://github.com/oh-jinsu/mac-bridge/releases"


def _restore_stdio_if_available() -> None:
    """PyInstaller --windowed sets sys.std* to None; MCP worker still receives pipe handles."""
    if sys.platform != "win32":
        return
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [ctypes.c_int]
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    specs = [
        ("stdin", -10, os.O_RDONLY, "rb"),
        ("stdout", -11, os.O_WRONLY, "wb"),
        ("stderr", -12, os.O_WRONLY, "wb"),
    ]
    for name, constant, flags, mode in specs:
        if getattr(sys, name) is not None:
            continue
        handle = kernel32.GetStdHandle(constant)
        if not handle or handle == ctypes.c_void_p(-1).value:
            continue
        try:
            fd = msvcrt.open_osfhandle(int(handle), flags)
            raw = os.fdopen(fd, mode, buffering=0, closefd=False)
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace",
                                    line_buffering=name != "stdin")
            setattr(sys, name, text)
        except OSError:
            continue


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def dispatch_background(argv: list[str]) -> int | None:
    if not argv:
        return None
    _restore_stdio_if_available()
    action = argv[0]
    if action == "--serve":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--serve", action="store_true")
        parser.add_argument("--data", type=Path, default=DATA)
        args = parser.parse_args(argv)
        return app_control.serve(args.data.expanduser().resolve())
    if action == "--worker":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--worker", action="store_true")
        parser.add_argument("--data", type=Path, default=DATA)
        args = parser.parse_args(argv)
        env = app_control.environment()
        os.environ.clear()
        os.environ.update(env)
        from .server import main as worker
        sys.argv = [sys.argv[0], "--root", str(args.data.expanduser().resolve()), "--assets", str(app_control.ASSETS)]
        worker()
        return 0
    if action == "--video":
        from .video import main as video_main
        return video_main(argv[1:])
    if action == "--doctor":
        print(json.dumps(app_control.bundle_doctor(), ensure_ascii=False))
        return 0
    return None


class WindowsApp:
    def __init__(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox

        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title(f"Mac Bridge {__version__}")
        self.root.geometry("680x540")
        self.root.minsize(620, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.tunnel = tk.StringVar()
        self.workspace = tk.StringVar()
        self.runtime_key = tk.StringVar()
        self.always = tk.BooleanVar(value=True)
        self.personal = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="상태 확인 중…")

        self._build()
        self.load()
        self.root.after(500, self._auto_start)
        self.root.after(1500, self.refresh)

    def _build(self):
        import tkinter.ttk as ttk

        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Mac Bridge · Windows", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(frame, textvariable=self.status_text).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(frame, text="터널 ID").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.tunnel).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 10))

        ttk.Label(frame, text="작업 폴더").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.workspace).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(2, 10))
        ttk.Button(frame, text="선택…", command=self.choose_workspace).grid(row=5, column=2, sticky="e", padx=(8, 0))

        ttk.Label(frame, text="Runtime API 키 (Windows 자격 증명에 있으면 비워 두세요)").grid(row=6, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.runtime_key, show="•").grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(2, 10))

        ttk.Checkbutton(frame, text="요청된 PC 작업 항상 허용 (로컬 승인창 생략)",
                        variable=self.always).grid(row=8, column=0, columnspan=3, sticky="w", pady=3)
        ttk.Checkbutton(frame, text="평소 Chrome 로그인 상태 사용 (Chrome 자체 허용 필요)",
                        variable=self.personal).grid(row=9, column=0, columnspan=3, sticky="w", pady=3)

        info = ("새 설치 기본값: 승인창 없이 사용 + 평소 Chrome 로그인 사용. "
                "Chrome의 remote debugging 허용은 Chrome에서 한 번 승인해야 합니다.")
        ttk.Label(frame, text=info, wraplength=620).grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(8, 14))

        buttons = ttk.Frame(frame)
        buttons.grid(row=11, column=0, columnspan=3, sticky="ew")
        ttk.Button(buttons, text="저장", command=self.save).pack(side="left")
        ttk.Button(buttons, text="연결 시작", command=self.start).pack(side="left", padx=6)
        ttk.Button(buttons, text="연결 중지", command=self.stop).pack(side="left")
        ttk.Button(buttons, text="Chrome 허용 페이지", command=self.open_chrome_settings).pack(side="left", padx=(18, 6))
        ttk.Button(buttons, text="로그 보기", command=self.open_logs).pack(side="left")

        bottom = ttk.Frame(frame)
        bottom.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        ttk.Button(bottom, text="업데이트 확인", command=lambda: webbrowser.open(RELEASES_URL)).pack(side="left")
        ttk.Button(bottom, text="종료", command=self.quit).pack(side="right")

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def current(self) -> dict:
        try:
            return app_control.status(DATA)
        except Exception:
            return {"configured": False, "running": False}

    def load(self):
        state = self.current()
        if state.get("configured"):
            self.tunnel.set(state.get("tunnel_id", ""))
            self.workspace.set(state.get("workspace", ""))
            self.always.set(state.get("approval_mode") == "always")
            self.personal.set(state.get("browser_mode") == "personal")
        else:
            documents = Path.home() / "Documents"
            if documents.is_dir():
                self.workspace.set(str(documents))
            self.always.set(True)
            self.personal.set(True)
        self._set_status(state)

    def _set_status(self, state: dict):
        if state.get("running"):
            self.status_text.set("연결됨 · 서버 실행 중")
        elif state.get("configured"):
            self.status_text.set("설정됨 · 서버 중지")
        else:
            self.status_text.set("처음 설정이 필요합니다.")

    def choose_workspace(self):
        selected = self.filedialog.askdirectory(initialdir=self.workspace.get() or str(Path.home()))
        if selected:
            self.workspace.set(selected)

    def save(self) -> bool:
        state = self.current()
        if state.get("running"):
            self.messagebox.showerror("Mac Bridge", "연결 중에는 설정을 바꾸지 않습니다. 먼저 연결을 중지하세요.")
            return False
        values = {
            "tunnel_id": self.tunnel.get().strip(),
            "workspace": self.workspace.get().strip(),
            "runtime_key": self.runtime_key.get().strip(),
            "approval_mode": "always" if self.always.get() else "ask",
            "browser_mode": "personal" if self.personal.get() else "dedicated",
        }
        try:
            app_control.configure(DATA, values)
        except Exception as exc:
            self.messagebox.showerror("설정 저장 실패", str(exc))
            return False
        finally:
            self.runtime_key.set("")
        self.status_text.set("설정 저장 완료")
        return True

    def _server_command(self) -> list[str]:
        return [sys.executable, "--serve", "--data", str(DATA)]

    def start(self):
        state = self.current()
        if state.get("running"):
            self._set_status(state)
            return
        if not state.get("configured") and not self.save():
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 2_000_000:
            previous = LOG_DIR / f"previous-{int(time.time())}.log"
            LOG_FILE.replace(previous)
        log = open(LOG_FILE, "ab", buffering=0)
        try:
            subprocess.Popen(self._server_command(), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             creationflags=_flags(), close_fds=True)
        except Exception as exc:
            log.close()
            self.messagebox.showerror("연결 시작 실패", str(exc))
            return
        log.close()
        self.status_text.set("서버 시작 중…")
        self.root.after(1200, self.refresh)

    def _controller_pid(self) -> int | None:
        state = self.current()
        pid = state.get("controller_pid")
        return pid if type(pid) is int and pid > 1 else None

    def stop(self):
        pid = self._controller_pid()
        if pid is None:
            self.status_text.set("서버 중지")
            return
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
        except Exception as exc:
            self.messagebox.showerror("연결 중지 실패", str(exc))
            return
        self.status_text.set("서버 중지 중…")
        self.root.after(1000, self.refresh)

    def open_chrome_settings(self):
        chrome = chrome_executable()
        if chrome is None:
            self.messagebox.showerror("Chrome", "Google Chrome을 찾지 못했습니다.")
            return
        subprocess.Popen([str(chrome), SETTINGS_URL], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def open_logs(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_DIR))

    def refresh(self):
        state = self.current()
        self._set_status(state)
        self.root.after(2000, self.refresh)

    def _auto_start(self):
        if self.current().get("configured") and not self.current().get("running"):
            self.start()

    def quit(self):
        self.stop()
        self.root.after(300, self.root.destroy)

    def run(self):
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    background = dispatch_background(argv)
    if background is not None:
        return int(background)
    if sys.platform != "win32":
        raise SystemExit("Windows launcher must run on Windows.")
    WindowsApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
