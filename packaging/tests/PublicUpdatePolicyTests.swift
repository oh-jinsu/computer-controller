import Foundation

@main enum PublicUpdatePolicyTests {
    static func main() {
        let base = "https://github.com/oh-jinsu/mac-bridge/releases/download/"
        let good = [base + "v0.5.0/Computer-Controller-0.5.0-macos26-arm64.zip",
                    base + "v0.5.0-beta.2/Computer-Controller-0.5.0-beta.2-macos26-arm64.zip"]
        let bad = ["http://github.com/oh-jinsu/mac-bridge/releases/download/v1/Computer-Controller-1.zip",
                   "https://github.com.evil.test/oh-jinsu/mac-bridge/releases/download/v1/Computer-Controller-1.zip",
                   "https://user:pass@github.com/oh-jinsu/mac-bridge/releases/download/v1/Computer-Controller-1.zip",
                   "https://github.com:443/oh-jinsu/mac-bridge/releases/download/v1/Computer-Controller-1.zip",
                   "https://github.com/another/repo/releases/download/v1/Computer-Controller-1.zip",
                   base + "v1/Computer-Controller-1.zip?token=anything",
                   base + "v1/Computer-Controller-1.zip#fragment",
                   base + "v1/../Computer-Controller-1.zip",
                   base + "v1/%2e%2e/Computer-Controller-1.zip",
                   base + "v1/Computer-Controller-%252f.zip",
                   base + "v1/unrelated.zip", base + "v1/Computer-Controller-1.pkg",
                   base + "v1//Computer-Controller-1.zip", base + "//Computer-Controller-1.zip",
                   base + "v../Computer-Controller-1.zip", "file:///tmp/Computer-Controller-1.zip"]
        for value in good { precondition(PublicUpdatePolicy.acceptsArchive(URL(string: value)), value) }
        for value in bad { precondition(!PublicUpdatePolicy.acceptsArchive(URL(string: value)), value) }
        precondition(!PublicUpdatePolicy.acceptsArchive(nil))
        precondition(PublicUpdatePolicy.feedURL == "https://github.com/oh-jinsu/mac-bridge/releases/latest/download/appcast.xml")
        print("Public update URL policy: 20 checks passed; no network or credentials used.")
    }
}
