"""macOS-native approval and exact-window capture; no Accessibility/input injection."""
from __future__ import annotations

import ctypes as C
import io
import json
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from PIL import Image
from .policy import MacError, Policy, private_dir, private_write

APPROVAL_SCRIPT = '''on run argv
    set r to display dialog (item 1 of argv) with title "Mac Bridge · 실행 승인" buttons {"거부", "한 번 허용"} default button "거부" cancel button "거부" giving up after 35
    if gave up of r then return "DENY"
    if button returned of r is "한 번 허용" then return "ALLOW"
    return "DENY"
end run'''


class NativeApproval:
    def __init__(self, policy: Policy):
        self.policy = policy

    def approve(self, action: str, arguments: dict) -> bool:
        self.policy.require_active()
        if sys.platform != 'darwin':
            raise MacError('Native approval is available on macOS only; no automatic approval fallback')
        text = json.dumps(arguments, ensure_ascii=False, indent=2)
        pending = private_dir(self.policy.state / 'pending')
        # At most the latest 20 local request previews; not exposed as an MCP tool.
        old = sorted(pending.glob('*.json'), key=lambda p: p.stat().st_mtime)
        for file in old[:-19]:
            if not file.is_symlink():
                file.unlink()
        full = pending / (uuid.uuid4().hex + '.json')
        private_write(full, text.encode())
        preview = text if len(text) <= 2400 else text[:2400] + '\n… 전체 요청은 아래 파일에 있습니다.'
        message = f'{action}\n\n{preview}\n\n전체 요청: {full}\n\n터미널 명령은 프로젝트 밖에도 접근할 수 있습니다. 승인한 요청 한 번만 실행합니다.'
        try:
            result = subprocess.run(['/usr/bin/osascript', '-e', APPROVAL_SCRIPT, '--', message],
                                    capture_output=True, text=True, timeout=40)
            return result.returncode == 0 and result.stdout.strip() == 'ALLOW'
        except subprocess.TimeoutExpired:
            return False


def quartz():
    if sys.platform != 'darwin':
        raise MacError('Window capture requires macOS')
    cg = C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg.CGPreflightScreenCaptureAccess.restype = C.c_bool
    cg.CGPreflightScreenCaptureAccess.argtypes = []
    cg.CGRequestScreenCaptureAccess.restype = C.c_bool
    cg.CGRequestScreenCaptureAccess.argtypes = []
    cg.CGWindowListCopyWindowInfo.restype = C.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [C.c_uint32, C.c_uint32]
    cf.CFPropertyListCreateData.restype = C.c_void_p
    cf.CFPropertyListCreateData.argtypes = [C.c_void_p, C.c_void_p, C.c_long, C.c_ulong, C.c_void_p]
    cf.CFDataGetLength.restype = C.c_long
    cf.CFDataGetLength.argtypes = [C.c_void_p]
    cf.CFDataGetBytePtr.restype = C.POINTER(C.c_ubyte)
    cf.CFDataGetBytePtr.argtypes = [C.c_void_p]
    cf.CFRelease.argtypes = [C.c_void_p]
    return cg, cf


def screen_permission(*, request: bool = False) -> bool:
    cg, _ = quartz()
    return bool(cg.CGRequestScreenCaptureAccess() if request else cg.CGPreflightScreenCaptureAccess())


def windows(app_name: str) -> list[dict]:
    if not app_name.strip() or len(app_name) > 120:
        raise MacError('Specify an application name, such as Godot; do not enumerate all apps')
    cg, cf = quartz()
    if not cg.CGPreflightScreenCaptureAccess():
        raise MacError('Screen Recording permission is missing. Run Mac-Screen-Permission.command locally, then restart the launcher if macOS requests it.')
    info = cg.CGWindowListCopyWindowInfo(1 | 16, 0)  # on-screen only, exclude desktop
    if not info:
        raise MacError('macOS returned no window information')
    data = None
    try:
        data = cf.CFPropertyListCreateData(None, info, 200, 0, None)  # binary plist
        if not data:
            raise MacError('Could not serialize macOS window information')
        size = cf.CFDataGetLength(data)
        if not 0 < size < 8_000_000:
            raise MacError('Unexpected window-list size')
        result = plistlib.loads(C.string_at(cf.CFDataGetBytePtr(data), size))
    finally:
        if data:
            cf.CFRelease(data)
        cf.CFRelease(info)
    items = []
    for w in result:
        owner = str(w.get('kCGWindowOwnerName', ''))
        bounds = w.get('kCGWindowBounds', {})
        if (w.get('kCGWindowLayer') != 0 or app_name.casefold() not in owner.casefold()
                or bounds.get('Width', 0) < 1 or bounds.get('Height', 0) < 1):
            continue
        items.append({'window_id': int(w['kCGWindowNumber']), 'owner_pid': int(w['kCGWindowOwnerPID']),
                      'app_name': owner, 'title': str(w.get('kCGWindowName', '')), 'bounds': bounds})
    return items[:100]


def resize_capture(raw: bytes, max_edge: int) -> tuple[bytes, dict]:
    if not 320 <= max_edge <= 2560 or len(raw) > 64 * 1024 * 1024:
        raise MacError('Invalid screenshot size')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 50_000_000:
            raise MacError('Screenshot dimensions exceed the safety limit')
        image.load()
        original = [image.width, image.height]
        image = image.convert('RGB')
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        target = io.BytesIO()
        image.save(target, 'JPEG', quality=88)
        return target.getvalue(), {'original_size': original, 'returned_size': list(image.size),
                                   'encoding': 'JPEG preview; resized only, no generated content'}


def capture_window(policy: Policy, app_name: str, window_id: int, owner_pid: int,
                   max_edge: int = 1600) -> tuple[dict, bytes]:
    if window_id < 1 or owner_pid < 1:
        raise MacError('Select positive window_id and owner_pid from mac_list_windows first')
    policy.require_active()
    match = next((x for x in windows(app_name) if x['window_id'] == window_id and x['owner_pid'] == owner_pid), None)
    if match is None:
        raise MacError('Selected window closed or changed; list windows again. No full-screen fallback.')
    with tempfile.TemporaryDirectory(prefix='mac-window-', dir=private_dir(policy.state / 'capture-tmp')) as folder:
        output = Path(folder) / 'window.png'
        policy.require_active()
        result = subprocess.run(['/usr/sbin/screencapture', '-x', '-o', '-l', str(window_id), '-t', 'png', str(output)],
                                capture_output=True, timeout=20)
        if result.returncode or not output.is_file():
            raise MacError('macOS could not capture that window. Check permission/visibility; there is no desktop fallback.')
        if not any(x['window_id'] == window_id and x['owner_pid'] == owner_pid for x in windows(app_name)):
            raise MacError('Window identity changed during capture; discarded image')
        policy.require_active()
        if output.stat().st_size > 64 * 1024 * 1024:
            raise MacError('Screenshot is too large')
        data, metadata = resize_capture(output.read_bytes(), max_edge)
    return {**match, **metadata, 'source': 'actual macOS window capture'}, data
