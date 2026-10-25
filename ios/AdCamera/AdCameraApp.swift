import SwiftUI

/// Ad Camera: films TikTok Shop videos straight into an Ad Factory project. Every take is
/// saved to the "Ad Studio" album in Photos and uploaded into the project's own OneDrive
/// inbox folder (through Ad Factory), where it gets pre-cut like any other drop.
@main
struct AdCameraApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()
    @StateObject private var clips = ClipStore.shared
    @Environment(\.scenePhase) private var phase

    init() {
        Prefs.register()
    }

    var body: some Scene {
        WindowGroup {
            ProjectsView()
                .environmentObject(model)
                .environmentObject(clips)
                .preferredColorScheme(.dark)
                .onChange(of: phase) { _, now in
                    if now == .active {
                        clips.retryWaiting()
                        Task { await model.refresh() }
                    }
                }
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    /// Uploads keep going after the app is closed; iOS wakes the app when they finish.
    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        ClipStore.shared.backgroundDone = completionHandler
    }
}

/// Settings keys and their defaults (the TikTok defaults live here).
enum Prefs {
    static func register() {
        UserDefaults.standard.register(defaults: [
            "res": "4k",           // 4K vertical: room to crop/zoom in the editor; renders are 1080x1920
            "fps": 30,             // what TikTok plays
            "codec": "hevc",       // half the size of H.264 at the same quality
            "stab": "standard",
            "mirror": false,       // front camera unmirrored, so product labels read the right way
            "lockWB": true,        // colour can't drift in the middle of a take
            "countdown": 0,
            "zones": true,
            "grid": false,
            "prompter": true,
            "prompterSize": 26.0,
            "cellular": true,
            "camera": "back",      // the back camera films (better lens and sensor); flip stays available
            "layout": "handheld",  // or "tripod": dead strip under the clamp, picture shrunk, controls beside it
            "tripodCountdown": 3,
            "tripodPrompter": false,
            "clampTop": false,
            "clampH": 160.0,       // about an inch
            "clampSet": false,
        ])
    }

    static func resetCamera() {
        for k in ["res", "fps", "codec", "stab", "mirror", "lockWB", "camera"] {
            UserDefaults.standard.removeObject(forKey: k)
        }
    }
}
