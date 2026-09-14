/**
 * 一个实体该用哪个图标。
 *
 * **原来一律 `bx-user`（一个人形）**，于是 `Facebook` `Canada` `iphone` `Russia`
 * `Apple Watch` `app` `cloud` 全都长着一张人脸（第 658 轮实拍）。这不是不好看的
 * 问题——**图标是一句断言**，而我们并不知道这些是什么：`kite` 抽出来的实体
 * `etype` 全库 1239 个**一个都没有值**。
 *
 * 所以规矩是「**不知道就别说**」：默认给一个中性的标签图标，只有真知道的
 * 才给专门图标。知道的来路见 `docs/kb-entities-plan.md`：
 *   · `etype`（将来索引层填的，现在还没有）
 *   · 说话人标签——那是唯一一类确定是「人」的
 *   · 两条窄后缀规则（机构 / 学校）：覆盖率只有 1%，但**100% 不会错**
 *
 * 剩下 88% 一律中性。宁可少说，不要说错。
 */
const ORG_SUFFIX = ['公司', '科技', '有限', '集团', '工厂', '实验室', '研究院', '事务所', '银行', '医院']
const EDU_SUFFIX = ['大学', '学院', '中学', '小学', '学校', '高中', '附中', '书院']

export const NEUTRAL_ENTITY_ICON = 'bx-purchase-tag'

export function entityIcon(name: string, etype = ''): string {
  const t = (etype || '').trim().toLowerCase()
  if (t) {
    if (t.startsWith('person') || t === '人' || t === '人物') return 'bx-user'
    if (t.startsWith('place') || t.startsWith('loc') || t === '地点') return 'bx-map'
    if (t.startsWith('org') || t === '机构' || t === '公司') return 'bx-buildings'
    if (t.startsWith('product') || t === '产品') return 'bx-package'
    return NEUTRAL_ENTITY_ICON
  }
  const s = (name || '').trim()
  if (EDU_SUFFIX.some((x) => s.endsWith(x))) return 'bx-book'
  if (ORG_SUFFIX.some((x) => s.endsWith(x))) return 'bx-buildings'
  return NEUTRAL_ENTITY_ICON
}
