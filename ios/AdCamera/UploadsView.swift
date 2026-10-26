import SwiftUI

/// Every take filmed on this phone and where it is: in Photos, uploading, sent, or waiting.
struct UploadsView: View {
    @EnvironmentObject private var clips: ClipStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    UploadSummary()
                    if clips.waiting > 0 {
                        Button("Try again now") { clips.retryWaiting() }
                    }
                }
                Section {
                    ForEach(clips.clips) { c in
                        ClipRow(clip: c, progress: clips.progress[c.id])
                    }
                }
            }
            .navigationTitle("Takes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Clear sent") { clips.clearFinished() }
                        .disabled(!clips.clips.contains { $0.uploaded && $0.inPhotos })
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

struct ClipRow: View {
    let clip: Clip
    let progress: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(verbatim: clip.projectTitle).font(.subheadline.bold()).lineLimit(1)
                Spacer()
                if clip.inPhotos {
                    Image(systemName: "photo.on.rectangle").foregroundStyle(.secondary)
                        .accessibilityLabel(Text("In Photos"))
                }
            }
            HStack(spacing: 8) {
                Text(clip.created, format: .dateTime.month(.abbreviated).day().hour().minute())
                Text(verbatim: Self.duration(clip.seconds))
                Text(verbatim: ByteCountFormatter.string(fromByteCount: clip.bytes, countStyle: .file))
                if let l = clip.line { Text("line \(l + 1)") }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            if clip.silent == true {
                Label("No sound in this take", systemImage: "speaker.slash.fill")
                    .font(.caption.bold()).foregroundStyle(.red)
            }
            if clip.uploaded {
                Label("Sent to OneDrive", systemImage: "checkmark.icloud.fill")
                    .font(.caption).foregroundStyle(.green)
            } else if let progress {
                ProgressView(value: progress) {
                    Text("Uploading \(Int(progress * 100))%").font(.caption)
                }
            } else if let e = clip.error {
                Text(verbatim: e).font(.caption).foregroundStyle(.orange)
            } else {
                Text("Waiting to upload").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    static func duration(_ s: Double) -> String {
        let t = Int(s.rounded())
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
