import SwiftUI
import WebKit

/// A project's page: a big Film button, Continue editing once Ad Factory has cut videos,
/// and thumbnails of every clip so far (filmed on this phone, and already in Ad Factory).
struct ProjectView: View {
    let project: Project
    var film: () -> Void
    @EnvironmentObject private var clips: ClipStore
    @State private var detail: ProjectDetail?
    @State private var problem: String?
    @State private var showEditor = false
    @State private var showScript = false

    private let grid = Array(repeating: GridItem(.flexible(), spacing: 6), count: 3)
    private var stage: String { detail?.stage ?? project.stage }
    private var lines: [String] { detail?.lines ?? project.lines }
    private var editing: Bool { ["edit", "post", "posted"].contains(stage) && (detail?.videos ?? 1) > 0 }
    private var mine: [Clip] { clips.clips.filter { $0.project == project.sid } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                Button(action: film) {
                    Label("Film", systemImage: "video.fill")
                        .font(.title2.bold())
                        .frame(maxWidth: .infinity, minHeight: 74)
                        .background(Color.accentColor, in: RoundedRectangle(cornerRadius: 16))
                        .foregroundStyle(.white)
                }
                if editing {
                    Button { showEditor = true } label: {
                        VStack(spacing: 2) {
                            Label("Continue editing", systemImage: "scissors").font(.headline)
                            if let d = detail {
                                Text("\(d.videos) videos cut · \(d.saved) saved").font(.caption).opacity(0.75)
                            }
                        }
                        .frame(maxWidth: .infinity, minHeight: 58)
                        .background(Color.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
                    }
                    .foregroundStyle(.primary)
                } else if stage == "precut" {
                    Label("Ad Factory is pre-cutting the clips…", systemImage: "hourglass")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                if !lines.isEmpty {
                    DisclosureGroup(isExpanded: $showScript) {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(Array(lines.enumerated()), id: \.offset) { i, l in
                                Text(verbatim: "\(i + 1). \(l)").font(.callout)
                            }
                        }
                        .padding(.top, 6)
                    } label: {
                        Text("Script (\(lines.count) lines)").font(.headline)
                    }
                }
                if !mine.isEmpty {
                    Text("Filmed on this phone").font(.headline).padding(.top, 4)
                    LazyVGrid(columns: grid, spacing: 6) {
                        ForEach(mine) { c in localTile(c) }
                    }
                }
                if let sources = detail?.sources, !sources.isEmpty {
                    Text("In Ad Factory").font(.headline).padding(.top, 4)
                    LazyVGrid(columns: grid, spacing: 6) {
                        ForEach(sources) { s in remoteTile(s) }
                    }
                }
                if mine.isEmpty && (detail?.sources.isEmpty ?? true) {
                    Text("No clips yet. Tap Film to start.").foregroundStyle(.secondary).padding(.top, 8)
                }
                if let problem {
                    Text(verbatim: problem).font(.footnote).foregroundStyle(.orange)
                }
            }
            .padding(16)
        }
        .navigationTitle(project.title)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await load() }
        .task {   // keep up with Ad Factory picking up and cutting new clips
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(nanoseconds: 15_000_000_000)
            }
        }
        .sheet(isPresented: $showEditor) {
            NavigationStack {
                AdFactoryPage(path: "/#review/\(project.sid)")
                    .ignoresSafeArea(edges: .bottom)
                    .navigationTitle("Ad Factory")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { showEditor = false }
                        }
                    }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let name = project.productName, !name.isEmpty, name != project.title {
                Text(verbatim: name).font(.subheadline).foregroundStyle(.secondary)
            }
            if !project.tags.isEmpty {
                Text(verbatim: project.tags.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func load() async {
        do {
            let d = try await API.project(project.sid)
            await MainActor.run {
                detail = d
                problem = nil
            }
        } catch {
            await MainActor.run { problem = error.localizedDescription }
        }
    }

    private func localTile(_ c: Clip) -> some View {
        let _ = clips.thumbsMade   // redraw once the thumbnail is ready
        return tile(image: ClipStore.thumb(c.id), seconds: c.seconds) {
            if c.silent == true {
                Image(systemName: "speaker.slash.fill").foregroundStyle(.red)
            } else if c.uploaded {
                Image(systemName: "checkmark.icloud.fill").foregroundStyle(.green)
            } else if let p = clips.progress[c.id] {
                Text(verbatim: "\(Int(p * 100))%").font(.caption2.bold())
            } else {
                Image(systemName: "icloud.and.arrow.up")
            }
        }
    }

    private func remoteTile(_ s: SourceClip) -> some View {
        tile(path: s.thumb, seconds: s.duration) {
            if s.status == "error" {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            } else if s.status != "ready" {
                ProgressView().controlSize(.mini)
            }
        }
    }

    private func tile<Badge: View>(image: UIImage? = nil, path: String? = nil, seconds: Double,
                                   @ViewBuilder badge: () -> Badge) -> some View {
        Color.white.opacity(0.08)
            .aspectRatio(9 / 16, contentMode: .fit)
            .overlay {
                if let image {
                    Image(uiImage: image).resizable().scaledToFill()
                } else if let path {
                    RemoteThumb(path: path)
                } else {
                    Image(systemName: "video").foregroundStyle(.secondary)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(alignment: .bottomLeading) {
                Text(verbatim: ClipRow.duration(seconds))
                    .font(.caption2.bold())
                    .padding(.horizontal, 5).padding(.vertical, 2)
                    .background(.black.opacity(0.55), in: Capsule())
                    .padding(5)
            }
            .overlay(alignment: .topTrailing) {
                badge()
                    .font(.caption)
                    .padding(5)
                    .background(.black.opacity(0.45), in: Circle())
                    .padding(4)
            }
    }
}

struct RemoteThumb: View {
    let path: String
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                ProgressView()
            }
        }
        .task(id: path) { image = await API.image(path) }
    }
}

/// Ad Factory's own page for the project (its phone-friendly Review screen), signed in with
/// the app's cookie. The mobile single-video editor will take this button over.
struct AdFactoryPage: UIViewRepresentable {
    let path: String

    func makeUIView(context: Context) -> WKWebView {
        let web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        guard let base = Server.baseURL, let url = URL(string: path, relativeTo: base) else { return web }
        if let token = Server.token, let host = base.host,
           let cookie = HTTPCookie(properties: [.domain: host, .path: "/", .name: Server.cookieName,
                                                .value: token, .secure: "TRUE"]) {
            web.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) {
                web.load(URLRequest(url: url))
            }
        } else {
            web.load(URLRequest(url: url))
        }
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {}
}
