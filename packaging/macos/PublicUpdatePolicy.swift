import Foundation

/// Public download endpoints only. No GitHub OAuth, API token, custom host or
/// runtime feed override is accepted. Sparkle verifies feed AND archive signatures.
enum PublicUpdatePolicy {
    static let repository = "oh-jinsu/mac-bridge"
    static let feedURL = "https://github.com/\(repository)/releases/latest/download/appcast.xml"

    static func acceptsArchive(_ url: URL?) -> Bool {
        guard let url = url,
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme == "https", parts.host == "github.com",
              parts.user == nil, parts.password == nil, parts.port == nil,
              parts.query == nil, parts.fragment == nil,
              !parts.percentEncodedPath.contains("%") else { return false }
        let prefix = "/\(repository)/releases/download/"
        guard parts.path.hasPrefix(prefix) else { return false }
        let tail = String(parts.path.dropFirst(prefix.count))
        let segments = tail.split(separator: "/", omittingEmptySubsequences: false)
        guard segments.count == 2 else { return false }
        let tag = String(segments[0]), name = String(segments[1])
        let alphabet = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-")
        return tag.hasPrefix("v") && tag.count > 1 && !tag.contains("..")
            && tag.unicodeScalars.allSatisfy { alphabet.contains($0) }
            && name.hasPrefix("Mac-Bridge-") && name.hasSuffix(".zip")
            && !name.contains("..") && name.unicodeScalars.allSatisfy { alphabet.contains($0) }
    }
}
