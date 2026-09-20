#!/usr/bin/env python3
"""t260913-03 场景②：旧例外分支命中面留痕 + 「声明即跳过」正/负锁（真闸，灰盒 L2）。

宿主管 260914 口径变更（起因＝KI-089：写集带目录形条目时例外分支恒命中，排除声明对全部
在跑票失效）：例外分支**已撤除**——每票段一律跳过声明池，被跳池只由项目级全量轮
（巡检/手动/回放，不传 apply）覆盖。本场景随之改判：

intent（用户可感知）：①一张票无论改到什么资产，集测段**都按声明跳过**被跳池（不再被
  「碰了就得全跑」拦下）；②旧口径的命中面必须**可见**——回执 former_force_assets 逐项
  点名「这些资产在旧口径下会触发全跑」，不许静默消失（少跑必须点名到回执）；③负锁：
  写集与资产面不相交时该字段为空，不许无差别乱报。

high-level steps：最小真泳道（声明 exclude_pools=engine,exclusive + 固定资产 integration/stage_docker.py），
  经真闸逐个形态传 write_set：声明固定资产 / 被跳场景文件 / 目录前缀 / 不相交 / 空写集 /
  在册条目文件——断言 ran（在册面）、回执 applied=true 与 former_force_assets 点名。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_pool_exclude_lane as F  # noqa: E402

C = F.Checker("t260913-03-scenario-2-force-assets")

# 契约面前置：闸的「消费声明」参数必须在工具 schema 里声明（实现段落地前红=预期 TDD 信号）
_key, _err = F.gate_apply_contract()
if not C.check(_key is not None, "P0 闸消费参数已在 verify_lane TOOL schema 声明（契约面）", _err):
    sys.exit(C.finish())

SPEC = [
    ("mini-main", "main", True),
    ("mini-ro", "ro", True),
    ("mini-engine", "engine", True),
    ("mini-engine2", "engine", True),
    ("mini-excl", "exclusive", True),
]
EXCLUDED_POOLS = ("engine", "exclusive")
ALL_NAMES = [n for n, _, _ in SPEC]
IN_NAMES = [n for n, p, _ in SPEC if p not in EXCLUDED_POOLS]
DECLARED_ASSET = "integration/stage_docker.py"           # 与真票面声明同形的固定资产
DERIVED_ASSET = "integration/mini/mini-engine.py"        # 被跳条目的场景文件本身（cmd token 派生面）
DIR_PREFIX = "integration/mini/"                         # 目录前缀形态（_in_write_set 前缀语义）


def _diag(g):
    r = g.get("result") or {}
    return "ok=%s err=%s ran=%s names=%s pool_exclude=%s" % (
        g.get("ok"), r.get("err"), r.get("ran"), F.scenario_names(r), r.get("pool_exclude"))


with F.tmpdir() as td:
    lane = F.build_lane(Path(td) / "lane", SPEC,
                        force_assets=(DECLARED_ASSET,))["lane"]

    # ---------------- 命中态 1：声明固定资产命中 → 仍跳过 + 留痕 ----------------
    g1 = F.call_gate(lane, apply=True, write_set=[DECLARED_ASSET])
    r1, pe1 = (g1.get("result") or {}), ((g1.get("result") or {}).get("pool_exclude") or {})
    C.check(r1.get("err") is None, "D1 真闸无 err", _diag(g1))
    C.check(r1.get("ran") == len(IN_NAMES) and set(F.scenario_names(r1)) == set(IN_NAMES),
            "D2 命中声明固定资产 → 仍按声明跳过（在册 %d 条）" % len(IN_NAMES), _diag(g1))
    C.check(pe1.get("applied") is True, "D3 回执 applied=true（已注入排除）", _diag(g1))
    C.check(DECLARED_ASSET in str(pe1.get("former_force_assets")),
            "D4 回执 former_force_assets 点名命中资产（旧口径命中面可见）", "pool_exclude=%s" % pe1)

    # ---------------- 命中态 2：被跳场景文件本身（注册表 cmd token 派生面） ----------------
    g2 = F.call_gate(lane, apply=True, write_set=[DERIVED_ASSET])
    r2, pe2 = (g2.get("result") or {}), ((g2.get("result") or {}).get("pool_exclude") or {})
    C.check(r2.get("ran") == len(IN_NAMES) and set(F.scenario_names(r2)) == set(IN_NAMES),
            "D5 命中被跳场景文件本身 → 仍按声明跳过", _diag(g2))
    C.check(DERIVED_ASSET in str(pe2.get("former_force_assets")),
            "D6 former_force_assets 点名被跳场景文件", "pool_exclude=%s" % pe2)

    # ---------------- 命中态 3：目录前缀形态（KI-089 的现场形态） ----------------
    g3 = F.call_gate(lane, apply=True, write_set=[DIR_PREFIX])
    r3, pe3 = g3.get("result") or {}, ((g3.get("result") or {}).get("pool_exclude") or {})
    C.check(r3.get("ran") == len(IN_NAMES) and pe3.get("applied") is True
            and pe3.get("former_force_assets"),
            "D7 写集目录前缀 → 仍跳过，且旧口径命中面留痕非空（KI-089 不再致排除失效）", _diag(g3))

    # ---------------- 负锁 1：write_set 不相交 → 排除照常、留痕为空 ----------------
    g4 = F.call_gate(lane, apply=True, write_set=["docs/testing-guide.md", "server/engine/shared.py"])
    r4, pe4 = (g4.get("result") or {}), ((g4.get("result") or {}).get("pool_exclude") or {})
    C.check(r4.get("err") is None, "D8 真闸无 err", _diag(g4))
    C.check(r4.get("ran") == len(IN_NAMES) and set(F.scenario_names(r4)) == set(IN_NAMES),
            "D9 负锁：写集不相交 → 排除照常生效（在册 %d 条）" % len(IN_NAMES), _diag(g4))
    C.check(pe4.get("applied") is True and not pe4.get("former_force_assets"),
            "D10 负锁：applied=true 且 former_force_assets 空", "pool_exclude=%s" % pe4)

    # ---------------- 负锁 2：空写集（老回放票形态）不得被当成全命中 ----------------
    g5 = F.call_gate(lane, apply=True, write_set=[])
    r5 = g5.get("result") or {}
    C.check((r5.get("pool_exclude") or {}).get("applied") is True
            and r5.get("ran") == len(IN_NAMES)
            and set(F.scenario_names(r5)) == set(IN_NAMES),
            "D11 空写集=无例外分支（回放票语义），排除照常生效",
            _diag(g5))

    # ---------------- 正用例 4：排除面为空集时不得误报「命中」 ----------------
    g6 = F.call_gate(lane, apply=True, write_set=["integration/mini/mini-main.py"])
    r6 = g6.get("result") or {}
    C.check((r6.get("pool_exclude") or {}).get("applied") is True
            and r6.get("ran") == len(IN_NAMES),
            "D12 命中**在册**条目文件（非被跳池资产）→ 不算例外分支，排除照常生效",
            _diag(g6))

sys.exit(C.finish())
