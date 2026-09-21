/** **一份走查日志的出处**：拼它的那两句，和认它的那两条正则，**在这一个文件里**（P97 A / P99 A）。
 *
 * 为什么单独一份：写的那一头在 `cdp.mjs`（跑的时候打头两行），认的那一头在
 * `scripts/check-walkthrough-provenance.mts`（入库之后核）。两头各写一份格式串的话，
 * 改一头忘了另一头 = **闸从此全红或者全绿，而且看不出来是哪一种**
 * （`whoami.mjs` 那一份就是为同一件事分出来的：抄得到的地方就会被抄）。
 *
 * 这两行长什么样、为什么有它们，见 `check-walkthrough-provenance.mts` 顶上那一段。
 *
 * ── P99 A 补的那一格 ──────────────────────────────────────────────────────
 * P97 只钉了**入口那一份**步骤脚本，自己写着射程：被 import 的 `lib*.mjs` /
 * `clickexact.mjs` 没钉，`cdp.mjs` 自己也没钉。这一批补上，补法是**第二行**：
 *
 *     依赖: cdp.mjs=<64 位> provenance.mjs=<64 位> steps/lib.mjs=<64 位> …
 *
 * **判据宁可窄**：这一行上的每一份，都是**从入口和驱动出发、顺着相对 import 一步步够得到的**
 * ——不是「把 `walkthrough/` 目录哈希一遍」。目录里躺着 30 多份别的步骤脚本，
 * 整目录哈希等于「隔壁那一步改了一行，这一批的日志全红」，那是一条天天误报的闸，
 * 而**一条天天误报的闸迟早被人改成不红**。
 */
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { basename, dirname, relative, resolve } from 'node:path'

/** 日志**第一行**的形状。**两头都钉死**：行首行尾各一个锚点，中间只认 `.mjs` + 64 位十六进制。 */
export const HEAD_RE = /^步骤脚本: ([A-Za-z0-9_.-]+\.mjs) sha256=([0-9a-f]{64})$/

/** 日志**第二行**的形状（P99 A）。**两头一样钉死**，中间是 `<相对路径>=<64 位>` 用单空格隔开。
 *
 * 路径是相对 `frontend/scripts/walkthrough/` 写的（`cdp.mjs` / `steps/lib.mjs`），
 * **一个 `..` 都不许有**：认的那一头按这个根去找文件，`..` 一出现射程就漏到工具箱外面去了。
 * 这一条**不写在正则里**（正则写「不含某个子串」写不利索），写在 `parseDeps()` 里，
 * **例 / 反例各一条钉着**。 */
export const DEPS_RE = /^依赖: ([A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*\.mjs=[0-9a-f]{64}(?: [A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*\.mjs=[0-9a-f]{64})*)$/

const sha = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')

/** 拼第一行。**读的是这一刻真读进来的那个文件的字节**，不是文件名、不是 git 里那一份。 */
export function stepProvenance(p) {
  return `步骤脚本: ${basename(p)} sha256=${sha(p)}`
}

/** 一份 `.mjs` 源码里，**相对 import** 的那几个 specifier。
 *
 * ⚠️ **「文件里有这个串」≠「这段代码还在跑」**：这几份文件顶上都压着整段中文注释，
 * 里头照样出现 `from './lib.mjs'` 这种串。所以**先把整行注释剔掉再找**
 * （跟 `check-walkthrough-provenance.mts` 里 `checkWriter()` 同一个剔法）。
 *
 * 认三种写法：`… from '<x>'` / `import('<x>')` / `import '<x>'`。
 * **只收 `.` 开头的**——`node:fs` 那种不是这个仓库的字节，钉了也没意义。 */
export function relImports(src) {
  const code = String(src).split('\n').map((l) => (/^\s*(\/\/|\*|\/\*)/.test(l) ? '' : l)).join('\n')
  const out = []
  for (const re of [/\bfrom\s*['"]([^'"]+)['"]/g, /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g, /\bimport\s+['"]([^'"]+)['"]/g]) {
    for (const m of code.matchAll(re)) if (m[1].startsWith('.')) out.push(m[1])
  }
  return [...new Set(out)]
}

/** 从几个起点出发，顺着相对 import 一步步够到的**全部**本地模块（含起点自己）。
 *
 * 回的是**相对 `root` 的路径**，排过序。够到 `root` 外头去 ⇒ **当场抛**：
 * 那说明工具箱的形状变了，得有人来看一眼——不静默把射程放宽，也不静默收窄。 */
export function importClosure(entries, root) {
  const seen = new Map()
  const stack = entries.map((p) => resolve(p))
  while (stack.length) {
    const p = stack.pop()
    if (seen.has(p)) continue
    const rel = relative(resolve(root), p)
    if (rel.startsWith('..')) throw new Error(`出处：\`${p}\` 在工具箱 \`${root}\` 外头——射程该有多远得有人来定，不静默放宽`)
    seen.set(p, rel)
    for (const spec of relImports(readFileSync(p, 'utf8'))) stack.push(resolve(dirname(p), spec))
  }
  return [...seen.values()].sort()
}

/** 拼第二行（P99 A）：**入口和驱动这一趟真读进来的那些字节**，入口自己不在里头（它在第一行）。 */
export function depsProvenance(stepPath, driverPath, root) {
  const entry = resolve(stepPath)
  const list = importClosure([entry, resolve(driverPath)], root).filter((rel) => resolve(root, rel) !== entry)
  return `依赖: ${list.map((rel) => `${rel}=${sha(resolve(root, rel))}`).join(' ')}`
}

/** 认第一行。**只认第一行**：出现在中间等于「跑完之后有人往里贴了一行」。 */
export function parseHead(text) {
  const m = HEAD_RE.exec(String(text).split('\n')[0] ?? '')
  return m ? { step: m[1], sha: m[2] } : null
}

/** 认第二行。**只认第二行**，理由跟第一行一样。`..` 一个都不许有（见 `DEPS_RE` 那一段）。 */
export function parseDeps(text) {
  const m = DEPS_RE.exec(String(text).split('\n')[1] ?? '')
  if (!m) return null
  const out = {}
  for (const pair of m[1].split(' ')) {
    const i = pair.lastIndexOf('=')
    const rel = pair.slice(0, i)
    if (rel.split('/').includes('..')) return null
    out[rel] = pair.slice(i + 1)
  }
  return out
}
