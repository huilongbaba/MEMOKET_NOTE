/** 灵动岛笔记面板底下那条「相关记忆」的召回（零模型，`/api/memory/recall`）。
 *
 *  跟工作台右栏的 `RelatedMemory` 同一套纪律，只保留召回那一半：
 *    · 停笔 900ms 才问一次；正文没变就不再问（`lastQuery`）；
 *    · 只认**最新那一问**的回答（`seq`）——两问都在飞，先发的后到不许盖回来；
 *    · 面板不在写作态（`enabled` = false）时把计时器撤掉、**留着上一次的结果**：
 *      切回来正文没变就直接接着用，不重新问；
 *    · 正文里已经引过（`[id]`）或已经写进去的原话（`factInBody`）当场折叠掉，
 *      按**渲染这一刻**的正文判，用户把引用插进去的那一下它就消失。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { recall, type Fact } from '../api'
import { factInBody, recallQuery } from './recallContext'
import { stripForRecall } from './wordCount'

export const AMBIENT_IDLE_MS = 900
export const AMBIENT_MIN_CHARS = 8
export const AMBIENT_LIMIT = 5

/** 去掉引用标记 / 图片 / 链接地址之后还剩几个非空白字符。 */
const meaningfulChars = (content: string) => stripForRecall(content).replace(/\s+/g, '').length

/** 正文最后一个非空段（按空行分段）。灵动岛的编辑器没有光标位置可拿，
 *  用户正在写的永远是最后一段。 */
function lastParagraph(content: string): string {
  const parts = content.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
  return parts.length ? parts[parts.length - 1] : ''
}

export function useAmbientRecall(content: string, enabled: boolean): { facts: Fact[]; terms: string[]; busy: boolean } {
  const [facts, setFacts] = useState<Fact[]>([])
  const [terms, setTerms] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const lastQuery = useRef('')
  const seq = useRef(0)
  const tooShort = meaningfulChars(content) < AMBIENT_MIN_CHARS

  // 卸载后飞回来的回答一律不要
  useEffect(() => () => { seq.current++ }, [])
  // 知识库刚进了新内容：正文没变也要再问一次
  const [kbTick, setKbTick] = useState(0)
  useEffect(() => {
    const changed = () => { lastQuery.current = ''; setKbTick((tick) => tick + 1) }
    window.addEventListener('kb-changed', changed)
    return () => window.removeEventListener('kb-changed', changed)
  }, [])

  useEffect(() => {
    if (!enabled) return
    const query = tooShort ? '' : recallQuery(content, lastParagraph(content)).query
    if (query.length < AMBIENT_MIN_CHARS) {
      lastQuery.current = ''
      seq.current++
      setFacts([]); setTerms([]); setBusy(false)
      return
    }
    if (query === lastQuery.current) return
    const timer = window.setTimeout(() => {
      lastQuery.current = query
      const mine = ++seq.current
      setBusy(true)
      // 先包一层 Promise：`recall` 本身同步抛（接口没接上）也走 catch，别把面板炸掉
      Promise.resolve().then(() => recall(query, AMBIENT_LIMIT))
        .then((r) => {
          if (mine !== seq.current) return
          setFacts(r.kb_empty ? [] : (r.facts ?? []))
          setTerms(r.terms ?? [])
        })
        .catch(() => {
          if (mine !== seq.current) return
          lastQuery.current = ''            // 下一次正文一变还问得动
          setFacts([]); setTerms([])
        })
        .finally(() => { if (mine === seq.current) setBusy(false) })
    }, AMBIENT_IDLE_MS)
    return () => window.clearTimeout(timer)
  }, [content, enabled, tooShort, kbTick])

  const visible = useMemo(
    () => (tooShort ? [] : facts.filter((f) => !content.includes('[' + f.id + ']') && !factInBody(f.text, content))),
    [facts, content, tooShort],
  )
  return { facts: visible, terms, busy }
}
