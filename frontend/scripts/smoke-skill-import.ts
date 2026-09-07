/**
 * Runtime check for skillImport.ts's parseSkillMd(). Pure function, no DOM,
 * but still worth a permanent test -- the YAML block-scalar bug this guards
 * against was found by fetching a REAL SKILL.md (discernment-nudge, whose
 * `description:` field is written as a ">" folded block scalar, which is
 * the common style for anything longer than one line) and finding the
 * parser produced a literal ">" character instead of the actual text.
 * Fixtures below are frozen copies of the real files' frontmatter shape so
 * this doesn't depend on network access to re-verify.
 *
 *     npx tsx scripts/smoke-skill-import.ts
 */
import { parseSkillMd } from '../src/skillImport'

function assertEqual(actual: unknown, expected: unknown, msg: string) {
  if (actual !== expected) throw new Error(`${msg}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`)
}

// Real shape from github.com/anthropics/skills/skills/discernment-nudge/SKILL.md
const FOLDED_SCALAR = `---
name: discernment-nudge
description: >
  After you give a substantive answer or draft that the user may act on
  — advice or recommendations, drafted artifacts such as goals, plans,
  pitches, proposals, or emails.
license: Complete terms in LICENSE.txt
---

# Discernment nudge

## Why this exists

Body content here.
`

const folded = parseSkillMd(FOLDED_SCALAR)
assertEqual(folded.name, 'discernment-nudge', 'folded scalar: name')
if (folded.description.includes('>')) throw new Error(`folded scalar description still contains a literal ">": ${JSON.stringify(folded.description)}`)
if (!folded.description.startsWith('After you give a substantive answer')) {
  throw new Error(`folded scalar description not assembled correctly: ${JSON.stringify(folded.description)}`)
}
if (folded.description.includes('\n')) throw new Error('">" (folded) should join continuation lines with spaces, not keep newlines')
if (folded.content.includes('---\nname:') || folded.content.includes('license:')) {
  throw new Error('frontmatter leaked into content')
}
console.log('OK: ">" (folded) YAML block scalar description parses to clean joined text, no stray ">" character')

const LITERAL_SCALAR = `---
name: some-skill
notes: |
  line one
  line two
---
body text
`
const literal = parseSkillMd(LITERAL_SCALAR)
assertEqual(literal.name, 'some-skill', 'literal scalar: name')
assertEqual(literal.content, 'body text', 'literal scalar: content')
console.log('OK: "|" (literal) YAML block scalar does not break parsing of surrounding fields')

// Real shape from github.com/anthropics/skills/skills/doc-coauthoring/SKILL.md
const SINGLE_LINE = `---
name: doc-coauthoring
description: Guide users through a structured workflow for co-authoring documentation. Use when user wants to write documentation.
---

# Doc Co-Authoring Workflow

Body content here.
`
const single = parseSkillMd(SINGLE_LINE)
assertEqual(single.name, 'doc-coauthoring', 'single-line: name')
if (!single.description.startsWith('Guide users through')) {
  throw new Error(`single-line description regressed: ${JSON.stringify(single.description)}`)
}
console.log('OK: plain single-line "key: value" frontmatter still parses correctly (no regression)')

const noFrontmatter = parseSkillMd('just some plain text, no frontmatter at all')
assertEqual(noFrontmatter.name, '', 'no-frontmatter: name')
assertEqual(noFrontmatter.description, '', 'no-frontmatter: description')
assertEqual(noFrontmatter.content, 'just some plain text, no frontmatter at all', 'no-frontmatter: content')
console.log('OK: text with no frontmatter falls back to content-only, name/description left empty (not garbage)')

console.log('ALL SKILL-IMPORT SMOKE CHECKS PASSED')
