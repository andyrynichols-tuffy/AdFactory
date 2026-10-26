import Foundation
import Security
import UIKit

/// Where Ad Factory is and how this phone signs in to it. The default address is the PC's
/// Tailscale link (tailnet only: the phone needs the Tailscale app switched on).
enum Server {
    static let defaultAddress = "https://tuffy.tailb24038.ts.net:8770"

    static var address: String {
        get { UserDefaults.standard.string(forKey: "server") ?? defaultAddress }
        set { UserDefaults.standard.set(newValue, forKey: "server") }
    }

    static var baseURL: URL? {
        var s = address.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        if !s.contains("://") { s = "https://" + s }
        return URL(string: s)
    }

    /// Ad Factory's sign-in cookie (adcut/auth.py), kept in the Keychain; good for 30 days.
    static var token: String? {
        get { Keychain.get("token") }
        set {
            if let v = newValue { Keychain.set("token", v) } else { Keychain.delete("token") }
        }
    }

    static var cookieName: String {
        get { UserDefaults.standard.string(forKey: "cookie") ?? "af_session" }
        set { UserDefaults.standard.set(newValue, forKey: "cookie") }
    }

    static func request(_ path: String, query: [(String, String)] = [], method: String = "GET") throws -> URLRequest {
        guard let base = baseURL, var comps = URLComponents(url: base.appendingPathComponent(path),
                                                            resolvingAgainstBaseURL: false) else {
            throw APIError.badAddress
        }
        if !query.isEmpty {
            comps.percentEncodedQuery = query.map { "\(escape($0.0))=\(escape($0.1))" }.joined(separator: "&")
        }
        guard let url = comps.url else { throw APIError.badAddress }
        var r = URLRequest(url: url)
        r.httpMethod = method
        r.httpShouldHandleCookies = false
        r.timeoutInterval = 20
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        if let t = token {
            r.setValue("\(cookieName)=\(t)", forHTTPHeaderField: "Cookie")
        }
        return r
    }

    /// Strict escaping: "+", "&" and "=" in a file or project name must survive the trip.
    static func escape(_ s: String) -> String {
        var ok = CharacterSet.alphanumerics
        ok.insert(charactersIn: "-._~")
        return s.addingPercentEncoding(withAllowedCharacters: ok) ?? s
    }
}

enum APIError: LocalizedError {
    case badAddress, signIn, wrongPassword, wait, http(Int, String)

    var errorDescription: String? {
        switch self {
        case .badAddress: return String(localized: "The Ad Factory address isn't right. Check it in Settings.")
        case .signIn: return String(localized: "Sign in to Ad Factory in Settings.")
        case .wrongPassword: return String(localized: "Wrong password.")
        case .wait: return String(localized: "Too many tries. Wait 10 minutes.")
        case .http(let code, let detail):
            return detail.isEmpty ? String(localized: "Ad Factory answered \(code).") : detail
        }
    }
}

enum API {
    private struct Detail: Decodable { var detail: String }
    private struct Token: Decodable { var cookie: String; var token: String }

    static func send(_ r: URLRequest) async throws -> Data {
        let (data, resp) = try await URLSession.shared.data(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw APIError.signIn }
        guard (200..<300).contains(code) else {
            throw APIError.http(code, (try? JSONDecoder().decode(Detail.self, from: data))?.detail ?? "")
        }
        return data
    }

    /// POST /login with Accept: application/json answers with the cookie instead of a page.
    static func signIn(password: String) async throws {
        var r = try Server.request("login", method: "POST")
        r.setValue(nil, forHTTPHeaderField: "Cookie")
        r.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        r.httpBody = Data("password=\(Server.escape(password))".utf8)
        let (data, resp) = try await URLSession.shared.data(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 {
            let d = (try? JSONDecoder().decode(Detail.self, from: data))?.detail
            throw d == "wait" ? APIError.wait : APIError.wrongPassword
        }
        guard code == 200, let t = try? JSONDecoder().decode(Token.self, from: data) else {
            throw APIError.http(code, "")
        }
        Server.cookieName = t.cookie
        Server.token = t.token
    }

    /// Any Ad Factory JSON call; the answer comes back exactly as it was written (see JSON).
    static func json(_ path: String, method: String = "GET", body: JSON? = nil) async throws -> JSON {
        var r = try Server.request(path, method: method)
        r.timeoutInterval = 60   // a whole shoot can be a few MB
        if let body {
            r.httpBody = body.data()
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return try JSON.parse(try await send(r))
    }

    static func catalog() async throws -> Data {
        try await send(try Server.request("api/camera/projects"))
    }

    static func project(_ sid: String) async throws -> ProjectDetail {
        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        return try dec.decode(ProjectDetail.self, from: try await send(try Server.request("api/camera/projects/\(sid)")))
    }

    /// An Ad Factory image (thumbnails need the sign-in cookie, so no AsyncImage); kept in memory.
    static func image(_ path: String) async -> UIImage? {
        if let hit = images.object(forKey: path as NSString) { return hit }
        guard let base = Server.baseURL, let url = URL(string: path, relativeTo: base) else { return nil }
        var r = URLRequest(url: url)
        r.httpShouldHandleCookies = false
        if let t = Server.token { r.setValue("\(Server.cookieName)=\(t)", forHTTPHeaderField: "Cookie") }
        guard let got = try? await URLSession.shared.data(for: r),
              (got.1 as? HTTPURLResponse)?.statusCode == 200, let img = UIImage(data: got.0) else { return nil }
        images.setObject(img, forKey: path as NSString)
        return img
    }

    private static let images = NSCache<NSString, UIImage>()

    static func newProject(_ p: NewProject) async throws -> Project {
        var r = try Server.request("api/camera/projects", method: "POST")
        let enc = JSONEncoder()
        enc.keyEncodingStrategy = .convertToSnakeCase
        r.httpBody = try enc.encode(p)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        return try dec.decode(Project.self, from: try await send(r))
    }
}

enum Keychain {
    private static let service = "AdCamera"

    static func set(_ key: String, _ value: String) {
        delete(key)
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
            kSecValueData as String: Data(value.utf8),
        ]
        SecItemAdd(q as CFDictionary, nil)
    }

    static func get(_ key: String) -> String? {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func delete(_ key: String) {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(q as CFDictionary)
    }
}
