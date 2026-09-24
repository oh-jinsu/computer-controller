import os
from pathlib import Path
import unittest
from unittest import mock
from mac_bridge.policy import clean_env

class BytecodeEnvironmentTests(unittest.TestCase):
    def test_clean_child_environment_prevents_bundle_mutation(self):
        with mock.patch.dict(os.environ, {'PYTHONDONTWRITEBYTECODE': '0', 'PYTHONNOUSERSITE': '0', 'PYTHONPATH': '/untrusted'}):
            env = clean_env(Path('/example/home'))
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')
        self.assertNotIn('PYTHONPATH', env)

if __name__ == '__main__': unittest.main()
