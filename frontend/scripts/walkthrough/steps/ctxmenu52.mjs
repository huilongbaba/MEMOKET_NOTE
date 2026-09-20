import { docText, pageText } from './lib.mjs'

/** 选中第 n 行（0 起）整行，右键。
 *
 * **P47 量具补的一刀**：跑完几趟智能续写之后编辑器是滚动过的，第 2 行的 bbox
 * `y = -26.9`——**在视口上面**，`elementFromPoint` 回 null，点下去谁都没收到。
 * 症状是「右键菜单 0 项」，读起来像「这个菜单没了」，其实是**没点上**
 * （走查量具那条：「点了没反应」先分清「没点上」还是「handler 不通」，
 * 这是第六个形状）。所以先把那一行滚进视口中间，滚完**再读一次 bbox**。 */
export async function selectLineAndRightClick(d, lineIdx) {
  await d.eval(`(() => {
    const el = document.querySelectorAll('.cm-content .cm-line')[${lineIdx}]
    if (el) el.scrollIntoView({ block: 'center' })
  })()`)
  await d.wait(400)
  const r = await d.eval(`(() => {
    const ls = document.querySelectorAll('.cm-content .cm-line')
    const el = ls[${lineIdx}]; if (!el) return null
    const b = el.getBoundingClientRect()
    if (b.y < 0 || b.y + b.height > innerHeight) throw new Error('这一行滚完还在视口外：y=' + b.y)
    return { x: b.x + 10, y: b.y + b.height / 2, text: el.textContent }
  })()`)
  if (!r) throw new Error('没有第 ' + lineIdx + ' 行')
  await d.clickAt(r.x, r.y)
  await d.wait(200)
  await d.key('Home')
  await d.key('End', ['shift'])
  await d.wait(300)
  const sel = await d.eval(`String(document.getSelection())`)
  const b = await d.eval(`(() => { const s = document.getSelection(); if (!s.rangeCount) return null; const r = s.getRangeAt(0).getBoundingClientRect(); return { cx: r.x + r.width/2, cy: r.y + r.height/2 } })()`)
  await d.clickAt(b.cx, b.cy, { button: 'right' })
  await d.wait(700)
  return { sel, b }
}

export default async function (d, args) {
  await d.setTheme('light')
  const lineIdx = Number(args[0] ?? 6)
  const { sel } = await selectLineAndRightClick(d, lineIdx)
  console.log('选中:', JSON.stringify(sel))
  const items = await d.eval(`Array.from(document.querySelectorAll('.palette-item, [class*="palette"] [class*="item"]')).map((e) => (e.textContent||'').trim())`)
  console.log('右键菜单:', JSON.stringify(items))
  await d.shot(args[1] ?? 'p47-5-old-ctx-light.png')
}
