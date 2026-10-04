#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-25 场景①：本票测试面放行——写集闸不再吞掉合法交付（灰盒 L3，真 git 直调 settle）。

intent（工单不变量③「写集外的合法交付必须有定义的、可见的落地面」的用户可感知面）：
- **本票自名测试文件过闸**：ticket 声明写集不含它（如 t261004-19 实案形态），但
  basename 以 test_ 开头、含本票 slug、位于测试面（tests/ 段或 integration/）的
  未跟踪新文件 **不被判 unauthorized_path、不被挪档**——文件原地在场，回执**点名**
  这条规则放行了它（named, never silent）；
- **同一批次里的真越权件照旧处置**：非测试面/非本票命名的越权 `??` 文件仍被挪档＋
  回执点名——放行是窄缝，不是写集闸失效；
- **测试面边界 fail-closed**：本票命名的 test_ 文件若在测试面**之外**（无 tests/ 段、
  不在 integration/ 下）不享受放行，照常处置——缝隙不许被路径形状撑大。

与相邻场景 intent 分界：
- sc_t26100425_mergecheck_carveout：彼锁**合并闸**（verify_lane code 道 diff 面），
  本条锁**段路径闸**（settle 时刻脏清单）；同一条谓词的两个执法点，分点不分家；
- sc_t26100425_quarantine_recover：彼锁**历史隔离批次的找回**（已经发生的错杀），
  本条锁**今后不再错杀**；
- developer L1（谓词真值表：slug 连字符/下划线换算、空 ticket_id 等）白盒随实现；
  本条锁 activity 级回执 + 磁盘终态。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t261004-25/sc_t26100425_test_face_gate.py（cwd=仓根）
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。实现落地前新契约子用例红属预期
（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"  # 红线桩：先钉再 import
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t26100425 import (  # noqa: E402
    check, engine_modules, env_fail, mk_lane, quarantine_root, archive_find,
    read_file, rmtree, settle, summary,
)

TID = "t261004-25"


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 settle 无 stdlib 替代子用例" % why)
    shared, aa = mods

    # ---- L1 本票自名测试文件过闸：原地在场 + 回执点名放行规则 ----
    print("\n== L1 本票测试面放行：文件原地 + 回执点名（named, never silent）")
    tmp, mainrepo, lane, fork = mk_lane("t26100425-l1-")
    probe = lane / "server" / "engine" / "tests" / "test_t261004_25_gate_probe.py"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("# lawful own-ticket test face\n", encoding="utf-8")
    qroot = quarantine_root(lane, shared)
    r1 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/", "server/engine/path_gates.py"])
    note1 = r1.note or ""
    check("L1a 合法测试文件不在隔离档（不被挪档）",
          not bool(archive_find(qroot, "test_t261004_25_gate_probe.py")),
          "root=%s" % qroot)
    check("L1b 文件原地在场（写集外但不消失＝ lawful path to land）",
          probe.is_file() and read_file(lane, "server/engine/tests/"
          "test_t261004_25_gate_probe.py") is not None, "gone")
    check("L1c 回执点名该文件被本票测试面规则放行（可见，不静默）",
          "test_t261004_25_gate_probe.py" in note1, "note=%r" % note1[:300])
    rmtree(tmp)

    # ---- L2 混合批次：真越权件照旧处置，窄缝不失效 ----
    print("\n== L2 混合批次：非测试面越权件照旧挪档点名")
    tmp, mainrepo, lane, fork = mk_lane("t26100425-l2-")
    probe = lane / "server" / "engine" / "tests" / "test_t261004_25_gate_probe.py"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("# lawful\n", encoding="utf-8")
    rogue = lane / "server" / "engine" / "rogue_helper.py"
    rogue.write_text("not a test, not in set\n", encoding="utf-8")
    qroot = quarantine_root(lane, shared)
    r2 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/"])
    note2 = r2.note or ""
    check("L2a 越权件已挪档（离场）", not rogue.exists(), "still there")
    check("L2b 越权件留档在隔离区且回执点名", bool(archive_find(qroot, "rogue_helper.py"))
          and "rogue_helper.py" in note2, "note=%r" % note2[:300])
    check("L2c 同批次本票测试文件仍原地在场（放行与处置互不误伤）", probe.is_file(),
          "probe gone")
    rmtree(tmp)

    # ---- L3 边界 fail-closed：本票命名但测试面之外 → 不放行 ----
    print("\n== L3 测试面之外的同名 test_ 文件不放行")
    tmp, mainrepo, lane, fork = mk_lane("t26100425-l3-")
    outside = lane / "server" / "engine" / "test_t261004_25_outside_probe.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("smuggle attempt\n", encoding="utf-8")
    qroot = quarantine_root(lane, shared)
    r3 = settle(shared, aa, lane, TID, "implement", 1, fork,
                write_set=["docs/"])
    note3 = r3.note or ""
    check("L3a 测试面外的本票命名件被处置（离场）", not outside.exists(),
          "still there")
    check("L3b 处置留档且回执点名", bool(archive_find(qroot, "test_t261004_25_outside_probe.py"))
          and "test_t261004_25_outside_probe.py" in note3, "note=%r" % note3[:300])
    rmtree(tmp)

    sys.exit(summary())


if __name__ == "__main__":
    main()
