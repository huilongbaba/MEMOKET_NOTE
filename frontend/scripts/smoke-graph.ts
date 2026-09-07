/**
 * Runtime smoke test for KnowledgeGraph -- same motivation as
 * smoke-editor.ts: tsc/vite build only check types, not "does this actually
 * mount and respond to interaction without throwing." This one carries real
 * risk surface tsc can't see: d3-force + d3-zoom + d3-drag all attached to
 * the same SVG, a CSS-class-based LOD toggle read from a ref (not React
 * state), and click-to-focus/hover-card state that's brand new this round.
 *
 *     npx tsx scripts/smoke-graph.ts
 */
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>')
;(globalThis as any).window = dom.window
;(globalThis as any).Window = dom.window.constructor
;(globalThis as any).document = dom.window.document
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
;(globalThis as any).getComputedStyle = dom.window.getComputedStyle
const raf = (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 0) as unknown as number
const caf = (id: number) => clearTimeout(id)
;(globalThis as any).requestAnimationFrame = raf
;(globalThis as any).cancelAnimationFrame = caf
;(dom.window as any).requestAnimationFrame = raf
;(dom.window as any).cancelAnimationFrame = caf
;(globalThis as any).DocumentFragment = dom.window.DocumentFragment
;(globalThis as any).Node = dom.window.Node
;(globalThis as any).Text = dom.window.Text
;(globalThis as any).MutationObserver = dom.window.MutationObserver
;(globalThis as any).ResizeObserver = dom.window.ResizeObserver ?? class {
  observe() {} unobserve() {} disconnect() {}
}
;(globalThis as any).SVGElement = dom.window.SVGElement
;(dom.window as any).SVGElement.prototype.getBBox = function () {
  return { x: 0, y: 0, width: 40, height: 14 }
}
;(dom.window as any).HTMLElement.prototype.getBoundingClientRect = () => ({
  top: 0, bottom: 0, left: 0, right: 0, width: 900, height: 560, x: 0, y: 0, toJSON() { return this },
})
// jsdom doesn't implement SVGAnimatedLength (width.baseVal/height.baseVal)
// on <svg> -- d3-zoom's transition path reads it to compute the default
// pan/zoom extent.
for (const attr of ['width', 'height'] as const) {
  Object.defineProperty((dom.window as any).SVGSVGElement.prototype, attr, {
    configurable: true,
    get(this: SVGSVGElement) { return { baseVal: { value: parseFloat(this.getAttribute(attr) || '0') } } },
  })
}

async function main() {
  const { default: React } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { default: KnowledgeGraph, MAX_RENDERED_NODES } = await import('../src/components/KnowledgeGraph')

  // A realistic-shaped fixture: a hierarchy, an entity relation, and
  // co-occurrence links -- exercises all three edge kinds and the
  // click-to-focus neighbor lookup (which is keyed off exactly this data,
  // see neighborMap in KnowledgeGraph.tsx).
  // Labels over 12 chars get truncated with an ellipsis in the widget (see
  // KnowledgeGraph.tsx) -- kept short here so text-content lookups below
  // match the actually-rendered label, not the untruncated source code.
  const topics = [
    { code: 'work', parents: [], status: 'canonical', aliases: [], fact_count: 3 },
    { code: 'deadline', parents: ['work'], status: 'canonical', aliases: [], fact_count: 5 },
    { code: 'hobby', parents: [], status: 'candidate', aliases: [], fact_count: 0 },
  ]
  const entities = [
    { code: 'acme', name: 'Acme Corp', type: 'org', aliases: ['acme corp'], relations: [['employs', 'alice']], fact_count: 4 },
    { code: 'alice', name: 'Alice', type: 'person', aliases: [], relations: [], fact_count: 2 },
  ]
  const links = [{ topic: 'deadline', entity: 'acme', weight: 3 }]

  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)

  let selected: [string, string] | null = null
  const makeProps = (t: typeof topics, e: typeof entities, l: typeof links) => ({
    topics: t, entities: e, links: l,
    onSelect: (kind: string, code: string) => { selected = [kind, code] },
    width: 900, height: 560,
  })

  // Mirrors MemoryBrowser's real mount sequence: topics/entities/links start
  // as [] (useState([])) and arrive async a moment later (memoryTopics().then
  // (setTopics)) -- NOT passed synchronously from the first render. This
  // is exactly the sequence that exposed the real bug this fixture is now
  // guarding against: a `useEffect(..., [])` for zoom setup ran on that
  // first (empty, svg-less) render, found the svg ref null, bailed out, and
  // -- because [] deps means it never runs again -- silently never attached
  // wheel/drag/fitTo to the real <svg> that mounted a moment later once data
  // arrived. A fixture that hands data over synchronously from the start
  // (as this test originally did) can never exercise that path.
  root.render(React.createElement(KnowledgeGraph, makeProps([], [], [])))
  await new Promise((r) => setTimeout(r, 50))
  if (!host.querySelector('svg')) {
    console.log('OK: empty-data first render shows the placeholder, not a bare svg (as expected)')
  }
  root.render(React.createElement(KnowledgeGraph, makeProps(topics, entities, links)))

  await new Promise((r) => setTimeout(r, 200))
  const svg = host.querySelector('svg')
  if (!svg) throw new Error('svg never mounted after data arrived')
  console.log('OK: mounted with topics+entities+all 3 link kinds (after an empty-first-render), no throw')

  const nodeGroups = host.querySelectorAll('.kg-zoom-group > g')
  if (nodeGroups.length !== topics.length + entities.length) {
    throw new Error(`expected ${topics.length + entities.length} node <g>s, got ${nodeGroups.length}`)
  }
  console.log(`OK: rendered exactly ${nodeGroups.length} node groups (topics + entities)`)

  // The actual regression check: wheel-zoom must work on a graph that went
  // through the real empty-then-populated mount sequence above. Directly
  // exercises what "滥轮/拖拽根本没反应" reported broken -- not just that
  // the svg exists, but that d3-zoom's listener is actually attached and a
  // wheel event actually moves the zoom group's transform.
  const zoomGroupEl = host.querySelector('.kg-zoom-group')
  const transformBefore = zoomGroupEl?.getAttribute('transform') ?? null
  svg.dispatchEvent(new dom.window.WheelEvent('wheel', {
    bubbles: true, cancelable: true, deltaY: -100, clientX: 450, clientY: 280,
  }))
  await new Promise((r) => setTimeout(r, 50))
  const transformAfter = zoomGroupEl?.getAttribute('transform') ?? null
  if (transformAfter === null || transformAfter === transformBefore) {
    throw new Error(
      `wheel event did not change the zoom transform (before=${transformBefore}, after=${transformAfter}) `
      + '-- this is exactly the "scroll/drag has no effect" bug: the zoom behavior never attached to the real <svg>',
    )
  }
  console.log('OK: a wheel event on the post-async-mount svg actually changes the zoom transform')

  // "zoom in/out 卡顿": labels/lines must be suppressed WHILE actively
  // zooming (kg-interacting), independent of the LOD scale threshold, and
  // restored again a beat after the gesture stops.
  if (!zoomGroupEl?.classList.contains('kg-interacting')) {
    throw new Error('a wheel event should immediately add kg-interacting to suppress repaint cost mid-gesture')
  }
  await new Promise((r) => setTimeout(r, 250)) // past the 150ms settle timer
  if (zoomGroupEl?.classList.contains('kg-interacting')) {
    throw new Error('kg-interacting should clear ~150ms after the last zoom event, but it is still set')
  }
  console.log('OK: kg-interacting suppresses labels/lines during an active zoom gesture and clears after it settles')

  // Click a node with a known neighbor (deadline <-> acme via cooccur,
  // deadline <-> work via hierarchy) -- unrelated nodes should be UNMOUNTED
  // entirely (not just dimmed): "别的都隐藏掉", not "faded but still there".
  const workDeadlineNode = Array.from(nodeGroups).find((g) => g.textContent?.includes('deadline'))
  if (!workDeadlineNode) throw new Error('could not find deadline node to click')
  workDeadlineNode.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 450)) // fitTo()'s transition
  const groupsAfterFocus = () => host.querySelectorAll('.kg-zoom-group > g')
  const hasNode = (needle: string) => Array.from(groupsAfterFocus()).some((g) => g.textContent?.includes(needle))
  if (hasNode('hobby')) throw new Error('unrelated node "hobby" should be unmounted after focusing deadline, but it\'s still in the DOM')
  if (!hasNode('work') || !hasNode('cme')) throw new Error('focusing deadline should keep its neighbors (work, acme) rendered')
  console.log('OK: clicking a node unmounts non-neighbors entirely (not just dims them)')

  // "点击的那个节点处于中间" -- the clicked node itself (not the bounding-box
  // centroid of its whole neighborhood) must land at the screen center.
  // Compute its actual on-screen position: node's own transform (simulation
  // space) run through the zoom group's transform (translate+scale -> screen
  // space), same math the browser itself would do to paint it.
  const zoomGroupTransform = zoomGroupEl?.getAttribute('transform') ?? ''
  const zm = /translate\(([-\d.]+),\s*([-\d.]+)\)\s*scale\(([-\d.]+)\)/.exec(zoomGroupTransform)
  const nodeTransform = workDeadlineNode.getAttribute('transform') ?? ''
  const nm = /translate\(([-\d.]+),\s*([-\d.]+)\)/.exec(nodeTransform)
  if (!zm || !nm) throw new Error(`could not parse transforms: zoomGroup=${zoomGroupTransform}, node=${nodeTransform}`)
  const [, tx, ty, k] = zm.map(Number) as unknown as [never, number, number, number]
  const [, nx, ny] = nm.map(Number) as unknown as [never, number, number]
  const screenX = tx + nx * k, screenY = ty + ny * k
  const centerX = 900 / 2, centerY = 560 / 2
  const dist = Math.hypot(screenX - centerX, screenY - centerY)
  if (dist > 5) {
    throw new Error(`clicked node landed at screen (${screenX.toFixed(1)}, ${screenY.toFixed(1)}), expected near center (${centerX}, ${centerY}) -- off by ${dist.toFixed(1)}px`)
  }
  console.log(`OK: the clicked node itself is centered on screen (off by ${dist.toFixed(2)}px, not just its neighborhood's bounding box)`)

  // Per the new design, only the "恢复" button clears focus -- neither a
  // second click on the same node nor clicking empty canvas should.
  workDeadlineNode.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 50))
  if (hasNode('hobby')) throw new Error('re-clicking the focused node should NOT clear focus, but hobby reappeared')
  console.log('OK: clicking the already-focused node again does not clear focus (only 恢复 does)')

  const restoreBtn = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === '恢复')
  if (!restoreBtn) throw new Error('no "恢复" button rendered while focused')
  restoreBtn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 450))
  if (!hasNode('hobby')) throw new Error('clicking "恢复" should bring back all nodes, but hobby is still missing')
  console.log('OK: clicking "恢复" restores every node')

  // Hover should surface the detail card after its debounce delay, with a
  // "view more" action that calls onSelect only when actually clicked.
  // Re-query rather than reuse `nodeGroups` -- the focus/restore cycle above
  // unmounts and remounts <g> elements (React tears down a key when its map
  // entry renders null and creates a fresh element when it reappears), so
  // the original NodeList's element references are now detached from the DOM.
  const acmeNode = Array.from(groupsAfterFocus()).find((g) => g.textContent?.includes('Acme') || g.textContent?.includes('acme'))
  if (!acmeNode) throw new Error('could not find acme node to hover')
  acmeNode.dispatchEvent(new dom.window.MouseEvent('mouseover', { bubbles: true, clientX: 100, clientY: 100 }))
  await new Promise((r) => setTimeout(r, 250))
  const hoverCard = host.querySelector('.kg-hover-card')
  if (!hoverCard) throw new Error('hover card never appeared after mouseenter + debounce delay')
  if (!hoverCard.textContent?.includes('Acme')) {
    throw new Error(`hover card content looks wrong: ${hoverCard.textContent}`)
  }
  console.log('OK: hovering a node shows the detail card with correct content')

  const viewMoreBtn = Array.from(hoverCard.querySelectorAll('button')).find((b) => b.textContent?.includes('查看详情'))
  if (!viewMoreBtn) throw new Error('hover card has no "查看详情" button for a node with facts')
  if (selected !== null) throw new Error('onSelect fired before the view-more button was clicked')
  viewMoreBtn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  if (!selected || (selected as [string, string])[1] !== 'acme') {
    throw new Error(`expected onSelect('entity','acme') after clicking view-more, got ${JSON.stringify(selected)}`)
  }
  console.log('OK: onSelect only fires from the hover card\'s "查看详情" button, not from a plain node click')

  // "topic点不了": clicking a node with zero neighbors (the fixture's
  // "hobby" topic -- no parents, nothing links to it) used to be a silent
  // no-op inside handleNodeClick. It should still do something visible now:
  // focus on just itself, unmounting everything else.
  const hobbyNode = Array.from(groupsAfterFocus()).find((g) => g.textContent?.includes('hobby'))
  if (!hobbyNode) throw new Error('could not find isolated "hobby" node to click')
  hobbyNode.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 450))
  const groupsAfterHobbyClick = host.querySelectorAll('.kg-zoom-group > g')
  if (groupsAfterHobbyClick.length !== 1 || !groupsAfterHobbyClick[0].textContent?.includes('hobby')) {
    throw new Error(
      `clicking the isolated "hobby" node should focus on just itself (1 node visible), `
      + `got ${groupsAfterHobbyClick.length}: ${Array.from(groupsAfterHobbyClick).map((g) => g.textContent).join(', ')}`,
    )
  }
  console.log('OK: clicking an isolated (zero-neighbor) node still focuses on itself instead of silently doing nothing')

  // "点击恢复之后，恢复不了，显示的有问题": a node/link hidden during focus
  // and then brought back by 恢复 is a BRAND NEW DOM element (React
  // unmounts+remounts on the null<->real toggle) with no transform/x1y1x2y2
  // until the simulation ticks again -- but by now the simulation has long
  // since settled and stopped ticking, so nothing else would ever position
  // it. Verify a restored node lands at its real simulated coordinates, not
  // stuck at the SVG origin.
  const restoreBtn2 = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === '恢复')
  if (!restoreBtn2) throw new Error('no "恢复" button rendered while focused on hobby')
  restoreBtn2.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 450))
  const hobbyRestored = Array.from(host.querySelectorAll('.kg-zoom-group > g')).find((g) => g.textContent?.includes('hobby'))
  if (!hobbyRestored) throw new Error('hobby node missing after restore')
  const hobbyTransform = hobbyRestored.getAttribute('transform') ?? ''
  const hm = /translate\(([-\d.]+),\s*([-\d.]+)\)/.exec(hobbyTransform)
  if (!hm) throw new Error(`restored node has no transform at all: "${hobbyTransform}"`)
  const [, hx, hy] = hm.map(Number) as unknown as [never, number, number]
  if (Math.abs(hx) < 1 && Math.abs(hy) < 1) {
    throw new Error(`restored node landed at/near the origin (${hx}, ${hy}) -- it never got repositioned on remount`)
  }
  console.log('OK: a node hidden then restored gets its real simulated position immediately on remount, not stuck at the origin')

  root.unmount()

  // The actual bug this round was fixing: with many nodes, the simulation
  // used to hard-clamp every node into the fixed width/height box every
  // tick, so "zoom out" just showed the same overlapping mass smaller --
  // never actually un-overlapping anything. Verify a few hundred nodes
  // really do spread beyond the viewport now, and that settling triggers
  // fitTo() -> a zoomed-out transform -> the LOD overview class.
  const manyTopics = Array.from({ length: 5 }, (_, i) => ({
    code: `root${i}`, parents: [], status: 'canonical', aliases: [], fact_count: 10,
  }))
  const manyEntities = Array.from({ length: 300 }, (_, i) => ({
    code: `e${i}`, name: `Entity${i}`, type: '', aliases: [],
    relations: i > 0 ? [['rel', `e${i - 1}`]] : [], fact_count: 1,
  }))
  const bigHost = document.createElement('div')
  document.body.appendChild(bigHost)
  const bigRoot = createRoot(bigHost)
  bigRoot.render(
    React.createElement(KnowledgeGraph, {
      topics: manyTopics, entities: manyEntities, links: [],
      onSelect: () => {}, width: 900, height: 560,
    }),
  )
  // Let the simulation run past its alpha<0.25 settle-fit trigger and the
  // fitTo() transition (400ms) finish.
  await new Promise((r) => setTimeout(r, 1500))
  const bigNodeGroups = bigHost.querySelectorAll('.kg-zoom-group > g')
  if (bigNodeGroups.length !== manyTopics.length + manyEntities.length) {
    throw new Error(`expected ${manyTopics.length + manyEntities.length} nodes, got ${bigNodeGroups.length}`)
  }
  const transforms = Array.from(bigNodeGroups)
    .map((g) => g.getAttribute('transform'))
    .filter((t): t is string => !!t)
    .map((t) => {
      const m = /translate\(([-\d.]+),\s*([-\d.]+)\)/.exec(t)
      return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null
    })
    .filter((p): p is { x: number; y: number } => p !== null)
  if (transforms.length < manyTopics.length + manyEntities.length - 2) {
    throw new Error(`too many nodes never got a transform set (${transforms.length}/${manyTopics.length + manyEntities.length})`)
  }
  const xs = transforms.map((p) => p.x)
  const spread = Math.max(...xs) - Math.min(...xs)
  // 900 is the viewport width these nodes would have been clamped inside
  // under the old (buggy) behavior -- an unbounded simulation with 305
  // colliding nodes must spread well past that.
  if (spread <= 900) {
    throw new Error(`305 nodes only spread ${spread.toFixed(0)}px on x -- looks like they're still clamped to the viewport`)
  }
  console.log(`OK: 305-node simulation spread ${spread.toFixed(0)}px wide (unbounded, not clamped to the 900px viewport)`)

  const bigZoomGroup = bigHost.querySelector('.kg-zoom-group')
  if (!bigZoomGroup?.classList.contains('lod-overview')) {
    throw new Error('305-node graph never entered LOD overview mode after settling -- fitTo() should have zoomed out past the threshold')
  }
  console.log('OK: settling a 305-node graph auto-zooms out into LOD overview mode (labels/edges hidden)')

  bigRoot.unmount()

  // "一进入就卡死": real data (terrence's actual knowledge base) hit ~2200
  // topics+entities -- an order of magnitude past what the 305-node test
  // above ever exercised, which is exactly why it never caught the freeze.
  // Push well past MAX_RENDERED_NODES and verify only the cap's worth of
  // <g> elements actually mount (not 2500), and that this still settles in
  // roughly the same time the 305-node test did -- proving the cap is what
  // keeps this from being unbounded DOM/simulation work regardless of how
  // large the real knowledge base grows.
  const hugeTopics = Array.from({ length: 500 }, (_, i) => ({
    code: `t${i}`, parents: [], status: 'canonical', aliases: [], fact_count: i,
  }))
  const hugeEntities = Array.from({ length: 2000 }, (_, i) => ({
    code: `he${i}`, name: `HugeEntity${i}`, type: '', aliases: [], relations: [], fact_count: i,
  }))
  const hugeHost = document.createElement('div')
  document.body.appendChild(hugeHost)
  const hugeRoot = createRoot(hugeHost)
  const hugeStart = Date.now()
  hugeRoot.render(
    React.createElement(KnowledgeGraph, {
      topics: hugeTopics, entities: hugeEntities, links: [],
      onSelect: () => {}, width: 900, height: 560,
    }),
  )
  await new Promise((r) => setTimeout(r, 1500))
  const hugeElapsed = Date.now() - hugeStart
  const hugeNodeGroups = hugeHost.querySelectorAll('.kg-zoom-group > g')
  if (hugeNodeGroups.length !== MAX_RENDERED_NODES) {
    throw new Error(
      `2500 input nodes should render exactly MAX_RENDERED_NODES=${MAX_RENDERED_NODES} <g> elements, `
      + `got ${hugeNodeGroups.length} -- the cap isn't actually bounding what gets mounted/simulated`,
    )
  }
  console.log(`OK: 2500 input nodes (topics+entities) render capped to exactly ${MAX_RENDERED_NODES}, settled in ${hugeElapsed}ms`)

  // The cap picks the highest fact_count nodes, not an arbitrary prefix --
  // the lowest-fact_count nodes (fact_count 0..99, well outside top 400 of
  // 2500 by construction) must NOT be among the rendered ones.
  const hugeLabels = new Set(Array.from(hugeNodeGroups).map((g) => g.textContent ?? ''))
  if (hugeLabels.has('HugeEntity0') || hugeLabels.has('t0')) {
    throw new Error('the lowest fact_count nodes got rendered -- the cap should keep the highest fact_count nodes, not an arbitrary prefix')
  }
  console.log('OK: the node cap keeps the highest-fact-count nodes, not an arbitrary prefix')

  hugeRoot.unmount()
  console.log('ALL GRAPH SMOKE CHECKS PASSED')
}

main().catch((err) => {
  console.error('SMOKE TEST FAILED:', err)
  process.exit(1)
})
