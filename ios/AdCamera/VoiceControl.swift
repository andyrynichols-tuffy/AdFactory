import AVFoundation
import Speech
import SwiftUI

/// Hands-free filming (user, 2026-10-27): say "Ad Camera, action" to start a take and "Ad Camera, cut"
/// to stop it. Listens with on-device speech recognition (no audio leaves the phone when the phone
/// supports it) through the same mic the camera records with.
///
/// Only the two full phrases count ("Ad Camera action" / "Ad Camera cut"), so a script
/// line that says "cut" or "action" never stops a take. "Action" goes through the normal record button
/// path, so the countdown setting still applies (handy for getting into position). The spoken "cut"
/// lands after the last script line, where pre-cutting in Ad Factory leaves it out anyway.
@MainActor
final class VoiceControl: ObservableObject {
    @Published var listening = false
    @Published var problem: String?
    @Published var heard: String?          // "Action" / "Cut", shown for a moment

    private let engine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var onAction: (() -> Void)?
    private var onCut: (() -> Void)?
    private var restartTimer: Timer?
    private var lastFire = Date.distantPast
    private var running = false

    static var enabled: Bool { UserDefaults.standard.object(forKey: "voiceControl") as? Bool ?? true }

    func start(action: @escaping () -> Void, cut: @escaping () -> Void) {
        onAction = action
        onCut = cut
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
            req.contextualStrings = ["Ad Camera action", "Ad Camera cut"]
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

    /// Looks at the end of what's been heard so far for one of the two phrases.
    private func check(_ text: String) {
        let words = text.lowercased().unicodeScalars.map { CharacterSet.letters.contains($0) ? Character($0) : " " }
        let w = String(words).split(separator: " ").suffix(3).map(String.init)
        guard w.count == 3, Date().timeIntervalSince(lastFire) > 1.5 else { return }
        // the whole phrase, "Ad Camera …": "cut" alone is everywhere in clothing scripts ("the cut on these")
        guard ["ad", "add", "at", "and"].contains(w[0]), ["camera", "cameras"].contains(w[1]) else { return }
        if ["action", "actions"].contains(w[2]) {
            fire("Action", onAction)
        } else if ["cut", "cuts", "cart", "kut"].contains(w[2]) {
            fire("Cut", onCut)
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
