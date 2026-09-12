/** 字数：一处定义。实拍信息面板「8449 字 · 约 21 分钟」、状态栏「8874 字 · 约 22 分钟」
 * 同一篇两个数——一个数 `content.length`（连空格换行都算），一个先去空白。
 * 统一为：去掉空白、markdown 记号（井号/列表符/强调星号/表格竖线）和 `[user-n-hex]`
 * 引用标记后的字符数；阅读速度按中文 400 字/分钟。 */
export function wordCount(content: string): number {
  return content
    .replace(/\[[A-Za-z][\w-]*-\d+-[0-9A-Fa-f]+\]/g, '')
    .replace(/^\s*(#{1,6}|[-*>+]|\d+\.)\s+/gm, '')
    .replace(/[*_`|~]/g, '')
    .replace(/\s+/g, '').length
}

export function readingMinutes(words: number): number {
  return Math.max(1, Math.round(words / 400))
}
