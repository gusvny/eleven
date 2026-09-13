#!/usr/bin/env python3
"""t260913-03 场景②：例外腿（write_set 命中被跳池资产 → 强制全跑）正/负锁（真闸，灰盒 L2）。

intent（用户可感知）：一张票改到「被跳池自己的资产」时，集测段**必须跑被跳过的池**——
  否则「改了基础资产的票」正好跳过了验证该资产的池。判据纯机械：票面 write_set
  与（声明固定资产 ∪ 注册表派生资产：被跳场景文件本身的 cmd token + import 闭包）求交非空。
  同时钉死负锁：write_set 与资产**不相交**时绝不触发（否则开关白设）。

high-level steps：最小真泳道（声明 exclude_pools=engine,exclusive + 固定资产 integration/stage_docker.py），
  经真闸逐个形态传 write_set：声明固定资产 / 被跳场景文件 / 目录前缀 / 不相交 / 空写集——
  断言 ran（全跑 vs 在册）、回执 applied 与 forced_by 点名。
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

    # ---------------- 正腿 1：声明固定资产命中 ----------------
    g1 = F.call_gate(lane, apply=True, write_set=[DECLARED_ASSET])
    r1, pe1 = (g1.get("result") or {}), ((g1.get("result") or {}).get("pool_exclude") or {})
    C.check(r1.get("err") is None, "D1 真闸无 err", _diag(g1))
    C.check(r1.get("ran") == len(ALL_NAMES) and set(F.scenario_names(r1)) == set(ALL_NAMES),
            "D2 命中声明固定资产 → 强制全跑 %d 条（被跳池条目在册）" % len(ALL_NAMES), _diag(g1))
    C.check(pe1.get("applied") is False, "D3 回执 applied=false（未注入排除）", _diag(g1))
    C.check(DECLARED_ASSET in str(pe1.get("forced_by")),
            "D4 回执 forced_by 点名命中资产", "pool_exclude=%s" % pe1)

    # ---------------- 正腿 2：被跳场景文件本身（注册表 cmd token 派生面） ----------------
    g2 = F.call_gate(lane, apply=True, write_set=[DERIVED_ASSET])
    r2, pe2 = (g2.get("result") or {}), ((g2.get("result") or {}).get("pool_exclude") or {})
    C.check(r2.get("ran") == len(ALL_NAMES) and set(F.scenario_names(r2)) == set(ALL_NAMES),
            "D5 命中被跳场景文件本身 → 强制全跑", _diag(g2))
    C.check(DERIVED_ASSET in str(pe2.get("forced_by")),
            "D6 forced_by 点名被跳场景文件", "pool_exclude=%s" % pe2)

    # ---------------- 正腿 3：目录前缀形态 ----------------
    g3 = F.call_gate(lane, apply=True, write_set=[DIR_PREFIX])
    r3 = g3.get("result") or {}
    C.check(r3.get("ran") == len(ALL_NAMES) and (r3.get("pool_exclude") or {}).get("applied") is False,
            "D7 写集目录前缀命中被跳场景文件 → 强制全跑（前缀语义与写集判定同源）", _diag(g3))

    # ---------------- 负锁 1：write_set 不相交绝不触发 ----------------
    g4 = F.call_gate(lane, apply=True, write_set=["docs/testing-guide.md", "server/engine/shared.py"])
    r4, pe4 = (g4.get("result") or {}), ((g4.get("result") or {}).get("pool_exclude") or {})
    C.check(r4.get("err") is None, "D8 真闸无 err", _diag(g4))
    C.check(r4.get("ran") == len(IN_NAMES) and set(F.scenario_names(r4)) == set(IN_NAMES),
            "D9 负锁：写集不相交 → 排除照常生效（在册 %d 条）" % len(IN_NAMES), _diag(g4))
    C.check(pe4.get("applied") is True and not pe4.get("forced_by"),
            "D10 负锁：applied=true 且 forced_by 空", "pool_exclude=%s" % pe4)

    # ---------------- 负锁 2：空写集（老回放票形态）不得被当成全命中 ----------------
    g5 = F.call_gate(lane, apply=True, write_set=[])
    r5 = g5.get("result") or {}
    C.check((r5.get("pool_exclude") or {}).get("applied") is True
            and r5.get("ran") == len(IN_NAMES)
            and set(F.scenario_names(r5)) == set(IN_NAMES),
            "D11 空写集=无例外腿（回放票语义），排除照常生效",
            _diag(g5))

    # ---------------- 正腿 4：排除面为空集时不得误报「命中」 ----------------
    g6 = F.call_gate(lane, apply=True, write_set=["integration/mini/mini-main.py"])
    r6 = g6.get("result") or {}
    C.check((r6.get("pool_exclude") or {}).get("applied") is True
            and r6.get("ran") == len(IN_NAMES),
            "D12 命中**在册**条目文件（非被跳池资产）→ 不算例外腿，排除照常生效",
            _diag(g6))

sys.exit(C.finish())
