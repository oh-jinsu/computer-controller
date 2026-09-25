# 릴리스 검증·공개 상태

기준: 2026-09-25. 이 문서는 현재 확인된 배포 상태를 구분합니다. 최신 공개 여부는 [Releases](https://github.com/oh-jinsu/mac-bridge/releases)와 릴리스 설명을 확인하세요.

## 검증된 파일

| 항목 | 확인 내용 |
| --- | --- |
| 버전 | `0.5.0-beta.2` / 빌드 `50002` |
| 대상 | Apple Silicon(arm64), macOS 26 이상 |
| 배포 ZIP | `Mac-Bridge-0.5.0-beta.2-macos26-arm64.zip` |
| 크기 | 244,482,885 bytes, 약 233 MiB |
| ZIP SHA-256 | `36794d27f97ad4bdb74e3ed962e849ba07eaa6e74618b3757dee3fd5276e1572` |
| 릴리스 자동화 실행 커밋 | `c8b37425c2bb473d26d24ec0b404a2874ab0f11a` |
| Apple 상태 | 공증된 앱 내보내기, 코드 서명과 공증 확인서 검증, Gatekeeper `Notarized Developer ID` 판정 통과 |
| 업데이트 파일 | ZIP과 appcast 서명 검증, GitHub 업로드 파일 5개의 해시 일치 확인 |
| 재실행 | 같은 체크포인트 재실행에서 Apple 재접수·파일 재업로드 없이 완료 |
| 공개 여부 | 현재 비공개 저장소의 Draft/prerelease. 일반 공개 다운로드가 아님 |

릴리스 자동화는 이미 공증된 동일 beta.2 앱을 검증해 재사용했습니다. 해당 실행 커밋의 모든 변경이 새로 컴파일되어 공증됐다는 뜻은 아닙니다. 빌드 출처 파일의 재사용 여부와 앱 내용 검증을 함께 확인해야 합니다.

## 검증 범위를 구분하세요

완료한 것은 **해당 beta.2 파일의 서명·공증, 빌드 Mac에서의 번들 통합 검사와 업로드 검증**입니다. 별도 테스트 앱에서는 변조된 업데이트 거부와 정상 버전 교체·재실행도 확인했습니다. 테스트 앱은 실제 운영 Mac Bridge의 공개 피드 경로를 대신 검증한 것이 아닙니다.

여전히 구별해서 마쳐야 하는 것은 다른 Mac에서의 최초 설치·연결, 실제 공개 최신 안정판 피드에서의 앱 업데이트·재연결, 포함된 외부 구성요소의 재배포 조건 검토, 소스/이력 공개 범위 검토입니다. 현재 개인 Chrome 파일 업로드와 별도 백그라운드 창도 구현 완료한 기능이 아닙니다.

## 문서 변경과 설치본 변경은 다릅니다

README와 개발 문서를 수정해도 이미 검증한 ZIP, appcast, 체크섬과 빌드 출처 파일은 재작성하지 않습니다. GitHub 릴리스 **설명 본문**은 설치 가이드로 개선할 수 있지만, 서명·체크섬 대상인 첨부 파일을 몰래 덮어쓰지 않습니다.

코드·버전이 바뀌는 다음 앱은 새 버전으로 빌드·서명·공증합니다. [릴리스 자동화](RELEASE-PIPELINE.md)의 체크포인트는 원래 소스 커밋에 묶여 있으므로 새 문서 커밋에서 이전 체크포인트를 강제로 이어가지 않습니다.

GitHub 기본 브랜치에 소스를 병합하는 것, 저장소를 공개하는 것, 릴리스를 게시하는 것, 사용자의 실행본을 교체하는 것은 각각 다른 작업입니다. 어느 하나가 끝났다고 다른 단계까지 완료됐다고 보고하지 않습니다.

## 공개 베타 0.5.0-beta.8

새 설치에서 **요청된 Mac 작업 항상 허용**을 기본값으로 하고, README의 터널/API 키 직링크·Create MCP App 안내·설정 화면 스크린샷을 반영한 버전입니다. 파일명은 `Mac-Bridge-0.5.0-beta.8-macos26-arm64.zip`입니다. 해당 빌드의 서명·공증·게시 상태는 릴리스 검증 결과에 따라 갱신합니다.

## 공개 배포 상태

`0.5.0-beta.8`은 공개 베타로 배포되어 있습니다. 기존 사용자의 저장된 승인·브라우저 모드는 유지하며, 새 설치는 `always`와 평소 Chrome(`personal`)이 기본입니다. 별도 Chrome 작업 창·파일 업로드는 아직 포함하지 않습니다. 실제 서명·공증·다운로드 검사 결과는 해당 릴리스의 검증 파일을 확인하세요.

## 로컬 교체용 0.5.0-beta.9

안전한 명령 인자 로그와 최신 `Plugins → Add → Create MCP App` 안내를 포함한 실행본입니다. 파일명은 `Mac-Bridge-0.5.0-beta.9-macos26-arm64.zip`입니다. 현재 목적은 기존 설치의 로컬 교체이며, 공개 beta.9 릴리스 여부는 별도입니다.

## Windows Preview 0.5.0-beta.10

Windows 11 x64용 첫 Preview입니다. 파일명은 `Mac-Bridge-0.5.0-beta.10-windows-x64.zip`입니다. GitHub Windows 러너에서 패키지 자체를 실행해 MCP/파일/PowerShell/영상/브라우저 smoke test를 통과한 빌드만 게시합니다. 현재 Windows 바이너리는 Authenticode 미서명이며 SmartScreen 평판/서명 검증은 제공하지 않습니다. SHA-256 파일을 함께 배포합니다.

## 0.5.0-beta.11 — process completion waiting

`mac_start_process`의 기본 동작을 프로세스 종료 대기로 변경한 cross-platform Preview입니다. Windows 파일명은 `Mac-Bridge-0.5.0-beta.11-windows-x64.zip`이며, macOS는 새 빌드 번호 `50011`로 별도 서명·공증합니다. `wait=start`는 의도적으로 장시간 실행되는 서버·REPL 등에만 사용합니다.


## 0.5.0-beta.12 — MCP 2026-07-28 discovery

ChatGPT 플러그인 새로고침이 사용하는 `server/discover`를 지원하도록 Python MCP SDK 2.2.0과 `MCPServer`로 마이그레이션한 Preview입니다. 빌드 번호는 `50012`이며 Windows 빌드의 파일명 규칙은 `Mac-Bridge-0.5.0-beta.12-windows-x64.zip`입니다. 소스 smoke에서 2026-07-28 discovery, 29개 도구, Desktop Commander, 요청 로그, 영상 및 전용 브라우저 경로를 검증합니다. 로컬 Preview 빌드와 사용 중 앱 교체 검증은 서명·공증된 공개 릴리스와 구분합니다.


## 0.5.0-beta.13 — process inventory and cleanup

프로젝트 개발 중 남는 Godot·Node·Python·서버 계열 프로세스를 확인하고 정리할 수 있도록 `mac_list_processes`와 `mac_kill_process`를 추가한 Preview입니다. 빌드 번호는 `50013`이며 Windows 파일명 규칙은 `Mac-Bridge-0.5.0-beta.13-windows-x64.zip`입니다. 전체 도구 수는 31개입니다. 종료 도구는 목록에서 방금 관찰한 동일 프로세스의 `kill_token`을 요구하고, Mac Bridge 자체 및 선택한 프로젝트와 무관한 프로세스는 거부합니다.
