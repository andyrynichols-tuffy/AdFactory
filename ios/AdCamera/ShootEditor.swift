import AVFoundation
import Foundation
import Photos

/// One take of a shoot, read from its JSON (adcut/store.py TAKE_FIELDS).
struct Take: Identifiable {
    let j: JSON

    var id: String { j["id"]?.string ?? "" }
    var line: String? { j["line"]?.string }
    var src: String { j["src"]?.string ?? "" }
    var start: Double { j["in"]?.double ?? 0 }
    var end: Double { j["out"]?.double ?? 0 }
    var status: String { j["status"]?.string ?? "good" }
    var usable: Bool { j["usable"]?.bool ?? true }
    var order: Double { j["order"]?.double ?? 0 }
    var speed: Double? { j["speed"]?.double.flatMap { $0 > 0 ? $0 : nil } }
    var captionsEdited: Bool { j["words_orig"] != nil }

    /// [[text, start, end]] in source seconds; a malformed entry keeps its place, empty.
    var words: [(String, Double, Double)] {
        (j["words"]?.array ?? []).map { w in
            let a = w.array ?? []
            return (a.first?.string ?? "", a.count > 1 ? a[1].double ?? 0 : 0, a.count > 2 ? a[2].double ?? 0 : 0)
        }
    }

    /// Cut-outs clipped to the take, merged and sorted (store.take_cuts).
    var cuts: [(Double, Double)] {
        let raw = (j["cuts"]?.array ?? []).compactMap { c -> (Double, Double)? in
            guard let a = c.array, a.count >= 2, let x = a[0].double, let y = a[1].double else { return nil }
            return (x, y)
        }
        var out: [(Double, Double)] = []
        for (a0, b0) in raw.sorted(by: { $0.0 < $1.0 }) {
            let a = max(a0, start), b = min(b0, end)
            if b - a < 0.02 { continue }
            if let last = out.last, a <= last.1 { out[out.count - 1].1 = max(last.1, b) } else { out.append((a, b)) }
        }
        return out
    }

    func inCut(_ x: Double) -> Bool { cuts.contains { x >= $0.0 && x < $0.1 } }

    /// The words its captions show: inside the trim and not cut out (app.js capWords).
    var captionWords: [(i: Int, w: (String, Double, Double))] {
        words.enumerated().compactMap { i, w in
            let m = (w.1 + w.2) / 2
            return m >= start && m <= end && !inCut(m) ? (i, w) : nil
        }
    }

    var captionText: String { captionWords.map(\.w.0).joined(separator: " ") }

    /// Seconds of footage it uses (cut-outs dropped), before any speed-up.
    var footage: Double { end - start - cuts.reduce(0) { $0 + $1.1 - $1.0 } }
}

struct ScriptLine: Identifiable {
    var id: String
    var text: String
}

/// A finished video: which takes make it (store.videos) and how its render stands (/review).
struct EditVideo: Identifiable {
    var n: Int
    var takes: [String]
    var skip: Bool
    var frozen: Bool           // saved or posted: its takes are locked
    var empty: Bool
    var duration = 0.0
    var rendered = false
    var fresh = false          // the render matches the edit
    var saved = false
    var posted = false
    var thumb: String?
    var safety: String?        // "ok" / "check" / "unsafe" (adcut/safety.py)

    var id: Int { n }
}

struct VideoPreview {
    var state: String          // ready / building / failed
    var url: String?
    var segs: [(take: String, off: Double, len: Double)]
    var error: String?
}

struct RenderJob {
    var id: String
    var state: String          // queued / running / done / error
    var msg: String
    var error: String?
}

/// The phone editor's copy of one Ad Factory shoot. Every change is a small function applied to
/// the shoot JSON (the same edits the desktop editor makes, app.js), then the whole shoot goes
/// back with PUT /api/shoots/<id>. If it changed on the computer meanwhile (409), the shoot is
/// reloaded and the waiting changes are applied again on top, so nobody's edit is lost.
@MainActor
final class ShootEditor: ObservableObject {
    let sid: String
    @Published private(set) var shoot: JSON = .null
    @Published private(set) var videos: [EditVideo] = []
    @Published private(set) var previews: [Int: VideoPreview] = [:]
    @Published private(set) var loaded = false
    @Published private(set) var saving = false
    @Published private(set) var job: RenderJob?
    @Published var problem: String?
    @Published var note: String?

    private var pending: [(inout JSON) -> Void] = []
    private var saveTask: Task<Void, Never>?
    private var again = false   // a save was asked for while one was going

    init(sid: String) { self.sid = sid }

    // MARK: reading the shoot

    var title: String { shoot["title"]?.string ?? sid }
    var lines: [ScriptLine] {
        (shoot["script"]?.array ?? []).compactMap { l in
            l["id"]?.string.map { ScriptLine(id: $0, text: l["text"]?.string ?? "") }
        }
    }
    var takes: [Take] { (shoot["takes"]?.array ?? []).map(Take.init) }
    func take(_ id: String) -> Take? { takes.first { $0.id == id } }
    func video(_ n: Int) -> EditVideo? { videos.first { $0.n == n } }

    /// The take a line uses in video n.
    func take(in n: Int, line: String) -> Take? {
        guard let v = video(n) else { return nil }
        let all = takes
        return v.takes.lazy.compactMap { id in all.first { $0.id == id } }.first { $0.line == line }
    }

    /// The video a take is in, if any.
    func videoOf(_ id: String) -> EditVideo? { videos.first { $0.takes.contains(id) } }

    /// The saved/posted video a take is locked into (store.locked_ids).
    func lockedIn(_ id: String) -> Int? { videos.first { $0.frozen && $0.takes.contains(id) }?.n }

    private func source(_ id: String) -> JSON? { shoot["sources"]?.array?.first { $0["id"]?.string == id } }
    func sourceKey(_ t: Take) -> String? { source(t.src)?["key"]?.string }
    func sourceLength(_ t: Take) -> Double? { source(t.src)?["duration"]?.double }

    func thumb(_ t: Take) -> String? {
        sourceKey(t).map { "/api/thumb/\($0)?t=\(String(format: "%.1f", ((t.start + t.end) * 5).rounded() / 10))" }
    }

    /// How fast a take plays: its own speed, else the video's speed times the auto pace (store.speed).
    func speed(_ t: Take) -> Double {
        if let s = t.speed { return s }
        let style = shoot["style"] ?? .null
        var sp = style["speed"]?.double ?? 1
        let pace = style["pace"] ?? .null
        if pace["auto"]?.bool == true {
            let spoken = t.footage
            let n = Double(t.captionWords.count)
            if n >= 3, spoken > 0.3 {
                let want = (pace["wps"]?.double ?? 5) / (n / spoken)
                sp *= min(pace["max"]?.double ?? 1.35, max(1, (want * 20).rounded() / 20))
            }
        }
        return (sp * 1000).rounded() / 1000
    }

    func autoSpeed(_ t: Take) -> Double {
        var j = t.j
        j["speed"] = .null
        return speed(Take(j: j))
    }

    // MARK: loading

    func load() async {
        do {
            let got = try await API.json("api/shoots/\(sid)")
            adopt(got)
            loaded = true
            problem = nil
            await refresh()
        } catch {
            problem = error.localizedDescription
        }
    }

    /// The shoot from GET (its _videos / _job / _sigs extras kept apart).
    private func adopt(_ got: JSON) {
        var s = got
        for k in s.keys where k.hasPrefix("_") { s[k] = nil }
        shoot = s
        setVideos(got["_videos"])
    }

    private func setVideos(_ vj: JSON?) {
        let old = Dictionary(uniqueKeysWithValues: videos.map { ($0.n, $0) })
        videos = (vj?["videos"]?.array ?? []).compactMap { v in
            guard let n = v["n"]?.int else { return nil }
            var e = EditVideo(n: n, takes: v["takes"]?.array?.compactMap(\.string) ?? [], skip: v["skip"]?.bool ?? false,
                              frozen: v["posted"]?.bool ?? false, empty: v["empty"]?.bool ?? false)
            if let o = old[n] {
                (e.duration, e.rendered, e.fresh, e.saved, e.posted, e.thumb, e.safety) =
                    (o.duration, o.rendered, o.fresh, o.saved, o.posted, o.thumb, o.safety)
            }
            return e
        }
    }

    /// Render state per video (the Review screen's list), and the previews.
    func refresh() async {
        if let r = try? await API.json("api/shoots/\(sid)/review") {
            for row in r["videos"]?.array ?? [] {
                guard let n = row["n"]?.int, let i = videos.firstIndex(where: { $0.n == n }) else { continue }
                videos[i].duration = row["duration"]?.double ?? 0
                videos[i].rendered = row["rendered"]?.bool ?? false
                videos[i].fresh = row["fresh"]?.bool ?? false
                videos[i].saved = row["saved"]?.bool ?? false
                videos[i].posted = row["posted"]?.bool ?? false
                videos[i].thumb = row["thumb"]?.string
                videos[i].safety = row["safety"]?.string
            }
            if let j = r["job"], !j.isNull { job = Self.job(j) }
        }
        await refreshPreviews()
    }

    /// Asking also queues the stale previews to be rebuilt on the PC.
    func refreshPreviews() async {
        guard let p = try? await API.json("api/shoots/\(sid)/previews") else { return }
        var out: [Int: VideoPreview] = [:]
        for k in p.keys {
            guard let n = Int(k), let v = p[k] else { continue }
            let segs = (v["segs"]?.array ?? []).compactMap { s -> (take: String, off: Double, len: Double)? in
                guard let id = s["id"]?.string else { return nil }
                return (id, s["off"]?.double ?? 0, s["len"]?.double ?? 0)
            }
            out[n] = VideoPreview(state: v["state"]?.string ?? "building", url: v["url"]?.string, segs: segs,
                                  error: v["error"]?.string)
        }
        previews = out
    }

    // MARK: saving

    /// Apply a change now and save it after `delay` seconds (later changes in that time go too).
    func change(after delay: Double = 0.6, _ fn: @escaping (inout JSON) -> Void) {
        fn(&shoot)
        pending.append(fn)
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            if delay > 0 { try? await Task.sleep(nanoseconds: UInt64(delay * 1e9)) }
            guard !Task.isCancelled else { return }
            await self?.save()
        }
    }

    /// Save whatever is waiting, now.
    func flush() async {
        saveTask?.cancel()
        saveTask = nil
        if !pending.isEmpty { await save() }
    }

    private func save(retry: Bool = true) async {
        guard !saving else { again = true; return }
        guard !pending.isEmpty else { return }
        saving = true
        let sending = pending.count
        do {
            let r = try await API.json("api/shoots/\(sid)", method: "PUT", body: shoot)
            if let rev = r["rev"] { shoot["rev"] = rev }
            setVideos(r["_videos"])
            pending.removeFirst(min(sending, pending.count))
            problem = nil
            saving = false
            await refresh()
        } catch APIError.http(409, _) where retry {
            // changed on the computer: start from its version and redo the phone's changes
            saving = false
            if let fresh = try? await API.json("api/shoots/\(sid)") {
                adopt(fresh)
                for fn in pending { fn(&shoot) }
                note = String(localized: "This project changed on the computer, so the phone loaded that version and redid your changes on top.")
            }
            await save(retry: false)
            return
        } catch {
            saving = false
            problem = error.localizedDescription
        }
        if again {
            again = false
            await save()
        }
    }

    /// Reload after the PC changed the shoot itself (a render, saving a video…).
    private func reload() async {
        await flush()
        if let got = try? await API.json("api/shoots/\(sid)") { adopt(got) }
        await refresh()
    }

    // MARK: edits (the same as the desktop editor's, app.js)

    private static func edit(_ s: inout JSON, take id: String, _ fn: (inout JSON) -> Void) {
        guard var ts = s["takes"]?.array, let i = ts.firstIndex(where: { $0["id"]?.string == id }) else { return }
        fn(&ts[i])
        s["takes"] = .array(ts)
    }

    /// Mark a field as set by hand, so a re-match keeps it.
    private static func byHand(_ t: inout JSON, _ field: String, _ on: Bool = true) {
        var u = t["user"] ?? .object([])
        if case .object = u {} else { u = .object([]) }
        u[field] = on ? .bool(true) : nil
        t["user"] = u
    }

    /// Move the start or end, keeping at least 0.2 s (app.js setTrim).
    func trim(_ id: String, start: Double? = nil, end: Double? = nil) {
        guard lockedIn(id) == nil, let t = take(id) else { return }
        let length = sourceLength(t) ?? 1e9
        change { s in
            ShootEditor.edit(&s, take: id) { x in
                let tin = x["in"]?.double ?? 0, tout = x["out"]?.double ?? 0
                if let v = start {
                    x["in"] = .float((min(max(0, v), tout - 0.2) * 1000).rounded() / 1000)
                    ShootEditor.byHand(&x, "in")
                }
                if let v = end {
                    x["out"] = .float((max(min(length, v), tin + 0.2) * 1000).rounded() / 1000)
                    ShootEditor.byHand(&x, "out")
                }
            }
        }
    }

    /// New caption words. Each word keeps its timing when the count is the same; otherwise the
    /// new words are spread over the same stretch, weighted by length (app.js setCaptions).
    func setCaptions(_ id: String, _ text: String) {
        guard lockedIn(id) == nil else { return }
        change(after: 0) { s in
            ShootEditor.edit(&s, take: id) { x in
                let t = Take(j: x)
                let vis = t.captionWords
                let toks = text.split(whereSeparator: \.isWhitespace).map(String.init)
                let raw = x["words"]?.array ?? []
                if x["user"]?["words"]?.bool != true, x["words_orig"] == nil { x["words_orig"] = .array(raw) }
                let shown = Set(vis.map(\.i))
                let keep = raw.enumerated().filter { !shown.contains($0.offset) }.map(\.element)
                var new: [JSON] = []
                if toks.count == vis.count {
                    new = zip(toks, vis).map { tok, v in
                        let old = raw[v.i].array ?? []
                        return .array([.string(tok), old.count > 1 ? old[1] : .float(v.w.1), old.count > 2 ? old[2] : .float(v.w.2)])
                    }
                } else {
                    // seconds into the take, skipping its cut-outs, and back
                    func rel(_ x: Double) -> Double {
                        t.cuts.reduce(x - t.start) { r, c in r - (x >= c.1 ? c.1 - c.0 : x > c.0 ? x - c.0 : 0) }
                    }
                    func src(_ r: Double) -> Double {
                        var x = t.start + r
                        for c in t.cuts { if x >= c.0 { x += c.1 - c.0 } else { break } }
                        return min(x, t.end)
                    }
                    let a = vis.first?.w.1 ?? t.start + 0.1, b = vis.last?.w.2 ?? t.end - 0.1
                    let total = Double(max(1, toks.reduce(0) { $0 + $1.count + 1 }))
                    let span = rel(b) - rel(a)
                    var acc = 0.0
                    for tok in toks {
                        let r0 = rel(a) + span * acc / total
                        acc += Double(tok.count + 1)
                        let r1 = rel(a) + span * acc / total
                        new.append(.array([.string(tok), .float((src(r0) * 1000).rounded() / 1000),
                                           .float((src(max(r0, r1 - 0.02)) * 1000).rounded() / 1000)]))
                    }
                }
                let all = (keep + new).sorted {
                    ($0.array?.dropFirst().first?.double ?? 0) < ($1.array?.dropFirst().first?.double ?? 0)
                }
                x["words"] = .array(all)
                x["text"] = .string(all.compactMap { $0.array?.first?.string }.joined(separator: " "))
                ShootEditor.byHand(&x, "words")
                ShootEditor.byHand(&x, "text")
            }
        }
    }

    /// Back to the words as they were transcribed (app.js resetCaptions). Words set by hand
    /// before any original was kept have nothing to go back to, so they stay as they are.
    func resetCaptions(_ id: String) {
        guard lockedIn(id) == nil, take(id)?.captionsEdited == true else { return }
        change(after: 0) { s in
            ShootEditor.edit(&s, take: id) { x in
                guard let orig = x["words_orig"] else { return }
                x["words"] = orig
                x["text"] = .string((orig.array ?? []).compactMap { $0.array?.first?.string }.joined(separator: " "))
                x["words_orig"] = nil
                ShootEditor.byHand(&x, "words", false)
                ShootEditor.byHand(&x, "text", false)
            }
        }
    }

    /// nil = automatic (the video's speed and pace).
    func setSpeed(_ id: String, _ v: Double?) {
        guard lockedIn(id) == nil else { return }
        change(after: 0) { s in
            ShootEditor.edit(&s, take: id) { x in
                x["speed"] = v.map(JSON.float) ?? .null
                var u = x["user"] ?? .object([])
                if case .object = u {} else { u = .object([]) }
                u["speed"] = .bool(v != nil)
                x["user"] = u
            }
        }
    }

    /// Put a take in video v (app.js swapInto): a good or spare take trades places with the
    /// line's take there; a reject takes that place and the take that was there becomes a reject.
    @discardableResult
    func use(_ id: String, inVideo v: Int) -> String? {
        guard let t0 = take(id), let lineId = t0.line else { return nil }
        if let n = lockedIn(id) {
            return String(localized: "That take is locked in saved video \(n).")
        }
        guard let target = video(v), !target.frozen else {
            return String(localized: "Video \(v) is saved: its takes are locked.")
        }
        let occId = target.takes.first { take($0)?.line == lineId }
        let wasUsable = t0.usable
        change(after: 0) { s in
            guard var ts = s["takes"]?.array, let ti = ts.firstIndex(where: { $0["id"]?.string == id }) else { return }
            let mine = ts.indices.filter { ts[$0]["line"]?.string == lineId }
            var st = mine.filter { ts[$0]["usable"]?.bool ?? true }.sorted {
                let (a, b) = (Take(j: ts[$0]), Take(j: ts[$1]))
                return a.order != b.order ? a.order < b.order : a.start < b.start
            }
            let occ = occId.flatMap { o in st.first { ts[$0]["id"]?.string == o } }
            if ts[ti]["usable"]?.bool ?? true {   // trade places
                guard let from = st.firstIndex(of: ti) else { return }
                if let occ, let to = st.firstIndex(of: occ) { st.swapAt(from, to) } else { st.remove(at: from); st.append(ti) }
            } else {   // a reject comes in, the take that was there goes out
                ts[ti]["usable"] = .bool(true)
                ShootEditor.byHand(&ts[ti], "usable")
                if ["nopayoff", "flub", "incomplete", "paused"].contains(ts[ti]["status"]?.string ?? "") {
                    ts[ti]["flags"] = .array((ts[ti]["flags"]?.array ?? []) + [.string("used anyway")])
                }
                if let occ, let pos = st.firstIndex(of: occ) {
                    ts[occ]["usable"] = .bool(false)
                    ShootEditor.byHand(&ts[occ], "usable")
                    st[pos] = ti
                } else {
                    st.append(ti)
                }
            }
            for (k, i) in st.enumerated() {
                ts[i]["order"] = .int(k)
                ShootEditor.byHand(&ts[i], "order")
            }
            let rejects = mine.filter { ts[$0]["usable"]?.bool == false }.sorted {
                (ts[$0]["order"]?.double ?? 0) < (ts[$1]["order"]?.double ?? 0)
            }
            for (k, i) in rejects.enumerated() { ts[i]["order"] = .int(k) }
            s["takes"] = .array(ts)
        }
        return wasUsable
            ? String(localized: "Swapped: the take that was in this video moved to where this one was.")
            : String(localized: "Now in this video; the take that was here went to the rejects.")
    }

    /// Leave video n out of "get all ready" (shoot.skip).
    func setSkip(_ n: Int, _ on: Bool) {
        change(after: 0) { s in
            var ns = Set((s["skip"]?.array ?? []).compactMap(\.int))
            if on { ns.insert(n) } else { ns.remove(n) }
            s["skip"] = .array(ns.sorted().map(JSON.int))
        }
    }

    // MARK: on the PC

    /// Render video n on the PC, following its progress.
    func render(_ n: Int) async {
        await flush()
        do {
            let j = try await API.json("api/shoots/\(sid)/render", method: "POST",
                                       body: .object([("videos", .array([.int(n)]))]))
            job = Self.job(j)
            while let cur = job, cur.state == "queued" || cur.state == "running" {
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                job = Self.job(try await API.json("api/jobs/\(cur.id)"))
            }
            if let e = job?.error { problem = e }
            job = nil
        } catch {
            problem = error.localizedDescription
            job = nil
        }
        await reload()
    }

    private static func job(_ j: JSON) -> RenderJob? {
        guard let id = j["id"]?.string else { return nil }
        return RenderJob(id: id, state: j["state"]?.string ?? "queued", msg: j["msg"]?.string ?? "",
                         error: j["error"]?.string)
    }

    /// ☆ save (locks its takes) or unsave.
    func setSaved(_ n: Int, _ on: Bool) async {
        await flush()
        do {
            _ = try await API.json("api/shoots/\(sid)/saved", method: "POST",
                                   body: .object([("n", .int(n)), ("saved", .bool(on))]))
        } catch { problem = error.localizedDescription }
        await reload()
    }

    func setPosted(_ n: Int, _ on: Bool) async {
        await flush()
        do {
            _ = try await API.json("api/shoots/\(sid)/saved", method: "POST",
                                   body: .object([("n", .int(n)), ("posted", .bool(on))]))
        } catch { problem = error.localizedDescription }
        await reload()
    }

    /// The finished video into Photos (the camera roll, not the takes' album).
    func saveToPhotos(_ n: Int) async throws {
        var r = try Server.request("api/output/\(sid)/\(n)", query: [("dl", "1")])
        r.timeoutInterval = 300
        r.setValue(nil, forHTTPHeaderField: "Accept")
        let (tmp, resp) = try await URLSession.shared.download(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard code == 200 else { throw code == 401 ? APIError.signIn : APIError.http(code, "") }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(sid) - video \(n).mp4")
        try? FileManager.default.removeItem(at: file)
        try FileManager.default.moveItem(at: tmp, to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        guard await PHPhotoLibrary.requestAuthorization(for: .addOnly) == .authorized else {
            throw APIError.http(0, String(localized: "Allow Ad Camera to add to Photos in Settings."))
        }
        try await PHPhotoLibrary.shared().performChanges {
            PHAssetCreationRequest.creationRequestForAssetFromVideo(atFileURL: file)
        }
    }

    /// A video file on Ad Factory, played with the sign-in cookie.
    static func asset(_ path: String) -> AVURLAsset? {
        guard let base = Server.baseURL, let url = URL(string: path, relativeTo: base)?.absoluteURL else { return nil }
        var options: [String: Any] = [:]
        if let token = Server.token, let host = base.host,
           let c = HTTPCookie(properties: [.domain: host, .path: "/", .name: Server.cookieName, .value: token, .secure: "TRUE"]) {
            options[AVURLAssetHTTPCookiesKey] = [c]
        }
        return AVURLAsset(url: url, options: options)
    }
}
