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
  // **不是一个评分维度，是判据的兜底桶**（后端 `harness/checks/pick.MECHANICS`，
  // 计划 4.4）。打分器永远不会打它；它出现只意味着一条代码判据在这一轮抓到了
  // 一个机械缺陷（手写 mermaid、审计腔、大纲被压平…），具体是什么在 note 里。
  // 在这之前这几条判据的兜底落在 `coherence` 上，于是界面上会显示「连贯自洽
  // 0 分」——而正文连贯与否根本没人看过。
  mechanics: '机械缺陷',
}

/** 现场生成的那几条：`checklist_1` → 「你的要求 1」。 */
const CHECKLIST = /^checklist_(\d+)$/

export function dimLabel(dim: string): string {
  const m = CHECKLIST.exec(dim)
  if (m) return `你的要求 ${m[1]}`
  return FIXED[dim] ?? dim
}

/** **判据**在界面上叫什么（计划 12.1）。
 *
 * 跟上面那张表是两件事，不能合并：一条判据挑哪个维度是运行时决定的
 * （后端 `checks/pick.pick_dimension`），而**五条判据同时落在
 * `factual_grounding` 上**——用户看到「事实依据 0 分」根本不知道是
 * `no_placeholder` 还是 `citations_exist` 判的。判据名是它自己的身份。
 *
 * 名单跟后端 `Mode.checks` 逐条对账：`backend/tests/test_event_contract.py`
 * 里有一条闸，后端挂上去的每一条判据这里都必须有中文名，否则界面上会原样
 * 蹦出 `no_same_sources_twice` 这种字样。
 */
const CHECKS: Record<string, string> = {
  no_placeholder: '占位符代替内容',
  no_audit_voice: '审计腔',
  outline_intact: '大纲被压平',
  citations_hold: '引用对不上材料',
  citations_exist: '引用的事实不存在',
  material_thin: '材料太薄',
  citations_present: '整段没有一条引用',
  material_used: '查到的材料没写进去',
  no_echoed_text: '同一串字写了两遍',
  no_repeated_lists: '列表重复',
  no_restated_paragraph: '整段换个说法又说一遍',
  no_same_sources_twice: '同一条材料用了两次',
  no_fake_charts: '用文字冒充图',
  charts_from_tools: '图不是工具画的',
  unsupported_specifics: '具体数字查无出处',
  // P13 #1：「完成标准」里代码判得了的那几条（`checks/done.py`，跟 `util/doneChecks` 同一份判定；动态挂上去的）
  done_criteria: '你定的完成标准',
  // P8 的三条（问题 7 / 8 / 10）
  chart_restates_list: '图只是把清单再画一遍',
  language_consistent: '换了语言',
  no_foreign_script: '混进了乱码字符',
  no_junk_tail: '段末贴了句垃圾',
  // P37 #1：整段答成一串 JSON（P35 #2 实拍两段整串落进正文，还进了目录）
  output_not_json: '整段答成了一串 JSON',
  section_budget: '这一节还没写够',
  chart_numbers_grounded: '图里的数字没依据',
  chart_readable: '图读不出来',
  heading_fits: '标题层级不合上文',
  tail_clashes: '结尾跟下文撞了',
  table_present: '该有表却没有表',
  table_columns_match: '表格列数对不上',
  numbers_from_tools: '数字不是工具算的',
  instruction_constraints: '你指令里的硬要求',
}

export function checkLabel(check?: string): string {
  if (!check) return '代码判据'
  return CHECKS[check] ?? check
}

/**
 * 「同一条判据连响几轮、停下了」那句话后面该不该再补一句**下一步**（P40 · B #2）。
 *
 * **这条修的是什么。** 走查实拍（`p40-B-harness-streamjson-light`）：模型每一轮都吐整串 JSON，
 * 判据每一轮都拦住（正文一个字没进，**对的**），跑了 3 轮之后收工那行写的是
 * 「『整段答成了一串 JSON』这条判据连响 3 轮都没解决，停下留了最好的那轮 · 3 轮 · 正文没有改动」。
 * 用户等了几十秒、一个字没拿到，而这句话是**判据的黑话**：它没说这是模型的毛病（不是他写的内容
 * 有问题），也没说下一步做什么。P37 给 `/verify`、`/trace`、`/expand` 三条都写了那么一句
 * （「换个模型，或者再试一次」），**收工这一句当时漏了**。
 *
 * **判据宁可窄：只认这一条。** 别的判据（完成标准、引用覆盖、节拍…）连响几轮说的是
 * **内容**还没写到位，下一步是「你自己看一眼」，不是「换个模型」——给它们套同一句话就是指错地方。
 */
const STUCK_TAIL: Record<string, string> = {
  output_not_json:
    '。模型每一轮答的都是一串 JSON，不是能写进正文的内容——不是你写的内容有问题。换个模型，或者再跑一次',
}

/** 收工那句话后面那半句（没有就回空串）。 */
export function stuckTail(check?: string): string {
  return (check && STUCK_TAIL[check]) || ''
}
