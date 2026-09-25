# 개발 환경과 소스 실행

앱을 사용하기만 하시는 분은 [README의 설치 안내](../README.md)를 따르세요. 여기의 Git·터미널·빌드 명령은 개발자와 기존 소스 설치 사용자용입니다.

## 소스와 실행 앱을 구분하세요

```text
~/dev/mac-bridge                         개발 소스
응용 프로그램/Computer Controller.app              독립 실행본
~/Library/Application Support/Computer Controller  앱의 설정·미디어·작업 기록
```

앱은 소스 체크아웃이나 그 `.venv`를 import하지 않습니다. 소스 변경은 새 앱 빌드·검증·배포 전까지 실행 중인 앱에 반영되지 않습니다. 반면 아래의 **소스 실행 방식은 해당 체크아웃을 직접 사용**합니다. 소스 서버를 실행하면서 같은 체크아웃을 수정하면 완전히 분리된 개발이 아니므로 작업 사본이나 독립 앱을 사용하세요.

실행 중인 터널과 같은 ID를 사용하는 서버를 동시에 두 개 실행하지 마세요. GitHub의 브랜치 병합은 사용자의 Mac에서 자동 `pull`하거나 실행본을 재시작하는 작업과 다릅니다.

## 개발 소스 받기

저장소가 비공개인 동안은 GitHub 접근 권한이 필요합니다. 공개 저장소 다운로드와 설치자의 앱 실행에는 GitHub 인증을 요구하지 않습니다.

```sh
git clone https://github.com/oh-jinsu/mac-bridge.git
cd mac-bridge
```

먼저 [AGENTS.md](../AGENTS.md)와 현재 브랜치의 변경 사항을 확인하세요. 다른 대화나 사용자가 수정 중인 파일을 강제로 초기화하지 마세요.

## 기존 소스 방식으로 실행하기

```sh
bash Mac-Start.command
```

이 명령은 개발용 환경을 준비하며 필요한 도구가 없으면 설치합니다. **릴리스 앱과 달리 개발 컴퓨터에는 Homebrew, uv, Node, 영상 도구 등의 준비가 필요할 수 있습니다.** 첫 실행에서 기존 설정을 가져오거나 터널 ID·실행용 키·작업 폴더를 설정합니다. 키는 로컬 숨김 입력 또는 키체인을 사용하고 대화에 붙여 넣지 마세요.

기존 설치에서 한 번 가져올 때:

```sh
bash Mac-Start.command --migrate "/실제/기존/설치/폴더"
```

일반적인 소스 업데이트는 실행을 Ctrl+C로 중지한 뒤:

```sh
git pull --ff-only
bash Mac-Start.command
```

명령이 실패하거나 로컬 변경이 있으면 해결한 뒤 진행하세요. 강제 `reset`, 사용자 파일 삭제, 다른 브랜치 파일 덮어쓰기는 하지 않습니다.

## 승인·브라우저 모드

새 소스 설치도 기본값은 `always`입니다. 요청마다 승인창을 띄우려면 처음 한 번 `ask`로 바꾸세요.

```sh
bash Mac-Start.command --approval-mode ask
```

다음부터는 `bash Mac-Start.command`입니다. 현재 모드 확인과 변경:

```sh
.venv/bin/python -m mac_bridge.local approval
.venv/bin/python -m mac_bridge.local approval --mode ask
```

기간·작업별 범위를 재설정하지 않으며 선택은 로컬 `.state`에 저장됩니다. 코드 업데이트만으로 사용자 선택을 바꾸지 않습니다. `always`는 로컬 승인창을 생략할 뿐, 요청하지 않은 삭제·외부 전송을 허가하거나 셸을 격리하는 기능이 아닙니다.

브라우저 모드 선택은 소스 실행을 중지한 상태에서 해당 체크아웃에 적용하세요.

```sh
.venv/bin/python -m mac_bridge.browser_connection --mode personal
# 전용 테스트 프로필로 복귀:
.venv/bin/python -m mac_bridge.browser_connection --mode dedicated
```

일반 Chrome 연결은 사용자가 Chrome의 연결 허용을 마쳐야 합니다. [브라우저 안내](BROWSER-CONTEXT.md)를 참고하세요. 설정 변경 후 실행 중인 연결을 닫고 다시 시작해야 합니다.

## 테스트

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke_mac_mcp.py
python tests/smoke_mcp.py
python tests/smoke_approval_mcp.py
python tests/smoke_browser_mcp.py
python tests/smoke_personal_chrome.py
```

단위 테스트의 모의 SDK·OS 응답과 실제 MCP/FFmpeg/브라우저 검사를 구별하세요. 실제 브라우저 검사는 일회용 프로필과 로컬 테스트 페이지를 사용하며 개인 계정의 메일 발송·게시·파일 업로드를 하지 않습니다. 테스트용 앱의 업데이트 성공도 실제 운영 앱의 공개 피드 기반 업데이트와 구별합니다.

소스 설치의 강제 재검사는 `bash Mac-Start.command --recheck`로 실행할 수 있습니다. 앱 번들 검사는 [배포 구조](APP-DISTRIBUTION.md)와 `packaging/scripts/smoke_bundle.py`를 참고하세요.

## 새 버전 배포

소스와 버전·빌드 번호를 검토·커밋·푸시한 후:

```sh
bash Mac-Release.command           # 검증된 GitHub Draft 생성
bash Mac-Release.command --publish # 공개 저장소의 정식 버전일 때만 게시
```

[재개 가능한 릴리스 자동화](RELEASE-PIPELINE.md)가 빌드·Developer ID 서명·Apple 공증·검사·Sparkle 서명·업로드를 이어갑니다. 중단되면 **같은 커밋의 같은 실행 기록**에서 재개하세요. 문서만 수정했더라도 이전 릴리스 체크포인트를 새 커밋에 억지로 재사용하거나 기존 서명 파일을 덮어쓰지 않습니다.

GitHub 공개 전환, 새 안정판 버전 지정, 코드 라이선스 선택은 별도의 검토 대상입니다. 공개 소스라고 해서 인증키·사용자 상태·브라우저 프로필을 공개하는 것은 아닙니다. `.state`, `.runtime`, `.venv`, 미디어, 캡처, 개인 로그와 비밀키는 커밋하지 마세요.


현재 영상 확인은 [공통 프로세스·파일 작업 절차](VIDEO-WORKFLOW.md)를 사용합니다. 이전 전용 영상 MCP 도구와 input 폴더 제한은 새 실행 경로에 적용되지 않습니다. pause/업데이트 대기는 공통 프로세스 관리로 처리합니다.
