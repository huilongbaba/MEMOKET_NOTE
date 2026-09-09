"""把每一步实际发给模型的 prompt 原样导出，供人工审阅。

不是把 prompts.py 抄一遍——那些是模板。这里渲染的是**真实调用时拼好的完整
消息**：system 部分带上用户启用的写作技能（compose_system 叠加后的结果），
user 部分带上真实的骨架、正文、知识库检索结果、机械查重候选、上一轮打分的
诊断、策略控制器注入的方向。看模板看不出问题，看拼好的才看得出。

覆盖单篇 harness 的六步 + 文件夹级四步 + KITE 检索编译两版对照。

输出到 MEMOKET_NOTE/prompts/，一步一个文件，按调用顺序编号。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts
from app.database import store
from app.harness import adapter as harness_adapter, tools# noqa: E402
from app.routers.compose import _profile, _retrieve  # noqa: E402
from app.harness.middleware.repeats import find_repeats  # noqa: E402
from app.harness.checks.rubric import DEFAULT_SYSTEM_PROMPT, _build_prompt  # noqa: E402

USER = "terrence"
OUT = Path(__file__).resolve().parents[2] / "prompts"

TITLE = "硬件量产前的未决项"
SPINE = "样机问题尚未收敛与量产节点临近之间的张力，迫使先划清哪些是量产前不可妥协的底线"
BEATS = [
    "建立处境：样机暴露的问题还没收敛，量产窗口已经在逼近",
    "用手板打样费和配件口径这些实际数字说明哪些成本必须在量产前锁定",
    "分出阻塞项与可延后项，给出判断依据",
    "落到报价前/放行前的自检清单",
]
CONTENT = """## 硬件量产前的未决项

样机阶段暴露的问题还没收敛完，得先把哪些是必须在量产前解决的列清楚。

## 量产前必须锁定的成本口径

配件按每套必配计入，一次性打样与结构验证费用按首批投放套数摊销。
渠道报备的时间与返工成本要估进去，不能只算物料。

## 量产前必须锁定的成本口径

配件耗材要写进单价，不要放在项目尾款里统一回收。
"""


def _md(title: str, why: str, blocks: list[tuple[str, str]]) -> str:
    out = [f"# {title}", "", why, ""]
    for label, body in blocks:
        out += [f"## {label}", "", "```text", body.rstrip(), "```", ""]
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    profile = _profile(USER)
    facts, _ids, _took = _retrieve(USER, CONTENT, SPINE, BEATS, limit=8,
                                   title=TITLE, anchor_first=True)
    dup_hints = find_repeats(CONTENT)
    tool_ctx = tools.ToolContext(user=USER, note_id="demo", note_title=TITLE)
    written: list[str] = []

    def write(idx: str, name: str, title: str, why: str, blocks):
        p = OUT / f"{idx}-{name}.md"
        p.write_text(_md(title, why, blocks), encoding="utf-8")
        written.append(p.name)
        print(f"  ✓ {p.name}", flush=True)

    # ---------------------------------------------------------- 单篇 harness
    write("01", "骨架", "① 骨架 · SKELETON_SYSTEM",
          "开跑前一次性生成核心张力与结构节拍。**这一步定错，后面每一轮都会忠实地服务错误目标**——"
          "已知的三个最深缺陷都出在这里。",
          [("system（含用户启用的 skeleton 技能）",
            prompts.compose_system(prompts.SKELETON_SYSTEM,
                                   store.enabled_skills_for_scope(USER, "skeleton"))),
           ("user", prompts.skeleton_user(TITLE, CONTENT, profile))])

    write("02", "修订", "② 修订 · EDIT_SYSTEM",
          "每轮第一步。检索到的事实 + 机械查重候选 + 上一轮最弱维度一起喂进去，"
          "模型返回一组 {op, anchor, text, reason, sources}，后端直接自动应用。",
          [("system（含用户启用的 edit 技能）",
            prompts.compose_system(prompts.EDIT_SYSTEM,
                                   store.enabled_skills_for_scope(USER, "edit"))),
           ("user", prompts.edit_user(SPINE, BEATS, CONTENT, facts, profile,
                                      focus="non_repetition", dup_hints=dup_hints))])

    write("03", "检索规划", "③ 检索规划 · RETRIEVAL_PLAN_SYSTEM",
          "agent 自己决定要不要查、查什么。**独立成一次调用**是必须的："
          "把工具挂在续写 prompt 上时实测模型一次都不查，还编造内容。"
          "steer 是策略控制器根据上一轮打分诊断注入的方向。",
          [("system", prompts.RETRIEVAL_PLAN_SYSTEM),
           ("user", prompts.retrieval_plan_user(
               TITLE, SPINE, BEATS, CONTENT,
               steer="上一轮打分认为正文的事实依据有问题：使用了知识库中未出现的具体日期和人物。"
                     "这一轮先把这些点查实——查得到就用查到的原话，查不到就把那句改写成"
                     "不含具体人名/日期/数字的说法，不要保留编造的细节。",
               require_verification=True,
               topics_overview=tools.dispatch("list_topics", {"limit": 40}, tool_ctx))),
           ("随请求一起发出的 tools 定义",
            json.dumps(tools.specs(["memory"]), ensure_ascii=False, indent=2))])

    write("04", "续写", "④ 续写 · MAGIC_TAP_SYSTEM",
          "唯一产出正文的一步，流式返回。知识库事实块里的内容来自上一步 agent 自己查到的结果。",
          [("system（含用户启用的 magic_tap 技能 + 工具说明）",
            prompts.compose_system(prompts.MAGIC_TAP_SYSTEM,
                                   store.enabled_skills_for_scope(USER, "magic_tap"))),
           ("user", prompts.note_harness_continue_user(SPINE, BEATS, CONTENT, facts, profile))])

    ev_ctx = {"核心张力": SPINE, "结构节拍": "\n".join(f"- {b}" for b in BEATS),
              "知识库事实": "\n".join(f"- {f}" for f in facts)}
    write("05", "打分", "⑤ 打分 · harness/rubric.py 的 evaluate()",
          "六个维度各自独立打 0/1/2。**system prompt 在独立包里、是英文的**——"
          "包要能开源出去，不带任何中文领域词汇；维度定义由 app 侧作为配置传入。",
          [("system（包内置，英文）", DEFAULT_SYSTEM_PROMPT),
           ("user（context 字典由 harness_adapter 组装，包原样渲染）",
            _build_prompt(CONTENT, harness_adapter.note_dimensions(bool(profile)),
                          ev_ctx, tuple(dup_hints)))])

    write("06", "骨架重规划", "⑥ 骨架重规划 · REPLAN_SYSTEM",
          "有约束的局部修正，不是重新生成。只允许改写/删除/新增单条节拍，"
          "**不许换核心张力**，节拍数量不许净增，每次 run 最多两次。",
          [("system", prompts.REPLAN_SYSTEM),
           ("user", prompts.replan_user(
               TITLE, SPINE, BEATS, CONTENT, facts,
               why="正文已经紧扣核心张力，但结构节拍连续两轮判为覆盖不足。"
                   "这通常说明是节拍本身要求错了。"))])

    # ---------------------------------------------------------- 文件夹级
    goal = "写一份硬件从样机到量产的复盘，说清楚哪些问题是设计带来的、哪些是流程带来的"
    folder_ctx = prompts.folder_context_block(store.notes_in_folder(USER, None, limit=3))
    summaries = ["《成本口径》 ｜ 覆盖：配件计入、打样摊销 ｜ 报价前要逐项核对",
                 "《进度对齐》 ｜ 覆盖：完成标准、同步节奏 ｜ 定义要写进任务本身"]
    write("07", "分段计划", "⑦ 分段计划 · PLAN_SYSTEM（文件夹级）",
          "把一个写作目标拆成若干分段，每段各写一篇笔记。",
          [("system", prompts.compose_system(
              prompts.PLAN_SYSTEM, store.enabled_skills_for_scope(USER, "plan_generate"))),
           ("user", prompts.plan_user(goal, facts, folder_ctx))])

    write("08", "分段写作", "⑧ 分段写作 · section_write_user（文件夹级）",
          "跟单篇续写共用 MAGIC_TAP_SYSTEM，上下文块换成分段自己的主题 + 其他分段小结。",
          [("system（含 section_write 技能）", prompts.compose_system(
              prompts.MAGIC_TAP_SYSTEM, store.enabled_skills_for_scope(USER, "section_write"))),
           ("user", prompts.section_write_user(
               "设计带来的问题", goal, summaries, CONTENT, facts, folder_ctx,
               profile, focus="coherence"))])

    write("09", "分段修订", "⑨ 分段修订 · section_edit_user（文件夹级）",
          "跟单篇修订共用 EDIT_SYSTEM，上下文块换成分段自己的。",
          [("system（含 edit 技能）", prompts.compose_system(
              prompts.EDIT_SYSTEM, store.enabled_skills_for_scope(USER, "edit"))),
           ("user", prompts.section_edit_user(
               "设计带来的问题", goal, summaries, CONTENT, facts, profile,
               focus="non_repetition", dup_hints=dup_hints))])

    write("10", "判断还缺分段", "⑩ 判断还缺分段 · MORE_SECTIONS_SYSTEM（文件夹级）",
          "所有分段写完后判断还有没有遗漏。只看得到各分段的小结，"
          "所以小结里必须带上各级小标题，否则判重时看不见这段覆盖了什么。",
          [("system", prompts.compose_system(
              prompts.MORE_SECTIONS_SYSTEM, store.enabled_skills_for_scope(USER, "more_sections"))),
           ("user", prompts.more_sections_user(goal, summaries, facts, folder_ctx))])

    # ---------------------------------------------------------- KITE 检索编译
    try:
        from memoket_kite import Memory
        from memoket_kite.pipeline.compile_plan import _compile_prompt

        from app.database.kite.kite_memory import UserMemory, _export_provider_env
        from app.database.kite.kite_profile import WritingProfile

        _export_provider_env()
        um = UserMemory(USER)
        st, vc = um._index()
        base = Memory.load([str(um.path)])._reasoner()._profile
        q = "在讨论 APP 装不上的那次会议里，除了安装问题还提到了哪些待办事项"
        default_p = _compile_prompt(q, vc, st, base)
        writing_p = _compile_prompt(q, vc, st, WritingProfile(base, st, vc))
        write("11", "KITE检索编译", "⑪ KITE 检索编译 · compile_plan 的 prompt",
              f"左边是库自带的通用兜底 prompt（{len(default_p):,} 字符，其中 93.8% 是 2427 个 "
              f"session 的 id=date 全量清单），右边是写作场景定制的（{len(writing_p):,} 字符）。"
              "定制版补上了多跳 schema、明确了 grep 必须是短词干、并说明说话人标签不是稳定身份。",
              [(f"默认 profile（{len(default_p):,} 字符，完整）", default_p),
               (f"写作 profile（{len(writing_p):,} 字符，完整）", writing_p)])
    except Exception as exc:
        print(f"  ✗ KITE 编译 prompt 导出失败: {type(exc).__name__}: {exc}", flush=True)

    idx = OUT / "README.md"
    idx.write_text("\n".join(
        ["# 每一步实际发给模型的 prompt", "",
         f"导出时间：{datetime.now().isoformat(timespec='seconds')}　·　用户 {USER}（真实知识库）", "",
         "渲染的是**真实调用时拼好的完整消息**，不是 prompts.py 里的模板：",
         "system 部分带上了用户启用的写作技能，user 部分带上了真实的骨架、正文、",
         "知识库检索结果、机械查重候选、上一轮打分诊断、策略控制器注入的方向。", "",
         "生成脚本：`backend/scripts/dump_prompts.py`。", "",
         "## 单篇笔记 harness（一轮里按顺序调用）", ""]
        + [f"- [{n[3:-3]}]({n})" for n in written if n[:2] in ("01", "02", "03", "04", "05", "06")]
        + ["", "## 文件夹级无限续写", ""]
        + [f"- [{n[3:-3]}]({n})" for n in written if n[:2] in ("07", "08", "09", "10")]
        + ["", "## 知识库检索", ""]
        + [f"- [{n[3:-3]}]({n})" for n in written if n[:2] == "11"]
        + [""]), encoding="utf-8")
    print(f"\n共 {len(written)} 份 → {OUT}")


if __name__ == "__main__":
    main()
