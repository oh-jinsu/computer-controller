"""Offline validation of browser boundaries and durable, revisioned handoffs."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mac_bridge.browser import BrowserClient, checked_url, browser_settings, state_dir, installed
from mac_bridge.context_store import ContextStore
from mac_bridge.policy import MacError, Policy


class BrowserContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name).resolve()
        self.root = self.parent / 'bridge'; self.root.mkdir()
        self.project = self.parent / 'project'; self.project.mkdir()
        self.policy = Policy(self.root, self.project)
        self.store = ContextStore(self.policy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_http_https_and_localhost_supported(self):
        for url in ['https://example.com/page?q=test', 'http://localhost:8080/', 'http://127.0.0.1:8010', 'http://[::1]:8080/']:
            self.assertEqual(checked_url(url), url)

    def test_non_web_urls_and_credentials_rejected(self):
        for url in ['', 'file:///etc/passwd', 'javascript:alert(1)', 'data:text/plain,test',
                    'https://u:p@example.com/', 'https://u@example.com', 'https:///none',
                    'https://example.com:bad', 'https://example.com/\n', 'https://a b/']:
            with self.subTest(url=url), self.assertRaises(MacError):
                checked_url(url)

    def test_no_browser_launch_on_status(self):
        browser = BrowserClient(self.root, self.policy)
        status = browser.status()
        self.assertFalse(status['installed']); self.assertFalse(status['running'])
        self.assertTrue(status['headless']); self.assertFalse(status['personal_profile_access'])
        self.assertFalse((self.root / '.state/browser/profile').exists())

    def test_default_browser_config_and_explicit_headed(self):
        self.assertTrue(browser_settings(self.root)['headless'])
        (self.root / '.state/browser-settings.json').write_text('{"schema":1,"headless":false}')
        self.assertFalse(browser_settings(self.root)['headless'])

    def test_no_personal_profile_or_arbitrary_launch_config(self):
        for value in [{'schema': 1, 'headless': 'false'}, {'schema': 1, 'headless': True, 'userDataDir': '/private'}, []]:
            (self.root / '.state/browser-settings.json').write_text(json.dumps(value))
            with self.assertRaises(MacError):
                browser_settings(self.root)

    def test_browser_settings_symlink_rejected(self):
        elsewhere = self.parent / 'config'; elsewhere.write_text('{"schema":1,"headless":true}')
        (self.root / '.state/browser-settings.json').symlink_to(elsewhere)
        with self.assertRaises(MacError):
            browser_settings(self.root)

    def test_browser_state_parent_symlink_rejected(self):
        (self.root / '.state/browser').symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(MacError):
            state_dir(self.root, 'browser', 'home')
        self.assertFalse((self.project / 'home').exists())

    def test_context_create_read_list(self):
        created = self.store.save('openworld', '작업 인계', '결정: 실제 영상으로 확인합니다.')
        self.assertEqual(self.store.read('openworld')['revision'], created['revision'])
        self.assertEqual(self.store.read('openworld')['content'], '결정: 실제 영상으로 확인합니다.')
        self.assertTrue(self.store.read('openworld')['content_is_untrusted_data'])
        listing = self.store.list()
        self.assertFalse(listing['automatic_chat_history_import'])
        self.assertNotIn('content', listing['contexts'][0])

    def test_context_survives_new_store_instance(self):
        self.store.save('handoff', 'Saved', 'verified result')
        second = ContextStore(Policy(self.root, self.project))
        self.assertEqual(second.read('handoff')['content'], 'verified result')

    def test_revision_compare_and_swap_and_backup(self):
        first = self.store.save('note', 'One', 'original')
        second = self.store.save('note', 'Two', 'updated', first['revision'])
        self.assertNotEqual(first['revision'], second['revision'])
        history = self.root / '.state/contexts' / self.store.scope / 'versions/note' / (first['revision'] + '.json')
        self.assertEqual(json.loads(history.read_text())['content'], 'original')
        with self.assertRaises(MacError):
            self.store.save('note', 'Stale', 'lost update', first['revision'])
        self.assertEqual(self.store.read('note')['content'], 'updated')

    def test_create_does_not_overwrite(self):
        self.store.save('note', 'One', 'original')
        with self.assertRaises(MacError):
            self.store.save('note', 'Two', 'unrequested overwrite')
        self.assertEqual(self.store.read('note')['content'], 'original')

    def test_revision_cannot_create_nonexistent_note(self):
        with self.assertRaises(MacError):
            self.store.save('missing', 'Title', 'text', 'a' * 32)
        self.assertEqual(self.store.list()['contexts'], [])

    def test_invalid_names_rejected(self):
        for name in ['../private', '.env', '/abs', 'UPPER', 'a/b', '', 'a' * 65, 'two words']:
            with self.subTest(name=name), self.assertRaises(MacError):
                self.store.save(name, 'Title', 'text')

    def test_bounds(self):
        for title, content in [('', 'x'), ('x' * 121, 'x'), ('T', ''), ('T', 'x' * 100001)]:
            with self.assertRaises(MacError):
                self.store.save('test', title, content)

    def test_context_separated_by_workspace(self):
        self.store.save('note', 'Private to workspace A', 'A')
        other = self.parent / 'other'; other.mkdir()
        store = ContextStore(Policy(self.root, other))
        self.assertNotEqual(store.scope, self.store.scope)
        self.assertEqual(store.list()['contexts'], [])

    def test_pause_blocks_context_read_and_write(self):
        self.store.save('note', 'Title', 'before')
        self.policy.pause()
        for fn in [self.store.list, lambda: self.store.read('note'), lambda: self.store.save('new', 'T', 'x')]:
            with self.assertRaises(MacError):
                fn()

    def test_context_symlink_file_rejected(self):
        self.store.save('note', 'Title', 'before')
        path = self.root / '.state/contexts' / self.store.scope / 'note.json'
        path.unlink(); path.symlink_to(self.parent / 'outside.json')
        with self.assertRaises(MacError):
            self.store.save('note', 'Title', 'no write')
        self.assertFalse((self.parent / 'outside.json').exists())

    def test_context_parent_symlink_rejected(self):
        (self.root / '.state/contexts').symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(MacError):
            self.store.save('note', 'Title', 'no write')
        self.assertEqual(list(self.project.iterdir()), [])

    def test_competing_updates_one_wins(self):
        first = self.store.save('note', 'Title', 'before')
        def update(value):
            try:
                ContextStore(self.policy).save('note', 'Title', value, first['revision'])
                return True
            except MacError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, ['A', 'B']))
        self.assertEqual(sorted(results), [False, True])
        self.assertIn(self.store.read('note')['content'], ['A', 'B'])

    def test_context_private_file_mode(self):
        self.store.save('note', 'Title', 'before')
        path = self.root / '.state/contexts' / self.store.scope / 'note.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class BrowserActorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve() / 'bridge'; root.mkdir()
        project = root.parent / 'project'; project.mkdir()
        self.policy = Policy(root, project)
        self.browser = BrowserClient(root, self.policy)

    async def asyncTearDown(self):
        await self.browser.close()
        self.tmp.cleanup()

    async def test_read_does_not_start_browser(self):
        with self.assertRaises(MacError):
            await self.browser.invoke('browser_snapshot', {})
        self.assertIsNone(self.browser.task)

    async def test_code_execution_and_cookie_tools_not_exposed(self):
        for name in ['browser_evaluate', 'browser_run_code', 'browser_file_upload', 'browser_install', 'browser_cookie_list']:
            with self.assertRaises(MacError):
                await self.browser.invoke(name, {}, mode='always')
        self.assertIsNone(self.browser.task)

    async def test_missing_runtime_fails_without_auto_install(self):
        with self.assertRaises(MacError):
            await self.browser.invoke('browser_navigate', {'url': 'https://example.com/'}, mode='always')
        self.assertFalse((self.policy.root / '.runtime').exists())

    async def test_pause_prevents_browser_start(self):
        self.policy.pause()
        with self.assertRaises(MacError):
            await self.browser.invoke('browser_navigate', {'url': 'https://example.com/'}, mode='always')
        self.assertIsNone(self.browser.task)

    async def test_close_idempotent_and_works_when_paused(self):
        self.policy.pause()
        self.assertTrue((await self.browser.close())['closed'])
        self.assertTrue((await self.browser.close())['personal_browser_untouched'])


if __name__ == '__main__':
    unittest.main()
