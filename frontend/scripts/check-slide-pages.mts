/** 幻灯片分页：前端预览那份（TS）和后端判据那份（Python）必须切出同样的页。
 *
 * 两边漂了的后果是「判据说 24 页、预览画出 26 页」——而判据的每一条（引用覆盖、
 * 一页太挤、整节漏掉）都是按页算的，页数一错整组数都不对。
 *
 *     npx tsx scripts/check-slide-pages.mts
 */
import { execFileSync } from 'node:child_process'

import { slidePages } from '../src/util/slidePages'

const CASES: { why: string; md: string }[] = [
  { why: 'front-matter 不算一页', md: '---\nmarp: true\nslides: true\n---\n\n# 标题\n\n---\n\n## 第二页\n' },
  { why: '没有 front-matter 也认', md: '# 一\n\n---\n\n## 二\n\n---\n\n## 三\n' },
  { why: '代码块里的横线不算分页符', md: '# 一\n\n```yaml\na: 1\n---\nb: 2\n```\n\n---\n\n## 二\n' },
  { why: 'mermaid 块里的横线也不算', md: '# 一\n\n```mermaid\ngraph TD\nA-->B\n```\n\n---\n\n## 二\n' },
  { why: '连着两个分页符不算出一页空的', md: '# 一\n\n---\n\n---\n\n## 二\n' },
  { why: '结尾的分页符后面没东西', md: '# 一\n\n---\n' },
  { why: '空的', md: '' },
  { why: '只有 front-matter', md: '---\nslides: true\n---\n' },
]

const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from app.harness.checks.slides import split_pages
print(json.dumps([len(split_pages(m)) for m in json.load(sys.stdin)]))
`
const venv = new URL('../../backend/.venv/bin/python', import.meta.url).pathname
const got = JSON.parse(execFileSync(venv, ['-c', py], {
  input: JSON.stringify(CASES.map((c) => c.md)), encoding: 'utf8',
})) as number[]

let bad = 0
CASES.forEach((c, i) => {
  const ts = slidePages(c.md).length
  const ok = ts === got[i]
  console.log(`${ok ? '✓' : '✗'} ${c.why}${ok ? '' : `　TS ${ts} / PY ${got[i]}`}`)
  if (!ok) bad++
})
console.log(bad ? `${bad} 处两边对不上` : `${CASES.length} 个用例，预览和判据切出同样的页数`)
process.exit(bad ? 1 : 0)
