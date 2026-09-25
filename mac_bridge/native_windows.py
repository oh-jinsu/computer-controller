"""Windows-native approval and exact-window capture helpers.

No UI automation or input injection. Window capture is limited to an HWND/PID pair
returned by the enumeration performed immediately before capture.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import io
import os
from pathlib import Path

from PIL import Image

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MB_YESNO = 0x00000004
MB_ICONWARNING = 0x00000030
MB_DEFBUTTON2 = 0x00000100
MB_SYSTEMMODAL = 0x00001000
IDYES = 6
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020


class RECT(C.Structure):
    _fields_ = [("left", C.c_long), ("top", C.c_long), ("right", C.c_long), ("bottom", C.c_long)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [
        ("biSize", W.DWORD), ("biWidth", C.c_long), ("biHeight", C.c_long),
        ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
        ("biSizeImage", W.DWORD), ("biXPelsPerMeter", C.c_long),
        ("biYPelsPerMeter", C.c_long), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD),
    ]


class BITMAPINFO(C.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 3)]


def _apis():
    if os.name != "nt":
        raise OSError("Windows APIs are only available on Windows.")
    user32 = C.WinDLL("user32", use_last_error=True)
    kernel32 = C.WinDLL("kernel32", use_last_error=True)
    gdi32 = C.WinDLL("gdi32", use_last_error=True)

    user32.IsWindowVisible.argtypes = [W.HWND]
    user32.IsWindowVisible.restype = W.BOOL
    user32.GetWindowTextLengthW.argtypes = [W.HWND]
    user32.GetWindowTextLengthW.restype = C.c_int
    user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user32.GetWindowTextW.restype = C.c_int
    user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user32.GetWindowThreadProcessId.restype = W.DWORD
    user32.GetWindowRect.argtypes = [W.HWND, C.POINTER(RECT)]
    user32.GetWindowRect.restype = W.BOOL
    user32.GetWindowDC.argtypes = [W.HWND]
    user32.GetWindowDC.restype = W.HDC
    user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
    user32.ReleaseDC.restype = C.c_int
    user32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    user32.PrintWindow.restype = W.BOOL

    kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel32.OpenProcess.restype = W.HANDLE
    kernel32.CloseHandle.argtypes = [W.HANDLE]
    kernel32.CloseHandle.restype = W.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = W.BOOL

    gdi32.CreateCompatibleDC.argtypes = [W.HDC]
    gdi32.CreateCompatibleDC.restype = W.HDC
    gdi32.DeleteDC.argtypes = [W.HDC]
    gdi32.DeleteDC.restype = W.BOOL
    gdi32.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
    gdi32.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
    gdi32.SelectObject.restype = W.HGDIOBJ
    gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
    gdi32.DeleteObject.restype = W.BOOL
    gdi32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, W.LPVOID, C.POINTER(BITMAPINFO), W.UINT]
    gdi32.GetDIBits.restype = C.c_int
    return user32, kernel32, gdi32


def approval_dialog(message: str) -> bool:
    user32, _, _ = _apis()
    # MessageBox is deliberately a local OS dialog. "No" is the default.
    result = user32.MessageBoxW(None, message, "Mac Bridge · 실행 승인",
                                MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SYSTEMMODAL)
    return result == IDYES


def screen_permission(*, request: bool = False) -> bool:
    # Windows desktop capture via Win32 does not have a macOS-style TCC permission.
    return True


def _process_image(pid: int, kernel32) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = W.DWORD(32768)
        buf = C.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)):
            return ""
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def _title(hwnd: int, user32) -> str:
    length = max(0, user32.GetWindowTextLengthW(hwnd))
    if length > 32767:
        return ""
    buf = C.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def windows(app_name: str) -> list[dict]:
    if not app_name.strip() or len(app_name) > 120:
        raise ValueError("Specify an application name, such as Godot; do not enumerate all apps")
    user32, kernel32, _ = _apis()
    needle = app_name.casefold().removesuffix(".exe")
    result: list[dict] = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if not pid.value:
            return True
        image = _process_image(int(pid.value), kernel32)
        process_name = Path(image).stem if image else ""
        title = _title(hwnd, user32)
        if needle not in process_name.casefold() and needle not in title.casefold():
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, C.byref(rect)):
            return True
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 1 or height < 1 or width * height > 100_000_000:
            return True
        result.append({
            "window_id": int(hwnd), "owner_pid": int(pid.value),
            "app_name": process_name or app_name, "title": title,
            "bounds": {"X": int(rect.left), "Y": int(rect.top),
                       "Width": int(width), "Height": int(height)},
        })
        return len(result) < 100

    callback = callback_type(visit)
    user32.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user32.EnumWindows.restype = W.BOOL
    user32.EnumWindows(callback, 0)
    return result[:100]


def capture_png(window_id: int, owner_pid: int) -> bytes:
    user32, _, gdi32 = _apis()
    hwnd = W.HWND(window_id)
    current_pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(current_pid))
    if int(current_pid.value) != owner_pid or not user32.IsWindowVisible(hwnd):
        raise OSError("Selected window closed or changed")
    rect = RECT()
    if not user32.GetWindowRect(hwnd, C.byref(rect)):
        raise OSError("Could not read selected window bounds")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 1 or height < 1 or width * height > 50_000_000:
        raise OSError("Unexpected selected window size")

    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        raise OSError("Could not get selected window device context")
    memory_dc = bitmap = old = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(window_dc)
        if not memory_dc:
            raise OSError("Could not create capture device context")
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        if not bitmap:
            raise OSError("Could not allocate capture bitmap")
        old = gdi32.SelectObject(memory_dc, bitmap)
        if not old:
            raise OSError("Could not select capture bitmap")
        if not user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT):
            raise OSError("Windows could not capture that exact window")
        header = BITMAPINFOHEADER(
            biSize=C.sizeof(BITMAPINFOHEADER), biWidth=width, biHeight=-height,
            biPlanes=1, biBitCount=32, biCompression=0, biSizeImage=width * height * 4,
            biXPelsPerMeter=0, biYPelsPerMeter=0, biClrUsed=0, biClrImportant=0,
        )
        info = BITMAPINFO()
        info.bmiHeader = header
        raw = C.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(memory_dc, bitmap, 0, height, raw, C.byref(info), DIB_RGB_COLORS)
        if lines != height:
            raise OSError("Windows returned an incomplete window bitmap")
        image = Image.frombuffer("RGB", (width, height), raw.raw, "raw", "BGRX", 0, 1)
        target = io.BytesIO()
        image.save(target, "PNG")
        return target.getvalue()
    finally:
        if old and memory_dc:
            gdi32.SelectObject(memory_dc, old)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
