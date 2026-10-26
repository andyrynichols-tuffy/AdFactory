import AVFoundation
import SwiftUI

/// Filming for one project: 9:16 viewfinder with TikTok's UI zones, the script as a
/// teleprompter, and a record button that can stop and start as often as needed. Every take
/// goes into this project.
///
/// Two layouts: Handheld (controls over the picture) and Tripod clamp (a dead strip at the
/// top or bottom where the clamp covers the screen; the whole frame shrinks to fit the rest,
/// with the most used controls in columns beside it). Tripod clamp has its own control set:
/// back camera, its own countdown, teleprompter off by default.
struct CameraView: View {
    let project: Project
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var clips: ClipStore
    @Environment(\.dismiss) private var dismiss
    @StateObject private var camera = CameraController()

    @AppStorage("zones") private var showZones = true
    @AppStorage("grid") private var showGrid = false
    @AppStorage("prompter") private var handheldPrompter = true
    @AppStorage("tripodPrompter") private var tripodPrompter = false
    @AppStorage("prompterSize") private var prompterSize = 26.0
    @AppStorage("countdown") private var handheldCountdown = 0
    @AppStorage("tripodCountdown") private var tripodCountdown = 3
    @AppStorage("layout") private var layout = "handheld"
    @AppStorage("clampTop") private var clampTop = false
    @AppStorage("clampH") private var clampH = 160.0
    @AppStorage("clampSet") private var clampSet = false
    @AppStorage("pX") private var handX = 0.5      // where the teleprompter sits, per layout
    @AppStorage("pY") private var handY = 0.22
    @AppStorage("pW") private var handW = 0.92
    @AppStorage("tpX") private var triX = 0.5
    @AppStorage("tpY") private var triY = 0.15
    @AppStorage("tpW") private var triW = 0.62

    @State private var line = 0
    @State private var counting: Int?
    @State private var countTask: Task<Void, Never>?
    @State private var showBias = false
    @State private var showSettings = false
    @State private var showUploads = false
    @State private var editingClamp = false

    private var tripod: Bool { layout == "tripod" }
    private var prompterOn: Bool { tripod ? tripodPrompter : handheldPrompter }
    private var showPrompter: Bool { prompterOn && !project.lines.isEmpty }
    private var countdown: Int { tripod ? tripodCountdown : handheldCountdown }

    var body: some View {
        ZStack {
            GeometryReader { geo in
                let frame = tripod ? TripodFrame(size: geo.size, insets: Self.windowInsets, top: clampTop,
                                                 strip: CGFloat(clampH)) : nil
                let r = frame?.preview ?? Self.handheldRect(geo.size)
                ZStack(alignment: .topLeading) {
                    Color.black
                    ZStack {
                        CameraPreview(camera: camera, shutter: tapRecord)
                        Guides(zones: model.zones, safe: model.safe, showZones: showZones, showGrid: showGrid)
                            .allowsHitTesting(false)
                    }
                    .frame(width: r.width, height: r.height)
                    .clipped()
                    .position(x: r.midX, y: r.midY)
                    if let frame { tripodControls(frame) }
                }
                .animation(.easeInOut(duration: 0.25), value: frame)
            }
            .ignoresSafeArea()

            if !tripod { handheldControls }

            GeometryReader { geo in
                if showPrompter {
                    FloatingPrompter(lines: project.lines, line: $line,
                                     x: tripod ? $triX : $handX, y: tripod ? $triY : $handY,
                                     width: tripod ? $triW : $handW, size: $prompterSize, screen: geo.size) {
                        if tripod { tripodPrompter = false } else { handheldPrompter = false }
                    }
                }
            }
            .ignoresSafeArea()
        }
        .foregroundStyle(.white)
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
        .onAppear {
            if tripod { camera.position = .back }
            camera.start()
            UIApplication.shared.isIdleTimerDisabled = true
        }
        .onDisappear {
            countTask?.cancel()
            camera.stop()
            UIApplication.shared.isIdleTimerDisabled = false
        }
        .sheet(isPresented: $showSettings, onDismiss: { camera.reconfigure() }) {
            SettingsView().environmentObject(model)
        }
        .sheet(isPresented: $showUploads) {
            UploadsView().environmentObject(clips)
        }
    }

    static func handheldRect(_ size: CGSize) -> CGRect {
        let w = min(size.width, size.height * 9 / 16), h = w * 16 / 9
        return CGRect(x: (size.width - w) / 2, y: (size.height - h) / 2, width: w, height: h)
    }

    static var windowInsets: UIEdgeInsets {
        (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first?.safeAreaInsets ?? .zero
    }

    // MARK: - handheld: controls over the picture

    private var handheldControls: some View {
        VStack(spacing: 10) {
            HStack(alignment: .center) {
                backButton
                Spacer()
                status
                Spacer()
                HStack(spacing: 8) {
                    layoutMenu
                    settingsButton
                }
            }
            .padding(.horizontal, 14)
            .padding(.top, 4)
            alerts
            Spacer()
            if let n = counting { countdownNumber(n) }
            Spacer()
            VStack(spacing: 12) {
                HStack(spacing: 8) {
                    zonesTool
                    prompterTool
                    biasTool
                    lockAndZoom
                    Spacer()
                    micMeter
                }
                if showBias { biasSlider }
                HStack {
                    Button { showUploads = true } label: { takesBadge }
                        .frame(width: 80, alignment: .leading)
                    Spacer()
                    RecordButton(recording: camera.recording, counting: counting != nil, action: tapRecord)
                    Spacer()
                    flipButton.frame(width: 80, alignment: .trailing)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 6)
        }
    }

    // MARK: - tripod clamp: dead strip, smaller picture, controls beside it

    @ViewBuilder
    private func tripodControls(_ f: TripodFrame) -> some View {
        ClampStrip(editing: editingClamp)
            .frame(width: f.strip.width, height: f.strip.height)
            .position(x: f.strip.midX, y: f.strip.midY)

        VStack(spacing: 12) {   // left: getting around, guides
            backButton
            layoutMenu
            settingsButton
            Spacer(minLength: 0)
            zonesTool
            prompterTool
            biasTool
        }
        .padding(.vertical, 8)
        .frame(width: f.left.width, height: f.left.height)
        .position(x: f.left.midX, y: f.left.midY)

        VStack(spacing: 12) {   // right: the thumb's side, record in the middle
            Button { showUploads = true } label: { takesCount }
            Spacer(minLength: 0)
            RecordButton(recording: camera.recording, counting: counting != nil,
                         size: min(76, f.right.width - 6), action: tapRecord)
            Spacer(minLength: 0)
            flipButton
        }
        .padding(.vertical, 8)
        .frame(width: f.right.width, height: f.right.height)
        .position(x: f.right.midX, y: f.right.midY)

        VStack(spacing: 6) {   // above the picture
            Spacer(minLength: 0)
            status
        }
        .padding(.bottom, 6)
        .frame(width: f.above.width + 2 * min(f.left.width, 40), height: max(0, f.above.height))
        .clipped()
        .position(x: f.above.midX, y: f.above.midY)

        VStack {   // warnings (no sound, mic off…) along the top of the picture
            alerts
            Spacer(minLength: 0)
        }
        .padding(.top, 8)
        .frame(width: f.preview.width + 2 * min(f.left.width, 30), height: f.preview.height)
        .position(x: f.preview.midX, y: f.preview.midY)

        VStack(spacing: 6) {   // below the picture
            HStack(spacing: 8) {
                lockAndZoom
                Spacer(minLength: 0)
                micMeter
            }
            if showBias { biasSlider }
            Spacer(minLength: 0)
        }
        .padding(.top, 6)
        .frame(width: f.below.width, height: max(0, f.below.height))
        .clipped()
        .position(x: f.below.midX, y: f.below.midY)

        if let n = counting {
            countdownNumber(n).position(x: f.preview.midX, y: f.preview.midY)
        }
        if editingClamp {
            clampEditor
                .frame(width: min(320, f.preview.width + 2 * f.left.width - 16))
                .position(x: f.preview.midX, y: f.preview.midY)
        }
    }

    private var clampEditor: some View {
        VStack(spacing: 12) {
            Text("Where does the clamp cover the screen?")
                .font(.subheadline.bold())
                .multilineTextAlignment(.center)
            Picker("Clamp", selection: $clampTop) {
                Text("Top").tag(true)
                Text("Bottom").tag(false)
            }
            .pickerStyle(.segmented)
            HStack(spacing: 14) {
                Button { clampH = max(40, clampH - 10) } label: { Image(systemName: "minus") }
                    .accessibilityLabel(Text("Thinner"))
                Text("Strip size").font(.caption)
                Button { clampH = min(320, clampH + 10) } label: { Image(systemName: "plus") }
                    .accessibilityLabel(Text("Thicker"))
            }
            .buttonStyle(.bordered)
            Text("Line the striped strip up with the clamp. The picture shrinks to fit the rest of the screen.")
                .font(.caption)
                .opacity(0.75)
                .multilineTextAlignment(.center)
            Button {
                clampSet = true
                editingClamp = false
            } label: {
                Text("Done").bold().frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(14)
        .background(.black.opacity(0.85), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - shared pieces

    private var backButton: some View {
        Button { dismiss() } label: { circle("chevron.left", bold: true) }
            .disabled(camera.recording)
            .accessibilityLabel(Text("Back to projects"))
    }

    private var settingsButton: some View {
        Button { showSettings = true } label: { circle("gearshape") }
            .disabled(camera.recording)
            .accessibilityLabel(Text("Settings"))
    }

    private var flipButton: some View {
        Button { camera.flip(remember: !tripod) } label: { circle("arrow.triangle.2.circlepath.camera") }
            .disabled(camera.recording)
            .accessibilityLabel(Text("Switch camera"))
    }

    private var layoutMenu: some View {
        Menu {
            Picker(selection: Binding(get: { layout }, set: { setLayout($0) })) {
                Label("Handheld", systemImage: "hand.raised").tag("handheld")
                Label("Tripod clamp", systemImage: "rectangle.bottomhalf.filled").tag("tripod")
            } label: {
                Text("Layout")
            }
            if tripod {
                Button { editingClamp = true } label: {
                    Label("Set clamp area", systemImage: "arrow.up.and.down")
                }
            }
        } label: {
            circle(tripod ? "rectangle.bottomhalf.filled" : "hand.raised")
        }
        .disabled(camera.recording)
        .accessibilityLabel(Text("Layout"))
    }

    private func circle(_ icon: String, bold: Bool = false) -> some View {
        Image(systemName: icon)
            .font(bold ? .title3.bold() : .title3)
            .frame(width: 42, height: 42)
            .background(.black.opacity(0.45), in: Circle())
    }

    private var status: some View {
        VStack(spacing: 2) {
            if let s = camera.started {
                HStack(spacing: 6) {
                    Circle().fill(.red).frame(width: 9, height: 9)
                    Text(s, style: .timer).monospacedDigit().font(.headline)
                }
                .padding(.horizontal, 12).padding(.vertical, 5)
                .background(.black.opacity(0.55), in: Capsule())
            } else {
                Text(verbatim: project.title).font(.subheadline.bold()).lineLimit(1)
                Text(verbatim: camera.summary).font(.caption2).opacity(0.75)
            }
        }
    }

    /// Camera problems, and the sound checks: a wireless lav whose transmitter is off (or a
    /// receiver that isn't plugged in) otherwise only shows up later as a silent video.
    @ViewBuilder
    private var alerts: some View {
        VStack(spacing: 6) {
            if camera.micOff {
                banner(Text("The microphone is off for Ad Camera, so videos won't have sound. Tap to turn it on in Settings."),
                       color: .red) {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }
            } else if camera.silent {
                banner(Text("No sound coming in. Is the mic's transmitter on?"), color: .red) {}
            } else if camera.externalExpected && !camera.recording {
                banner(Text("Using the iPhone's own mic, not \(camera.externalName)."), color: .orange) {}
            }
            if let id = clips.silentTake, mine.contains(where: { $0.id == id }) {
                banner(Text("That take has no sound. Check the mic and film it again."), color: .red) {
                    clips.silentTake = nil
                }
            }
            if let p = camera.problem {
                banner(Text(verbatim: p), color: .orange) { camera.problem = nil }
            }
        }
        .padding(.horizontal)
    }

    private func banner(_ text: Text, color: Color, tap: @escaping () -> Void) -> some View {
        text
            .font(.footnote.bold())
            .multilineTextAlignment(.center)
            .lineLimit(3)
            .padding(10)
            .frame(maxWidth: .infinity)
            .background(color.opacity(0.88), in: RoundedRectangle(cornerRadius: 10))
            .onTapGesture(perform: tap)
    }

    private var micMeter: some View {
        if camera.micOff {
            return MicMeter(name: String(localized: "Mic is off"), level: 0, tint: .red)
        }
        if camera.silent {
            return MicMeter(name: String(localized: "No sound"), level: camera.level, tint: .red)
        }
        if camera.externalExpected {
            return MicMeter(name: String(localized: "iPhone mic"), level: camera.level, tint: .orange)
        }
        return MicMeter(name: camera.mic, level: camera.level, tint: nil)
    }

    private func countdownNumber(_ n: Int) -> some View {
        Text(verbatim: "\(n)")
            .font(.system(size: 120, weight: .heavy, design: .rounded))
            .minimumScaleFactor(0.4)
            .shadow(radius: 10)
            .transition(.scale)
    }

    private var zonesTool: some View {
        tool("rectangle.dashed", on: showZones, label: Text("TikTok screen guides")) { showZones.toggle() }
    }

    @ViewBuilder
    private var prompterTool: some View {
        if !project.lines.isEmpty {
            tool("text.bubble", on: prompterOn, label: Text("Teleprompter")) {
                if tripod { tripodPrompter.toggle() } else { handheldPrompter.toggle() }
            }
        }
    }

    private var biasTool: some View {
        tool("plusminus.circle", on: showBias, label: Text("Brightness")) { showBias.toggle() }
    }

    private var biasSlider: some View {
        Slider(value: Binding(get: { Double(camera.bias) }, set: { camera.setBias(Float($0)) }), in: -2...2, step: 0.1)
            .tint(.yellow)
    }

    @ViewBuilder
    private var lockAndZoom: some View {
        if camera.locked {
            Text("AE/AF LOCK")
                .font(.caption2.bold())
                .padding(.horizontal, 6).padding(.vertical, 3)
                .background(.yellow, in: RoundedRectangle(cornerRadius: 4))
                .foregroundStyle(.black)
        }
        if camera.zoom > 1.05 {
            Text(verbatim: String(format: "%.1fx", camera.zoom)).font(.caption.bold())
        }
    }

    private var mine: [Clip] { clips.clips.filter { $0.project == project.sid } }

    private var takesBadge: some View {
        let left = mine.filter { !$0.uploaded }.count
        return VStack(alignment: .leading, spacing: 2) {
            Text("\(mine.count) takes").font(.subheadline.bold())
            if left > 0 {
                Label { Text("\(left) to send") } icon: { Image(systemName: "arrow.up.circle") }
                    .font(.caption2)
            } else if !mine.isEmpty {
                Label { Text("All sent") } icon: { Image(systemName: "checkmark.circle.fill") }
                    .font(.caption2)
                    .foregroundStyle(.green)
            }
        }
        .padding(8)
        .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 10))
    }

    /// The takes badge squeezed into a side column: the count, and whether any are still uploading.
    private var takesCount: some View {
        let left = mine.filter { !$0.uploaded }.count
        return VStack(spacing: 2) {
            Text(verbatim: "\(mine.count)").font(.title3.bold())
            if !mine.isEmpty {
                Image(systemName: left > 0 ? "arrow.up.circle" : "checkmark.circle.fill")
                    .font(.caption)
                    .foregroundStyle(left > 0 ? Color.white : Color.green)
            }
        }
        .frame(width: 54, height: 54)
        .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("\(mine.count) takes"))
    }

    private func tool(_ icon: String, on: Bool, label: Text, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.body)
                .frame(width: 36, height: 36)
                .background(on ? Color.white.opacity(0.3) : Color.black.opacity(0.45), in: Circle())
        }
        .accessibilityLabel(label)
    }

    // MARK: - layout and recording

    /// Each layout keeps its own control set: the tripod one films on the back camera.
    private func setLayout(_ new: String) {
        guard !camera.recording, new != layout else { return }
        withAnimation { layout = new }
        if new == "tripod" {
            camera.use(.back)
            if !clampSet { editingClamp = true }   // first time: show where the clamp goes
        } else {
            editingClamp = false
            camera.use(UserDefaults.standard.string(forKey: "camera") == "front" ? .front : .back)
        }
    }

    private func tapRecord() {
        if editingClamp { return }
        if camera.recording {
            camera.stopRecording()
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            return
        }
        if let t = countTask {   // a second tap during the countdown cancels it
            t.cancel()
            countTask = nil
            counting = nil
            return
        }
        guard countdown > 0 else { return begin() }
        let from = countdown
        countTask = Task { @MainActor in
            for n in stride(from: from, to: 0, by: -1) {
                withAnimation { counting = n }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled { return }
            }
            counting = nil
            countTask = nil
            begin()
        }
    }

    private func begin() {
        let at = showPrompter ? line : nil
        let p = project
        let store = clips
        camera.record(to: ClipStore.newFile(for: p)) { file, secs in
            store.add(file: file, project: p, seconds: secs, line: at)
        }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }
}

/// Where everything goes in the Tripod clamp layout (full-screen points): the dead strip the
/// clamp covers, the whole 9:16 frame shrunk to fit the rest (leaving `column` points on each
/// side for controls), and the leftover space above and below the picture.
struct TripodFrame: Equatable {
    var strip: CGRect
    var preview: CGRect
    var above: CGRect
    var below: CGRect
    var left: CGRect
    var right: CGRect

    init(size: CGSize, insets: UIEdgeInsets, top: Bool, strip d: CGFloat, column: CGFloat = 72) {
        let W = size.width, H = size.height
        strip = top ? CGRect(x: 0, y: 0, width: W, height: d) : CGRect(x: 0, y: H - d, width: W, height: d)
        let y0 = top ? max(d, insets.top) : insets.top
        let y1 = top ? H - insets.bottom : H - max(d, insets.bottom)
        let pw = max(0, min(W - 2 * column, (y1 - y0) * 9 / 16))
        let ph = pw * 16 / 9
        preview = CGRect(x: (W - pw) / 2, y: (y0 + y1 - ph) / 2, width: pw, height: ph)
        above = CGRect(x: preview.minX, y: y0, width: pw, height: preview.minY - y0)
        below = CGRect(x: preview.minX, y: preview.maxY, width: pw, height: y1 - preview.maxY)
        left = CGRect(x: 0, y: y0, width: preview.minX, height: y1 - y0)
        right = CGRect(x: preview.maxX, y: y0, width: W - preview.maxX, height: y1 - y0)
    }
}

/// The part of the screen under the clamp: striped so it's easy to line up with the clamp.
struct ClampStrip: View {
    var editing: Bool

    var body: some View {
        Canvas { ctx, size in
            var p = Path()
            var x = -size.height
            while x < size.width {
                p.move(to: CGPoint(x: x, y: size.height))
                p.addLine(to: CGPoint(x: x + size.height, y: 0))
                x += 16
            }
            ctx.stroke(p, with: .color(.white.opacity(editing ? 0.4 : 0.12)), lineWidth: 2)
        }
        .background(Color.black.opacity(editing ? 0.5 : 0.2))
        .overlay {
            if editing {
                Text("Clamp").font(.headline).padding(6).background(.black.opacity(0.6), in: Capsule())
            }
        }
        .overlay(Rectangle().stroke(editing ? Color.yellow : Color.clear, lineWidth: 2))
        .allowsHitTesting(false)
    }
}

/// TikTok's UI (top tabs, like rail, caption block, cart tag) shaded, and the safe area
/// outlined; the same boxes Ad Factory keeps text out of (adcut/layout.py).
struct Guides: View {
    var zones: [String: [Double]]
    var safe: [Double]
    var showZones: Bool
    var showGrid: Bool

    var body: some View {
        GeometryReader { g in
            let W = g.size.width, H = g.size.height
            ZStack(alignment: .topLeading) {
                if showGrid {
                    Path { p in
                        for i in 1...2 {
                            let x = W * CGFloat(i) / 3, y = H * CGFloat(i) / 3
                            p.move(to: CGPoint(x: x, y: 0)); p.addLine(to: CGPoint(x: x, y: H))
                            p.move(to: CGPoint(x: 0, y: y)); p.addLine(to: CGPoint(x: W, y: y))
                        }
                    }
                    .stroke(Color.white.opacity(0.35), lineWidth: 0.5)
                }
                if showZones {
                    ForEach(zones.keys.sorted(), id: \.self) { k in
                        if let b = zones[k], b.count == 4 {
                            Rectangle()
                                .fill(Color.black.opacity(0.3))
                                .overlay(alignment: .topLeading) {
                                    Text(LocalizedStringKey(k))
                                        .font(.system(size: 9, weight: .semibold))
                                        .opacity(0.7)
                                        .padding(3)
                                }
                                .frame(width: W * (b[2] - b[0]), height: H * (b[3] - b[1]))
                                .offset(x: W * b[0], y: H * b[1])
                        }
                    }
                    if safe.count == 4 {
                        Rectangle()
                            .stroke(Color.white.opacity(0.45), style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
                            .frame(width: W * (safe[2] - safe[0]), height: H * (safe[3] - safe[1]))
                            .offset(x: W * safe[0], y: H * safe[1])
                    }
                }
            }
            .foregroundStyle(.white)
        }
    }
}

struct RecordButton: View {
    var recording: Bool
    var counting: Bool
    var size: CGFloat = 80
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle().stroke(.white, lineWidth: size * 0.0625).frame(width: size, height: size)
                RoundedRectangle(cornerRadius: recording ? size * 0.1 : size * 0.41)
                    .fill(Color.red)
                    .frame(width: recording ? size * 0.42 : size * 0.82, height: recording ? size * 0.42 : size * 0.82)
                if counting {
                    Image(systemName: "xmark").font(.title2.bold()).foregroundStyle(.white)
                }
            }
            .animation(.easeInOut(duration: 0.18), value: recording)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(recording ? Text("Stop recording") : Text("Record"))
    }
}

/// Which mic is recording and how loud it is; tinted red/orange when the sound needs a look.
struct MicMeter: View {
    var name: String
    var level: Float
    var tint: Color?

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "mic.fill").font(.caption)
            Capsule()
                .fill(Color.white.opacity(0.25))
                .frame(width: 50, height: 6)
                .overlay(alignment: .leading) {
                    Capsule()
                        .fill(level > 0.9 ? Color.red : Color.green)
                        .frame(width: 50 * CGFloat(level), height: 6)
                }
            if !name.isEmpty {
                Text(verbatim: name).font(.caption2.bold()).lineLimit(1).frame(maxWidth: 100, alignment: .leading)
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background((tint ?? .black).opacity(tint == nil ? 0.45 : 0.85), in: Capsule())
    }
}
