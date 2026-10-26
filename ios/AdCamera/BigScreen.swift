import AVFoundation
import SwiftUI

/// What the big screen shows: a TV through an Apple TV, a Mac (AirPlay Receiver) or a monitor
/// on a cable. When the phone mirrors to one, iOS gives the app a second window there
/// (BigScreenSceneDelegate) and it shows its own layout instead of a copy of the phone:
/// the camera picture beside the script in big type. The camera screen fills this in.
@MainActor
final class BigScreen: ObservableObject {
    static let shared = BigScreen()

    @Published var connected = false
    @Published var camera: CameraController?
    @Published var project: Project?
    @Published var line = 0
    @Published var counting: Int?
    @Published var zones: [String: [Double]] = Catalog.defaultZones
    @Published var safe: [Double] = Catalog.defaultSafe
    @Published var showZones = true
}

/// The window on the big screen (iOS asks for it when one connects; AppDelegate picks this).
final class BigScreenSceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let ws = scene as? UIWindowScene else { return }
        let w = UIWindow(windowScene: ws)
        let host = UIHostingController(rootView: BigScreenView(big: BigScreen.shared))
        host.view.backgroundColor = .black
        w.rootViewController = host
        w.overrideUserInterfaceStyle = .dark
        w.isHidden = false
        window = w
        BigScreen.shared.connected = true
    }

    func sceneDidDisconnect(_ scene: UIScene) {
        window = nil
        BigScreen.shared.connected = false
    }
}

struct BigScreenView: View {
    @ObservedObject var big: BigScreen

    var body: some View {
        GeometryReader { g in
            let pad = g.size.height * 0.05
            if let camera = big.camera, let project = big.project {
                HStack(alignment: .top, spacing: pad) {
                    ZStack {
                        BigCameraPreview(camera: camera)
                        Guides(zones: big.zones, safe: big.safe, showZones: big.showZones, showGrid: false)
                            .allowsHitTesting(false)
                        if let n = big.counting {
                            Text(verbatim: "\(n)")
                                .font(.system(size: g.size.height * 0.3, weight: .heavy, design: .rounded))
                                .shadow(radius: 12)
                        }
                    }
                    .aspectRatio(9 / 16, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: g.size.height * 0.015))
                    BigScript(camera: camera, project: project, line: big.line, height: g.size.height)
                }
                .padding(pad)
            } else {
                VStack(spacing: g.size.height * 0.03) {
                    Image(systemName: "video.fill")
                        .font(.system(size: g.size.height * 0.1))
                        .foregroundStyle(Color.accentColor)
                    Text("Ad Camera").font(.system(size: g.size.height * 0.07, weight: .bold))
                    Text("Open a project on the phone and tap Film: the camera and the script show up here.")
                        .font(.system(size: g.size.height * 0.035))
                        .multilineTextAlignment(.center)
                        .opacity(0.7)
                        .frame(maxWidth: g.size.width * 0.6)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Color.black)
        .foregroundStyle(.white)
    }
}

/// The script beside the picture: the line to say in big type, the next one under it, and
/// whether it's recording.
private struct BigScript: View {
    @ObservedObject var camera: CameraController
    let project: Project
    let line: Int
    let height: CGFloat

    var body: some View {
        let lines = project.lines
        let i = max(0, min(line, lines.count - 1))
        VStack(alignment: .leading, spacing: height * 0.03) {
            HStack(spacing: height * 0.02) {
                if let s = camera.started {
                    HStack(spacing: height * 0.012) {
                        Circle().fill(.red).frame(width: height * 0.025, height: height * 0.025)
                        Text(s, style: .timer).monospacedDigit()
                    }
                    .font(.system(size: height * 0.04, weight: .bold))
                    .padding(.horizontal, height * 0.025).padding(.vertical, height * 0.01)
                    .background(Color.red.opacity(0.25), in: Capsule())
                }
                Text(verbatim: project.title)
                    .font(.system(size: height * 0.035, weight: .semibold))
                    .lineLimit(1)
                    .opacity(0.6)
            }
            if camera.micOff || camera.silent {
                Text(camera.micOff ? "The microphone is off for Ad Camera, so videos won't have sound."
                                   : "No sound coming in. Is the mic's transmitter on?")
                    .font(.system(size: height * 0.035, weight: .bold))
                    .padding(height * 0.02)
                    .background(Color.red.opacity(0.85), in: RoundedRectangle(cornerRadius: height * 0.015))
            }
            if lines.isEmpty {
                Spacer()
                Text("No script for this project.").font(.system(size: height * 0.05)).opacity(0.6)
                Spacer()
            } else {
                Text("Line \(i + 1) of \(lines.count)")
                    .font(.system(size: height * 0.035, weight: .semibold))
                    .opacity(0.6)
                Text(verbatim: lines[i])
                    .font(.system(size: height * 0.075, weight: .bold))
                    .minimumScaleFactor(0.4)
                    .lineSpacing(height * 0.01)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if i + 1 < lines.count {
                    Text(verbatim: lines[i + 1])
                        .font(.system(size: height * 0.045))
                        .minimumScaleFactor(0.5)
                        .lineLimit(3)
                        .opacity(0.45)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

/// A second live picture from the same camera, for the big screen (no gestures: it's a TV).
struct BigCameraPreview: UIViewRepresentable {
    let camera: CameraController

    func makeUIView(context: Context) -> BigPreviewView {
        let v = BigPreviewView()
        v.previewLayer.videoGravity = .resizeAspectFill
        camera.attachBig(v.previewLayer)
        return v
    }

    func updateUIView(_ v: BigPreviewView, context: Context) {}

    static func dismantleUIView(_ v: BigPreviewView, coordinator: ()) {
        v.previewLayer.session = nil
    }
}

final class BigPreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = UIColor(white: 0.08, alpha: 1)   // the frame shows before the picture does
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func layoutSubviews() {
        super.layoutSubviews()
        if let c = previewLayer.connection, c.isVideoRotationAngleSupported(90) { c.videoRotationAngle = 90 }
    }
}
