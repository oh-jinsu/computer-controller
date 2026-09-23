"""Real Sparkle install/relaunch on a DISPOSABLE app; never updates Mac Bridge.

Uses the already configured release key through sign_update (no export). This
is a framework integration test, NOT a test of the production private-GitHub
feed discovery, tunnel migration or notarized Gatekeeper policy.
"""
from __future__ import annotations
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPARKLE_NS = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
ET.register_namespace('sparkle', SPARKLE_NS)


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass  # Last line may be in-flight.
    return rows


def execute_case(app: Path, evidence: Path, feed: str, expectation: str) -> list[dict]:
    info_path = app / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes()); info['SUFeedURL'] = feed
    info_path.write_bytes(plistlib.dumps(info))
    run(['/usr/bin/codesign', '--force', '--sign', '-', app], capture_output=True)
    start = len(events(evidence))
    run(['/usr/bin/open', '-n', '-g', app], capture_output=True)
    deadline = time.monotonic() + 125
    while time.monotonic() < deadline:
        found = events(evidence)[start:]
        if any(x['event'] == 'updated_app_relaunched' for x in found):
            if expectation != 'updated':
                raise AssertionError('Invalid signed data was accepted.')
            return found
        failed = [x for x in found if x['event'] in {'update_error', 'aborted', 'start_error', 'not_found', 'timeout'}]
        if failed:
            if expectation != 'rejected' or any(x['event'] in {'start_error', 'not_found', 'timeout'} for x in failed):
                raise AssertionError(json.dumps(found, ensure_ascii=False))
            if not any('signature' in x.get('description', '').lower() or 'signed' in x.get('description', '').lower() for x in failed):
                raise AssertionError('Rejection was not a signature-validation failure: ' + json.dumps(failed))
            time.sleep(1)  # Allow the fixture's NSApp termination to complete.
            if plistlib.loads(info_path.read_bytes())['CFBundleVersion'] != '1':
                raise AssertionError('Rejected update changed the bundle version.')
            return found
        time.sleep(0.25)
    raise AssertionError('Fixture did not finish within its bounded lifetime.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / 'packaging/release.json').read_text())
    directory = Path(tempfile.mkdtemp(prefix='mac-bridge-sparkle-smoke-')).resolve()
    fixture = directory / 'installed/Mac Bridge Update Fixture.app'
    updated = directory / 'new/Mac Bridge Update Fixture.app'
    webroot = directory / 'web'; webroot.mkdir()
    evidence = directory / 'events.jsonl'
    transport = {'corrupt_archive': False, 'requests': []}
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            transport['requests'].append(self.path)
            if transport['corrupt_archive'] and self.path == '/update.zip':
                payload = bytearray((webroot / 'update.zip').read_bytes())
                payload[-1] ^= 1
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Content-Type', 'application/zip')
                self.end_headers(); self.wfile.write(payload)
            else:
                super().do_GET()
    handler = functools.partial(Handler, directory=str(webroot))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base_url = f'http://127.0.0.1:{server.server_port}'
    try:
        for name in ['MacOS', 'Frameworks']:
            (fixture / 'Contents' / name).mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / '.cache/sparkle/Sparkle.framework', fixture / 'Contents/Frameworks/Sparkle.framework', symlinks=True)
        run(['xcrun', 'clang', '-fobjc-arc', '-fmodules', '-O', '-framework', 'Cocoa', '-framework', 'Sparkle',
             '-F', fixture / 'Contents/Frameworks', '-Wl,-rpath,@executable_path/../Frameworks',
             ROOT / 'packaging/tests/SparkleSmoke.m', '-o', fixture / 'Contents/MacOS/Smoke'], capture_output=True)
        info = {'CFBundleExecutable': 'Smoke', 'CFBundleIdentifier': 'com.ohjinsu.mac-bridge.update-fixture.' + uuid.uuid4().hex,
                'CFBundleName': 'Mac Bridge Update Fixture', 'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0', 'LSUIElement': True,
                'LSMinimumSystemVersion': '12.0', 'SUPublicEDKey': config['sparkle_public_key'],
                'SURequireSignedFeed': True, 'SUVerifyUpdateBeforeExtraction': True,
                'SUEnableAutomaticChecks': False, 'SUSendProfileInfo': False,
                'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
                'MBSmokeEvidence': str(evidence), 'SUFeedURL': base_url + '/appcast.xml'}
        (fixture / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        shutil.copytree(fixture, updated, symlinks=True)
        newer = {**info, 'CFBundleVersion': '2', 'CFBundleShortVersionString': '2.0'}
        (updated / 'Contents/Info.plist').write_bytes(plistlib.dumps(newer))
        run(['/usr/bin/codesign', '--force', '--sign', '-', updated], capture_output=True)
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', updated], capture_output=True)
        archive = webroot / 'update.zip'
        run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', updated, archive])
        signer = ROOT / '.cache/sparkle/bin/sign_update'
        account = config['sparkle_keychain_account']
        signature = run([signer, '--account', account, '-p', archive], capture_output=True, text=True).stdout.strip()
        rss = ET.Element('rss', {'version': '2.0'}); channel = ET.SubElement(rss, 'channel')
        ET.SubElement(channel, 'title').text = 'Disposable updater integration fixture'
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = 'Fixture 2.0'
        ET.SubElement(item, '{' + SPARKLE_NS + '}version').text = '2'
        ET.SubElement(item, '{' + SPARKLE_NS + '}shortVersionString').text = '2.0'
        ET.SubElement(item, '{' + SPARKLE_NS + '}minimumSystemVersion').text = '12.0'
        ET.SubElement(item, 'enclosure', {'url': base_url + '/update.zip', 'length': str(archive.stat().st_size),
            'type': 'application/octet-stream', '{' + SPARKLE_NS + '}edSignature': signature})
        feed = webroot / 'appcast.xml'
        feed.write_bytes(ET.tostring(rss, encoding='utf-8', xml_declaration=True))
        run([signer, '--account', account, feed], capture_output=True)
        run([signer, '--account', account, '--verify', feed], capture_output=True)
        corrupt = webroot / 'bad-feed.xml'
        corrupt.write_bytes(feed.read_bytes().replace(b'Fixture 2.0', b'Fixture 9.0'))
        print('TESTING invalid signed feed', flush=True)
        begin = len(transport['requests'])
        rejected_feed = execute_case(fixture, evidence, base_url + '/bad-feed.xml', 'rejected')
        if '/update.zip' in transport['requests'][begin:]:
            raise AssertionError('Tampered feed triggered archive download.')
        print('TESTING invalid signed archive', flush=True)
        transport['corrupt_archive'] = True
        rejected_archive = execute_case(fixture, evidence, base_url + '/appcast.xml', 'rejected')
        if any(x['event'] == 'install_ready' for x in rejected_archive):
            raise AssertionError('Tampered archive reached installation readiness.')
        print('TESTING verified update installation and relaunch', flush=True)
        transport['corrupt_archive'] = False
        updated_events = execute_case(fixture, evidence, base_url + '/appcast.xml', 'updated')
        actual = plistlib.loads((fixture / 'Contents/Info.plist').read_bytes())
        assert actual['CFBundleVersion'] == '2'
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', fixture], capture_output=True)
        report = {'passed': True, 'framework': config['sparkle_version'],
                  'checks': ['tampered signed feed rejected before archive download',
                             'tampered archive rejected without installing',
                             'valid signed feed and archive downloaded, installed, and app relaunched at version 2',
                             'installed fixture code signature remains valid'],
                  'events': {'invalid_feed': rejected_feed, 'invalid_archive': rejected_archive, 'valid_update': updated_events},
                  'not_tested': ['production Mac Bridge app delegate and private GitHub download',
                                 'active tunnel switching', 'Developer ID and Gatekeeper notarization']}
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        for rows in report['events'].values():
            for row in rows:
                if 'description' in row:
                    row['description'] = row['description'].replace(str(directory), '<fixture>').replace(str(Path.home()), '<home>')
        args.evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc), 'fixture_path': str(directory), 'events': events(evidence)}, ensure_ascii=False), flush=True)
        raise
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == '__main__':
    main()
