# Computer Controller

ChatGPT에서 내 **Mac 또는 Windows PC**의 파일·터미널·Chrome·스크린샷·영상 프레임을 다루는 연결 앱입니다.

**지원 환경:** Apple Silicon macOS 26+ · Windows 11 x64(Preview) · ChatGPT 개발자 모드/Tunnel 사용 가능 계정.

## 설치

1. [OpenAI 터널 설정](https://platform.openai.com/settings/organization/tunnels)에서 **터널을 만들고 ChatGPT 워크스페이스를 연결**한 뒤 `tunnel_...` ID를 복사하세요.
2. [OpenAI API Keys](https://platform.openai.com/api-keys)에서 **Runtime API 키**를 만드세요. 터널 실행에 **Tunnels Read + Use** 권한이 필요합니다.
3. [Releases](https://github.com/oh-jinsu/mac-bridge/releases)에서 운영체제에 맞는 ZIP을 받으세요: **macOS `Computer-Controller-...-macos26-arm64.zip` / Windows `Computer-Controller-...-windows-x64.zip`**.
4. 앱을 실행하고 **터널 ID·Runtime API 키·작업 폴더**를 입력한 뒤 **저장 → 연결 시작**을 누르세요. **승인창 없이 사용 + 평소 Chrome 로그인 상태 사용이 기본값**입니다.
5. macOS는 처음 나오는 **화면 기록 권한**을 허용하세요. Windows는 별도 화면 기록 권한 단계가 없습니다.
6. ChatGPT에서 **설정 → 보안 및 로그인 → 개발자 모드**를 켜고, [Plugins](https://chatgpt.com/plugins)에서 **Add → Create MCP App → Connection: Tunnel**을 선택해 같은 터널을 연결하세요. **앱 이름은 원하는 이름으로 정하면 됩니다.**
7. 새 대화에서 **방금 만든 MCP App을 선택**하고 `status로 연결 상태를 확인해 주세요.`라고 요청하세요.

macOS는 **Computer Controller.app → 응용 프로그램**으로 옮겨 실행하고, Windows는 압축을 푼 폴더의 **Computer Controller.exe**를 실행합니다.

![macOS 설정 화면](docs/images/mac-bridge-settings.png)

## 선택 설정

**요청마다 승인창을 띄우려면:** 설정에서 **요청된 컴퓨터 작업 항상 허용**을 끄세요.

**평소 Chrome 로그인 사용:** Chrome의 `chrome://inspect/#remote-debugging`에서 최초 연결을 허용하세요.

## 사용

다음부터는 **앱 실행 → ChatGPT에서 만든 MCP App 선택**만 하시면 됩니다.

현재 배포는 **공개 베타**입니다. Windows판은 아직 Authenticode 서명이 없어 Microsoft Defender SmartScreen 경고가 나타날 수 있습니다. 브라우저 파일 업로드·별도 백그라운드 작업 창은 아직 포함하지 않습니다. macOS 베타는 안정판 자동 업데이트 대상이 아닙니다.

[설치·권한·문제 해결](docs/INSTALL.md) · [영상 사용법](docs/VIDEO-WORKFLOW.md) · [개발자 문서](docs/DEVELOPMENT.md) · [배포 상태](docs/RELEASE-STATUS.md) · [외부 구성요소·소스](THIRD-PARTY.md)
