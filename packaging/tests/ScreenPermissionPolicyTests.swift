import Foundation

@main enum ScreenPermissionPolicyTests {
    static func main() {
        var checks = 0
        for allowed: Bool? in [nil, false, true] {
            for previouslyRequested in [false, true] {
                for manual in [false, true] {
                    for disabled in [false, true] {
                        let actual = ScreenPermissionPolicy.action(allowed: allowed,
                            previouslyRequested: previouslyRequested, manual: manual, disabled: disabled)
                        let expected: ScreenPermissionAction
                        if disabled { expected = .disabled }
                        else if allowed == nil { expected = .unavailable }
                        else if allowed == true { expected = .allowed }
                        else if previouslyRequested { expected = .settings(open: manual) }
                        else { expected = .request }
                        precondition(actual == expected, "Unexpected permission plan")
                        checks += 1
                    }
                }
            }
        }
        precondition(ScreenPermissionPolicy.action(allowed: false, previouslyRequested: true,
            manual: false, disabled: false) == .settings(open: false), "Do not prompt on denial/revocation")
        precondition(ScreenPermissionPolicy.action(allowed: true, previouslyRequested: false,
            manual: true, disabled: false) == .allowed, "Already granted needs no request")
        print("Screen permission policy: \(checks + 2) checks passed; no OS permissions changed.")
    }
}
