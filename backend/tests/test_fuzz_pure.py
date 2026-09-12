"""纯函数的健壮性：随机中英数字标点混着喂，一个都不能抛。固定种子，600 例（第 149 轮巡检时
先跑了 3000 例零失败，这里留一份小的当回归）。"""

from __future__ import annotations

import random
from types import SimpleNamespace

from app.database import exporters
from app.database.kb import relations
from app.database.kb.units import part_labels
from app.harness.checks import citations

_ALPHABET = "甲乙丙丁戊己庚辛壬癸0123456789 mAh元%日月年-/.:：，。abcXYZ[]()#*>|`\n\n\n"


def _rnd(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, n)))


def test_纯函数随机输入不抛异常():
    rng = random.Random(7)
    for _ in range(600):
        p = _rnd(rng, 120)
        facts = [{"id": f"u-{k}-A{k}", "text": _rnd(rng, 80),
                  "date": rng.choice(["", "2026-05-08", "2026-13-40", "x"])} for k in range(rng.randint(0, 6))]
        relations.detect(p, facts)
        relations.extract_values(p)
        exporters.md_to_notion_blocks(p)
        exporters.md_to_feishu_children(p)
        citations.fake_citations(p, [f["text"] for f in facts], lambda fid: False)
        citations.strip_citations(p, citations.malformed_citations(p))
        units = [SimpleNamespace(id=_rnd(rng, 12) or "x", date=rng.choice(["", "2026-01-01"]), title=_rnd(rng, 10))
                 for _ in range(rng.randint(0, 5))]
        part_labels(units)
        exporters.safe_name(p)
        exporters.display_title(_rnd(rng, 20), p)
