import SwiftUI

/// Home: Ad Factory's projects (to film first), a new-project button and the upload status.
struct ProjectsView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var clips: ClipStore
    @State private var path: [Project] = []
    @State private var filming: Project?
    @State private var made: Project?
    @State private var showNew = false
    @State private var showSettings = false
    @State private var showUploads = false
    @State private var showPosted = false
    @State private var deleting: Project?
    @State private var showCarousels = false
    @State private var carouselRun: CarouselRun?

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if !model.signedIn {
                    Section {
                        Button { showSettings = true } label: {
                            Label("Sign in to Ad Factory", systemImage: "person.badge.key")
                        }
                    } footer: {
                        Text("Projects and uploads come from Ad Factory on the PC.")
                    }
                }
                if let p = model.problem, model.signedIn {
                    Section {
                        Label { Text(verbatim: p) } icon: { Image(systemName: "wifi.exclamationmark") }
                            .foregroundStyle(.orange)
                    } footer: {
                        if model.offline {
                            Text("Showing the list from last time. Takes you film wait on the phone and upload later.")
                        }
                    }
                }
                if !clips.clips.isEmpty {
                    Section {
                        Button { showUploads = true } label: { UploadSummary() }
                    }
                }
                let all = model.catalog?.projects ?? []
                let shelf = all.filter { model.archived.contains($0.sid) }
                let live = all.filter { !model.archived.contains($0.sid) }
                let carousels = live.filter { $0.carousel == true && $0.stage != "posted" }
                if !carousels.isEmpty {
                    Section {
                        Button { showCarousels = true } label: {
                            Label("Shoot carousels (\(carousels.count))", systemImage: "square.grid.3x3")
                        }
                    } footer: {
                        Text("Several carousels at once: every outfit with every product.")
                    }
                }
                let toFilm = live.filter { $0.stage == "film" && $0.carousel != true }
                let going = live.filter { ["precut", "edit", "post"].contains($0.stage) }
                let posted = live.filter { $0.stage == "posted" }
                Section {
                    ForEach(toFilm) { p in
                        row(p).swipeActions(edge: .trailing) {
                            Button { withAnimation { model.setArchived(p.sid, true) } } label: {
                                Label("Archive", systemImage: "archivebox")
                            }
                            .tint(.orange)
                        }
                    }
                    if toFilm.isEmpty {
                        Text("Nothing waiting to be filmed. Tap ＋ to start a project.")
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("To film")
                } footer: {
                    if !toFilm.isEmpty { Text("Swipe a project from the right to archive it.") }
                }
                if !going.isEmpty {
                    Section {
                        ForEach(going) { row($0) }
                    } header: {
                        Text("Filmed: add more takes")
                    }
                }
                if !shelf.isEmpty {
                    Section {
                        ForEach(shelf) { p in
                            row(p)
                                .swipeActions(edge: .leading) {
                                    Button { withAnimation { model.setArchived(p.sid, false) } } label: {
                                        Label("Unarchive", systemImage: "tray.and.arrow.up")
                                    }
                                    .tint(.blue)
                                }
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) { deleting = p } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                        }
                    } header: {
                        Text("Archived")
                    } footer: {
                        Text("Swipe from the left to bring one back, from the right to delete it.")
                    }
                }
                if !posted.isEmpty {
                    Section {
                        DisclosureGroup(isExpanded: $showPosted) {
                            ForEach(posted) { row($0) }
                        } label: {
                            Text("Posted (\(posted.count))")
                        }
                    }
                }
            }
            .navigationTitle("Ad Camera")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel(Text("Settings"))
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNew = true } label: { Image(systemName: "plus") }
                        .disabled(!model.signedIn || model.catalog == nil)
                        .accessibilityLabel(Text("New project"))
                }
            }
            .refreshable { await model.refresh() }
            .overlay {
                if model.catalog == nil && model.loading { ProgressView() }
            }
            .task { await model.refresh() }
            .navigationDestination(for: Project.self) { p in
                ProjectView(project: p) { filming = p }
            }
        }
        .sheet(isPresented: $showNew, onDismiss: {
            if let p = made {   // a new project goes straight to the camera, with its page underneath
                made = nil
                path = [p]
                filming = p
            }
        }) {
            NewProjectView { made = $0 }
                .environmentObject(model)
        }
        .confirmationDialog(Text(verbatim: deleting.map { String(localized: "Delete \"\($0.title)\"?") } ?? ""),
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                            titleVisibility: .visible, presenting: deleting) { p in
            Button("Delete", role: .destructive) {
                Task {
                    do { try await model.delete(p) } catch { model.problem = error.localizedDescription }
                }
            }
        } message: { _ in
            Text("It moves to Ad Factory's trash folder on the PC. Its raw footage and finished videos are kept.")
        }
        .sheet(isPresented: $showSettings) {
            SettingsView().environmentObject(model)
        }
        .sheet(isPresented: $showCarousels) {
            CarouselSetup(projects: (model.catalog?.projects ?? []).filter { $0.carousel == true && $0.stage != "posted" }) { chosen, n in
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { carouselRun = CarouselRun(projects: chosen, outfits: n) }
            }
        }
        .fullScreenCover(item: $carouselRun, onDismiss: { Task { await model.refresh() } }) {
            CarouselView(projects: $0.projects, outfits: $0.outfits)
        }
        .sheet(isPresented: $showUploads) {
            UploadsView().environmentObject(clips)
        }
        .fullScreenCover(item: $filming) {
            CameraView(project: $0) { next in   // "Next project": close this camera, open the next one with its page underneath
                filming = nil
                path = [next]
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { filming = next }
            }
            .environmentObject(model).environmentObject(clips)
        }
    }

    private func row(_ p: Project) -> some View {
        NavigationLink(value: p) {
            ProjectRow(project: p, here: clips.count(for: p.sid))
        }
    }
}

struct ProjectRow: View {
    let project: Project
    let here: Int

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "video.fill")
                .font(.title3)
                .foregroundStyle(Color.accentColor)
                .frame(width: 30)
            VStack(alignment: .leading, spacing: 3) {
                Text(verbatim: project.title).font(.headline).lineLimit(2)
                if let name = project.productName, !name.isEmpty, name != project.title {
                    Text(verbatim: name).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                }
                if !project.tags.isEmpty {
                    Text(verbatim: project.tags.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                HStack(spacing: 10) {
                    if project.lines.isEmpty {
                        Text("No script")
                    } else {
                        Text("\(project.lines.count) lines")
                    }
                    if project.clips > 0 { Text("\(project.clips) videos in Ad Factory") }
                    if here > 0 { Text("\(here) filmed here") }
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            if project.stage != "film" {
                Text(verbatim: Stage.label(project.stage))
                    .font(.caption2.bold())
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(Color.white.opacity(0.12), in: Capsule())
            }
        }
        .padding(.vertical, 2)
    }
}

struct UploadSummary: View {
    @EnvironmentObject private var clips: ClipStore

    var body: some View {
        HStack {
            if clips.waiting == 0 {
                Label("All takes sent to OneDrive", systemImage: "checkmark.icloud.fill")
                    .foregroundStyle(.green)
            } else if clips.sending > 0 {
                Label { Text("Uploading \(clips.sending) of \(clips.waiting) takes") } icon: {
                    Image(systemName: "icloud.and.arrow.up")
                }
            } else {
                Label { Text("\(clips.waiting) takes waiting to upload") } icon: {
                    Image(systemName: "icloud.slash")
                }
                .foregroundStyle(.orange)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.caption).foregroundStyle(.secondary)
        }
    }
}


struct CarouselRun: Identifiable {
    let id = UUID()
    let projects: [Project]
    let outfits: Int
}
