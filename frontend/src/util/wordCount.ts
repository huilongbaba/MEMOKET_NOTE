/** 字数：一处定义。实拍信息面板「8449 字 · 约 21 分钟」、状态栏「8874 字 · 约 22 分钟」
 * 同一篇两个数——一个数 `content.length`（连空格换行都算），一个先去空白。
 * 统一为：去掉空白、markdown 记号（井号/列表符/强调星号/表格竖线）和 `[user-n-hex]`
 * 引用标记后的字符数；阅读速度按中文 400 字/分钟。 */
/** `[user-n-hex]` 引用标记。相关记忆的字数门槛也要先去掉它：实拍「据 [terrence-1872-5F8] 所述。」
 * 4 个字被 id 撑过 8 字门槛，右栏召回了五条不相干的事实。 */
/** 引用 id 正则的唯一源（带捕获组）。跟后端 store._CITE / checks/citations / prompts/fragments 三处同步；
 *  前端 factCite.ts 的高亮和 App 的「引用了哪些事实」都从这里拿，不再各抄一份。 */
export const CITE_RE_SOURCE = String.raw`\[([A-Za-z][A-Za-z0-9_-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+)\]`
export const CITATION_RE = new RegExp(CITE_RE_SOURCE, 'g')
/** 正文里引用了哪些事实 id（去重、按首次出现顺序）。跟后端 `store.cited_fact_ids` 同一条正则——
 *  两边认的不是同一批，ribbon 的角标和树上的 ◆ 就会对不上。 */
export const citedFactIds = (s: string): string[] => Array.from(new Set(Array.from(s.matchAll(CITATION_RE), (m) => m[1])))
export const stripCitations = (s: string) => s.replace(CITATION_RE, '').replace(/[ \t]{2,}/g, ' ')

/** 拿去召回 / 判关系之前的正文：去掉引用标记、整条图片、链接地址（只留链接文字）。
 * 实拍拖一张图进空笔记，右栏立刻冒出 Bill Browder / Russia 的英文事实——查询词就是那行
 * `![probe](/api/assets/…png)`，「assets」撞上了「assets of Russia frozen」。 */
export const stripForRecall = (s: string) => stripCitations(
  s.replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1'))

export function wordCount(content: string): number {
  return content
    // 图片整条不算（alt 里常是几千字的生成提示词——实拍一篇几百字的笔记显示 27779 字）；
    // 链接只算显示文字，不算地址
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(CITATION_RE, '')
    // 表格分隔行 |---|:--:| 整行是记号（格式化把它们对齐补宽之后字数曾从 7760 跳到 8241）
    .replace(/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/gm, '')
    .replace(/^\s*(#{1,6}|[-*>+]|\d+\.)\s+/gm, '')
    .replace(/[*_`|~]/g, '')
    .replace(/\s+/g, '').length
}

export function readingMinutes(words: number): number {
  return Math.max(1, Math.round(words / 400))
}

/** 正文里某几条引用（`[id]` 连同它前面那个空格）的位置区间，给编辑器一次性删掉用——
 *  只删括号里的 id，句子留着（句子本身没错，错的是依据没了）。区间按位置正序、互不重叠。 */
export function citationRanges(text: string, ids: string[]): { from: number; to: number }[] {
  const want = new Set(ids)
  const out: { from: number; to: number }[] = []
  for (const m of text.matchAll(CITATION_RE)) {
    if (!want.has(m[0].slice(1, -1))) continue
    let from = m.index
    if (from > 0 && text[from - 1] === ' ') from -= 1
    out.push({ from, to: m.index + m[0].length })
  }
  return out
}

/** `[标题](note://id)` 笔记链接的唯一源（m[1] 标题、m[2] id）。跟后端 store._NOTE_LINK 同步。 */
export const NOTE_LINK_RE = /\[([^\]\n]*)\]\(note:\/\/([0-9a-f]{12})\)/g
/** 正文链到了哪些笔记 id（去重、按首次出现顺序）。链接面板的「链出去」「链到的不在了」和 ribbon 角标都从这算。 */
export const linkedNoteIds = (s: string): string[] => Array.from(new Set(Array.from(s.matchAll(NOTE_LINK_RE), (m) => m[2])))

/** 正文里链到某几篇笔记的 `[标题](note://id)`：区间 + 替换成的纯文本（标题）。链到的笔记没了，
 *  链接改成纯文本，字留着。 */
export function noteLinkRanges(text: string, ids: string[]): { from: number; to: number; insert: string }[] {
  const want = new Set(ids)
  const out: { from: number; to: number; insert: string }[] = []
  for (const m of text.matchAll(NOTE_LINK_RE)) {
    if (!want.has(m[2])) continue
    out.push({ from: m.index, to: m.index + m[0].length, insert: m[1] })
  }
  return out
}
