import Foundation
import Photos

/// Every take filmed on this phone: saved to Photos ("Ad Studio" album) and uploaded into
/// its project's OneDrive inbox folder through Ad Factory (PUT /api/inbox/upload?shoot=…).
/// Uploads run in a background URLSession, so they keep going with the phone locked or the
/// app closed. The app's own copy is removed once a take is both in Photos and uploaded.
final class ClipStore: NSObject, ObservableObject, URLSessionDataDelegate {
    static let shared = ClipStore()

    @Published private(set) var clips: [Clip] = []
    @Published private(set) var progress: [UUID: Double] = [:]   // uploading right now
    var backgroundDone: (() -> Void)?

    static let folder: URL = {
        let d = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Clips", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }()

    private let ledger = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("clips.json")
    private var retryTimer: Timer?

    private lazy var session: URLSession = {
        let c = URLSessionConfiguration.background(withIdentifier: "adcamera.uploads")
        c.sessionSendsLaunchEvents = true
        c.isDiscretionary = false
        c.httpShouldSetCookies = false
        c.httpCookieAcceptPolicy = .never
        c.timeoutIntervalForResource = 3 * 24 * 3600
        return URLSession(configuration: c, delegate: self, delegateQueue: .main)
    }()

    override init() {
        super.init()
        if let d = try? Data(contentsOf: ledger), let c = try? JSONDecoder().decode([Clip].self, from: d) {
            clips = c
        }
        session.getAllTasks { tasks in  // uploads that kept going while the app was closed
            DispatchQueue.main.async {
                for t in tasks {
                    if let id = UUID(uuidString: t.taskDescription ?? "") { self.progress[id] = 0 }
                }
                self.retryWaiting()
            }
        }
    }

    // MARK: - takes

    static func newFile(for p: Project) -> URL {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH.mm.ss"
        let name = String(p.title.filter { !"<>:\"/\\|?*+&#%=".contains($0) }.prefix(60))
            .trimmingCharacters(in: .whitespaces)
        return folder.appendingPathComponent("\(name.isEmpty ? "Take" : name) \(f.string(from: Date())).mov")
    }

    func add(file: URL, project: Project, seconds: Double, line: Int?) {
        let size = (try? FileManager.default.attributesOfItem(atPath: file.path)[.size] as? NSNumber)?.int64Value ?? 0
        let clip = Clip(project: project.sid, projectTitle: project.title, file: file.lastPathComponent,
                        seconds: seconds, bytes: size, line: line)
        clips.insert(clip, at: 0)
        save()
        savePhoto(clip.id)
        upload(clip.id)
    }

    func count(for project: String) -> Int {
        clips.filter { $0.project == project }.count
    }

    var waiting: Int { clips.filter { !$0.uploaded }.count }
    var sending: Int { progress.count }

    /// Forget takes that are done (in Photos and uploaded). Their videos stay in Photos and OneDrive.
    func clearFinished() {
        clips.removeAll { $0.uploaded && $0.inPhotos }
        save()
    }

    func retryWaiting() {
        for c in clips {
            if !c.inPhotos { savePhoto(c.id) }
            if !c.uploaded { upload(c.id) }
        }
    }

    // MARK: - Photos

    private var savingPhotos: Set<UUID> = []

    private func savePhoto(_ id: UUID) {
        guard let c = clip(id), !c.inPhotos, !savingPhotos.contains(id) else { return }
        let url = Self.folder.appendingPathComponent(c.file)
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        savingPhotos.insert(id)
        Task {
            let problem: String?
            do {
                try await PhotoAlbum.save(url)
                problem = nil
            } catch {
                problem = error.localizedDescription
            }
            await MainActor.run {
                self.savingPhotos.remove(id)
                self.update(id) { c in
                    if let problem { c.error = problem } else { c.inPhotos = true }
                }
                self.cleanUp(id)
            }
        }
    }

    // MARK: - uploads

    private func upload(_ id: UUID) {
        guard var c = clip(id), !c.uploaded, progress[id] == nil else { return }
        let url = Self.folder.appendingPathComponent(c.file)
        guard FileManager.default.fileExists(atPath: url.path) else {
            update(id) { $0.error = String(localized: "The video file is missing on this phone.") }
            return
        }
        guard Server.token != nil else {
            update(id) { $0.error = String(localized: "Waiting: sign in to Ad Factory in Settings.") }
            return
        }
        if c.bytes == 0 {
            c.bytes = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0
            let b = c.bytes
            update(id) { $0.bytes = b }
        }
        do {
            // one request for the whole file (Tailscale has no size cap); a retry starts over
            var r = try Server.request("api/inbox/upload", query: [
                ("name", c.file), ("offset", "0"), ("total", String(c.bytes)), ("shoot", c.project),
            ], method: "PUT")
            r.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            r.timeoutInterval = 120
            r.allowsCellularAccess = UserDefaults.standard.bool(forKey: "cellular")
            let task = session.uploadTask(with: r, fromFile: url)
            task.taskDescription = id.uuidString
            progress[id] = 0
            update(id) { $0.error = nil }
            task.resume()
        } catch {
            update(id) { $0.error = error.localizedDescription }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        guard let id = UUID(uuidString: task.taskDescription ?? ""), totalBytesExpectedToSend > 0 else { return }
        progress[id] = Double(totalBytesSent) / Double(totalBytesExpectedToSend)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let id = UUID(uuidString: task.taskDescription ?? "") else { return }
        progress[id] = nil
        let code = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        if error == nil && code == 200 {
            update(id) { $0.uploaded = true; $0.error = nil }
            cleanUp(id)
            return
        }
        let why: String
        if let error {
            why = error.localizedDescription
        } else if code == 401 {
            why = String(localized: "Waiting: sign in to Ad Factory in Settings.")
        } else if code == 404 {
            why = String(localized: "This project isn't in Ad Factory anymore.")
        } else {
            why = String(localized: "Ad Factory answered \(code).")
        }
        update(id) { $0.error = why }
        scheduleRetry()
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async {
            self.backgroundDone?()
            self.backgroundDone = nil
        }
    }

    private func scheduleRetry() {
        guard retryTimer == nil else { return }
        retryTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: false) { [weak self] _ in
            self?.retryTimer = nil
            self?.retryWaiting()
        }
    }

    // MARK: - bookkeeping

    private func clip(_ id: UUID) -> Clip? { clips.first { $0.id == id } }

    private func update(_ id: UUID, _ change: (inout Clip) -> Void) {
        guard let i = clips.firstIndex(where: { $0.id == id }) else { return }
        change(&clips[i])
        save()
    }

    /// The app's copy goes once the take is safe in both places.
    private func cleanUp(_ id: UUID) {
        guard let c = clip(id), c.uploaded, c.inPhotos else { return }
        try? FileManager.default.removeItem(at: Self.folder.appendingPathComponent(c.file))
    }

    private func save() {
        if let d = try? JSONEncoder().encode(clips) { try? d.write(to: ledger, options: .atomic) }
    }
}

/// The "Ad Studio" album in Photos.
enum PhotoAlbum {
    static let name = "Ad Studio"

    enum Problem: LocalizedError {
        case denied
        var errorDescription: String? {
            String(localized: "Allow Photos for Ad Camera in the iPhone's Settings to save takes to the album.")
        }
    }

    static func save(_ file: URL) async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .readWrite)
        guard status == .authorized || status == .limited else { throw Problem.denied }
        let album = try await albumOrMake()
        try await PHPhotoLibrary.shared().performChanges {
            let req = PHAssetCreationRequest.forAsset()
            req.addResource(with: .video, fileURL: file, options: nil)
            if let album, let placeholder = req.placeholderForCreatedAsset,
               let add = PHAssetCollectionChangeRequest(for: album) {
                add.addAssets([placeholder] as NSArray)
            }
        }
    }

    private final class Box { var id: String? }

    private static func albumOrMake() async throws -> PHAssetCollection? {
        if let id = UserDefaults.standard.string(forKey: "albumID"),
           let a = PHAssetCollection.fetchAssetCollections(withLocalIdentifiers: [id], options: nil).firstObject {
            return a
        }
        let opts = PHFetchOptions()
        opts.predicate = NSPredicate(format: "title = %@", name)
        if let a = PHAssetCollection.fetchAssetCollections(with: .album, subtype: .albumRegular, options: opts).firstObject {
            UserDefaults.standard.set(a.localIdentifier, forKey: "albumID")
            return a
        }
        let box = Box()
        try await PHPhotoLibrary.shared().performChanges {
            box.id = PHAssetCollectionChangeRequest.creationRequestForAssetCollection(withTitle: name)
                .placeholderForCreatedAssetCollection.localIdentifier
        }
        guard let id = box.id else { return nil }
        UserDefaults.standard.set(id, forKey: "albumID")
        return PHAssetCollection.fetchAssetCollections(withLocalIdentifiers: [id], options: nil).firstObject
    }
}
