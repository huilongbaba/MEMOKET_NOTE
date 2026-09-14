import { describe, expect, it } from 'vitest'
import { featureLabel } from '../../components/SettingsPanel'

/** 这里列的是**真实库里真的记过**的功能名（llm_usage 的 distinct feature）。
 *  功能名由中间件从 URL 路径自动生成，标签表是手工维护的，两边会漂——
 *  第 612 轮截图实拍时用量那一行里就混着一个裸的 `writing-plan/start`。 */
const RECORDED = ['note-harness/run', 'writing-plan/run', 'skeleton', 'writing-plan/start',
                  'verify', 'magic-tap', 'expand', 'digest', 'compose/block',
                  'kb/extract~', 'memory/relations']

describe('用量里的功能名', () => {
  it('真实记过的每一个都有中文标签，不漏路由名给用户', () => {
    const raw = RECORDED.filter((k) => featureLabel(k) === k)
    expect(raw).toEqual([])
  })

  it('同一块功能下新长出来的路由至少读得出属于哪块', () => {
    expect(featureLabel('writing-plan/whatever')).toBe('无限续写 · 其他')
    expect(featureLabel('note-harness/pause')).toBe('智能续写 · 其他')
  })

  it('整块都没见过才原样显示——兜底不该把不认识的东西说成认识', () => {
    expect(featureLabel('brand-new/thing')).toBe('brand-new/thing')
  })
})
