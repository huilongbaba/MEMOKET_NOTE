/**
 * 一篇笔记显示成什么名字。树、标签页、面包屑都用这一个——三处各算一遍就会
 * 出现「树上叫 A、标签上叫 未命名」。
 *
 * 旧界面建笔记时把标题填成了「未命名」，真实库里 18 篇有 15 篇是这个值。
 * 一列二十个「未命名」没法用，所以这种情况退回正文首行。
 *
 * **只在显示这一层做，不改库里的值**：把它当真标题写回去，就等于替用户
 * 给笔记起了名，而他可能只是还没想好。
 */
export const PLACEHOLDER = new Set(['', '未命名', 'Untitled', 'note'])
export const isPlaceholderTitle = (t: string) => PLACEHOLDER.has((t ?? '').trim())

export function displayTitle(n: { title?: string; preview?: string; content?: string }): string {
  const t = (n.title ?? '').trim()
  if (!PLACEHOLDER.has(t)) return t
  const firstLine = (n.preview ?? n.content ?? '')
    .split('\n')
    .map((l) => l.trim().replace(/^#+\s*/, '').trim())     // 先 trim：整篇缩进的笔记「    # 标题」不然会显示成「# 标题」
    .find((l) => l.length > 0)
  return firstLine ? clipTitle(firstLine) : '未命名'
}

/** 正文首行当标题时截到第一个句读：「今天跟供应商确认了 PCBA 样品的交期，4 月 10 日拿到手板之后再定…」
 *  标签页上读起来像一句话不像标题（第 316 轮实拍）。句读太靠前（< 8 字）就不在那里截，退回 60 字硬截。 */
export function clipTitle(line: string, max = 60): string {
  // 按出现顺序找第一个「够格」的句读：句号（。！？）只要不在开头一两个字就算；
  // 逗号 / 分号 / 冒号太靠前（< 8 字）截出来不成标题（「好的，那就这么定了」「APP定义：先锚定范围」），跳过找下一个
  for (const m of line.matchAll(/[。！？；，,：:]/g)) {
    const min = /[。！？]/.test(m[0]) ? 2 : 8
    if (m.index >= min) return line.slice(0, Math.min(m.index, max))
  }
  return line.slice(0, max)
}
