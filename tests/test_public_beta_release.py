"""Offline tests for public beta gates and source/binary correspondence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_beta_pipeline', ROOT / 'packaging/scripts/release_pipeline.py')
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


class PublicBetaTests(unittest.TestCase):
    def test_beta_requires_public_repository(self):
        with self.assertRaises(rp.ReleaseError):
            rp.prerelease_gate({'preview': True}, True)

    def test_beta_does_not_relabel_stable(self):
        with self.assertRaises(rp.ReleaseError):
            rp.prerelease_gate({'preview': False}, False)

    def test_public_beta_allowed(self):
        rp.prerelease_gate({'preview': True}, False)

    def test_stable_gate_still_refuses_beta(self):
        with self.assertRaises(rp.ReleaseError):
            rp.publication_gate({'preview': True}, False, True)

    def test_source_artifact_must_match_app_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'Computer Controller.app'
            record = app / 'Contents/Resources/Licenses/Distribution/SOURCE-ARCHIVE.json'
            record.parent.mkdir(parents=True)
            source = root / '.cache/distribution/Third-Party-Sources.tar.gz'
            source.parent.mkdir(parents=True); source.write_bytes(b'fixture source bytes')
            record.write_text(json.dumps({'filename': source.name, 'sha256': rp.digest(source)}))
            with mock.patch.object(rp, 'ROOT', root):
                self.assertEqual(rp.distribution_source(app), source)
                source.write_bytes(b'different source')
                with self.assertRaises(rp.ReleaseError): rp.distribution_source(app)

    def test_source_record_cannot_select_arbitrary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / 'Computer Controller.app'
            record = app / 'Contents/Resources/Licenses/Distribution/SOURCE-ARCHIVE.json'
            record.parent.mkdir(parents=True)
            record.write_text(json.dumps({'filename': '../private-file'}))
            with self.assertRaises(rp.ReleaseError): rp.distribution_source(app)

    def test_beta_uses_non_latest_publication(self):
        text = (ROOT / 'packaging/scripts/release_pipeline.py').read_text()
        self.assertIn("['--prerelease', '--latest=false']", text)
        self.assertIn("attempt / source_archive.name", text)
        self.assertIn("distribution_source(app)", text)
        self.assertNotIn('--visibility', text)

    def test_readme_is_short_and_links_extended_guide(self):
        text = (ROOT / 'README.md').read_text()
        self.assertLess(len(text.splitlines()), 50)
        self.assertIn('docs/INSTALL.md', text)
        self.assertIn('공개 베타', text)
        for word in ['git clone', 'brew install', 'pip install']:
            self.assertNotIn(word, text)


if __name__ == '__main__': unittest.main()
