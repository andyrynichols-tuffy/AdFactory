import AVFoundation
import SwiftUI

/// Filming for one project: 9:16 viewfinder with TikTok's UI zones, the script as a
/// teleprompter up by the lens, and a record button that can stop and start as often as
/// needed. Every take goes into this project.
struct CameraView: View {
    let project: Project
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var clips: ClipStore
    @Environment(\.dismiss) private var dismiss
    @StateObject private var camera = CameraController()

    @AppStorage("zones") private var showZones = true
    @AppStorage("grid") private var showGrid = false
    @AppStorage("prompter") private var showPrompter = true
    @AppStorage("prompterSize") private var prompterSize = 26.0
    @AppStorage("countdown") private var countdown = 0

    @State private var line = 0
    @State private var counting: Int?
    @State private var countTask: Task<Void, Never>?
    @State private var showBias = false
    @State private var showSettings = false
    @State private var showUploads = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            GeometryReader { geo in
                let w = min(geo.size.width, geo.size.height * 9 / 16)
                let h = w * 16 / 9
                ZStack {
                    CameraPreview(camera: camera, shutter: tapRecord)
                    Guides(zones: model.zones, safe: model.safe, showZones: showZones, showGrid: showGrid)
                        .allowsHitTesting(false)
                }
                .frame(width: w, height: h)
                .clipped()
                .position(x: geo.size.width / 2, y: geo.size.height / 2)
            }
            .ignoresSafeArea()

            VStack(spacing: 10) {
                topBar
                if showPrompter && !project.lines.isEmpty { prompter }
                if let p = camera.problem {
                    Text(verbatim: p)
                        .font(.footnote)
                        .padding(10)
                        .background(.orange.opacity(0.85), in: RoundedRectangle(cornerRadius: 10))
                        .onTapGesture { camera.problem = nil }
                        .padding(.horizontal)
                }
                Spacer()
                if let n = counting {
                    Text(verbatim: "\(n)")
                        .font(.system(size: 120, weight: .heavy, design: .rounded))
                        .shadow(radius: 10)
                        .transition(.scale)
                }
                Spacer()
                bottomBar
            }
            .foregroundStyle(.white)
        }
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
        .onAppear {
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

    // MARK: - parts

    private var topBar: some View {
        HStack(alignment: .center) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.title3.bold())
                    .frame(width: 42, height: 42)
                    .background(.black.opacity(0.45), in: Circle())
            }
            .disabled(camera.recording)
            .accessibilityLabel(Text("Back to projects"))
            Spacer()
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
            Spacer()
            Button { showSettings = true } label: {
                Image(systemName: "gearshape")
                    .font(.title3)
                    .frame(width: 42, height: 42)
                    .background(.black.opacity(0.45), in: Circle())
            }
            .disabled(camera.recording)
            .accessibilityLabel(Text("Settings"))
        }
        .padding(.horizontal, 14)
        .padding(.top, 4)
    }

    /// Up top, close to the front lens, so reading it still looks like eye contact.
    private var prompter: some View {
        let lines = project.lines
        let i = min(line, lines.count - 1)
        return VStack(spacing: 6) {
            Text(verbatim: lines[i])
                .font(.system(size: prompterSize, weight: .bold))
                .multilineTextAlignment(.center)
                .lineLimit(5)
                .minimumScaleFactor(0.6)
            if i + 1 < lines.count {
                Text(verbatim: lines[i + 1])
                    .font(.system(size: prompterSize * 0.6))
                    .multilineTextAlignment(.center)
                    .opacity(0.55)
                    .lineLimit(2)
            }
            HStack {
                Text("Line \(i + 1) of \(lines.count)")
                Spacer()
                Text("Tap: next line · swipe right: back")
            }
            .font(.caption2)
            .opacity(0.6)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.black.opacity(0.5), in: RoundedRectangle(cornerRadius: 14))
        .padding(.horizontal, 12)
        .contentShape(Rectangle())
        .onTapGesture { line = min(lines.count - 1, i + 1) }
        .gesture(DragGesture(minimumDistance: 30).onEnded { v in
            line = v.translation.width > 0 ? max(0, i - 1) : min(lines.count - 1, i + 1)
        })
    }

    private var bottomBar: some View {
        VStack(spacing: 12) {
            HStack(spacing: 8) {
                tool("rectangle.dashed", on: showZones, label: Text("TikTok screen guides")) { showZones.toggle() }
                if !project.lines.isEmpty {
                    tool("text.bubble", on: showPrompter, label: Text("Teleprompter")) { showPrompter.toggle() }
                }
                tool("plusminus.circle", on: showBias, label: Text("Brightness")) { showBias.toggle() }
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
                Spacer()
                MicMeter(name: camera.mic, level: camera.level)
            }
            if showBias {
                Slider(value: Binding(get: { Double(camera.bias) }, set: { camera.setBias(Float($0)) }),
                       in: -2...2, step: 0.1)
                    .tint(.yellow)
            }
            HStack {
                Button { showUploads = true } label: { takesBadge }
                    .frame(width: 80, alignment: .leading)
                Spacer()
                RecordButton(recording: camera.recording, counting: counting != nil, action: tapRecord)
                Spacer()
                Button { camera.flip() } label: {
                    Image(systemName: "arrow.triangle.2.circlepath.camera")
                        .font(.title2)
                        .frame(width: 56, height: 56)
                        .background(.black.opacity(0.45), in: Circle())
                }
                .disabled(camera.recording)
                .accessibilityLabel(Text("Switch camera"))
                .frame(width: 80, alignment: .trailing)
            }
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 6)
    }

    private var takesBadge: some View {
        let mine = clips.clips.filter { $0.project == project.sid }
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

    private func tool(_ icon: String, on: Bool, label: Text, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.body)
                .frame(width: 36, height: 36)
                .background(on ? Color.white.opacity(0.3) : Color.black.opacity(0.45), in: Circle())
        }
        .accessibilityLabel(label)
    }

    // MARK: - recording

    private func tapRecord() {
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
        countTask = Task { @MainActor in
            for n in stride(from: countdown, to: 0, by: -1) {
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
        let at = showPrompter && !project.lines.isEmpty ? line : nil
        let p = project
        let store = clips
        camera.record(to: ClipStore.newFile(for: p)) { file, secs in
            store.add(file: file, project: p, seconds: secs, line: at)
        }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
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
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle().stroke(.white, lineWidth: 5).frame(width: 80, height: 80)
                RoundedRectangle(cornerRadius: recording ? 8 : 33)
                    .fill(Color.red)
                    .frame(width: recording ? 34 : 66, height: recording ? 34 : 66)
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

struct MicMeter: View {
    var name: String
    var level: Float

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
                Text(verbatim: name).font(.caption2).lineLimit(1).frame(maxWidth: 100, alignment: .leading)
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(.black.opacity(0.45), in: Capsule())
    }
}
