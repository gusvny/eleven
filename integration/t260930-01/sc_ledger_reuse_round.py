#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_ledger_reuse_round.py —— t260930-01 台账绿行复用的端到端行为（灰盒 L3）。

intent（用户可感知行为；真源=票面「同 commit 同环境指纹同宽的绿行可直接复用」）：
  在**一棵真 git 树**上跑真 `integration/run_scenarios.py`（在被验证树内的副本），
  锁复用的完整行为面：
    A. 首轮：账里没有同键绿行 → 实跑（规范行 PASS 在场）、汇总 `reused=0`、
       `SCENARIOS … reused=0` 尾注在场、报告 JSON 带 `reused=0` 与全名单键；
    B. 同 commit 第二轮：**复用** → 一声不跑（零散场景输出）、stdout 带
       `INTEG_REUSE 复用台账绿行 1 条…`、`reused==expected==1`、`ran=0`、rc=0 正常绿；
       且**不重盖章**（账行数不增：复用不得刷新时间戳）；
    C. 换 commit：同一棵树 detach 到父提交 → 判据第一键不等 → **零复用**（实跑）；
    D. kill switch：`SANDBAR_LEDGER_REUSE=0` → 零复用且 stderr 具名理由点名该 env；
    E. 脏树：sibling 未跟踪文件 → 零复用且 stderr 具名理由点名「脏」；
    F. 主账不可读（目录权限 000）→ 零复用且 stderr 具名理由（fail-closed，绝不静默）；
    G. **闸回执面**：真 verify_lane integ 道跑同树 → 全复用轮回执带
       `reuse.reused/all_reused`、`REUSE_FULL_ROUND` 行在场，且闸判**绿**
       （复用的完整性判据 `ran + reused == expected` 兑现）。

分层与 intent 分工（防重复，与既有资产不互替）：
  · 纯函数四键判据/畸形行容错/三态理由 → L1 `server/engine/tests/
    test_t260930_01_ledger_reuse.py`（白盒真值表），本场景不重测；
  · 执行器既有三态出口/清单完整性 → t260904-12 / t260910-13 电池（本场景只补
    ` reused=` 尾注在场这一 additive 形状，电池自身已加锁）；
  · 闸的台账采信（红名归属/基线免跑）→ t260922-12 家族；本场景只锁**复用面回执**。

安全红线：真 git 树由 `git worktree add --detach` 落本场景私有临时目录（终态在
finally + atexit 双路回收并 `git worktree prune`——本仓 main 树的 worktree 注册表
不得留痕）；被验证树内只放**未跟踪**的副本与夹具（`git status --porcelain` 里
untracked 不进脏判据，故 A/B 两轮真干净）；零 docker、零 Temporal、零控制台
（永不接触 3099）；账目录由 `SANDBAR_SCENARIO_LEDGER_DIR` 指向临时目录（真账零写入）。
三态：git 缺失=ENV_FAIL exit 2（本场景的判据全是 git 面）；断言不符=FAIL exit 1。
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import (  # noqa: E402
    clean_narrowing_env, no_narrowing_env, owned_env_note)
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t260930-01-ledger-reuse-round"
SLUG = "t260930-01-ledger-reuse-fixture"

_TMP = None
_MAIN = None
_WT = None
_RECLAIMED = False

# 断言助手走共享单点（t261002-14 收敛，原局部逐字拷贝已删；措辞逐字保留：
# detail 截断 600、flush=True、SUMMARY 带 na 计数、全 N/A=红）。
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
na = _ck.na


def env_fail(reason):
    _ck.env_fail(NAME, reason)


def finish():
    _ck.finish(NAME)


# ---------------------------------------------------------------- 夹具与回收

def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd or _MAIN),
                          capture_output=True, text=True, timeout=120)


def _cleanup():
    """终态回收（幂等；正常/异常/信号路径都到）：注销 worktree + 删临时目录。

    `git worktree prune` 是兜底：即便 remove 失败，注册表里的死条目也不会赖在
    本仓（清扫器与 on-duty 巡检盯着「worktree list 零残留」这条判据）。"""
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    try:
        if _WT is not None and _MAIN is not None and Path(str(_WT)).exists():
            _git("worktree", "remove", "--force", str(_WT))
        if _MAIN is not None:
            _git("worktree", "prune")
    except Exception:          # noqa: BLE001 —— 回收面不抛（残留交清扫器）
        pass
    try:
        if _TMP is not None:
            shutil.rmtree(str(_TMP), ignore_errors=True)
    except Exception:          # noqa: BLE001
        pass


atexit.register(_cleanup)


def _fixture_script(marker: Path, log: Path) -> str:
    """夹具场景正文：写标记 + 打**真形状**规范行（`{` 开头，与执行器自产同族）。

    名字**烘进夹具脚本**（`SANDBAR_FIXTURE_SCENARIO_NAME` 可覆盖，缺省=注册名）：
    台账行落的是**子用例名**，而复用的第四键比对的是**注册表场景名**，两者必须逐字
    相等，否则账里的绿行永远命不中（本场景第一版就是这么假红的）。烘进脚本而不只靠
    env：闸侧跑子进程时用的 env 不一定带着本场景注入的键，夹具缺键即炸=红得莫名其妙。
    """
    return (
        "import json, os, pathlib\n"
        "NAME = os.environ.get('SANDBAR_FIXTURE_SCENARIO_NAME') or %r\n"
        "pathlib.Path(%r).write_text('ran\\n')\n"
        "pathlib.Path(%r).open('a').write('ran\\n')\n"
        "print(json.dumps({'name': NAME,\n"
        "                  'suite': 'main', 'status': 'pass', 'cause': None,\n"
        "                  'reason': None, 'evidence': 'fixture', 'dur_s': 0.01,\n"
        "                  'started': '2026-09-30T00:00:00+00:00', 'git_sha': '',\n"
        "                  'attempt': 1}, ensure_ascii=False))\n"
        % (SLUG, str(marker), str(log)))


def _build_tree(tmp: Path):
    """造一棵**真 git 树**（两个**内容相同、提交不同**的提交）+ 树内执行器副本 + 夹具。

    为什么用真仓而不是主树：复用判据第一键是「被验证树的 HEAD」，主树在开发期必然
    脏（未提交改动）→ 复用本来就该关，`PASS` 与 `FAIL` 分不出来。真仓让「干净树」这个
    前提可被本场景自己造出来。

    两个提交**内容逐字节相同**、只有提交对象不同（`-c` 换 committer 时间戳造出两个
    sha）：这样「换 commit ⇒ 零复用」这一子用例换的是**判据的第一键**，而不是别的东西
    （若第二个提交内容不同，复用失败就可能被别的原因解释——那正是要避免的假红/假绿）。

    树内材料一律**提交**（`git add -A`）：`git status --porcelain` 干干净净，A/B 两轮
    跑在真干净树上，不靠口头豁免。被验证的 runner 副本、台账库、以及它 import 的
    `server/engine/failure_protocol.py`（指纹算法与台账 verdict 词表的真源）都在树内。"""
    global _TMP, _MAIN, _WT
    _TMP = tmp
    main = tmp / "main"
    main.mkdir()
    _MAIN = main
    _git("init", "-q", cwd=main)
    _git("config", "user.email", "scenario@example.invalid", cwd=main)
    _git("config", "user.name", "scenario", cwd=main)
    integ = main / "integration"
    integ.mkdir()
    for name in ("run_scenarios.py", "scenario_ledger.py", "lib_tmp_reclaim.py",
                 "lib_env.py", "lib_result.py", "conftest_result_protocol.py",
                 "conftest.py"):
        p = REPO / "integration" / name
        if p.is_file():
            shutil.copy2(str(p), str(integ / name))
    # 引擎协议库（指纹算法/verdict 词表/台账采信判据的唯一真源）：**只复制判据面那一个
    # 模块** `failure_protocol.py`（执行器与台账库都只 import 它；整目录复制会带上
    # `out/` 里的断链软链与上百 MB 运行物料=纯噪声，与判据面无关）。
    eng_dst = main / "server" / "engine"
    eng_dst.mkdir(parents=True)
    shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                 str(eng_dst / "failure_protocol.py"))
    # 夹具场景脚本落在树外（树内零多余文件），经注册表绝对路径执行。
    fx = tmp / "fixtures"
    fx.mkdir()
    script = fx / "fake_scenario.py"
    script.write_text(_fixture_script(tmp / "ran.marker", tmp / "ran.log"),
                      encoding="utf-8")
    # 被验证树的注册表：真注册表文件头 + 一条夹具条目（读真文件=不复制已漂移的表）。
    text = (integ / "run_scenarios.py").read_text(encoding="utf-8")
    entry = ('    (%r,\n'
             '     "夹具：复用行为面的最小轮（本场景注入，不属真注册表）",\n'
             '     "python3 %s", "serial"),\n]' % (SLUG, script))
    head, sep, _tail = text.partition("\nSCENARIOS = [")
    if not sep:
        env_fail("run_scenarios 注册表锚未命中（SCENARIOS = [ 形态变了）")
    text = head + sep + "\n" + entry + text.split("\nSCENARIOS = [", 1)[1].split("\n]", 1)[1]
    (integ / "run_scenarios.py").write_text(text, encoding="utf-8")
    # `.gitignore`（随夹具提交）：执行器会落 `out/`（报告 JSON）与 `__pycache__/`——
    # 这两样必须被**忽略**，否则「干净树」这一个前提会在第一轮跑完就自我破坏
    # （第二轮直接因脏树禁用复用，测的就不是复用面了）。忽略规则是夹具自己的声明，
    # 不在判据链上动任何手脚。
    (main / ".gitignore").write_text("out/\n__pycache__/\n", encoding="utf-8")
    # verify.yaml：真声明道的最小形（integration.cmd 走同一棵树里的副本）。
    (main / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/run_scenarios.py\n", encoding="utf-8")
    _git("add", "-A", cwd=main)
    r = _git("commit", "-q", "-m", "fixture", cwd=main)
    if r.returncode != 0:
        env_fail("夹具提交失败：%s" % (r.stderr or r.stdout)[-300:])
    c1 = _git("rev-parse", "HEAD", cwd=main).stdout.strip()
    # 第二个提交：内容一字不改，只换 committer/author 时间戳 → 不同 sha、同内容。
    r = _git("-c", "author.date=2026-01-01T00:00:00+00:00",
             "-c", "committer.date=2026-01-01T00:00:00+00:00",
             "commit", "-q", "--allow-empty", "-m", "fixture-sibling", cwd=main)
    if r.returncode != 0:
        env_fail("夹具第二提交失败：%s" % (r.stderr or r.stdout)[-300:])
    c2 = _git("rev-parse", "HEAD", cwd=main).stdout.strip()
    if c1 == c2:
        env_fail("两次提交 sha 相同（无法构造「换 commit」几何）")
    # c2 = 当前 HEAD（第一轮跑的那个提交）；c1 = 另一提交（同内容，不同 sha）。
    _TREE["head"] = c2
    _TREE["other"] = c1
    return main


_TREE = {"head": "", "other": ""}


# ---------------------------------------------------------------- 驱动与解析

def _run_runner(wt: Path, ledger_dir: Path, extra_env=None, cwd=None):
    """真入口跑一轮（子进程），返回 (rc, stdout, stderr)。"""
    # 260930：继承来的收窄/策略旋钮单点清理（本夹具自己声明的那几档在下面显式给）
    env = clean_narrowing_env()
    env["SANDBAR_SCENARIO_LEDGER_DIR"] = str(ledger_dir)
    env["SANDBAR_POOL_CONC"] = "4"
    env["SANDBAR_CONC_POOLS"] = "main:1"
    env["SANDBAR_UNDECLARED_POLICY"] = "record"
    # 夹具子用例名（复用的第四键比对的是**注册表场景名**，两者必须逐字相等）。
    env["SANDBAR_FIXTURE_SCENARIO_NAME"] = SLUG
    # 单飞锁档落临时区（本场景逐轮串行，不需要真锁；锁档路径**独立于账目录**——
    # 「主账不可读」子用例会把账目录整棵 chmod 000，锁档不得跟着一起不可写）。
    env["SANDBAR_INTEG_RUN_LOCK_PATH"] = str(_TMP / "run.lock")
    env.update({k: str(v) for k, v in (extra_env or {}).items()})
    try:
        p = subprocess.run(["python3", "integration/run_scenarios.py"], cwd=str(cwd or wt),
                           capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout or ""), (e.stderr or "")
    return p.returncode, p.stdout or "", p.stderr or ""


def _parse(out):
    res = {"pass": [], "fail": [], "env_fail": [], "reuse": [], "scenarios": "",
           "summary": None, "spec_rows": 0}
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("PASS ["):
            res["pass"].append(s)
        elif s.startswith("FAIL ["):
            res["fail"].append(s)
        elif s.startswith("ENV_FAIL ["):
            res["env_fail"].append(s)
        elif ln.startswith("INTEG_REUSE "):
            res["reuse"].append(ln)
        elif ln.startswith("SCENARIOS ran="):
            res["scenarios"] = ln
        elif ln.startswith("INTEG_SUMMARY "):
            try:
                res["summary"] = json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                res["summary"] = "MALFORMED"
        if s[:1] in ("{", "[") and s.startswith('{"name"'):
            res["spec_rows"] += 1
    return res


def _run_gate(wt: Path, ledger_dir: Path, base_sha: str):
    """真verify_lane integ 道跑一轮（台账唯一写者=闸，复用判据的账行由它落）。

    `SANDBAR_GATE_BASELINE=0` 免基线对照（本场景面是复用与账行，不是归属）；
    `SANDBAR_SCENARIO_LEDGER_DIR` 把主账投到夹具目录——真账零写入；
    `SANDBAR_SCENARIO_LEDGER_SOURCE` 声明记账来源（闸侧无来源=**不写账**（宁可缺行
    不可脏行）——生产由引擎注入，本场景显式声明成集测段形态 `lane:<票>`）。"""
    sys.path.insert(0, str(REPO / "server" / "tools"))
    import verify_lane as vl
    keys = ("SANDBAR_SCENARIO_LEDGER_DIR", "SANDBAR_INTEG_LEDGER_SOURCE",
            "SANDBAR_GATE_BASELINE", "SANDBAR_LEDGER_REUSE",
            "SANDBAR_INTEG_RUN_BUDGET_SEC", "SANDBAR_SCENARIO_ONLY",
            "SANDBAR_SCENARIO_EXCLUDE_POOLS",
            # t261002-14 仲裁钉：宽度键必须与本场景内轮显式档（POOL_CONC=4 /
            # CONC_POOLS=main:1，见 _run_runner）**同档**——账行四键里的 width 是
            # 复用判据之一，闸轮若继承外层泳道轮的校准档（t261002-03 起引擎按内存
            # 注入 SANDBAR_POOL_CONC，本进程内调用不经过子进程 env 清理缝），账行
            # 就按外层档记账（实测 width=3 vs 内轮 4）→ B 轮四键 width 不等 →
            # 复用被拒判实跑 → B2..B11 成片假红（260930 本票闸三轮连红实锤，
            # main 树与其余泳道同红=非本票改动引入）。这里显式钉同档，进程内闸轮
            # 与子进程 runner 轮永远同宽。
            "SANDBAR_POOL_CONC", "SANDBAR_CONC_POOLS")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = str(ledger_dir)
        os.environ["SANDBAR_INTEG_LEDGER_SOURCE"] = "lane:" + NAME
        os.environ["SANDBAR_GATE_BASELINE"] = "0"
        os.environ["SANDBAR_POOL_CONC"] = "4"
        os.environ["SANDBAR_CONC_POOLS"] = "main:1"
        for k in ("SANDBAR_LEDGER_REUSE", "SANDBAR_INTEG_RUN_BUDGET_SEC",
                  "SANDBAR_SCENARIO_ONLY", "SANDBAR_SCENARIO_EXCLUDE_POOLS"):
            os.environ.pop(k, None)
        return vl._integ({"lane": "integ", "path": str(wt), "base": base_sha})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _ledger_rows(ledger_dir: Path):
    p = ledger_dir / "scenario-results.jsonl"
    if not p.is_file():
        return []
    rows = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
    return rows


def _reuse_names(res):
    return [ln for ln in res["reuse"]]


# ---------------------------------------------------------------- 主程序

def main():
    # t261017-10 规格②：本场景测的就是复用行为，继承的复用 kill switch 与被测面
    # 直接矛盾——剥掉（clean_narrowing_env 现已收编该裸名）并**点名**认领。
    owned_env_note(("SANDBAR_LEDGER_REUSE", "SANDBAR_INTEG_LEDGER_SOURCE"))
    if shutil.which("git") is None:
        env_fail("git 缺席：本场景的判据面（HEAD/脏树/commit 切换）全在 git 上")
    tmp = Path(tempfile.mkdtemp(prefix="t260930-01-reuse-"))
    try:
        wt = _build_tree(tmp)
        ledger_dir = tmp / "ledger"
        ledger_dir.mkdir()
        other_commit = _TREE["other"]
        marker = tmp / "ran.marker"

        # ---------------- A 首轮：账里没有同键绿行 → 实跑 ----------------
        rcA, outA, errA = _run_runner(wt, ledger_dir)
        rA = _parse(outA)
        ok(rcA == 0 and len(rA["pass"]) == 1, "A1 首轮实跑 rc=0 且规范行 PASS 在场",
           "rc=%s pass=%s fail=%s | stderr=%s | stdout-tail=%s"
           % (rcA, rA["pass"], rA["fail"], errA[-400:], outA[-800:]))
        ok(marker.is_file(), "A2 首轮夹具真被执行（标记文件落盘）")
        ok(bool(rA["summary"]) and rA["summary"].get("reused") == 0
           and rA["summary"].get("expected") == 1 and rA["summary"].get("ran") == 1,
           "A3 首轮汇总 reused=0/ran=expected=1", rA["summary"])
        ok(rA["scenarios"].endswith(" reused=0"),
           "A4 首轮 SCENARIOS 行带 ` reused=0` 尾注（additive）",
           rA["scenarios"])
        ok(not rA["reuse"], "A5 首轮无 INTEG_REUSE 命中行（零复用不冒充复用）",
           rA["reuse"])
        # 账行的唯一写者是闸（执行器不写账）：先让真闸跑同一棵树（此时账里零绿行 →
        # 闸侧也是实跑），账里才会出现复用判据要的那条绿行——**端到端**，不是手写。
        headA = _git("rev-parse", "HEAD", cwd=wt).stdout.strip()
        rcptA = _run_gate(wt, ledger_dir, headA)
        ok(rcptA.get("green") is True,
           "A6 首轮真闸判绿（账行由闸落，复用判据的输入不是手写的）",
           (rcptA.get("green"), rcptA.get("err"), (rcptA.get("detail_red") or [])[:2]))
        rowsA = _ledger_rows(ledger_dir)
        ok(len(rowsA) == 1 and rowsA[0].get("verdict") == "pass"
           and rowsA[0].get("scenario") == SLUG
           and rowsA[0].get("commit") == headA,
           "A7 账里恰一条同名绿行且 commit=树 HEAD（四键判据的输入面）",
           ([(r.get("scenario"), r.get("verdict"), r.get("commit")) for r in rowsA],
            "ledger_dir=%s exists=%s files=%s ledger_face=%s"
            % (ledger_dir, ledger_dir.exists(),
               sorted(x.name for x in ledger_dir.glob("*")),
               json.dumps((rcptA or {}).get("ledger"), ensure_ascii=False)[:400])))

        # ---------------- B 同 commit 第二轮：复用 ----------------
        marker.unlink(missing_ok=True)
        rcB, outB, errB = _run_runner(wt, ledger_dir)
        rB = _parse(outB)
        ok(rcB == 0, "B1 复用轮仍给正常绿 rc=0（全复用不是红也不是「没跑成」）",
           "rc=%s err=%s" % (rcB, errB[-300:]))
        ok(len(rB["reuse"]) >= 1 and rB["reuse"][0].startswith("INTEG_REUSE 复用台账绿行 1 条"),
           "B2 stdout 有专行 `INTEG_REUSE 复用台账绿行 1 条…`（响亮，绝不静默）",
           (rB["reuse"][:1], "pass=%s summary=%s stderr=%s"
            % (rB["pass"], rB["summary"], errB[-300:])))
        ok(bool(rB["reuse"]) and SLUG in rB["reuse"][0],
           "B3 专行点名到具体场景名", rB["reuse"][:1])
        ok(not marker.exists(), "B4 复用条目**没被实跑**（标记文件未重造）")
        ok(not rB["pass"] and not rB["fail"] and not rB["env_fail"] and not rB["spec_rows"],
           "B5 复用轮零散场景/零规范行（不冒充实跑）",
           (rB["pass"], rB["fail"], rB["spec_rows"]))
        sB = rB["summary"]
        ok(bool(sB) and sB.get("ran") == 0 and sB.get("reused") == 1
           and sB.get("expected") == 1,
           "B6 全复用轮 ran=0/reused=expected=1（ran+reused==expected）", sB)
        ok(" ran=0 " in rB["scenarios"] and rB["scenarios"].endswith(" reused=1"),
           "B7 SCENARIOS 行如实报 ran=0 且尾注 reused=1", rB["scenarios"])
        ok(bool(sB) and sB.get("pass") == 0,
           "B8 复用条目不进 pass 计数（不算新鲜通过）", sB)
        rowsB = _ledger_rows(ledger_dir)
        ok(len(rowsB) == len(rowsA),
           "B9 复用条目不重盖章：账行数不变（时间戳不被刷新，绿行自行老化）",
           (len(rowsA), len(rowsB)))
        rep = sorted((wt / "out").glob("integration-report-*.json"))
        ok(bool(rep), "B10 报告 JSON 落档（在被验证树的 out/ 下）")
        if rep:
            doc = json.loads(rep[-1].read_text(encoding="utf-8"))
            ok(doc.get("reused") == 1 and doc.get("reused_names") == [SLUG],
               "B11 报告 JSON 带 reused 计数与**全名单**", doc.get("reused_names"))
            ok(doc.get("reuse_enabled") is True and doc.get("reuse_disabled_reason") is None,
               "B12 报告 JSON 记录本轮复用**启用**（三态可分辨）",
               (doc.get("reuse_enabled"), doc.get("reuse_disabled_reason")))

        # ---------------- C 换 commit：切到同内容的另一提交 → 零复用 ----------------
        # 两提交内容逐字节相同、只有 sha 不同：换的**只有判据第一键**。若这里判成复用，
        # 就说明「同 commit」这条根本没被当判据（拿别的维度蒙对）。
        r = _git("checkout", "--detach", other_commit, cwd=wt)
        ok(r.returncode == 0, "C0 被验证树切到另一提交（几何前提）", (r.stderr or "")[-200:])
        ok(_git("status", "--porcelain", cwd=wt).stdout.strip() == "",
           "C0b 切换后树仍干净（差异只有 commit sha 这一维）",
           _git("status", "--porcelain", cwd=wt).stdout[:200])
        marker.unlink(missing_ok=True)
        rcC, outC, errC = _run_runner(wt, ledger_dir)
        rC = _parse(outC)
        ok(rcC == 0 and len(rC["pass"]) == 1, "C1 换 commit 后实跑（rc=0、规范行在场）",
           (rcC, rC["pass"], errC[-300:]))
        ok(marker.is_file(), "C2 换 commit 后夹具**真被执行**（未复用）")
        ok(bool(rC["summary"]) and rC["summary"].get("reused") == 0
           and not rC["reuse"],
           "C3 复用判据第一键精确相等：别的 commit 的绿行不复用（祖先/同内容兄弟提交都不算）",
           (rC["summary"], rC["reuse"]))
        r = _git("checkout", "--detach", _TREE["head"], cwd=wt)
        ok(r.returncode == 0 and _git("rev-parse", "HEAD", cwd=wt).stdout.strip()
           == _TREE["head"],
           "C4 几何复原到原 HEAD（后续子用例的前提；账行就挂在这个提交上）",
           (_git("rev-parse", "HEAD", cwd=wt).stdout.strip(), _TREE["head"]))

        # ---------------- D kill switch ----------------
        marker.unlink(missing_ok=True)
        rcD, outD, errD = _run_runner(wt, ledger_dir,
                                      extra_env={"SANDBAR_LEDGER_REUSE": "0"})
        rD = _parse(outD)
        ok(rcD == 0 and marker.is_file(), "D1 kill switch 下实跑（rc=0、夹具真跑）", rcD)
        ok(not rD["reuse"] and bool(rD["summary"]) and rD["summary"].get("reused") == 0,
           "D2 kill switch 下零复用（专行缺席、计数 0）",
           (rD["reuse"], rD["summary"]))
        ok(("SANDBAR_LEDGER_REUSE" in errD) and ("禁用" in errD or "关闭" in errD),
           "D3 stderr 一行具名理由点名 kill switch（降级绝不静默）", errD[-300:])

        # ---------------- E 脏树 ----------------
        (wt / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        marker.unlink(missing_ok=True)
        rcE, outE, errE = _run_runner(wt, ledger_dir)
        rE = _parse(outE)
        ok(rcE == 0 and marker.is_file(), "E1 脏树下实跑（rc=0、夹具真跑）", rcE)
        ok(not rE["reuse"] and bool(rE["summary"]) and rE["summary"].get("reused") == 0,
           "E2 脏树禁用复用（HEAD 单独描述不了这棵树）",
           (rE["reuse"], rE["summary"]))
        ok("脏" in errE, "E3 stderr 一行具名理由点名「工作树脏」", errE[-300:])
        (wt / "untracked.txt").unlink()
        ok(_git("status", "--porcelain", cwd=wt).stdout.strip() == "",
           "E4 清掉未跟踪件后树恢复干净（后续子用例的几何前提）",
           _git("status", "--porcelain", cwd=wt).stdout[:200])

        # ---------------- F 主账不可读（fail-closed） ----------------
        locked = tmp / "locked"
        (locked / "ledger").mkdir(parents=True)
        (locked / "ledger" / "scenario-results.jsonl").write_text("", encoding="utf-8")
        led_dir = locked / "ledger"
        marker.unlink(missing_ok=True)
        os.chmod(str(led_dir), 0o000)
        try:
            rcF, outF, errF = _run_runner(wt, led_dir)
        finally:
            os.chmod(str(led_dir), 0o755)
        rF = _parse(outF)
        if rcF != 0 and "Permission" not in errF and os.geteuid() == 0:
            na("F 主账不可读面", "以 root 跑时 chmod 000 挡不住读（权限面不可构造）")
        else:
            ok(rcF == 0 and marker.is_file(), "F1 主账不可读时实跑（rc=0、夹具真跑）", rcF)
            ok(not rF["reuse"] and bool(rF["summary"]) and rF["summary"].get("reused") == 0,
               "F2 读账失败 = fail-closed 关（零复用，绝不静默按空账放行）",
               (rF["reuse"], rF["summary"], errF[-200:]))
            ok("禁用" in errF or "失败" in errF,
               "F3 stderr 一行具名理由点名读账失败", errF[-300:])

        # ---------------- G 闸回执面（真 verify_lane integ 道，全复用轮） ----------------
        # 账里已有同 commit+同指纹同宽的绿行（A 轮闸落的），被验证树干净、HEAD 未动
        # → 本轮的执行器**一条都不实跑**；闸回执必须把这件事说清楚且仍判绿。
        base = _git("rev-parse", "HEAD", cwd=wt).stdout.strip()
        rcpt = _run_gate(wt, ledger_dir, base)
        reuse_face = (rcpt or {}).get("reuse")
        ok(bool(reuse_face) and reuse_face.get("reused") == 1
           and reuse_face.get("all_reused") is True,
           "G1 闸回执带复用面：reused=1 且 all_reused=True（全复用轮一眼可辨）",
           reuse_face)
        ok(bool(reuse_face) and reuse_face.get("names") == [SLUG]
           and reuse_face.get("expected") == 1,
           "G2 闸回执带复用名单与在册数（仲裁不必读执行器 stdout）", reuse_face)
        ok(rcpt.get("green") is True,
           "G3 闸判绿：完整性判据 ran + reused == expected 兑现（复用轮不冒充实跑全绿，"
           "也不因零实跑被误判残缺）", (rcpt.get("green"), rcpt.get("err"),
                                       (rcpt.get("detail_red") or [])[:2]))
        ok(not (rcpt.get("detail_red") or []),
           "G4 闸零 detail_red（复用的完整性不推任何红面）",
           (rcpt.get("detail_red") or [])[:2])
    finally:
        _cleanup()


if __name__ == "__main__":
    main()          # 早退档（env_fail/finish）自行 exit；正常返回后才收口
    finish()
