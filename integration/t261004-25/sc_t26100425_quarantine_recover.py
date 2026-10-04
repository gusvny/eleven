#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-25 场景②：历史隔离批次找回——被错杀的本票测试文件机械复活（灰盒 L3）。

intent（工单不变量④「被挪走的文件必须可找回并在回执点名」；实案=t261004-18 五批
manifest、其引擎侧单测始终没进 commit）：
- **moved 项找回**：quarantine/unauth-*/manifest.json 里 action=moved、原路径命中
  本票测试面谓词的条目，settle 时被搬回原路径（内容零丢失）、manifest 条目标记
  已找回（带时间戳，审计面）、回执点名找回动作；
- **畸形 manifest 消费三态**（外部输入纪律）：manifest JSON 解析炸 → 跳过该批并
  **点名诊断**，不炸整个 settle；条目指向的留档件缺失 → 跳过并点名，绝不假装找回；
- **reverted 项不动**：非 moved 动作（diff 回滚类）不参与找回——那是另一条处置
  通道的留档，找回权不在本机制；
- **无票 id 不扫**：拿不到 ticket_id 时零行为（fail-closed 零变化）。

与相邻场景 intent 分界：
- sc_t26100425_test_face_gate：彼锁今后不再错杀（闸侧），本条锁历史错杀的找回
  （恢复侧）；
- t260916-19 disposal-matrix：彼锁处置动作本身（挪档/回滚/拒绝），本条只消费其
  manifest 产物做逆操作；
- developer L1（manifest 逐字段真值表）白盒随实现。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t261004-25/sc_t26100425_quarantine_recover.py（cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。实现落地前红属预期（TDD 信号）。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, HERE)
from lib_t26100425 import (  # noqa: E402
    check, engine_modules, env_fail, mk_lane, quarantine_root, rmtree, settle,
    summary,
)
from pathlib import Path

TID = "t261004-25"
LOST_REL = "server/engine/tests/test_t261004_25_lost_probe.py"
LOST_BODY = "# resurrect me: t261004-18 lost test face\n"


def craft_batch(lane, shared, name, items, files):
    """手工造一个历史隔离批次（与 _remediate_unauthorized_violations 落盘契约同形）。"""
    qroot = quarantine_root(lane, shared)
    batch = qroot / name
    batch.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = batch / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    # manifest 的 archive 字段与生产者同口径：相对泳道 cwd 的路径（留档件在
    # 隔离档内保留原相对路径）。
    for it in items:
        if it.get("archive") and not it["archive"].startswith("."):
            it["archive"] = str((batch / it["archive"]).relative_to(Path(lane)))
    (batch / "manifest.json").write_text(
        json.dumps({"ticket_stage": "implement", "gen": 0,
                    "ts": int(time.time() * 1000), "items": items},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return batch


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 settle 无 stdlib 替代子用例" % why)
    shared, aa = mods
    arch_rel = "server/engine/tests/test_t261004_25_lost_probe.py"

    # ---- L1 moved 项找回：原路径复活 + manifest 标记 + 回执点名 ----
    print("\n== L1 moved 找回：文件复活 + manifest 标记 + 回执点名")
    tmp, mainrepo, lane, fork = mk_lane("t26100425-r1-")
    batch = craft_batch(lane, shared, "unauth-implement-gen0",
                        [{"path": LOST_REL, "xy": "??", "action": "moved",
                          "archive": arch_rel,
                          "ts": 1}],
                        {arch_rel: LOST_BODY})
    r1 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/"])
    note1 = r1.note or ""
    restored = Path(lane) / LOST_REL
    check("L1a 文件回到原路径且内容零丢失",
          restored.is_file() and restored.read_text(encoding="utf-8") == LOST_BODY,
          "exists=%s" % restored.is_file())
    man = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    item = man["items"][0]
    check("L1b manifest 条目标记已找回（审计面在场，非静默）",
          bool(item.get("recovered")) and item.get("recovered_ts"),
          "item=%r" % item)
    check("L1c 回执点名找回动作（含原路径）", LOST_REL in note1,
          "note=%r" % note1[:300])
    rmtree(tmp)

    # ---- L2 畸形输入三态：坏 manifest 与缺失留档跳过且点名，settle 不炸 ----
    print("\n== L2 畸形 manifest / 缺失留档：跳过+点名，不炸不假绿")
    tmp, mainrepo, lane, fork = mk_lane("t26100425-r2-")
    qroot = quarantine_root(lane, shared)
    bad = qroot / "unauth-implement-gen0"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")
    craft_batch(lane, shared, "unauth-implement-gen1",
                [{"path": LOST_REL, "xy": "??", "action": "moved",
                  "archive": arch_rel, "ts": 1}],
                {})  # 留档件缺席
    r2 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/"])
    note2 = r2.note or ""
    check("L2a settle 正常完成（畸形输入不炸活动）", r2.error in (None, ""),
          "error=%r" % r2.error)
    check("L2b 坏 manifest 被点名诊断（不静默吞）",
          "gen0" in note2 or "manifest" in note2, "note=%r" % note2[:300])
    check("L2c 缺失留档的条目跳过且点名，不假装找回",
          ("gen1" in note2 or LOST_REL in note2) and not (Path(lane) / LOST_REL).exists(),
          "note=%r" % note2[:300])
    rmtree(tmp)

    # ---- L3 reverted 项不动；无票 id 不扫 ----
    print("\n== L3 reverted 不动 + 无票 id 零行为")
    tmp, mainrepo, lane, fork = mk_lane("t26100425-r3-")
    rev_rel = "docs/kb.md"
    batch = craft_batch(lane, shared, "unauth-implement-gen0",
                        [{"path": rev_rel, "xy": " M", "action": "reverted",
                          "diff": "kb.md.diff", "ts": 1}],
                        {rev_rel: "modified kb\n", "kb.md.diff": "--- a/docs/kb.md\n"})
    r3 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["integration/"])
    check("L3a reverted 留档件原样留在隔离档（找回权不在本机制）",
          (batch / rev_rel).is_file() and (batch / "kb.md.diff").is_file(),
          "batch disturbed")
    rmtree(tmp)
    tmp, mainrepo, lane, fork = mk_lane("t26100425-r4-")
    batch = craft_batch(lane, shared, "unauth-implement-gen0",
                        [{"path": LOST_REL, "xy": "??", "action": "moved",
                          "archive": arch_rel,
                          "ts": 1}],
                        {arch_rel: LOST_BODY})
    try:
        r4 = settle(shared, aa, lane, "", "implement", 1, fork,
                    write_set=["docs/"])
        swept = (batch / arch_rel).is_file() and not (Path(lane) / LOST_REL).exists()
        check("L3b 无票 id：零找回（文件仍在隔离档，fail-closed 零变化；参数层拒收空票 id 亦算守住的终态）",
              swept, "batch intact=%s" % (batch / arch_rel).is_file())
    except Exception as e:  # 参数层 fail-closed 拒收空票 id 也是合法终态（零找回）
        check("L3b 无票 id：入口拒收空票 id（fail-closed，零找回）",
              "ticket" in str(e).lower(), "raised %s: %s" % (type(e).__name__, e))
    rmtree(tmp)

    sys.exit(summary())


if __name__ == "__main__":
    main()
