import SwiftUI

/// A new Ad Factory project from the phone: product, library script (or your own words),
/// style tags and the account it posts on. Same as "＋ New video" in Ad Factory.
struct NewProjectView: View {
    var made: (Project) -> Void
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var title = ""
    @State private var product: String?
    @State private var script: String?
    @State private var ownWords = ""
    @State private var tags: Set<String> = []
    @State private var account: String?
    @State private var busy = false
    @State private var problem: String?

    private var catalog: Catalog? { model.catalog }
    private var chosenScript: LibraryScript? { catalog?.scripts.first { $0.id == script } }

    /// The product's own scripts first.
    private var scripts: [LibraryScript] {
        let all = catalog?.scripts ?? []
        guard let product else { return all }
        return all.filter { $0.product == product } + all.filter { $0.product != product }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name (optional)", text: $title)
                } footer: {
                    Text("Left empty, it's named after the product and today's date.")
                }
                Section {
                    Picker("Product", selection: $product) {
                        Text("None").tag(String?.none)
                        ForEach(catalog?.products ?? []) { p in
                            Text(verbatim: p.name).tag(String?.some(p.id))
                        }
                    }
                }
                Section {
                    Picker("Script", selection: $script) {
                        Text("My own words").tag(String?.none)
                        ForEach(scripts) { s in
                            Text(verbatim: s.title).tag(String?.some(s.id))
                        }
                    }
                    if let s = chosenScript {
                        Text(verbatim: s.text).font(.callout).foregroundStyle(.secondary)
                    } else {
                        TextEditor(text: $ownWords)
                            .frame(minHeight: 130)
                            .overlay(alignment: .topLeading) {
                                if ownWords.isEmpty {
                                    Text("One line per line of the script…")
                                        .foregroundStyle(.tertiary)
                                        .padding(.top, 8).padding(.leading, 4)
                                        .allowsHitTesting(false)
                                }
                            }
                    }
                } header: {
                    Text("Script")
                } footer: {
                    Text("{Blanks} fill in from the product. Each line shows on the teleprompter.")
                }
                ForEach(["Format", "Hook", "Style", "Tone"], id: \.self) { group in
                    let inGroup = (catalog?.tags ?? []).filter { $0.group == group }
                    if !inGroup.isEmpty {
                        Section {
                            Flow {
                                ForEach(inGroup) { t in
                                    Chip(text: t.name, on: tags.contains(t.id)) {
                                        if tags.contains(t.id) { tags.remove(t.id) } else { tags.insert(t.id) }
                                    }
                                }
                            }
                            .padding(.vertical, 4)
                        } header: {
                            Text(LocalizedStringKey(group))
                        }
                    }
                }
                if let accounts = catalog?.accounts, !accounts.isEmpty {
                    Section {
                        Picker("Posts on", selection: $account) {
                            Text("Decide later").tag(String?.none)
                            ForEach(accounts) { a in
                                let handle = a.handle ?? ""
                                Text(verbatim: handle.isEmpty ? a.name : "\(a.name) (@\(handle))").tag(String?.some(a.id))
                            }
                        }
                    }
                }
                if let problem {
                    Section { Text(verbatim: problem).foregroundStyle(.red) }
                }
            }
            .navigationTitle("New project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else {
                        Button("Film it") { create() }
                            .bold()
                            .disabled(title.isEmpty && product == nil && script == nil && ownWords.isEmpty)
                    }
                }
            }
        }
    }

    private func create() {
        busy = true
        problem = nil
        let body = NewProject(title: title.trimmingCharacters(in: .whitespaces), product: product, script: script,
                              scriptText: chosenScript?.text ?? ownWords, tags: Array(tags), account: account)
        Task { @MainActor in
            do {
                let p = try await model.create(body)
                made(p)
                dismiss()
            } catch {
                problem = error.localizedDescription
            }
            busy = false
        }
    }
}

struct Chip: View {
    var text: String
    var on: Bool
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(verbatim: text)
                .font(.subheadline)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(on ? Color.accentColor : Color.white.opacity(0.12), in: Capsule())
                .foregroundStyle(on ? Color.white : Color.primary)
        }
        .buttonStyle(.plain)
    }
}

/// Wraps its children onto as many rows as they need.
struct Flow: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 320
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0
        for s in subviews {
            let d = s.sizeThatFits(.unspecified)
            if x > 0 && x + d.width > width {
                x = 0
                y += row + spacing
                row = 0
            }
            x += d.width + spacing
            row = max(row, d.height)
        }
        return CGSize(width: width, height: y + row)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, row: CGFloat = 0
        for s in subviews {
            let d = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + d.width > bounds.maxX {
                x = bounds.minX
                y += row + spacing
                row = 0
            }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(d))
            x += d.width + spacing
            row = max(row, d.height)
        }
    }
}
