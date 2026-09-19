"""把 P23 给探针加的两件**量具**（不是产品代码）补进 before 树，好让两边用同一把尺子量：

  · `dom:<ms>:<选择器>` —— 把页面里那一块的存在 / 文字 / 禁用态写进日志
  · `fill` 对 textarea 用对 setter —— 老的那份拿 HTMLInputElement 的 setter 去 call 一个
    textarea，Chrome 直接 TypeError，值一个字没改（「引用 · 改成空」那一格在 before 树上
    因此根本摆不出来）

产品代码一行不动：这两处都只在 `--probe=` 下跑。
"""
from pathlib import Path

BEFORE = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/"
              "401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p23before/frontend/src/probes.ts")
src = BEFORE.read_text(encoding="utf-8")

old_fill = """      } else {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(el, decodeURIComponent(rest.join(':')))
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }"""
new_fill = """      } else {
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
        Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, decodeURIComponent(rest.join(':')))
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }"""
assert old_fill in src, "fill 那一段对不上"
src = src.replace(old_fill, new_fill, 1)

anchor = "  if (probe?.startsWith('toasts:')) {"
dom_step = """  if (probe?.startsWith('dom:')) {
    const [, ms, ...rest] = probe.split(':')
    const sel = decodeURIComponent(rest.join(':'))
    setTimeout(() => {
      const els = Array.from(document.querySelectorAll(sel))
      void api.clientLog('warn', `dom ${sel} n=${els.length} ` + JSON.stringify(els.slice(0, 8).map((e) => ({
        t: (e.textContent ?? '').replace(/\\s+/g, ' ').trim().slice(0, 120),
        d: (e as HTMLButtonElement).disabled ?? null,
      }))), '', 'probe')
    }, Number(ms))
    return
  }
"""
assert anchor in src, "toasts 锚点对不上"
src = src.replace(anchor, dom_step + anchor, 1)

guard_old = "/^(netdown|click:|toasts:|type:|confirmyes)/"
guard_new = "/^(netdown|click:|toasts:|type:|dom:|confirmyes)/"
assert guard_old in src
src = src.replace(guard_old, guard_new, 1)

BEFORE.write_text(src, encoding="utf-8")
print("before 树的探针已补上 dom: 和 textarea fill")
