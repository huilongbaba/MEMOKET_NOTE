import { useEffect, useState } from 'react'
import type { CompanionBridge } from '../desktop'

/** A transient, local candidate. Reading never creates a note or shelf item. */
export function useClipboardSuggestion(bridge: CompanionBridge | undefined, active: boolean, content: string) {
  const [candidate, setCandidate] = useState<{ text: string; truncated: boolean } | null>(null)
  const [dismissed, setDismissed] = useState('')
  useEffect(() => {
    if (!active || !bridge?.peekClipboard) { setCandidate(null); return }
    let live = true
    let pending = false
    const refresh = async () => {
      if (pending || document.visibilityState === 'hidden') return
      pending = true
      try {
        const next = await bridge.peekClipboard()
        if (live) {
          setCandidate(next.text.trim() ? next : null)
          setDismissed(previous => previous && previous !== next.text ? '' : previous)
        }
      } catch {
        if (live) setCandidate(null)
      } finally { pending = false }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 1200)
    window.addEventListener('focus', refresh)
    return () => { live = false; window.clearInterval(timer); window.removeEventListener('focus', refresh) }
  }, [active, bridge])
  const visible = active && candidate && candidate.text !== dismissed && !content.includes(candidate.text) ? candidate : null
  return { candidate: visible, dismiss: () => { if (candidate) setDismissed(candidate.text) } }
}
