"""Developer-only production gate: COPY -> Developer ID -> notarytool -> staple.

Never modifies the input app, reads/export private key material, creates certificates,
changes Keychain ACLs, or accepts command-line passwords. Credentials are resolved
by Apple's tools from an explicitly named local Keychain profile. No publication.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

MACH_MAGICS = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
               b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
               b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
JIT_FILES = {'Contents/Resources/bin/node', 'Contents/Resources/bin/deno'}
JIT_ENTITLEMENTS = {'com.apple.security.cs.allow-jit': True,
                    'com.apple.security.cs.allow-unsigned-executable-memory': True}


def command(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True, **kw)


def developer_identities(text: str) -> list[dict[str, str]]:
    matches = re.findall(r'^\s*\d+\) ([A-Fa-f0-9]{40}) "(Developer ID Application: [^"\n]+)"\s*$', text, re.M)
    return [{'sha1': digest.upper(), 'name': name} for digest, name in matches]


def available_identities() -> list[dict[str, str]]:
    return developer_identities(command(['/usr/bin/security', 'find-identity', '-v', '-p', 'codesigning'], text=True).stdout)


def resolve_identity(requested: str, identities: list[dict[str, str]]) -> str:
    matches = [row for row in identities if requested == row['name'] or requested.upper() == row['sha1']]
    if len(matches) != 1:
        raise ValueError('Choose one installed Developer ID Application identity. Apple Development/Distribution and ad-hoc identities cannot replace it.')
    return matches[0]['sha1']


def macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as f:
        return f.read(4) in MACH_MAGICS


def signing_targets(app: Path) -> list[Path]:
    app = app.resolve(strict=True)
    paths = list(app.rglob('*'))
    for p in paths:
        if p.is_symlink() and not p.resolve(strict=True).is_relative_to(app):
            raise ValueError('External symlink is not allowed in a release bundle.')
    binaries = [p for p in paths if macho(p)]
    if not binaries:
        raise ValueError('No native code found in the app.')
    containers = [p for p in paths if not p.is_symlink() and p.is_dir()
                  and p.suffix in {'.app', '.xpc', '.framework'}]
    # Sign ALL native files (including native Python/npm dependencies) first,
    # then nested code bundles deepest-first, and the containing app last.
    return sorted(binaries, key=lambda p: (-len(p.parts), str(p))) + sorted(containers, key=lambda p: (-len(p.parts), str(p))) + [app]


def signing_arguments(path: Path, app: Path, identity: str, entitlements: Path) -> list[str]:
    args = ['/usr/bin/codesign', '--force', '--sign', identity, '--options', 'runtime', '--timestamp']
    if path.relative_to(app).as_posix() in JIT_FILES:
        args += ['--entitlements', str(entitlements)]
    # Do not copy debug/get-task-allow/disable-library-validation entitlements
    # from a developer machine. Every bundled native dependency uses this identity.
    return args + [str(path)]


def notarize(app: Path, output: Path, identity: str, profile: str) -> dict:
    identity = resolve_identity(identity, available_identities())
    if not profile or len(profile) > 160 or any(ord(c) < 32 for c in profile):
        raise ValueError('Specify an existing local notarytool Keychain profile name.')
    app = app.resolve(strict=True)
    if app.name != 'Mac Bridge.app' or not (app / 'Contents/Info.plist').is_file():
        raise ValueError('Choose a built Mac Bridge.app.')
    output = output.absolute()
    if output.is_relative_to(app) or output.exists() or output.is_symlink():
        raise ValueError('Choose a fresh output directory, outside the input bundle.')
    command(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    output.mkdir(parents=True, mode=0o700)
    target = output / app.name
    command(['/usr/bin/ditto', app, target])
    with tempfile.TemporaryDirectory(prefix='mac-bridge-signing-') as tmp:
        entitlement = Path(tmp) / 'runtime.plist'
        entitlement.write_bytes(plistlib.dumps(JIT_ENTITLEMENTS))
        for path in signing_targets(target):
            command(signing_arguments(path, target, identity, entitlement))
    command(['/usr/bin/codesign', '--verify', '--deep', '--strict', target])
    archive = output / 'notary-submission.zip'
    command(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', target, archive])
    submission = command(['xcrun', 'notarytool', 'submit', archive, '--keychain-profile', profile,
                          '--wait', '--timeout', '20m', '--output-format', 'json'], text=True, timeout=1260)
    value = json.loads(submission.stdout)
    evidence = {'submission_id': value.get('id'), 'status': value.get('status'),
                'developer_id_signed': True, 'notarized': False, 'input_bundle_unchanged': True}
    evidence_path = output / 'notarization-status.json'
    evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
    if value.get('status') != 'Accepted':
        raise RuntimeError('Apple did not accept this submission. Do not publish; inspect the submission ID with notarytool log.')
    command(['xcrun', 'stapler', 'staple', target])
    command(['xcrun', 'stapler', 'validate', target])
    command(['/usr/bin/codesign', '--verify', '--deep', '--strict', target])
    command(['/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=2', target])
    evidence.update(notarized=True, gatekeeper_assessment_passed=True, signed_app=str(target))
    evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', nargs='?', type=Path)
    parser.add_argument('--preflight', action='store_true', help='List usable certificate names/fingerprints only; no Keychain secret access')
    parser.add_argument('--identity', help='Exact installed Developer ID Application name or SHA1 fingerprint')
    parser.add_argument('--keychain-profile', help='Existing notarytool profile; never enter passwords as arguments')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.preflight:
        identities = available_identities()
        print(json.dumps({'developer_id_available': bool(identities), 'identities': identities,
                          'apple_account_login_attempted': False}, indent=2))
        return
    if not all([args.app, args.identity, args.keychain_profile, args.output]):
        parser.error('app, --identity, --keychain-profile and --output are required')
    print(json.dumps(notarize(args.app, args.output, args.identity, args.keychain_profile), indent=2))


if __name__ == '__main__':
    main()
