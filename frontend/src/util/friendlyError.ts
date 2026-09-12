/** 把 fetch / 后端抛出来的错误翻成用户看得懂的一句话。
 *
 * 实拍：模型连不上时用户看到的是「续写失败：Error: All connection attempts failed」
 * 和「生成骨架失败：Error: 500 Internal Server Error」——两句都没说该去哪修。
 * 连接类错误统一指向设置页的 LLM 供应商；其它原样给，别把真实信息吞掉。 */
export function friendlyError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? '')
  const msg = raw.replace(/^Error:\s*/i, '')
  if (/connection attempts failed|ECONNREFUSED|ENOTFOUND|Failed to fetch|NetworkError|Connect(?:ion)? (?:error|refused)|timed? ?out|Read timeout/i.test(msg)) {
    return '模型连不上——去设置里检查 LLM 供应商的地址和 key'
  }
  if (/\b50[023]\b|Internal Server Error|Bad Gateway|Service Unavailable/i.test(msg)) {
    return '后端处理出错（多半是模型没应答）——看一眼设置里的 LLM 供应商，或稍后再试'
  }
  if (/\b401\b|\b403\b|Unauthorized|invalid[_ ]api[_ ]key/i.test(msg)) {
    return '模型服务拒绝了请求：API key 不对或没权限，去设置里改'
  }
  if (/\b429\b|rate limit/i.test(msg)) return '模型服务限流了，等一会儿再试'
  return msg || '未知错误'
}

/** 这条错误是不是「模型连不上」这一类——调用方据此决定要不要带「打开设置」按钮。 */
export function isLlmUnreachable(e: unknown): boolean {
  return friendlyError(e).startsWith('模型连不上') || friendlyError(e).startsWith('后端处理出错') || friendlyError(e).startsWith('模型服务拒绝')
}
