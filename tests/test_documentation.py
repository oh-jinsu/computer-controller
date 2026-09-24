"""Offline onboarding checks. No browser, signing key, network or live tunnel access."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ('README.md', 'docs/INSTALL.md', 'docs/DEVELOPMENT.md', 'docs/BROWSER-CONTEXT.md',
             'docs/APP-DISTRIBUTION.md', 'docs/RELEASE-STATUS.md', 'docs/VIDEO-WORKFLOW.md')


def anchors(markdown: str) -> set[str]:
    result = set()
    counts: dict[str, int] = {}
    for heading in re.findall(r'^#{1,6}\s+(.+)$', markdown, re.M):
        value = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(value, 0)
        counts[value] = count + 1
        result.add(value if count == 0 else f'{value}-{count}')
    return result


class DocumentationTests(unittest.TestCase):
    def test_local_document_links_and_anchors_exist(self):
        checked = 0
        for name in DOCUMENTS:
            path = ROOT / name
            for link in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', path.read_text()):
                target = urlsplit(link)
                if target.scheme or target.netloc:
                    continue
                destination = (path.parent / unquote(target.path)).resolve() if target.path else path
                self.assertTrue(destination.is_file(), f'{name}: {link}')
                self.assertTrue(destination.is_relative_to(ROOT), link)
                if target.fragment:
                    self.assertIn(unquote(target.fragment), anchors(destination.read_text()), f'{name}: {link}')
                checked += 1
        self.assertGreater(checked, 20)

    def test_installation_is_short_sequential_checklist(self):
        headings = re.findall(r'^(\d+)\. ', (ROOT / 'README.md').read_text().split('## 설치', 1)[1].split('## 선택 설정', 1)[0], re.M)
        self.assertEqual(headings, ['1', '2', '3', '4', '5', '6', '7'])

    def test_readme_keeps_terminal_bootstrap_in_developer_guide(self):
        readme = (ROOT / 'README.md').read_text()
        for command in ['git clone https://', 'bash Mac-Start.command', 'brew install', 'pip install']:
            self.assertNotIn(command, readme)
        self.assertIn('docs/DEVELOPMENT.md', readme)
        development = (ROOT / 'docs/DEVELOPMENT.md').read_text()
        self.assertIn('bash Mac-Start.command', development)
        self.assertIn('bash Mac-Release.command --publish', development)

    def test_documented_app_buttons_exist_in_actual_ui(self):
        readme = (ROOT / 'docs/INSTALL.md').read_text()
        swift = (ROOT / 'packaging/macos/MacBridge.swift').read_text()
        for label in ['연결 시작', '연결 중지', '설정…', '화면 기록 권한…', '업데이트 확인…',
                      '이전 실행본 보기', '로그 보기', '기존 설정 가져오기…',
                      '요청된 Mac 작업 항상 허용', '평소 Chrome 로그인 상태 사용',
                      '서명된 업데이트 자동 확인·다운로드']:
            self.assertIn(label, swift, label)
            self.assertIn(label, readme, label)

    def test_release_filename_matches_current_configuration(self):
        config = json.loads((ROOT / 'packaging/release.json').read_text())
        expected = f'Mac-Bridge-{config["display_version"]}-macos26-arm64.zip'
        for path in ['README.md', 'docs/RELEASE-STATUS.md']:
            self.assertIn(expected, (ROOT / path).read_text())
        self.assertEqual(config['minimum_macos'], '26.0')
        self.assertEqual(config['architecture'], 'arm64')

    def test_user_guide_distinguishes_runtime_and_update_signing_keys(self):
        readme = (ROOT / 'docs/INSTALL.md').read_text()
        for text in ['Runtime API 키', '업데이트 서명용 비밀키', '각 사용자는 자신의 터널과 키',
                     'Apple Developer Program', '키체인', '보안 샌드박스가 아닙니다']:
            self.assertIn(text, readme)

    def test_user_guide_does_not_hide_beta_limits(self):
        readme = (ROOT / 'README.md').read_text()
        for text in ['공개 베타', '브라우저 파일 업로드', '별도 백그라운드', '안정판 자동 업데이트 대상이 아닙니다']:
            self.assertIn(text, readme)
        details = (ROOT / 'docs/INSTALL.md').read_text()
        for text in ['자동 복구는 구현하지 않았습니다', '재시작만으로도 해제되지 않습니다', 'Source code (zip)']:
            self.assertIn(text, details)
        self.assertLess(len(readme.splitlines()), 50)
        self.assertLess(len(readme), 2600)

    def test_onboarding_never_instructs_gatekeeper_bypass(self):
        for name in DOCUMENTS:
            text = (ROOT / name).read_text()
            for command in ['spctl --master-disable', 'spctl --global-disable',
                            'xattr -dr', 'xattr -d com.apple.quarantine', 'security dump-keychain']:
                self.assertNotIn(command, text, name)

    def test_app_data_paths_not_source_relative(self):
        readme = (ROOT / 'docs/INSTALL.md').read_text()
        control = (ROOT / 'mac_bridge/app_control.py').read_text()
        self.assertIn('Library/Application Support/Mac Bridge', control)
        self.assertIn('~/Library/Application Support/Mac Bridge/input', readme)
        self.assertIn('~/Library/Application Support/Mac Bridge/.state/contexts', readme)
        self.assertIn('independent_runtime: true', readme)
        self.assertIn('source_checkout_is_runtime: false', readme)


if __name__ == '__main__':
    unittest.main()
