// 通用：按文字点一个**最小的**元素（不是最外层那个 <html>）。args = [文字, 截图名?, idx?, waitMs?, slack?]
// 「选不到 ≠ 没有」——findText('*', x) 会匹配到 <html>，得挑面积最小的那个。
export async function pick(d, txt, idx = 0, slack = 6) {
  return d.eval(`(() => {
    const want = ${JSON.stringify(txt)}
    const cand = Array.from(document.querySelectorAll('*')).filter((e) => {
      const t = (e.textContent || '').replace(/\\s+/g, ' ').trim()
      if (!t.includes(want) || t.length > want.length + ${slack}) return false
      const b = e.getBoundingClientRect()
      return b.width > 0 && b.height > 0
    })
    cand.sort((a, b) => {
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect()
      return (ra.width * ra.height) - (rb.width * rb.height)
    })
    // 同一处会有嵌套的几层，取最小的那批里彼此不重叠的
    const out = []
    for (const e of cand) {
      if (out.some((o) => o.contains(e) || e.contains(o))) continue
      out.push(e)
    }
    return out.slice(0, 8).map((el) => {
      const b = el.getBoundingClientRect()
      return { cx: b.x + b.width / 2, cy: b.y + b.height / 2, w: b.width, h: b.height, tag: el.tagName,
               cls: String(el.className).slice(0, 60), text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40) }
    })
  })()`)
}

export async function clickExact(d, txt, idx = 0, slack = 6) {
  const list = await pick(d, txt, idx, slack)
  const r = list[idx]
  if (!r) throw new Error('clickExact 找不到「' + txt + '」（候选 ' + list.length + '）')
  await d.clickAt(r.cx, r.cy)
  return r
}

export default async function (d, args) {
  const list = await pick(d, args[0], 0, Number(args[4] ?? 6))
  console.log('候选:', JSON.stringify(list, null, 0))
  const r = await clickExact(d, args[0], Number(args[2] ?? 0), Number(args[4] ?? 6))
  console.log('点了:', JSON.stringify(r))
  await d.wait(Number(args[3] ?? 1500))
  console.log((await d.eval('document.body.innerText')).slice(0, 2500))
  if (args[1]) await d.shot(args[1])
}
