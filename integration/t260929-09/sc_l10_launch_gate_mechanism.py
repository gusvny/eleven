#!/usr/bin/env python3
"""sc_l10_launch_gate_mechanism.py — L10 控制台启动面闸的机制化守卫（t260929-09，灰盒 L3）。

背景（260929 宿主实报「浏览器不停跳新窗口」）：真凶
server/plugins/watchdog/bench/host-prompt-bench.mjs 用 **变量二进制**起真 dsh web
控制台、argv 带 --profile 且没带 --no-open，而旧 L10（integration/lint_tests.py
lint_console_no_open）只认字面量 `spawn('dsh', …)` ——闸报「5 处全合规」时真凶是
第 6 处、根本没被扫到（当日基线实测更糟：字面量闸数出 **0 处**启动点，绿灯纯属盲区）。
本场景把闸的**机制契约**钉死，防同类盲区回潮：

  A 机制红面：变量二进制/argv 带 --profile/dsh 命名表达式/字面量路径四族
    「缺 --no-open」样本必须被识别（A1=事故同形状字面级回归，事故回归纪律）；
  B 绿面/防误报：带 --no-open、--version 探针、L10-allow 注记（同行＋前注释行
    两形态，review gen0 意见②）、非 dsh 二进制、无启动调用文本=零误报；
  C 畸形输入不炸（未闭合括号/CRLF/嵌套引号/空文本——外部输入三态纪律）；
  D 现树闸全绿：`python3 integration/lint_tests.py` exit 0 且 0 error / 0 warn
    （工单验收口径原话）；与 A/B 合起来防「降回字面量闸也绿」的假阴：
    机制样本红 + 现树绿 + 真实启动面在场（E/F）三层互证；
  E .sh 启动面合同：六个已知 automation 调用面逐个在场且带 --no-open
    （防「静默不扫 .sh」与「vacuous green」两个失败面——票 scope 2a）；
    两个人工豁免面（start-console.sh / stage_console.sh 默认开浏览器）
    必须在 lint_tests.py 里以具名理由声明（scope 2b，沉默不是豁免）；
  F 事故现场收据锚：bench 启动行今日仍带 --no-open（ebb52c9 直修不回潮；
    真机 console.log 证据归验收报告，不在本条重复）。

被测契约=闸对「启动点是否带 --no-open」的判定行为，锚公开承诺（工单 scope 1–3）
不锚内部结构；助手函数名 `_l10_launch_sites` 是 developer 方案（t260929-09
create_plan Step 1）声明的测试缝，缺席=TDD 红点名后立即收口（缺失状态下绿面子用例
会假绿，绝不带着假缝跑完）。

Hermetic 纯文本秒级、零 docker 零端口零 3099。**implement 落地前红属预期
（TDD 信号），arbitrate/merge 期必须绿。**

intent 分工（防重复）：developer L1 守助手纯函数真值表；本条守闸机制契约
（事故形状回归＋现树绿＋.sh 面合同）——t260907-10 sc_engine_layout §D 的
反向样本是**布局扫描器**的自证，与本条（--no-open 闸）intent 不同面，不重复。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260907-04"))  # 共享 helper：lib_naming.Rec
import lib_naming  # noqa: E402

BENCH = os.path.join(REPO, "server/plugins/watchdog/bench/host-prompt-bench.mjs")
LINT = os.path.join(REPO, "integration/lint_tests.py")

# 票 scope 2a 点名的 automation 调用面（闸必须看得到它们且它们带 --no-open 证据）。
# capture-lane 实测（260929 收票时）：server/ui-check/capture-lane.mjs 自身 **不 spawn
# dsh web**（台来自 docker --stage-json；--boot-local 是人工显式通路，:176「截图台不
# spawn」）——票面「capture-lane passes --no-open」的兑现形态=无启动面可违，E 段按
# 「无 spawn 或带旗」双臂断言，谁往里加裸 spawn 都会被 L10 主扫描抓（.mjs 在扫面内）。
SH_INVOKERS = [
    "integration/t260904-17/lib_fix17.mjs",
    "integration/t260905-07/lib_t260905.mjs",
    "integration/t260916-26/lib_t260916_26_bench.mjs",
    "integration/t260916-25/sc_stage_console_guardrails.mjs",
    "integration/tests/test_start_console_bits.py",
]
SH_NO_SPAWN_OK = ["server/ui-check/capture-lane.mjs"]
# 票 scope 2b 的两个人工豁免面（具名理由必须出现在闸里，沉默不是豁免）
HUMAN_LAUNCHERS = ("start-console.sh", "stage_console.sh")

r = lib_naming.Rec()

# A 段样本行内带 L10-allow 注记只为防「本场景文件被仓扫自咬」；喂给被测机制前剥掉
# 注记，还原无注记原文（红面样本必须是真·无豁免形态，否则 helper 判 exempt=假阴）。
_ALLOW_MARK = "L10-allow: 反向样本字面量"


def _strip_allow(s):
    """剥掉防自咬注记（py `#` 与 js `//` 两前缀形），还原无豁免原文。"""
    return s.replace("# " + _ALLOW_MARK, "").replace("// " + _ALLOW_MARK, "")


def _flagged(text):
    """喂文本给被测机制，返回缺旗启动点的行号集合。

    兼容两种已声明/已落地缝形（灰盒绑定浅，重构不掉链）：
    - l10_launch_sites(text) → [(lineno, kind, why)]，kind=='bad' 即缺旗（现行落地形）；
    - _l10_launch_sites(text) → [(lineno, argv_text, why)]，argv 无 --no-open 即缺旗（方案声明形）。
    """
    sites = lint_tests.l10_launch_sites(text) if hasattr(lint_tests, "l10_launch_sites") \
        else lint_tests._l10_launch_sites(text)
    bad = set()
    for item in sites:
        line, second = item[0], item[1]
        if isinstance(second, str) and second in ("bad", "compliant", "exempt", "probe"):
            if second == "bad":
                bad.add(line)
        elif "--no-open" not in second:                # (lineno, argv_text, why) 形
            bad.add(line)
    return bad


# ── 被测缝装载（缺失=TDD 红，立即收口） ─────────────────────────────────
try:
    import lint_tests  # noqa: E402
    _has_helper = (callable(getattr(lint_tests, "l10_launch_sites", None))
                   or callable(getattr(lint_tests, "_l10_launch_sites", None)))
except Exception as _e:                                # noqa: BLE001 —— 装载失败=点名
    lint_tests = None
    _has_helper = False
if not _has_helper:
    r.check(False, "A0 机制化助手 lint_tests._l10_launch_sites 未落地 "
                   "(TDD 红属预期；缺失状态下绿面子用例会假绿，本条到此收口)")
    r.finish()

# ── 样本集（全部为字面量反向样本，行内 L10-allow 注记防自咬） ──────────────
S_VAR_NOFLAG = "child = spawn(dshCmd, ['--profile', 'sandbar-bench', '--port', '53340'], {opts})  # L10-allow: 反向样本字面量（260929 事故同形状）"
S_VAR_FLAG = "child = spawn(dshCmd, ['--profile', 'sandbar-bench', '--no-open'], {opts})  # L10-allow: 反向样本字面量"
S_LIT_NOFLAG = "spawnSync('/opt/homebrew/bin/dsh', ['--profile', 'x', '--port', '1'])  # L10-allow: 反向样本字面量"
S_NAMED_NOFLAG = "const p = spawn(binDsh, ['web', '--port', '1'], {opts})  // L10-allow: 反向样本字面量（dsh 命名变量无 --profile）"
S_PATHCONCAT_NOFLAG = "spawn(root + '/bin/dsh', ['web', '--port', '1'])  // L10-allow: 反向样本字面量（bin/dsh 路径拼接）"
S_VERSION = "spawnSync('dsh', ['--version'], {encoding: 'utf8'})  // L10-allow: 反向样本字面量（版本探针不启台）"
S_NONDSH = "spawn('docker', ['logs', '-f', 'sandbar-test-integ'], {opts})  // L10-allow: 反向样本字面量（非 dsh 二进制）"
S_PREV_COMMENT = ("// L10-allow: 前注释行豁免形态（review gen0 意见②）\n"
                  "spawn(dshBin, ['web', '--port', '2'])")  # L10-allow: 反向样本字面量

print("== A 机制红面（缺 --no-open 必须被识别）")
r.check(bool(_flagged(_strip_allow(S_VAR_NOFLAG))),
        "A1 变量二进制+argv --profile 缺旗被识别（260929 事故同形状，字面级回归）")
r.check(bool(_flagged(_strip_allow(S_LIT_NOFLAG))),
        "A2 字面量 dsh 路径（含 homebrew 前缀）缺旗被识别（旧行为保持）")
r.check(bool(_flagged(_strip_allow(S_NAMED_NOFLAG))),
        "A3 dsh 命名变量（无 --profile argv）缺旗被识别")
r.check(bool(_flagged(_strip_allow(S_PATHCONCAT_NOFLAG))),
        "A4 bin/dsh 路径拼接表达式缺旗被识别")

print("== B 绿面（合规/豁免/非 dsh=零误报）")
r.check(not _flagged(S_VAR_FLAG),
        "B1 同形状带 --no-open 不被 flag")
r.check(not _flagged(S_VERSION),
        "B2 --version 探针不被 flag（不启台）")
r.check(not _flagged(S_PREV_COMMENT),
        "B3 L10-allow 前注释行豁免形态生效（沉默≠豁免，但具名注记=豁免）")
r.check(not _flagged(S_NONDSH),
        "B4 非 dsh 二进制（无 --profile argv）不被 flag（防误报回潮）")
r.check(not _flagged("const x = 1\nconst y = 2"),
        "B5 无启动调用文本=零启动点（扫得动空面）")

print("== C 畸形输入不炸（三态纪律： malformed 不异常、不假绿）")
for label, sample in (
        ("C1 未闭合 argv 括号", "spawn(dshCmd, ['--profile', 'x'"),  # L10-allow: 反向样本字面量
        ("C2 CRLF 文本", S_VAR_NOFLAG.replace("\n", "") + "\r\nspawn('dsh', ['--version'])"),
        ("C3 嵌套引号/括号", "spawn(fn('a['), ['--profile', \"it's [weird]\"], {})"),  # L10-allow: 反向样本字面量
        ("C4 空文本", "")):
    try:
        _flagged(sample)
        r.check(True, "%s 畸形样本不抛异常" % label)
    except Exception as e:                             # noqa: BLE001 —— 畸形输入抛异常=产品红
        r.check(False, "%s 畸形样本抛异常 %s: %s" % (label, type(e).__name__, e))

print("== D 现树闸全绿（工单验收口径原话：lint_tests.py 0 error / 0 warn）")
p = subprocess.run([sys.executable, LINT], capture_output=True, text=True,
                   timeout=300, cwd=REPO)
out = (p.stdout or "") + (p.stderr or "")
r.check(p.returncode == 0 and "0 error / 0 warn" in out,
        "D1 lint_tests.py exit 0 且 0 error / 0 warn（exit=%d, tail=%s）"
        % (p.returncode, out.strip().splitlines()[-1] if out.strip() else "<empty>"))
r.check("L10" in out, "D2 L10 检查在闸输出中在场（未被静默摘除）")

print("== E .sh 启动面合同（automation 必带旗 + 人工豁免具名）")
for rel in SH_INVOKERS:
    fp = os.path.join(REPO, rel)
    if not os.path.isfile(fp):
        r.check(False, "E 已知 automation 调用面缺席: %s" % rel)
        continue
    txt = open(fp, encoding="utf-8", errors="replace").read()
    r.check("--no-open" in txt,
            "E automation 调用面带 --no-open: %s" % rel)
for rel in SH_NO_SPAWN_OK:
    fp = os.path.join(REPO, rel)
    if not os.path.isfile(fp):
        r.check(False, "E 已知 automation 面缺席: %s" % rel)
        continue
    txt = open(fp, encoding="utf-8", errors="replace").read()
    r.check("--no-open" in txt or not re.search(
        r"\b(?:spawn|spawnSync|execFile|execFileSync)\s*\(\s*['\"][^'\"]*dsh", txt),
        "E automation 面无裸 dsh-web spawn（或带旗）: %s" % rel)
lint_src = open(LINT, encoding="utf-8", errors="replace").read()
for name in HUMAN_LAUNCHERS:
    r.check(name in lint_src,
            "E 人工启动面 %s 在闸里被点名（非静默跳过 .sh）" % name)
r.check(re.search(r"start-console\.sh[^#\n]*(人工|human|by design|默认开)|"
                  r"(人工|human|by design)[^#\n]*start-console\.sh", lint_src) is not None
        and re.search(r"stage_console\.sh[^#\n]*(人工|human|by design|默认)|"
                      r"(人工|human|by design)[^#\n]*stage_console\.sh", lint_src) is not None,
        "E 两个人工豁免面带具名理由（scope 2b：silence is not an exemption）")

print("== F 事故现场收据锚（ebb52c9 直修不回潮）")
if os.path.isfile(BENCH):
    bench = open(BENCH, encoding="utf-8", errors="replace").read()
    r.check("spawn(dshCmd, ['--profile', 'sandbar-bench', '--no-open']" in bench,
            "F1 bench 启动行仍带 --no-open（260929 直修收据）")
else:
    r.check(False, "F1 bench 文件缺席: server/plugins/watchdog/bench/host-prompt-bench.mjs")

r.finish()
