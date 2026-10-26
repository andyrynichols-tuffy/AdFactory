import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @AppStorage("server") private var server = Server.defaultAddress
    @AppStorage("res") private var res = "4k"
    @AppStorage("fps") private var fps = 30
    @AppStorage("codec") private var codec = "hevc"
    @AppStorage("stab") private var stab = "standard"
    @AppStorage("mirror") private var mirror = false
    @AppStorage("lockWB") private var lockWB = true
    @AppStorage("countdown") private var countdown = 0
    @AppStorage("zones") private var zones = true
    @AppStorage("grid") private var grid = false
    @AppStorage("prompterSize") private var prompterSize = 26.0
    @AppStorage("cellular") private var cellular = true
    @AppStorage("tripodCountdown") private var tripodCountdown = 3
    @AppStorage("tripodPrompter") private var tripodPrompter = false
    @AppStorage("warnMic") private var warnMic = true

    @State private var password = ""
    @State private var busy = false
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Address", text: $server)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    if model.signedIn {
                        Label("Signed in", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                        Button("Sign out", role: .destructive) { model.signOut() }
                    } else {
                        SecureField("Ad Factory password", text: $password)
                            .textContentType(.password)
                        Button { signIn() } label: {
                            if busy { ProgressView() } else { Text("Sign in") }
                        }
                        .disabled(password.isEmpty || busy)
                    }
                    if let problem {
                        Text(verbatim: problem).foregroundStyle(.red)
                    }
                } header: {
                    Text("Ad Factory")
                } footer: {
                    Text("The same password as the Ad Factory web link. The phone reaches the PC through the Tailscale app, so keep it switched on.")
                }

                Section {
                    Picker("Resolution", selection: $res) {
                        Text("4K").tag("4k")
                        Text("1080p").tag("1080")
                    }
                    Picker("Frame rate", selection: $fps) {
                        Text("24 fps").tag(24)
                        Text("30 fps").tag(30)
                        Text("60 fps").tag(60)
                    }
                    Picker("Video format", selection: $codec) {
                        Text("HEVC (smaller files)").tag("hevc")
                        Text("H.264 (most compatible)").tag("h264")
                    }
                    Picker("Stabilization", selection: $stab) {
                        Text("Standard").tag("standard")
                        Text("Cinematic (smoother, crops more)").tag("cinematic")
                        Text("Off").tag("off")
                    }
                    Toggle("Mirror the front camera", isOn: $mirror)
                    Toggle("Hold white balance during a take", isOn: $lockWB)
                    Button("Back to the TikTok defaults") { Prefs.resetCamera() }
                } header: {
                    Text("Camera")
                } footer: {
                    Text("Set for TikTok: vertical 4K at 30 fps, SDR (HDR is always off: HDR uploads look washed out on TikTok). 4K leaves room to crop and zoom in the editor. The front camera records unmirrored so product labels read the right way.")
                }

                Section {
                    Picker("Countdown", selection: $countdown) {
                        Text("Off").tag(0)
                        Text("3 s").tag(3)
                        Text("5 s").tag(5)
                        Text("10 s").tag(10)
                    }
                    Toggle("TikTok screen guides", isOn: $zones)
                    Toggle("Grid", isOn: $grid)
                    VStack(alignment: .leading) {
                        Text("Teleprompter text size")
                        Slider(value: $prompterSize, in: 14...64, step: 1)
                    }
                    Toggle("Warn when the external mic isn't plugged in", isOn: $warnMic)
                } header: {
                    Text("Filming")
                } footer: {
                    Text("Tap the picture to focus there; hold to lock focus and brightness. Pinch to zoom. The volume buttons start and stop recording. Drag the teleprompter to move it, drag its corner to make it wider, pinch it to change the text size. Takes that come out with no sound are flagged right away.")
                }

                Section {
                    Picker("Countdown", selection: $tripodCountdown) {
                        Text("Off").tag(0)
                        Text("3 s").tag(3)
                        Text("5 s").tag(5)
                        Text("10 s").tag(10)
                    }
                    Toggle("Teleprompter", isOn: $tripodPrompter)
                } header: {
                    Text("Tripod clamp")
                } footer: {
                    Text("Switch to it with the layout button on the camera screen: back camera, a strip left clear where the clamp covers the screen, the picture shrunk to fit, controls beside it. In it, \"Clamp\" moves the strip and \"Handheld\" switches back.")
                }

                Section {
                    Toggle("Upload over cellular", isOn: $cellular)
                } header: {
                    Text("Uploads")
                } footer: {
                    Text("Every take also saves to the \"Ad Studio\" album in Photos. Uploads go into the project's OneDrive folder and keep going with the phone locked.")
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func signIn() {
        busy = true
        problem = nil
        Task { @MainActor in
            do {
                try await model.signIn(password)
                password = ""
            } catch {
                problem = error.localizedDescription
            }
            busy = false
        }
    }
}
