import Foundation

/// The projects list from Ad Factory, kept on the phone so filming works with no signal.
final class AppModel: ObservableObject {
    @Published var catalog: Catalog?
    @Published var loading = false
    @Published var problem: String?
    @Published var offline = false          // showing the list from last time
    @Published var signedIn = Server.token != nil

    private let cacheFile = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("catalog.json")

    init() {
        if let d = try? Data(contentsOf: cacheFile) {
            catalog = try? Catalog.decode(d)
        }
    }

    var zones: [String: [Double]] { catalog?.zones ?? Catalog.defaultZones }
    var safe: [Double] { catalog?.safe ?? Catalog.defaultSafe }

    @MainActor
    func refresh() async {
        guard signedIn, !loading else { return }
        loading = true
        defer { loading = false }
        do {
            let data = try await API.catalog()
            catalog = try Catalog.decode(data)
            try? data.write(to: cacheFile)
            problem = nil
            offline = false
        } catch {
            if case APIError.signIn = error { signedIn = false }
            problem = error.localizedDescription
            offline = catalog != nil
        }
    }

    @MainActor
    func signIn(_ password: String) async throws {
        try await API.signIn(password: password)
        signedIn = true
        await refresh()
        ClipStore.shared.retryWaiting()
    }

    func signOut() {
        Server.token = nil
        signedIn = false
    }

    @MainActor
    func create(_ p: NewProject) async throws -> Project {
        let project = try await API.newProject(p)
        catalog?.projects.insert(project, at: 0)
        return project
    }
}
