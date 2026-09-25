"""Public-update and signing preparation checks; no remote publication or secret access.
The Swift URL policy also has separately compiled tests in packaging/tests/.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_signing', ROOT / 'packaging/scripts/sign_and_notarize.py')
signing = importlib.util.module_from_spec(spec); spec.loader.exec_module(signing)


class PublicDistributionTests(unittest.TestCase):
    def setUp(self):
        self.swift = (ROOT / 'packaging/macos/MacBridge.swift').read_text()
        self.builder = (ROOT / 'packaging/scripts/build_app.py').read_text()
        self.config = json.loads((ROOT / 'packaging/release.json').read_text())

    def test_public_feed_is_latest_stable_without_auth(self):
        self.assertEqual(self.config['update_feed_url'], 'https://github.com/oh-jinsu/mac-bridge/releases/latest/download/appcast.xml')

    def test_native_updater_does_not_retrieve_github_credentials(self):
        for forbidden in ['signInGitHub', 'authProcess', 'api.github.com', 'Bearer ', 'updateAuthorization', 'apiAssets', 'GitHub 연결']:
            self.assertNotIn(forbidden, self.swift)
        self.assertIn('httpHeaders = [:]', self.swift)

    def test_no_duplicate_updater_scheduler(self):
        self.assertNotIn('withTimeInterval: 21600', self.swift)
        self.assertIn('SUScheduledCheckInterval', self.builder)

    def test_public_signature_validation_never_expires(self):
        self.assertIn("'SURequireSignedFeed': True", self.builder)
        self.assertIn("'SUVerifyUpdateBeforeExtraction': True", self.builder)
        self.assertIn("'SUSignedFeedFailureExpirationInterval': 0", self.builder)

    def test_feed_and_url_policy_are_wired_into_native_app(self):
        self.assertIn("'SUFeedURL': RELEASE['update_feed_url']", self.builder)
        self.assertIn('PublicUpdatePolicy.acceptsArchive(item.fileURL)', self.swift)
        self.assertIn("packaging/macos/PublicUpdatePolicy.swift", self.builder)

    def test_github_cli_not_required_in_end_user_runtime(self):
        self.assertNotIn("'deno', 'gh'", self.builder)
        self.assertNotIn("('gh', ['--version'])", (ROOT / 'mac_bridge/app_control.py').read_text())
        self.assertNotIn('bin/gh', self.swift)

    def test_no_connect_mode_does_not_start_updater(self):
        self.assertIn('guard !noConnect, !updaterStarted', self.swift)

    def test_idle_drain_and_backup_remain(self):
        self.assertIn('shouldPostponeRelaunchForUpdate', self.swift)
        self.assertIn('helper(["prepare-update"])', self.swift)
        self.assertIn('previous', (ROOT / 'mac_bridge/app_control.py').read_text())

    def test_public_release_uses_new_build_number(self):
        self.assertGreater(self.config['build_number'], 50001)
        self.assertNotEqual(self.config['display_version'], '0.5.0-beta.1')


class SigningPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.app = self.root / 'Computer Controller.app'
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        (self.app / 'Contents/MacOS/MacBridge').write_bytes(b'\xcf\xfa\xed\xfe' + b'fixture')
        self.identity = {'sha1': 'A' * 40, 'name': 'Developer ID Application: Unit Test (TESTTEAM12)'}
    def tearDown(self): self.tmp.cleanup()

    def test_only_usable_developer_id_identity_recognized(self):
        text = '\n'.join([' 1) ' + 'B'*40 + ' "Apple Development: Test"',
            ' 2) ' + 'A'*40 + ' "' + self.identity['name'] + '"',
            ' 3) ' + 'C'*40 + ' "Developer ID Installer: Test"'])
        self.assertEqual(signing.developer_identities(text), [self.identity])

    def test_invalid_or_revoked_identity_not_accepted(self):
        text = ' 1) ' + 'A'*40 + ' "' + self.identity['name'] + '" (CSSMERR_TP_CERT_REVOKED)'
        self.assertEqual(signing.developer_identities(text), [])

    def test_exact_name_or_fingerprint_selection(self):
        self.assertEqual(signing.resolve_identity(self.identity['name'], [self.identity]), 'A'*40)
        self.assertEqual(signing.resolve_identity('a'*40, [self.identity]), 'A'*40)

    def test_non_developer_id_and_ambiguous_names_refused(self):
        for value in ['-', 'Apple Development: Test', 'Test']:
            with self.assertRaises(ValueError): signing.resolve_identity(value, [self.identity])
        with self.assertRaises(ValueError): signing.resolve_identity(self.identity['name'], [self.identity, self.identity])

    def test_missing_certificate_fails_before_copy(self):
        with mock.patch.object(signing, 'available_identities', return_value=[]), mock.patch.object(signing, 'command') as cmd:
            with self.assertRaises(ValueError): signing.notarize(self.app, self.root/'output', 'missing', 'test-profile')
        cmd.assert_not_called(); self.assertFalse((self.root/'output').exists())

    def test_signing_plan_is_inside_out(self):
        nested = self.app / 'Contents/Frameworks/Engine.framework'
        nested.mkdir(parents=True); (nested/'Engine').write_bytes(b'\xcf\xfa\xed\xfe' + b'fixture')
        targets = signing.signing_targets(self.app)
        self.assertLess(targets.index(nested/'Engine'), targets.index(nested))
        self.assertEqual(targets[-1], self.app)

    def test_internal_alias_does_not_duplicate_native_signing(self):
        alias = self.app/'Contents/MacOS/alias'; alias.symlink_to('MacBridge')
        targets = signing.signing_targets(self.app)
        self.assertNotIn(alias, targets)

    def test_external_symlink_is_refused(self):
        (self.app/'Contents/leak').symlink_to(self.root)
        with self.assertRaises(ValueError): signing.signing_targets(self.app)

    def test_empty_app_is_refused(self):
        other = self.root/'Empty.app'; other.mkdir()
        with self.assertRaises(ValueError): signing.signing_targets(other)

    def test_production_flags_without_deep_signing(self):
        args = signing.signing_arguments(self.app, self.app, 'A'*40, self.root/'entitlements')
        self.assertIn('--timestamp', args); self.assertIn('runtime', args)
        self.assertNotIn('--deep', args); self.assertNotIn('--timestamp=none', args)
        self.assertNotIn('--entitlements', args)

    def test_jit_entitlements_only_for_explicit_node_deno(self):
        for name in ['node', 'deno']:
            args = signing.signing_arguments(self.app/'Contents/Resources/bin'/name, self.app, 'A'*40, self.root/'entitlements')
            self.assertIn('--entitlements', args)
        self.assertNotIn('--entitlements', signing.signing_arguments(self.app/'Contents/MacOS/node', self.app, 'A'*40, self.root/'entitlements'))
        for name in ['com.apple.security.get-task-allow', 'com.apple.security.cs.disable-library-validation', 'com.apple.security.cs.allow-dyld-environment-variables']:
            self.assertNotIn(name, signing.JIT_ENTITLEMENTS)

    def test_credentials_only_named_keychain_profile(self):
        source = (ROOT/'packaging/scripts/sign_and_notarize.py').read_text()
        self.assertIn("'--keychain-profile', profile", source)
        self.assertNotIn("'--password'", source)
        self.assertNotIn('store-credentials', source)
        self.assertNotIn('set-key-partition-list', source)


if __name__ == '__main__': unittest.main()
