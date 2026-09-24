# Mac Bridge

ChatGPT에서 내 Mac의 파일·터미널·Chrome·스크린샷·영상 프레임을 다루는 연결 앱입니다.

**지원 환경:** Apple Silicon(M1 이상), macOS 26 이상, ChatGPT 개발자 모드·Tunnel 사용 가능 계정.

## 설치

1. [터널 설정](https://platform.openai.com/settings/organization/tunnels)에서 **터널을 만들고, 사용할 ChatGPT 워크스페이스를 연결**하세요. 터널 ID를 복사하세요.
2. 같은 조직에서 **터널 실행 권한(Read + Use)이 있는 Runtime API 키**를 준비하세요. [키·권한 안내](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
3. [Releases](https://github.com/oh-jinsu/mac-bridge/releases)에서 **`Mac-Bridge-0.5.0-beta.7-macos26-arm64.zip`**을 받으세요. 압축을 풀고 **Mac Bridge.app → 응용 프로그램**으로 옮겨 실행하세요.
4. **MB → 설정…**에서 **터널 ID·Runtime API 키·작업 폴더**를 입력하고 **저장 → 연결 시작**을 누르세요.
5. 처음 나오는 macOS **화면 기록 권한**을 허용하세요. 재시작 안내가 나오면 앱을 다시 실행하세요.
6. ChatGPT에서 **설정 → 보안 및 로그인 → 개발자 모드**를 켠 뒤, [Plugins](https://chatgpt.com/plugins)의 **+ → My Mac → Connection: Tunnel**에서 같은 터널을 연결하세요.
7. 새 대화에서 **My Mac**을 선택하고 **“mac_status로 연결 상태를 확인해 주세요.”**라고 요청하세요.

이미 연결하셨다면 새 터널·키 대신 **MB → 설정… → 기존 설정 가져오기…**를 사용하세요.

## 선택 설정

**승인창 없이 사용:** MB → 설정… → **요청된 Mac 작업 항상 허용**을 체크하세요. 터미널은 Mac 사용자 권한으로 실행됩니다.

**평소 Chrome 로그인 사용:** **평소 Chrome 로그인 상태 사용**을 체크하고, Chrome의 `chrome://inspect/#remote-debugging`에서 허용하세요.

## 사용

다음부터는 **앱 실행 → ChatGPT에서 My Mac 선택**만 하시면 됩니다. 종료는 **MB → 종료**, 로그는 **MB → 로그 보기**입니다.

현재 배포는 **공개 베타**입니다. 브라우저 파일 업로드·별도 백그라운드 작업 창은 아직 포함하지 않습니다. 베타는 안정판 자동 업데이트 대상이 아닙니다.

[설치·권한·문제 해결](docs/INSTALL.md) · [영상 사용법](docs/VIDEO-WORKFLOW.md) · [개발자 문서](docs/DEVELOPMENT.md) · [배포 상태](docs/RELEASE-STATUS.md) · [외부 구성요소·소스](THIRD-PARTY.md)
