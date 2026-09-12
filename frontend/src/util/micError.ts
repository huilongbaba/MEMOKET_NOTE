import { friendlyError } from './friendlyError'

/** getUserMedia 失败翻成一句能照着做的话。
 *
 * 实拍前两处录音入口各写了一句：一处「拿不到麦克风权限」，一处「浏览器要求
 * HTTPS 或 localhost 才允许录音」——后者是网页版年代的话，桌面版里根本不成立；
 * 而真正常见的两种情况（系统没授权 / 没有麦克风设备）都没区分。macOS 上
 * 拒绝一次之后再点永远静默失败，只有去系统设置里打开才行，这句必须说出来。 */
export function micError(e: unknown): string {
  const name = (e as { name?: string } | null)?.name || ''
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError' || name === 'SecurityError') {
    return '系统没给麦克风权限：到「系统设置 → 隐私与安全性 → 麦克风」里打开 MEMOKET NOTE，再回来重试'
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError') {
    return '没找到可用的麦克风设备，接上麦克风或检查输入设备设置'
  }
  if (name === 'NotReadableError' || name === 'AbortError') {
    return '麦克风被别的程序占用了，关掉正在录音的应用再试'
  }
  return `打不开麦克风：${friendlyError(e)}`
}
