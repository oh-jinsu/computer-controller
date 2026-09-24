import Foundation

/// The remembered flag is onboarding history, NEVER a replacement for macOS permission.
/// Probe the actual capture helper on each launch; a refusal/revocation is not a reason
/// to repeatedly display a consent prompt. Manual menu actions can open System Settings.
enum ScreenPermissionAction: Equatable {
    case disabled, allowed, request, unavailable
    case settings(open: Bool)
}

enum ScreenPermissionPolicy {
    static let requestedKey = "MBScreenCapturePermissionRequested"

    static func action(allowed: Bool?, previouslyRequested: Bool, manual: Bool,
                       disabled: Bool) -> ScreenPermissionAction {
        if disabled { return .disabled }
        guard let allowed = allowed else { return .unavailable }
        if allowed { return .allowed }
        if !previouslyRequested { return .request }
        return .settings(open: manual)
    }
}
