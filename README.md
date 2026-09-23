# Mac Bridge

## 0.5.0-beta.1: 독립 실행 앱과 자동 업데이트

사용자용 설치는 **릴리스 ZIP → Mac Bridge.app 실행**을 목표로 분리했습니다. Python·Node·영상 처리 도구를 포함하므로 앱 실행 시 Homebrew나 개발 저장소가 필요하지 않습니다. 개발 소스는 자유롭게 수정하고, 앱은 번들 안의 고정된 코드로 실행하며, 설정은 앱 바깥에 보관합니다.

**현재는 macOS 26+ / Apple Silicon용 내부 테스트 베타입니다.** 앱 빌드·UI·실제 MCP 통합 검사는 통과했지만, Developer ID/Apple 공증과 실제 자동 업데이트 교체 검증은 남아 있습니다. 업데이트 서명 도구의 Keychain 접근이 취소돼 서명된 업데이트 피드는 아직 발행하지 않았습니다. 기존 실행 중인 0.4.0 서버도 교체하지 않았습니다.

[앱 설치·개발·자동 업데이트·검증 현황](docs/APP-DISTRIBUTION.md)

아래의 clone/pull/시작 스크립트 설명은 **기존 소스 설치 및 개발자용 경로**입니다. 독립 앱 사용자가 매번 이 절차를 반복하는 구조는 아닙니다.

하나의 저장소, 하나의 시작 파일, 하나의 기존 터널로 사용하는 개인용 MCP 서버입니다.

**영상 프레임 추출 + 프로젝트 파일·터미널 + 지정 앱 창 캡처 + 전용 브라우저 + 작업 맥락 저장**를 제공합니다.
`scene_bridge/`는 이 저장소 안의 영상 처리 모듈 이름일 뿐입니다. 별도의 `scene-bridge` 설치 폴더나 업데이트 ZIP은 필요하지 않습니다.

## 0.4.0: 브라우저와 작업 맥락

기존 연결에 브라우저 도구 12개와 작업 맥락 도구 3개를 더해 총 **34개 도구**를 제공합니다. 웹페이지 탐색·입력·클릭·실제 페이지 캡처·탭·콘솔·네트워크 확인과, 다음 대화에서 불러올 작업 요약 저장이 가능합니다.

**기존 터널·항상 허용 설정은 그대로 유지합니다.** 업데이트 후 재시작하고 기존 `My Mac` 연결을 Refresh하면 됩니다. 전용 브라우저는 기본적으로 화면을 띄우지 않으며, 평소 사용하던 Chrome 프로필을 읽지 않습니다. 브라우저 페이지 캡처에는 macOS 화면 기록 권한이 필요하지 않습니다.

[브라우저·작업 맥락 사용법과 제한](docs/BROWSER-CONTEXT.md)

## 처음 한 번

이미 Scene Bridge 또는 0.2 업데이트판을 사용 중이라면 **이전 실행 창에서 Ctrl+C로 종료**합니다. 같은 터널 ID를 두 프로세스에서 동시에 실행하지 마세요.

다음 명령으로 받습니다. 비공개 저장소이므로 로컬 Git의 GitHub 인증이 되어 있어야 합니다. 토큰을 채팅에 붙여 넣지 마세요.

```sh
git clone https://github.com/oh-jinsu/mac-bridge.git
cd mac-bridge
bash Mac-Start.command
```

첫 실행에서 기존 설정 가져오기에 동의하고 이전 설치 폴더를 선택합니다. **터널 ID와 작업 폴더만 복사**합니다. 기존 키체인에 Runtime 키가 저장되어 있다면 그대로 사용합니다. 키체인에 없거나 접근이 거부되면 기존 키를 로컬 터미널에서 숨김 입력합니다. 새 터널이나 새 키 발급은 필요하지 않습니다.

새 저장소의 Python 환경과 로컬 엔진을 준비하고, 실제 MCP/엔진/영상 검사를 통과해야 터널을 시작합니다. 로컬 터널 프로필은 새 실행 경로를 가리키도록 별도로 생성하지만 **OpenAI에 만들어 둔 터널 ID는 그대로**입니다. ChatGPT의 기존 `My Mac` 연결을 한 번 Refresh하세요.

폴더 선택 대신 경로를 지정할 수도 있습니다.

```sh
bash Mac-Start.command --migrate "/실제/기존/scene-bridge/경로"
```

`--migrate`는 설정이 없는 새 체크아웃에서 처음 한 번만 사용합니다. 기존 설정을 덮어쓰는 옵션은 없습니다. 다음부터는 그냥 `bash Mac-Start.command`입니다.

설정 이전이 끝나면 이전 설치의 실행 코드/가상환경에는 의존하지 않습니다. 다만 **이전 `input/`, `output/`, `.state/file-backups/`의 사용자 자료를 자동 복사하거나 삭제하지 않습니다.** 필요한 영상과 백업은 보관한 뒤 이전 폴더를 정리하세요.

## 이후 업데이트

실행 창에서 Ctrl+C로 종료한 다음:

```sh
git pull --ff-only
bash Mac-Start.command
```

같은 저장소에서 코드만 갱신합니다. `.state/` 설정, `.runtime/` 설치 캐시, `.venv/`, 사용자 영상은 Git 추적 대상이 아닙니다. 코드/의존성이 달라지면 시작 전 검사를 다시 실행하며, 실패하면 터널을 시작하지 않습니다. **실패한 `git pull`이나 로컬 수정사항을 강제로 초기화하지 않으며, Git 코드를 자동 롤백하지도 않습니다.** 충돌은 먼저 해결하세요.

## 승인 모드 — 한 번 선택하면 계속 유지

기존 설치는 별도로 선택하지 않으면 **매번 확인(`ask`)**을 유지합니다. **항상 허용(`always`)**을 선택하면 파일 쓰기·부분 수정·터미널 명령·프로세스 입력을 Mac 승인창 없이 실행합니다. 작업별 범위·기간·목록을 새로 지정할 필요가 없으며, 재시작과 일반 `git pull` 후에도 유지됩니다.

실행 중인 창에서 `Ctrl+C`로 종료하고, 저장소에서 **최초 한 번** 실행하세요.

```sh
git pull --ff-only
bash Mac-Start.command --approval-mode always
```

다음부터는 `bash Mac-Start.command`만 사용합니다. 선택은 Git에서 제외된 `.state/approval-settings.json`에 저장됩니다. 기존 터널·키체인·작업 폴더 설정은 그대로 두며, 누락된 승인 설정은 `ask`, 잘못된 설정은 실행 거부로 처리합니다. 승인 모드 기능 자체는 새 의존성을 요구하지 않습니다. 0.4.0 브라우저 기능은 별도 전용 로컬 Playwright 런타임을 사용합니다.

실행 중에 모드를 확인하거나 되돌리려면 별도 터미널에서:

```sh
.venv/bin/python -m mac_bridge.local approval
.venv/bin/python -m mac_bridge.local approval --mode ask
```

변경은 다음 요청부터 적용됩니다. 이미 실행된 작업을 취소하는 기능은 아니며, 대기 중 승인 모드가 바뀐 요청은 실행하지 않고 재요청을 요구합니다. 일시 중지된 서버를 이 명령으로 재개하지 않습니다. `mac_status`의 `approval_mode`와 `approval_mode_persistent`로 실제 상태를 확인할 수 있습니다.

**백업·작업 기록·즉시 중지·파일 경로 검사·PID 소유권 검사는 두 모드 모두 유지**합니다. 파일 도구의 변경 전 백업은 셸 명령이 변경하는 모든 파일까지 백업한다는 뜻은 아닙니다. 자동 허용은 요청하지 않은 삭제·설치·외부 전송의 포괄적 위임이 아닙니다. 터미널은 기존처럼 Mac 사용자 권한으로 폴더 밖에도 접근할 수 있습니다. macOS 화면 기록·키체인 권한 및 ChatGPT 쪽 승인 설정은 이 로컬 옵션이 바꾸지 않습니다.

## 추가 조작

```sh
# Mac 작업을 일시 중지합니다. 영상 도구와 터널은 유지합니다.
bash Mac-Stop.command

# 지정 창 캡처를 위한 화면 기록 권한 요청
bash Mac-Screen-Permission.command

# 실제 MCP/엔진/영상 시작 전 검사를 다시 실행
bash Mac-Start.command --recheck
```

화면 기록 권한은 macOS 시스템 설정에서 직접 승인합니다. 일반 Mac 앱의 클릭·키보드 도구는 없으며, 브라우저 도구는 전용 웹페이지 안에서만 입력합니다. 전체 종료는 실행 중인 터미널에서 Ctrl+C입니다.

## 제공 도구

| 범위 | 도구 |
| --- | --- |
| 영상 | `start_extraction`, `get_extraction`, `get_frame`, `list_local_videos`, `bridge_status` |
| 파일 | `mac_list_directory`, `mac_read_file`, `mac_write_file`, `mac_edit_file` |
| 프로세스 | `mac_start_process`, `mac_process_output`, `mac_send_input`, `mac_stop_process`, `mac_list_sessions` |
| 창 | `mac_list_windows`, `mac_capture_window` |
| 상태/중지/기록 | `mac_status`, `mac_pause`, `mac_recent_actions` |
| 브라우저 | `browser_status`, `browser_navigate`, `browser_snapshot`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_press_key`, `browser_resize`, `browser_tabs`, `browser_console_messages`, `browser_network_requests`, `browser_close` |
| 작업 맥락 | `mac_context_list`, `mac_context_read`, `mac_context_save` |

YouTube는 단일 영상 HTTPS 주소만 받습니다. 로컬 영상은 이 저장소의 `input/`에 넣고 `local:파일명.mp4`로 요청합니다. 전체/구간을 일정 간격으로 훑거나 지정 시각을 추출합니다. 의미 있는 장면을 자동 판별하는 기능은 아닙니다. YouTube 접근 제한이나 봇 차단을 우회하지 않습니다.

## 권한과 데이터

파일 도구는 선택한 개발 폴더로 제한하고, 홈 전체(`~`)와 파일시스템 루트는 선택할 수 없습니다. 프로젝트를 모은 상위 개발 폴더를 선택할 수 있으며, 그 안의 Mac Bridge 자체 파일은 파일 도구에서 제외합니다. `.env`, 일부 자격증명 경로, 키 파일, 심볼릭 링크도 파일 읽기/편집 도구에서 거부합니다.

파일 변경·터미널 실행·프로세스 입력은 저장된 승인 모드를 따릅니다. **`ask`는 요청마다 Mac 승인, `always`는 로컬 승인창 없이 실행**합니다. 기존 파일은 수정 전 백업하고, 실행 전에 내용이 바뀌었다면 덮어쓰지 않습니다.

**이것은 보안 샌드박스가 아닙니다.** 승인한 셸 명령은 현재 macOS 사용자 권한으로 프로젝트 밖 파일과 네트워크에 접근할 수 있습니다. 삭제/설치/자격증명 접근/보안 설정 변경은 실제 요청 내용을 확인하세요. 창 캡처 결과와 읽은 내용은 도구 결과로 대화에 전달될 수 있습니다.

로컬 실행 파일은 서명된 macOS 앱이 아닙니다. Gatekeeper 해제나 운영체제 보안 우회 명령은 사용하지 않습니다. 실행 파일을 검토한 후 위 `bash` 명령으로 실행하세요.

## 구조

```text
Mac-Start.command        # 독립 시작점: 없는 의존성만 설치 → 검사 → 기존 터널
run_server.py            # 터널 키 환경변수를 제거하고 통합 MCP 시작
mac_bridge/              # 파일·프로세스·지정 창·승인·설정 이전
scene_bridge/            # 같은 저장소 안의 영상 처리 모듈
input/                   # 사용자 로컬 영상: Git 제외
.state/                  # 로컬 설정·승인 기록·백업·브라우저 프로필·작업 요약: Git 제외
.runtime/                # Desktop Commander·Playwright 로컬 설치: Git 제외
output/                  # 영상 추출 결과: Git 제외
```

Runtime 키는 macOS 키체인을 사용합니다. 기존 키 재사용을 위해 키체인 서비스 식별자 `scene-bridge-tunnel`만 유지합니다. 이 식별자는 이전 설치 폴더를 가리키지 않습니다. 키체인 항목 및 외부 `tunnel-client` 프로필은 저장소 삭제만으로 제거되지 않습니다.

Desktop Commander는 로컬 `0.2.51` 엔진을 사용하며, 유료 원격 서비스/Claude 설정/전체 CLI의 Chrome 자동 설치는 실행하지 않습니다. `npm install --ignore-scripts`로 설치 스크립트를 생략합니다. 엔진 자체와 MCP SDK 버전은 고정했지만, **전체 간접 의존성 잠금 파일을 사전 제공하지는 않습니다.** `uv.lock`과 `package-lock.json`은 첫 로컬 설치 결과를 보존하며 Git에는 올리지 않습니다.

## 검증

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke_mac_mcp.py
python tests/smoke_mcp.py
python tests/smoke_approval_mcp.py
python tests/smoke_browser_mcp.py
```

유닛 테스트에는 모의 SDK/엔진/OS 응답이 포함됩니다. `smoke_*.py`는 실제 SDK와 설치된 프로그램으로 작동하는 별도 검사이며, 개인 파일 수정·개인 화면 촬영·터널 연결은 하지 않습니다. 브라우저 검사는 임시 로컬 테스트 페이지를 실제 Chrome에서 캡처하고 디코딩합니다. 검증 범위는 [docs/VALIDATION.md](docs/VALIDATION.md)에 구분했습니다.

## 공식 참고 자료

- OpenAI Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- OpenAI tunnel-client (stdio 동시 실행 제한 포함): https://github.com/openai/tunnel-client
- ChatGPT 연결 갱신: https://developers.openai.com/plugins/deploy/connect-chatgpt
- Desktop Commander 로컬 엔진: https://github.com/wonderwhy-er/DesktopCommanderMCP/tree/v0.2.51
