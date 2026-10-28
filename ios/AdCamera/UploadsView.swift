import SwiftUI

/// Every take filmed on this phone and where it is: in Photos, uploading, sent, or waiting.
struct UploadsView: View {
    @EnvironmentObject private var clips: ClipStore
    @Environment(\.dismiss) private var dismiss
    @State private var deleting: Clip?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    UploadSummary()
                    if clips.waiting > 0 {
                        Button("Try again now") { clips.retryWaiting() }
                    }
                }
                let live = clips.clips.filter { $0.archived != true }
                let shelf = clips.clips.filter { $0.archived == true }
                Section {
                    ForEach(live) { c in
                        ClipRow(clip: c, progress: clips.progress[c.id], telling: clips.telling(c))
                            .swipeActions(edge: .trailing) {
                                Button { withAnimation { clips.setArchived(c.id, true) } } label: {
                                    Label("Archive", systemImage: "archivebox")
                                }
                                .tint(.orange)
                            }
                    }
                } footer: {
                    if !live.isEmpty { Text("Swipe a take from the right to archive it.") }
                }
                if !shelf.isEmpty {
                    Section {
                        ForEach(shelf) { c in
                            ClipRow(clip: c, progress: nil, telling: clips.telling(c))
                                .swipeActions(edge: .leading) {
                                    Button { withAnimation { clips.setArchived(c.id, false) } } label: {
                                        Label("Unarchive", systemImage: "tray.and.arrow.up")
                                    }
                                    .tint(.blue)
                                }
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) { deleting = c } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                        }
                    } header: {
                        Text("Archived")
                    } footer: {
                        Text("Archived takes are kept out of Ad Factory's videos. Swipe from the left to bring one back, from the right to delete it.")
                    }
                }
            }
            .confirmationDialog(Text("Delete this take?"),
                                isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                                titleVisibility: .visible, presenting: deleting) { c in
                Button("Delete", role: .destructive) { withAnimation { clips.delete(c.id) } }
            } message: { c in
                Text(c.uploaded ? "It's removed from this phone and kept out of Ad Factory's videos. The footage itself stays in Ad Factory and in Photos (Ad Studio album)."
                                : "It's removed from this phone and won't be sent. A copy already saved in Photos (Ad Studio album) stays there.")
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
    var telling = false        // Ad Factory hasn't heard about an archive / unarchive yet

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
            } else if clip.archived == true {
                Label("On hold while archived", systemImage: "pause.circle")
                    .font(.caption).foregroundStyle(.secondary)
            } else if let progress {
                ProgressView(value: progress) {
                    Text("Uploading \(Int(progress * 100))%").font(.caption)
                }
            } else if let e = clip.error {
                Text(verbatim: e).font(.caption).foregroundStyle(.orange)
            } else {
                Text("Waiting to upload").font(.caption).foregroundStyle(.secondary)
            }
            if clip.archived == true && clip.uploaded {
                Label(telling ? "Taking it out of Ad Factory's videos…" : "Kept out of Ad Factory's videos",
                      systemImage: telling ? "arrow.triangle.2.circlepath" : "nosign")
                    .font(.caption).foregroundStyle(.secondary)
            } else if telling && clip.uploaded {
                Label("Putting it back in Ad Factory's videos…", systemImage: "arrow.triangle.2.circlepath")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    static func duration(_ s: Double) -> String {
        let t = Int(s.rounded())
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
