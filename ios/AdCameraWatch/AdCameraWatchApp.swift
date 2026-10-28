import SwiftUI
import WatchConnectivity
import WatchKit

/// Ad Camera's Apple Watch remote (user, 2026-10-27): one big button to start and stop a take on the
/// iPhone (camera on a tripod, you in frame), the running time, and how many takes are in.
/// Talks to the phone through WatchConnectivity (ios/AdCamera/WatchLink.swift).
@main
struct AdCameraWatchApp: App {
    @StateObject private var link = PhoneLink()
    var body: some Scene {
        WindowGroup { RemoteView().environmentObject(link) }
    }
}

@MainActor
final class PhoneLink: NSObject, ObservableObject, WCSessionDelegate {
    @Published var recording = false
    @Published var open = false          // a project is open in the camera on the phone
    @Published var project = ""
    @Published var started: Date?
    @Published var takes = 0
    @Published var counting: Int?
    @Published var reachable = false
    @Published var problem: String?

    override init() {
        super.init()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
    }

    func toggle() {
        guard WCSession.default.isReachable else {
            problem = String(localized: "Open Ad Camera on the iPhone")
            return
        }
        let cmd = recording || counting != nil ? "stop" : "start"
        WKInterfaceDevice.current().play(cmd == "start" ? .start : .stop)
        WCSession.default.sendMessage(["cmd": cmd], replyHandler: { reply in
            let why = reply["why"] as? String
            Task { @MainActor in self.problem = why }
        }, errorHandler: { err in
            Task { @MainActor in self.problem = err.localizedDescription }
        })
    }

    private func apply(_ s: [String: Any]) {
        recording = s["recording"] as? Bool ?? false
        open = s["open"] as? Bool ?? false
        project = s["project"] as? String ?? ""
        started = (s["started"] as? Double).map { Date(timeIntervalSince1970: $0) }
        takes = s["takes"] as? Int ?? 0
        counting = s["counting"] as? Int
        if open { problem = nil }
    }

    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        let ctx = session.receivedApplicationContext, r = session.isReachable
        Task { @MainActor in self.apply(ctx); self.reachable = r }
    }
    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        let r = session.isReachable
        Task { @MainActor in self.reachable = r }
    }
    nonisolated func session(_ session: WCSession, didReceiveApplicationContext ctx: [String: Any]) {
        Task { @MainActor in self.apply(ctx) }
    }
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor in self.apply(message) }
    }
}

struct RemoteView: View {
    @EnvironmentObject private var link: PhoneLink

    var body: some View {
        VStack(spacing: 8) {
            Text(link.open ? link.project : String(localized: "Open a project on the iPhone"))
                .font(.footnote).foregroundStyle(.secondary).lineLimit(2).multilineTextAlignment(.center)
            Button(action: link.toggle) {
                ZStack {
                    Circle().stroke(.white.opacity(0.9), lineWidth: 4)
                    if let n = link.counting {
                        Text("\(n)").font(.system(size: 44, weight: .bold, design: .rounded))
                    } else if link.recording {
                        RoundedRectangle(cornerRadius: 8).fill(.red).frame(width: 46, height: 46)
                    } else {
                        Circle().fill(.red).padding(10)
                    }
                }
                .frame(width: 112, height: 112)
            }
            .buttonStyle(.plain)
            .disabled(!link.open)
            .opacity(link.open ? 1 : 0.4)
            if link.recording, let started = link.started {
                Text(started, style: .timer).font(.headline.monospacedDigit()).foregroundStyle(.red)
            } else {
                Text("\(link.takes) takes").font(.footnote).foregroundStyle(.secondary)
            }
            if let p = link.problem { Text(p).font(.caption2).foregroundStyle(.orange).multilineTextAlignment(.center) }
        }
        .padding(.horizontal, 6)
    }
}
