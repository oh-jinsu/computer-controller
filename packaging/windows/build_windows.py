"""Build the self-contained Windows x64 app on a Windows host.

Downloads only pinned runtime archives with SHA-256 checks and builds Node/Python
dependencies into an onedir PyInstaller bundle. It never reads user settings or keys.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "packaging/windows/runtime.json").read_text())
VERSION = __import__("mac_bridge").__version__
DISPLAY_VERSION = VERSION.replace("b", "-beta.")
WORK = ROOT / "dist/windows-build"
CACHE = ROOT / ".cache/windows"
ASSETS = WORK / "assets"
BIN = ASSETS / "bin"
LICENSES = ASSETS / "Licenses"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url: str, expected: str, name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.is_file() and sha256(target) == expected:
        return target
    target.unlink(missing_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = sha256(target)
    if actual != expected:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {name}: {actual}")
    return target


def extract(archive: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            destination = (target / info.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise RuntimeError("Unsafe archive path")
        z.extractall(target)
    return target


def copy_found(root: Path, name: str, destination: Path) -> Path:
    matches = [p for p in root.rglob(name) if p.is_file()]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name}, found {len(matches)}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(matches[0], destination)
    return destination


def npm_install(folder: Path, package: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "package.json").write_text(json.dumps(package, indent=2))
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is missing")
    env = dict(os.environ, PUPPETEER_SKIP_DOWNLOAD="true", PUPPETEER_SKIP_CHROMIUM_DOWNLOAD="true")
    for key in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "CONTROL_PLANE_API_KEY"):
        env.pop(key, None)
    subprocess.run([npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"],
                   cwd=folder, env=env, check=True, timeout=600)


def prepare_assets() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows build must run on Windows")
    if WORK.exists():
        shutil.rmtree(WORK)
    BIN.mkdir(parents=True)
    LICENSES.mkdir(parents=True)

    node_cfg = CONFIG["node"]
    node_zip = download(node_cfg["url"], node_cfg["sha256"], "node.zip")
    node_root = extract(node_zip, WORK / "node") / node_cfg["directory"]
    shutil.copy2(node_root / "node.exe", BIN / "node.exe")
    if (node_root / "LICENSE").is_file():
        shutil.copy2(node_root / "LICENSE", LICENSES / "Node-LICENSE.txt")

    tunnel_cfg = CONFIG["tunnel_client"]
    tunnel_zip = download(tunnel_cfg["url"], tunnel_cfg["sha256"], "tunnel.zip")
    tunnel_root = extract(tunnel_zip, WORK / "tunnel")
    copy_found(tunnel_root, "tunnel-client-runtime-cloudflared.exe", BIN / "tunnel-client.exe")
    copy_found(tunnel_root, "cloudflared.exe", BIN / "cloudflared.exe")
    license_file = download(tunnel_cfg["license_url"], tunnel_cfg["license_sha256"], "tunnel-licenses.txt")
    shutil.copy2(license_file, LICENSES / "Tunnel-Client-LICENSES.txt")

    deno_cfg = CONFIG["deno"]
    deno_zip = download(deno_cfg["url"], deno_cfg["sha256"], "deno.zip")
    deno_root = extract(deno_zip, WORK / "deno")
    copy_found(deno_root, "deno.exe", BIN / "deno.exe")
    deno_license = download(deno_cfg["license_url"], deno_cfg["license_sha256"], "deno-license.md")
    shutil.copy2(deno_license, LICENSES / "Deno-LICENSE.md")

    ffmpeg_cfg = CONFIG["ffmpeg"]
    ffmpeg_zip = download(ffmpeg_cfg["url"], ffmpeg_cfg["sha256"], "ffmpeg.zip")
    ffmpeg_root = extract(ffmpeg_zip, WORK / "ffmpeg")
    ffmpeg_exe = next(iter(ffmpeg_root.rglob("ffmpeg.exe")), None)
    ffprobe_exe = next(iter(ffmpeg_root.rglob("ffprobe.exe")), None)
    if ffmpeg_exe is None or ffprobe_exe is None or ffmpeg_exe.parent != ffprobe_exe.parent:
        raise RuntimeError("Unexpected FFmpeg archive layout")
    for file in ffmpeg_exe.parent.iterdir():
        if file.is_file() and file.suffix.lower() in {".exe", ".dll"}:
            shutil.copy2(file, BIN / file.name)
    for pattern in ("LICENSE*", "COPYING*", "README*"):
        for file in ffmpeg_root.rglob(pattern):
            if file.is_file() and file.stat().st_size < 2_000_000:
                target = LICENSES / "FFmpeg" / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(file, target)

    runtime = ASSETS / ".runtime"
    npm_install(runtime / "desktop-commander", {
        "private": True, "name": "mac-bridge-windows-dc", "version": VERSION,
        "dependencies": {"@wonderwhy-er/desktop-commander": "0.2.51"},
    })
    npm_install(runtime / "playwright", {
        "private": True, "name": "mac-bridge-windows-browser", "version": VERSION,
        "dependencies": {"@playwright/mcp": "0.0.82"},
    })

    bridge_assets = ASSETS / "mac_bridge"
    bridge_assets.mkdir(parents=True)
    shutil.copy2(ROOT / "mac_bridge/dc_entry.mjs", bridge_assets / "dc_entry.mjs")

    package_rows = {}
    for tree in (runtime / "desktop-commander/node_modules", runtime / "playwright/node_modules"):
        for package_json in tree.rglob("package.json"):
            try:
                value = json.loads(package_json.read_text(encoding="utf-8"))
            except Exception:
                continue
            name, version, license_name = value.get("name"), value.get("version"), value.get("license")
            if isinstance(name, str) and isinstance(version, str):
                package_rows[name] = {"version": version, "license": license_name}
    (LICENSES / "Node-packages.json").write_text(json.dumps(package_rows, indent=2, sort_keys=True))


def build_app() -> Path:
    prepare_assets()
    dist = WORK / "pyinstaller"
    spec = WORK / "spec"
    for folder in (dist, spec):
        folder.mkdir(parents=True, exist_ok=True)
    sep = os.pathsep
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--name", "Computer Controller", "--distpath", str(dist), "--workpath", str(WORK / "pyi-work"),
        "--specpath", str(spec),
        "--additional-hooks-dir", str(ROOT / "packaging/windows/hooks"),
        "--collect-all", "keyring", "--collect-all", "yt_dlp",
        "--collect-all", "pydantic_settings", "--hidden-import", "keyring.backends.Windows",
        "--add-data", f"{ASSETS / 'bin'}{sep}bin",
        "--add-data", f"{ASSETS / '.runtime/desktop-commander'}{sep}.runtime/desktop-commander",
        "--add-data", f"{ASSETS / '.runtime/playwright'}{sep}.runtime/playwright",
        "--add-data", f"{ASSETS / 'mac_bridge/dc_entry.mjs'}{sep}mac_bridge",
        "--add-data", f"{LICENSES}{sep}Licenses",
        str(ROOT / "packaging/windows/entry.py"),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, timeout=1200)
    app = dist / "Computer Controller"
    exe = app / "Computer Controller.exe"
    if not exe.is_file():
        raise RuntimeError("PyInstaller did not produce Computer Controller.exe")
    doctor = subprocess.run([str(exe), "--doctor"], cwd=app, capture_output=True, text=True, timeout=90)
    if doctor.returncode:
        raise RuntimeError("Packaged --doctor failed:\n" + doctor.stdout + doctor.stderr)
    subprocess.run([sys.executable, str(ROOT / "packaging/windows/smoke_windows.py"), str(exe)],
                   cwd=ROOT, check=True, timeout=300)
    return app


def package(app: Path) -> Path:
    out = ROOT / "dist/windows"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    archive_base = out / f"Computer-Controller-{DISPLAY_VERSION}-windows-x64"
    archive = Path(shutil.make_archive(str(archive_base), "zip", root_dir=app.parent, base_dir=app.name))
    provenance = {
        "schema": 1, "version": DISPLAY_VERSION, "engine_version": VERSION,
        "platform": "windows-x64", "archive": archive.name, "archive_sha256": sha256(archive),
        "code_signed": False, "smart_screen_reputation": False,
        "runtime_manifest": CONFIG,
    }
    (out / "BUILD-PROVENANCE-WINDOWS.json").write_text(json.dumps(provenance, indent=2))
    (out / "SHA256SUMS-WINDOWS.txt").write_text(f"{sha256(archive)}  {archive.name}\n")
    print(json.dumps({"app": str(app), "archive": str(archive), "sha256": sha256(archive),
                      "signed": False}, indent=2))
    return archive


def main() -> int:
    app = build_app()
    package(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
