/** 字数：一处定义。实拍信息面板「8449 字 · 约 21 分钟」、状态栏「8874 字 · 约 22 分钟」
 * 同一篇两个数——一个数 `content.length`（连空格换行都算），一个先去空白。
 * 统一为：去掉空白、markdown 记号（井号/列表符/强调星号/表格竖线）和 `[user-n-hex]`
 * 引用标记后的字符数；阅读速度按中文 400 字/分钟。 */
export function wordCount(content: string): number {
  return content
    // 图片整条不算（alt 里常是几千字的生成提示词——实拍一篇几百字的笔记显示 27779 字）；
    // 链接只算显示文字，不算地址
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[[A-Za-z][\w-]*-(?:\d+|[0-9a-f]{12})-[0-9A-Fa-f]+\]/g, '')
    // 表格分隔行 |---|:--:| 整行是记号（格式化把它们对齐补宽之后字数曾从 7760 跳到 8241）
    .replace(/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/gm, '')
    .replace(/^\s*(#{1,6}|[-*>+]|\d+\.)\s+/gm, '')
    .replace(/[*_`|~]/g, '')
    .replace(/\s+/g, '').length
}

export function readingMinutes(words: number): number {
  return Math.max(1, Math.round(words / 400))
}
