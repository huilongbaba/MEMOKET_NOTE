/** P40 · B 第四次全流程走查当批修的那条（前端）。
 *
 * **收工那句话是判据的黑话，而且没有出路。** 走查实拍（`p40-B-harness-streamjson-light`）：
 * streamjson 档下跑智能续写，判据每一轮都拦住（正文一个字没进，**对的**），3 轮之后收工那行写的是
 *
 *   「『整段答成了一串 JSON』这条判据连响 3 轮都没解决，停下留了最好的那轮 · 3 轮 · -1 字」
 *
 * 用户等了几十秒、一个字没拿到。这句话没说**这是模型的毛病**（不是他写的内容有问题），
 * 也没说**下一步做什么**——而 P37 给 `/verify`、`/trace`、`/expand` 三条都写了那么一句。
 * （那个「-1 字」是另一条，修在后端 `checks/shape.drop_json_paragraphs`，见 `tests/test_p40.py`。）
 */
import { describe, expect, it } from 'vitest'

import { checkLabel, stuckTail } from '../dimLabel'
import appSrc from '../../App.tsx?raw'

describe('P40 #2 收工那句话要说清是谁的毛病、下一步做什么', () => {
  it('模型答的形状不对那一档，后面补一句「换个模型，或者再跑一次」', () => {
    const tail = stuckTail('output_not_json')
    expect(tail).toContain('换个模型')
    expect(tail).toContain('不是你写的内容有问题')
  })

  it('**判据宁可窄**：别的判据一个字都不多说', () => {
    // 完成标准 / 引用覆盖 / 节拍这些连响几轮说的是「内容还没写到位」，
    // 下一步是「你自己看一眼」，套「换个模型」就是指错地方。
    for (const c of ['done_criteria', 'citations_present', 'no_placeholder', 'beat_coverage', '']) {
      expect(stuckTail(c)).toBe('')
    }
    expect(stuckTail(undefined)).toBe('')
  })

  it('拼出来的整句话读得通，而且判据名是中文', () => {
    const check = 'output_not_json'
    const line = `「${checkLabel(check)}」这条判据连响 3 轮都没解决，停下留了最好的那轮${stuckTail(check)}`
    expect(line).toBe(
      '「整段答成了一串 JSON」这条判据连响 3 轮都没解决，停下留了最好的那轮。'
      + '模型每一轮答的都是一串 JSON，不是能写进正文的内容——不是你写的内容有问题。换个模型，或者再跑一次',
    )
    expect(line).not.toContain('output_not_json')
  })

  it('**接线洞**：App.tsx 的 check_stuck 那一支真的调了 stuckTail', () => {
    // 函数写对了没接上，上面三条全绿——P32 / P34 / P36 三次都栽在这个形状上。
    const line = appSrc.split('\n').find((l: string) => l.includes('这次没达到交付标准'))
    expect(line, 'App.tsx 里找不到收工那句话').toBeTruthy()
    expect(line).toContain('stuckTail(stuckCheckRef.current.check)')
  })
})
