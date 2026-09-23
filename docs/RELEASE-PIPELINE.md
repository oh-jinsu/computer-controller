# 한 번에 배포하기 — 개발자용

앱 사용자는 `Mac Bridge.app`만 실행합니다. 아래 명령은 배포자가 새 버전을 만들 때만 사용합니다.

## 평소 사용하는 명령

```sh
# 검증된 배포 파일을 GitHub Draft로 업로드 (기본값)
bash Mac-Release.command

# 이미 공개된 저장소에 정식 버전을 게시하고 latest로 지정
bash Mac-Release.command --publish
```

소스와 `packaging/release.json`의 버전·빌드 번호를 검토하여 커밋하고 GitHub에 푸시한 다음 실행합니다. 개발자 인증서가 하나이면 자동으로 선택하고, Xcode에 로그인된 Apple 계정을 재사용합니다. 인증서를 매번 생성하거나 공증 비밀번호를 별도로 입력하지 않습니다. 여러 Developer ID 인증서가 있으면 `--identity`로 정확히 선택합니다. macOS의 키체인 자체 접근 허용/계정 만료/인증서 갱신이 필요한 경우에는 정상 권한 절차를 완료해야 하며, 스크립트가 이를 우회하지 않습니다.

새 버전의 표시 이름(`display_version`), 엔진 버전(`engine_version`), 증가하는 정수 `build_number`, `preview`와 Python 모듈의 버전은 개발 변경과 함께 관리합니다. 같은 버전의 기존 Git 태그나 배포 파일을 다른 코드로 덮어쓰지 않습니다. 베타는 `0.5.0-beta.N`/`preview: true`, 정식 버전은 `0.5.0`/`preview: false` 형태입니다.

`--publish`는 저장소가 여전히 비공개이거나 베타 설정이면 시작 전에 거부합니다. 저장소 공개 전환, 베타를 정식 버전으로 바꾸기, 소스 커밋/푸시는 암묵적으로 하지 않습니다. `--draft`는 게시하지 않은 릴리스 초안만 만듭니다.

## 자동으로 이어지는 단계

1. 소스 상태·버전·인증서·GitHub 권한을 확인하고 단위/회귀 검사를 실행합니다.
2. 기존 독립 앱 빌더로 코드를 물리적으로 복사하고 필요한 런타임을 묶습니다. 운영 앱이나 터널은 바꾸지 않습니다.
3. 새 앱 사본의 네이티브 구성요소를 안쪽부터 Developer ID로 서명합니다. Hardened Runtime과 보안 타임스탬프를 적용합니다.
4. Xcode 아카이브를 만들고 `xcodebuild -exportArchive`의 `developer-id`/`upload` 경로로 Apple 공증에 제출합니다. App Store 심사가 아닙니다.
5. 같은 아카이브에 `-exportNotarizedApp`을 호출해 완료를 기다립니다. 공증된 내보내기 결과의 코드 서명·공증 티켓·Gatekeeper 판정을 확인합니다.
6. 공증본에 포함된 Python/Node/FFmpeg/Playwright로 임시 데이터 기반 실제 통합 검사를 실행합니다. 실제 터널·사용자 Chrome 계정은 건드리지 않습니다.
7. 최종 앱으로 ZIP을 만들고 Sparkle의 아카이브·업데이트 목록 서명을 검증합니다. 빌드 출처와 체크섬을 작성합니다.
8. GitHub에는 우선 Draft를 생성하고 파일을 올립니다. 서버의 SHA-256(없으면 재다운로드한 파일)을 로컬 결과와 비교합니다. 태그가 다른 커밋을 가리키거나 파일이 다르면 중단합니다.
9. `--publish`일 때만 모든 검증 후 Draft를 게시하고 최신 안정판으로 지정합니다.

이 방식은 릴리스 제작 자동화입니다. 새 앱의 실제 설치/실행과 이미 설치된 앱의 자동 업데이트는 별도의 소비 경로입니다. 릴리스 생성이 운영 터널을 자동 재시작하지는 않습니다.

## 중단 후 이어가기

각 단계의 결과는 Git에서 제외한 `dist/releases/v<버전>/release-state.json`에 저장합니다. 작업 로그도 같은 폴더에만 저장하며 키를 인자로 전달하거나 원문 로그를 Git에 올리지 않습니다.

**같은 소스 커밋에서 같은 명령을 다시 실행하면 됩니다.** 완료한 빌드·서명·검사는 결과 파일의 해시를 확인한 뒤 재사용합니다. GitHub에 이미 동일한 파일이 있으면 다시 올리지 않습니다. 다른 바이트는 덮어쓰지 않고 거부합니다.

공증 접수 직전에 체크포인트를 저장합니다. 응답을 받기 전에 프로세스가 종료됐거나 네트워크 오류가 나서 접수 결과를 모르더라도 **다시 업로드하지 않습니다.** 기존 아카이브의 처리 상태만 조회합니다. 상태를 확정하지 못하면 로그/Xcode에서 확인해야 합니다.

기본은 30초 간격으로 최대 20분 동안 공증 완료를 기다립니다. Apple 검사가 계속 진행 중이면 종료 코드 `75`로 끝나며 같은 명령으로 이어갈 수 있습니다. 이를 공증 거절이나 성공으로 처리하지 않습니다. 자동으로 별도 백그라운드 감시 서비스를 설치하지도 않습니다.

```sh
bash Mac-Release.command --status       # 로컬 진행 기록만 조회
bash Mac-Release.command --wait-minutes 60
bash Mac-Release.command --prepare-only # Apple 공증/서명까지, GitHub 쓰기는 하지 않음
```

서버/키체인/보안 설정을 재설정하지 않으며, 릴리스용 잠금으로 같은 작업의 중복 실행을 막습니다. 빌드 중 실패한 사본은 보존하고 새 시도는 새 경로를 사용합니다. 소스 커밋 또는 배포 설정이 바뀌면 이전 단계와 섞지 않고 중단합니다. 다음 코드 변경을 배포할 때는 새 버전을 사용하세요.

## 이미 공증된 결과 재사용

이전에 공증을 받은 **동일한 버전·빌드·키·업데이트 경로·Python/JS 엔진 소스**인 앱은 명시적으로 지정해 재사용할 수 있습니다. 인증서 팀과 공증 확인서를 다시 검증하고, 전체 통합 검사를 거친 뒤 서명 ZIP을 만듭니다. 이 옵션은 공증 우회가 아니며 새 공증 제출을 하지 않습니다.

```sh
bash Mac-Release.command --draft --adopt-notarized "/실제/공증된/Mac Bridge.app"
```

이미 새 빌드/다른 접수가 시작된 실행 기록에 공증본을 끼워 넣는 것은 거부합니다. 기존 앱이 변경된 소스와 맞지 않으면 새 버전을 빌드해야 합니다. 출처 JSON의 `source_commit`은 릴리스 도구를 실행한 커밋이며, 재사용한 앱에는 별도의 새 기능을 주입하지 않습니다.

## 검증 범위

`tests/test_release_pipeline.py`는 네트워크·Apple·서명을 모의 처리하여 순서, 실패 시 중단, 중복 업로드 방지, 재개, 해시 불일치, 태그 충돌, GitHub 오류, 공개/비공개 구분을 검사합니다. 실제 Developer ID 서명·Apple 공증의 동작 결과와 혼동하지 마세요.

실제 릴리스 실행 시 `release-state.json`, `BUILD-PROVENANCE.json`, `SHA256SUMS.txt`와 각 단계의 종료 결과가 증거입니다. 임시 브라우저 검사 통과는 평소 Chrome의 글 발행/영상 업로드나 공개 피드를 이용한 운영 앱 교체까지 시험했다는 뜻이 아닙니다.

## 공식 근거

- Apple Xcode notarization/export: https://help.apple.com/xcode/mac/current/en.lproj/dev88332a81e.html
- Apple custom notarization workflows: https://developer.apple.com/documentation/security/customizing-the-notarization-workflow
- Sparkle archive/feed signing: https://sparkle-project.org/documentation/publishing/
- GitHub draft-first releases: https://cli.github.com/manual/gh_release_create
