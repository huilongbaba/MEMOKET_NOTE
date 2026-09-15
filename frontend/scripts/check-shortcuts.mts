/** 快捷键的两条规矩。
 *
 *     npx tsx scripts/check-shortcuts.mts
 *
 * **① 绑了的键必须在快捷键表里查得到。**
 * 第 706 轮逐条核对我自己给过的理由时发现：标题、列表一个键都没绑，而我上一轮
 * 拿「⌘1 这些键都在」当过收起工具条的理由。补上键之后立刻加这条——
 * **表里查不到的键等于没有**，用户没有别的地方能知道它存在。
 *
 * **② 给人看的快捷键文案不许写死 mac 符号。**
 * 10 处 `title="…（⌘K）"` 直接把 ⌘ 写进了字符串，Windows 上显示的是键盘上
 * 根本没有的符号。要走 `fmtShortcut()`。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../src')
const walk = (d: string, out: string[] = []) => {
  for (const f of readdirSync(d)) {
    const p = join(d, f)
    if (statSync(p).isDirectory()) { if (!p.includes('__tests__')) walk(p, out) } else out.push(p)
  }
  return out
}

let bad = 0

// ① CM6 keymap 里绑的键 → 快捷键表
{
  const km = readFileSync(join(root, 'editor/markdownCommands.ts'), 'utf8')
  const table = readFileSync(join(root, 'shortcuts.ts'), 'utf8')
  const body = km.slice(km.indexOf('export const markdownKeymap'))
  const keys = [...body.matchAll(/key: '([^']+)'/g)].map((m) => m[1])
  if (keys.length < 3) { console.error('没读到 markdownKeymap，闸门失效'); process.exit(1) }
  for (const k of keys) {
    const parts = k.split('-')
    const main = parts[parts.length - 1]
    const want: string[] = []
    if (parts.includes('Mod')) want.push('⌘')
    if (parts.includes('Alt')) want.push('⌥')
    if (parts.includes('Shift')) want.push('⇧')
    /* 表里是给人看的写法，顺序（⌃⌥⇧⌘）跟 CM6 的写法（`Mod-Alt-…`）不一样，
       所以不比顺序，只比「这个和弦有哪些修饰符 + 主键是什么」。
       **一行里常常写好几个和弦**（`⌘B / ⌘I / ⇧⌘K`），所以先拆开再逐个比——
       第一版拿整行比，`⌘B` 被同一行里 `⇧⌘K` 的那个 ⇧ 判成不匹配（当场误报）。 */
    const chords = [...table.matchAll(/keys: '([^']+)'/g)]
      .flatMap((m) => m[1].split(/\s*[/…]\s*/))
    const hit = chords.some((c) => {
      const mods = (c.match(/[⌘⌥⇧⌃]/g) ?? []).join('')
      const rest = c.replace(/[⌘⌥⇧⌃]/g, '')
      return mods.length === want.length && want.every((w) => mods.includes(w))
        && rest.toUpperCase() === main.toUpperCase()
    })
    if (hit) continue
    bad++
    console.log(`✗ 绑了 ${k} 但 shortcuts.ts 的表里查不到 —— 用户没别的地方知道它存在`)
  }
}

// ② 给人看的文案不许写死 mac 符号
{
  for (const f of walk(root)) {
    if (!/\.tsx?$/.test(f) || f.endsWith('shortcuts.ts') || f.endsWith('util/keys.ts')) continue
    const rel = f.replace(root + '/', '')
    readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
      const code = line.split('//')[0]
      if (code.trimStart().startsWith('*')) return           // 注释里讲到某个键不算
      // 只认**双引号字面量**里的：模板串里的都是 `${fmtShortcut(...)}` 拼出来的
      for (const m of code.matchAll(/(title|placeholder|aria-label)="([^"]*[⌘⌥⇧⌃][^"]*)"/g)) {
        bad++
        console.log(`✗ ${rel}:${i + 1} ${m[1]} 里写死了 mac 符号「${m[2].slice(0, 30)}」`
          + ` —— Windows 上是键盘上没有的符号，走 fmtShortcut()`)
      }
    })
  }
}

if (bad) { console.error(`${bad} 处`); process.exit(1) }
console.log('OK: 绑了的键表里都有，给人看的键位也没写死 mac 符号')
