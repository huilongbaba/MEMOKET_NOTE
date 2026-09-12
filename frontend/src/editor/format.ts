/** 一键格式化整篇 markdown。
 *
 * **纯函数、不走模型**：格式是有明确规则的东西，交给模型只会引入不确定性
 * （每次结果不一样、还可能顺手改内容）。这里只动排版，一个字的内容都不改。
 *
 * 最要紧的不变量是**幂等**：格式化两次必须等于格式化一次。不幂等的话，用户
 * 每点一次都产生一堆 diff，"接受/撤回"就变成了噪声。scripts/check-format.mts
 * 用固定用例 + 随机 fuzz 守这条。
 *
 * 代码块、行内代码、表格分隔行里的内容一律**原样不动**——排版规则套进代码里
 * 就是在改用户的程序。
 */

const FENCE = /^(\s*)(`{3,}|~{3,})/

/** 把正文按「代码块外 / 代码块内」切开。代码块内的行原样保留。 */
function splitFences(lines: string[]): { code: boolean; lines: string[] }[] {
  const out: { code: boolean; lines: string[] }[] = []
  let cur: { code: boolean; lines: string[] } = { code: false, lines: [] }
  let fence = ''
  for (const line of lines) {
    const m = FENCE.exec(line)
    if (!fence && m) {
      if (cur.lines.length) out.push(cur)
      fence = m[2]
      cur = { code: true, lines: [line] }
      continue
    }
    if (fence) {
      cur.lines.push(line)
      // 结束标记必须是同类型、且不短于开始那一串
      if (m && m[2][0] === fence[0] && m[2].length >= fence.length) {
        out.push(cur)
        cur = { code: false, lines: [] }
        fence = ''
      }
      continue
    }
    cur.lines.push(line)
  }
  if (cur.lines.length) out.push(cur)
  return out
}

const cells = (line: string): string[] => {
  const t = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  const out: string[] = []
  let cur = ''
  for (let i = 0; i < t.length; i++) {
    if (t[i] === '\\' && t[i + 1] === '|') { cur += '\\|'; i++; continue }
    if (t[i] === '|') { out.push(cur.trim()); cur = ''; continue }
    cur += t[i]
  }
  out.push(cur.trim())
  return out
}

const isSep = (line: string): boolean => {
  const cs = cells(line)
  return cs.length > 0 && cs.every((c) => /^:?-{1,}:?$/.test(c))
}

/** 显示宽度：CJK 和全角标点占两格。表格对齐要按这个算，按字符数算的话
 * 中文表格在等宽字体里还是参差的。 */
function width(s: string): number {
  let w = 0
  for (const ch of s) {
    const c = ch.codePointAt(0) ?? 0
    w += (c >= 0x1100 && (c <= 0x115f || c === 0x2329 || c === 0x232a
      || (c >= 0x2e80 && c <= 0xa4cf && c !== 0x303f)
      || (c >= 0xac00 && c <= 0xd7a3) || (c >= 0xf900 && c <= 0xfaff)
      || (c >= 0xfe30 && c <= 0xfe6f) || (c >= 0xff00 && c <= 0xff60)
      || (c >= 0xffe0 && c <= 0xffe6))) ? 2 : 1
  }
  return w
}

const pad = (s: string, w: number, align: 'left' | 'center' | 'right'): string => {
  const gap = Math.max(0, w - width(s))
  if (align === 'right') return ' '.repeat(gap) + s
  if (align === 'center') {
    const l = Math.floor(gap / 2)
    return ' '.repeat(l) + s + ' '.repeat(gap - l)
  }
  return s + ' '.repeat(gap)
}

/** 表格按列对齐。AI 现在会生成整表（智能表格 / EDA），原始输出的竖线是不齐的，
 * 在源码里根本读不出结构。 */
function formatTable(rows: string[]): string[] {
  const grid = rows.map(cells)
  const sepIdx = rows.findIndex(isSep)
  const aligns = (grid[sepIdx] ?? []).map((c) => {
    const l = c.startsWith(':')
    const r = c.endsWith(':')
    return l && r ? 'center' as const : r ? 'right' as const : 'left' as const
  })
  const cols = Math.max(...grid.map((g) => g.length))
  const widths: number[] = []
  for (let i = 0; i < cols; i++) {
    widths[i] = Math.max(3, ...grid.map((g, ri) => (ri === sepIdx ? 0 : width(g[i] ?? ''))))
  }
  return grid.map((g, ri) => {
    if (ri === sepIdx) {
      return '|' + widths.map((w, i) => {
        const a = aligns[i] ?? 'left'
        // 三种对齐的分隔行总宽度要一致（w + 2），否则每列的竖线对不齐
        const bar = '-'.repeat(Math.max(1, w))
        return a === 'center' ? `:${bar}:` : a === 'right' ? ` ${bar}:` : ` ${bar} `
      }).join('|') + '|'
    }
    return '| ' + widths.map((w, i) => pad(g[i] ?? '', w, aligns[i] ?? 'left')).join(' | ') + ' |'
  })
}

/** 中西文之间补一个空格（中文排版通行做法）。**代码、链接、URL 里不动**。 */
function cjkSpacing(s: string): string {
  const parts = s.split(/(`[^`]*`|\[[^\]]*\]\([^)]*\)|https?:\/\/\S+)/g)
  return parts.map((p, i) => {
    if (i % 2) return p                          // 分隔捕获组：代码/链接原样
    return fixBoldPunct(p)
      .replace(/([一-鿿぀-ヿ])([A-Za-z0-9])/g, '$1 $2')
      .replace(/([A-Za-z0-9])([一-鿿぀-ヿ])/g, '$1 $2')
  }).join('')
}

/** 「**依赖链：**容量」→「**依赖链**：容量」。闭合 ** 前面是标点、后面紧跟汉字时
 *  CommonMark 不认它是闭合，整段渲染成裸星号（实拍）。跟后端
 *  editor/textshape.fix_bold_punct 同一条规则。 */
export function fixBoldPunct(s: string): string {
  return s.replace(/\*\*([^*\n]+?)([：:，,。；;！!？?、）)])\*\*/g, '**$1**$2')
}

/** 一个块属于哪一类。**markdown 的块级结构靠空行分隔**——类型一变就必须
 * 空一行，否则不只是难看，是会解析错：
 *   · 引用块紧跟列表项 → 被当成那一项的延续（lazy continuation）
 *   · HTML 块后面紧跟文字 → 那行文字被吞进 HTML 块，**根本渲染不出来**
 *   · 无序列表紧接有序列表 → 两个列表粘成一个
 * 这几条都是拿这个 app 自己会生成的内容（audio 标签、AI 表格）跑出来的。
 */
type Kind = 'blank' | 'heading' | 'para' | 'ul' | 'ol' | 'quote' | 'table' | 'code' | 'html'

const HTML_BLOCK = /^\s*<\/?[a-zA-Z][^>]*>/

export function formatMarkdown(src: string): string {
  const out: string[] = []
  let prev = 'blank' as Kind

  /** 推一个块进去，需要的话先补一个空行。 */
  const push = (kind: Kind, lines: string[]) => {
    if (!lines.length) return
    const needBlank = prev !== 'blank' && (
      kind !== prev
      // 同类型之间也要空行的：标题、表格、代码块、HTML 块各自独立成块
      || kind === 'heading' || kind === 'table' || kind === 'code' || kind === 'html'
    )
    if (needBlank && out.length && out[out.length - 1].trim()) out.push('')
    out.push(...lines)
    prev = kind
  }

  for (const seg of splitFences((src ?? '').replace(/\r\n?/g, '\n').split('\n'))) {
    if (seg.code) {
      // 代码块前后各留一个空行，块内一个字都不动
      push('code', seg.lines.map((l) => l.replace(/\s+$/, '')))
      continue
    }
    let i = 0
    const lines = seg.lines
    // 这一段里列表出现过的缩进宽度（升序）。空行隔断的两段列表各算各的。
    let indents: number[] = []
    while (i < lines.length) {
      const raw = lines[i]
      const line = raw.replace(/\s+$/, '')

      // 表格：连续的 | 开头的行整块处理
      if (/^\s*\|/.test(line)) {
        const rows: string[] = []
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i].trim()), i++
        if (rows.length >= 2 && isSep(rows[1])) push('table', formatTable(rows))
        else push('para', rows)                  // 不是合法表格就别乱动
        continue
      }
      i++

      if (!line.trim()) { prev = 'blank'; out.push(''); indents = []; continue }

      // 标题：`#标题` → `# 标题`，独立成块
      const h = /^(#{1,6})\s*(.*)$/.exec(line)
      if (h) { push('heading', [`${h[1]} ${cjkSpacing(h[2].trim())}`]); continue }

      // 引用
      if (/^\s*>/.test(line)) {
        push('quote', [line.replace(/^(\s*>+)\s?/, (_m, g) => g.trim() + ' ').trimEnd()])
        continue
      }

      // HTML 块（这个 app 自己会插 <audio>）
      if (HTML_BLOCK.test(line)) { push('html', [line.trim()]); continue }

      // 列表：统一用 -，缩进按 2 空格一级；有序列表统一 `1.`
      const li = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line)
      if (li) {
        // **层级按缩进宽度推断，不用固定除法。** 有人用 2 空格一级、有人用 4，
        // 写死 /2 的话「4 空格的一级」会被当成二级，格式化把用户的结构改了。
        const w = li[1].replace(/\t/g, '  ').length
        if (!indents.includes(w)) { indents.push(w); indents.sort((a, b) => a - b) }
        const level = indents.indexOf(w)
        const ordered = /^\d/.test(li[2])
        const marker = ordered ? li[2].replace(/\)$/, '.') : '-'
        // 嵌套的子项跟父列表算同一块（不补空行），顶层换了类型才补
        const kind: Kind = ordered ? 'ol' : 'ul'
        if (level > 0 && (prev === 'ul' || prev === 'ol')) {
          out.push('  '.repeat(level) + marker + ' ' + cjkSpacing(li[3].trim()))
        } else {
          push(kind, ['  '.repeat(level) + marker + ' ' + cjkSpacing(li[3].trim())])
        }
        continue
      }

      push('para', [cjkSpacing(line.replace(/^\s+/, (m) => m.replace(/\t/g, '  ')))])
    }
  }
  // 连续空行压成一个，首尾清干净，结尾留一个换行
  return out.join('\n').replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '').replace(/\s+$/, '') + '\n'
}
