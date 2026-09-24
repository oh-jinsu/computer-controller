"""Business-logic tests using SDK/engine stubs. These DO NOT test MCP transport."""
from __future__ import annotations
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Data:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.isError = kwargs.get('isError', False)


class FakeMCP:
    def __init__(self, *a, **kw): self.tools = {}; self.annotations = {}
    def tool(self, **kw):
        def decorate(f):
            self.tools[f.__name__] = f; self.annotations[f.__name__] = kw.get('annotations'); return f
        return decorate


class FakeDC:
    def __init__(self, root, policy):
        self.policy = policy; self.calls = []; self.pids = set(); self.version = 'stub'; self.session = object()
    async def invoke(self, name, args, **kw):
        if not kw.get('allow_paused'): self.policy.require_active()
        self.calls.append((name, args))
        if name == 'write_file': Path(args['path']).write_text(args['content'])
        if name == 'edit_block':
            path = Path(args['file_path'])
            path.write_text(path.read_text().replace(args['old_string'], args['new_string'], 1))
        return Data(content=[], structuredContent={'called': name})
    def require_owned(self, pid):
        from mac_bridge.policy import MacError
        if pid not in self.pids: raise MacError('Not owned')
    async def stop_owned(self): return {'requested_stop': [], 'unconfirmed': []}


class FakeBrowser:
    def __init__(self, root, policy):
        self.root = root; self.policy = policy; self.calls = []; self.closed = 0
    def status(self):
        return {'installed': True, 'running': bool(self.calls), 'personal_profile_access': False}
    async def invoke(self, name, args, *, mode=None):
        self.policy.require_active()
        self.calls.append((name, args, mode))
        return Data(content=[], structuredContent={'called': name})
    async def close(self):
        self.closed += 1
        return {'closed': True}


class LogicTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        modules = {}
        for name in ['mcp', 'mcp.server', 'mcp.server.fastmcp', 'mcp.types']:
            modules[name] = types.ModuleType(name)
        modules['mcp.server.fastmcp'].FastMCP = FakeMCP
        for name in ['CallToolResult', 'ImageContent', 'TextContent', 'ToolAnnotations']:
            setattr(modules['mcp.types'], name, Data)
        cls.modules_patch = mock.patch.dict(sys.modules, modules)
        cls.modules_patch.start()
        cls.server = importlib.import_module('mac_bridge.server')

    @classmethod
    def tearDownClass(cls):
        cls.modules_patch.stop()
        # Keep stubs scoped to this logic test process.
        sys.modules.pop('mac_bridge.server', None)
        sys.modules.pop('mac_bridge.responses', None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        parent = Path(self.tmp.name).resolve(); self.root = parent / 'bridge'; self.project = parent / 'project'
        (self.root / '.state').mkdir(parents=True); self.project.mkdir()
        (self.root / '.state/mac-settings.json').write_text(json.dumps({'workspace': str(self.project)}))
        from mac_bridge.approvals import set_approval_mode
        set_approval_mode(self.root, 'ask')
        self.approver = mock.Mock(); self.approver.approve.return_value = False
        def build_dc(root, policy):
            self.dc = FakeDC(root, policy); return self.dc
        def build_browser(root, policy):
            self.browser = FakeBrowser(root, policy); return self.browser
        with mock.patch.object(self.server, 'DesktopClient', side_effect=build_dc), mock.patch.object(self.server, 'NativeApproval', return_value=self.approver), mock.patch.object(self.server, 'BrowserClient', side_effect=build_browser):
            self.mcp = self.server.create_server(self.root)

    def tearDown(self): self.tmp.cleanup()

    async def test_tools_and_write_annotations(self):
        self.assertEqual(len(self.mcp.tools), 29)
        self.assertFalse(self.mcp.annotations['mac_start_process'].readOnlyHint)
        self.assertFalse(self.mcp.annotations['mac_write_file'].readOnlyHint)
        self.assertTrue(self.mcp.annotations['mac_read_file'].readOnlyHint)
        self.assertNotIn('mac_resume', self.mcp.tools)
        for name in ('start_extraction', 'get_extraction', 'get_frame', 'list_local_videos', 'bridge_status'):
            self.assertNotIn(name, self.mcp.tools)

    async def test_denial_does_not_run_command(self):
        r = await self.mcp.tools['mac_start_process']('echo unsafe')
        self.assertTrue(r.isError); self.assertEqual(self.dc.calls, [])

    async def test_approval_runs_only_shown_command(self):
        self.approver.approve.return_value = True
        r = await self.mcp.tools['mac_start_process']('echo approved')
        self.assertFalse(r.isError); self.assertEqual(len(self.dc.calls), 1)
        self.assertIn('echo approved', self.dc.calls[0][1]['command'])

    async def test_pause_after_approval_prevents_execution(self):
        def approve(*args): self.dc.policy.pause(); return True
        self.approver.approve.side_effect = approve
        r = await self.mcp.tools['mac_start_process']('echo approved')
        self.assertTrue(r.isError); self.assertEqual(self.dc.calls, [])

    async def test_write_denied_keeps_original(self):
        p = self.project / 'a.txt'; p.write_text('before')
        r = await self.mcp.tools['mac_write_file']('a.txt', 'after')
        self.assertTrue(r.isError); self.assertEqual(p.read_text(), 'before')
        self.assertFalse((self.root / '.state/file-backups').exists())

    async def test_write_approved_backs_up_original(self):
        p = self.project / 'a.txt'; p.write_text('before')
        self.approver.approve.return_value = True
        r = await self.mcp.tools['mac_write_file']('a.txt', 'after')
        self.assertFalse(r.isError); self.assertEqual(p.read_text(), 'after')
        backups = list((self.root / '.state/file-backups').rglob('a.txt'))
        self.assertEqual(backups[0].read_text(), 'before')

    async def test_external_edit_during_approval_preserved(self):
        p = self.project / 'a.txt'; p.write_text('before')
        def approve(*args): p.write_text('USER_EDIT'); return True
        self.approver.approve.side_effect = approve
        r = await self.mcp.tools['mac_write_file']('a.txt', 'after')
        self.assertTrue(r.isError); self.assertEqual(p.read_text(), 'USER_EDIT')
        self.assertEqual(self.dc.calls, [])

    async def test_ambiguous_edit_refused_before_approval(self):
        (self.project / 'a.txt').write_text('before before')
        r = await self.mcp.tools['mac_edit_file']('a.txt', 'before', 'after')
        self.assertTrue(r.isError); self.approver.approve.assert_not_called()

    async def test_foreign_pid_not_read_or_stopped(self):
        for tool in ['mac_process_output', 'mac_stop_process']:
            r = await self.mcp.tools[tool](1)
            self.assertTrue(r.isError)
        self.assertEqual(self.dc.calls, [])

    async def test_paused_read_rejected(self):
        self.dc.policy.pause()
        r = await self.mcp.tools['mac_list_directory']()
        self.assertTrue(r.isError); self.assertEqual(self.dc.calls, [])


    def always(self):
        from mac_bridge.approvals import set_approval_mode
        set_approval_mode(self.root, 'always')

    async def test_always_command_skips_native_dialog_and_records(self):
        self.always()
        r = await self.mcp.tools['mac_start_process']('pwd')
        self.assertFalse(r.isError)
        self.approver.approve.assert_not_called()
        self.assertEqual(len(self.dc.calls), 1)
        states = [row['state'] for row in self.dc.policy.history()]
        self.assertIn('auto_approved', states)
        self.assertEqual(states[-1], 'completed')

    async def test_always_write_keeps_backup(self):
        self.always()
        p = self.project / 'a.txt'; p.write_text('before')
        r = await self.mcp.tools['mac_write_file']('a.txt', 'after')
        self.assertFalse(r.isError)
        self.approver.approve.assert_not_called()
        self.assertEqual(p.read_text(), 'after')
        backups = list((self.root / '.state/file-backups').rglob('a.txt'))
        self.assertEqual(backups[0].read_text(), 'before')

    async def test_always_edit_keeps_exact_match_and_backup(self):
        self.always()
        p = self.project / 'a.txt'; p.write_text('before')
        r = await self.mcp.tools['mac_edit_file']('a.txt', 'before', 'after')
        self.assertFalse(r.isError)
        self.assertEqual(p.read_text(), 'after')
        self.approver.approve.assert_not_called()
        self.assertEqual(list((self.root / '.state/file-backups').rglob('a.txt'))[0].read_text(), 'before')
        p.write_text('x x')
        r = await self.mcp.tools['mac_edit_file']('a.txt', 'x', 'y')
        self.assertTrue(r.isError)
        self.assertEqual(p.read_text(), 'x x')

    async def test_always_input_still_requires_owned_pid(self):
        self.always()
        r = await self.mcp.tools['mac_send_input'](123, 'hello')
        self.assertTrue(r.isError)
        self.dc.pids.add(123)
        r = await self.mcp.tools['mac_send_input'](123, 'hello')
        self.assertFalse(r.isError)
        self.approver.approve.assert_not_called()
        self.assertEqual(self.dc.calls[-1][0], 'interact_with_process')

    async def test_always_never_bypasses_pause(self):
        self.always()
        self.dc.policy.pause()
        r = await self.mcp.tools['mac_start_process']('pwd')
        self.assertTrue(r.isError)
        self.assertEqual(self.dc.calls, [])
        self.approver.approve.assert_not_called()

    async def test_always_keeps_path_and_credentials_guardrails(self):
        self.always()
        for path in ['../outside.txt', '.env', str(self.root / 'run_server.py')]:
            r = await self.mcp.tools['mac_write_file'](path, 'not written')
            self.assertTrue(r.isError, path)
        self.assertEqual(self.dc.calls, [])

    async def test_revert_to_ask_applies_to_existing_server(self):
        from mac_bridge.approvals import set_approval_mode
        self.always()
        set_approval_mode(self.root, 'ask')
        r = await self.mcp.tools['mac_start_process']('pwd')
        self.assertTrue(r.isError)
        self.approver.approve.assert_called_once()
        self.assertEqual(self.dc.calls, [])

    async def test_mode_change_while_awaiting_approval_cancels_request(self):
        def approve(*args):
            self.always()
            return True
        self.approver.approve.side_effect = approve
        r = await self.mcp.tools['mac_start_process']('pwd')
        self.assertTrue(r.isError)
        self.assertEqual(self.dc.calls, [])

    async def test_revoke_always_just_before_execution_cancels_request(self):
        from mac_bridge.approvals import set_approval_mode
        self.always()
        original = self.dc.policy.record
        def record(action, args, state):
            original(action, args, state)
            if state == 'auto_approved':
                set_approval_mode(self.root, 'ask')
        with mock.patch.object(self.dc.policy, 'record', side_effect=record):
            r = await self.mcp.tools['mac_start_process']('pwd')
        self.assertTrue(r.isError)
        self.assertEqual(self.dc.calls, [])

    async def test_status_reports_persistent_mode(self):
        self.always()
        with mock.patch.object(self.server, 'screen_permission', return_value=False):
            r = await self.mcp.tools['mac_status']()
        self.assertEqual(r.structuredContent['approval_mode'], 'always')
        self.assertTrue(r.structuredContent['approval_mode_persistent'])
        self.assertFalse(r.structuredContent['terminal_is_sandboxed'])

    async def test_invalid_setting_does_not_run_or_prompt(self):
        (self.root / '.state/approval-settings.json').write_text('{"schema":1,"mode":"typo"}')
        r = await self.mcp.tools['mac_start_process']('pwd')
        self.assertTrue(r.isError)
        self.assertEqual(self.dc.calls, [])
        self.approver.approve.assert_not_called()

    async def test_always_keeps_write_annotations_and_no_policy_tool(self):
        self.always()
        self.assertEqual(len(self.mcp.tools), 29)
        self.assertFalse(self.mcp.annotations['mac_write_file'].readOnlyHint)
        self.assertTrue(self.mcp.annotations['mac_start_process'].destructiveHint)
        self.assertNotIn('mac_set_approval_mode', self.mcp.tools)
        import inspect
        for tool in ('mac_write_file', 'mac_start_process', 'mac_send_input'):
            self.assertNotIn('approved', inspect.signature(self.mcp.tools[tool]).parameters)
            self.assertNotIn('approval_mode', inspect.signature(self.mcp.tools[tool]).parameters)



    async def test_browser_denial_does_not_launch_or_navigate(self):
        r = await self.mcp.tools['browser_navigate']('https://example.com/')
        self.assertTrue(r.isError)
        self.assertEqual(self.browser.calls, [])

    async def test_browser_always_mode_has_no_native_dialog(self):
        self.always()
        r = await self.mcp.tools['browser_navigate']('http://localhost:8080/')
        self.assertFalse(r.isError)
        self.approver.approve.assert_not_called()
        self.assertEqual(self.browser.calls[-1], ('browser_navigate', {'url': 'http://localhost:8080/'}, 'always'))

    async def test_browser_ask_approval_applies_only_to_shown_target(self):
        self.approver.approve.return_value = True
        r = await self.mcp.tools['browser_click']('e5', 'test button')
        self.assertFalse(r.isError)
        self.assertEqual(self.browser.calls[-1][1], {'target': 'e5', 'element': 'test button'})
        self.assertEqual(self.browser.calls[-1][2], 'ask')

    async def test_browser_pause_during_approval_cancels(self):
        def approve(*args): self.dc.policy.pause(); return True
        self.approver.approve.side_effect = approve
        r = await self.mcp.tools['browser_navigate']('https://example.com/')
        self.assertTrue(r.isError)
        self.assertEqual(self.browser.calls, [])

    async def test_browser_mode_change_during_approval_cancels(self):
        def approve(*args): self.always(); return True
        self.approver.approve.side_effect = approve
        r = await self.mcp.tools['browser_navigate']('https://example.com/')
        self.assertTrue(r.isError)
        self.assertEqual(self.browser.calls, [])

    async def test_browser_forbidden_scheme_rejected_without_prompt(self):
        r = await self.mcp.tools['browser_navigate']('file:///private')
        self.assertTrue(r.isError)
        self.approver.approve.assert_not_called()
        self.assertEqual(self.browser.calls, [])

    async def test_browser_screenshot_has_no_output_path_or_full_page(self):
        r = await self.mcp.tools['browser_screenshot']()
        self.assertFalse(r.isError)
        self.assertEqual(self.browser.calls[-1], ('browser_take_screenshot', {'type': 'jpeg', 'scale': 'css', 'fullPage': False}, None))

    async def test_browser_tabs_require_observed_index(self):
        r = await self.mcp.tools['browser_tabs']('close')
        self.assertTrue(r.isError)
        self.approver.approve.assert_not_called()

    async def test_browser_typing_and_context_annotations_remain_mutations(self):
        for name in ['browser_navigate', 'browser_click', 'browser_type', 'browser_press_key', 'browser_tabs', 'mac_context_save']:
            self.assertFalse(self.mcp.annotations[name].readOnlyHint, name)
        for name in ['browser_screenshot', 'browser_snapshot', 'mac_context_read']:
            self.assertTrue(self.mcp.annotations[name].readOnlyHint, name)
        for name in ['browser_evaluate', 'browser_run_code', 'browser_file_upload', 'browser_cookie_list']:
            self.assertNotIn(name, self.mcp.tools)

    async def test_context_save_ask_denied_no_content_stored(self):
        r = await self.mcp.tools['mac_context_save']('test', 'Title', 'not stored')
        self.assertTrue(r.isError)
        r = await self.mcp.tools['mac_context_list']()
        self.assertEqual(r.structuredContent['contexts'], [])

    async def test_context_save_always_and_revision_conflict(self):
        self.always()
        r = await self.mcp.tools['mac_context_save']('test', 'Title', 'saved')
        self.assertFalse(r.isError)
        revision = r.structuredContent['revision']
        read = await self.mcp.tools['mac_context_read']('test')
        self.assertEqual(read.structuredContent['content'], 'saved')
        r = await self.mcp.tools['mac_context_save']('test', 'Title', 'updated', revision)
        self.assertFalse(r.isError)
        r = await self.mcp.tools['mac_context_save']('test', 'Title', 'stale', revision)
        self.assertTrue(r.isError)
        self.approver.approve.assert_not_called()

    async def test_pause_also_closes_dedicated_browser(self):
        r = await self.mcp.tools['mac_pause']()
        self.assertFalse(r.isError)
        self.assertEqual(self.browser.closed, 1)
        r = await self.mcp.tools['browser_snapshot']()
        self.assertTrue(r.isError)


if __name__ == '__main__': unittest.main()
