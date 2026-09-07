#!/usr/bin/env python3
"""ui-evidence-failure-retention.py —— UI 票失败尽力视图保留契约基线（t260901-02）。

用户可感知契约（黑盒，从 prepare_ui_evidence 公共入口进，不碰内部函数）：
  capture 两候选全败时，已拍 PNG 不再随失败蒸发：
    C1 归档成功路径：泳道 screenshots 里的 png 归档到主树 .suyou/evidence/<ticket>/  # naming-compat
       （同字节），并从泳道移出（机械闸 review_gate_verdict 数泳道 on-disk png，
       移出后 png_count 归 0 维持红灯——残缺视图不假通过）；回执 ok=False、
       shots 列出移出清单、detail 带人话标注。
    C2 归档失败路径：evidence 目标目录被同名普通文件占位 → 归档失败的图**留在
       泳道**（闸红 + 可人工捞回——归档失败还 unlink = 图彻底蒸发，正是本单根治
       的病）；detail 带归档失败说明；ok 仍 False。

安全红线（测试自己先遵守）：不碰 3099——本测试显式把 SANDBAR_CONSOLE_URL 钉死在
死端口 127.0.0.1:1，并在执行前硬断言该值不含 3099；候选脚本用临时假 capture.mjs
（process.exit(3)），零浏览器、零网络、零控制台 boot。

依赖与降级：import agent_activities 需 temporalio SDK——三态契约定稿 §7.3：
SDK 不可用 → ENV_FAIL 环境红（exit 2），绝不静默放行。跑法（manifest 侧自动选 venv python）：
  PY=server/dsh/temporal-poc/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" integration/baselines/ui-evidence-failure-retention.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POC = REPO / "server" / "dsh" / "temporal-poc"

pass_n = 0
fail_n = 0
env_fail_n = 0
failures = []


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  PASS %s" % label)
    else:
        fail_n += 1
        failures.append(label)
        print("  FAIL %s" % label)


try:
    import temporalio  # noqa: F401
except ImportError:
    print("ENV_FAIL: temporalio SDK unavailable (no server/dsh/temporal-poc/.venv, no "
          "system temporalio) -- known limitation, see integration/README.md")
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

sys.path.insert(0, str(POC))
import agent_activities  # noqa: E402
from shared import EVIDENCE_DIR, UI_EVIDENCE_DIR, UiEvidenceArgs  # noqa: E402

# 最小合法 PNG（1x1 像素），与 agent_activities._ui_capture_stub 同款，glob("*.png") 可命中
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c63000100000500010d0a2db4"
    "0000000049454e44ae426082")

TICKET = "t-integ-retention"
DEAD_URL = "http://127.0.0.1:1"


def make_env(ed):
    """显式钉死候选环境：单直连候选（假 capture.mjs 秒退 3）+ 死端口 + 临时归档目录。"""
    assert "3099" not in DEAD_URL, "红线自检：测试绝不指向 3099"
    os.environ["SANDBAR_CONSOLE_URL"] = DEAD_URL
    os.environ["SANDBAR_EVIDENCE_DIR"] = str(ed)


def clear_env():
    for k in ("SANDBAR_CONSOLE_URL", "SANDBAR_EVIDENCE_DIR"):
        os.environ.pop(k, None)


def make_fake_main_tree(td):
    """临时假主树：无 capture-lane.mjs（只剩直连候选），capture.mjs 是秒退脚本。"""
    t = td / "maintree"
    uc = t / "server" / "dsh" / "ui-check"
    uc.mkdir(parents=True, exist_ok=True)
    (uc / "capture.mjs").write_text("process.exit(3);\n", encoding="utf-8")
    return t


def seed_shots(wt, names):
    d = wt / UI_EVIDENCE_DIR
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(PNG_BYTES)
    return d


async def run_prepare(wt):
    return await agent_activities.prepare_ui_evidence(
        UiEvidenceArgs(ticket_id=TICKET, worktree=str(wt)))


saved_repo_root = agent_activities.REPO_ROOT
try:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)

        # ---------- C1 归档成功：移出泳道 + 主树同字节留存 + ok=False ----------
        ed1 = td / "ev1"
        ed1.mkdir()
        fake = make_fake_main_tree(td)
        agent_activities.REPO_ROOT = fake
        wt1 = td / "wt1"
        wt1.mkdir()
        shot_dir1 = seed_shots(wt1, ["console-default.png", "console-chat.png"])
        make_env(ed1)
        try:
            res = asyncio.run(run_prepare(wt1))
        finally:
            clear_env()
            agent_activities.REPO_ROOT = saved_repo_root
        ok(res.ok is False, "C1 capture 全败 → ok=False（不假通过）")
        ok("退出码 3" in (res.detail or ""), "C1 detail 带真实退因（候选秒退 3）")
        ok(sorted(res.shots or []) == ["console-chat.png", "console-default.png"],
           "C1 shots 列出移出清单：%s" % (res.shots,))
        ok("尽力视图 2 张已归档" in (res.detail or ""),
           "C1 detail 带尽力视图标注")
        left = sorted(p.name for p in shot_dir1.glob("*.png"))
        ok(left == [], "C1 归档成功的图已移出泳道（png_count 归 0，闸红灯）：%s" % left)
        ev = ed1 / TICKET
        same = all((ev / n).is_file() and (ev / n).read_bytes() == PNG_BYTES
                   for n in ("console-default.png", "console-chat.png"))
        ok(same, "C1 主树归档处两张同字节 png（worktree 拆后不蒸发）")

        # ---------- C2 归档失败：图留泳道（可人工捞回），不蒸发 ----------
        ed2 = td / "ev2"
        ed2.mkdir()
        (ed2 / TICKET).write_text("occupied")  # 同名普通文件占位 → 归档 mkdir 必败
        fake2 = make_fake_main_tree(td)
        agent_activities.REPO_ROOT = fake2
        wt2 = td / "wt2"
        wt2.mkdir()
        shot_dir2 = seed_shots(wt2, ["console-default.png", "console-chat.png"])
        make_env(ed2)
        try:
            res2 = asyncio.run(run_prepare(wt2))
        finally:
            clear_env()
            agent_activities.REPO_ROOT = saved_repo_root
        ok(res2.ok is False, "C2 ok 仍 False（归档失败不翻通过语义）")
        kept = sorted(p.name for p in shot_dir2.glob("*.png"))
        ok(kept == ["console-chat.png", "console-default.png"],
           "C2 归档失败的图留泳道可人工捞回（不蒸发）：%s" % kept)
        ok("归档失败" in (res2.detail or ""), "C2 detail 带归档失败人话说明")
        ok(not (res2.shots or []), "C2 shots 不含未移出的图（回执与盘上一致）")
finally:
    agent_activities.REPO_ROOT = saved_repo_root
    clear_env()

print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (pass_n, fail_n, env_fail_n))
if fail_n > 0:
    print("failed cases: %s" % " | ".join(failures))
    sys.exit(1)
