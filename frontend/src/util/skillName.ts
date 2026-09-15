/** 把 skill 名字里结尾那一对括号拆出来。
 *
 *  内置 skill 的名字全长成「生成前确认范围（受 brainstorming 启发）」这样——括号里
 *  是**出处**（这条规则是受 Anthropic 哪个 skill 启发写的），该留着；但它把标题撑长，
 *  而卡片标题在窄窗里是省略号截断的，结果**每一条内置的名字都被从中间切掉**，
 *  切完连右括号都没了：「宁缺毋滥（受 discernment-nudge 的克制…」（第 673 轮实拍）。
 *
 *  名字里最能分辨的是**前面那一截**。把括号摘出来单独放，两样都看得见。
 *  只摘结尾那一对，中间的括号（「校验触发/跳过规则」这种名字里没有，但用户自建的
 *  可能有）不动。 */
export function splitSkillName(raw: string): { head: string; note: string } {
  const name = (raw ?? '').trim()
  const m = /^(.*\S)\s*[（(]([^（()）]*)[）)]$/.exec(name)
  if (!m || !m[1] || !m[2].trim()) return { head: name, note: '' }
  return { head: m[1], note: m[2].trim() }
}
