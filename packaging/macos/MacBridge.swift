import AppKit
import Foundation
import Sparkle

struct CommandResult { let status: Int32; let out: Data; let err: Data }

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, SPUUpdaterDelegate {
    let resources = Bundle.main.resourceURL!
    var stateItem: NSMenuItem!
    var screenStatusItem: NSMenuItem!
    var screenPermissionLabel: NSTextField!
    var screenPermissionBusy = false
    var statusBar: NSStatusItem!
    var window: NSWindow!
    var message: NSTextField!
    var tunnel: NSTextField!
    var workspace: NSTextField!
    var secret: NSSecureTextField!
    var always: NSButton!
    var personal: NSButton!
    var autoUpdate: NSButton!
    var runner: Process?
    var runnerLog: FileHandle?
    var updaterController: SPUStandardUpdaterController!
    var updaterStarted = false
    var updatePending: (() -> Void)?
    var preparingUpdate = false
    var quitPending = false
    var statusTimer: Timer?
    var latestStatus: [String: Any] = [:]
    let noConnect = CommandLine.arguments.contains("--no-connect") || CommandLine.arguments.contains("--ui-smoke")

    nonisolated static func execute(_ executable: URL, _ args: [String], input: Data? = nil, env: [String: String]? = nil) -> CommandResult {
        let process = Process(); let stdout = Pipe(); let stderr = Pipe(); let stdin = Pipe()
        process.executableURL = executable; process.arguments = args
        process.standardOutput = stdout; process.standardError = stderr
        process.standardInput = input == nil ? FileHandle.nullDevice : stdin
        if let env = env { process.environment = env }
        do {
            try process.run()
            if let input = input { try stdin.fileHandleForWriting.write(contentsOf: input); try stdin.fileHandleForWriting.close() }
            let timer = DispatchSource.makeTimerSource()
            timer.schedule(deadline: .now() + 180)
            timer.setEventHandler { if process.isRunning { process.terminate() } }
            timer.resume()
            let out = stdout.fileHandleForReading.readDataToEndOfFile()
            let err = stderr.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit(); timer.cancel()
            return CommandResult(status: process.terminationStatus, out: out, err: err)
        } catch { return CommandResult(status: -1, out: Data(), err: Data(error.localizedDescription.utf8)) }
    }

    var runtimeEnvironment: [String: String] {
        var env: [String: String] = ["HOME": NSHomeDirectory(), "LANG": "en_US.UTF-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"]
        env["PATH"] = resources.appendingPathComponent("bin").path + ":/usr/bin:/bin:/usr/sbin:/sbin"
        env["PYTHONPATH"] = resources.appendingPathComponent("engine").path
        return env
    }

    func helper(_ args: [String], input: Data? = nil, completion: @escaping ([String: Any], Int32) -> Void) {
        let executable = resources.appendingPathComponent("python/bin/python3")
        let arguments = [resources.appendingPathComponent("engine/app_entry.py").path] + args
        let env = runtimeEnvironment
        DispatchQueue.global(qos: .utility).async {
            let result = Self.execute(executable, arguments, input: input, env: env)
            let data = result.status == 0 ? result.out : result.err
            let parsed = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            DispatchQueue.main.async { completion(parsed ?? ["error": "작업에 실패했습니다. 상태 로그를 확인하세요."], result.status) }
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusBar = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusBar.button?.title = "MB"
        let menu = NSMenu()
        stateItem = NSMenuItem(title: "Mac Bridge · 확인 중", action: nil, keyEquivalent: "")
        menu.addItem(stateItem)
        screenStatusItem = NSMenuItem(title: "화면 캡처 · 확인 중", action: nil, keyEquivalent: "")
        menu.addItem(screenStatusItem)
        for (title, action) in [("연결 시작", #selector(start)), ("연결 중지", #selector(stop)), ("설정…", #selector(showSettings)), ("화면 기록 권한…", #selector(screenPermission)), ("업데이트 확인…", #selector(checkUpdates)), ("이전 실행본 보기", #selector(showPrevious)), ("로그 보기", #selector(showLogs)), ("종료", #selector(quit))] {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item)
        }
        statusBar.menu = menu
        updaterController = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: self, userDriverDelegate: nil)
        buildWindow()
        refreshStatus()
        statusTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in Task { @MainActor in self?.refreshStatus(); self?.continueUpdate() } }
        if noConnect {
            message.stringValue = "UI 테스트 모드 — 기존 서버에 연결하거나 설정을 변경하지 않습니다."
            window.orderFrontRegardless()
            if CommandLine.arguments.contains("--ui-smoke") {
                print("MAC_BRIDGE_UI_READY")
                Timer.scheduledTimer(withTimeInterval: 12, repeats: false) { _ in NSApp.terminate(nil) }
            }
            return
        }
        helper(["status"]) { [weak self] result, _ in
            guard let self = self else { return }
            if result["configured"] as? Bool == true { self.start() }
            else { self.showSettings() }
        }
        // Independent from tunnel startup: missing screen permission never blocks file work.
        checkScreenPermission()
        startPublicUpdater()
        if autoUpdate.state == .on { updaterController.updater.checkForUpdatesInBackground() }
    }

    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 590, height: 490), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Mac Bridge"; window.isReleasedWhenClosed = false; window.center()
        let view = window.contentView!
        func label(_ text: String, _ y: CGFloat) { let l = NSTextField(labelWithString: text); l.frame = NSRect(x: 26, y: y, width: 535, height: 24); view.addSubview(l) }
        label("Mac Bridge · 독립 실행 앱", 445)
        message = NSTextField(wrappingLabelWithString: "기존 연결 설정을 가져오거나 새 연결을 설정하세요.")
        message.frame = NSRect(x: 26, y: 388, width: 535, height: 52); view.addSubview(message)
        label("터널 ID", 354); tunnel = NSTextField(frame: NSRect(x: 26, y: 323, width: 535, height: 26)); view.addSubview(tunnel)
        label("작업 폴더", 292); workspace = NSTextField(frame: NSRect(x: 26, y: 263, width: 430, height: 26)); view.addSubview(workspace)
        let choose = NSButton(title: "선택…", target: self, action: #selector(chooseWorkspace)); choose.frame = NSRect(x: 463, y: 261, width: 96, height: 30); view.addSubview(choose)
        label("Runtime API 키 (키체인에 있으면 비워 두세요)", 232)
        secret = NSSecureTextField(frame: NSRect(x: 26, y: 203, width: 535, height: 26)); view.addSubview(secret)
        always = NSButton(checkboxWithTitle: "요청된 Mac 작업 항상 허용 (로컬 승인창 생략)", target: nil, action: nil)
        always.frame = NSRect(x: 26, y: 167, width: 535, height: 24); always.state = .on; view.addSubview(always)
        personal = NSButton(checkboxWithTitle: "평소 Chrome 로그인 상태 사용 (Chrome 자체 허용 필요)", target: nil, action: nil)
        personal.frame = NSRect(x: 26, y: 137, width: 535, height: 24); personal.state = .on; view.addSubview(personal)
        autoUpdate = NSButton(checkboxWithTitle: "서명된 업데이트 자동 확인·다운로드", target: self, action: #selector(toggleAutomatic))
        autoUpdate.frame = NSRect(x: 26, y: 107, width: 535, height: 24)
        autoUpdate.state = UserDefaults.standard.object(forKey: "MBUpdatesEnabled") as? Bool == false ? .off : .on
        view.addSubview(autoUpdate)
        screenPermissionLabel = NSTextField(labelWithString: "화면 캡처: 확인 중")
        screenPermissionLabel.frame = NSRect(x: 26, y: 81, width: 535, height: 20)
        screenPermissionLabel.font = NSFont.systemFont(ofSize: 12)
        view.addSubview(screenPermissionLabel)
        let migrate = NSButton(title: "기존 설정 가져오기…", target: self, action: #selector(importSettings)); migrate.frame = NSRect(x: 24, y: 44, width: 190, height: 34); view.addSubview(migrate)
        let save = NSButton(title: "저장", target: self, action: #selector(saveSettings)); save.frame = NSRect(x: 380, y: 44, width: 78, height: 34); view.addSubview(save)
        let connect = NSButton(title: "연결 시작", target: self, action: #selector(start)); connect.frame = NSRect(x: 465, y: 44, width: 99, height: 34); view.addSubview(connect)
    }

    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        updatePending = nil
        helper(["cancel-update"]) { [weak self] _, _ in self?.message.stringValue = "업데이트가 중단되었습니다. 현재 실행본과 설정은 유지됩니다." }
    }

    func displayScreenPermission(_ allowed: Bool?) {
        let label: String
        switch allowed {
        case true?: label = "허용됨"
        case false?: label = "미허용 · ‘화면 기록 권한…’에서 허용하세요"
        case nil: label = "확인 실패 · ‘화면 기록 권한…’에서 다시 확인하세요"
        }
        screenStatusItem.title = "화면 캡처 · " + label
        screenPermissionLabel.stringValue = "화면 캡처: " + label
    }

    func openScreenPermissionSettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
    }

    func checkScreenPermission(manual: Bool = false) {
        guard !noConnect, screenStatusItem != nil, !screenPermissionBusy else { return }
        screenPermissionBusy = true
        // Query the SAME bundled helper used for capture, not a cached preference.
        // This action checks permission only: no screenshot, window enumeration or recording.
        helper(["permission-status"]) { [weak self] value, code in
            guard let self = self else { return }
            let allowed = code == 0 ? value["screen_recording_allowed"] as? Bool : nil
            let defaults = UserDefaults.standard
            let action = ScreenPermissionPolicy.action(allowed: allowed,
                previouslyRequested: defaults.bool(forKey: ScreenPermissionPolicy.requestedKey),
                manual: manual, disabled: self.noConnect)
            switch action {
            case .disabled:
                self.screenPermissionBusy = false
            case .allowed:
                defaults.set(true, forKey: ScreenPermissionPolicy.requestedKey)
                self.displayScreenPermission(true)
                self.screenPermissionBusy = false
            case .unavailable:
                self.displayScreenPermission(nil)
                self.screenPermissionBusy = false
            case .settings(let open):
                self.displayScreenPermission(false)
                self.screenPermissionBusy = false
                if open { self.openScreenPermissionSettings() }
            case .request:
                // Persist BEFORE requesting so relaunch/reentrant activation cannot spam prompts.
                defaults.set(true, forKey: ScreenPermissionPolicy.requestedKey)
                self.screenStatusItem.title = "화면 캡처 · macOS 승인 대기"
                self.screenPermissionLabel.stringValue = "화면 캡처: macOS에서 허용해 주세요. 요청한 창만 캡처합니다."
                self.helper(["permission"]) { [weak self] result, status in
                    guard let self = self else { return }
                    let granted = status == 0 ? result["screen_recording_allowed"] as? Bool : nil
                    self.displayScreenPermission(granted)
                    self.screenPermissionBusy = false
                    // A denial must not immediately open another prompt/settings window.
                    // The menu remains available for an explicit later settings change.
                }
            }
        }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        checkScreenPermission()
    }

    @objc func screenPermission() { checkScreenPermission(manual: true) }
    @objc func showSettings() { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); loadSettingsFields() }
    func loadSettingsFields() { helper(["status"]) { [weak self] value, _ in
        guard let self = self else { return }
        self.tunnel.stringValue = value["tunnel_id"] as? String ?? ""
        self.workspace.stringValue = value["workspace"] as? String ?? ""
        let configured = value["configured"] as? Bool == true
        self.always.state = configured ? (value["approval_mode"] as? String == "always" ? .on : .off) : .on
        self.personal.state = configured ? (value["browser_mode"] as? String == "personal" ? .on : .off) : .on
    } }
    @objc func chooseWorkspace() { let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; if panel.runModal() == .OK { workspace.stringValue = panel.url!.path } }
    @objc func importSettings() {
        guard runner == nil else { message.stringValue = "설정을 가져오려면 먼저 앱의 연결을 중지하세요."; return }
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true
        panel.message = "이전 mac-bridge 폴더를 선택하세요. 원본과 영상·백업은 삭제하지 않습니다."
        if panel.runModal() == .OK { helper(["import", "--source", panel.url!.path]) { [weak self] value, code in
            self?.message.stringValue = code == 0 ? "설정을 가져왔습니다. 기존 터미널 서버를 종료한 뒤 연결 시작을 누르세요. 이전 영상·기록은 원래 폴더에 보존됩니다." : value["error"] as? String ?? "가져오기 실패"
            self?.loadSettingsFields()
        } }
    }
    @objc func saveSettings() {
        guard runner == nil else { message.stringValue = "연결 중에는 터널 설정을 바꾸지 않습니다. 먼저 연결을 중지하세요."; return }
        let value: [String: Any] = ["tunnel_id": tunnel.stringValue, "workspace": workspace.stringValue,
            "approval_mode": always.state == .on ? "always" : "ask", "browser_mode": personal.state == .on ? "personal" : "dedicated", "runtime_key": secret.stringValue]
        guard let input = try? JSONSerialization.data(withJSONObject: value) else { return }
        secret.stringValue = ""
        helper(["configure"], input: input) { [weak self] value, code in self?.message.stringValue = code == 0 ? "설정 저장 완료. 키는 키체인에 보관됩니다." : value["error"] as? String ?? "저장 실패" }
    }
    func refreshStatus() { helper(["status"]) { [weak self] value, _ in
        guard let self = self else { return }; self.latestStatus = value
        self.stateItem.title = value["running"] as? Bool == true ? "Mac Bridge · 서버 실행 중" : (self.runner == nil ? "Mac Bridge · 중지됨" : "Mac Bridge · 연결 준비 중")
    } }
    @objc func start() {
        guard runner == nil, !noConnect else { return }
        let process = Process(); process.executableURL = resources.appendingPathComponent("python/bin/python3")
        process.arguments = [resources.appendingPathComponent("engine/app_entry.py").path, "serve"]
        process.environment = runtimeEnvironment; process.standardInput = FileHandle.nullDevice
        let log = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Logs/Mac Bridge")
        do {
            try FileManager.default.createDirectory(at: log, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let target = log.appendingPathComponent("app.log")
            if let size = try? target.resourceValues(forKeys: [.fileSizeKey]).fileSize, size > 2_000_000 { try FileManager.default.moveItem(at: target, to: log.appendingPathComponent("previous-\(Int(Date().timeIntervalSince1970)).log")) }
            FileManager.default.createFile(atPath: target.path, contents: nil, attributes: [.posixPermissions: 0o600])
            runnerLog = try FileHandle(forWritingTo: target); try runnerLog?.seekToEnd()
            process.standardOutput = runnerLog; process.standardError = runnerLog
            process.terminationHandler = { [weak self] p in DispatchQueue.main.async {
                guard let self = self else { return }; self.runner = nil; try? self.runnerLog?.close(); self.runnerLog = nil
                self.message.stringValue = p.terminationStatus == 0 ? "연결이 종료되었습니다." : "시작 또는 연결에 실패했습니다. 기존 실행본과 설정은 유지됩니다. 로그를 확인하세요."
                if self.quitPending { NSApp.reply(toApplicationShouldTerminate: true) }
            } }
            try process.run(); runner = process; message.stringValue = "서버를 시작합니다. 기존 터미널 서버가 실행 중이면 새 연결은 거부됩니다."
        } catch { message.stringValue = "실행 실패: \(error.localizedDescription)" }
    }
    @objc func stop() { runner?.terminate() }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let runner = runner, runner.isRunning { quitPending = true; runner.terminate(); return .terminateLater }
        return .terminateNow
    }
    @objc func showLogs() { NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Logs/Mac Bridge")) }
    @objc func showPrevious() { NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support/Mac Bridge/previous")) }
    @objc func toggleAutomatic() {
        UserDefaults.standard.set(autoUpdate.state == .on, forKey: "MBUpdatesEnabled")
        startPublicUpdater()
        if updaterStarted {
            updaterController.updater.automaticallyChecksForUpdates = autoUpdate.state == .on
            updaterController.updater.automaticallyDownloadsUpdates = autoUpdate.state == .on
        }
    }
    func startPublicUpdater() {
        guard !noConnect, !updaterStarted else { return }
        guard Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") as? String == PublicUpdatePolicy.feedURL,
              Bundle.main.object(forInfoDictionaryKey: "SURequireSignedFeed") as? Bool == true,
              Bundle.main.object(forInfoDictionaryKey: "SUVerifyUpdateBeforeExtraction") as? Bool == true else {
            message.stringValue = "공개 업데이트 설정을 확인하지 못했습니다. 현재 버전을 유지합니다."
            return
        }
        // Sparkle owns scheduling. Never retrieve credentials or shell out to gh.
        updaterController.updater.httpHeaders = [:]
        updaterController.updater.automaticallyChecksForUpdates = autoUpdate.state == .on
        updaterController.updater.automaticallyDownloadsUpdates = autoUpdate.state == .on
        updaterController.startUpdater()
        updaterStarted = true
    }
    @objc func checkUpdates() {
        startPublicUpdater()
        if updaterStarted { updaterController.checkForUpdates(nil) }
    }
    func updater(_ updater: SPUUpdater, shouldDownloadReleaseNotesForUpdate item: SUAppcastItem) -> Bool { false }
    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate item: SUAppcastItem, updateCheck: SPUUpdateCheck) throws {
        guard PublicUpdatePolicy.acceptsArchive(item.fileURL) else {
            throw NSError(domain: "MacBridge", code: 1, userInfo: [NSLocalizedDescriptionKey: "허용된 공개 릴리스 파일 주소가 아닙니다."])
        }
    }
    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem, untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        updatePending = installHandler; continueUpdate(); return true
    }
    func continueUpdate() {
        guard let pending = updatePending, !preparingUpdate else { return }; preparingUpdate = true
        helper(["prepare-update"]) { [weak self] result, code in
            guard let self = self else { return }; self.preparingUpdate = false
            if code == 0 && result["ready"] as? Bool == true { self.updatePending = nil; pending() }
            else { self.message.stringValue = code == 0 ? "업데이트 준비됨 — 진행 중인 작업이 끝나기를 기다립니다. 브라우저 작업이 끝났다면 연결을 닫아 주세요." : "업데이트 준비 실패. 기존 실행본을 유지합니다." }
        }
    }
    @objc func cancelUpdate() { updatePending = nil; helper(["cancel-update"]) { [weak self] _, _ in self?.message.stringValue = "업데이트 적용 대기를 취소했습니다. 새 작업을 받을 수 있습니다." } }
}

@main enum MacBridgeMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
