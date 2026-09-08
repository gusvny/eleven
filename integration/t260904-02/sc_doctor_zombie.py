#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-02 场景③：doctor 引擎僵尸探测红绿自证（epic 验收 3；ro 只读池）。

intent（守护的用户可感知行为）：
- `sandbar doctor` 消费 SANDBAR_ZOMBIE_CENSUS 注入的进程 census（fixture 档零真扫）：
  · 异仓引擎形态（cwd 落在「含 server/engine 标记」且引擎根 ≠ 当前引擎根，
    即 260904 实案=headless cwd 指向冻结仓）→ doctor exit1 + 红行点名 pid 与异仓路径；
  · 干净 census（同仓 cwd + 无关进程 + 空表）→ exit0、兼容矩阵恰 5 行（绿一行
    append 一行）且新行含 zombie 语义探针名、重复 doctor 幂等（行集合不变）；
  · 坏 JSON census → 显式红不假绿（消费外部输入的畸形三态之一）；
- 文案自辨（review_plan C2）：僵尸面输出自带 --live 指引（缺省=sample 档，防把
  「跑过 doctor 绿」误读为「无僵尸」）；完成语文案不写死「四面」（数字随探针数漂移）。

census 契约：JSON {"processes": [{"pid": int, "command": str, "cwd": str}, ...]}。

红线：零端口依赖（fixture 档）；HOME 桩隔离，绝不写真 ~/.sandbar。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_gate import (REPO, Fail, cleanup, make_temp_home,  # noqa: E402
                      read_rows_compat, require_sandbar_entry, run_cli)

FAKE_ZOMBIE_PID = 410242  # 假 pid（fixture 档零真扫，不撞真进程面）
SAME_OK_PID = 410243


def write_census(path, processes):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"processes": processes}, f, ensure_ascii=False)


def doctor_with(entry, env, census_path):
    env2 = dict(env)
    env2["SANDBAR_ZOMBIE_CENSUS"] = census_path
    return run_cli(entry, ["doctor"], env2, timeout=120)


def matrix_path(home):
    return os.path.join(home, ".sandbar", "compat-matrix.json")


def main():
    fail = Fail("t260904-02 ③doctor 引擎僵尸探测红绿自证")
    entry = require_sandbar_entry(fail)
    tmp, env = make_temp_home()
    try:
        poc_marker = os.path.join("server", "engine")
        fake_foreign_root = os.path.join(tmp, "fake-frozen-engine")  # 模拟冻结仓
        # ---------- ① 红腿：注入异仓引擎形态 census ----------
        bad = os.path.join(tmp, "census_bad.json")
        write_census(bad, [
            {"pid": FAKE_ZOMBIE_PID, "command": "node server/plugins/temporal-tools/node.ts",
             "cwd": os.path.join(fake_foreign_root, poc_marker)},
            {"pid": SAME_OK_PID, "command": "Python worker.py",
             "cwd": os.path.join(REPO, poc_marker)},  # 同仓引擎进程=不红
        ])
        rc, out = doctor_with(entry, env, bad)
        fail.check(rc == 1, "异仓引擎 census → doctor exit1（实得 rc=%s）" % rc)
        fail.check(str(FAKE_ZOMBIE_PID) in out,
                   "红行点名异仓 pid %d（输出=%s）" % (FAKE_ZOMBIE_PID, out.strip()[:160]))
        fail.check(("异仓" in out) or (fake_foreign_root in out),
                   "红行带异仓语义/对方仓路径（可定位，非一句「有僵尸」）")
        fail.check(str(SAME_OK_PID) not in out,
                   "同仓引擎进程不误报（pid %d 不在红行）" % SAME_OK_PID)

        # ---------- ② 绿腿：干净 census → exit0 + 矩阵 5 行 + 幂等 ----------
        good = os.path.join(tmp, "census_good.json")
        write_census(good, [
            {"pid": 410250, "command": "node", "cwd": os.path.join(REPO, poc_marker)},
            {"pid": 410251, "command": "Python", "cwd": REPO},
            {"pid": 410252, "command": "Code Helper", "cwd": "/Users"},
        ])
        rc2, out2 = doctor_with(entry, env, good)
        fail.check(rc2 == 0, "干净 census → doctor 零退出（rc=%s，尾部=%s）"
                   % (rc2, out2.strip()[-160:]))
        mpath = matrix_path(tmp)
        ok_rows, rows = read_rows_compat(mpath)
        fail.check(ok_rows and len(rows) == 5,
                   "兼容矩阵恰 5 行=四面+僵尸面（绿一行 append 一行，实得 %d 行）" % len(rows))
        if rows:
            names = " ".join(str(r.get("probe", "")) for r in rows if isinstance(r, dict))
            fail.check("zombie" in names.lower(),
                       "新探针行含 zombie 语义词（行 probe 名：%s）" % names)
        before = json.dumps(rows, sort_keys=True)
        rc2b, _ = doctor_with(entry, env, good)
        _, rows_b = read_rows_compat(mpath)
        fail.check(rc2b == 0 and json.dumps(rows_b, sort_keys=True) == before,
                   "重复 doctor 幂等：行集合不变（%d 行）" % len(rows_b))

        # ---------- ③ 畸形腿：坏 JSON census → 显式红不假绿 ----------
        malformed = os.path.join(tmp, "census_malformed.json")
        with open(malformed, "w", encoding="utf-8") as f:
            f.write("{not-json-at-all")
        rc3, out3 = doctor_with(entry, env, malformed)
        fail.check(rc3 != 0, "坏 JSON census 显式红（rc=%s）——畸形输入不静默绿" % rc3)

        # ---------- ④ 文案自辨腿（review C2） ----------
        rc4, out4 = doctor_with(entry, env, good)
        fail.check("--live" in out4,
                   "僵尸面输出自辨 sample 档并指 --live 真扫（防「跑过=无僵尸」误读）")
        fail.check("四面" not in out4,
                   "完成语文案不写死「四面」（数字随探针数漂移=文案撒谎面）")
    finally:
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
