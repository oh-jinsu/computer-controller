import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mac_bridge import platform_support as ps


class ProductNamingTests(unittest.TestCase):
    def test_fresh_macos_data_path_uses_computer_controller(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(ps, 'IS_WINDOWS', False),
            mock.patch.object(ps, 'IS_MAC', True),
            mock.patch.object(ps, 'IS_LINUX', False),
            mock.patch.object(ps.Path, 'home', return_value=Path(tmp)),
        ):
            expected = Path(tmp) / 'Library/Application Support/Computer Controller'
            self.assertEqual(ps.app_data_dir(), expected)

    def test_existing_legacy_macos_data_path_is_reused_until_migrated(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(ps, 'IS_WINDOWS', False),
            mock.patch.object(ps, 'IS_MAC', True),
            mock.patch.object(ps, 'IS_LINUX', False),
            mock.patch.object(ps.Path, 'home', return_value=Path(tmp)),
        ):
            base = Path(tmp) / 'Library/Application Support'
            legacy = base / 'Mac Bridge'
            legacy.mkdir(parents=True)
            self.assertEqual(ps.app_data_dir(), legacy)
            current = base / 'Computer Controller'
            current.mkdir()
            self.assertEqual(ps.app_data_dir(), current)

    def test_fresh_windows_data_path_uses_computer_controller(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(ps, 'IS_WINDOWS', True),
            mock.patch.object(ps, 'IS_MAC', False),
            mock.patch.object(ps, 'IS_LINUX', False),
            mock.patch.dict(os.environ, {'LOCALAPPDATA': tmp}, clear=False),
        ):
            self.assertEqual(ps.app_data_dir(), Path(tmp) / 'Computer Controller')


if __name__ == '__main__':
    unittest.main()
