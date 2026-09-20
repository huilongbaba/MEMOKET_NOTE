// P40 步骤脚本共用的几个量具。
//
// **「看到 ≠ 真在正文里」**（P35 栽的第四次）：`.cm-content.innerText` 会把**占位块 widget
// 的字**算进正文——形状闸明明拦住了，探针却报「正文里有那串 JSON」。所以正文一律逐
// `.cm-line` 读，再拿状态栏那个字数对一遍。
//
// **「选不到 ≠ 没有」**（P17/P31/P35 各栽四次）：选不到先换选择器，别当成「这个东西没有」。

export const DOC_JS = `(() => {
  const lines = Array.from(document.querySelectorAll('.cm-content .cm-line'))
  if (!lines.length) return null
  return lines.map((l) => l.textContent ?? '').join('\\n')
})()`

/** 真正落在文档里的正文（不含占位块 widget）。 */
export async function docText(d) { return d.eval(DOC_JS) }

// ── 状态栏那个字数 ────────────────────────────────────────────────────────────
//
// ## P70 问题 #2：这条正则太窄，截图上白纸黑字写着「1072 字」，脚本读回 `null`
//
// 老写法是 `/^\s*\d+\s*字\s*$/`，配 `document.querySelectorAll('*')` 里
// `children.length === 0` 的叶子——**要求那个叶子整串只有「N 字」**。
// 而 `App.tsx` 状态栏那一格真长这样（`wordCount(content) > 0` 时后半句一定在）：
//
//     {current && <span className="muted">{wordCount(content)} 字{wordCount(content) > 0 && <> · 约 {readingMinutes(…)} 分钟</>}</span>}
//
// 渲染出来是 `1072 字 · 约 4 分钟`（React fragment 不建元素，所以它**确实**是
// 一个 `children.length === 0` 的叶子，选是选中了）——是 `$` 那个锚点当场落空，
// 回了 `null`。而 `null` 跟「状态栏压根没有这一格」读起来一模一样：
// **「选不到 ≠ 没有」的第五张脸，判据比产品窄**（同 P70 §问题 #2 / P69 合并那两次 `strings`）。
//
// 新写法两件事一起定死：
//  ① **射程锚在 `.status-bar` 上**，不在整页。判据宁可窄：`RevisionHistoryPanel`
//     （`{r.chars} 字`）/ `TrashPanel`（`{it.chars} 字`）/ `ChangeLayersPanel`
//     （`+{delta} 字`）/ `DocumentOutline`（`· {s.words} 字`）/ `KbNoteView`
//     （`展开全文（N 字）`）全页都在摆「N 字」——不锚射程就会静默读回**别人那一格**。
//  ② 正则只要求「数字 + 字」**贴在一起**，后面爱跟什么跟什么。
//
// 例 / 反例在 `STATUS_WORDS_CASES`，闸是 `scripts/check-walkthrough-runnable.mts`
// ——那条闸里**还留着老正则当反例**：老正则要是也能过第一条，这条闸就没在核任何东西。

/** 「N 字」贴在一起就算数；后面跟不跟「· 约 N 分钟」不管。射程由调用方锚死。 */
export const STATUS_WORDS_RE = /\d[\d,]*\s*字/

/** `[状态栏整串, statusWords() 该读回什么]`。**第一条是 P70 那张截图上的原话。** */
export const STATUS_WORDS_CASES = [
  // 真界面上的原话（P70 第十四次走查，老用户那一趟，同屏截图写着 1072 字）。**老正则在这一条上回 null。**
  ['1072 字 · 约 4 分钟', '1072 字'],
  // 刚新建、一个字都没有：`wordCount(content) > 0` 那半句不渲染，只剩「0 字」。
  ['0 字', '0 字'],
  // 左半边先有面包屑 / 后台 job 那一行时，整串是拼起来的（字数那一格在最后）。
  ['482 篇笔记 存入知识库中… 第 2/7 块 · 还要约 40 秒 · 已抽出 12 条 1072 字 · 约 4 分钟', '1072 字'],
  // 没开笔记时那一格整个不渲染（`{current && …}`）——**读回 null 是对的**，不是缺陷。
  ['482 篇笔记', null],
  ['还没配模型 · 去设置', null],
  // 反例：别把「N 分钟」「N 条」「N 块」「N 篇」当成字数。
  ['约 4 分钟', null],
  ['已抽出 12 条', null],
  ['第 2/7 块', null],
]

/** 状态栏那一整条的原话（`innerText`，空白压平）。**选不到就抛**：`.status-bar` 不在
 *  说明这不是 MEMOKET NOTE 的主界面（或者壳没起全），那不是一条「产品缺陷」的读数。 */
export async function statusBarText(d) {
  const t = await d.eval(`(() => {
    const b = document.querySelector('.status-bar')
    return b ? (b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim() : null
  })()`)
  if (t === null) throw new Error('statusBarText: 页面上没有 .status-bar —— 这不是主界面，别把它读成「字数那一格没了」')
  return t
}

/** 状态栏那个字数（界面自己报的数，用来跟 docText 对一遍）。没开笔记时那一格不渲染 → `null`。 */
export async function statusWords(d) {
  const m = STATUS_WORDS_RE.exec(await statusBarText(d))
  return m ? m[0].replace(/\s+/g, ' ').trim() : null
}

/** 同上，只是给个数（`'1072 字'` → `1072`）。 */
export async function statusWordCount(d) {
  const s = await statusWords(d)
  return s === null ? null : Number(s.replace(/[^\d]/g, ''))
}

/** 页面上所有可见文字（找一句话在不在界面上）。 */
export async function pageText(d) {
  return d.eval(`document.body.innerText.replace(/\\n{3,}/g, '\\n\\n')`)
}

export async function has(d, s) {
  const t = await pageText(d)
  return t.includes(s)
}

/** toast 那一摞。 */
export async function toasts(d) {
  // P62 ①：通配会把外层容器 `.toaster` 一起选中（那个串里含 `toast`），
  // 一条读回来是两条一模一样的字。走公共那份精确选择器。
  return d.toasts()
}

export const wait = (ms) => new Promise((r) => setTimeout(r, ms))

/** 等到 fn() 为真（或超时）。**别用固定 sleep**——P17 那次「等够 14s 再读日志」就是这么来的。 */
export async function until(fn, ms = 20000, step = 250) {
  const t0 = Date.now()
  for (;;) {
    const v = await fn()
    if (v) return v
    if (Date.now() - t0 > ms) return null
    await wait(step)
  }
}
