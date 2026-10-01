#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_executor_authority_gate.py —— 执行器授权闸的契约场景（L3 灰盒，integration 岗位资产）

intent（验证什么）
    把「执行器能做什么，只由项目级 grants 声明说了算」这组承诺锁在**引擎判定核**上：
    声明缺席或畸形时 fail-closed、已授予才放行、元权限与清单写面对执行器永久关闭、
    拒收必留审计。这是「执行器被唤醒后，零授予＝写不进去」这条用户可感知保证的机械面
    ——昨晚实案：某常驻会话在项目零授予下签了两笔 merge（KI-177 / t261001-20）。

high-level steps（如何到达并断言）
    S1–S6  以 IO 注入式纯核 judge_core 覆盖语义矩阵（自定义 load_face / audit_sink，
           零真 IO）：声明缺席、已授予、元权限反锁、畸形声明、夜间时间盒、未映射 op；
    S7–S8  起子进程把 SANDBAR_PROJECTS_DIR 指向临时项目根，用**真声明文件**跑 judge()
           （真 IO 端到端），并核对拒收落进真审计文件；
    S9     写面反锁：执行器通道写自己的声明一律拒收，宿主通道可写；
    末行 `SUMMARY pass=N fail=M env_fail=K na=J`；fail>0 → exit 1；环境缺件 → exit 2（不假绿）。

已知开口（**刻意不编码为本场景契约**）
    `ticket.py` 显式声明 caller_project 时身份来源落 arg/env，判定核按「零回归红线」
    不设闸——即「声明自己是谁」可绕过闸。真因、证据与修法见 t261001-20 票面与 KI-177；
    修法落地后本场景需补一条「执行器会话的写不因通道声明而免闸」的断言（届时改这张网的
    期望值必须走票，不得为了绿而放宽——见本仓「改共享守卫期望值＝自授权」先例）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE))

passed = failed = env_failed = na = 0


def ok(cond: bool, label: str, detail: str = "") -> bool:
    global passed, failed
    if cond:
        passed += 1
        print("  ok  %s" % label)
    else:
        failed += 1
        print("  FAIL %s %s" % (label, str(detail)[:300]))
    return bool(cond)


def env_fail(label: str, detail: str = "") -> None:
    global env_failed
    env_failed += 1
    print("  ENV_FAIL %s %s" % (label, str(detail)[:200]))


def info(label: str) -> None:
    print("  ..  %s" % label)


# ---------------------------------------------------------------- 引擎面导入
try:
    import executor_grants as eg  # type: ignore
except Exception as e:  # noqa: BLE001
    env_fail("import executor_grants", "%s: %s" % (type(e).__name__, e))
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (passed, failed, env_failed, na))
    raise SystemExit(2)

NOW = int(time.time() * 1000)
KEY = "demo"

# ---------------------------------------------------------------- 纯核矩阵（S1–S6）
info("S1–S6 纯核矩阵（judge_core，注入 load_face / audit_sink）")


def core(op, load, now=NOW, channel=eg.EXECUTOR_CHANNEL, sink=None, sink_box=None):
    """跑一次判定核；sink_box=列表时收集审计行，并记录 load_face 是否被调用。"""
    called = {"n": 0}

    def face(k):
        called["n"] += 1
        return load(k) if callable(load) else load

    rows = sink_box if sink_box is not None else []
    r = eg.judge_core(channel, op, KEY, face, now, sink if sink is not None else (lambda k, row: rows.append(row)))
    return r, rows, called


# S1 声明缺席 ⇒ 拒收（fail-closed），回执点名声明文件与"零授予"口径，且落一条拒收审计
absent = {"ok": False, "kind": "absent", "declared": False,
          "reason": "项目 %s 尚无执行器授权声明（缺 /tmp/x/executor-grants.json）——零授予=只读与问" % KEY,
          "file": "/tmp/x/executor-grants.json"}
box: list = []
r1, rows1, _ = core("sign", absent, sink_box=box)
ok(r1.get("allowed") is False, "S1 声明缺席 ⇒ 拒收（fail-closed）", r1)
ok("executor-grants.json" in str(r1.get("why") or ""), "S1 拒收文案点名声明文件路径", r1.get("why"))
ok(len(box) == 1 and box[0].get("action") == "refuse", "S1 拒收落一条审计行", box)

# S2 已授予 ⇒ 放行，且标记为"受闸且放行"（enforced），溯源在场
granted = {"ok": True, "declared": True, "file": "/tmp/x/executor-grants.json",
           "grants": {"sign": True}, "night_tier": None}
r2, _, _ = core("sign", granted)
ok(r2.get("allowed") is True, "S2 已授予 sign ⇒ 放行", r2)
ok(r2.get("enforced") is True, "S2 放行带 enforced 标记（受闸路径）", r2)
ok(bool(r2.get("provenance")), "S2 放行带溯源（哪个键定了值）", r2.get("provenance"))

# S3 元权限反锁：改/扩授予清单永远是宿主特权，全授也不解锁，且**先于**声明读取
r3, _, called3 = core(eg.META_OP, granted)
ok(r3.get("allowed") is False, "S3 元权限（manage-grants）对执行器永久拒收", r3)
ok(called3["n"] == 0, "S3 反锁先于声明读取（声明缺席/畸形也锁得住）", called3)

# S4 畸形/不可判定声明 ⇒ 拒收（fail-closed，绝不静默放行）
for kind, label in (("malformed", "S4 畸形声明"), ("unreadable", "S4 不可读声明")):
    bad = {"ok": False, "kind": kind, "declared": True,
           "reason": "执行器授权声明不可判定（%s）——fail-closed 拒收，绝不静默放行" % kind,
           "file": "/tmp/x/executor-grants.json"}
    r, _, _ = core("sign", bad)
    ok(r.get("allowed") is False and "fail-closed" in str(r.get("why") or ""), label, r)

# S5 夜间时间盒：窗口内全权、过期回落声明值（该键未授予 ⇒ 拒收）
win = {"ok": True, "declared": True, "file": "/tmp/x/executor-grants.json",
       "grants": {"sign": False}, "night_tier": {"enabled": True, "until": NOW + 3600_000, "note": "box"}}
r5a, _, _ = core("sign", win)
ok(r5a.get("allowed") is True, "S5 夜间时间盒窗口内 ⇒ 放行", r5a)
exp = {"ok": True, "declared": True, "file": "/tmp/x/executor-grants.json",
       "grants": {"sign": False}, "night_tier": {"enabled": True, "until": NOW - 1000, "note": "expired"}}
r5b, _, _ = core("sign", exp)
ok(r5b.get("allowed") is False, "S5 时间盒过期 ⇒ 回落声明（未授予=拒收）", r5b)

# S6 未映射的引擎写 op ⇒ 拒收（固定操作面外没有"执行器可做"这回事）
r6, _, _ = core("frobnicate-everything", granted)
ok(r6.get("allowed") is False, "S6 固定面外的 op ⇒ 拒收（fail-closed）", r6)

# S6b 引擎写 op 名 → 授予面名的映射必须落在 GRANT_OPS 内（防新增 op 静默落到"可授予"）
mapping = getattr(eg, "ENGINE_OP_TO_GRANT", {}) or {}
ok(all(v in eg.GRANT_OPS for v in mapping.values()),
   "S6b 引擎 op → 授予面映射值全部 ∈ GRANT_OPS", mapping)
ok("manage-grants" not in mapping.values(),
   "S6b 元权限不出现在映射面（不可被授予面放行）", mapping)

# S10 零回归红线：非执行器通道（泳道 agent = env 注入身份）不受闸——今天的行为一字不变
#     （这条是**边界子用例**：变异自证实测，缺了它，把"只对执行器通道设闸"整条拆掉本场景照样全绿。
#      t261001-20 修"声明身份绕过"时，本子用例锁的这条红线必须原样保留。）
for ch, label in (("env", "S10 泳道 agent 通道（env）不受闸（零回归红线）"),
                  ("none", "S10 未声明身份通道不受闸")):
    r, _, _ = core("sign", absent, channel=ch)
    ok(r.get("allowed") is True and not r.get("enforced"), label, r)

# ---------------------------------------------------------------- 真 IO 端到端（S7–S8）
info("S7–S9 真 IO：临时 SANDBAR_PROJECTS_DIR + 真声明文件 + 真审计文件")
tmp = tempfile.mkdtemp(prefix="exec-grants-")
root = os.path.join(tmp, "projects")
os.makedirs(os.path.join(root, KEY), exist_ok=True)
env = dict(os.environ, SANDBAR_PROJECTS_DIR=root)
probe = (
    "import json,sys;sys.path.insert(0, %r);import executor_grants as eg;"
    "print(json.dumps(eg.judge({'channel_src':'cwd'},'sign',%r)))" % (str(ENGINE), KEY)
)
decl = os.path.join(root, KEY, "executor-grants.json")


def run_judge() -> tuple:
    p = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return None, (p.stdout or "") + (p.stderr or "")
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]), ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, p.stdout[:200])


# S7a 真文件：未授予 ⇒ 拒收；S7b 真文件：授予 ⇒ 放行
with open(decl, "w", encoding="utf-8") as f:
    json.dump({"version": 1, "grants": {"sign": False}, "updated_by": "scenario", "updated_at": NOW}, f)
verdict_a, err_a = run_judge()
ok(verdict_a is not None and verdict_a.get("allowed") is False, "S7 真文件未授予 ⇒ 拒收", err_a or verdict_a)

with open(decl, "w", encoding="utf-8") as f:
    json.dump({"version": 1, "grants": {"sign": True}, "updated_by": "scenario", "updated_at": NOW}, f)
verdict_b, err_b = run_judge()
ok(verdict_b is not None and verdict_b.get("allowed") is True, "S7 真文件已授予 ⇒ 放行", err_b or verdict_b)

# S8 拒收落真审计文件（append-only；写失败不掩盖判定，但正常路径必须留痕）
with open(decl, "w", encoding="utf-8") as f:
    json.dump({"version": 1, "grants": {}, "updated_by": "scenario", "updated_at": NOW}, f)
run_judge()
audit = os.path.join(root, KEY, "executor-grants-audit.jsonl")
row_ok = False
if os.path.exists(audit):
    rows = [json.loads(x) for x in open(audit, encoding="utf-8") if x.strip()]
    row_ok = any(r.get("action") == "refuse" and r.get("op") == "sign" for r in rows)
ok(row_ok, "S8 拒收落真审计文件（executor-grants-audit.jsonl）", audit)

# S9 写面反锁：执行器通道写声明 ⇒ 拒收；宿主通道 ⇒ 可写
probe_save = (
    "import json,sys;sys.path.insert(0, %r);import executor_grants as eg;"
    "print(json.dumps(eg.save_declaration(%r, {'sign': True}, 'who', %d, caller_channel=%r)))"
)
for ch, expect_saved, label in (("cwd", False, "S9 执行器通道写自己的授予清单 ⇒ 拒收"),
                                ("host", True, "S9 宿主通道写授予清单 ⇒ 放行")):
    p = subprocess.run([sys.executable, "-c", probe_save % (str(ENGINE), KEY, NOW, ch)],
                       capture_output=True, text=True, env=env)
    got = None
    if p.returncode == 0:
        try:
            got = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            got = None
    ok(got is not None and bool(got.get("saved")) is expect_saved, label,
       (p.stdout or "") + (p.stderr or "") if got is None else got)

shutil.rmtree(tmp, ignore_errors=True)  # 临时项目根回收（L8 reclaim）
print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (passed, failed, env_failed, na))
raise SystemExit(1 if (failed > 0 or (passed + failed == 0 and na > 0)) else (2 if env_failed and passed == 0 else 0))
