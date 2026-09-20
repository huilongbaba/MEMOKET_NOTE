/** 源码和文档里不许有真的 NUL 字节 —— 因为它会让 `grep` **静默跳过整个文件**（P56 #5⑥）。
 *
 * **这条闸是一次真事故逼出来的，而且那次事故的症状是「什么都没有」。**
 * P52 留给下一批的第 ⑥ 条逐字写着：「轮次卡片那几句 P47 时代的话
 * （「照它改的」/「判词就是下面」）今天在 `frontend/src` 里一个字都搜不到
 * —— 所以这一批量到的 0 次不是缺陷，是那几句已经不在了。」
 *
 * P56 去源码对了一遍：**那几句一直在**（`AgentActivity.tsx`，P33 写进去之后一个字没动过）。
 * 搜不到是因为同一个文件的 `hitKey()` 里拿一个**真的 NUL 字节**当分隔符，
 * `file(1)` 于是把整份 `.tsx` 判成 `data`，而 GNU/BSD `grep` 对二进制文件默认
 * 只说一句「Binary file matches」——带 `-n` / 在 `-r` 里更是**一行都不打**。
 * 于是一次「源码里搜一下」得到了空结果，而空结果被读成了「这几句没了」。
 *
 * 要紧的不是那两个字节，是**「搜不到」和「不存在」在终端里长得一模一样**。
 * 所以判据窄在一件事上：下面这几个目录里**一个 NUL 都不许有**。
 * 要那个值就写转义（反斜杠 + `u0000`），运行期分毫不差。
 *
 * **为什么连 `docs/` 和 `frontend/scripts/` 也扫**：这条闸的第一版只扫
 * `frontend/src` + `desktop/src`，于是它**看不见自己**，也看不见台账——
 * 写它的那一轮就在 `docs/TRACELOG-product.md`、`docs/product-readiness-plan.md`
 * 和这个文件自己里各留了一个 NUL，三个都是闸放过去的。
 * 而「在台账里 grep 一下」正是这个仓每一批都在做的事。
 *
 *     npx tsx scripts/check-greppable.mts
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.join(here, '../..')
const ROOTS = ['frontend/src', 'frontend/scripts', 'desktop/src', 'backend/app',
               'backend/scripts', 'backend/tests', 'docs', 'shared']
const SKIP = new Set(['node_modules', 'dist', '__pycache__', '.vite'])
// `.mjs` 是 P66 加的：走查的公共驱动（`frontend/scripts/walkthrough/cdp.mjs`）搬进仓库了，
// 而这条闸要治的正是「在源码里 grep 一下」——量具进来了，闸得看得见它。
const EXTS = new Set(['.ts', '.tsx', '.mts', '.mjs', '.js', '.jsx', '.css', '.json', '.jsonl',
                      '.md', '.html', '.py'])

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue
    const p = path.join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (EXTS.has(path.extname(name))) out.push(p)
  }
  return out
}

const files = ROOTS.flatMap((r) => walk(path.join(REPO, r)))
// **分母先报出来**：扫了 0 个文件也会「全过」，而那跟真的全过长得一样
// （跟这条闸本身要治的毛病是同一个形状）。
console.log(`扫了 ${files.length} 个源文件 / 文档（${ROOTS.length} 个目录）`)
if (files.length < 600) {
  console.error(`✗ 只扫到 ${files.length} 个文件，太少了 —— 大概是路径错了，不算过`)
  process.exit(1)
}

const bad: string[] = []
for (const f of files) {
  const buf = readFileSync(f)
  const i = buf.indexOf(0)
  if (i >= 0) {
    const line = buf.subarray(0, i).toString('utf8').split('\n').length
    bad.push(`${path.relative(REPO, f)}:${line}`)
  }
}

if (bad.length) {
  console.error(`✗ ${bad.length} 个文件里有真的 NUL 字节，grep 会静默跳过它们：`)
  for (const b of bad) console.error(`    ${b}`)
  console.error('  要那个值就写转义（反斜杠 + u0000）——运行期一模一样，只是文件不再是二进制。')
  process.exit(1)
}
console.log('✓ 一个 NUL 都没有 —— 这几个目录 grep 得动')
