"""Release orchestration tests. Fake signing/network; no Apple upload or private keys.
Actual bundle/Sparkle checks remain separate developer integration tests.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('release_pipeline_tested', Path(__file__).resolve().parents[1] / 'packaging/scripts/release_pipeline.py')
rp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rp)
CONFIG = {'display_version': '0.5.0-beta.2', 'engine_version': '0.5.0b2', 'build_number': 50002,
          'minimum_macos': '26.0', 'architecture': 'arm64', 'preview': True,
          'github_repository': 'owner/mac-bridge', 'sparkle_public_key': 'public-only',
          'sparkle_keychain_account': 'release-test',
          'update_feed_url': 'https://github.com/owner/mac-bridge/releases/latest/download/appcast.xml'}
COMMIT = 'a' * 40


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.run_dir = self.root / 'release'
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        self.p = rp.Pipeline(copy.deepcopy(CONFIG), self.run_dir, self.runtime, 'prepare', wait_seconds=0)
        self.p.state = {'schema': 1, 'binding': {'source_commit': COMMIT}, 'stages': {},
                        'identity': {'name': 'Developer ID Application: Test (ABCDEFGHIJ)', 'sha1': 'B' * 40, 'team': 'ABCDEFGHIJ'}}
        self.p.runner = mock.Mock()
        self.p.runner.run.return_value = (0, '')
        self.p.fresh_source = mock.Mock(return_value=COMMIT)

    def tearDown(self):
        self.temp.cleanup()

    def app(self, parent=None):
        app = (parent or self.root) / rp.APP_NAME
        (app / 'Contents').mkdir(parents=True)
        plist = {'CFBundleIdentifier': rp.BUNDLE_ID, 'CFBundleShortVersionString': CONFIG['display_version'],
                 'CFBundleVersion': str(CONFIG['build_number']), 'SUPublicEDKey': CONFIG['sparkle_public_key'],
                 'SUFeedURL': CONFIG['update_feed_url'], 'LSMinimumSystemVersion': CONFIG['minimum_macos'],
                 'SURequireSignedFeed': True, 'SUVerifyUpdateBeforeExtraction': True, 'MBPreviewBuild': True}
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
        (app / 'Contents/payload').write_bytes(b'payload')
        return app

    def test_configuration_accepts_known_beta(self):
        rp.validate_config(CONFIG)

    def test_configuration_rejects_path_injection(self):
        for version in ['../private', '1.2.3/../../x', '--help', '1.2.3\n', 'release']:
            with self.subTest(version=version), self.assertRaises(rp.ReleaseError):
                rp.validate_config({**CONFIG, 'display_version': version})

    def test_configuration_rejects_boolean_build_number(self):
        with self.assertRaises(rp.ReleaseError): rp.validate_config({**CONFIG, 'build_number': True})

    def test_configuration_preview_flag_must_match(self):
        for patch in [{'preview': False}, {'display_version': '0.5.0'}]:
            with self.assertRaises(rp.ReleaseError): rp.validate_config({**CONFIG, **patch})

    def test_publication_requires_stable_and_public(self):
        stable = {**CONFIG, 'display_version': '0.5.0', 'preview': False}
        for config, private in [(CONFIG, True), (CONFIG, False), (stable, True)]:
            with self.assertRaises(rp.ReleaseError): rp.publication_gate(config, private, True)
        rp.publication_gate(stable, False, True)

    def test_draft_allowed_without_changing_visibility(self):
        rp.publication_gate(CONFIG, True, False)
        rp.publication_gate(CONFIG, False, False)

    def test_checkpoint_is_private_and_valid_json(self):
        target = self.root / 'checkpoint.json'
        rp.atomic_json(target, {'stage': 'processing'})
        self.assertEqual(json.loads(target.read_text())['stage'], 'processing')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_symlink_checkpoint_rejected(self):
        target = self.root / 'target'; target.write_text('original')
        alias = self.root / 'alias'; alias.symlink_to(target)
        with self.assertRaises(rp.ReleaseError): rp.atomic_json(alias, {'x': 1})
        self.assertEqual(target.read_text(), 'original')

    def test_same_release_has_exclusive_lock(self):
        with rp.run_lock(self.run_dir):
            with self.assertRaises(rp.ReleaseError):
                with rp.run_lock(self.run_dir): pass

    def test_bundle_fingerprint_includes_bytes(self):
        app = self.app(); first = rp.tree_digest(app)
        (app / 'Contents/payload').write_bytes(b'changed')
        self.assertNotEqual(first, rp.tree_digest(app))

    def test_bundle_fingerprint_includes_executable_bit(self):
        app = self.app(); first = rp.tree_digest(app)
        (app / 'Contents/payload').chmod(0o755)
        self.assertNotEqual(first, rp.tree_digest(app))

    def test_bundle_fingerprint_rejects_external_symlink(self):
        app = self.app(); (app / 'Contents/escape').symlink_to(self.runtime)
        with self.assertRaises(rp.ReleaseError): rp.tree_digest(app)

    def test_bundle_fingerprint_accepts_internal_symlink(self):
        app = self.app(); (app / 'Contents/link').symlink_to('payload')
        self.assertEqual(rp.tree_digest(app), rp.tree_digest(app))

    def test_bundle_metadata_version_key_and_security_checked(self):
        app = self.app(); rp.app_info(app, CONFIG)
        path = app / 'Contents/Info.plist'
        original = plistlib.loads(path.read_bytes())
        for key, value in [('CFBundleVersion', '1'), ('SUPublicEDKey', 'wrong'),
                           ('SURequireSignedFeed', False), ('SUVerifyUpdateBeforeExtraction', False),
                           ('MBPreviewBuild', False), ('SUFeedURL', 'https://example.com/')]:
            path.write_bytes(plistlib.dumps({**original, key: value}))
            with self.subTest(key=key), self.assertRaises(rp.ReleaseError): rp.app_info(app, CONFIG)

    def test_completed_stage_rejects_modified_bundle(self):
        app = self.app(); self.p.remember_app('build', app)
        self.assertEqual(self.p.reuse_app('build'), app)
        (app / 'Contents/payload').write_text('different')
        with self.assertRaises(rp.ReleaseError): self.p.reuse_app('build')

    def test_archive_metadata_is_developer_id_not_app_store(self):
        info = rp.app_info(self.app(), CONFIG)
        result = rp.xcode_archive_info(info, 'Developer ID Application: Test (ABCDEFGHIJ)', 'ABCDEFGHIJ')
        self.assertEqual(result['ArchiveVersion'], 2)
        self.assertEqual(result['ApplicationProperties']['Team'], 'ABCDEFGHIJ')
        self.assertEqual(result['ApplicationProperties']['ApplicationPath'], 'Applications/Computer Controller.app')

    def test_export_processing_is_not_a_rejection(self):
        self.assertEqual(rp.export_state(65, 'Archive "X" is processing and not ready for distribution.'), 'processing')
        self.assertEqual(rp.export_state(65, 'The archive was rejected'), 'rejected')
        self.assertEqual(rp.export_state(65, 'Could not authenticate'), 'error')
        self.assertEqual(rp.export_state(0, '** EXPORT SUCCEEDED **'), 'accepted')

    def test_notary_resume_never_reuploads(self):
        self.p.state['notary'] = {'archive': '/test/existing.xcarchive', 'status': 'submitting'}
        self.p.runner.run.return_value = (65, 'Archive "X" is processing and not ready for distribution.')
        with self.assertRaises(rp.Pending): self.p.notarize(self.app())
        args = self.p.runner.run.call_args_list
        self.assertEqual(len(args), 1)
        self.assertIn('-exportNotarizedApp', args[0].args[0])
        self.assertNotIn('-exportArchive', args[0].args[0])
        self.assertEqual(json.loads(self.p.path.read_text())['notary']['status'], 'processing')

    def test_notary_unknown_failure_does_not_reupload(self):
        self.p.state['notary'] = {'archive': '/test/existing.xcarchive', 'status': 'unknown'}
        self.p.runner.run.return_value = (65, 'Apple account unavailable')
        with self.assertRaises(rp.ReleaseError): self.p.notarize(self.app())
        self.assertEqual(self.p.runner.run.call_count, 1)
        self.assertIn('-exportNotarizedApp', self.p.runner.run.call_args.args[0])

    def test_completed_notary_reused_not_submitted(self):
        app = self.app(); self.p.remember_app('notarized', app)
        self.p.verify_notarized = mock.Mock()
        self.assertEqual(self.p.notarize(app), app)
        self.p.verify_notarized.assert_called_once_with(app)
        self.p.runner.run.assert_not_called()

    def test_signing_reuses_unchanged_completed_app(self):
        app = self.app(); self.p.remember_app('developer-id', app)
        self.assertEqual(self.p.sign(self.root / 'nonexistent'), app)
        self.p.runner.run.assert_not_called()

    def test_build_reuses_unchanged_completed_app(self):
        app = self.app(); self.p.remember_app('build', app)
        self.assertEqual(self.p.build(), app)
        self.p.runner.run.assert_not_called()

    def test_failed_unit_tests_do_not_checkpoint_success(self):
        self.p.runner.run.side_effect = rp.ReleaseError('tests failed')
        with self.assertRaises(rp.ReleaseError): self.p.tests()
        self.assertNotIn('unit-tests', self.p.state['stages'])

    def test_completed_unit_tests_not_repeated(self):
        self.p.state['stages']['unit-tests'] = {'passed': True}
        self.p.tests(); self.p.runner.run.assert_not_called()

    def test_changed_source_stops_release(self):
        self.p.fresh_source.return_value = 'b' * 40
        with self.assertRaises(rp.ReleaseError): self.p.require_same_source()

    def test_binding_mismatch_rejected(self):
        self.p.state['binding'] = {'config': CONFIG, 'source_commit': 'b' * 40}
        with self.assertRaises(rp.ReleaseError): self.p.preflight()
        self.p.runner.json.assert_not_called()

    def test_existing_package_bytes_are_immutable(self):
        folder = self.root / 'files'; folder.mkdir()
        file = folder / 'app.zip'; file.write_bytes(b'original')
        self.p.state['stages']['sparkle'] = {'folder': str(folder), 'sha256': {file.name: rp.digest(file)}}
        self.assertEqual(self.p.package(self.root / 'unused'), folder)
        file.write_bytes(b'changed')
        with self.assertRaises(rp.ReleaseError): self.p.package(self.root / 'unused')

    def test_prepare_only_never_calls_github(self):
        app = self.app()
        for name in ['preflight', 'tests', 'verify_notarized', 'smoke', 'github']:
            setattr(self.p, name, mock.Mock())
        self.p.reuse_app = mock.Mock(return_value=app)
        self.p.package = mock.Mock(return_value=self.root / 'artifacts')
        self.p.run()
        self.p.github.assert_not_called()
        self.assertFalse(self.p.state['result']['running_bridge_changed'])

    def test_failed_smoke_prevents_packaging_and_upload(self):
        self.p.mode = 'draft'
        self.p.preflight = mock.Mock(); self.p.tests = mock.Mock()
        self.p.reuse_app = mock.Mock(return_value=self.app()); self.p.verify_notarized = mock.Mock()
        self.p.smoke = mock.Mock(side_effect=rp.ReleaseError('smoke failed'))
        self.p.package = mock.Mock(); self.p.github = mock.Mock()
        with self.assertRaises(rp.ReleaseError): self.p.run()
        self.p.package.assert_not_called(); self.p.github.assert_not_called()

    def test_pipeline_order_from_new_build_through_draft(self):
        self.p.mode = 'draft'; order = []; app = self.app()
        self.p.preflight = lambda: order.append('preflight')
        self.p.tests = lambda: order.append('tests')
        self.p.reuse_app = lambda _: None
        self.p.build = lambda: (order.append('build') or app)
        self.p.sign = lambda _: (order.append('sign') or app)
        self.p.notarize = lambda _: (order.append('notarize') or app)
        self.p.verify_notarized = lambda _: order.append('verify')
        self.p.smoke = lambda _: order.append('smoke')
        self.p.package = lambda _: (order.append('package') or self.root)
        self.p.github = lambda _: order.append('github')
        self.p.run()
        self.assertEqual(order, ['preflight', 'tests', 'build', 'sign', 'notarize', 'verify', 'smoke', 'package', 'github'])

    def test_github_auth_failure_not_treated_as_missing_release(self):
        self.p.tag_gate = mock.Mock()
        self.p.mode = 'draft'
        self.p.runner.json.return_value = {'isPrivate': True}
        self.p.runner.run.return_value = (1, 'authentication required')
        with self.assertRaises(rp.ReleaseError): self.p.github(self.root)
        self.assertFalse(any('create' in c.args[0] for c in self.p.runner.run.call_args_list))

    def test_github_commit_collision_does_not_overwrite(self):
        self.p.tag_gate = mock.Mock()
        self.p.mode = 'draft'
        self.p.runner.json.return_value = {'isPrivate': True}
        self.p.runner.run.return_value = (0, json.dumps({'targetCommitish': 'wrong', 'isPrerelease': True}))
        with self.assertRaises(rp.ReleaseError): self.p.github(self.root)
        self.assertFalse(any('upload' in c.args[0] or 'edit' in c.args[0] for c in self.p.runner.run.call_args_list))

    def test_missing_tag_is_allowed_without_creating_it_in_preflight(self):
        self.p.runner.run.return_value = (1, 'HTTP 404: Not Found')
        self.p.tag_gate()
        self.assertEqual(self.p.runner.run.call_count, 1)

    def test_tag_auth_error_blocks(self):
        self.p.runner.run.return_value = (1, 'HTTP 401: Unauthorized')
        with self.assertRaises(rp.ReleaseError): self.p.tag_gate()

    def test_tag_for_another_commit_blocks(self):
        self.p.runner.run.return_value = (0, json.dumps({'object': {'type': 'commit', 'sha': 'wrong'}}))
        with self.assertRaises(rp.ReleaseError): self.p.tag_gate()

    def test_annotated_tag_is_dereferenced_and_verified(self):
        self.p.runner.run.return_value = (0, json.dumps({'object': {'type': 'tag', 'sha': 'tag-sha'}}))
        self.p.runner.json.return_value = {'object': {'type': 'commit', 'sha': COMMIT}}
        self.p.tag_gate()
        self.p.runner.json.assert_called_once()

    def test_upload_intent_is_saved_before_external_request(self):
        app = self.app()
        import shutil
        def run(args, label, **kwargs):
            if label == 'archive-copy':
                Path(args[2]).parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(args[1], args[2])
                return 0, ''
            if label == 'notary-submit':
                saved = json.loads(self.p.path.read_text())
                self.assertEqual(saved['notary']['status'], 'submitting')
                self.assertIn('developer-id', plistlib.loads((self.run_dir / 'notary/ExportOptions.plist').read_bytes())['method'])
                raise rp.Pending('network outcome unknown')
            raise AssertionError(label)
        self.p.runner.run.side_effect = run
        with self.assertRaises(rp.Pending): self.p.notarize(app)
        self.assertEqual(json.loads(self.p.path.read_text())['notary']['status'], 'submitting')

    def test_remote_hash_mismatch_never_publishes(self):
        self.p.mode = 'draft'; self.p.tag_gate = mock.Mock()
        self.p.state['stages']['sparkle'] = {'sha256': {'app.zip': 'expected'}}
        release = {'targetCommitish': COMMIT, 'isPrerelease': True, 'isDraft': True,
                   'url': 'test', 'assets': [{'name': 'app.zip', 'apiUrl': 'https://api.github.com/repos/owner/mac-bridge/releases/assets/123'}]}
        self.p.runner.run.return_value = (0, json.dumps(release))
        self.p.runner.json.side_effect = [{'isPrivate': True}, release, {'digest': 'sha256:wrong'}]
        with self.assertRaises(rp.ReleaseError): self.p.github(self.root)
        self.assertFalse(any('edit' in c.args[0] for c in self.p.runner.run.call_args_list))

    def test_complete_draft_is_idempotent_and_not_published(self):
        self.p.mode = 'draft'; self.p.tag_gate = mock.Mock()
        self.p.state['stages']['sparkle'] = {'sha256': {'app.zip': 'expected'}}
        release = {'targetCommitish': COMMIT, 'isPrerelease': True, 'isDraft': True,
                   'url': 'test', 'assets': [{'name': 'app.zip', 'apiUrl': 'https://api.github.com/repos/owner/mac-bridge/releases/assets/123'}]}
        self.p.runner.run.return_value = (0, json.dumps(release))
        self.p.runner.json.side_effect = [{'isPrivate': True}, release, {'digest': 'sha256:expected'}]
        self.p.github(self.root)
        self.assertTrue(self.p.state['stages']['github']['draft'])
        self.assertFalse(any('upload' in c.args[0] or 'edit' in c.args[0] or 'create' in c.args[0] for c in self.p.runner.run.call_args_list))

    def test_extra_unverified_remote_asset_blocks(self):
        self.p.mode = 'draft'; self.p.tag_gate = mock.Mock()
        self.p.state['stages']['sparkle'] = {'sha256': {'app.zip': 'expected'}}
        release = {'targetCommitish': COMMIT, 'isPrerelease': True, 'isDraft': True,
                   'assets': [{'name': 'unverified.exe'}]}
        self.p.runner.run.return_value = (0, json.dumps(release))
        self.p.runner.json.return_value = {'isPrivate': True}
        with self.assertRaises(rp.ReleaseError): self.p.github(self.root)

    def test_no_automatic_privacy_or_keychain_changes_in_pipeline(self):
        source = (Path(__file__).resolve().parents[1] / 'packaging/scripts/release_pipeline.py').read_text()
        for forbidden in ['--visibility', '--clobber', 'set-key-partition-list', 'dump-keychain', 'security delete', 'gh auth token']:
            self.assertNotIn(forbidden, source)


if __name__ == '__main__': unittest.main()
