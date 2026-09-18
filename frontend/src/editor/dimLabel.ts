/** 打分维度在界面上叫什么。
 *
 * 原来这张表只在 `components/AgentActivity.tsx` 里，而块生成那条路
 * （`App.runBlock` 的 onEvaluate）直接把维度名原样打进日志——两处各说各话。
 * 批 17 之后必须收成一处：`prompt` / `custom` 两个模式会在跑前**现场生成**
 * 几个维度（`checklist_1…`，后端 `harness/checklist.py`），它们不在任何一张
 * 写死的表里，落到哪一处没处理，用户就会在那一处看见 `checklist_1` 这种字样。
 */
const FIXED: Record<string, string> = {
  spine_fidelity: '扣题',
  topic_fidelity: '扣题',
  beat_coverage: '节拍覆盖',
  non_repetition: '不重复',
  coherence: '连贯自洽',
  factual_grounding: '事实依据',
  material_use: '用上你的材料',
  style_fit: '风格贴合',
  follows_prompt: '照你的指令做',
  fits_context: '跟上下文合得上',
  no_fabrication: '没有编造',
  replaces_cleanly: '能直接替换选区',
}

/** 现场生成的那几条：`checklist_1` → 「你的要求 1」。 */
const CHECKLIST = /^checklist_(\d+)$/

export function dimLabel(dim: string): string {
  const m = CHECKLIST.exec(dim)
  if (m) return `你的要求 ${m[1]}`
  return FIXED[dim] ?? dim
}
