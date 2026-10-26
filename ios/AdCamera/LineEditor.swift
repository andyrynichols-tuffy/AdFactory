import AVKit
import Combine
import SwiftUI

/// One line of one video: its take played from the raw footage, with its trim, captions and
/// speed, and every other take of the line to try and swap in.
struct LineEditor: View {
    @ObservedObject var ed: ShootEditor
    let video: Int
    let lineId: String
    let number: Int
    @Environment(\.dismiss) private var dismiss
    @StateObject private var player = TakePlayer()
    @State private var trying: String?          // another take, played to compare
    @State private var words = ""
    @State private var window: ClosedRange<Double> = 0...1   // the part of the raw file the trim bar shows
    @State private var message: String?

    private static let speeds: [Double] = [1, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5]   // app.js
    private var take: Take? { ed.take(in: video, line: lineId) }
    private var other: Take? { trying.flatMap(ed.take).flatMap { $0.id == take?.id ? nil : $0 } }

    var body: some View {
        NavigationStack {
            ScrollViewReader { scroller in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let take {
                        playerBox.id("top")
                        if let message {
                            Label { Text(verbatim: message) } icon: { Image(systemName: "checkmark.circle.fill") }
                                .font(.footnote)
                                .foregroundStyle(.green)
                        }
                        if let other {
                            tryingBar(other)
                        } else {
                            trimBox(take)
                            captionsBox(take)
                            speedBox(take)
                        }
                        othersBox(take)
                    } else {
                        Text("This line isn't in the video anymore.").foregroundStyle(.secondary)
                    }
                }
                .padding()
            }
            .onChange(of: take?.id) { withAnimation { scroller.scrollTo("top", anchor: .top) } }
            }
            .navigationTitle(Text("Line \(number)"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        saveWords()
                        dismiss()
                    }
                }
                ToolbarItem(placement: .topBarLeading) {
                    if ed.saving { ProgressView() }
                }
            }
        }
        .onAppear { reset() }
        .onChange(of: take?.id) { reset() }
        .onChange(of: rangeKey) { load(other ?? take) }
        .onDisappear {
            saveWords()
            player.stop()
        }
    }

    private var rangeKey: String {
        let t = other ?? take
        return "\(t?.id ?? "")|\(t?.start ?? 0)|\(t?.end ?? 0)|\(t.map(ed.speed) ?? 1)"
    }

    private func reset() {
        trying = nil
        guard let take else { return }
        words = take.captionText
        let length = ed.sourceLength(take) ?? take.end + 3
        window = max(0, take.start - 3)...min(length, take.end + 3)
        load(take)
    }

    private func load(_ t: Take?) {
        guard let t else { return }
        if let take, t.id == take.id {   // keep the whole trim in view
            window = min(window.lowerBound, t.start)...max(window.upperBound, t.end)
        }
        player.load(ed.sourceKey(t).map { "/proxy/\($0).mp4" }, start: t.start, end: t.end, cuts: t.cuts,
                    rate: Float(ed.speed(t)), window: t.id == take?.id ? window : nil)
    }

    private func saveWords() {
        guard let take, other == nil else { return }
        let w = words.trimmingCharacters(in: .whitespacesAndNewlines)
        if !w.isEmpty, w != take.captionText { ed.setCaptions(take.id, w) }
    }

    // MARK: the player

    private var playerBox: some View {
        VStack(spacing: 10) {
            VideoPlayer(player: player.av)
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            HStack(spacing: 14) {
                Button { player.playing ? player.pause() : player.play() } label: {
                    Image(systemName: player.playing ? "pause.fill" : "play.fill")
                        .font(.title3)
                        .frame(width: 48, height: 40)
                        .background(Color.accentColor, in: RoundedRectangle(cornerRadius: 10))
                        .foregroundStyle(.white)
                }
                .accessibilityLabel(player.playing ? Text("Pause") : Text("Play"))
                Text(verbatim: Self.time(player.time)).font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                Spacer()
                if let t = other ?? take {
                    Text("\(String(format: "%.1f", t.footage / ed.speed(t))) s at \(String(format: "%.2f", ed.speed(t)))×")
                        .font(.footnote.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    // MARK: trim

    private func trimBox(_ t: Take) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Trim").font(.headline)
            TrimBar(window: window, start: t.start, end: t.end, cuts: t.cuts, playhead: player.time) {
                player.scrub(to: $0)
            }
            .frame(height: 44)
            HStack(alignment: .top, spacing: 12) {
                trimSide("Start", t.start) { ed.trim(t.id, start: $0) }
                trimSide("End", t.end) { ed.trim(t.id, end: $0) }
            }
            Text("Drag along the bar to find the spot, then set the start or end there. ± moves it a twentieth of a second.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func trimSide(_ name: LocalizedStringKey, _ value: Double, set: @escaping (Double) -> Void) -> some View {
        VStack(spacing: 8) {
            HStack {
                Text(name).font(.subheadline.bold())
                Spacer()
                Text(verbatim: Self.time(value)).font(.subheadline.monospacedDigit())
            }
            HStack(spacing: 8) {
                Button { set(value - 0.05) } label: { Image(systemName: "minus").frame(maxWidth: .infinity, minHeight: 32) }
                    .accessibilityLabel(Text("Earlier"))
                Button { set(value + 0.05) } label: { Image(systemName: "plus").frame(maxWidth: .infinity, minHeight: 32) }
                    .accessibilityLabel(Text("Later"))
            }
            .buttonStyle(.bordered)
            Button { set(player.time) } label: {
                Text("Set here").font(.footnote.bold()).frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!player.ready || !window.contains(player.time))   // no footage yet: the playhead means nothing
        }
        .padding(10)
        .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
    }

    // MARK: captions and speed

    private func captionsBox(_ t: Take) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Captions").font(.headline)
            TextField("What the captions say", text: $words, axis: .vertical)
                .lineLimit(2...6)
                .padding(10)
                .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
            HStack {
                Button("Save captions") { saveWords() }
                    .buttonStyle(.borderedProminent)
                    .disabled(words.trimmingCharacters(in: .whitespacesAndNewlines) == t.captionText
                              || words.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if t.captionsEdited {
                    Button("Back to what was said") { ed.resetCaptions(t.id) }
                        .buttonStyle(.bordered)
                }
            }
            Text("Fixing a word keeps its timing. Adding or removing words spreads them over the same stretch.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .onChange(of: t.captionText) { words = t.captionText }
    }

    private func speedBox(_ t: Take) -> some View {
        HStack {
            Text("Speed").font(.headline)
            Spacer()
            Picker("Speed", selection: Binding(get: { t.speed ?? 0 }, set: { ed.setSpeed(t.id, $0 == 0 ? nil : $0) })) {
                Text("Auto · \(String(format: "%.2f", ed.autoSpeed(t)))×").tag(0.0)
                ForEach(Self.speeds, id: \.self) { v in
                    Text(verbatim: String(format: "%.2f×", v)).tag(v)
                }
            }
            .pickerStyle(.menu)
        }
    }

    // MARK: other takes

    private func tryingBar(_ o: Take) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Trying another take").font(.headline)
            Text(verbatim: o.captionText.isEmpty ? (o.j["text"]?.string ?? "") : o.captionText)
                .font(.callout)
            whereLabel(o).font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Button { use(o) } label: {
                    Label("Use this take", systemImage: "arrow.left.arrow.right").frame(maxWidth: .infinity, minHeight: 34)
                }
                .buttonStyle(.borderedProminent)
                .disabled(ed.lockedIn(o.id) != nil)
                Button { trying = nil; load(take) } label: {
                    Text("Back").frame(maxWidth: .infinity, minHeight: 34)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(12)
        .background(Color.accentColor.opacity(0.15), in: RoundedRectangle(cornerRadius: 12))
    }

    private func othersBox(_ t: Take) -> some View {
        let others = ed.takes.filter { $0.line == lineId && $0.id != t.id }.sorted { a, b in
            let (ga, gb) = (group(a), group(b))
            if ga != gb { return ga < gb }
            return (ed.videoOf(a.id)?.n ?? 0, a.order) < (ed.videoOf(b.id)?.n ?? 0, b.order)
        }
        return VStack(alignment: .leading, spacing: 8) {
            Text("Other takes of this line").font(.headline)
            if others.isEmpty {
                Text("There's only this one.").font(.callout).foregroundStyle(.secondary)
            }
            ForEach(others) { o in
                HStack(spacing: 10) {
                    if let thumb = ed.thumb(o) {
                        RemoteImage(path: thumb)
                            .frame(width: 56, height: 56)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(verbatim: o.captionText.isEmpty ? (o.j["text"]?.string ?? "") : o.captionText)
                            .font(.footnote)
                            .lineLimit(2)
                        HStack(spacing: 6) {
                            whereLabel(o)
                            if o.status != "good" { Text(Grade.label(o.status)).foregroundStyle(.orange) }
                            Text(verbatim: String(format: "%.1f s", o.footage / ed.speed(o)))
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    Button { trying = o.id; load(o); player.play() } label: {
                        Image(systemName: "play.fill").frame(width: 36, height: 36)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityLabel(Text("Play"))
                    Button("Use") { use(o) }
                        .buttonStyle(.borderedProminent)
                        .disabled(ed.lockedIn(o.id) != nil)
                }
                .padding(8)
                .background(o.id == trying ? Color.accentColor.opacity(0.15) : Color.white.opacity(0.05),
                            in: RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    /// 0 = in another video, 1 = a spare, 2 = locked, 3 = a reject.
    private func group(_ t: Take) -> Int {
        if ed.lockedIn(t.id) != nil { return 2 }
        if ed.videoOf(t.id) != nil { return 0 }
        return t.usable ? 1 : 3
    }

    @ViewBuilder
    private func whereLabel(_ t: Take) -> some View {
        if let k = ed.lockedIn(t.id) {
            Label("In saved video \(k)", systemImage: "lock.fill")
        } else if let v = ed.videoOf(t.id) {
            Text("In video \(v.n)")
        } else if t.usable {
            Text("Spare")
        } else {
            Text("Reject")
        }
    }

    private func use(_ o: Take) {
        player.stop()
        message = ed.use(o.id, inVideo: video)
        trying = nil
    }

    static func time(_ s: Double) -> String {
        let t = max(0, s)
        return String(format: "%d:%05.2f", Int(t) / 60, t.truncatingRemainder(dividingBy: 60))
    }
}

/// The raw file around the take: the kept part filled, cut-outs dark, the playhead white.
/// Dragging moves the playhead.
struct TrimBar: View {
    let window: ClosedRange<Double>
    let start: Double
    let end: Double
    let cuts: [(Double, Double)]
    let playhead: Double
    let scrub: (Double) -> Void

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, span = max(0.1, window.upperBound - window.lowerBound)
            let x = { (v: Double) in CGFloat((min(max(v, window.lowerBound), window.upperBound) - window.lowerBound) / span) * w }
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.1))
                RoundedRectangle(cornerRadius: 8).fill(Color.accentColor.opacity(0.55))
                    .frame(width: max(2, x(end) - x(start)))
                    .offset(x: x(start))
                ForEach(Array(cuts.enumerated()), id: \.offset) { _, c in
                    Rectangle().fill(Color.black.opacity(0.6))
                        .frame(width: max(1, x(c.1) - x(c.0)))
                        .offset(x: x(c.0))
                }
                Rectangle().fill(Color.white).frame(width: 2).offset(x: x(playhead) - 1)
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { g in
                scrub(window.lowerBound + Double(min(max(0, g.location.x), w) / w) * span)
            })
        }
        .accessibilityElement()
        .accessibilityLabel(Text("Trim bar"))
    }
}

/// Plays one take from its raw file: from the start (or wherever the playhead is) to its end,
/// jumping its cut-outs, at its speed.
@MainActor
final class TakePlayer: ObservableObject {
    let av = AVPlayer()
    @Published var time = 0.0
    @Published var playing = false
    @Published var ready = false        // the footage has loaded
    private var path: String?
    private var start = 0.0, end = 0.0, stopAt = 0.0
    private var window: ClosedRange<Double>?
    private var cuts: [(Double, Double)] = []
    private var rate: Float = 1
    private var status: AnyCancellable?

    init() {
        av.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 30), queue: .main) { [weak self] t in
            MainActor.assumeIsolated { self?.tick(t.seconds) }
        }
    }

    private func tick(_ t: Double) {
        time = t
        playing = av.rate > 0
        guard playing else { return }
        if t >= stopAt {
            av.pause()
            playing = false
        } else if let c = cuts.first(where: { t >= $0.0 && t < $0.1 }) {
            seek(c.1)
        }
    }

    func load(_ newPath: String?, start: Double, end: Double, cuts: [(Double, Double)], rate: Float,
              window: ClosedRange<Double>?) {
        let moved = newPath != path || start != self.start || end != self.end
        (self.start, self.end, self.cuts, self.rate, self.window) = (start, end, cuts, rate, window)
        if newPath != path {
            path = newPath
            ready = false
            let item = newPath.flatMap(ShootEditor.asset).map { AVPlayerItem(asset: $0) }
            item?.audioTimePitchAlgorithm = .timeDomain   // sped-up speech keeps its pitch
            av.replaceCurrentItem(with: item)
            status = item?.publisher(for: \.status).receive(on: RunLoop.main).sink { [weak self] s in
                guard let self, s == .readyToPlay, !self.ready else { return }
                self.ready = true
                self.seek(self.start)   // a seek asked for before it loaded may not have landed
                self.time = self.start
            }
        }
        if av.rate > 0 { av.rate = rate }
        if moved, av.rate == 0 { seek(start) }
    }

    /// From the playhead if it's before the end (so a trim can be heard past the start),
    /// else from the start.
    func play() {
        if time >= end - 0.05 || time < (window?.lowerBound ?? start) - 0.01 { seek(start) }
        stopAt = end
        av.playImmediately(atRate: rate)
        playing = true
    }

    func pause() {
        av.pause()
        playing = false
    }

    func scrub(to s: Double) {
        pause()
        seek(s)
        time = s
    }

    func seek(_ s: Double) {
        av.seek(to: CMTime(seconds: s, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
    }

    func stop() { pause() }
}
