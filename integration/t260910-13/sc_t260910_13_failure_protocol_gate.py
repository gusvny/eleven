#!/usr/bin/env python3
"""失败分类协议闸：机械分类×基线归属判定的真缝场景（t260910-13，灰盒 L2/L3）。

intent：260910 三次误判（t260910-05/08/10）的根治面——失败信息从「文本行+退出码
只能人读猜」升级为「单行 JSON 规范行 + 闸机械判定」。本场景经真缝
（admin.py call verify_lane lane=integ，fixture 仓桩输出）钉死闸的判定契约：

  - 规范行权威（C8）：以 `{` 起始、可独立 json.loads、必含最小字段
    name/suite/status(pass|fail|not-checked)/cause/reason/dur_s/attempt/started/
    git_sha/evidence/artifacts 的单行 = 规范行；闸判定以规范行为准，
    旧 PASS[/FAIL[/ENV_FAIL[ 文本行降级为兼容面。
  - 三态收紧 fail-closed：无证据的 not-checked(ENV_FAIL 态) 闸内改判 FAIL（拦）；
    fail×prepare-reason(self_precheck/connect_refused/lock_busy/missing_asset)
    = 协议违约 → 改判 not-checked + violation + 拦（不因 main 也红放行，C5）。
  - 机械归属（宿主决策表）：基线红名单只收 checked fail（C1，基线 not-checked
    不进名单、对应用例归属 unknown）；指纹相等才采信差集（C2，不等全降 unknown
    +差异面显式）；not-checked×self×main绿→拦；not-checked×external×main绿→
    记录不堵；checked fail×main红→既有欠账记录不堵；checked fail×main绿→真回归拦；
    基线缺席/关闭→降级显式声明（不静默跳过对照），产品红保守不放松。
  - 汇总行由闸补全（C6）：summary 含 ran/pass/fail/not_checked/wall_s/concurrency/
    pool_config/env_fingerprint/baseline_ref，旧回执字段（green/ran/...）不动。
  - 闸不认识场景名（机械判定对抗探针）：同名异 payload 同判、异名同 payload 同判。

真基线子用例（C10）：fixture 为真 git 仓（main 提交桩 + 泳道工作树脏改桩），闸真跑
`git worktree add --detach` 取基线红名单，全程真 git 真进程；终态回收经
`git worktree list` 断言零残留。git 缺席=ENV_FAIL exit 2 点名（三态契约，环境缺失红不假绿）。

与既有场景 intent 分界：t260904-12 甲/乙段守「三态输出不可穿闸」（ENV_FAIL 文本行
契约面），t260903-01 ②b-(a) 守「畸形 FAIL 行 fallback 与汇总矛盾面」——均为旧文本
协议；本条守规范行解析+违约改判+基线归属决策表，实现落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。与 developer L1（决策表纯函数真值表、畸形 JSON 电池）
不同层：本条锁真缝（admin 入口→verify_lane→基线子进程）的组装行为。

安全红线：fixture 全落系统临时目录零真仓接触；不触 3099/7233；零 docker 零端口。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
if str(INTEG) not in sys.path:          # 集成侧回收 helper（同目录树根）
    sys.path.insert(0, str(INTEG))
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


def call_gate(repo, extra_env=None, timeout=180):
    """真缝调闸：admin.py call verify_lane lane=integ（t260904-12 甲段同款入口）。"""
    env = dict(os.environ)
    env.update(extra_env or {})
    try:
        p = subprocess.run(
            [sys.executable, "server/admin.py", "call", "verify_lane",
             json.dumps({"lane": "integ", "path": str(repo)})],
            cwd=str(REPO), capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stderr": "gate call timeout"}
    if p.returncode != 0:
        return {"ok": False, "stderr": (p.stderr or "")[-300:]}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stderr": "unparseable: " + p.stdout[-200:]}
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if not isinstance(inner, dict):
        return {"ok": False, "stderr": "no result envelope: " + p.stdout[-200:]}
    return {"ok": True, "result": inner}


def row(status=None, cause=None, reason=None, evidence=None, name="case-x",
        omit=(), **over):
    """构造一条规范行文本（最小字段全给，omit/over 供畸形变体）。"""
    d = {"name": name, "suite": "stub", "status": status, "cause": cause,
         "reason": reason, "dur_s": 0.1, "attempt": 1,
         "started": "2026-09-10T00:00:00Z", "git_sha": "0" * 40,
         "evidence": evidence, "artifacts": []}
    for k in omit:
        d.pop(k, None)
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


def make_fixture(body, git=False, stub_name="integ_stub.py"):
    """临时仓：verify.yaml 声明 integration.cmd → 桩；git=True 时提交 main（真基线子用例）。"""
    # 夹具回收（260927 全族整治）：本文件是 L8 基线里的存量债——$TMPDIR 顶层实测
    # `t26091013-*` 17,254 条（其中 <6h 的 8,594 条=当期最大单一活生产源）。改走集成侧
    # 注册表（登记 + atexit 兜底 + 幂等回收；终态矩阵见 lib_tmp_reclaim 模块头）。
    td = str(mkdtemp_reclaimed("t26091013-"))
    repo = Path(td)
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        "integration:\n  cmd: python3 %s\n" % stub_name)
    (repo / stub_name).write_text(body)
    if git:
        r = subprocess.run(["git", "init", "-b", "main"], cwd=repo,
                           capture_output=True, text=True)
        if r.returncode != 0:  # 旧 git 无 -b：init+branch 兜底
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "main"], cwd=repo,
                           capture_output=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                        "-c", "user.name=t", "commit", "-m", "stub"],
                       capture_output=True)
    return repo


def worktree_count(repo):
    r = subprocess.run(["git", "-C", str(repo), "worktree", "list",
                        "--porcelain"], capture_output=True, text=True)
    return len([b for b in r.stdout.split("\n") if b.startswith("worktree ")])


def has_string(obj, needle):
    """深搜：结果 JSON 任意层级字符串值含 needle（浅绑定：不锚容器形状）。"""
    return needle in json.dumps(obj, ensure_ascii=False)


def ok_judged(inner, label):
    """协议判定真发生过守卫：err 非空 = 闸走了兼容/异常路径而非规范行判定——
    green 值再对也只是巧合 fail-closed，不算数（对抗纪律：防「红对 Reasons 错」）。"""
    ok(inner.get("err") is None and inner.get("cases") is not None,
       label + "（协议判定真发生：err 空+cases 在场）")


BASELINE_OFF = {"SANDBAR_GATE_BASELINE": "0"}


def stub_src(row_text, exit_code=None):
    """桩执行器 = 模拟真实执行器完整输出契约：规范行 + INTEG_SUMMARY + 一致的
    退出码（三态契约：fail→1、not-checked→2；汇总行在场是闸「用例集完整」的
    判据，真执行器崩溃时恰缺席——S9 崩溃面以此区分）。"""
    c = json.loads(row_text)
    st = c["status"]
    if exit_code is None:
        exit_code = 0 if st == "pass" else (1 if st == "fail" else 2)
    summ = {"ran": 1, "pass": 1 if st == "pass" else 0,
            "fail": 1 if st == "fail" else 0,
            "not_checked": 1 if st == "not-checked" else 0,
            "wall_s": 0.1, "concurrency": 1, "pool_config": "stub:1",
            "env_fingerprint": "stub-fp"}
    return ("import json\nprint(%r)\nprint('INTEG_SUMMARY ' + json.dumps(%r))\n"
            "import sys; sys.exit(%d)\n" % (row_text, summ, exit_code))


# 桩库：每支=打印规范行后按协议退出。行权威口径：闸以行判定。
STUB_PASS = stub_src(row("pass", evidence="ok"), 0)
STUB_ASSERT_FAIL = stub_src(row(
    "fail", cause="self", reason="assert_mismatch", evidence="assert 1==2 failed"), 1)
STUB_PRECHECK_FAIL = stub_src(row(
    "fail", cause="self", reason="self_precheck", evidence="precheck: bundle stale, refused to run"), 1)
STUB_EXT_NOEVID = stub_src(row(
    "not-checked", cause="external", reason="connect_refused", evidence=""))
STUB_EXT_EVID = stub_src(row(
    "not-checked", cause="external", reason="connect_refused",
    evidence="ENV: connection refused 127.0.0.1:9 (docker stage down)"))
STUB_SELF_EVID = stub_src(row(
    "not-checked", cause="self", reason="self_precheck",
    evidence="self precheck: fixture missing src/asset.json"))

print("== S0 对照组（夹具有效性）：规范行 pass → 闸绿（基线关，全绿无需对照）")
repo = make_fixture(STUB_PASS)
res = call_gate(repo, BASELINE_OFF)
ok(res.get("ok") is True, "S0 调用成功（admin.py 真入口）")
inner = res.get("result", {})
ok(inner.get("green") is True, "S0 规范行 pass → green=true（旧字段不动）")

print("== S1 汇总行契约（C6）：闸补全九键汇总，测试不写汇总")
s = inner.get("summary")
ok(isinstance(s, dict), "S1 summary 在场（闸生成）")
if isinstance(s, dict):
    for k in ("ran", "pass", "fail", "not_checked", "wall_s", "concurrency",
              "pool_config", "env_fingerprint", "baseline_ref"):
        ok(k in s, "S1 summary.%s 在场" % k)
    ok(bool(s.get("env_fingerprint")), "S1 env_fingerprint 非空")

print("== S2 真红必拦（t260910-10 型）：lane 断言红 × 基线绿 → 拦（真 git 基线）")
if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
    ok(False, "S2 git 缺失=ENV_FAIL 面（基线子用例不可验）")
    print("ENV_FAIL: git 缺失，基线归属子用例不可验（exit 2）")
    sys.exit(2)
repo = make_fixture(STUB_PASS, git=True)
(repo / "integ_stub.py").write_text(STUB_ASSERT_FAIL)  # 泳道脏改=断言红
res = call_gate(repo)  # 基线缺省开
inner = res.get("result", {})
ok(inner.get("green") is False, "S2 真回归 → green=false（拦）")
ok_judged(inner, "S2 判定面")
ok(has_string(inner, "case-x"), "S2 归属记录点名用例（可见非静默）")
ok(has_string(inner, "baseline"), "S2 基线对照面在案（baseline_ref/记录）")
ok(worktree_count(repo) == 1, "S2 基线 worktree 终态回收零残留")

print("== S3 main 基线红不堵票：同断言红 × 基线红 → 既有欠账记录不堵")
repo = make_fixture(STUB_ASSERT_FAIL, git=True)  # main 与泳道同红
res = call_gate(repo)
inner = res.get("result", {})
ok(inner.get("green") is True, "S3 既有欠账 → 不堵（green=true）")
ok_judged(inner, "S3 判定面")
ok((inner.get("summary") or {}).get("fail") == 1, "S3 汇总诚实计数 fail=1（不洗数）")
ok(has_string(inner, "case-x"), "S3 欠账记录点名用例（记录可见）")
ok(worktree_count(repo) == 1, "S3 基线 worktree 回收零残留")

print("== S4 违约拦（capture-chat-active 型）：fail×self_precheck，且 main 也红不放行")
repo = make_fixture(STUB_ASSERT_FAIL, git=True)  # main=checked fail（进红名单）
(repo / "integ_stub.py").write_text(STUB_PRECHECK_FAIL)  # 泳道=违约形态
res = call_gate(repo)
inner = res.get("result", {})
ok(inner.get("green") is False, "S4 违约独立拦截（不因基线红放行）")
ok_judged(inner, "S4 判定面")
ok(has_string(inner, "self_precheck") or has_string(inner, "violation"),
   "S4 违约标记在案（reason 保留/标注）")

print("== S5 无证据 ENV_FAIL 按 FAIL 处理（fail-closed 治免责标签）")
repo = make_fixture(STUB_EXT_NOEVID)
res = call_gate(repo, BASELINE_OFF)
inner = res.get("result", {})
ok(inner.get("green") is False, "S5 无证据 not-checked → 改判 FAIL（拦）")
ok_judged(inner, "S5 判定面")
ok(has_string(inner, "evidence"), "S5 改判理由点名证据缺失（报错精确）")

print("== S6 决策表 not-checked 两子用例：self×main绿拦 / external×main绿记录不堵")
repo = make_fixture(STUB_PASS, git=True)
(repo / "integ_stub.py").write_text(STUB_SELF_EVID)
res = call_gate(repo)
res6a = res.get("result") or {}
ok(res6a.get("green") is False, "S6a not-checked×self×main绿 → 拦（本票造成）")
ok_judged(res6a, "S6a 判定面")
repo = make_fixture(STUB_PASS, git=True)
(repo / "integ_stub.py").write_text(STUB_EXT_EVID)
res = call_gate(repo)
inner = res.get("result", {})
ok(inner.get("green") is True, "S6b not-checked×external×main绿 → 记录+促治理不堵")
ok(has_string(inner, "connect_refused") or has_string(inner, "case-x"),
   "S6b 促治理记录点名（可见）")

print("== S7 基线关闭=降级显式：产品红保守拦不放松；缺席声明不静默")
repo = make_fixture(STUB_PASS)
(repo / "integ_stub.py").write_text(STUB_ASSERT_FAIL)
res = call_gate(repo, BASELINE_OFF)
inner = res.get("result", {})
ok(inner.get("green") is False, "S7a 基线缺席 × 断言红 → 保守拦（归属未知不放松产品红）")
repo = make_fixture(STUB_EXT_EVID)
res = call_gate(repo, BASELINE_OFF)
inner = res.get("result", {})
ok(inner.get("green") is True, "S7b 基线缺席 × not-checked×external → 记录不堵")
ok((inner.get("summary") or {}).get("baseline_ref") is None,
   "S7b baseline_ref=None 显式（缺席可见）")
ok(has_string(inner, "baseline") or has_string(inner, "基线"),
   "S7b 降级声明在案（不静默跳过对照）")

print("== S8 畸形规范行与机械性对抗面（消费外部输入纪律）")
mal = row("fail", cause="self", reason="assert_mismatch", evidence="x",
          omit=("status",))  # 必填字段缺失
repo = make_fixture("print(%r)\nimport sys; sys.exit(0)\n" % mal)
res = call_gate(repo, BASELINE_OFF)
res8a = res.get("result") or {}
ok(res8a.get("green") is False,
   "S8a 缺 status 的规范行 → fail-closed（不得静默零场景绿）")
ok_judged(res8a, "S8a 判定面")
repo = make_fixture("print('{not-json')\nimport sys; sys.exit(0)\n")
res = call_gate(repo, BASELINE_OFF)
ok((res.get("result") or {}).get("green") is False,
   "S8b 伪规范行（{起始不可解析）→ fail-closed（不得静默丢行后假绿）")
dup = row("pass", evidence="ok")
repo = make_fixture("print(%r); print(%r)\nimport sys; sys.exit(0)\n" % (dup, dup))
res = call_gate(repo, BASELINE_OFF)
res8c = res.get("result") or {}
ok(res8c.get("green") is False,
   "S8c 同名重复行 → 红（一行=一用例不变式，重复即闸红）")
ok_judged(res8c, "S8c 判定面")
r1 = call_gate(make_fixture(
    "print(%r)\nimport sys; sys.exit(1)\n" % row(
        "fail", cause="self", reason="assert_mismatch", evidence="x",
        name="capture-chat-active"), ), BASELINE_OFF)
r2 = call_gate(make_fixture(
    "print(%r)\nimport sys; sys.exit(1)\n" % row(
        "fail", cause="self", reason="assert_mismatch", evidence="x",
        name="plain-case-zzz"), ), BASELINE_OFF)
ok((r1.get("result") or {}).get("green") is (r2.get("result") or {}).get("green") is False,
   "S8d 闸不认识场景名：异名同 payload 同判（双拦）")
ok(has_string(r1.get("result", {}), "capture-chat-active")
   and not has_string(r1.get("result", {}), "plain-case-zzz"),
   "S8d 归属记录各归其名（无名字特判串味）")

print("== S9 执行器崩溃面 fail-closed（走查 gen1 问题一回归钉）：非正常退出≠绿")
# 探针A 形态复刻：规范行 pass + 旧 PASS 行，exit 1、无 INTEG_SUMMARY（崩溃/被杀，
# 用例集残缺）——协议模式不得出绿。修改前口径：green=True（fail-open 实证）。
crash_body = ("print(%r)\nprint('PASS [case-x] (0.1s)')\nimport sys; sys.exit(1)\n"
              % row("pass", evidence="ok"))
repo = make_fixture(crash_body)
res = call_gate(repo, BASELINE_OFF)
res9a = res.get("result") or {}
ok(res9a.get("green") is False, "S9a 崩溃面（rc!=0+汇总缺席）→ 红（不得 fail-open）")
ok_judged(res9a, "S9a 判定面")
ok(has_string(res9a, "incomplete") or has_string(res9a, "abnormally"),
   "S9a 红因点名用例集可能残缺（报错精确；260927 报告英文面）")
# 对照子用例：同样 pass 规范行 + 汇总在场 + rc=0 → 绿（区分「场景级红」与「崩溃面」）
ok_body = stub_src(row("pass", evidence="ok"), 0).replace(
    "import json\n", "import json\nprint('PASS [case-x] (0.1s)')\n", 1)
repo = make_fixture(ok_body)
res = call_gate(repo, BASELINE_OFF)
ok((res.get("result") or {}).get("green") is True,
   "S9b 对照：rc=0+汇总在场+全 pass 规范行 → 绿（崩溃面判定不误伤正常面）")

print("== S9c 清单残缺面（t260911 仲裁③）：ran != 在册 expected → 闸红")
# 复刻 260911 静默丢条形态：汇总自洽但 ran < expected——唯一机械不变式在闸侧复验。
lack = stub_src(row("pass", evidence="ok"), 0).replace(
    "'env_fingerprint': 'stub-fp'}",
    "'env_fingerprint': 'stub-fp', 'expected': 2}")
repo = make_fixture(lack)
res = call_gate(repo, BASELINE_OFF)
res9c = res.get("result") or {}
ok(res9c.get("green") is False, "S9c ran!=expected → 红（条目级丢失在闸现形）")
ok(has_string(res9c, "清单残缺") or has_string(res9c, "expected"),
   "S9c 红因点名清单残缺（报错精确）")

print("== 结果：%d ok / %d FAIL" % (pass_n, fail_n))
sys.exit(1 if fail_n else 0)
