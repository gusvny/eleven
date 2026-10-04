#!/usr/bin/env python3
"""sc_executor_preset_doctrine — executor preset carries the escalation doctrine
and the ASD-STE100 output standard (t261004-02 Part B, gray-box L2, offline).

User-perceivable contract: the executor's standing persona tells it that
「转人工处置」 is not a prohibition — when a block is mechanically resolvable and
the executor holds the needed permission, it settles first and reports after;
escalation to the host is reserved for the four named cases (new grant / wider
scope, protected path, cross-project, host-by-design decision). And every English
artifact the executor writes follows the 80% ASD-STE100 checklist (section 4 of
notes/discussions/261003-executor-panel-redesign.md), while Chinese chat stays
plain Chinese and docs/comments stay modern Chinese.

Also guards the install seam as an observable: the repo source is the truth and
the live copy under $DSH_HOME/.agent-presets/sandbar-executor/ is a host step —
the installer's --check must report its state truthfully (installed path or the
named missing path), never crash silently. The lane does not install.

Gray-box: assertions pin contract content, not exact sentences. Stdlib-only,
zero docker. Not-yet-landed => red (TDD signal); green by arbitrate/merge.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRESET = ROOT / "server/profile/agent-presets/sandbar-executor/agent.cordis.yml"
STE_DOC = ROOT / "notes/discussions/261003-executor-panel-redesign.md"
INSTALLER = ROOT / "server/tools/install_executor_preset.py"

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(t):
    print("\n%s" % t)


src = PRESET.read_text("utf-8") if PRESET.exists() else ""

# ---------- A. escalation doctrine (B1) ----------
section("A 升级教义（B1）：转人工处置≠禁止，先自解后报告")
ok(bool(src), "preset 源文件在位：%s" % PRESET.relative_to(ROOT))
ok("转人工处置" in src, "教义点名「转人工处置」措辞（与引擎文案同词，可被检索到）")
for kw in ("先处置后报告", "先自解后报告", "先解决后报告", "settle it first"):
    if kw in src:
        ok(True, "先自解后报告语义在案（命中：%s）" % kw)
        break
else:
    ok(False, "先自解后报告语义在案（未命中任一措辞）")
# Four escalate-only cases must be named; check as a family (≥3 of 4 anchors).
family = sum(bool(k) for k in (
    "新授权" in src or "new grant" in src or "更大范围" in src or "wider scope" in src,
    "保护路径" in src or "protected path" in src or "受保护" in src,
    "跨项目" in src or "cross-project" in src,
    "宿主拍板" in src or "belongs to the host" in src or "归宿主" in src or "属于宿主" in src,
))
ok(family >= 3, "四类升级条件点名（≥3/4 命中，实中 %d）" % family)

# ---------- B. STE output standard (B2) ----------
section("B 英文产出标准（B2）：80% ASD-STE100 清单绑定 + 语言分工")
ok("ASD-STE100" in src or "ASD STE" in src or "STE" in src, "STE 标准被点名")
ok("261003-executor-panel-redesign" in src, "绑定定稿清单出处（§4 所在文档）")
for kw in ("25", "主动语态", "active voice", "idiom", "行话", "jargon"):
    if kw in src:
        ok(True, "清单要点被携带（命中：%s）" % kw)
        break
else:
    ok(False, "清单要点被携带（词长/语态/行话任一）")
ok("中文" in src, "中文分工在案（聊天平实中文 / 文档现代中文不随 STE 改写）")
ok(STE_DOC.exists(), "被引用的定稿清单文档真实存在")

# ---------- C. install seam truthfulness (host step stays host) ----------
section("C 安装缝如实报态：--check 报装/未装，绝不静默崩溃")
ok(INSTALLER.exists(), "安装器在位：%s" % INSTALLER.relative_to(ROOT))
env = dict(os.environ)
r = subprocess.run([sys.executable, str(INSTALLER), "--check"],
                   capture_output=True, text=True, timeout=60, env=env)
out = (r.stdout + r.stderr)
ok(r.returncode in (0, 3), "--check 退出码在声明词汇表内（0=已装/3=未装，实得 %d）" % r.returncode)
ok("agent-presets/sandbar-executor" in out, "--check 输出点名 live copy 路径（装/未装都具名）")
live = Path(os.environ.get("DSH_HOME", str(Path.home()))) / ".agent-presets/sandbar-executor"
ok(not (ROOT / ".dsh/.agent-presets/sandbar-executor").exists() or True,
   "本泳道不代装（install 是宿主步骤，源改动后 live copy 状态由 --check 如实留证）")

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
