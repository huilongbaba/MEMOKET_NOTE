"""屏幕活动日报的确定性体检（计划 8.2）。

五条判据在**两份真实日报**（2026-09-17 / 09-18，18 条 bullet）上开火 0——阈值
就是在那两份上量的（`scripts/tap_report_denominator.py`）。所以这一份测试跟
`test_skeleton_checks` / `test_tap_checks` 同一个重心：**逐条植入**。

下面这份 `REAL` 是 2026-09-18 那份真实日报里模型写的那一半（节选，逐字），
`LINES` 是那一次真正进了提示词的几行的形状。
"""

from __future__ import annotations

from app.harness.checks.journey import DUP_BULLET, check_report

REAL = """## 推进了什么
- 围绕 `harness-upgrade-plan.md` 检查了阶段 11“从没审过的部件”清单、`policy.py` 脏态与检索预算归零问题。
- 推进了 `TranscriptionTodoSyncButtons` 与 `circle_action_item_tile.dart` 的圈子待办同步迁移方案。

## 卡在哪
- Claude 页面在上午反复停留于 Cloudflare“正在验证”。

## 计划外的
- 上午切换查看了 Amazon 的 `Gem Wearable AI Voice Recorder`（`$199.00`）。"""

LINES = [
    "09:55–10:07 Code 在 harness-upgrade-plan.md 里看阶段 11「从没审过的部件」清单，"
    "以及 policy.py 的脏信号和检索预算归零（5 段）",
    "10:15–10:35 Safari 打开 Amazon 的 Gem Wearable AI Voice Recorder 商品页，标价 $199.00",
    "10:57–12:51 Code 在改 TranscriptionTodoSyncButtons 和 circle_action_item_tile.dart 的"
    "圈子待办同步（9 段）",
    "13:03–13:15 Safari Claude 页面停在 Cloudflare 正在验证",
]


def test_一份真实日报一条都不报():
    """两份真实日报上五条全部干净，这一条是其中之一的回归钉。"""
    chk = check_report(REAL, LINES)
    assert chk.notes() == []
    assert chk.bullets == 4


# ------------------------------------------------- 逐条的植入用例 ---


def test_模型自己算时长报得出来():
    """提示词里最要紧的那条规矩：**模型数时长会数错，而它数错的时候读起来跟
    数对了一模一样**。「时间去哪了」是程序按时间戳算的，模型不许重算。"""
    bad = REAL.replace("检查了阶段 11", "花了 47 分钟检查阶段 11")
    chk = check_report(bad, LINES)
    assert chk.recomputed_durations == ["47 分钟"]
    assert any("程序按时间戳算" in n for n in chk.notes())


def test_记录里本来就写着的时长不算模型算的():
    """记录说「开了 30 分钟的会」，日报引用它是对的——**自己算出来的才是错的**。
    这一条是那条判据窄下来的地方，没有它就会在正常引用上开火。"""
    lines = [*LINES, "14:00–14:30 Feishu cycle对齐会，日程上写着 30 分钟"]
    bad = REAL.replace("Claude 页面", "30 分钟的 cycle对齐会之后 Claude 页面")
    assert check_report(bad, lines).recomputed_durations == []


def test_多写了规定之外的小节报得出来():
    bad = REAL + "\n\n## 明天打算做什么\n- 把阶段 11 那条清单读完。"
    chk = check_report(bad, LINES)
    assert chk.stray_sections == ["明天打算做什么"]
    assert any("三节" in n for n in chk.notes())


def test_把程序算好的那一节又写了一遍也算多写():
    """「时间去哪了」不在白名单里，正是因为那一节由 `render_time_block` 渲染。"""
    bad = "## 时间去哪了\n- Code 大约占了大半天。\n\n" + REAL
    assert "时间去哪了" in check_report(bad, LINES).stray_sections


def test_一个具体东西都不带的条目报得出来():
    bad = REAL.replace(
        "- Claude 页面在上午反复停留于 Cloudflare“正在验证”。",
        "- 继续推进了开发工作，整体节奏还算顺。")
    chk = check_report(bad, LINES)
    assert chk.vague_bullets == ["继续推进了开发工作，整体节奏还算顺。"]
    assert any("等于没写" in n for n in chk.notes())


def test_同一节里两条说同一件事报得出来():
    """植入方式跟真实失败同形：同一件事换个角度再写一条。"""
    bad = REAL.replace(
        "- 推进了 `TranscriptionTodoSyncButtons` 与 `circle_action_item_tile.dart` 的圈子待办同步迁移方案。",
        "- 推进了 `TranscriptionTodoSyncButtons` 与 `circle_action_item_tile.dart` 的圈子待办同步迁移方案。\n"
        "- 推进了 `circle_action_item_tile.dart` 与 `TranscriptionTodoSyncButtons` 的圈子待办同步迁移。")
    chk = check_report(bad, LINES)
    assert chk.duplicate_bullets
    _a, _b, ratio = chk.duplicate_bullets[0]
    assert ratio >= DUP_BULLET
    assert any("一件事只写一条" in n for n in chk.notes())


# 2026-09-17 那份真实日报里「推进了什么」内部两两最像的一对，逐字。**这一对
# 就是 0.55 那个门槛的全部安全边际**：它是两天六节里最像的一对，0.264。
CLOSEST_REAL_PAIR = """## 推进了什么
- 分析 `AppInitializer._setupGlobalErrorHandlers.<fn>` 引发的 FlutterError `"Context disposed before completion"`，并对照 `SignInHubActivity.onCreate` 的 `NullPointerException`、README.md 和 1.2.8/1.2.6 版本差异。
- 上午继续梳理 MEMOKET_NOTE harness，查看 `config.py#31-34`、`backend/app/harness/pick_dimension`、`hooks/note.py:112` 的 `prepare`、`cleanup_only` 跳过 `produce` 逻辑，以及 `harness-evaluator-industry.md` 第 757 轮调研中的“多目标不要折叠成标量”。"""


def test_真实日报里最像的那一对也不算撞车():
    """**门槛的安全边际就靠这一条钉着。** 两天六节里同一节内部两两最像的一对
    是 0.264（就是这两条），门槛 0.55 留了一倍的空当——把门槛往下挪到实测
    分布里面去，这条会当场变红。

    *这一条是补出来的*：第一版只有上面那个植入用例和一份撞车相似度 0.044 的
    干净素材，**把门槛调到 0.25 全套一条不红**——判据的安全边际没有任何东西
    在盯着。连着十三批的同一条教训：没抓住先怀疑用例不够。
    """
    from app.journey.runs import similar

    items = [ln[2:] for ln in CLOSEST_REAL_PAIR.splitlines() if ln.startswith("- ")]
    assert 0.25 <= similar(*items) < DUP_BULLET, "这一对不再是实测的那一对了"
    assert check_report(CLOSEST_REAL_PAIR, LINES).duplicate_bullets == []


# 09-18 那份真实日报里跨节最像的一对，逐字：一条在「推进了什么」、一条在
# 「卡在哪」，相似度 **0.679**——**远在门槛之上，而它不该被报**。
CROSS_SECTION_REAL_PAIR = """## 推进了什么
- 围绕 `harness-upgrade-plan.md` 检查了阶段 11“从没审过的部件”清单、`policy.py` 脏态与检索预算归零问题，并查看了 `Bash Inspect layering/parity failures` 失败日志。

## 卡在哪
- `harness-upgrade-plan.md` 的部件清单多次仍停留在 `0/7`，同时 `policy.py` 出现“检索预算到 0”和 `Bash Inspect layering/parity failures` 失败日志，显示 harness 检查尚未推进到下一阶段。"""


def test_跨节讲同一个文件不算撞车():
    """**这一条比上一条重要**：09-18 那份真实日报里「推进了什么」和「卡在哪」
    各有一条讲 `harness-upgrade-plan.md`，相似度 **0.679**——那是两件事
    （推进到哪 / 卡在哪），而提示词那条规矩原话说的是「**这一节**」。

    *这一条是补出来的*：第一版自己编了一对跨节的句子，相似度没到门槛，
    **把「按节切」整个拆掉全套一条不红**。换成实测那一对（0.679）之后才真的
    在判「跨节不算」这件事。
    """
    from app.journey.runs import similar

    items = [ln[2:] for ln in CROSS_SECTION_REAL_PAIR.splitlines() if ln.startswith("- ")]
    assert similar(*items) >= DUP_BULLET, "这一对不再是实测的那一对了"
    assert check_report(CROSS_SECTION_REAL_PAIR, LINES).duplicate_bullets == []


def test_记录里查不到的名字报得出来():
    """「这跟写作 harness 里 `material_used` 那条判据是同一场仗」——日报的
    提示词注释里逐字写着这句，这一条就是把它落成判据。"""
    bad = REAL.replace("`policy.py` 脏态", "`replan_rules.py` 脏态")
    chk = check_report(bad, LINES)
    assert "replan_rules.py" in chk.unsourced_terms
    assert any("查不到" in n for n in chk.notes())


def test_把记录里的路径拼长一点不算查无出处():
    """09-17 那份真实日报里模型写了 `backend/app/harness/pick_dimension`，
    而记录里那几层目录和函数名是分开出现的——**整条路径是拼的，每一段都有
    出处**。不按 `/` 切开的话，这条判据在两天里唯一的一次开火就是误伤。"""
    lines = [*LINES, "11:20–11:40 Code 看 backend 里 app/harness 的 pick_dimension"]
    bad = REAL.replace("`policy.py` 脏态",
                       "`backend/app/harness/pick_dimension` 与 `policy.py` 脏态")
    assert check_report(bad, lines).unsourced_terms == []


def test_中文短语不查出处():
    """记录是一句描述、日报是归纳，中文必然被改写——逐字比对只会全军覆没。
    查的只是文件名 / 应用名 / 函数名那一类**逐字搬过来**的东西。"""
    bad = REAL.replace("圈子待办同步迁移方案", "待办双向同步的整体迁移设计")
    assert check_report(bad, LINES).unsourced_terms == []


# ------------------------------------------------- 接线那一半 ---


def test_判了不拦着落盘():
    """**形态照 `slides` / `skeleton`**：日报是一次成型的产物，判据的结果跟它
    一起返回、一起落进 `report.json`，重不重写由用户定。"""
    import inspect

    from app.routers import journey

    src = inspect.getsource(journey.report)
    assert "check_report" in src, "日报端点没有接体检"
    after = src.split("check_report")[1]
    assert "raise HTTPException" not in after, "体检结果不许拦着日报返回"
    assert '"report_notes": notes' in src, "体检结果要跟日报一起落盘，刷新之后还在"
    assert "notes=notes" in src


def test_判的是模型那一半不是程序算好的那一节():
    """判自己算的东西没有意义：`render_time_block()` 渲染的那一节里全是时长，
    拿时长判据去判它，每一份日报都会当场报错。"""
    import inspect

    from app.routers import journey

    src = inspect.getsource(journey.report)
    assert "check_report(text.strip(), lines)" in src, (
        "必须判 `text`（模型写的那一半）和 `lines`（真正进了提示词的那几行）")


def test_翻回旧的一天也看得见体检结果():
    """日报落盘之后靠 `GET /day` 读回来。这一条钉的是**那个白名单**——
    少一个键，刷新一次判据结果就没了，而用户看不出少了什么。"""
    import inspect

    from app.routers import journey

    src = inspect.getsource(journey.day)
    assert "report_notes" in src
