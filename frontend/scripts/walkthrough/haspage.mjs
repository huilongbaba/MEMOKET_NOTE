// 壳的窗口起来了没有：CDP 应答**而且**真有一个 page target。
//
// 光有 `/json/version` 不够——那一刻窗口还没建出来，下一条 cdp.mjs 就会
// 「没有 page target: []」，看起来像步骤脚本写错了。
//
// **P58 加的那个 3 秒超时**：上一趟一个**别的批次留下的壳**占着这个端口、
// 接受连接却不回，这里的 `fetch` 于是永远挂着 —— `go.sh` 那个 45 次的循环
// 第一次就卡死，看起来像「壳起不来」，其实是量具自己挂了。
// **一个会永远挂着的探针不是探针。**
//
// **P74 从 scratch 搬进仓库**（P72 留的第 ① 条）。搬进来之后一个字节没动。
// 假壳那条路（`scripts/run-walkthrough-fakeshell.mjs`）把同一段逻辑内联了一份
// ——那边要的是「等到起来为止」的循环，这边是「问一次，退出码就是答案」，
// 给 shell 循环用。**两边的判据逐字相同**（`type === 'page'` 且 url 是 127.0.0.1）。
//
// usage: node haspage.mjs <cdp-port>   → 0 有窗口（打印 url）/ 1 还没有 / 2 端口不应答
const port = process.argv[2]
if (!port) { console.error('usage: node haspage.mjs <cdp-port>'); process.exit(64) }
let list
try {
  list = await (await fetch(`http://127.0.0.1:${port}/json`, { signal: AbortSignal.timeout(3000) })).json()
} catch (e) { console.error('CDP 不应答：' + e.message); process.exit(2) }
const page = list.find((t) => t.type === 'page' && /127\.0\.0\.1:\d+/.test(t.url))
if (!page) { console.error('还没有 page target'); process.exit(1) }
console.log(page.url)
