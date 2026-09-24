"""Pure upload/form guard tests; no real browser, credentials or remote transfer."""
import os
from pathlib import Path
import tempfile
import unittest
from mac_bridge.browser_actions import form_fields, upload_files, check_upload_unchanged, FormField
from mac_bridge.policy import Policy, MacError


class BrowserActionValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.work = self.base / 'work'; self.work.mkdir()
        self.state = self.base / 'app'; self.state.mkdir()
        self.policy = Policy(self.state, self.work)
        self.file = self.work / 'attachment.txt'; self.file.write_text('fixture only')

    def tearDown(self): self.tmp.cleanup()

    def test_regular_workspace_file(self):
        items = upload_files(self.policy, ['attachment.txt'])
        self.assertEqual(check_upload_unchanged(self.policy, items), [str(self.file)])

    def test_missing_file(self):
        with self.assertRaises(MacError): upload_files(self.policy, ['missing'])

    def test_directory_rejected(self):
        with self.assertRaises(MacError): upload_files(self.policy, ['.'])

    def test_outside_workspace(self):
        p = self.base / 'outside.txt'; p.write_text('private')
        with self.assertRaises(MacError): upload_files(self.policy, [str(p)])

    def test_internal_secret_paths(self):
        for name in ['.env', 'id_rsa', 'private.key', '.state/key.txt']:
            with self.assertRaises(MacError): upload_files(self.policy, [name])

    def test_symlink_rejected(self):
        p = self.work / 'link'; p.symlink_to(self.file)
        with self.assertRaises(MacError): upload_files(self.policy, [str(p)])

    def test_hardlink_rejected(self):
        p = self.work / 'link'; os.link(self.file, p)
        with self.assertRaises(MacError): upload_files(self.policy, [str(p)])

    def test_source_changed_before_execution(self):
        before = upload_files(self.policy, [str(self.file)])
        self.file.write_text('different')
        with self.assertRaises(MacError): check_upload_unchanged(self.policy, before)

    def test_source_replaced_before_execution(self):
        before = upload_files(self.policy, [str(self.file)])
        self.file.unlink(); self.file.write_text('fixture only')
        with self.assertRaises(MacError): check_upload_unchanged(self.policy, before)

    def test_duplicates_empty_or_too_many(self):
        for paths in [[], [str(self.file)] * 2, [str(self.file)] * 21]:
            with self.assertRaises(MacError): upload_files(self.policy, paths)

    def test_batch_limit_without_reading_large_file(self):
        with self.file.open('wb') as f: f.truncate(32 * 1024**3 + 1)
        with self.assertRaises(MacError): upload_files(self.policy, [str(self.file)])

    def field(self, **changes):
        return {'target':'e1', 'name':'Title', 'type':'textbox', 'value':'Example', **changes}

    def test_form_accepts_model_and_dict(self):
        self.assertEqual(form_fields([FormField(**self.field())]), [self.field()])
        self.assertEqual(form_fields([self.field()]), [self.field()])

    def test_no_arbitrary_selector_or_extra_parameters(self):
        for f in [self.field(target='body'), self.field(target=''), self.field(submit=True)]:
            with self.assertRaises(MacError): form_fields([f])

    def test_no_duplicate_targets(self):
        with self.assertRaises(MacError): form_fields([self.field(), self.field()])

    def test_boolean_value_validation(self):
        with self.assertRaises(MacError): form_fields([self.field(type='checkbox',value='maybe')])
        self.assertEqual(form_fields([self.field(type='checkbox',value='true')])[0]['value'],'true')

    def test_form_size_bounds(self):
        for fields in [[], [self.field()] * 21, [self.field(value='x'*8001)],
                       [self.field(target=f'e{i}',value='x'*8000) for i in range(5)]]:
            with self.assertRaises(MacError): form_fields(fields)


if __name__ == '__main__': unittest.main()
