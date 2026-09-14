import { describe, expect, it } from 'vitest'

import { slidesToHtml } from '../../util/slideHtml'

const MD = `---
slides: true
---

# 创业一年回顾

一句话结论。

---

## EVT 从 6 月挪到 8 月

- 结构件改了 [terrence-1-A1]
- **粗体**要活着
`

describe('幻灯片 → 能打印成 PDF 的 HTML', () => {
  it('一页一个 section，第一页是封面', () => {
    const html = slidesToHtml('标题', MD)
    expect(html.match(/<section/g)).toHaveLength(2)
    expect(html).toContain('<section class="cover">')
    expect(html).toContain('page-break-after: always')
  })

  it('页码带着总页数——看的人要知道还剩几页', () => {
    expect(slidesToHtml('标题', MD)).toContain('<footer>2 / 2</footer>')
  })

  it('页标题不在正文里再出现一次', () => {
    const html = slidesToHtml('标题', MD)
    expect(html).toContain('<h1>EVT 从 6 月挪到 8 月</h1>')
    expect(html).not.toContain('<h2>EVT')
  })

  it('粗体活着，尖括号被转义——正文是用户写的，不能直接拼进 HTML', () => {
    const html = slidesToHtml('标题', '# 标题\n\n- **粗** 和 <script>alert(1)</script>\n')
    expect(html).toContain('<b>粗</b>')
    expect(html).not.toContain('<script>alert(1)</script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('标题里的尖括号也转义', () => {
    expect(slidesToHtml('<img src=x>', '# 一\n')).not.toContain('<img src=x>')
  })
})

describe('图', () => {
  const MD2 = '# 一\n\n---\n\n## 硬件方案经历了连续调整\n\n```mermaid\ngraph TD\nA-->B\n```\n'

  it('渲好的 SVG 内联进去——打印那一步的窗口是关着 JS 的，图只能先渲好', () => {
    const html = slidesToHtml('标题', MD2, new Map([['graph TD\nA-->B', '<svg id="fake"></svg>']]))
    expect(html).toContain('<figure class="diagram"><svg id="fake"></svg></figure>')
  })

  it('没渲出来就印源码，不拦着导出——一张图渲不出来不该让整份 PDF 导不成', () => {
    const html = slidesToHtml('标题', MD2)
    expect(html).toContain('<pre>graph TD\nA--&gt;B</pre>')
    expect(html).not.toContain('```')
  })
})
