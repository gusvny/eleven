#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-25 场景③：合并闸本票测试面放行——verify_lane code 道不再误卡合法交付
（灰盒 L3，真 git 仓 + verify_lane 公开入口 run() 直调，零 docker）。

intent（实案=t261004-19：合法单测已 commit 进泳道分支，merge_check 判「越界写」
全场绿唯独此处红，票堵死在最后一道闸）：
- **已 commit 的本票自名测试文件过写集白名单**：diff base...HEAD 里命中本票测试面
  谓词的路径不判越界，且检查项回执**点名**这条规则放行了它（named, never silent）；
- **真越权件照旧红且点名**：同 diff 里的非测试面越界文件仍判「越界写」并点名——
  窄缝不等于闸失效；
- **缺票 id = 旧行为逐字保留**：不带 ticket_id 时同 diff 照旧判红（fail-closed
  零放宽——老泳道未带新参数的行为不漂移）。

与相邻场景 intent 分界：
- sc_t26100425_test_face_gate：彼锁段路径闸（settle 时刻脏清单），本条锁合并闸
  （verify_lane diff 面）；同一条谓词的两个执法点；
- developer L1（_in_write_set / 谓词真值表、两判据源 write_set>write_allow 的
  分支矩阵）白盒随实现，本条锁公开入口 run() 的绿/红/点名三面。

跑法：python3 -B integration/t261004-25/sc_t26100425_mergecheck_carveout.py（cwd=仓根）
纯 stdlib：tmp 自建仓（带最小 verify.yaml）+ 真 git commit + 直调 verify_lane.run。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。实现落地前红属预期（TDD 信号）。
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t26100425 import (  # noqa: E402
    BASE_WITH_VERIFY, check, env_fail, git, git_ok, head_sha, mk_lane, rmtree,
    run_verify_code, summary, tmpdir,
)

TID = "t261004-25"
PROBE_REL = "server/engine/tests/test_t261004_25_merge_probe.py"
ROGUE_REL = "server/engine/rogue_helper.py"
WRITE_SET = ["docs/", "server/engine/path_gates.py"]


def commit_file(lane, rel, body, msg):
    p = Path(lane) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    git(["add", rel], lane)
    git(["commit", "-qm", msg], lane)


def main():
    tmp, mainrepo, lane, fork = mk_lane("t26100425-m1-", base=BASE_WITH_VERIFY)

    # ---- L1 合法本票测试文件：过白名单且回执点名 ----
    print("\n== L1 本票测试面 commit 过白名单（named, never silent）")
    commit_file(lane, PROBE_REL, "# lawful own-ticket test\n", "add own test")
    r1 = run_verify_code({"path": str(lane), "base": fork,
                          "write_set": WRITE_SET, "ticket_id": TID,
                          "require_base": True})
    ws1 = next(c for c in r1["checks"] if c["check"] == "写集白名单")
    check("L1a 白名单绿（合法交付不再卡死合并闸）", ws1["level"] == "green",
          "level=%s items=%r" % (ws1["level"], ws1["items"][:2]))
    check("L1b 回执点名放行文件与规则", PROBE_REL in str(ws1), "checks=%r" % ws1)

    # ---- L2 真越权件同 diff 照旧红且点名 ----
    print("\n== L2 混合 diff：真越界件照旧红")
    commit_file(lane, ROGUE_REL, "not a test\n", "add rogue")
    r2 = run_verify_code({"path": str(lane), "base": fork,
                          "write_set": WRITE_SET, "ticket_id": TID,
                          "require_base": True})
    ws2 = next(c for c in r2["checks"] if c["check"] == "写集白名单")
    flat2 = str(ws2)
    check("L2a 白名单红（窄缝不放走真越界）", ws2["level"] == "red",
          "level=%s" % ws2["level"])
    check("L2b 越界点名 rogue_helper.py 且不牵连合法测试文件名",
          ROGUE_REL in flat2, "flat=%r" % flat2[:300])
    check("L2c 汇总绿/红判定诚实（red_count>0）", r2["red_count"] > 0,
          "red_count=%s" % r2["red_count"])

    # ---- L3 缺票 id = 旧行为（同 diff 判红） ----
    print("\n== L3 缺 ticket_id：旧行为逐字保留（fail-closed 零放宽）")
    r3 = run_verify_code({"path": str(lane), "base": fork,
                          "write_set": WRITE_SET, "require_base": True})
    ws3 = next(c for c in r3["checks"] if c["check"] == "写集白名单")
    flat3 = str(ws3)
    check("L3a 无票 id 时本票测试文件照旧判红（旧语义不漂移）",
          ws3["level"] == "red" and PROBE_REL in flat3,
          "level=%s flat=%r" % (ws3["level"], flat3[:300]))
    rmtree(tmp)

    sys.exit(summary())


if __name__ == "__main__":
    main()
