# Changes

## 0.5.0-beta.16 — Computer Controller naming

- 제품 표시 이름을 **Computer Controller**로 변경했습니다. macOS 앱은 `Computer Controller.app`, Windows 실행 파일은 `Computer Controller.exe`를 사용합니다.
- MCP 도구의 플랫폼 접두사 `mac_`를 제거했습니다. 예: `status`, `read_file`, `batch_files`, `start_process`, `list_processes`, `capture_window`, `context_*`. `browser_*` 이름은 그대로 유지합니다.
- 새 배포 파일명은 `Computer-Controller-<버전>-...zip`을 사용하고 GitHub 저장소를 `oh-jinsu/computer-controller`로 변경했습니다. bundle identifier와 Python 패키지 이름은 업데이트·권한·런타임 호환성을 위해 유지합니다.
- 새 설치는 `Computer Controller` 데이터 폴더를 사용하고, 기존 `Mac Bridge` 데이터 폴더가 있으면 자동 이동하지 않고 그대로 재사용하여 터널 ID·승인 모드·브라우저 프로필·백업·컨텍스트를 보존합니다.

## 0.5.0-beta.15 — transactional batch file mutations

- `mac_batch_files`를 추가해 최대 50개의 `write`, `edit`, `move`, `mkdir`, `delete` 작업을 한 번의 MCP 호출과 한 번의 승인으로 처리합니다.
- 전체 배치를 먼저 검증하고 승인 뒤 경로 상태를 다시 확인합니다. 기존 쓰기/편집 대상은 백업하며, 중간 실패 시 이미 적용된 작업을 역순으로 원복합니다.
- `delete`는 일반 파일만 허용하며 영구 삭제 대신 내부 복구 보관소로 이동합니다. `move`는 덮어쓰기를 허용하지 않습니다.
- 배치 요청 로그에는 작업 내용이나 파일 내용 대신 작업 개수만 기록합니다. 전체 MCP 도구 수는 37개입니다.

## 0.5.0-beta.14 — file batch, move, info and search tools

- `mac_read_multiple_files`를 추가해 관련 파일 최대 20개를 한 번에 읽을 수 있습니다. 프로젝트/비밀 경로 제한은 기존 `mac_read_file`과 동일하고 총 입력 크기는 8 MiB로 제한합니다.
- `mac_create_directory`, `mac_move_file`, `mac_file_info`를 추가했습니다. 디렉터리 생성/이동은 기존 ask/always 승인 정책을 따르며 이동은 덮어쓰기를 거부합니다.
- `mac_search`를 추가해 선택한 프로젝트에서 파일명 또는 내용 검색을 한 번의 도구 호출로 수행합니다. 내부 Desktop Commander 검색 세션은 자동으로 조회·정리됩니다.
- 번들 Desktop Commander 어댑터에 `read_multiple_files`, `create_directory`, `move_file`, `get_file_info`, 검색 세션 도구를 포함하고 전체 MCP 도구 수를 36개로 늘렸습니다.

## 0.5.0-beta.13 — process inventory and cleanup

- `mac_list_processes`를 추가해 현재 사용자 프로세스를 CPU/메모리/명령 요약과 함께 확인하고, 프로젝트/브리지 관련 프로세스를 먼저 표시합니다.
- `mac_kill_process`를 추가해 `mac_list_processes`에서 방금 관찰한 `killable=true` 프로세스만 종료할 수 있습니다. PID 재사용을 막기 위해 `kill_token`이 일치해야 합니다.
- Mac Bridge 자체 프로세스와 무관한 사용자 앱은 종료 대상으로 노출하지 않으며, 브리지에서 시작했거나 선택한 작업 폴더와 연관된 프로세스만 종료 가능하도록 유지합니다.
- 번들된 Desktop Commander의 `list_processes`/`kill_process` 지원을 어댑터에 포함하고 전체 MCP 도구 수를 31개로 늘렸습니다.

## 0.5.0-beta.12 — MCP 2026-07-28 discovery

- Python MCP SDK를 2.2.0으로 올리고 서버를 `MCPServer` API로 마이그레이션해 `server/discover`와 2026-07-28 프로토콜 discovery를 지원합니다.
- 기존 29개 Mac/브라우저/프로젝트 도구와 legacy `initialize` 기반 내부 어댑터 호환성을 유지합니다.
- MCP v2의 snake_case Python 모델 필드와 숫자형 timeout API에 맞춰 도구 결과, 이미지, 주석, Desktop Commander/Playwright 클라이언트를 갱신했습니다.
- 요청 로그 래퍼를 v2 low-level `tools/call` 핸들러에 맞추고, 실제 `server/discover` smoke와 번들 검사를 추가했습니다.

## 0.5.0-beta.11 — process completion waiting

- `mac_start_process`는 기본적으로 실행한 프로세스가 끝날 때까지 기다린 뒤 PID·종료 코드·보존된 출력을 같은 응답으로 반환합니다.
- 개발 서버·Godot·REPL·`tail -f`처럼 의도적으로 계속 살아 있어야 하는 프로세스는 `wait=start`로 즉시 PID를 받을 수 있습니다.
- 기본 완료 대기는 최대 10분 안전 한도를 가지며, 한도에 도달해도 프로세스를 죽이지 않고 PID와 실행 중 상태를 반환합니다.
- 요청 로그는 기본 완료 대기에서 `process_state=completed`와 실제 종료 코드를 기록합니다.
- macOS/Linux MCP smoke와 Windows 패키지 smoke가 별도 `mac_process_output` 폴링 없이 기본 완료 대기를 검증합니다.


## 0.5.0-beta.10 — Windows x64 Preview

- Windows 11 x64용 독립 실행 앱과 GitHub Actions 빌드·실제 패키지 smoke test를 추가했습니다.
- Windows에서도 파일/PowerShell 프로세스/Chrome/영상 프레임/프로젝트 컨텍스트를 같은 29개 MCP 도구로 제공합니다.
- 지정 HWND/PID의 실제 창 캡처와 로컬 승인 대화상자를 Win32 API로 구현했습니다. 임의 데스크톱 입력 도구는 추가하지 않았습니다.
- 새 Windows 설치는 macOS와 같이 `always`와 평소 Chrome(`personal`)을 기본으로 사용합니다.
- Node·FFmpeg·Deno·Secure MCP Tunnel 런타임은 SHA-256으로 고정된 Windows x64 바이너리를 번들합니다.
- Windows Preview는 아직 Authenticode 서명과 자동 업데이트가 없습니다. 릴리스 ZIP·SHA-256으로 배포합니다.

## 0.5.0-beta.9 — command log visibility

- `mac_start_process` 요청 로그에 프로그램·서브커맨드·일반 플래그·경로 등 안전한 명령 인자를 표시합니다.
- API 키·토큰·비밀번호·Authorization 헤더·HTTP 본문·검색 패턴·인라인 코드와 스크립트 내용은 계속 마스킹합니다.
- ChatGPT 연결 안내를 최신 `Plugins → Add → Create MCP App` UI에 맞췄습니다.
- 새 설치의 `always` 및 평소 Chrome(`personal`) 기본값을 유지합니다.


## 0.5.0-beta.8 — simplified onboarding defaults

- README 설치를 터널 생성 → Runtime API 키 → 앱 실행 → Create MCP App 순서의 짧은 체크리스트로 정리하고 직접 이동 링크를 추가했습니다.
- 앱 이름을 `My Mac`으로 고정하지 않고 사용자가 원하는 MCP App 이름을 쓰도록 안내합니다.
- 실제 Mac Bridge 설정 화면 스크린샷을 README에 추가했습니다.
- 새 설치의 기본값을 `요청된 Mac 작업 항상 허용` ON, `평소 Chrome 로그인 상태 사용` ON으로 변경했습니다. 기존 사용자의 저장된 선택은 유지합니다.
- Chrome 자체의 remote-debugging/연결 승인과 macOS 화면 기록 승인은 운영체제·브라우저 권한으로 계속 별도입니다.

## 0.5.0-beta.7 — first public beta

- Concise seven-step installation checklist; detailed onboarding in docs/INSTALL.md.
- Include dependency attribution, pinned source archives and build recipes alongside the app.
- Same 29-tool runtime and screenshot onboarding as beta.6; no unfinished browser-workspace feature enabled.
- Publication remains gated on this artifact's Developer ID signature and notarization; never inherits another beta's ticket.


## 0.5.0-beta.6 — 시작 시 화면 캡처 권한 안내

- 앱 시작·다시 활성화 시 실제 캡처 helper의 권한을 조회하고, 최초 미허용 상태에서 시스템 승인 요청을 한 번 표시합니다.
- 이미 허용된 경우 재요청하지 않습니다. 거절/권한 철회 후에는 안내만 유지하고 메뉴에서 사용자가 다시 설정할 수 있습니다.
- 메뉴 막대와 설정 창에 실제 권한 상태를 표시합니다. 권한 요청이 파일·터미널 연결을 막거나 자동 촬영을 시작하지 않습니다.
- UI smoke/no-connect 모드에서는 권한 요청을 하지 않습니다. 이 버전의 공증/공개 배포 여부는 별도 확인 대상입니다.


## 0.5.0-beta.5 — 공통 영상 확인 절차

- 영상 전용 MCP 도구 5개를 제거하고 29개 공통 도구만 제공합니다.
- 기존 `mac_read_file`의 실제 이미지 반환을 재사용합니다. 새 이미지 도구는 없습니다.
- 검증된 yt-dlp/FFmpeg/시각/모아보기 코어를 일반 foreground CLI로 실행합니다.
- 일반 PID·출력·취소·pause·업데이트 대기를 사용하며 MCP 안에 영상 작업 큐를 생성하지 않습니다.
- 실제 로컬 경로를 직접 받고, 원본은 유지하며, 결과/manifest는 일반 작업 폴더에 영속 저장합니다.
- 시각/용량/시간 제한, 원본 변경 검사, 실패/정상취소 시 임시 결과 정리와 자식 종료를 검사합니다.
- beta.4의 Python bytecode 보호를 유지합니다. 이 새 빌드의 공증/공개 배포는 별도입니다.


## Unreleased — 요청·응답 로그

- MCP 도구 호출 시작/종료, 안전한 대상·결과 요약, 요청 상관 ID, 승인/지연/취소와 시간을 stderr 및 순환 JSONL에 기록합니다.
- SDK 입력 검증/도구 오류도 기록하며 본문·스크립트·응답 원문·인증 정보는 제외합니다.
- 로그 실패가 작업 결과를 바꾸거나 재실행하지 않도록 하고, stdout의 MCP 통신과 기존 승인/audit 규칙을 유지합니다.
- CLI 터널의 기본 로그를 warn으로 낮췄습니다. `--tunnel-log-level info`로 연결 진단 로그를 복원할 수 있습니다.
- 현재 실행본/기존 공증 ZIP은 변경하지 않습니다. 다음 앱 빌드는 새 버전·서명·공증이 필요합니다.

## Documentation — beta.2 onboarding

- Replaced the accumulated developer-first README with six end-user installation steps, optional browser/screen permissions, daily use, updates, migration and troubleshooting.
- Moved source launch/build commands to docs/DEVELOPMENT.md and corrected browser-mode and notarization status documentation.
- Kept private/Draft availability, pending public rollout, unsupported features and independent-runtime boundaries explicit. Documentation changes do not replace or re-sign the already verified beta.2 archive.

## 0.5.0-beta.2 — 공개 업데이트 준비

- 네이티브 앱의 GitHub 로그인·토큰 조회·API 호출을 제거하고 공개 최신 정식 릴리스의 signed appcast를 사용합니다. 수신용 앱에 GitHub CLI를 포함하지 않습니다.
- Sparkle의 기존 서명 검증과 작업 종료 후 교체를 유지하고 별도 중복 업데이트 타이머를 제거했습니다. 실패한 피드 서명의 검증 만료도 끕니다.
- 버전별 다운로드 URL 허용 규칙을 Swift로 구현·검사했습니다. HTTP, 다른 저장소, 사용자정보/포트/쿼리, 경로 변조는 거부합니다.
- Developer ID 준비 상태 조회 및 원본을 보존하는 서명·공증 도구를 추가했습니다. 인증서/자격정보를 자동 생성하거나 보안 설정을 변경하지 않습니다.
- 공개 발행은 정식 버전·배포용 서명·공증·공개 저장소를 모두 확인해야 합니다. 기존 beta.1과 서명된 ZIP은 변경하지 않습니다.
- 실제 Apple 서명·공증 및 공개 업데이트 전체 경로는 아직 검증되지 않았습니다.

## 0.5.0-beta.1 — 독립 앱 / 자동 업데이트 기반

- AppKit 메뉴 막대 앱을 만들고 Python·Node·FFmpeg/ffprobe·Deno·MCP 런타임·터널·GitHub CLI를 번들에 포함했습니다.
- 실행 코드와 데이터 root를 분리했습니다. 소스 checkout을 수정해도 앱의 실행 코드가 바뀌지 않으며, 파일 도구는 앱 번들과 내부 상태를 계속 보호합니다.
- 기존 터널 ID·작업 폴더·ask/always·브라우저 모드·일시정지 상태를 가져옵니다. Runtime 키는 기존 키체인을 재사용합니다. 이전 영상/맥락/백업/로그는 원래 위치에 남습니다.
- 기존 개발본의 permissioned personal Chrome 연결 모드를 앱 설정에 통합했습니다. 파일 업로드와 별도 배경 창은 아직 추가하지 않았습니다.
- Sparkle 2.10.0 서명된 피드/아카이브 검증, 비공개 GitHub 릴리스 조회, 6시간 자동 확인/다운로드 설정, 작업 drain과 이전 앱 보관을 구현했습니다.
- 회귀 검사 168개 및 실제 독립 번들 MCP/영상/브라우저 검사를 실행했습니다. 개발 폴더·Homebrew·기존 Python 접근 차단 환경에서는 핵심 파일/프로세스/영상 검사가 통과했습니다.
- 주의: ad-hoc 테스트 앱이며 Developer ID 서명/공증이 없습니다. Keychain에서 릴리스 서명 키 사용이 취소되어 서명된 appcast는 미발행입니다. 실제 업데이트 설치/재실행 및 기존 터널 교체는 미검증입니다.

## 0.4.0 — 브라우저 + 프로젝트 인계

- 단일 서버에 전용 브라우저 도구 12개와 작업 맥락 도구 3개를 추가해 총 34개가 됐습니다.
- Playwright MCP 0.0.82를 고정하고, 개인 Chrome과 분리한 지속형 프로필을 사용합니다. 기본은 headless입니다.
- 실제 페이지 이미지, 입력/클릭/키, 탭, 크기 조절, 콘솔 및 요청 메타데이터를 지원합니다.
- 로컬 요약은 작업 폴더별로 분리하고 revision 충돌 검사·원본 버전 보관·원자적 교체를 적용합니다.
- 기존 ask/always·백업·기록·중지 정책은 유지하며 브라우저/맥락 변경에도 적용합니다.
- 임의 코드 실행·개인 프로필 연결·파일 업로드·쿠키 내보내기 도구는 노출하지 않습니다.
- macOS의 /var → /private/var 별칭을 반영하도록 테스트용 경로를 정규화했습니다. 실제 파일 보호 정책은 완화하지 않았습니다.
- Mac에서 148개 단위 검사와 실제 MCP/엔진/영상/승인/Chrome 통합 검사를 실행했습니다. 상세 범위는 docs/VALIDATION.md에 기록합니다.

## 0.3.1 — 영구 항상 허용 선택

- `bash Mac-Start.command --approval-mode always`로 로컬 승인창 없는 모드를 한 번 선택합니다. 범위·기간 입력 없이 재시작/업데이트 후에도 유지합니다.
- 기본/미설정은 `ask`이며, 기존 사용자의 승인 선택을 업데이트만으로 바꾸지 않습니다. 별도 로컬 CLI에서 상태 조회·`ask` 복귀가 가능합니다.
- 백업·작업 기록·중지·파일 범위·PID 검사를 유지하고, 저장된 설정 오류와 실행 직전 승인 모드 변경은 실행을 거부합니다.
- `mac_status`에 실제 승인 모드를 표시하고 도구 설명/개발 지침을 일치시켰습니다. 쓰기 도구의 위험 표시는 유지합니다.
- 승인 설정·비밀·작업 내용을 Git에 넣지 않습니다. 추가 Python/npm 패키지나 새 터널은 필요하지 않습니다.
- 설정과 실행 경로 회귀 검사, 실제 MCP/엔진의 항상 허용·프로세스 재시작 검사를 추가했습니다. Mac 실연결과 테스트 환경은 검증 문서에 구분합니다.

## 0.3.0 — 단일 저장소

- Scene Bridge의 영상 처리 코어와 Mac Bridge의 파일/프로세스/창 기능을 한 저장소로 통합했습니다.
- 이전 폴더의 실행파일, `.venv`, `payload/` 및 업데이트 패키지에 대한 실행 의존성을 제거했습니다.
- `Mac-Start.command`가 독립 설치와 실행을 담당합니다. 일반 갱신은 `git pull --ff-only` 후 재시작입니다.
- 기존 설정에서 터널 ID와 작업 폴더만 이전합니다. 기존 키체인 서비스 식별자를 유지해 키를 재사용합니다.
- 실행 경로가 바뀌면 새 로컬 터널 프로필을 만들지만 OpenAI의 기존 터널 ID는 유지합니다. 이전 프로필을 삭제/덮어쓰지 않습니다.
- 영상/캡처/로컬 설정/작업기록/키/백업/설치 캐시를 Git에서 제외합니다.
- 설정 이전, 경로 변경, 이전 폴더 없이 실행 명령 구성, 설정 보호, Git 제외 등에 대한 검사 19개를 추가했습니다.
- 기존 읽기 범위/쓰기 승인/네이티브 권한 정책은 확대하지 않았습니다.

0.2.0 업데이트 패키지는 독립 배포본이 아니었으며 0.1 설치를 요구했습니다. 이 저장소에서는 그 패키지 구조를 사용하지 않습니다.
