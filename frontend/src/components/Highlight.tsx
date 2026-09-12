/** 把 `q` 在 `text` 里的命中包成 <mark>，大小写不敏感，只标第一处——列表行
 * 一行一个就够，全标反而花。搜索卡 / ⌘K 共用，别各自再写一遍 indexOf。 */
export default function Highlight({ text, q }: { text: string; q: string }) {
  const needle = q.trim()
  const i = needle ? text.toLowerCase().indexOf(needle.toLowerCase()) : -1
  if (i < 0) return <>{text}</>
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + needle.length)}</mark>{text.slice(i + needle.length)}</>
}
