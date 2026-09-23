"""Offline publisher guards. Signature subprocess calls are mocked here;
actual Sparkle verification/install tests live in packaging/scripts/smoke_sparkle_update.py.
"""
import base64
import importlib.util
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'packaging/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

prepare = load('prepare_release')
publish = load('update_draft')

class ExistingArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.app = self.root / 'Mac Bridge.app'; (self.app / 'Contents').mkdir(parents=True)
        (self.app / 'Contents/source.py').write_bytes(b'original')
        self.archive = self.root / 'existing.zip'
    def tearDown(self): self.tmp.cleanup()
    def make(self, entries=None):
        with zipfile.ZipFile(self.archive, 'w') as z:
            for name, data in (entries or [('Mac Bridge.app/Contents/source.py', b'original')]):
                z.writestr(name, data)
    def test_existing_bytes_match_without_recompression(self):
        self.make(); before = self.archive.read_bytes()
        prepare.verify_existing_archive(self.archive, self.app)
        self.assertEqual(self.archive.read_bytes(), before)
    def test_changed_file_rejected(self):
        self.make([('Mac Bridge.app/Contents/source.py', b'changed')])
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_missing_file_rejected(self):
        self.make(); (self.app / 'Contents/missing.py').write_text('x')
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_extra_file_rejected(self):
        self.make([('Mac Bridge.app/Contents/source.py', b'original'), ('Mac Bridge.app/Contents/unknown', b'x')])
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_traversal_rejected(self):
        self.make([('Mac Bridge.app/../escape', b'x')])
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_absolute_entry_rejected(self):
        self.make([('/Mac Bridge.app/Contents/source.py', b'original')])
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_duplicate_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            self.make([('Mac Bridge.app/Contents/source.py', b'original')]*2)
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_other_application_rejected(self):
        self.make([('Another.app/Contents/source.py', b'original')])
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)
    def test_archive_symlink_rejected(self):
        self.make(); alias = self.root / 'alias.zip'; alias.symlink_to(self.archive)
        with self.assertRaises(ValueError): prepare.verify_existing_archive(alias, self.app)
    def test_matching_internal_symlink(self):
        (self.app / 'Contents/link').symlink_to('source.py'); self.make()
        info = zipfile.ZipInfo('Mac Bridge.app/Contents/link'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, 'a') as z: z.writestr(info, 'source.py')
        prepare.verify_existing_archive(self.archive, self.app)
    def test_different_symlink_rejected(self):
        (self.app / 'Contents/link').symlink_to('source.py'); self.make()
        info = zipfile.ZipInfo('Mac Bridge.app/Contents/link'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, 'a') as z: z.writestr(info, '../../elsewhere')
        with self.assertRaises(ValueError): prepare.verify_existing_archive(self.archive, self.app)

class SignedMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.config = {'display_version':'0.5.0-beta.1','build_number':50001,
            'github_repository':'owner/bridge','sparkle_keychain_account':'unit-test-no-keychain-access'}
        self.name = 'Mac-Bridge-0.5.0-beta.1-macos26-arm64.zip'
        (self.root / self.name).write_bytes(b'fixture')
        self.rss = ET.Element('rss'); channel = ET.SubElement(self.rss,'channel'); item = ET.SubElement(channel,'item')
        self.version = ET.SubElement(item,'{' + publish.NS + '}version'); self.version.text = '50001'
        self.enclosure = ET.SubElement(item,'enclosure',{
            'url':'https://github.com/owner/bridge/releases/download/v0.5.0-beta.1/' + self.name,
            'length':'7','{' + publish.NS + '}edSignature':base64.b64encode(bytes(64)).decode()})
        self.save()
    def tearDown(self): self.tmp.cleanup()
    def save(self): (self.root / 'appcast.xml').write_bytes(ET.tostring(self.rss))
    def test_valid_metadata_verifies_feed_then_archive(self):
        with mock.patch.object(publish,'command') as call:
            result = publish.verify_bundle_metadata(self.root,self.config)
        self.assertEqual(result['name'],self.name); self.assertEqual(call.call_count,2)
        self.assertIn('--verify',call.call_args_list[0].args[0])
    def test_wrong_url_rejected(self):
        self.enclosure.set('url','https://unrelated.example/archive.zip'); self.save()
        with mock.patch.object(publish,'command') as call, self.assertRaises(ValueError):
            publish.verify_bundle_metadata(self.root,self.config)
        self.assertEqual(call.call_count,1)
    def test_wrong_version_rejected(self):
        self.version.text='50002'; self.save()
        with mock.patch.object(publish,'command'), self.assertRaises(ValueError):
            publish.verify_bundle_metadata(self.root,self.config)
    def test_wrong_length_rejected(self):
        self.enclosure.set('length','8'); self.save()
        with mock.patch.object(publish,'command'), self.assertRaises(ValueError):
            publish.verify_bundle_metadata(self.root,self.config)
    def test_feed_signature_failure_prevents_archive_verification(self):
        with mock.patch.object(publish,'command',side_effect=subprocess.CalledProcessError(1,'sign_update')) as call:
            with self.assertRaises(subprocess.CalledProcessError): publish.verify_bundle_metadata(self.root,self.config)
        self.assertEqual(call.call_count,1)
    def test_feed_symlink_rejected_before_verification(self):
        feed=self.root/'appcast.xml'; feed.rename(self.root/'actual.xml'); feed.symlink_to(self.root/'actual.xml')
        with mock.patch.object(publish,'command') as call, self.assertRaises(ValueError):
            publish.verify_bundle_metadata(self.root,self.config)
        call.assert_not_called()

if __name__=='__main__': unittest.main()
