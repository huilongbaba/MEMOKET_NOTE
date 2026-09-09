"""harness-framework.md 的一致性检查。

    python3 docs/_research/check_harness_doc.py

每一条都是机械可验证的。写这个脚本的理由：这份文档改了十几轮，每一轮都
留下不一致（子节编号没跟着父节、Mode 定义里漏挂 middleware、废弃的术语
残留、State 用到没定义的字段），而这些**全都是靠人眼一次次发现的**。
靠自觉不行，靠检查。

改完文档跑一次，绿了再提交。加新的约束就往这里加一条 chk()。
"""
import pathlib, re, sys
t = pathlib.Path("docs/harness-framework.md").read_text()
ls = t.split("\n")
bad = []
def chk(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f"  → {detail}"))
    if not cond: bad.append(name)

print("── 结构 ──")
chk("代码块配对", sum(1 for l in ls if l.startswith("```")) % 2 == 0)
nums = [int(m.group(1)) for l in ls if (m := re.match(r"^## (\d+)\.", l))]
chk("章节连号", nums == list(range(len(nums))), str(nums))
sub_bad = []
cur = None
for i, l in enumerate(ls, 1):
    if m := re.match(r"^## (\d+)\.", l): cur = m.group(1)
    if (m2 := re.match(r"^### (\d+)\.(\d+)", l)) and m2.group(1) != cur:
        sub_bad.append(f"{i}行 {m2.group(0)}@第{cur}节")
chk("子节编号跟父节一致", not sub_bad, str(sub_bad))
refs = {int(x) for x in re.findall(r"见第 (\d+) 节", t)} | {int(x) for x in re.findall(r"第 (\d+) 节", t)}
chk("章节引用存在", refs <= set(nums), str(refs - set(nums)))
sub = {f"{a}.{b}" for a, b in re.findall(r"^### (\d+)\.(\d+)", t, re.M)}
# 匹配所有引用形态：「见 10.8」「第 10.8 节」「（10.8）」——
# 漏掉不带「节」字的那种，就抓不到 SKILL.md 例子里那两处错的交叉引用
subrefs = set(re.findall(r"(?:见|第|（)\s*(\d+\.\d+)", t))
chk("子节引用存在", subrefs <= sub, str(subrefs - sub))
toc = set(re.findall(r"\[(\d+) ", t.split("---")[1] if "---" in t else ""))
chk("目录条数 == 章节数", len(toc) == len(nums) or not toc, f"目录{len(toc)} vs 章节{len(nums)}")

print("── 类型自洽 ──")
def fields(cls):
    m = re.search(rf"class {cls}[^:]*:(.*?)(?:\n\n\n|\n```)", t, re.S)
    return set(re.findall(r"^    (\w+):", m.group(1), re.M)) if m else set()
st_f = fields("State")
st_u = set(re.findall(r"\bst\.(\w+)", t)) - {"rank", "mode", "round"}
chk("State 字段齐", st_u <= st_f | {"mode", "round"}, str(st_u - st_f))
md_f = fields("Mode")
md_u = {a or b for a, b in re.findall(r"\bmode\.(\w+)|st\.mode\.(\w+)", t)} - {"xxx"}
chk("Mode 字段齐", md_u <= md_f, str(md_u - md_f))

print("── middleware 一致性 ──")
proto = set(re.findall(r"async def (\w+)\(self, st", re.search(
    r"class Middleware\(Protocol\):(.*?)\n\n\nCheck", t, re.S).group(1)))
fired = set(re.findall(r'_fire\(mw, "(\w+)"', t))
chk("_fire 的钩子都已声明", fired <= proto, str(fired - proto))
base = re.search(r"BASE: tuple\[Middleware, \.\.\.\] = \(\n    (.+?)\n\)", t, re.S).group(1)
base_n = [x.strip().rstrip("()") for x in base.split(",") if x.strip()]
tbl_base = [m.group(1) for m in re.finditer(r"^\| `(\w+)` \| `(?:before|after)_\w+` \| .+ \|$", t, re.M)]
chk("BASE 表顺序对齐", tbl_base[:len(base_n)] == base_n, f"{tbl_base[:len(base_n)]} vs {base_n}")
extra_tbl = {m.group(1) for m in re.finditer(r"^\| `(\w+)` \| `(?:before|after)_\w+` \| .+ \| (?:note|block).+\|$", t, re.M)}
# 括号配对而不是 [^)]*：extra_mw=(Revise(), Save()) 里的 Revise() 自带括号，
# 非贪婪匹配会在第一个 ) 就停下，漏掉后面所有的（反向验证抓到过这个 bug）。
extra_names = set()
for m in re.finditer(r"extra_mw=\(", t):
    i, depth = m.end() - 1, 0
    while i < len(t):
        if t[i] == "(": depth += 1
        elif t[i] == ")":
            depth -= 1
            if depth == 0: break
        i += 1
    extra_names |= set(re.findall(r"\b([A-Z]\w+)\(\)", t[m.end():i]))
chk("extra_mw 用到的都在表里", extra_names <= extra_tbl | set(base_n), str(extra_names - extra_tbl - set(base_n)))

print("── 术语 ──")
for word, why in [("with_skills", "已废弃：skill 不再叠加到 Mode"),
                  ("叠加到 Mode", "已废弃"),
                  ("规则型", "已废弃的二分"), ("任务型", "已废弃的二分"),
                  ("compact_facts", "不存在的函数"),
                  ("mode_from_skill", "已废弃")]:
    n = t.count(word)
    chk(f"无「{word}」", n == 0, f"{n} 处（{why}）")

print("── 需求 ──")
R = sorted({int(x) for x in re.findall(r"\bR(\d+)\b", t)})
chk("R 连续", R == list(range(1, max(R)+1)), str(R))
r1 = [int(x) for x in re.findall(r"\| \*\*R(\d+)\*\* \|", t)]
chk("需求表有序", r1 == sorted(r1), str(r1))
r2 = [int(x) for x in re.findall(r"^\| R(\d+) \|", t, re.M)]
chk("借鉴表有序", r2 == sorted(r2), str(r2))
chk("两表条数一致", len(r1) == len(r2), f"{len(r1)} vs {len(r2)}")

print(f"\n{len(ls)} 行 · {len(nums)} 节 · {len(sub)} 子节 · {len(bad)} 个问题")
sys.exit(1 if bad else 0)
