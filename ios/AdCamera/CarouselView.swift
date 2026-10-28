import Photos
import SwiftUI

/// Carousel mode (user, 2026-10-27): shoot several carousel projects in one go. Pick the carousels
/// (one product each) and how many outfits; every outfit is shot once with every product. Switch the
/// product or the outfit freely, so you can do all outfits for one product in a row, or keep one outfit
/// and swap the products through it. After each photo it moves to the next combo not done yet, in the
/// order you picked. Each photo goes to the "Ad Studio" album and into that product's carousel folder in
/// Ad Factory (PUT /api/camera/photo?shoot=…&outfit=N); a retake replaces it.
struct CarouselSetup: View {
    let projects: [Project]
    var start: ([Project], Int) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var picked: Set<String> = []
    @AppStorage("carouselOutfits") private var outfits = 3

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ForEach(projects) { p in
                        Button {
                            if picked.contains(p.sid) { picked.remove(p.sid) } else { picked.insert(p.sid) }
                        } label: {
                            HStack {
                                Image(systemName: picked.contains(p.sid) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(picked.contains(p.sid) ? Color.accentColor : .secondary)
                                VStack(alignment: .leading) {
                                    Text(verbatim: p.productName ?? p.title).foregroundStyle(.primary)
                                    if let d = p.due, !d.isEmpty { Text(verbatim: d).font(.caption).foregroundStyle(.secondary) }
                                }
                                Spacer()
                                if let o = p.outfits, !o.isEmpty { Text("\(o.count) done").font(.caption).foregroundStyle(.secondary) }
                            }
                        }
                    }
                } header: {
                    Text("Carousels to shoot")
                } footer: {
                    Text("Each one is a product's carousel.")
                }
                Section {
                    Stepper(value: $outfits, in: 2...5) { Text("\(outfits) outfits") }
                } footer: {
                    Text("Every outfit is shot once with every product you picked: \(picked.count * outfits) photos.")
                }
            }
            .navigationTitle("Shoot carousels")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Start") {
                        let chosen = projects.filter { picked.contains($0.sid) }
                        dismiss()
                        start(chosen, outfits)
                    }
                    .disabled(picked.isEmpty)
                }
            }
            .onAppear {   // the soonest day's carousels, picked to start with, and that day's planned outfit count
                let first = projects.compactMap(\.due).filter { !$0.isEmpty }.min()
                let soon = projects.filter { first == nil || $0.due == first }
                picked = Set(soon.map(\.sid))
                if let n = soon.first?.outfitPlan?.count, (2...5).contains(n) { outfits = n }
            }
        }
    }
}

struct CarouselView: View {
    let projects: [Project]
    let outfits: Int
    @Environment(\.dismiss) private var dismiss
    @StateObject private var camera = CameraController()
    @StateObject private var voice = VoiceControl()
    @State private var product = 0
    @State private var outfit = 1
    @State private var done: [String: Set<Int>] = [:]        // shoot id -> outfits shot
    @State private var sending: Set<String> = []             // "sid#outfit" uploading
    @State private var problem: String?
    @State private var flash = false
    @AppStorage("carouselOrder") private var order = "product"   // "product": all outfits of one product first

    private var current: Project { projects[product] }
    private func isDone(_ p: Int, _ o: Int) -> Bool { done[projects[p].sid]?.contains(o) ?? false }
    private var total: Int { projects.count * outfits }
    private var shot: Int { projects.indices.reduce(0) { n, p in n + (1...outfits).filter { isDone(p, $0) }.count } }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            GeometryReader { geo in
                let w = min(geo.size.width, geo.size.height * 9 / 16)
                CameraPreview(camera: camera, shutter: shoot)
                    .frame(width: w, height: w * 16 / 9)
                    .position(x: geo.size.width / 2, y: geo.size.height / 2)
                    .overlay(Color.white.opacity(flash ? 0.7 : 0).allowsHitTesting(false))
            }
            .ignoresSafeArea()
            VStack(spacing: 10) {
                HStack {
                    Button { dismiss() } label: { Image(systemName: "xmark").font(.headline).padding(10).background(.black.opacity(0.5), in: Circle()) }
                    Spacer()
                    Text("\(shot) of \(total) photos").font(.subheadline.weight(.semibold)).padding(.horizontal, 12).padding(.vertical, 6)
                        .background(.black.opacity(0.5), in: Capsule())
                    Spacer()
                    Menu {
                        Picker("Order", selection: $order) {
                            Text("All outfits for one product").tag("product")
                            Text("One outfit, swap the products").tag("outfit")
                        }
                    } label: { Image(systemName: "arrow.triangle.swap").font(.headline).padding(10).background(.black.opacity(0.5), in: Circle()) }
                }
                .padding(.horizontal, 14)
                VoiceBadge(voice)
                if let problem { Text(verbatim: problem).font(.caption).foregroundStyle(.orange).padding(6).background(.black.opacity(0.6), in: Capsule()) }
                Spacer()
                guide
                grid
                picker(title: "Product", count: projects.count, sel: $product) { i in
                    Text(verbatim: Self.short(projects[i])).lineLimit(1)
                }
                picker(title: "Outfit", count: outfits, sel: Binding(get: { outfit - 1 }, set: { outfit = $0 + 1 })) { i in
                    Text("Outfit \(i + 1)")
                }
                HStack {
                    Text(isDone(product, outfit) ? "Retake replaces it" : " ").font(.caption).foregroundStyle(.secondary).frame(width: 110, alignment: .leading)
                    Spacer()
                    Button(action: shoot) {
                        ZStack {
                            Circle().stroke(.white, lineWidth: 4).frame(width: 74, height: 74)
                            Circle().fill(.white).frame(width: 60, height: 60)
                        }
                    }
                    Spacer()
                    Color.clear.frame(width: 110)
                }
                .padding(.horizontal, 16).padding(.bottom, 8)
            }
            .foregroundStyle(.white)
        }
        .statusBarHidden()
        .onAppear {
            camera.position = .back
            camera.start()
            for p in projects { done[p.sid] = Set(p.outfits ?? []) }
            next(from: true)
            voice.start(action: { shoot() }, cut: {})   // "Ad Camera, action" takes the photo
            UIApplication.shared.isIdleTimerDisabled = true
        }
        .onDisappear {
            voice.stop()
            camera.stop()
            UIApplication.shared.isIdleTimerDisabled = false
        }
    }

    /// What to lay out right now: the planned outfit for this product, and (outfit 1) the carousel's text.
    @ViewBuilder private var guide: some View {
        let plan = current.outfitPlan ?? []
        VStack(alignment: .leading, spacing: 4) {
            if outfit <= plan.count {
                let o = plan[outfit - 1]
                Text("Outfit \(outfit): \(o.name)").font(.subheadline.weight(.semibold))
                Text("Lay \(Self.short(current)) with \(o.with)").font(.footnote)
            } else {
                Text("Outfit \(outfit)").font(.subheadline.weight(.semibold))
            }
            if let text = current.carouselText, !text.isEmpty {
                Text("On-screen text: \(text)").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal, 14)
    }

    /// Which combos are shot: products down, outfits across; tap a cell to go to it.
    private var grid: some View {
        VStack(spacing: 4) {
            ForEach(projects.indices, id: \.self) { p in
                HStack(spacing: 4) {
                    Text(verbatim: Self.short(projects[p])).font(.caption2).lineLimit(1).frame(width: 96, alignment: .leading)
                    ForEach(1...outfits, id: \.self) { o in
                        let here = p == product && o == outfit, key = "\(projects[p].sid)#\(o)"
                        Button { product = p; outfit = o } label: {
                            ZStack {
                                RoundedRectangle(cornerRadius: 5).fill(isDone(p, o) ? Color.green.opacity(0.75) : Color.white.opacity(0.15))
                                if sending.contains(key) { ProgressView().scaleEffect(0.6) }
                                else if isDone(p, o) { Image(systemName: "checkmark").font(.caption2.bold()) }
                            }
                            .frame(width: 30, height: 22)
                            .overlay(RoundedRectangle(cornerRadius: 5).stroke(here ? Color.white : .clear, lineWidth: 2))
                        }
                    }
                }
            }
        }
        .padding(8)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }

    private func picker<L: View>(title: LocalizedStringKey, count: Int, sel: Binding<Int>, @ViewBuilder label: @escaping (Int) -> L) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(0..<count, id: \.self) { i in
                    Button { sel.wrappedValue = i } label: {
                        label(i).font(.subheadline.weight(sel.wrappedValue == i ? .semibold : .regular))
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(sel.wrappedValue == i ? Color.accentColor : Color.black.opacity(0.5), in: Capsule())
                    }
                }
            }
            .padding(.horizontal, 14)
        }
        .accessibilityLabel(Text(title))
    }

    static func short(_ p: Project) -> String {
        let name = p.productName ?? p.title
        if let dash = name.range(of: " - ") { return String(name[dash.upperBound...]) }   // the colourway
        return name
    }

    private func shoot() {
        let p = current, o = outfit, key = "\(p.sid)#\(o)"
        camera.takePhoto { data in
            guard let data else { problem = String(localized: "That photo didn't take. Try again."); return }
            withAnimation(.easeOut(duration: 0.15)) { flash = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { withAnimation { flash = false } }
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            done[p.sid, default: []].insert(o)
            sending.insert(key)
            next(from: false)
            Task { await send(data, project: p, outfit: o, key: key) }
        }
    }

    /// Move to the next combo not shot yet, in the chosen order.
    private func next(from start: Bool) {
        var combos: [(Int, Int)] = []
        if order == "product" {
            for p in projects.indices { for o in 1...outfits { combos.append((p, o)) } }
        } else {
            for o in 1...outfits { for p in projects.indices { combos.append((p, o)) } }
        }
        let here = combos.firstIndex { $0.0 == product && $0.1 == outfit } ?? 0
        let ordered = start ? combos : Array(combos[here...] + combos[..<here])
        if let n = ordered.first(where: { !isDone($0.0, $0.1) }) { (product, outfit) = n }
    }

    private func send(_ data: Data, project p: Project, outfit o: Int, key: String) async {
        let ext = data.starts(with: [0xFF, 0xD8]) ? "jpg" : "heic"
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("carousel-\(UUID().uuidString).\(ext)")
        try? data.write(to: file)
        try? await PhotoAlbum.save(file, as: .photo)
        var ok = false
        for attempt in 0..<4 {   // a few tries: the PC may be busy or the Wi-Fi flaky
            do {
                var r = try Server.request("api/camera/photo", query: [("shoot", p.sid), ("outfit", String(o)), ("name", "outfit-\(o).\(ext)")], method: "PUT")
                r.timeoutInterval = 60
                r.httpBody = data
                _ = try await Server.send(r)
                ok = true
                break
            } catch {
                try? await Task.sleep(nanoseconds: UInt64(2 + attempt * 3) * 1_000_000_000)
            }
        }
        try? FileManager.default.removeItem(at: file)
        await MainActor.run {
            sending.remove(key)
            problem = ok ? nil : String(localized: "Couldn't send a photo to Ad Factory. It's in the Ad Studio album; retake it later.")
            if !ok { done[p.sid]?.remove(o) }
        }
    }
}
