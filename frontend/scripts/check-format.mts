/** 一键格式化的自测。
 *
 *     npx tsx scripts/check-format.mts
 *
 * 最要紧的不变量是**幂等**：格式化两次 === 格式化一次。不幂等的话用户每点
 * 一次都产生一堆 diff，「接受/撤回」就变成了噪声。固定用例覆盖已知形态，
 * 随机 fuzz 覆盖边界——后者才是真正会坏的地方。
 *
 * 第二条不变量：**只动排版，不动内容**。代码块里一个字符都不能变。
 */
import { formatMarkdown as fmt } from '../src/editor/format.ts'

let bad = 0
const ok = (c: unknown, m: string) => { console.log(`${c ? '✓' : '✗'} ${m}`); if (!c) bad++ }

// —— 标题 ——
ok(fmt('#标题\n正文。') === '# 标题\n\n正文。\n', '`#标题` 补空格 + 标题后空一行')
ok(fmt('正文。\n## 小节') === '正文。\n\n## 小节\n', '标题前补空行')

// —— 列表 ——
ok(fmt('* 甲\n+ 乙\n- 丙') === '- 甲\n- 乙\n- 丙\n', '列表标记统一成 -')
ok(fmt('1) 甲\n2) 乙') === '1. 甲\n2. 乙\n', '有序列表 `1)` → `1.`')
ok(fmt('- 甲\n    - 乙') === '- 甲\n  - 乙\n', '嵌套缩进统一成 2 空格')

// —— 空行与空白 ——
ok(fmt('甲。\n\n\n\n乙。') === '甲。\n\n乙。\n', '连续空行压成一个')
ok(fmt('甲。   \n乙。\t') === '甲。\n乙。\n', '行尾空白清掉')
ok(fmt('\n\n甲。\n\n\n') === '甲。\n', '首尾空行清掉，结尾留一个换行')

// —— 表格对齐（AI 生成的表原始输出是不齐的）——
const t = fmt('|月份|渠道|销量|\n|---|:---:|---:|\n|3月|官网|1200|\n|4月|Kickstarter|800|')
console.log(t.split('\n').map((l) => '    ' + l).join('\n'))
// 中文算两格：「渠道」列最宽的是 Kickstarter(11)，中文表头要补到同宽
ok(t.includes('| Kickstarter |'), '表格按显示宽度对齐（中文算两格）')
// 按**显示宽度**比，不是字符数——中文占两格，用 .length 比会把对齐的表判成不齐
const dispWidth = (s2: string) => [...s2].reduce((w, ch) => {
  const c = ch.codePointAt(0) ?? 0
  return w + ((c >= 0x2e80 && c <= 0xa4cf) || (c >= 0xff00 && c <= 0xff60) ? 2 : 1)
}, 0)
const rowWidths = t.split('\n').filter((l) => l.startsWith('|')).map(dispWidth)
ok(new Set(rowWidths).size === 1, `每一行竖线对齐（各行显示宽度 ${[...new Set(rowWidths)]}）`)
ok(t.includes(':----') || t.includes(':---'), '保留居中/右对齐标记')

// —— 中西文之间补空格 ——
ok(fmt('用ask memory查记忆').includes('用 ask memory 查记忆'), '中西文之间补空格')
ok(fmt('见`code`这里') === '见`code`这里\n', '行内代码两边不动（避免改坏标识符）')
ok(fmt('看 [链接](http://a.com/b)吧').includes('](http://a.com/b)'), 'URL 不动')

// —— 代码块一个字符都不能动 ——
const code = '```python\ndef  f( x ):\n    return   x*2   # 保留\n```\n'
const got = fmt('正文。\n' + code + '后面。')
ok(got.includes('def  f( x ):') && got.includes('return   x*2   # 保留'),
  '代码块里的空格、缩进、注释原样保留')
ok(!got.includes('def  f ( x )'), '代码块里不做中西文空格处理')
ok(fmt('```\n|a|b|\n|---|---|\n```').includes('|a|b|'), '代码块里的假表格不格式化')

// —— 块之间必须空行：这三条是**会渲染错**，不是排版难看 ——
//
// markdown 的块级结构靠空行分隔。拿这个 app 自己会生成的内容跑出来的：
const blocks = fmt([
  '- 无序项',
  '1) 有序项',
  '> 引用',
  '<audio controls src="/api/assets/a.webm"></audio>',
  '录音转写的文字',
].join('\n'))
ok(/- 无序项\n\n1\. 有序项/.test(blocks),
  '无序列表和有序列表之间空行（不然两个列表粘成一个）')
ok(/1\. 有序项\n\n> 引用/.test(blocks),
  '引用块前空行（不然被当成上一个列表项的延续）')
ok(/<\/audio>\n\n录音转写的文字/.test(blocks),
  'HTML 块后空行（**不然后面那行文字根本渲染不出来**）')

// 嵌套子项不该被当成"换了块"而插空行
ok(fmt('- 父\n  - 子') === '- 父\n  - 子\n', '嵌套子项跟父列表算同一块')

// 标题、表格、代码块各自独立成块
ok(/# 一\n\n## 二/.test(fmt('# 一\n## 二')), '相邻标题之间空行')

// —— 幂等 ——
const CASES = [
  '#标题\n\n\n* 甲\n+ 乙\n\n|a|b|\n|---|---|\n|1|2|\n\n正文用ask memory查。',
  '```js\nlet x=1\n```\n\n## 小节\n1) 一\n2) 二\n',
  '没有任何需要改的一段话。\n',
  '',
  '|不是|表格\n|因为没有分隔行|\n',
]
let notIdem = 0
for (const c of CASES) {
  const a = fmt(c)
  if (fmt(a) !== a) {
    notIdem++
    console.log('✗ 不幂等：', JSON.stringify(c.slice(0, 40)))
    console.log('   一次:', JSON.stringify(a.slice(0, 80)))
    console.log('   两次:', JSON.stringify(fmt(a).slice(0, 80)))
  }
}
ok(notIdem === 0, `${CASES.length} 个固定用例都幂等`)

// —— 随机 fuzz ——
const BITS = ['# 标', '## 小节', '- 甲', '* 乙', '1) 一', '正文abc中文', '', '   ', '|a|b|',
  '|---|---|', '|1|2|', '```', 'let x = 1', '> 引用', '\t缩进', '结尾  ']
const rnd = (n: number) => Math.floor(Math.random() * n)
let fuzzBad = 0
for (let i = 0; i < 3000; i++) {
  const doc = Array.from({ length: 1 + rnd(12) }, () => BITS[rnd(BITS.length)]).join('\n')
  const a = fmt(doc)
  if (fmt(a) !== a) {
    fuzzBad++
    if (fuzzBad <= 2) {
      console.log('✗ fuzz 不幂等：', JSON.stringify(doc))
      console.log('   一次:', JSON.stringify(a))
      console.log('   两次:', JSON.stringify(fmt(a)))
    }
  }
}
ok(fuzzBad === 0, `随机 3000 例都幂等`)

console.log(bad ? `\n✗ ${bad} 项没通过` : '\n格式化：通过')
if (bad) process.exit(1)
