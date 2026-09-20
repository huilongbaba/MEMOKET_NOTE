/**
 * 「我连的是谁」——开局核一次，对不上就吵（P45 #2 / P44 问题 #2）。
 *
 * ## 这条修的是什么
 *
 * P44 实拍：同一台机上开第二份 app，第二个窗口连到了**第一份的后端**上。
 * 日志里写着「后端崩了，重新拉起」「固定端口 47231 被占，改用 47232」，
 * 可窗口的 `location.origin` 还是 `http://127.0.0.1:47231`——那是另一份实例的
 * 后端，于是这一屏摆的是**别人的库**（读出来「P43 走查（可删）」和「20 层」，
 * 而自己这份库是 483 篇 / 1 层）。**两个窗口写同一个库是数据级的后果。**
 *
 * 壳那一侧已经改了两处：重拉后端之后按新端口 `loadURL`（`desktop/src/main.ts`），
 * 起后端时按 pid 核「这个端口上的是不是我的子进程」（`desktop/src/backend.ts`）。
 * 这个文件是**第三道**，也是最后一道：**界面自己再核一遍**。
 *
 * ## 为什么界面也要核
 *
 * P44 教训 #2 原话：「壳里有几个可执行件就得核几个」不够，还得核「窗口连的是
 * 哪个后端」——**核到「这一屏上的字是不是这个库里的」为止**。前两道守的是壳的
 * 行为，这一道守的是**结果**：不管中间哪一步出了岔子（手工改地址、旧窗口被系统
 * 恢复、将来某次重构又把 `loadURL` 写回 `reload`），只要这一屏连错了后端，
 * 这里就当场说出来。而 P44 是靠 `lsof` 才发现的——**那个能力该在产品里。**
 *
 * ## 判据宁可窄
 *
 * 只在**三样都拿得到、而且明确不一致**时才吵：
 *   · 不在桌面壳里（网页版）→ 不吵（没有「该连谁」这个概念）；
 *   · 壳还没起好后端（`backendInfo()` 回 null）→ 不吵；
 *   · 后端没报 `backend.pid`（旧版后端 / 别人的服务）→ **端口那一格照样核**，
 *     pid 那一格跳过——`undefined !== 47231` 这种比较是在拿「不知道」当「不一样」。
 * 端口和 pid **各自**判，各自说话：端口对不上是「窗口指错了地方」，
 * pid 对不上是「这个端口上坐的是另一个进程」，两句话指向的修法不一样。
 */

export type ShellBackend = { port: number; pid: number; dataDir: string }
export type HealthWho = { pid?: number; data_dir?: string; started_at?: string }

export type Mismatch = { kind: 'port' | 'pid'; text: string }

/** 纯函数，好测：壳说该连谁 + 这一屏实际连上了谁 → 对不上的那几条。 */
export function compareIdentity(
  shell: ShellBackend | null | undefined,
  pageOrigin: string,
  who: HealthWho | null | undefined,
): Mismatch[] {
  if (!shell) return []                       // 网页版 / 壳还没起好：没有「该连谁」
  const out: Mismatch[] = []
  const port = Number(new URL(pageOrigin).port || 0)
  if (port && shell.port && port !== shell.port) {
    out.push({
      kind: 'port',
      text: `这个窗口连的是 127.0.0.1:${port}，可这份 app 自己的后端在 ${shell.port}。`
        + `屏幕上这些笔记多半是同机另一份 memoket-NOTE 的——别在这儿编辑，先把这个窗口关掉。`,
    })
  }
  // **`pid` 拿不到就不判**：旧版后端没有这一格，把「不知道」读成「不一样」
  // 会让每个升级到一半的用户都看见一条假警报（§21「判据宁可窄」）。
  const theirs = Number(who?.pid ?? 0)
  if (theirs && shell.pid && theirs !== shell.pid) {
    out.push({
      kind: 'pid',
      text: `这个端口上应答的后端是进程 ${theirs}，而这份 app 起的是 ${shell.pid}。`
        + `两份实例在写同一个库——先把其中一个关掉。`,
    })
  }
  return out
}

/** 吵出来。**用最笨的那一种**：一条钉在窗口顶上、点不掉的横幅。
 *
 * 不走 toast：toast 会自己消失，而「你正在编辑别人的库」这件事**不该自己消失**。
 * 不走 React：这条得在 App 之外活着（App 自己也在读那个连错的后端），
 * 而且这一批不碰 `App.tsx`（另一个 agent 的地盘）。
 */
function shout(lines: string[]) {
  const id = 'memoket-wrong-backend'
  if (document.getElementById(id)) return
  const bar = document.createElement('div')
  bar.id = id
  bar.setAttribute('role', 'alert')
  // 颜色 / 层级 / 字号一律走令牌（`docs/UI_SPEC.md` §1，`check-ui-tokens` 盯着）：
  // `--live` 是这套设计里的那一枚红，`--z-toast` 是「永远在最上面」那一层
  // ——这条横幅要的正是那两样。
  bar.style.cssText = [
    'position:fixed', 'inset:0 0 auto 0', 'z-index:var(--z-toast)',
    'padding:var(--s-3) var(--s-5)', 'font-size:var(--t-sm)', 'line-height:1.5',
    'background:var(--live)', 'color:#fff', 'white-space:pre-wrap',
  ].join(';')
  bar.textContent = '⚠︎ 连错后端了\n' + lines.join('\n')
  document.body.appendChild(bar)
}

/** 开局核一次。失败（拿不到 health / 没有壳）一律安静返回——**自检不承重**。 */
export async function checkBackendIdentity(
  fetchHealth: () => Promise<{ backend?: HealthWho } | null> = defaultHealth,
): Promise<Mismatch[]> {
  let shell: ShellBackend | null = null
  try {
    shell = (await window.memoketDesktop?.backendInfo?.()) ?? null
  } catch { return [] }
  if (!shell) return []
  let who: HealthWho | null = null
  try {
    who = (await fetchHealth())?.backend ?? null
  } catch { who = null }
  const bad = compareIdentity(shell, location.origin, who)
  if (bad.length) {
    shout(bad.map((m) => m.text))
    // 落盘一份：用户截图里只有那条横幅，日志里得有「谁对谁」
    try {
      const { clientLog } = await import('../api')
      void clientLog('error', bad.map((m) => `${m.kind}: ${m.text}`).join(' | '), '', 'backend-identity')
    } catch { /* 连错后端时这一条本来就可能发不出去 */ }
  }
  return bad
}

async function defaultHealth(): Promise<{ backend?: HealthWho } | null> {
  const r = await fetch('/api/health')
  if (!r.ok) return null
  return (await r.json()) as { backend?: HealthWho }
}
