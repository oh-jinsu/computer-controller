import AppKit
import Foundation
import Sparkle

struct CommandResult { let status: Int32; let out: Data; let err: Data }
struct ReleaseAsset: Decodable { let id: Int; let name: String; let url: String; let browser_download_url: String }
struct Release: Decodable { let draft: Bool; let prerelease: Bool; let assets: [ReleaseAsset] }

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, SPUUpdaterDelegate {
    let resources = Bundle.main.resourceURL!
    var stateItem: NSMenuItem!
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
    var authProcess: Process?
    var runnerLog: FileHandle?
    var updaterController: SPUStandardUpdaterController!
    var feed: String?
    var apiAssets: [String: String] = [:]
    var updateAuthorization: String?
    var updaterStarted = false
    var updatePending: (() -> Void)?
    var preparingUpdate = false
    var checking = false
    var quitPending = false
    var statusTimer: Timer?
    var latestStatus: [String: Any] = [:]
    let noConnect = CommandLine.arguments.contains("--no-connect") || CommandLine.arguments.contains("--ui-smoke")
    let repo = "oh-jinsu/mac-bridge"

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
        env["GH_PROMPT_DISABLED"] = "1"
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
        for (title, action) in [("연결 시작", #selector(start)), ("연결 중지", #selector(stop)), ("설정…", #selector(showSettings)), ("화면 기록 권한…", #selector(screenPermission)), ("업데이트 확인…", #selector(checkUpdates)), ("이전 실행본 보기", #selector(showPrevious)), ("로그 보기", #selector(showLogs)), ("종료", #selector(quit))] {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item)
        }
        statusBar.menu = menu
        updaterController = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: self, userDriverDelegate: nil)
        buildWindow()
        refreshStatus()
        statusTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in Task { @MainActor in self?.refreshStatus(); self?.continueUpdate() } }
        Timer.scheduledTimer(withTimeInterval: 21600, repeats: true) { [weak self] _ in Task { @MainActor in self?.warmUpdates(manual: false) } }
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
        warmUpdates(manual: false)
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
        always.frame = NSRect(x: 26, y: 167, width: 535, height: 24); view.addSubview(always)
        personal = NSButton(checkboxWithTitle: "평소 Chrome 로그인 상태 사용 (Chrome 자체 허용 필요)", target: nil, action: nil)
        personal.frame = NSRect(x: 26, y: 137, width: 535, height: 24); view.addSubview(personal)
        autoUpdate = NSButton(checkboxWithTitle: "서명된 업데이트 자동 확인·다운로드", target: self, action: #selector(toggleAutomatic))
        autoUpdate.frame = NSRect(x: 26, y: 107, width: 535, height: 24)
        autoUpdate.state = UserDefaults.standard.object(forKey: "MBUpdatesEnabled") as? Bool == false ? .off : .on
        view.addSubview(autoUpdate)
        let migrate = NSButton(title: "기존 설정 가져오기…", target: self, action: #selector(importSettings)); migrate.frame = NSRect(x: 24, y: 44, width: 190, height: 34); view.addSubview(migrate)
        let github = NSButton(title: "GitHub 연결…", target: self, action: #selector(signInGitHub)); github.frame = NSRect(x: 218, y: 44, width: 150, height: 34); view.addSubview(github)
        let save = NSButton(title: "저장", target: self, action: #selector(saveSettings)); save.frame = NSRect(x: 380, y: 44, width: 78, height: 34); view.addSubview(save)
        let connect = NSButton(title: "연결 시작", target: self, action: #selector(start)); connect.frame = NSRect(x: 465, y: 44, width: 99, height: 34); view.addSubview(connect)
    }

    @objc func signInGitHub() {
        guard authProcess == nil else { return }
        let p = Process(); let output = Pipe(); let input = Pipe()
        p.executableURL = resources.appendingPathComponent("bin/gh")
        p.arguments = ["auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web"]
        var env = runtimeEnvironment; env.removeValue(forKey: "GH_PROMPT_DISABLED"); env["BROWSER"] = "/usr/bin/open"
        p.environment = env; p.standardInput = input; p.standardOutput = output; p.standardError = output
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            let text = String(data: data, encoding: .utf8) ?? ""
            DispatchQueue.main.async { self?.message.stringValue = String(text.suffix(480)) }
        }
        p.terminationHandler = { [weak self] process in DispatchQueue.main.async {
            self?.authProcess = nil
            self?.message.stringValue = process.terminationStatus == 0 ? "GitHub 연결 완료. 비공개 저장소의 서명된 업데이트를 확인합니다." : "GitHub 인증을 마치지 못했습니다. 현재 앱은 계속 사용할 수 있습니다."
            self?.warmUpdates(manual: false)
        } }
        do { try p.run(); authProcess = p; try input.fileHandleForWriting.write(contentsOf: Data("\n".utf8)); try input.fileHandleForWriting.close() }
        catch { message.stringValue = "GitHub 인증 시작에 실패했습니다." }
    }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        updatePending = nil
        helper(["cancel-update"]) { [weak self] _, _ in self?.message.stringValue = "업데이트가 중단되었습니다. 현재 실행본과 설정은 유지됩니다." }
    }

    @objc func screenPermission() {
        helper(["permission"]) { [weak self] value, _ in
            self?.message.stringValue = value["screen_recording_allowed"] as? Bool == true ? "화면 기록 권한이 허용되어 있습니다." : "시스템 설정에서 Mac Bridge의 화면 기록 권한을 허용한 뒤, 요청되면 앱을 재시작하세요."
            if value["screen_recording_allowed"] as? Bool != true { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!) }
        }
    }
    @objc func showSettings() { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); loadSettingsFields() }
    func loadSettingsFields() { helper(["status"]) { [weak self] value, _ in
        guard let self = self else { return }
        self.tunnel.stringValue = value["tunnel_id"] as? String ?? ""
        self.workspace.stringValue = value["workspace"] as? String ?? ""
        self.always.state = value["approval_mode"] as? String == "always" ? .on : .off
        self.personal.state = value["browser_mode"] as? String == "personal" ? .on : .off
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
        authProcess?.terminate()
        if let runner = runner, runner.isRunning { quitPending = true; runner.terminate(); return .terminateLater }
        return .terminateNow
    }
    @objc func showLogs() { NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Logs/Mac Bridge")) }
    @objc func showPrevious() { NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support/Mac Bridge/previous")) }
    @objc func toggleAutomatic() {
        UserDefaults.standard.set(autoUpdate.state == .on, forKey: "MBUpdatesEnabled")
        if updaterStarted { updaterController.updater.automaticallyChecksForUpdates = autoUpdate.state == .on; updaterController.updater.automaticallyDownloadsUpdates = autoUpdate.state == .on }
        else if autoUpdate.state == .on { warmUpdates(manual: false) }
    }
    @objc func checkUpdates() { warmUpdates(manual: true) }

    func warmUpdates(manual: Bool) {
        guard !checking, !noConnect, (manual || autoUpdate.state == .on) else { return }; checking = true
        let gh = resources.appendingPathComponent("bin/gh"); let env = runtimeEnvironment; let repo = self.repo
        let preview = Bundle.main.object(forInfoDictionaryKey: "MBPreviewBuild") as? Bool == true
        DispatchQueue.global(qos: .utility).async {
            let releases = Self.execute(gh, ["api", "repos/\(repo)/releases?per_page=20"], env: env)
            let rows = (try? JSONDecoder().decode([Release].self, from: releases.out)) ?? []
            let selected = rows.first { !$0.draft && (preview || !$0.prerelease) && $0.assets.contains { $0.name == "appcast.xml" } }
            // Uses the installed GitHub CLI's normal authenticated keychain access.
            // The token exists only in process memory; never send it through the MCP or persist it.
            let credentials = selected == nil ? nil : Self.execute(gh, ["auth", "token", "--hostname", "github.com"], env: env)
            let token = credentials.flatMap { $0.status == 0 ? String(data: $0.out, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) : nil }
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }; self.checking = false
                guard let selected = selected, let asset = selected.assets.first(where: { $0.name == "appcast.xml" }), let token = token, !token.isEmpty else {
                    if manual { self.showSettings(); self.message.stringValue = "자동 업데이트 대기: 서명된 게시 릴리스 또는 이 비공개 저장소의 GitHub 인증이 아직 없습니다. 현재 버전은 그대로 유지됩니다." }; return
                }
                let prefix = "https://api.github.com/repos/\(repo)/releases/assets/"
                guard asset.url.hasPrefix(prefix) else { return }
                self.feed = asset.url
                self.apiAssets = Dictionary(uniqueKeysWithValues: selected.assets.filter { $0.url.hasPrefix(prefix) }.map { ($0.browser_download_url, $0.url) })
                self.updateAuthorization = "Bearer " + token
                self.updaterController.updater.httpHeaders = ["Authorization": "Bearer " + token, "Accept": "application/octet-stream"]
                if !self.updaterStarted { self.updaterController.startUpdater(); self.updaterStarted = true }
                self.updaterController.updater.automaticallyChecksForUpdates = self.autoUpdate.state == .on
                self.updaterController.updater.automaticallyDownloadsUpdates = self.autoUpdate.state == .on
                if manual { self.updaterController.checkForUpdates(nil) }
                else { self.updaterController.updater.checkForUpdatesInBackground() }
            }
        }
    }
    func feedURLString(for updater: SPUUpdater) -> String? { feed }
    func updater(_ updater: SPUUpdater, shouldDownloadReleaseNotesForUpdate item: SUAppcastItem) -> Bool { false }
    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate item: SUAppcastItem, updateCheck: SPUUpdateCheck) throws {
        guard let url = item.fileURL?.absoluteString, apiAssets[url] != nil else { throw NSError(domain: "MacBridge", code: 1, userInfo: [NSLocalizedDescriptionKey: "이 저장소의 검증된 릴리스 파일이 아닙니다."]) }
    }
    func updater(_ updater: SPUUpdater, willDownloadUpdate item: SUAppcastItem, with request: NSMutableURLRequest) {
        if let original = item.fileURL?.absoluteString, let api = apiAssets[original] {
            request.url = URL(string: api)
            request.setValue(updateAuthorization, forHTTPHeaderField: "Authorization")
            request.setValue("application/octet-stream", forHTTPHeaderField: "Accept")
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
