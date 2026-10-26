import AVFoundation

/// After each take: did any sound actually get recorded? Reads the file's audio and looks for
/// a single sample louder than about -60 dBFS (any speech is far above that; a lav whose
/// transmitter was off records dead silence far below it).
enum AudioCheck {
    /// true = no audio track, or nothing louder than -60 dBFS; nil = couldn't tell.
    static func isSilent(_ url: URL) async -> Bool? {
        let asset = AVURLAsset(url: url)
        guard let tracks = try? await asset.loadTracks(withMediaType: .audio) else { return nil }
        guard let track = tracks.first else { return true }   // filmed with no sound at all
        guard let reader = try? AVAssetReader(asset: asset) else { return nil }
        let out = AVAssetReaderTrackOutput(track: track, outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ])
        guard reader.canAdd(out) else { return nil }
        reader.add(out)
        guard reader.startReading() else { return nil }
        let threshold: Int16 = 33   // 32768 × 10^(-60/20)
        while let buffer = out.copyNextSampleBuffer() {
            guard let block = CMSampleBufferGetDataBuffer(buffer) else { continue }
            var length = 0
            var pointer: UnsafeMutablePointer<Int8>?
            guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: &length, totalLengthOut: nil,
                                              dataPointerOut: &pointer) == kCMBlockBufferNoErr,
                  let pointer else { continue }
            let loud = pointer.withMemoryRebound(to: Int16.self, capacity: length / 2) { samples -> Bool in
                for i in 0..<(length / 2) where samples[i] > threshold || samples[i] < -threshold { return true }
                return false
            }
            if loud {
                reader.cancelReading()
                return false
            }
        }
        return reader.status == .completed ? true : nil
    }
}
