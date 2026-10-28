import SwiftUI
import WebKit

/// A project's page: a big Film button, Edit videos once Ad Factory has cut videos (the phone
/// editor; Ad Factory's own Review page is a tap below it), and thumbnails of every clip so far (filmed on this phone, and already in Ad Factory).
struct ProjectView: View {
    let project: Project
    var film: () -> Void
    @EnvironmentObject private var clips: ClipStore
    @State private var detail: ProjectDetail?
    @State private var problem: String?
    @State private var showEditor = false
    @State private var showReview = false
    @State private var showScript = false
    @State private var deleting: ClipName?

    private let grid = Array(repeating: GridItem(.flexible(), spacing: 6), count: 3)
    private var stage: String { detail?.stage ?? project.stage }
    private var lines: [String] { detail?.lines ?? project.lines }
    private var editing: Bool { ["edit", "post", "posted"].contains(stage) && (detail?.videos ?? 1) > 0 }
    private var mine: [Clip] { clips.clips.filter { $0.project == project.sid && $0.archived != true } }

    // Archive / delete work by file name, so a clip in Ad Factory and the take it came from on
    // this phone move together (Ad Factory keeps archived and deleted clips out of its videos).
    private var factory: [SourceClip] {
        (detail?.sources ?? []).filter { !clips.isHidden(project: project.sid, name: $0.name) }
    }
    private var shelfPhone: [Clip] { clips.clips.filter { $0.project == project.sid && $0.archived == true } }
    private var shelfFactory: [SourceClip] {
        let shown = Set(shelfPhone.map { ClipStore.fileKey($0.file) })
        return factory.filter { isOff($0) && !shown.contains(ClipStore.fileKey($0.name)) }
    }

    private func phoneClip(named name: String) -> Clip? {
        clips.clips.first { $0.project == project.sid && ClipStore.fileKey($0.file) == ClipStore.fileKey(name) }
    }

    private func isOff(_ s: SourceClip) -> Bool {
        if let pending = clips.pendingOff(project: project.sid, name: s.name) { return pending }
        if phoneClip(named: s.name)?.archived == true { return true }
        return s.off ?? false
    }

    private func archive(_ name: String, _ on: Bool) {
        if let c = phoneClip(named: name) {
            clips.setArchived(c.id, on)
        } else {
            clips.tell(project: project.sid, name: name, off: on)
        }
    }

    private func delete(_ name: String) {
        if let c = phoneClip(named: name) {
            clips.delete(c.id)   // also tells Ad Factory and hides its copy here
        } else {
            clips.tell(project: project.sid, name: name, off: true)
            clips.hide(project: project.sid, name: name)
        }
    }

    @ViewBuilder
    private func clipMenu(_ name: String, archived: Bool) -> some View {
        if archived {
            Button { withAnimation { archive(name, false) } } label: { Label("Unarchive", systemImage: "tray.and.arrow.up") }
        } else {
            Button { withAnimation { archive(name, true) } } label: { Label("Archive", systemImage: "archivebox") }
        }
        Button(role: .destructive) { deleting = ClipName(name: name) } label: { Label("Delete", systemImage: "trash") }
    }

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
                            Label("Edit videos", systemImage: "scissors").font(.headline)
                            if let d = detail {
                                Text("\(d.videos) videos cut · \(d.saved) saved").font(.caption).opacity(0.75)
                            }
                        }
                        .frame(maxWidth: .infinity, minHeight: 58)
                        .background(Color.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
                    }
                    .foregroundStyle(.primary)
                    Button { showReview = true } label: {
                        Label("Review videos in Ad Factory", systemImage: "play.rectangle.on.rectangle")
                            .font(.subheadline)
                            .frame(maxWidth: .infinity)
                    }
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
                let live = factory.filter { !isOff($0) }
                if !mine.isEmpty {
                    Text("Filmed on this phone").font(.headline).padding(.top, 4)
                    LazyVGrid(columns: grid, spacing: 6) {
                        ForEach(mine) { c in
                            localTile(c).contextMenu { clipMenu(c.file, archived: false) }
                        }
                    }
                }
                if !live.isEmpty {
                    Text("In Ad Factory").font(.headline).padding(.top, 4)
                    LazyVGrid(columns: grid, spacing: 6) {
                        ForEach(live) { s in
                            remoteTile(s).contextMenu { clipMenu(s.name, archived: false) }
                        }
                    }
                }
                if !mine.isEmpty || !live.isEmpty {
                    Text("Press and hold a clip to archive or delete it.").font(.caption).foregroundStyle(.secondary)
                }
                if !shelfPhone.isEmpty || !shelfFactory.isEmpty {
                    Text("Archived").font(.headline).padding(.top, 4)
                    LazyVGrid(columns: grid, spacing: 6) {
                        ForEach(shelfPhone) { c in
                            localTile(c).opacity(0.45).contextMenu { clipMenu(c.file, archived: true) }
                        }
                        ForEach(shelfFactory) { s in
                            remoteTile(s).opacity(0.45).contextMenu { clipMenu(s.name, archived: true) }
                        }
                    }
                    Text("Kept out of Ad Factory's videos. Press and hold one to bring it back or delete it.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if mine.isEmpty && factory.isEmpty && shelfPhone.isEmpty {
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
        .confirmationDialog(Text("Delete this clip?"),
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                            titleVisibility: .visible, presenting: deleting) { ref in
            Button("Delete", role: .destructive) { withAnimation { delete(ref.name) } }
        } message: { ref in
            if let c = phoneClip(named: ref.name), !c.uploaded {
                Text("It's removed from this phone and won't be sent. A copy already saved in Photos (Ad Studio album) stays there.")
            } else {
                Text("It's removed from this project and kept out of Ad Factory's videos. The footage itself stays in Ad Factory and in Photos.")
            }
        }
        .navigationDestination(isPresented: $showEditor) {
            EditorView(project: project)
        }
        .sheet(isPresented: $showReview) {
            NavigationStack {
                AdFactoryPage(path: "/#review/\(project.sid)") { showReview = false }
                    .ignoresSafeArea(edges: .bottom)
                    .navigationTitle("Ad Factory")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { showReview = false }
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
            let product = Self.web(detail?.productLink ?? project.productLink)
            let reference = Self.web(detail?.referenceUrl ?? project.referenceUrl)
            if product != nil || reference != nil {
                HStack(spacing: 8) {
                    if let product { linkButton("Product page", "cart", product) }
                    if let reference { linkButton("Video to replicate", "play.rectangle", reference) }
                }
                .padding(.top, 6)
            }
        }
    }

    /// Opens in TikTok (or Safari); hold for Copy link.
    private func linkButton(_ title: LocalizedStringKey, _ icon: String, _ url: URL) -> some View {
        Link(destination: url) {
            Label(title, systemImage: icon)
                .font(.subheadline.bold())
                .lineLimit(1)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Color.white.opacity(0.12), in: Capsule())
        }
        .contextMenu {
            Button { UIPasteboard.general.url = url } label: { Label("Copy link", systemImage: "doc.on.doc") }
        }
    }

    static func web(_ s: String?) -> URL? {
        guard let s = s?.trimmingCharacters(in: .whitespacesAndNewlines), let u = URL(string: s),
              ["http", "https"].contains(u.scheme?.lowercased() ?? "") else { return nil }
        return u
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

struct ClipName: Identifiable {
    var name: String
    var id: String { name }
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
/// It stays on that one screen: the page's own ← (to Ad Factory's home) and Review/Edit switch
/// (the desktop editor) are hidden, since Done closes it; if it leaves anyway, `left` runs.
struct AdFactoryPage: UIViewRepresentable {
    let path: String
    var left: () -> Void = {}

    func makeCoordinator() -> Coordinator { Coordinator(left: left) }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        let left: () -> Void
        init(left: @escaping () -> Void) { self.left = left }
        func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
            DispatchQueue.main.async(execute: left)
        }
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let stay = """
        (function () {
          var css = document.createElement('style');
          css.textContent = '#backBtn, #modeSeg { display: none !important; }';
          document.documentElement.appendChild(css);
          var check = function () {
            if (!location.hash.startsWith('#review/')) window.webkit.messageHandlers.left.postMessage(location.hash);
          };
          var replace = history.replaceState;
          history.replaceState = function () { replace.apply(history, arguments); check(); };
          window.addEventListener('hashchange', check);
        })();
        """
        config.userContentController.addUserScript(WKUserScript(source: stay, injectionTime: .atDocumentStart,
                                                                forMainFrameOnly: true))
        config.userContentController.add(context.coordinator, name: "left")
        let web = WKWebView(frame: .zero, configuration: config)
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
