import Foundation

/// A shoot exactly as Ad Factory sent it. The editor changes a few fields and sends the whole
/// shoot back (PUT /api/shoots/<id> saves all of it), so everything else must survive the trip
/// untouched: numbers keep their written form ("1.0" stays "1.0"), because Ad Factory
/// fingerprints a video's takes to tell whether its render is out of date (render.video_sig).
enum JSON: Equatable {
    case null
    case bool(Bool)
    case number(String)        // the literal as written
    case string(String)
    case array([JSON])
    case object([(String, JSON)])   // in the order it came

    static func == (a: JSON, b: JSON) -> Bool {
        switch (a, b) {
        case (.null, .null): return true
        case let (.bool(x), .bool(y)): return x == y
        case let (.number(x), .number(y)): return x == y
        case let (.string(x), .string(y)): return x == y
        case let (.array(x), .array(y)): return x == y
        case let (.object(x), .object(y)): return x.count == y.count && zip(x, y).allSatisfy { $0.0 == $1.0 && $0.1 == $1.1 }
        default: return false
        }
    }

    // MARK: reading

    subscript(key: String) -> JSON? {
        get {
            guard case .object(let kv) = self else { return nil }
            return kv.first { $0.0 == key }?.1
        }
        set {
            guard case .object(var kv) = self else { return }
            if let i = kv.firstIndex(where: { $0.0 == key }) {
                if let newValue { kv[i].1 = newValue } else { kv.remove(at: i) }
            } else if let newValue {
                kv.append((key, newValue))
            }
            self = .object(kv)
        }
    }

    var string: String? { if case .string(let s) = self { return s } else { return nil } }
    var bool: Bool? { if case .bool(let b) = self { return b } else { return nil } }
    var double: Double? { if case .number(let n) = self { return Double(n) } else { return nil } }
    var int: Int? { double.map { Int($0) } }
    var array: [JSON]? { if case .array(let a) = self { return a } else { return nil } }
    var keys: [String] { if case .object(let kv) = self { return kv.map(\.0) } else { return [] } }
    var isNull: Bool { self == .null }

    // MARK: writing (in the form Python's json.dumps uses)

    static func float(_ v: Double) -> JSON {
        guard v.isFinite else { return .null }
        if v == v.rounded(), abs(v) < 1e16 { return .number(String(format: "%.1f", v)) }
        return .number("\(v)")
    }

    static func int(_ v: Int) -> JSON { .number(String(v)) }

    // MARK: text

    static func parse(_ data: Data) throws -> JSON {
        var p = Parser(bytes: [UInt8](data))
        p.space()
        let v = try p.value()
        p.space()
        guard p.i == p.bytes.count else { throw p.fail("extra text") }
        return v
    }

    func data() -> Data {
        var out = ""
        write(&out)
        return Data(out.utf8)
    }

    private func write(_ out: inout String) {
        switch self {
        case .null: out += "null"
        case .bool(let b): out += b ? "true" : "false"
        case .number(let n): out += n
        case .string(let s): JSON.quote(s, &out)
        case .array(let a):
            out += "["
            for (i, v) in a.enumerated() {
                if i > 0 { out += ", " }
                v.write(&out)
            }
            out += "]"
        case .object(let kv):
            out += "{"
            for (i, (k, v)) in kv.enumerated() {
                if i > 0 { out += ", " }
                JSON.quote(k, &out)
                out += ": "
                v.write(&out)
            }
            out += "}"
        }
    }

    private static func quote(_ s: String, _ out: inout String) {
        out += "\""
        for u in s.unicodeScalars {
            switch u {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            default:
                if u.value < 0x20 { out += String(format: "\\u%04x", u.value) } else { out.unicodeScalars.append(u) }
            }
        }
        out += "\""
    }

    private struct Parser {
        let bytes: [UInt8]
        var i = 0

        func fail(_ why: String) -> Error {
            NSError(domain: "JSON", code: 1, userInfo: [NSLocalizedDescriptionKey: "Bad JSON at \(i): \(why)"])
        }

        mutating func space() {
            while i < bytes.count, [0x20, 0x0A, 0x0D, 0x09].contains(bytes[i]) { i += 1 }
        }

        mutating func word(_ w: String) -> Bool {
            let b = Array(w.utf8)
            guard i + b.count <= bytes.count, Array(bytes[i..<i + b.count]) == b else { return false }
            i += b.count
            return true
        }

        mutating func value() throws -> JSON {
            guard i < bytes.count else { throw fail("ended early") }
            switch bytes[i] {
            case UInt8(ascii: "{"):
                i += 1
                var kv: [(String, JSON)] = []
                space()
                if i < bytes.count, bytes[i] == UInt8(ascii: "}") { i += 1; return .object(kv) }
                while true {
                    space()
                    guard i < bytes.count, bytes[i] == UInt8(ascii: "\"") else { throw fail("expected a key") }
                    let k = try string()
                    space()
                    guard i < bytes.count, bytes[i] == UInt8(ascii: ":") else { throw fail("expected :") }
                    i += 1
                    space()
                    kv.append((k, try value()))
                    space()
                    guard i < bytes.count else { throw fail("ended early") }
                    if bytes[i] == UInt8(ascii: ",") { i += 1; continue }
                    if bytes[i] == UInt8(ascii: "}") { i += 1; return .object(kv) }
                    throw fail("expected , or }")
                }
            case UInt8(ascii: "["):
                i += 1
                var a: [JSON] = []
                space()
                if i < bytes.count, bytes[i] == UInt8(ascii: "]") { i += 1; return .array(a) }
                while true {
                    space()
                    a.append(try value())
                    space()
                    guard i < bytes.count else { throw fail("ended early") }
                    if bytes[i] == UInt8(ascii: ",") { i += 1; continue }
                    if bytes[i] == UInt8(ascii: "]") { i += 1; return .array(a) }
                    throw fail("expected , or ]")
                }
            case UInt8(ascii: "\""):
                return .string(try string())
            default:
                if word("null") { return .null }
                if word("true") { return .bool(true) }
                if word("false") { return .bool(false) }
                for w in ["NaN", "Infinity", "-Infinity"] where word(w) { return .number(w) }   // Python writes these
                let start = i
                while i < bytes.count, "+-0123456789.eE".utf8.contains(bytes[i]) { i += 1 }
                guard i > start, let n = String(bytes: bytes[start..<i], encoding: .ascii), Double(n) != nil else {
                    throw fail("unexpected character")
                }
                return .number(n)
            }
        }

        mutating func string() throws -> String {
            i += 1   // opening quote
            var raw: [UInt8] = []
            while true {
                guard i < bytes.count else { throw fail("unterminated string") }
                let c = bytes[i]
                i += 1
                if c == UInt8(ascii: "\"") { break }
                guard c == UInt8(ascii: "\\") else { raw.append(c); continue }
                guard i < bytes.count else { throw fail("bad escape") }
                let e = bytes[i]
                i += 1
                switch e {
                case UInt8(ascii: "n"): raw.append(0x0A)
                case UInt8(ascii: "t"): raw.append(0x09)
                case UInt8(ascii: "r"): raw.append(0x0D)
                case UInt8(ascii: "b"): raw.append(0x08)
                case UInt8(ascii: "f"): raw.append(0x0C)
                case UInt8(ascii: "u"):
                    var u = try hex4()
                    if (0xD800..<0xDC00).contains(u), word("\\u") {   // a surrogate pair
                        let lo = try hex4()
                        u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00)
                    }
                    raw.append(contentsOf: Array(String(UnicodeScalar(u).map(Character.init) ?? "\u{FFFD}").utf8))
                default: raw.append(e)   // \" \\ \/
                }
            }
            guard let s = String(bytes: raw, encoding: .utf8) else { throw fail("not UTF-8") }
            return s
        }

        mutating func hex4() throws -> UInt32 {
            guard i + 4 <= bytes.count, let s = String(bytes: bytes[i..<i + 4], encoding: .ascii),
                  let v = UInt32(s, radix: 16) else { throw fail("bad \\u escape") }
            i += 4
            return v
        }
    }
}
