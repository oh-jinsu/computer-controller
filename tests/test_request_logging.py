"""Operational logging tests. Fixtures only; no real credentials or Mac sessions."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from mac_bridge import request_logging as rl


def request(name='mac_status', **arguments):
    return NS(params=NS(name=name, arguments=arguments))


def response(text='', *, error=False, data=None, image=False):
    blocks = [NS(type='text', text=text)]
    if image:
        blocks.append(NS(type='image', data='DO_NOT_LOG_IMAGE_DATA'))
    return NS(root=NS(content=blocks, isError=error, structuredContent=data))


class SummaryTests(unittest.TestCase):
    def test_private_arguments_are_lengths_only(self):
        private = 'private body, otp, password, confidential title'
        args = {name: private for name in rl.TEXT_FIELDS}
        out = rl.summarize_arguments(args)
        self.assertNotIn(private, json.dumps(out))
        self.assertEqual(out['text_chars'], len(private))
        self.assertEqual(out['old_string_chars'], len(private))

    def test_unknown_fields_and_nested_structures_are_hidden(self):
        out = rl.summarize_arguments({'token': 'SECRET', 'authorization': 'SECRET', 'extra': {'cookie': 'SECRET'}})
        self.assertEqual(out, {'other_fields_hidden': 3})

    def test_url_hides_userinfo_query_fragment_and_path(self):
        out = rl.url_summary('https://user:password@naver.com/PRIVATE-TOKEN?key=SECRET#OTP')
        self.assertEqual(out, 'https://naver.com')

    def test_invalid_urls_are_not_reflected(self):
        for value in ['javascript:SECRET', 'https://[', 'SECRET']:
            self.assertNotIn('SECRET', rl.url_summary(value))

    def test_workspace_path_is_relative(self):
        self.assertEqual(rl.path_summary('/Users/test/dev/game/main.gd', Path('/Users/test/dev')), './game/main.gd')

    def test_external_path_does_not_print_user_directory(self):
        self.assertEqual(rl.path_summary('/Users/another-person/topsecret/file.txt', None), '[outside workspace]/file.txt')

    def test_sensitive_paths_and_control_characters(self):
        self.assertEqual(rl.path_summary('app/.env.production', None), '[private path]')
        for value in ['a\nRES OK\r\x1b[31m', 'a\u202efile']:
            out = rl.clean_text(value)
            self.assertNotIn('\n', out); self.assertNotIn('\x1b', out); self.assertNotIn('\u202e', out)

    def test_paths_scrub_credentials_and_emails(self):
        for value in ['tmp/sk-proj-ABCDEFGHIJKLMN.txt', 'tmp/ghp_ABCDEFGHIJKLMN', 'tmp/hello@example.com', 'tmp/token=SECRET']:
            out = rl.path_summary(value, None)
            self.assertNotIn('ABCDEFGHIJKLMN', out)
            self.assertNotIn('hello@example.com', out)
            self.assertNotIn('SECRET', out)

    def test_commands_never_log_scripts_or_arguments(self):
        for command in ['curl -H "Authorization: Bearer SECRET" https://a', 'python -c "print(SECRET)"',
                        'TOKEN=SECRET git status', 'echo SECRET', 'bash -c SECRET', 'SECRET --foo']:
            self.assertNotIn('SECRET', rl.command_summary(command))
        self.assertEqual(rl.command_summary('git status --short'), 'git status [arguments hidden]')
        self.assertEqual(rl.command_summary('pwd'), 'pwd')

    def test_shell_substitution_and_multiline_not_parsed(self):
        for command in ['echo $(cat PRIVATE)', 'echo `cat PRIVATE`', "python - <<'PY'\nPRIVATE\nPY"]:
            self.assertEqual(rl.command_summary(command), '[script; arguments hidden]')

    def test_target_only_discloses_observed_reference(self):
        self.assertEqual(rl.summarize_arguments({'target': 'f7e4'}), {'target': 'f7e4'})
        self.assertEqual(rl.summarize_arguments({'target': 'text=PRIVATE'}), {'target': '[selector hidden]'})

    def test_literal_keypress_hidden(self):
        self.assertEqual(rl.summarize_arguments({'key': 'PRIVATE'})['key'], '[keypress hidden]')
        self.assertEqual(rl.summarize_arguments({'key': 'Enter'})['key'], 'Enter')

    def test_numbers_booleans_and_enums(self):
        value = {'pid': 123, 'submit': False, 'action': 'select', 'index': 2}
        self.assertEqual(rl.summarize_arguments(value), value)
        self.assertEqual(rl.summarize_arguments({'pid': 'PRIVATE'}), {'other_fields_hidden': 1})
        self.assertEqual(rl.summarize_arguments({'pid': 10 ** 500}), {'other_fields_hidden': 1})

    def test_summary_omits_response_bodies_and_images(self):
        out = rl.summarize_result(response('PRIVATE_RESPONSE', data={'secret': 'PRIVATE'}, image=True), 'browser_screenshot')
        self.assertEqual(out['images'], 1)
        self.assertEqual(out['text_chars'], len('PRIVATE_RESPONSE'))
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.assertNotIn('DO_NOT_LOG', json.dumps(out))

    def test_tool_error_is_a_failure_even_without_exception(self):
        out = rl.summarize_result(response('Path is outside the selected project directory: PRIVATE', error=True), 'mac_read_file')
        self.assertEqual(out['status'], 'error'); self.assertEqual(out['error_code'], 'outside_workspace')
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_starting_a_process_is_not_reported_as_completion(self):
        out = rl.summarize_result(response('Process started with PID 456 (shell: /bin/sh)\nInitial output: PRIVATE'), 'mac_start_process')
        self.assertEqual(out['pid'], 456); self.assertEqual(out['process_state'], 'started')
        self.assertNotIn('reported_exit_code', out)

    def test_exit_code_is_separate_from_tool_success(self):
        out = rl.summarize_result(response('✅ Process completed with exit code 3 (runtime: 1.1s)'), 'mac_process_output')
        self.assertEqual(out['status'], 'ok'); self.assertEqual(out['reported_exit_code'], 3)

    def test_video_job_state_and_counts(self):
        out = rl.summarize_result(response(data={'state': 'complete', 'frames': [{'secret': 'PRIVATE'}]}), 'get_extraction')
        self.assertEqual(out['job_state'], 'complete'); self.assertEqual(out['frames_count'], 1)
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_bad_structured_shape_does_not_crash(self):
        self.assertEqual(rl.summarize_result(response(data={'state': ['unknown']}), 'get_extraction')['status'], 'ok')

    def test_quiet_filter_keeps_real_warnings(self):
        f = rl._QuietDispatch()
        def rec(level, msg): return logging.LogRecord('mcp.server.lowlevel.server', level, '', 0, msg, (), None)
        self.assertFalse(f.filter(rec(logging.INFO, 'Processing request of type %s')))
        self.assertTrue(f.filter(rec(logging.WARNING, 'Processing request of type failed')))
        self.assertTrue(f.filter(rec(logging.INFO, 'other event')))


class SinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.stderr = io.StringIO(); self.sink = rl.RequestLog(self.root, stream=self.stderr)
        self.call = {'tool': 'mac_status', 'trace_id': 'test-1'}
    def tearDown(self): self.tmp.cleanup()

    def test_only_stderr_and_private_jsonl(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout): self.sink.emit('request', self.call, arguments={})
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('REQ mac_status', self.stderr.getvalue())
        path = self.root / '.state/request-logs/requests.jsonl'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())['tool'], 'mac_status')

    def test_rotation_keeps_two_previous_files(self):
        self.sink.max_bytes = 512
        for _ in range(30): self.sink.emit('request', self.call, arguments={})
        logs = list((self.root / '.state/request-logs').glob('requests.jsonl*'))
        self.assertEqual(len(logs), 3)
        for path in logs:
            self.assertLessEqual(path.stat().st_size, 512)
            for line in path.read_text().splitlines(): json.loads(line)

    def test_symlink_log_is_not_followed(self):
        folder = self.root / '.state/request-logs'; folder.mkdir(parents=True)
        victim = self.root / 'victim'; victim.write_text('unchanged')
        (folder / 'requests.jsonl').symlink_to(victim)
        self.sink.emit('request', self.call, arguments={})
        self.assertEqual(victim.read_text(), 'unchanged')
        self.assertIn('log unavailable', self.stderr.getvalue())

    def test_symlink_directory_is_not_followed(self):
        victim = self.root / 'victim'; victim.mkdir()
        (self.root / '.state').symlink_to(victim)
        self.sink.emit('request', self.call, arguments={})
        self.assertEqual(list(victim.iterdir()), [])

    def test_hardlink_log_is_not_written(self):
        folder = self.root / '.state/request-logs'; folder.mkdir(parents=True)
        victim = self.root / 'victim'; victim.write_text('unchanged')
        os.link(victim, folder / 'requests.jsonl')
        self.sink.emit('request', self.call, arguments={})
        self.assertEqual(victim.read_text(), 'unchanged')

    def test_two_writers_do_not_corrupt_records(self):
        other = rl.RequestLog(self.root, stream=io.StringIO())
        def write(index):
            sink = self.sink if index % 2 else other
            sink.emit('request', {'tool': 'mac_status', 'trace_id': 't-' + str(index)}, arguments={})
        with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(write, range(40)))
        rows = [json.loads(l) for l in (self.root / '.state/request-logs/requests.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 40)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.stderr = io.StringIO(); self.sink = rl.RequestLog(self.root, stream=self.stderr)
    def tearDown(self): self.tmp.cleanup()
    def rows(self):
        return [json.loads(l) for l in (self.root / '.state/request-logs/requests.jsonl').read_text().splitlines()]

    async def test_response_identity_and_correlation_preserved(self):
        result = response('PRIVATE')
        async def handler(req): return result
        actual = await self.sink.handle(handler, request(), rpc_id=0)
        self.assertIs(actual, result)
        rows = self.rows(); self.assertEqual([r['event'] for r in rows], ['request', 'response'])
        self.assertEqual(rows[0]['trace_id'], rows[1]['trace_id']); self.assertEqual(rows[0]['rpc_id'], 0)
        self.assertIn('duration_ms', rows[1]); self.assertNotIn('PRIVATE', self.stderr.getvalue())

    async def test_reused_rpc_id_gets_distinct_trace_ids(self):
        async def handler(req): return response()
        await self.sink.handle(handler, request(), rpc_id=0)
        await self.sink.handle(handler, request(), rpc_id=0)
        self.assertNotEqual(self.rows()[0]['trace_id'], self.rows()[2]['trace_id'])

    async def test_untrusted_rpc_string_is_hashed(self):
        async def handler(req): return response()
        await self.sink.handle(handler, request(), rpc_id='SECRET')
        self.assertNotIn('SECRET', json.dumps(self.rows()))
        self.assertIn('rpc_id_hash', self.rows()[0])

    async def test_exception_does_not_expose_message_or_get_retried(self):
        count = 0
        async def handler(req):
            nonlocal count
            count += 1; raise ValueError('SECRET')
        with self.assertRaisesRegex(ValueError, 'SECRET'): await self.sink.handle(handler, request())
        self.assertEqual(count, 1); self.assertNotIn('SECRET', self.stderr.getvalue())
        self.assertEqual(self.rows()[-1]['status'], 'error')

    async def test_cancellation_is_logged_and_propagated(self):
        async def handler(req): raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError): await self.sink.handle(handler, request())
        self.assertEqual(self.rows()[-1]['status'], 'cancelled')
        self.assertIsNone(rl._CURRENT.get())

    async def test_approval_phase_is_linked_to_call(self):
        async def handler(req):
            await asyncio.to_thread(rl.request_phase, 'approval_requested')
            return response('Denied or timed out locally; nothing executed.', error=True)
        await self.sink.handle(handler, request('mac_write_file', content='PRIVATE'))
        rows = self.rows(); self.assertEqual(rows[1]['phase'], 'approval_wait')
        self.assertEqual(rows[0]['trace_id'], rows[1]['trace_id'])
        self.assertEqual(rows[-1]['error_code'], 'approval_denied')

    async def test_concurrent_requests_have_separate_contexts(self):
        async def handler(req):
            await asyncio.sleep(0)
            rl.request_phase('auto_approved')
            return response()
        await asyncio.gather(self.sink.handle(handler, request('browser_click')), self.sink.handle(handler, request('mac_write_file')))
        for row in self.rows():
            matches = [r for r in self.rows() if r['trace_id'] == row['trace_id']]
            self.assertEqual(len(matches), 3); self.assertEqual(len({r['tool'] for r in matches}), 1)

    async def test_logging_failure_does_not_fail_or_retry_tool(self):
        result = response()
        handler = mock.AsyncMock(return_value=result)
        with mock.patch.object(self.sink, 'append', side_effect=OSError('disk full SECRET')):
            actual = await self.sink.handle(handler, request())
        self.assertIs(actual, result); handler.assert_awaited_once()
        self.assertNotIn('SECRET', self.stderr.getvalue())

    async def test_summary_failure_does_not_fail_tool(self):
        handler = mock.AsyncMock(return_value=response())
        with mock.patch.object(rl, 'summarize_arguments', side_effect=ValueError('SECRET')), mock.patch.object(rl, 'summarize_result', side_effect=ValueError('SECRET')):
            await self.sink.handle(handler, request())
        handler.assert_awaited_once(); self.assertEqual(self.rows()[-1]['status'], 'unknown')

    async def test_unknown_tool_name_not_reflected(self):
        handler = mock.AsyncMock(return_value=response('Unknown tool SECRET', error=True))
        await self.sink.handle(handler, request('SECRET'))
        self.assertNotIn('SECRET', self.stderr.getvalue())
        self.assertEqual(self.rows()[-1]['error_code'], 'unknown_tool')


    async def test_slow_request_reports_wait_and_stops_after_completion(self):
        async def handler(req):
            await asyncio.sleep(0.04)
            return response()
        with mock.patch.object(rl, 'SLOW_AFTER', 0.01), mock.patch.object(rl, 'SLOW_EVERY', 0.01):
            await self.sink.handle(handler, request())
            count = len(self.rows())
            await asyncio.sleep(0.03)
        self.assertEqual(len(self.rows()), count)
        self.assertTrue(any(row['event'] == 'running' for row in self.rows()))
        self.assertEqual(self.rows()[-1]['event'], 'response')

    async def test_sdk_warning_preserves_severity_not_raw_payload(self):
        record = logging.LogRecord('mcp.server.fastmcp.tools.base', logging.ERROR, '', 0,
                                   'Bad input: %s', ('SECRET',), None)
        record.exc_text = 'traceback SECRET'
        self.assertTrue(rl._SDKPayloadFilter().filter(record))
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertNotIn('SECRET', record.getMessage())
        self.assertIsNone(record.exc_text)

    async def test_unrelated_logger_is_not_modified(self):
        record = logging.LogRecord('other_module', logging.WARNING, '', 0, 'normal warning', (), None)
        self.assertTrue(rl._SDKPayloadFilter().filter(record))
        self.assertEqual(record.getMessage(), 'normal warning')


if __name__ == '__main__': unittest.main()
