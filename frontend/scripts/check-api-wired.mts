/** 每一条 API 都得有人调——**「建好了、测过了、用户够不着」是这个仓库反复出的一种 bug**。
 *
 * 第 665 轮手工查了一遍：132 条路由里六条前端一次都没调过，全是有注释、有测试的
 * 诊断能力，只是没有任何入口。其中 `kb/quality` 那条给的是「全库 16% 的事实形状上
 * 就用不上」——一个直接解释「为什么召回有时候给我一堆废话」的数字，而用户看不到。
 *
 * 手工查一次没用，下次还会长出来，所以做成门禁。另一半同样重要：
 * **名单里的东西一旦真接上了就要从名单里删掉**——一份过期的豁免名单比没有名单更糟，
 * 它会把新长出来的问题藏在里面。所以两个方向都判。
 *
 *     npx tsx scripts/check-api-wired.mts
 */
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/** 有意不接前端的。**每一条都要写清楚为什么**，不然它就只是「懒得接」的遮羞布。 */
const INTENTIONAL: Record<string, string> = {
  '/api/kb/coverage': '碎片化诊断（主题中位数 / 小主题占比）——给开发看的，不是给用户看的',
  '/api/kb/quality': '全量明细（含「数字原文里查不到」的反例）给诊断用；首页那一格只给了一个比例，明细要不要给用户看还没定',
  '/api/kb/quality/judged': '要花模型调用去判抽取质量；确定性那一半已经接到首页「能用的事实」了',
  '/api/kb/rebuild': '两个 codebook 之间的迁移工具（source → writing），不是日常功能',
  '/api/kb/rebuild/pending': '同上',
  '/api/memory/timeline': '跟树上的「时间线」重复，那边已经有页面',
}

const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(new URL('../../backend', import.meta.url).pathname)})
from app.main import app
def walk(routes):
    for r in routes:
        orig = getattr(r, "original_router", None)
        if orig is not None:
            yield from walk(orig.routes)
        elif getattr(r, "routes", None):
            yield from walk(r.routes)
        elif getattr(r, "path", None):
            yield r.path
# 导入 app.main 会往 stdout 打启动日志（「托管前端：…」），会把 JSON 弄脏。
# 用一个记号把真正的输出框起来，调用方只取记号之间的那一段。
print("<<<ROUTES")
print(json.dumps(sorted({p for p in walk(app.routes) if p.startswith("/api")})))
print("ROUTES>>>")
`
const venv = new URL('../../backend/.venv/bin/python', import.meta.url).pathname
const raw = execFileSync(venv, ['-c', py], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
const routes = JSON.parse(raw.split('<<<ROUTES')[1].split('ROUTES>>>')[0].trim()) as string[]

function read(dir: string): string {
  let out = ''
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out += read(p)
    else if (/\.tsx?$/.test(name)) out += readFileSync(p, 'utf8')
  }
  return out
}
const src = read(new URL('../src', import.meta.url).pathname)

// 路径里 `{param}` 之前那一截必须原样出现在前端源码里（模板串拼的也算）
const head = (p: string) => p.split('{')[0].replace(/\/$/, '')

let bad = 0
const missing = routes.filter((p) => head(p) && !src.includes(head(p)) && !(p in INTENTIONAL))
for (const p of missing) { console.log(`✗ ${p} —— 后端有，前端没人调，也不在有意不接的名单里`); bad++ }

const stale = Object.keys(INTENTIONAL).filter((p) => src.includes(head(p)))
for (const p of stale) { console.log(`✗ ${p} —— 已经接上了，从 INTENTIONAL 名单里删掉（过期的豁免名单会藏住新问题）`); bad++ }

const gone = Object.keys(INTENTIONAL).filter((p) => !routes.includes(p))
for (const p of gone) { console.log(`✗ ${p} —— 这条路由已经不存在了，名单该跟着删`); bad++ }

console.log(bad ? `${bad} 处要处理` : `${routes.length} 条 API 都有人调（${Object.keys(INTENTIONAL).length} 条有意不接，理由写在脚本里）`)
process.exit(bad ? 1 : 0)
