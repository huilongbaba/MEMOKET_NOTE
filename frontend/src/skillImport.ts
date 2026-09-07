export type ParsedSkill = { name: string; description: string; content: string }

/**
 * 解析第三方 Claude Skill 的 SKILL.md（YAML frontmatter + markdown 正文）。
 * 只处理常见的 "key: value" 单行 frontmatter，外加 YAML 折叠/字面量块标量
 * （"key: >"/"key: |" 后面跟着缩进续行）——真实的 SKILL.md（比如 Anthropic
 * 官方 discernment-nudge）description 字段几乎都是这种写法，不认它解析出来
 * 的就是一个孤零零的 ">" 字符，比留空还误导人。除此之外的复杂 YAML（嵌套
 * 结构、多值列表）不处理，遇到就跳过那个字段，不是要做一个真正的 YAML
 * 解析器，那对 name/description 这两个字段来说是过度工程。
 *
 * 只提取 name/description（填充表单）+ 正文（当 content）。SKILL.md 常见
 * 的 bundled scripts/references 这里天然就丢了——MEMOKET_NOTE 后端调的是
 * 原始 chat completions 接口，没有机制"运行"那些脚本，这是已知的、跟用户
 * 明确同步过的约束，不是这个函数漏做了什么。
 */
export function parseSkillMd(raw: string): ParsedSkill {
  const text = raw.replace(/^﻿/, '').trim()
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) {
    // 没有 frontmatter，整份原文当正文，名称/描述留空让用户自己填
    return { name: '', description: '', content: text }
  }
  const [, frontmatter, body] = match
  const lines = frontmatter.split('\n')
  const fields: Record<string, string> = {}
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^([A-Za-z_][\w-]*):\s*(.*)$/)
    if (!m) continue
    const key = m[1].trim()
    const rest = m[2].trim()
    if (/^[|>][+-]?$/.test(rest)) {
      // 块标量：值在接下来缩进更深的行里，折叠(">")用空格拼接、字面量("|")
      // 保留换行，直到遇到缩进恢复到跟 key 同级（或更浅）的行为止。
      const folded = rest[0] === '>'
      const continued: string[] = []
      let j = i + 1
      while (j < lines.length && (lines[j] === '' || /^\s+\S/.test(lines[j]))) {
        continued.push(lines[j].trim())
        j++
      }
      fields[key] = continued.filter((l) => l !== '').join(folded ? ' ' : '\n')
      i = j - 1
    } else {
      fields[key] = rest.replace(/^["']|["']$/g, '')
    }
  }
  return {
    name: fields.name || '',
    description: fields.description || '',
    content: body.trim(),
  }
}
