/** 标题为 title 的小节在正文里哪结束：下一个层级不深于它的标题之前，没有就是文末。
 *  跟后端 editor/outline.section_end 同一条规则——定向续写的落点前端按自己的正文算，
 *  后端给的 pos 只在这里找不到标题时兜底。 */
export function sectionEnd(content: string, title: string): number | null {
  const marks: { level: number; title: string; start: number }[] = []
  let inFence = false
  let offset = 0
  // 围栏代码块里的 # 不是标题——逐行扫
  for (const line of content.split('\n')) {
    if (/^\s*(`{3,}|~{3,})/.test(line)) inFence = !inFence
    else if (!inFence) {
      const h = /^(#{1,6})\s+(\S.*?)\s*$/.exec(line)
      if (h) marks.push({ level: h[1].length, title: h[2].trim(), start: offset })
    }
    offset += line.length + 1
  }
  const want = title.trim()
  for (let i = 0; i < marks.length; i++) {
    if (marks[i].title !== want) continue
    for (let j = i + 1; j < marks.length; j++) if (marks[j].level <= marks[i].level) return marks[j].start
    return content.length
  }
  return null
}
