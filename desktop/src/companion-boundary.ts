/** A small pure boundary used by every companion IPC handler and directly regression tested. */
export function trustedCompanionFrame(event: { sender: unknown; senderFrame: unknown }, expected: {
  contents: unknown
  mainFrame: unknown
  frameUrl: string
  baseUrl: string
  surface: 'top' | 'shelf'
}): boolean {
  if (event.sender !== expected.contents || !event.senderFrame || event.senderFrame !== expected.mainFrame) return false
  try {
    const frame = new URL(expected.frameUrl)
    const base = new URL(expected.baseUrl)
    return base.protocol === 'http:' && base.hostname === '127.0.0.1'
      && frame.origin === base.origin && frame.pathname === base.pathname
      && frame.searchParams.get('surface') === expected.surface
  } catch { return false }
}

export function validWorkspaceDestination(value: unknown): value is string | undefined {
  return value === undefined || (typeof value === 'string' && /^(?:app:[a-z][a-z-]{0,63}|note:[\w-]{1,128})$/.test(value))
}
