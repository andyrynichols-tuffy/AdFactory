import AVKit
import SwiftUI

/// The phone editor for one shoot, a video at a time: watch it line by line, swap a line's take,
/// trim it, fix its captions or speed; skip the video, get it ready, save it to Photos, ☆ save it
/// or mark it posted. The bigger tools (pictures on lines, sounds, effects, caption styles,
/// cutting pauses out, voiceovers, the script) stay in Ad Factory on the computer.
struct EditorView: View {
    @StateObject private var ed: ShootEditor
    @StateObject private var player = PreviewPlayer()
    @State private var n = 1
    @State private var editing: LineRef?
    @State private var watching: FinalRef?
    @State private var busy = false
    @State private var toast: String?

    init(project: Project) {
        _ed = StateObject(wrappedValue: ShootEditor(sid: project.sid))
    }

    private var video: EditVideo? { ed.video(n) }
    private var preview: VideoPreview? { ed.previews[n] }
    private var shown: [EditVideo] { ed.videos.filter { !$0.empty } }

    var body: some View {
        Group {
            if ed.loaded {
                content
            } else if let p = ed.problem {
                ContentUnavailableView {
                    Label("Couldn't open the project", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(verbatim: p)
                } actions: {
                    Button("Try again") { Task { await ed.load() } }
                }
            } else {
                ProgressView()
            }
        }
        .navigationTitle(Text(verbatim: ed.loaded ? ed.title : ""))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if ed.saving { ProgressView() }
            }
        }
        .task {
            await ed.load()
            if video == nil || video?.empty == true, let first = shown.first { n = first.n }
        }
        .task(id: n) {   // keep asking until this video's preview is built on the PC
            while !Task.isCancelled {
                if ed.previews[n]?.state != "ready" { await ed.refreshPreviews() }
                try? await Task.sleep(nanoseconds: ed.previews[n]?.state == "ready" ? 8_000_000_000 : 2_000_000_000)
            }
        }
        .onChange(of: preview?.url) { player.show(preview?.state == "ready" ? preview?.url : nil) }
        .onChange(of: n) { player.show(preview?.state == "ready" ? preview?.url : nil, from: 0) }
        .onDisappear {
            player.stop()
            Task { await ed.flush() }
        }
        .sheet(item: $editing) { ref in
            LineEditor(ed: ed, video: ref.video, lineId: ref.line, number: ref.number)
        }
        .sheet(item: $watching) { ref in
            FinalPlayer(path: "/api/output/\(ed.sid)/\(ref.n)")
        }
        .alert(Text(verbatim: ed.note ?? ""), isPresented: Binding(get: { ed.note != nil }, set: { if !$0 { ed.note = nil } })) {
            Button("OK", role: .cancel) {}
        }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if shown.isEmpty {
                    Text("No videos yet: Ad Factory makes them once the takes are cut.")
                        .foregroundStyle(.secondary)
                } else {
                    picker
                    stage
                    status
                    linesList
                    actions
                }
                if let p = ed.problem {
                    Label { Text(verbatim: p) } icon: { Image(systemName: "exclamationmark.triangle") }
                        .foregroundStyle(.orange)
                        .font(.footnote)
                }
            }
            .padding()
        }
        .refreshable { await ed.load() }
        .overlay(alignment: .bottom) {
            if let toast {
                Text(verbatim: toast)
                    .font(.footnote.bold())
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(.black.opacity(0.8), in: Capsule())
                    .foregroundStyle(.white)
                    .padding(.bottom, 20)
                    .transition(.opacity)
            }
        }
    }

    private func say(_ s: String?) {
        guard let s else { return }
        withAnimation { toast = s }
        Task {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if toast == s { withAnimation { toast = nil } }
        }
    }

    // MARK: the videos

    private var picker: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(shown) { v in
                    Button { n = v.n } label: {
                        HStack(spacing: 4) {
                            Text(verbatim: "\(v.n)").font(.headline.monospacedDigit())
                            if v.posted {
                                Image(systemName: "checkmark.seal.fill")
                            } else if v.saved {
                                Image(systemName: "star.fill")
                            } else if v.skip {
                                Image(systemName: "nosign")
                            } else if v.rendered && !v.fresh {
                                Circle().fill(.orange).frame(width: 6, height: 6)
                            }
                        }
                        .font(.caption)
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(v.n == n ? Color.accentColor : Color.white.opacity(0.1), in: Capsule())
                        .foregroundStyle(v.n == n ? Color.white : Color.primary)
                    }
                    .accessibilityLabel(Text("Video \(v.n)"))
                }
            }
        }
    }

    /// The video as Ad Factory previews it (footage only; its captions are drawn over it here).
    private var stage: some View {
        ZStack {
            Color(white: 0.07)
            if preview?.state == "ready" {
                VideoPlayer(player: player.av) {
                    if let t = currentTake, !t.captionText.isEmpty {
                        VStack {
                            Spacer()
                            Text(verbatim: t.captionText)
                                .font(.system(size: 17, weight: .heavy))
                                .multilineTextAlignment(.center)
                                .foregroundStyle(.white)
                                .shadow(color: .black, radius: 2)
                                .padding(.horizontal, 24)
                                .padding(.bottom, 90)
                        }
                        .allowsHitTesting(false)
                    }
                }
            } else {
                if let thumb = video?.thumb { RemoteImage(path: thumb).opacity(0.45) }
                VStack(spacing: 10) {
                    if preview?.state == "failed" {
                        Image(systemName: "exclamationmark.triangle")
                        Text("The preview didn't build on the PC.").font(.footnote)
                        if let e = preview?.error { Text(verbatim: e).font(.caption2).opacity(0.7).lineLimit(3) }
                    } else {
                        ProgressView()
                        Text("Getting the preview ready on the PC…").font(.footnote)
                    }
                }
                .foregroundStyle(.white)
                .padding()
            }
        }
        .aspectRatio(9 / 16, contentMode: .fit)
        .frame(maxHeight: 460)
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private var currentTake: Take? {
        guard let segs = preview?.segs else { return nil }
        let t = player.time
        return segs.last { $0.off <= t + 0.01 }.flatMap { ed.take($0.take) }
    }

    private var status: some View {
        HStack(spacing: 10) {
            Text("Video \(n)").font(.headline)
            if let v = video {
                Text(verbatim: Self.clock(v.duration)).foregroundStyle(.secondary)
                if v.posted {
                    Label("Posted", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
                } else if v.saved {
                    Label("Saved", systemImage: "star.fill").foregroundStyle(.yellow)
                }
                if v.skip { Label("Skipped", systemImage: "nosign").foregroundStyle(.secondary) }
                if v.safety == "unsafe" {
                    Label("Not Shop-safe", systemImage: "exclamationmark.shield").foregroundStyle(.red)
                } else if v.safety == "check" {
                    Label("Check wording", systemImage: "exclamationmark.shield").foregroundStyle(.orange)
                }
            }
        }
        .font(.subheadline)
        .labelStyle(.titleAndIcon)
    }

    // MARK: its lines

    private var linesList: some View {
        let locked = video?.frozen ?? false
        let playing = currentTake?.id
        return VStack(spacing: 8) {
            ForEach(Array(ed.lines.enumerated()), id: \.element.id) { i, line in
                let t = ed.take(in: n, line: line.id)
                HStack(alignment: .top, spacing: 10) {
                    Text(verbatim: "\(i + 1)")
                        .font(.caption.bold().monospacedDigit())
                        .frame(width: 22, height: 22)
                        .background(Color.white.opacity(0.12), in: Circle())
                    VStack(alignment: .leading, spacing: 4) {
                        if let t {
                            Text(verbatim: t.captionText.isEmpty ? line.text : t.captionText)
                                .font(.callout)
                                .foregroundStyle(t.captionText.isEmpty ? .secondary : .primary)
                                .lineLimit(3)
                            badges(t, locked: locked)
                        } else {
                            Text(verbatim: line.text).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                            Text("Not in this video").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    Spacer(minLength: 0)
                    if let t, !locked {
                        Button { editing = LineRef(video: n, line: line.id, number: i + 1) } label: {
                            Image(systemName: "slider.horizontal.3")
                                .font(.body.bold())
                                .frame(width: 40, height: 36)
                                .background(Color.accentColor.opacity(0.25), in: RoundedRectangle(cornerRadius: 9))
                        }
                        .accessibilityLabel(Text("Edit line \(i + 1)"))
                        .disabled(t.id.isEmpty)
                    }
                }
                .padding(10)
                .background(t != nil && t?.id == playing ? Color.accentColor.opacity(0.18) : Color.white.opacity(0.06),
                            in: RoundedRectangle(cornerRadius: 12))
                .contentShape(Rectangle())
                .onTapGesture {   // jump to it in the preview
                    if let t, let seg = preview?.segs.first(where: { $0.take == t.id }) { player.seek(seg.off) }
                }
            }
        }
    }

    @ViewBuilder
    private func badges(_ t: Take, locked: Bool) -> some View {
        HStack(spacing: 8) {
            if t.status != "good" { Text(Grade.label(t.status)).foregroundStyle(.orange) }
            if let s = t.speed { Text(verbatim: String(format: "%.2f×", s)) }
            if t.captionsEdited { Label("Captions edited", systemImage: "pencil") }
            if locked { Image(systemName: "lock.fill") }
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .labelStyle(.titleAndIcon)
    }

    // MARK: what to do with it

    @ViewBuilder
    private var actions: some View {
        if let v = video {
            VStack(alignment: .leading, spacing: 10) {
                if v.frozen {
                    Label(v.posted ? "Posted: its takes are locked, because TikTok flags reused footage."
                                   : "Saved: its takes are locked. Unsave it to change them.",
                          systemImage: "lock.fill")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                if let j = ed.job {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text(verbatim: j.msg.isEmpty ? String(localized: "Working on it…") : j.msg).font(.footnote)
                    }
                } else if !v.skip {
                    if !v.fresh {
                        wide(v.rendered ? "Get it ready again (it changed)" : "Get it ready", "wand.and.stars", primary: true) {
                            await ed.render(v.n)
                        }
                        Text("Makes the finished video on the PC. Takes a minute or two.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        HStack(spacing: 10) {
                            wide("Watch", "play.fill", primary: true) { watching = FinalRef(n: v.n) }
                            wide("Save to Photos", "square.and.arrow.down") {
                                do {
                                    try await ed.saveToPhotos(v.n)
                                    say(String(localized: "Saved to Photos"))
                                } catch {
                                    ed.problem = error.localizedDescription
                                }
                            }
                        }
                    }
                }
                HStack(spacing: 10) {
                    if !v.posted {
                        wide(v.saved ? "Unsave" : "Save", v.saved ? "star.slash" : "star") {
                            await ed.setSaved(v.n, !v.saved)
                        }
                    }
                    wide(v.posted ? "Not posted" : "Mark posted", v.posted ? "arrow.uturn.backward" : "checkmark.seal") {
                        await ed.setPosted(v.n, !v.posted)
                    }
                }
                if !v.frozen {
                    wide(v.skip ? "Keep this video" : "Skip this video", v.skip ? "arrow.uturn.backward" : "nosign") {
                        ed.setSkip(v.n, !v.skip)
                    }
                }
            }
            .disabled(busy)
        }
    }

    private func wide(_ title: LocalizedStringKey, _ icon: String, primary: Bool = false,
                      _ action: @escaping () async -> Void) -> some View {
        Button {
            busy = true
            Task {
                await action()
                busy = false
            }
        } label: {
            Label(title, systemImage: icon)
                .font(.subheadline.bold())
                .frame(maxWidth: .infinity, minHeight: 46)
                .background(primary ? Color.accentColor : Color.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
                .foregroundStyle(primary ? Color.white : Color.primary)
        }
    }

    static func clock(_ s: Double) -> String {
        let t = max(0, s)
        return String(format: "%d:%02d", Int(t) / 60, Int(t.rounded()) % 60)
    }
}

struct LineRef: Identifiable {
    var video: Int
    var line: String
    var number: Int
    var id: String { "\(video)-\(line)" }
}

struct FinalRef: Identifiable {
    var n: Int
    var id: Int { n }
}

/// Take grades, named the way Ad Factory shows them (app.js STATUS).
enum Grade {
    static func label(_ s: String) -> LocalizedStringKey {
        switch s {
        case "good": return "Good"
        case "close": return "Reworded"
        case "flub": return "Flub"
        case "incomplete": return "Cut off"
        case "paused": return "Paused"
        case "nopayoff": return "Stayed lit"
        default: return "Other"
        }
    }
}

/// The video preview: a player plus where it is, for following along line by line.
@MainActor
final class PreviewPlayer: ObservableObject {
    let av = AVPlayer()
    @Published var time = 0.0
    private var path: String?

    init() {
        av.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 10), queue: .main) { [weak self] t in
            MainActor.assumeIsolated { self?.time = t.seconds }
        }
    }

    /// Switch to another file (a rebuilt preview keeps its place unless `from` says otherwise).
    func show(_ newPath: String?, from: Double? = nil) {
        guard newPath != path else {
            if let from { seek(from, play: false) }
            return
        }
        let at = from ?? time
        path = newPath
        av.replaceCurrentItem(with: newPath.flatMap(ShootEditor.asset).map { AVPlayerItem(asset: $0) })
        if newPath != nil, at > 0 { seek(at, play: false) }
    }

    func seek(_ s: Double, play: Bool = true) {
        av.seek(to: CMTime(seconds: s, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        if play { av.play() }
    }

    func stop() { av.pause() }
}

/// The finished video from the PC.
struct FinalPlayer: View {
    let path: String
    @Environment(\.dismiss) private var dismiss
    @State private var av = AVPlayer()

    var body: some View {
        NavigationStack {
            VideoPlayer(player: av)
                .ignoresSafeArea(edges: .bottom)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                }
                .onAppear {
                    av.replaceCurrentItem(with: ShootEditor.asset(path).map { AVPlayerItem(asset: $0) })
                    av.play()
                }
                .onDisappear { av.pause() }
        }
    }
}

/// An Ad Factory thumbnail (needs the sign-in cookie).
struct RemoteImage: View {
    let path: String
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Color.white.opacity(0.06)
            }
        }
        .clipped()
        .task(id: path) { image = await API.image(path) }
    }
}
