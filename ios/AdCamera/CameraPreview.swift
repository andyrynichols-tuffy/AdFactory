import AVFoundation
import AVKit
import SwiftUI

/// The live picture. Tap = focus/expose there; long press = lock them (AE/AF LOCK);
/// pinch = zoom; the volume buttons (and Camera Control) start and stop recording.
struct CameraPreview: UIViewRepresentable {
    let camera: CameraController
    var shutter: () -> Void

    func makeUIView(context: Context) -> PreviewView {
        let v = PreviewView()
        v.previewLayer.session = camera.session
        v.previewLayer.videoGravity = .resizeAspectFill
        camera.preview = v.previewLayer
        v.onFocus = { [weak camera] point, hold in camera?.focus(at: point, hold: hold) }
        let coordinator = context.coordinator
        v.onPinch = { [weak camera] scale, state in
            guard let camera else { return }
            if state == .began { coordinator.startZoom = camera.zoom }
            camera.setZoom(coordinator.startZoom * scale)
        }
        v.onShutter = shutter
        return v
    }

    func updateUIView(_ v: PreviewView, context: Context) {
        v.onShutter = shutter
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        var startZoom: CGFloat = 1
    }
}

final class PreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

    var onFocus: ((CGPoint, Bool) -> Void)?
    var onPinch: ((CGFloat, UIGestureRecognizer.State) -> Void)?
    var onShutter: (() -> Void)?
    private let ring = UIView()

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .black
        addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(tapped)))
        addGestureRecognizer(UILongPressGestureRecognizer(target: self, action: #selector(held)))
        addGestureRecognizer(UIPinchGestureRecognizer(target: self, action: #selector(pinched)))
        ring.frame = CGRect(x: 0, y: 0, width: 76, height: 76)
        ring.layer.borderWidth = 1.5
        ring.layer.borderColor = UIColor.systemYellow.cgColor
        ring.alpha = 0
        ring.isUserInteractionEnabled = false
        addSubview(ring)
        if #available(iOS 17.2, *) {
            addInteraction(AVCaptureEventInteraction { [weak self] event in
                if event.phase == .ended { self?.onShutter?() }
            })
        }
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func layoutSubviews() {
        super.layoutSubviews()
        if let c = previewLayer.connection, c.isVideoRotationAngleSupported(90) { c.videoRotationAngle = 90 }
    }

    @objc private func tapped(_ g: UITapGestureRecognizer) {
        let p = g.location(in: self)
        onFocus?(previewLayer.captureDevicePointConverted(fromLayerPoint: p), false)
        showRing(at: p, locked: false)
    }

    @objc private func held(_ g: UILongPressGestureRecognizer) {
        guard g.state == .began else { return }
        let p = g.location(in: self)
        onFocus?(previewLayer.captureDevicePointConverted(fromLayerPoint: p), true)
        showRing(at: p, locked: true)
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }

    @objc private func pinched(_ g: UIPinchGestureRecognizer) {
        onPinch?(g.scale, g.state)
    }

    private func showRing(at p: CGPoint, locked: Bool) {
        ring.center = p
        ring.transform = CGAffineTransform(scaleX: 1.4, y: 1.4)
        ring.alpha = 1
        UIView.animate(withDuration: 0.25) { self.ring.transform = .identity }
        UIView.animate(withDuration: 0.4, delay: locked ? 2.0 : 0.9, options: []) { self.ring.alpha = 0 }
    }
}
