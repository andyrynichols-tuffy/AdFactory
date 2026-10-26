import SwiftUI

/// The teleprompter: a floating card that can be dragged anywhere, made wider or narrower
/// (drag its corner), have its text resized (pinch) and be closed (✕). Tap it for the next
/// line; ‹ › step back and forward. Where it sits is kept per layout.
struct FloatingPrompter: View {
    let lines: [String]
    @Binding var line: Int
    @Binding var x: Double          // centre, as a fraction of the screen
    @Binding var y: Double
    @Binding var width: Double      // fraction of the screen width
    @Binding var size: Double       // text size in points
    let screen: CGSize
    let close: () -> Void

    @State private var move: CGSize = .zero
    @State private var grow: CGFloat = 0
    @GestureState private var pinch: CGFloat = 1

    var body: some View {
        let i = max(0, min(line, lines.count - 1))
        let w = min(screen.width - 12, max(150, screen.width * width + grow))
        let s = min(64, max(14, CGFloat(size) * pinch))
        VStack(spacing: 6) {
            HStack(spacing: 16) {
                Image(systemName: "arrow.up.and.down.and.arrow.left.and.right").font(.caption).opacity(0.6)
                Text("Line \(i + 1) of \(lines.count)").font(.caption2).opacity(0.7)
                Spacer(minLength: 0)
                Button { line = max(0, i - 1) } label: { Image(systemName: "chevron.left") }
                    .disabled(i == 0)
                    .accessibilityLabel(Text("Previous line"))
                Button { line = min(lines.count - 1, i + 1) } label: { Image(systemName: "chevron.right") }
                    .disabled(i >= lines.count - 1)
                    .accessibilityLabel(Text("Next line"))
                Button(action: close) { Image(systemName: "xmark") }
                    .accessibilityLabel(Text("Hide the teleprompter"))
            }
            .font(.subheadline.bold())
            .foregroundStyle(.white)
            Text(verbatim: lines[i])
                .font(.system(size: s, weight: .bold))
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .fixedSize(horizontal: false, vertical: true)
            if i + 1 < lines.count {
                Text(verbatim: lines[i + 1])
                    .font(.system(size: s * 0.6))
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
                    .opacity(0.55)
                    .lineLimit(2)
            }
        }
        .padding(12)
        .frame(width: w)
        .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 14))
        .overlay(alignment: .bottomTrailing) {
            Image(systemName: "arrow.up.left.and.arrow.down.right")   // drag sideways: wider / narrower
                .font(.caption.bold())
                .frame(width: 32, height: 32)
                .contentShape(Rectangle())
                .highPriorityGesture(DragGesture(minimumDistance: 2)
                    .onChanged { grow = $0.translation.width * 2 }
                    .onEnded { v in
                        let px = min(screen.width - 12, max(150, screen.width * width + v.translation.width * 2))
                        width = Double(px / screen.width)
                        grow = 0
                    })
                .accessibilityLabel(Text("Resize"))
        }
        .contentShape(RoundedRectangle(cornerRadius: 14))
        .onTapGesture { line = min(lines.count - 1, i + 1) }
        .gesture(DragGesture(minimumDistance: 8)
            .onChanged { move = $0.translation }
            .onEnded { v in
                x = Double(min(max((screen.width * x + v.translation.width) / screen.width, 0.1), 0.9))
                y = Double(min(max((screen.height * y + v.translation.height) / screen.height, 0.06), 0.94))
                move = .zero
            })
        .simultaneousGesture(MagnificationGesture()
            .updating($pinch) { value, state, _ in state = value }
            .onEnded { value in size = Double(min(64, max(14, CGFloat(size) * value))) })
        .position(x: screen.width * x + move.width, y: screen.height * y + move.height)
    }
}
