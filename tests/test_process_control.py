from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mac_bridge import process_control as pc


class ProcessControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name).resolve() / 'project'
        self.workspace.mkdir()
        self.rows = [
            {'pid': 100, 'ppid': 50, 'cpu': '0.1', 'memory': '0.2', 'command': 'python -m mac_bridge.server --root bridge'},
            {'pid': 300, 'ppid': 1, 'cpu': '1.0', 'memory': '2.0', 'command': 'python dev_server.py'},
            {'pid': 301, 'ppid': 300, 'cpu': '0.5', 'memory': '1.0', 'command': 'node child.js'},
            {'pid': 400, 'ppid': 1, 'cpu': '3.5', 'memory': '4.0', 'command': '/Applications/Godot.app/Contents/MacOS/Godot --editor'},
            {'pid': 500, 'ppid': 1, 'cpu': '0.0', 'memory': '0.1', 'command': 'python unrelated.py'},
            {'pid': 600, 'ppid': 1, 'cpu': '0.0', 'memory': '0.1', 'command': '/Users/me/Applications/Computer Controller.app/Contents/MacOS/MacBridge'},
            {'pid': 601, 'ppid': 1, 'cpu': '0.0', 'memory': '0.1', 'command': '/Users/me/Applications/Mac Bridge.app/Contents/MacOS/MacBridge'},
            {'pid': 700, 'ppid': 1, 'cpu': '0.0', 'memory': '0.1', 'command': 'zsh'},
        ]
        self.cwds = {
            100: str(self.workspace),
            300: '/tmp',
            301: '/tmp',
            400: str(self.workspace / 'game'),
            500: '/tmp',
            600: str(self.workspace),
            601: str(self.workspace),
            700: str(self.workspace),
        }
        (self.workspace / 'game').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def inventory(self, bridge_pids=None, query=''):
        with mock.patch.object(pc, 'raw_process_rows', return_value=(self.rows, self.cwds)):
            return pc.inventory(self.workspace, set(bridge_pids or ()), query=query,
                                limit=100, current_pid=100)

    def test_project_and_bridge_descendants_are_killable(self):
        rows = {row['pid']: row for row in self.inventory({300})}
        self.assertTrue(rows[300]['killable'])
        self.assertTrue(rows[301]['killable'])
        self.assertTrue(rows[400]['killable'])
        self.assertFalse(rows[500]['killable'])
        self.assertTrue(rows[300]['bridge_owned'])
        self.assertTrue(rows[301]['bridge_owned'])
        self.assertTrue(rows[400]['project_related'])

    def test_bridge_core_is_never_killable_even_in_workspace(self):
        rows = {row['pid']: row for row in self.inventory()}
        self.assertFalse(rows[100]['killable'])
        self.assertFalse(rows[600]['killable'])
        self.assertFalse(rows[601]['killable'])
        self.assertFalse(rows[700]['killable'])
        self.assertIsNone(rows[100]['kill_token'])
        self.assertIsNone(rows[600]['kill_token'])

    def test_query_filters_safe_display(self):
        rows = self.inventory(query='godot')
        self.assertEqual([row['pid'] for row in rows], [400])
        self.assertEqual(rows[0]['name'], 'Godot.app')

    def test_kill_requires_fresh_matching_token(self):
        with mock.patch.object(pc, 'raw_process_rows', return_value=(self.rows, self.cwds)):
            rows = pc.inventory(self.workspace, set(), limit=100, current_pid=100)
            godot = next(row for row in rows if row['pid'] == 400)
            verified = pc.validate_kill(self.workspace, set(), 400, godot['kill_token'], current_pid=100)
            self.assertEqual(verified['pid'], 400)
            with self.assertRaisesRegex(ValueError, 'identity changed|freshly observed'):
                pc.validate_kill(self.workspace, set(), 400, 'bad-token', current_pid=100)
            with self.assertRaisesRegex(ValueError, 'bridge-owned or selected-project'):
                pc.validate_kill(self.workspace, set(), 500, 'anything', current_pid=100)

    def test_kill_plan_is_descendants_first(self):
        with mock.patch.object(pc, 'raw_process_rows', return_value=(self.rows, self.cwds)):
            rows = pc.inventory(self.workspace, {300}, limit=100, current_pid=100)
            root = next(row for row in rows if row['pid'] == 300)
            plan = pc.validate_kill_plan(self.workspace, {300}, 300, root['kill_token'], current_pid=100)
        self.assertEqual([row['pid'] for row in plan], [301, 300])
        self.assertEqual([row['tree_depth'] for row in plan], [1, 0])


if __name__ == '__main__':
    unittest.main()
