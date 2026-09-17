"""屏幕活动（Daily Journey）里**不需要模型也能算准**的那一半。

这个包只有纯函数：给一天的段落，算出时长、连续专注的块、反复来回的地方。
`routers/journey.py` 负责 I/O 和模型调用，这里一个都不碰。

分这条线是这个仓库的老规矩：**能用规则算准的就不交给模型**。日报里
「时间去哪了」那一节如果让模型去数，它会数错——而它数错的时候读起来
跟数对了一模一样。
"""

from .runs import group_runs, similar
from .stats import AppSpan, Churn, DayStats, Stretch, day_stats, render_time_block

__all__ = ["AppSpan", "Churn", "DayStats", "Stretch", "day_stats", "group_runs",
           "render_time_block", "similar"]
