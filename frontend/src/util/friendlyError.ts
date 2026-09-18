/** 把 fetch / 后端抛出来的错误翻成用户看得懂的一句话。
 *
 * 实拍：模型连不上时用户看到的是「续写失败：Error: All connection attempts failed」
 * 和「生成骨架失败：Error: 500 Internal Server Error」——两句都没说该去哪修。
 * 连接类错误统一指向设置页的 LLM 供应商；其它原样给，别把真实信息吞掉。
 *
 * P3（`docs/edge-cases.md`）补的三条：
 *   1. **浏览器连不上后端**（`Failed to fetch`）跟**后端连不上模型**是两回事——原来两种
 *      都说「模型连不上——去设置里检查 LLM 供应商」，后端进程没起来时这是指错了地方。
 *   2. 语音服务的错说语音服务，别指去 LLM 供应商。
 *   3. 后端已经翻好的中文句子（`llm.describe_error` / `asr.describe_error` 出来的 502）
 *      原样给，不再被「5xx = 后端处理出错」这条一刀切盖掉。 */
export function friendlyError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? '')
  const msg = raw.replace(/^Error:\s*/i, '').replace(/^TypeError:\s*/i, '')
  // 浏览器 → 后端这一跳断了：后端进程没起来 / 刚重启 / 被杀。跟模型无关，别指去设置页。
  if (/^Failed to fetch$|NetworkError when attempting|Load failed|net::ERR_/i.test(msg)) {
    return '连不上应用后台（后端进程没在跑，或刚重启还没起来）——等几秒再试，还不行就重启应用'
  }
  // 状态码后面已经是一句中文（后端翻好的），状态码对用户没意义，只留那句话
  const body = msg.replace(/^\d{3}\s+(?=\S)/, '')
  if (/[一-鿿]/.test(body)) return body
  if (/transcription failed|whisper/i.test(msg)) {
    return '语音服务连不上或转写失败——去设置里检查语音服务地址'
  }
  if (/connection attempts failed|ECONNREFUSED|ENOTFOUND|Connect(?:ion)? (?:error|refused)|timed? ?out|Read timeout/i.test(msg)) {
    return '模型连不上——去设置里检查 LLM 供应商的地址和 key'
  }
  if (/\b50[023]\b|Internal Server Error|Bad Gateway|Service Unavailable/i.test(msg)) {
    return '后端处理出错（多半是模型没应答）——看一眼设置里的 LLM 供应商，或稍后再试'
  }
  if (/\b401\b|\b403\b|Unauthorized|invalid[_ ]api[_ ]key/i.test(msg)) {
    return '模型服务拒绝了请求：API key 不对或没权限，去设置里改'
  }
  if (/\b429\b|rate limit/i.test(msg)) return '模型服务限流了，等一会儿再试'
  return body || '未知错误'
}

/** 这条错误是不是「模型连不上 / 模型侧出错」这一类——调用方据此决定要不要带「打开设置」按钮。 */
export function isLlmUnreachable(e: unknown): boolean {
  const m = friendlyError(e)
  return m.startsWith('模型连不上') || m.startsWith('后端处理出错') || m.startsWith('模型服务')
    || m.startsWith('模型太久没应答')
}

/** 是不是「后端进程本身连不上」——这种时候「打开设置」帮不上忙。 */
export function isBackendDown(e: unknown): boolean {
  return friendlyError(e).startsWith('连不上应用后台')
}
