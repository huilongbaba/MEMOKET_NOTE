/** **一份走查日志的出处**：拼它的那一句，和认它的那条正则，**在这一个文件里**（P97 A）。
 *
 * 为什么单独一份：写的那一头在 `cdp.mjs`（跑的时候打第一行），认的那一头在
 * `scripts/check-walkthrough-provenance.mts`（入库之后核）。两头各写一份格式串的话，
 * 改一头忘了另一头 = **闸从此全红或者全绿，而且看不出来是哪一种**
 * （`whoami.mjs` 那一份就是为同一件事分出来的：抄得到的地方就会被抄）。
 *
 * 这一行长什么样、为什么有它，见 `check-walkthrough-provenance.mts` 顶上那一段。
 */
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'

/** 日志第一行的形状。**两头都钉死**：行首行尾各一个锚点，中间只认 `.mjs` + 64 位十六进制。 */
export const HEAD_RE = /^步骤脚本: ([A-Za-z0-9_.-]+\.mjs) sha256=([0-9a-f]{64})$/

/** 拼那一句。**读的是这一刻真读进来的那个文件的字节**，不是文件名、不是 git 里那一份。 */
export function stepProvenance(p) {
  return `步骤脚本: ${basename(p)} sha256=${createHash('sha256').update(readFileSync(p)).digest('hex')}`
}

/** 认那一句。**只认第一行**：出现在中间等于「跑完之后有人往里贴了一行」。 */
export function parseHead(text) {
  const m = HEAD_RE.exec(String(text).split('\n')[0] ?? '')
  return m ? { step: m[1], sha: m[2] } : null
}
