import AVFoundation
import UIKit

/// The capture session, set up for TikTok: vertical, SDR (HDR off), 4K or 1080p at a fixed
/// frame rate, smooth autofocus, white balance held during a take, front camera unmirrored.
final class CameraController: NSObject, ObservableObject, AVCaptureFileOutputRecordingDelegate, AVCapturePhotoCaptureDelegate {
    let session = AVCaptureSession()
    weak var preview: AVCaptureVideoPreviewLayer?
    weak var bigPreview: AVCaptureVideoPreviewLayer?   // the same picture on a TV / Mac (BigScreen)

    @Published var position: AVCaptureDevice.Position =
        UserDefaults.standard.string(forKey: "camera") == "back" ? .back : .front
    @Published var recording = false
    @Published var started: Date?
    @Published var summary = ""          // "4K · 30 fps · SDR · HEVC"
    @Published var problem: String?
    @Published var mic = ""
    @Published var level: Float = 0      // 0...1
    @Published var micOff = false        // no mic permission / no audio input: videos would be silent
    @Published var silent = false        // recording, but nothing coming in (lav transmitter off?)
    @Published var externalExpected = false   // on the iPhone's own mic, though an external one was used before
    @Published var externalName = ""     // the external mic last seen (e.g. the Maono receiver)
    private var silentSince: Date?
    @Published var locked = false        // focus + exposure held (long press)
    @Published var bias: Float = 0
    @Published var zoom: CGFloat = 1
    @Published var maxZoom: CGFloat = 1

    private let queue = DispatchQueue(label: "adcamera.session")
    private let output = AVCaptureMovieFileOutput()
    private let photoOutput = AVCapturePhotoOutput()   // carousel mode (CarouselView)
    private var photoDone: ((Data?) -> Void)?
    private var device: AVCaptureDevice?
    private var videoInput: AVCaptureDeviceInput?
    private var audioInput: AVCaptureDeviceInput?
    private var levelTimer: Timer?
    private var finished: ((URL, Double) -> Void)?
    private var observing = false

    struct Config {
        var fourK = true
        var fps = 30
        var hevc = true
        var stabilization = AVCaptureVideoStabilizationMode.standard
        var mirrorFront = false
        var lockWhiteBalance = true

        static func current() -> Config {
            let d = UserDefaults.standard
            var c = Config()
            c.fourK = d.string(forKey: "res") != "1080"
            c.fps = d.integer(forKey: "fps") > 0 ? d.integer(forKey: "fps") : 30
            c.hevc = d.string(forKey: "codec") != "h264"
            switch d.string(forKey: "stab") {
            case "cinematic": c.stabilization = .cinematic
            case "off": c.stabilization = .off
            default: c.stabilization = .standard
            }
            c.mirrorFront = d.bool(forKey: "mirror")
            c.lockWhiteBalance = d.bool(forKey: "lockWB")
            return c
        }
    }

    // MARK: - start / stop

    func start() {
        if !observing {
            observing = true
            NotificationCenter.default.addObserver(self, selector: #selector(routeChanged),
                                                   name: AVAudioSession.routeChangeNotification, object: nil)
        }
        let pos = position
        Task {
            let cam = await AVCaptureDevice.requestAccess(for: .video)
            let mic = await AVCaptureDevice.requestAccess(for: .audio)
            guard cam else {
                await MainActor.run {
                    self.problem = String(localized: "Ad Camera needs the camera. Allow it in the iPhone's Settings.")
                }
                return
            }
            await MainActor.run { self.micOff = !mic }
            self.queue.async {
                self.configure(position: pos, audio: mic)
                if !self.session.isRunning { self.session.startRunning() }
                DispatchQueue.main.async { self.updateMic() }
            }
        }
        levelTimer?.invalidate()
        levelTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            guard let self else { return }
            guard let ch = self.output.connection(with: .audio)?.audioChannels.first else {
                self.level = 0
                return
            }
            let db = ch.averagePowerLevel
            self.level = max(0, min(1, (db + 50) / 50))   // -50...0 dB
            // A wireless lav whose transmitter is off sends dead digital silence, far below any
            // room noise. Only judged while recording, when sound is surely flowing.
            if self.recording && !(db > -70) {
                let since = self.silentSince ?? Date()
                self.silentSince = since
                if Date().timeIntervalSince(since) > 2 && !self.silent { self.silent = true }
            } else {
                self.silentSince = nil
                if self.silent { self.silent = false }
            }
        }
    }

    func stop() {
        levelTimer?.invalidate()
        levelTimer = nil
        queue.async {
            if self.output.isRecording { self.output.stopRecording() }
            if self.session.isRunning { self.session.stopRunning() }
        }
    }

    /// Settings changed: set the camera up again (not while recording).
    func reconfigure() {
        guard !recording else { return }
        let pos = position
        let audio = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        queue.async { self.configure(position: pos, audio: audio) }
    }

    /// remember = make it the handheld layout's camera (the tripod layout always starts on the back one).
    func flip(remember: Bool = true) {
        guard !recording else { return }
        position = position == .front ? .back : .front
        if remember { UserDefaults.standard.set(position == .back ? "back" : "front", forKey: "camera") }
        reconfigure()
    }

    func use(_ pos: AVCaptureDevice.Position) {
        guard !recording, pos != position else { return }
        position = pos
        reconfigure()
    }

    // MARK: - setup (on the session queue)

    private func configure(position pos: AVCaptureDevice.Position, audio: Bool) {
        let config = Config.current()
        session.beginConfiguration()
        session.automaticallyConfiguresCaptureDeviceForWideColor = false   // we pick SDR ourselves
        // voice control (VoiceControl.swift) listens on the same mic: keep the app's audio session
        // (play-and-record, mix with others) instead of letting capture take the mic for itself
        session.usesApplicationAudioSession = true
        session.automaticallyConfiguresApplicationAudioSession = !VoiceControl.enabled

        if let v = videoInput {
            session.removeInput(v)
            videoInput = nil
        }
        guard let dev = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: pos),
              let input = try? AVCaptureDeviceInput(device: dev), session.canAddInput(input) else {
            session.commitConfiguration()
            report(String(localized: "Couldn't open that camera."))
            return
        }
        session.addInput(input)
        videoInput = input
        device = dev

        if audio, audioInput == nil, let micDevice = AVCaptureDevice.default(for: .audio),
           let a = try? AVCaptureDeviceInput(device: micDevice), session.canAddInput(a) {
            session.addInput(a)
            audioInput = a
        }
        let noAudio = audioInput == nil
        DispatchQueue.main.async { self.micOff = noAudio }
        if !session.outputs.contains(output), session.canAddOutput(output) {
            session.addOutput(output)
        }
        if !session.outputs.contains(photoOutput), session.canAddOutput(photoOutput) {
            session.addOutput(photoOutput)
            photoOutput.maxPhotoQualityPrioritization = .quality
        }

        let want = Double(config.fps)
        let format = Self.format(dev, width: config.fourK ? 3840 : 1920, fps: want)
            ?? Self.format(dev, width: 1920, fps: want)
            ?? Self.format(dev, width: 1920, fps: 30)
        var fps = 30
        do {
            try dev.lockForConfiguration()
            if let format { dev.activeFormat = format }
            if dev.activeFormat.supportedColorSpaces.contains(.sRGB) {
                dev.activeColorSpace = .sRGB   // SDR: HDR uploads look washed out on TikTok
            }
            if dev.activeFormat.isVideoHDRSupported {
                dev.automaticallyAdjustsVideoHDREnabled = false
                dev.isVideoHDREnabled = false
            }
            let top = dev.activeFormat.videoSupportedFrameRateRanges.map(\.maxFrameRate).max() ?? 30
            fps = Int(min(want, top))
            dev.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CMTimeScale(fps))
            dev.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CMTimeScale(fps))
            if dev.isFocusModeSupported(.continuousAutoFocus) { dev.focusMode = .continuousAutoFocus }
            if dev.isSmoothAutoFocusSupported { dev.isSmoothAutoFocusEnabled = true }   // no focus jumps mid-take
            if dev.isExposureModeSupported(.continuousAutoExposure) { dev.exposureMode = .continuousAutoExposure }
            if dev.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                dev.whiteBalanceMode = .continuousAutoWhiteBalance
            }
            dev.automaticallyAdjustsFaceDrivenAutoExposureEnabled = true
            dev.automaticallyAdjustsFaceDrivenAutoFocusEnabled = true
            dev.setExposureTargetBias(0, completionHandler: nil)
            dev.videoZoomFactor = 1
            dev.unlockForConfiguration()
        } catch {
            report(error.localizedDescription)
        }

        var codec = AVVideoCodecType.h264
        if let c = output.connection(with: .video) {
            if c.isVideoRotationAngleSupported(90) { c.videoRotationAngle = 90 }   // portrait
            if c.isVideoStabilizationSupported { c.preferredVideoStabilizationMode = config.stabilization }
            if c.isVideoMirroringSupported {
                c.automaticallyAdjustsVideoMirroring = false
                c.isVideoMirrored = pos == .front && config.mirrorFront
            }
            if config.hevc && output.availableVideoCodecTypes.contains(.hevc) { codec = .hevc }
            output.setOutputSettings([AVVideoCodecKey: codec], for: c)
        }
        session.commitConfiguration()

        let dims = CMVideoFormatDescriptionGetDimensions(dev.activeFormat.formatDescription)
        let res = dims.width >= 3840 ? "4K" : "\(min(dims.width, dims.height))p"
        let text = "\(res) · \(fps) fps · SDR · \(codec == .hevc ? "HEVC" : "H.264")"
        let top = min(dev.activeFormat.videoMaxZoomFactor, 5)
        DispatchQueue.main.async {
            self.summary = text
            self.maxZoom = top
            self.zoom = 1
            self.bias = 0
            self.locked = false
            for layer in [self.preview, self.bigPreview] {
                if let c = layer?.connection, c.isVideoRotationAngleSupported(90) { c.videoRotationAngle = 90 }
            }
        }
    }

    /// The big screen's picture: a second preview of the same session. If that ever takes the
    /// phone's own picture away, the phone gets it back and the big screen does without.
    func attachBig(_ layer: AVCaptureVideoPreviewLayer) {
        layer.session = session
        bigPreview = layer
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self, weak layer] in
            guard let self, let layer, let phone = self.preview else { return }
            if phone.connection == nil, layer.connection != nil {
                layer.session = nil
                phone.session = nil
                phone.session = self.session
            }
        }
    }

    /// The best 16:9 SDR format at this width and frame rate: 8-bit video range first (what
    /// phones and TikTok expect), not pixel-binned, with cinematic stabilization if possible.
    private static func format(_ dev: AVCaptureDevice, width: Int32, fps: Double) -> AVCaptureDevice.Format? {
        let ok = dev.formats.filter { f in
            let d = CMVideoFormatDescriptionGetDimensions(f.formatDescription)
            let sub = CMFormatDescriptionGetMediaSubType(f.formatDescription)
            return d.width == width && d.height == width * 9 / 16
                && (sub == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
                    || sub == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
                && f.videoSupportedFrameRateRanges.contains { $0.minFrameRate <= fps && fps <= $0.maxFrameRate }
                && f.supportedColorSpaces.contains(.sRGB)
        }
        func rank(_ f: AVCaptureDevice.Format) -> Int {
            var r = 0
            if CMFormatDescriptionGetMediaSubType(f.formatDescription) == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange { r += 4 }
            if !f.isVideoBinned { r += 2 }
            if f.isVideoStabilizationModeSupported(.cinematic) { r += 1 }
            return r
        }
        return ok.max { rank($0) < rank($1) }
    }

    private func report(_ text: String) {
        DispatchQueue.main.async { self.problem = text }
    }

    // MARK: - recording

    func record(to url: URL, done: @escaping (URL, Double) -> Void) {
        guard !recording else { return }
        finished = done
        recording = true
        started = Date()
        let holdWB = Config.current().lockWhiteBalance
        queue.async {
            if holdWB, let d = self.device, d.isWhiteBalanceModeSupported(.locked), (try? d.lockForConfiguration()) != nil {
                d.whiteBalanceMode = .locked   // colour can't drift mid-take
                d.unlockForConfiguration()
            }
            self.output.startRecording(to: url, recordingDelegate: self)
        }
    }

    /// One still for a carousel (HEIC when the phone can, else JPEG), straight from the live session.
    func takePhoto(done: @escaping (Data?) -> Void) {
        queue.async {
            guard !self.output.isRecording else { return DispatchQueue.main.async { done(nil) } }
            self.photoDone = done
            let fmt: [String: Any] = self.photoOutput.availablePhotoCodecTypes.contains(.hevc)
                ? [AVVideoCodecKey: AVVideoCodecType.hevc] : [AVVideoCodecKey: AVVideoCodecType.jpeg]
            let s = AVCapturePhotoSettings(format: fmt)
            s.photoQualityPrioritization = .balanced
            if let c = self.photoOutput.connection(with: .video), c.isVideoRotationAngleSupported(90) {
                c.videoRotationAngle = 90   // portrait, like the takes
            }
            self.photoOutput.capturePhoto(with: s, delegate: self)
        }
    }

    func stopRecording() {
        queue.async {
            if self.output.isRecording { self.output.stopRecording() }
        }
    }

    func fileOutput(_ output: AVCaptureFileOutput, didFinishRecordingTo url: URL,
                    from connections: [AVCaptureConnection], error: Error?) {
        let secs = output.recordedDuration.seconds
        let ok = error == nil
            || ((error as NSError?)?.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool ?? false)
        let exists = FileManager.default.fileExists(atPath: url.path)
        queue.async {
            if let d = self.device, d.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance),
               (try? d.lockForConfiguration()) != nil {
                d.whiteBalanceMode = .continuousAutoWhiteBalance
                d.unlockForConfiguration()
            }
        }
        DispatchQueue.main.async {
            self.recording = false
            self.started = nil
            self.silent = false
            self.silentSince = nil
            if !ok { self.problem = error?.localizedDescription }
            if exists { self.finished?(url, secs.isFinite ? secs : 0) }   // keep whatever got filmed
            self.finished = nil
        }
    }

    // MARK: - focus, exposure, zoom

    /// Tap: focus and expose there, keep adjusting. Long press (hold): lock both there.
    func focus(at point: CGPoint, hold: Bool) {
        queue.async {
            guard let d = self.device, (try? d.lockForConfiguration()) != nil else { return }
            d.automaticallyAdjustsFaceDrivenAutoExposureEnabled = !hold
            d.automaticallyAdjustsFaceDrivenAutoFocusEnabled = !hold
            if hold {
                d.isFaceDrivenAutoExposureEnabled = false
                d.isFaceDrivenAutoFocusEnabled = false
            }
            if d.isFocusPointOfInterestSupported {
                d.focusPointOfInterest = point
                let mode: AVCaptureDevice.FocusMode = hold ? .autoFocus : .continuousAutoFocus
                if d.isFocusModeSupported(mode) { d.focusMode = mode }
            }
            if d.isExposurePointOfInterestSupported {
                d.exposurePointOfInterest = point
                let mode: AVCaptureDevice.ExposureMode = hold ? .autoExpose : .continuousAutoExposure
                if d.isExposureModeSupported(mode) { d.exposureMode = mode }
            }
            d.unlockForConfiguration()
            DispatchQueue.main.async { self.locked = hold }
        }
    }

    func setBias(_ value: Float) {
        bias = value
        queue.async {
            guard let d = self.device, (try? d.lockForConfiguration()) != nil else { return }
            d.setExposureTargetBias(max(d.minExposureTargetBias, min(d.maxExposureTargetBias, value)), completionHandler: nil)
            d.unlockForConfiguration()
        }
    }

    func setZoom(_ value: CGFloat) {
        let z = max(1, min(maxZoom, value))
        zoom = z
        queue.async {
            guard let d = self.device, (try? d.lockForConfiguration()) != nil else { return }
            d.videoZoomFactor = z
            d.unlockForConfiguration()
        }
    }

    // MARK: - microphone

    @objc private func routeChanged() {
        DispatchQueue.main.async { self.updateMic() }
    }

    /// Which mic iOS is recording from. An external one (USB-C receiver, wired lav) is
    /// remembered, so falling back to the iPhone's own mic later (receiver not plugged in) is flagged.
    func updateMic() {
        let d = UserDefaults.standard
        let input = AVAudioSession.sharedInstance().currentRoute.inputs.first
        mic = input?.portName ?? ""
        if let input, input.portType != .builtInMic {
            d.set(input.portName, forKey: "externalMic")
        }
        externalName = d.string(forKey: "externalMic") ?? ""
        externalExpected = input?.portType == .builtInMic && !externalName.isEmpty && d.bool(forKey: "warnMic")
    }
}


extension CameraController {
    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        let data = error == nil ? photo.fileDataRepresentation() : nil
        DispatchQueue.main.async {
            self.photoDone?(data)
            self.photoDone = nil
        }
    }
}
