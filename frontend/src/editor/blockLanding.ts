/**
 * `/` 块 / 右键「自定义提示」的产出怎么落进正文（P17 走查 #3）。
 *
 * 两种块：
 *   - 插入类（`/` 菜单那几项）：在光标处插一块，后面补一个空行把它跟下文隔开；
 *   - 替换类（`custom`：右键「自定义提示…」对选中的这段做点什么）：**开跑时选区已经清掉了**，
 *     产出落在原来选区的位置。
 *
 * P17 实拍的坑：替换类的 diff 基准取的是清掉选区之后的正文，于是「全部撤回」只撤掉新写的，
 * 原来选中的那几个字跟着没了——「其中硬件 700 万」撤回后成了「其中 700 万」（⌘Z 反而是对的，
 * 因为 CM 的历史里记着那次删除）。基准要把选区补回原位，diff 里才有「删掉选区 + 写入产出」两半。
 * 同一处的第二个坑：替换行内一段时后面跟着的「\n\n」把句子截成两行。
 *
 * 纯函数，`runBlock` 只负责调它。
 */

/** 「全部撤回」要回到的那一版：替换类把被清掉的选区补回 `at`，插入类就是当前正文。 */
export function diffBaseForBlock(doc: string, at: number, key: string, selection: string): string {
  if (key !== 'custom' || !selection) return doc
  const i = Math.max(0, Math.min(at, doc.length))
  return doc.slice(0, i) + selection + doc.slice(i)
}

/** 真正写进正文的字：插入类补空行隔开下文；替换类原样落回句子里。 */
export function textToLand(key: string, text: string): string {
  return key === 'custom' ? text : text + '\n\n'
}
