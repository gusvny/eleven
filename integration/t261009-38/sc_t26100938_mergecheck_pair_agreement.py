#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-38 场景②：合并闸白名单面与段闸同认一条声明——重建产物不换一张红脸。

intent（工单不变量④「BOTH FACES MUST AGREE」+ ②「src 不在写集 → out 不放宽」在
merge_check verify_lane code 道写集白名单上的用户可感知面）：
- M1 src 在工单写集 → 合并闸以**加宽后的白名单**判（票写集 ∪ 声明 out 前缀，
  `_bundle_widened_write_set`）→ 白名单绿；加宽 note 点名规则与前缀（named, never
  silent）。这是 gen0 评审实锤的第二死结面：只修段闸时，重建件进 commit 后在这里
  以「越界写」换一张红脸继续死锁（t261009-22/-35 实测两轮）。
- M2 src 不在写集 → 加宽集=原集（note 空）→ 同一 out 改动照旧红「越界写」。
- M3 窄缝不失效：加宽后的白名单下，声明外真越权件照旧红。
- M4 泳道声明缺失 → 不加宽（fail-closed）→ out 改动照旧红。
- M5 声明畸形 → 不加宽且具名留痕（fail-closed，操作员看得见为何没放宽）。

实现口径（与 plan v2 的偏离，developer 记录）：plan 原钉「verify_lane._ws_refuse
镜像 + 写集扩区 server/tools/verify_lane.py」；扩区四轮未批，本面改钉在
merge_check 调用点（agent_activities，写集内）——白名单判定仍全在 verify_lane
工具内，本面只修「判据是哪个集合」，note 记名、fail-closed 不变。verify_lane 内
镜像（任何调用方同享）仍是后续理想位，归 follow-up 债。

与相邻场景 intent 分界：
- sc_t26100938_gate_admits_bundle_out：彼锁段路径闸（settle 脏清单），本条锁合并闸
  白名单面——同一声明的两个执法点，分点不分家；
- bundle_freshness 红（src 改了没重建仍红）本票不触碰（工单规格⑥），不在本条重判；
- developer L1（bundle_out_prefixes / 加宽 helper 真值表）白盒随实现，不在本条重铺。

跑法：python3 -B integration/t261009-38/sc_t26100938_mergecheck_pair_agreement.py
      （cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from lib_t26100938 import (  # noqa: E402
    MALFORMED_CHECKS_YAML, OUT, SRC, TID, check, dirty, engine_modules, env_fail,
    git_ok, mk_bundle_lane, rmtree, run_verify_code, summary,
)

OUTFILE = OUT + "client.js"
WS_ID = "write_set_whitelist"


def ws_result(lane, fork, write_set):
    """verify_lane code 道公开入口：白名单检查项（diff = fork...HEAD）。"""
    res = run_verify_code({"path": str(lane), "base": str(fork),
                           "write_set": list(write_set), "ticket_id": TID})
    for c in res.get("checks", []):
        if c.get("id") == WS_ID:
            return c
    return {}


def commit(lane, paths):
    ok, out = git_ok(["add", "-A"], lane)
    ok2, out2 = git_ok(["commit", "-qm", "lane work"], lane)
    if not (ok and ok2):
        raise RuntimeError("fixture commit 失败: %s%s" % (out[-150:], out2[-150:]))


def main():
    try:
        run_verify_code  # noqa: B018  装载探针
        from lib_env import no_narrowing_env  # noqa: F401
    except Exception as e:
        env_fail("verify_lane/夹具链不可导入（%s: %s）" % (type(e).__name__, e))
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——合并闸加宽面无替代子用例" % why)
    _shared, aa = mods
    widened = aa._bundle_widened_write_set

    # ---- M1 双面同认：src 在写集，合并闸白名单以加宽集判，重建件放行 + note 点名 ----
    print("\n== M1 src 在写集：白名单加宽放行重建件 + note 点名")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-m1-")
    dirty(lane, SRC + "widget.ts", "export const w = 2\n")
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    commit(lane, None)
    eff1, note1 = widened(lane, [SRC])
    check("M1a 加宽集含声明 out 前缀（票写集 ∪ 声明 out）",
          OUT.rstrip("/") in [e.rstrip("/") for e in eff1] and SRC in eff1,
          "eff=%r" % eff1[:4])
    check("M1b note 点名规则与前缀（named, never silent）",
          "bundle-out-face rule" in (note1 or "") and OUT.rstrip("/") in (note1 or ""),
          "note=%r" % (note1 or "")[:300])
    c1 = ws_result(lane, fork, eff1)
    check("M1c 白名单绿（重建件不再换红脸）", not c1.get("items"),
          "items=%r" % (c1.get("items") or [])[:2])
    rmtree(tmp)

    # ---- M2 src 不在写集：不加宽，out 改动照旧越界红 ----
    print("\n== M2 src 不在写集：不放宽")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-m2-")
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    commit(lane, None)
    eff2, note2 = widened(lane, ["docs/"])
    check("M2a 不加宽（集合原样、note 空）",
          list(eff2) == ["docs/"] and note2 == "",
          "eff=%r note=%r" % (eff2[:3], (note2 or "")[:120]))
    c2 = ws_result(lane, fork, eff2)
    items2 = str(c2.get("items", []))
    check("M2b 白名单红且点名 out 件（越界写）",
          bool(c2.get("items")) and OUTFILE in items2, "items=%r" % items2[:300])
    rmtree(tmp)

    # ---- M3 窄缝：加宽后声明外越权件照旧红 ----
    print("\n== M3 混入声明外越权件：照旧红")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-m3-")
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    dirty(lane, "server/engine/rogue_helper.py", "not lawful\n")
    commit(lane, None)
    eff3, _ = widened(lane, [SRC])
    c3 = ws_result(lane, fork, eff3)
    items3 = str(c3.get("items", []))
    check("M3a 越权件被红点名", "rogue_helper.py" in items3, "items=%r" % items3[:300])
    rmtree(tmp)

    # ---- M4 声明缺失：fail-closed 不加宽，照旧红 ----
    print("\n== M4 泳道无声明：无放行")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-m4-", checks=None)
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    commit(lane, None)
    eff4, note4 = widened(lane, [SRC])
    check("M4a 不加宽（声明缺失=合法 opt-out，note 空）",
          list(eff4) == [SRC] and note4 == "",
          "eff=%r note=%r" % (eff4[:3], (note4 or "")[:120]))
    c4 = ws_result(lane, fork, eff4)
    check("M4b 声明缺失时 out 改动照旧红", bool(c4.get("items")),
          "items=%r" % str(c4.get("items", []))[:200])
    rmtree(tmp)

    # ---- M5 声明畸形：不加宽且具名留痕 ----
    print("\n== M5 声明畸形：具名 fail-closed")
    tmp, mainrepo, lane, fork = mk_bundle_lane("t26100938-m5-",
                                               checks=MALFORMED_CHECKS_YAML)
    dirty(lane, OUTFILE, "rebuilt bundle\n")
    commit(lane, None)
    eff5, note5 = widened(lane, [SRC])
    check("M5a 不加宽且 note 具名（操作员看得见为何没放宽）",
          list(eff5) == [SRC] and "no widening" in (note5 or ""),
          "eff=%r note=%r" % (eff5[:3], (note5 or "")[:200]))
    rmtree(tmp)

    sys.exit(summary())


if __name__ == "__main__":
    main()
