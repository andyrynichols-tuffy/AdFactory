import Foundation
import WatchConnectivity

/// The iPhone side of the Apple Watch remote (ios/AdCameraWatch): the watch sends "start" / "stop",
/// the phone sends back what's happening (filming or not, which project, how long, how many takes).
/// Works with the phone on a tripod across the room; without a paired watch it simply does nothing.
@MainActor
final class WatchLink: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchLink()
    @Published var reachable = false
    /// set by the camera screen while it's open; nil = no camera open, the watch shows "open a project"
    var onCommand: ((String) -> Void)?

    func activate() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    /// Tell the watch the current state (kept as the latest "application context", so it's there
    /// the moment the watch app opens, and sent live when the watch is awake).
    func send(recording: Bool, project: String?, started: Date?, takes: Int, counting: Int?) {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated else { return }
        var s: [String: Any] = ["recording": recording, "takes": takes, "open": project != nil, "at": Date().timeIntervalSince1970]
        if let project { s["project"] = project }
        if let started { s["started"] = started.timeIntervalSince1970 }
        if let counting { s["counting"] = counting }
        try? WCSession.default.updateApplicationContext(s)
        if WCSession.default.isReachable { WCSession.default.sendMessage(s, replyHandler: nil) }
    }

    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        Task { @MainActor in self.reachable = session.isReachable }
    }
    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.reachable = session.isReachable }
    }
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) { session.activate() }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        let cmd = message["cmd"] as? String ?? ""
        Task { @MainActor in
            if let handler = self.onCommand { handler(cmd); replyHandler(["ok": true]) }
            else { replyHandler(["ok": false, "why": "Open a project in Ad Camera on the iPhone first."]) }
        }
    }
}
