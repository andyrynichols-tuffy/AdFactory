import AVFoundation
import Speech
import SwiftUI

/// Hands-free filming (user, 2026-10-27). Every command starts with "Ad Camera", so words in a script
/// ("cut", "next") never trigger anything:
///   "Ad Camera, action"            start a take (the countdown setting still applies)
///   "Ad Camera, cut"               stop it (the take is kept)
///   "Ad Camera, scrap that"        throw away the take just filmed (also "delete that", "toss it")
///   "Ad Camera, keep"              keep it now instead of waiting a few seconds
///   "Ad Camera, next line" / "last line"            move the teleprompter
///   "Ad Camera, teleprompter on" / "teleprompter off"
/// The screen decides which commands count right now (only "cut" while recording). Listens with on-device
/// speech recognition through the same mic the camera records with; the spoken "cut" lands after the last
/// script line, where pre-cutting in Ad Factory leaves it out anyway.
struct VoiceCommand {
    let label: String                 // shown for a moment when heard ("Next line")
    let phrases: [[String]]           // the words after "Ad Camera", e.g. [["next", "line"]]
    var when: () -> Bool = { true }   // only listened for when this says so
    let run: () -> Void
}

@MainActor
final class VoiceControl: ObservableObject {
    @Published var listening = false
    @Published var problem: String?
    @Published var heard: String?          // "Action" / "Cut", shown for a moment

    private let engine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var commands: [VoiceCommand] = []
    private var restartTimer: Timer?
    private var lastFire = Date.distantPast
    private var running = false

    static var enabled: Bool { UserDefaults.standard.object(forKey: "voiceControl") as? Bool ?? true }

    func start(action: @escaping () -> Void, cut: @escaping () -> Void) {
        start([VoiceCommand(label: "Action", phrases: [["action"], ["actions"]], run: action),
               VoiceCommand(label: "Cut", phrases: [["cut"], ["cuts"], ["cart"], ["kut"]], run: cut)])
    }

    func start(_ commands: [VoiceCommand]) {
        self.commands = commands
        guard Self.enabled else { return }
        SFSpeechRecognizer.requestAuthorization { status in
            Task { @MainActor in
                guard status == .authorized else {
                    self.problem = String(localized: "Voice control needs Speech Recognition: Settings → Ad Camera.")
                    return
                }
                self.running = true
                self.begin()
            }
        }
    }

    func stop() {
        running = false
        restartTimer?.invalidate()
        restartTimer = nil
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        if engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        listening = false
    }

    private func begin() {
        guard running else { return }
        let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
        guard let rec, rec.isAvailable else {
            problem = String(localized: "Voice control isn't available right now.")
            return
        }
        recognizer = rec
        do {
            // share the mic with the camera: the capture session uses this same audio session
            let s = AVAudioSession.sharedInstance()
            try s.setCategory(.playAndRecord, mode: .videoRecording, options: [.mixWithOthers, .allowBluetooth, .defaultToSpeaker])
            try s.setActive(true)
            let req = SFSpeechAudioBufferRecognitionRequest()
            req.shouldReportPartialResults = true
            if rec.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
            req.contextualStrings = ["Ad Camera action", "Ad Camera cut", "Ad Camera scrap that", "Ad Camera keep", "Ad Camera next line", "Ad Camera last line", "Ad Camera teleprompter on", "Ad Camera teleprompter off"]
            request = req
            let input = engine.inputNode
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { [weak req] buf, _ in
                req?.append(buf)
            }
            engine.prepare()
            if !engine.isRunning { try engine.start() }
            listening = true
            problem = nil
            task = rec.recognitionTask(with: req) { [weak self] result, error in
                guard let self else { return }
                let text = result?.bestTranscription.formattedString ?? ""
                let final = result?.isFinal ?? false
                Task { @MainActor in
                    if !text.isEmpty { self.check(text) }
                    if error != nil || final { self.restart(after: 0.3) }
                }
            }
            // recognition tasks are meant to be short: start a fresh one every 50 s
            restartTimer?.invalidate()
            restartTimer = Timer.scheduledTimer(withTimeInterval: 50, repeats: false) { [weak self] _ in
                Task { @MainActor in self?.restart(after: 0) }
            }
        } catch {
            problem = error.localizedDescription
            listening = false
            restart(after: 3)
        }
    }

    private func restart(after secs: Double) {
        guard running else { return }
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + secs) { [weak self] in self?.begin() }
    }

    /// Looks at the end of what's been heard so far for "Ad Camera" + one of the commands.
    private func check(_ text: String) {
        let letters = text.lowercased().unicodeScalars.map { CharacterSet.letters.contains($0) ? Character($0) : " " }
        let w = String(letters).split(separator: " ").suffix(6).map(String.init)
        guard Date().timeIntervalSince(lastFire) > 1.5,
              let cam = w.lastIndex(where: { $0 == "camera" || $0 == "cameras" }), cam > 0,
              ["ad", "add", "at", "and"].contains(w[cam - 1]) else { return }
        let rest = Array(w[(cam + 1)...])
        for c in commands where c.when() {
            if c.phrases.contains(where: { $0 == rest }) {
                fire(c.label, c.run)
                return
            }
        }
    }

    private func fire(_ word: String, _ handler: (() -> Void)?) {
        lastFire = Date()
        heard = word
        handler?()
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        restart(after: 0.2)   // a fresh task, so the same words can't trigger twice
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { [weak self] in
            if self?.heard == word { self?.heard = nil }
        }
    }
}

/// The little "listening" badge on the viewfinder; shows the command for a moment when heard.
struct VoiceBadge: View {
    @ObservedObject var voice: VoiceControl
    var body: some View {
        if let p = voice.problem {
            Label(p, systemImage: "mic.slash").font(.caption).padding(.horizontal, 10).padding(.vertical, 6)
                .background(.black.opacity(0.6), in: Capsule())
        } else if voice.listening {
            HStack(spacing: 6) {
                Image(systemName: voice.heard == nil ? "waveform" : "checkmark.circle.fill")
                Text(voice.heard.map { LocalizedStringKey($0) } ?? "Say “Ad Camera, action”")
            }
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background((voice.heard == nil ? Color.black.opacity(0.45) : Color.blue.opacity(0.85)), in: Capsule())
            .animation(.easeInOut(duration: 0.2), value: voice.heard)
        }
    }
}
