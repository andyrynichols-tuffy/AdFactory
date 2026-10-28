import Foundation

/// One Ad Factory shoot (a "project" on the phone). Mirrors adcut/cameraapi.py.
struct Project: Codable, Identifiable, Hashable {
    var sid: String
    var title: String
    var created: Double
    var stage: String          // film / precut / edit / post / posted
    var product: String?
    var productName: String?
    var tags: [String]
    var due: String?
    var lines: [String]        // the script, one teleprompter line each
    var clips: Int             // videos Ad Factory already has for it
    var carousel: Bool?        // a planned flat-lay carousel: photos, not takes (CarouselView)
    var outfits: [Int]?        // carousel: which outfit numbers already have a photo in Ad Factory

    var id: String { sid }
}

struct Product: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var brand: String?
}

struct LibraryScript: Codable, Identifiable, Hashable {
    var id: String
    var title: String
    var text: String
    var product: String?
    var tags: [String]
}

struct Tag: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var group: String          // Format / Hook / Style / Tone
}

struct Account: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var handle: String?
}

/// Everything GET /api/camera/projects sends.
struct Catalog: Codable {
    var projects: [Project]
    var products: [Product]
    var scripts: [LibraryScript]
    var tags: [Tag]
    var accounts: [Account]
    var zones: [String: [Double]]   // TikTok's UI as boxes [x0, y0, x1, y1], fractions of the frame
    var safe: [Double]

    static func decode(_ data: Data) throws -> Catalog {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(Catalog.self, from: data)
    }

    /// adcut/layout.py, for before the first sync.
    static let defaultZones: [String: [Double]] = [
        "top tabs": [0.0, 0.0, 1.0, 0.075],
        "like / comment / share": [0.835, 0.40, 1.0, 0.87],
        "caption + username": [0.0, 0.80, 0.835, 1.0],
        "orange cart tag": [0.03, 0.745, 0.62, 0.795],
    ]
    static let defaultSafe: [Double] = [0.04, 0.085, 0.82, 0.735]
}

/// A video Ad Factory already has for a project (GET /api/camera/projects/<sid>).
struct SourceClip: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var status: String         // ready / queued / error…
    var duration: Double
    var batch: Int
    var thumb: String?         // /api/thumb/… once it's processed
}

/// The project page: its clips in Ad Factory and how far the edit is.
struct ProjectDetail: Codable {
    var stage: String
    var lines: [String]
    var sources: [SourceClip]
    var videos: Int            // videos cut from the takes so far
    var saved: Int
}

/// POST /api/camera/projects (the same fields as Ad Factory's "＋ New video").
struct NewProject: Encodable {
    var title: String
    var product: String?
    var script: String?
    var scriptText: String
    var tags: [String]
    var account: String?
}

/// A take filmed on this phone.
struct Clip: Codable, Identifiable, Equatable {
    var id = UUID()
    var project: String        // shoot id
    var projectTitle: String
    var file: String           // in the app's Clips folder; also its name in OneDrive
    var created = Date()
    var seconds: Double = 0
    var bytes: Int64 = 0
    var line: Int?             // teleprompter line on screen when it started (0-based)
    var inPhotos = false
    var uploaded = false
    var error: String?
    var silent: Bool?          // true = no sound got recorded (AudioCheck); nil = not checked
}

enum Stage {
    static func label(_ s: String) -> String {
        switch s {
        case "film": return String(localized: "To film")
        case "precut": return String(localized: "Pre-cutting")
        case "edit": return String(localized: "To edit")
        case "post": return String(localized: "To post")
        case "posted": return String(localized: "Posted")
        default: return s
        }
    }
}
