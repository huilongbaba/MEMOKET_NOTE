// modtap：双击一个修饰键（默认 ⌥）就往 stdout 打一行 "tap"。MEMOKET NOTE 的「拿主意」用它触发截图。
// 全局监听按键要辅助功能权限（由启动它的应用继承）；启动时先报一句 "ready trusted=true/false"。
// 编译：npm run build:helpers（swiftc -O -swift-version 5 -o dist/modtap helpers/modtap.swift）。
import Cocoa

let name = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "option"
let flag: NSEvent.ModifierFlags
switch name {
case "control": flag = .control
case "command": flag = .command
case "shift": flag = .shift
default: flag = .option
}
let all: NSEvent.ModifierFlags = [.command, .control, .shift, .option]
/// 两下之间最多隔多久。
let window: TimeInterval = 0.35
var down = false
var lastDown: TimeInterval = 0
var armed = false

setbuf(stdout, nil)
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
print("ready trusted=\(AXIsProcessTrusted())")

NSEvent.addGlobalMonitorForEvents(matching: [.flagsChanged, .keyDown, .leftMouseDown]) { event in
  // 两下之间敲了别的键、点了鼠标，都不算双击。
  if event.type != .flagsChanged { armed = false; lastDown = 0; return }
  let pressed = event.modifierFlags.contains(flag)
  let others = event.modifierFlags.intersection(all).subtracting(flag)
  if pressed && !down {
    down = true
    // 只认这一个键单独按下：⌘⌥、⌥⇧ 之类不算。
    if !others.isEmpty { armed = false; lastDown = 0; return }
    if armed && event.timestamp - lastDown < window {
      print("tap")
      armed = false
      lastDown = 0
    } else {
      lastDown = event.timestamp
      armed = false
    }
  } else if !pressed && down {
    down = false
    // 第一下按得短才算数：按住不放是别的意思（⌥ 拖拽、⌥ 点菜单）。
    armed = lastDown > 0 && event.timestamp - lastDown < window
  }
}
app.run()
