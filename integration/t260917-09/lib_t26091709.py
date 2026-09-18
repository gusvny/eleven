# -*- coding: utf-8 -*-
"""t260917-09 共享夹具（本票两场景 sc_tests_* 共用；非 sc_ 前缀＝共享代码不登记）。

提供：
- T09_STUB：arbitrate 可控**判决序列**桩（lib_ki061.ARB_STUB 是常量 verdict，
  序列能力本票自建——R4 结论）；判决序列耗尽后确定性回落 verdict=pass（主腿
  确定性终态，防第 N+1 判决撞上限造成场景自身假红）。
- make_fixture_repo：夹具项目仓（裸仓或带 integration 声明面：verify.yaml +
  mini 执行器，供机械链真跑三态回执）。
- MINI_RUNNER：夹具迷你执行器（场景自有资产，随夹具仓落库）。真注册表形状
  （SCENARIOS=[(name,intent,cmd)]，/bin/sh -c 语义），模式由 T09_FIXTURE_MODE
  选 JITTER/ENV/GHOST；ghost_stale_name 刻意不在册（模拟基线/闸拦面的陈旧
  红项名——不在册必须保守计轮，封死死源静默复发，C1 钉子）。

骨架抄 t260912-03 sc_authz_overlimit_accept / t260908-01 lib_ki061（取舍清单
见方案 v2 §3；本库不新增引擎面依赖）。
"""
import json
import os
import re
import subprocess

# 判决序列 env（worker 环境读定；逗号分隔三态词，耗尽回落 pass）
ENV_ARB_SEQ = "SANDBAR_T09_ARB_SEQ"
# 夹具执行器模式 env（经 worker→activity→verify_lane→执行器继承）
ENV_FIXTURE_MODE = "T09_FIXTURE_MODE"

ARB_STUB = r"""
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
log = os.environ["T09_STUB_LOG"]
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps({"stage": stage, "ts": time.time(), "prompt": prompt},
                       ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    if stage == "arbitrate":
        seq = [s.strip() for s in
               os.environ.get("SANDBAR_T09_ARB_SEQ", "tests-fault").split(",")
               if s.strip()]
        n = 0
        try:
            with open(log, encoding="utf-8") as f:
                n = sum(1 for ln in f if '"stage": "arbitrate"' in ln) - 1
        except OSError:
            n = 0
        verdict = seq[n] if 0 <= n < len(seq) else "pass"  # 耗尽=确定性回落 pass
        body = {"status": "ok",
                "summary": "verdict=%s（t260917-09 桩：第 %d 次 arbitrate）"
                           % (verdict, n + 1),
                "report": "[t09-stub] 机械仲裁回执 verdict=%s" % verdict,
                "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "t09-stub"}
    else:
        body = {"status": "ok", "summary": "[t09-stub] %s 完成" % stage,
                "report": "[t09-stub] 桩回执", "deliverables": [],
                "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "t09-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""

# 夹具迷你执行器：真注册表形状（SCENARIOS 三元组，cmd 走 /bin/sh -c，与主仓
# 执行器同语义的 mini 形）；ghost_stale_name 只在回执面出现、不在 SCENARIOS。
MINI_RUNNER = r'''
#!/usr/bin/env python3
"""t260917-09 夹具迷你执行器（场景自有，随夹具仓落库；模式=T09_FIXTURE_MODE）。

契约与主仓执行器同形（mini 版）：每案一行 PASS[/FAIL[/ENV_FAIL[ 文本行 +
一行 JSON 规范行（失败案带缩进尾巴），末行 INTEG_SUMMARY（ran/pass/fail/
not_checked/expected 五键，闸重算复核口径）；红面 rc≠0、全绿 rc=0。
"""
import json
import os
import subprocess
import sys

SCENARIOS = [
    ("flaky_sc", "t260917-09 夹具：首跑红、复跑绿（marker 确定性抖动形，KI-072 同族）",
     # marker 必须落在 tests/ 测试面内（路径闸白名单）：根目录裸文件会让 arbitrate
     # 段 settle 撞「unauthorized_path」闸拒（t260917-01），仲裁回执被吞票即封
     "[ -f tests/.probe_marker ] || { mkdir -p tests; touch tests/.probe_marker; exit 1; }"),
    ("env_sc", "t260917-09 夹具：确定性环境红（依赖缺席三态形）",
     "echo 'ENV_FAIL: 夹具确定性环境红（依赖缺席，t260917-09 夹具）' >&2; exit 2"),
    ("real_sc", "t260917-09 夹具：恒绿对照案", "true"),
]
# ghost_stale_name 刻意不在上表：回执面出现、注册表查无——陈旧红项名形态
# （基线改名/闸拦面遗留），引擎必须保守计轮并点名，绝不静默当全绿。


def _emit_pass(name):
    print("PASS [%s]" % name)
    print(json.dumps({"name": name, "status": "pass", "cause": "self",
                      "suite": "t09"}, ensure_ascii=False))


def _emit_fail(name, tail):
    flat = " ".join(str(tail or "fail").split())
    print("FAIL [%s] exit=1" % name)
    if flat:
        print("    %s" % flat[:1500])
    print(json.dumps({"name": name, "status": "fail", "cause": "self",
                      "reason": "assert", "evidence": flat[:200],
                      "suite": "t09"}, ensure_ascii=False))


def _emit_env_fail(name, tail):
    flat = " ".join(str(tail or "env").split())
    print("ENV_FAIL [%s] exit=2" % name)
    if flat:
        print("    %s" % flat[:1500])
    print(json.dumps({"name": name, "status": "not-checked", "cause": "external",
                      "reason": "env", "evidence": flat[:200],
                      "suite": "t09"}, ensure_ascii=False))


def _run_entry(name):
    cmd = dict((s[0], s[2]) for s in SCENARIOS)[name]
    p = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _reprobe(names):
    """--reprobe：只复跑点名条目，串行（t260917-09 探针契约，证据面非闸面）。
    与主仓执行器 reprobe_main 同形：不在册/空名单 → 一条都不跑＋REPROBE_SUMMARY
    打 error 点名 exit 2（fail-closed 保守计轮信号）；rc=0 当且仅当全绿。
    引擎 parse_reprobe_summary 只认「末行 REPROBE_SUMMARY <JSON>」——缺行=error。"""
    index = dict((s[0], s) for s in SCENARIOS)
    missing = [n for n in names if n not in index]
    if not names or missing:
        print("REPROBE_SUMMARY " + json.dumps({
            "ran": 0, "passed": 0, "failed": 0, "env_fail": 0,
            "missing": missing, "error": ("红项不在册：%s——一条都未跑（保守计轮信号）"
                                          % "、".join(missing)) if missing
                                         else "复跑名单为空——一条都未跑",
            "entries": []}, ensure_ascii=False))
        return 2
    ran = passed = failed = env_fail = 0
    entries = []
    for n in names:
        rc, tail = _run_entry(n)
        dur = 0.0
        entries.append({"name": n, "exit": rc, "dur_s": dur})
        ran += 1
        print("复跑 [%s] %s（exit=%d）" % (
            n, "过" if rc == 0 else ("环境红" if rc == 2 else "败"), rc),
            flush=True)
        if tail:
            print("    %s" % " ".join(tail.split())[:600])
        if rc == 0:
            passed += 1
        elif rc == 2:
            env_fail += 1
        else:
            failed += 1
    print("REPROBE_SUMMARY " + json.dumps({
        "ran": ran, "passed": passed, "failed": failed, "env_fail": env_fail,
        "missing": [], "error": "",
        "entries": entries}, ensure_ascii=False))
    return 0 if failed == 0 and env_fail == 0 else 1


def main():
    mode = os.environ.get("T09_FIXTURE_MODE", "JITTER")
    results = []  # (name, kind, exit, tail)；kind ∈ pass|fail|env
    if mode == "JITTER":
        rc, tail = _run_entry("flaky_sc")
        results.append(("flaky_sc", "pass" if rc == 0 else "fail", rc, tail))
    elif mode == "ENV":
        rc, tail = _run_entry("env_sc")
        results.append(("env_sc", "pass" if rc == 0 else "env", rc, tail))
    elif mode == "GHOST":
        rc, tail = _run_entry("real_sc")
        results.append(("real_sc", "pass" if rc == 0 else "fail", rc, tail))
        results.append(("ghost_stale_name", "fail", 1,
                        "ghost：陈旧红项名（不在注册表，t260917-09 夹具）"))
    else:
        print("未知 T09_FIXTURE_MODE=%r" % mode, file=sys.stderr)
        sys.exit(2)
    npass = nfail = nenv = 0
    for name, kind, _rc, tail in results:
        if kind == "pass":
            _emit_pass(name)
            npass += 1
        elif kind == "env":
            _emit_env_fail(name, tail)
            nenv += 1
        else:
            _emit_fail(name, tail)
            nfail += 1
    n = len(results)
    print("INTEG_SUMMARY " + json.dumps(
        {"ran": n, "pass": npass, "fail": nfail, "not_checked": nenv,
         "expected": n}))
    sys.exit(0 if nfail == 0 and nenv == 0 else 1)


if __name__ == "__main__":
    if "--reprobe" in sys.argv:               # t260917-09 探针出口（先于全量跑分流）
        _i = sys.argv.index("--reprobe")
        _names = [n for n in sys.argv[_i + 1:] if not n.startswith("--")]
        sys.exit(_reprobe([n for n in ",".join(_names).split(",") if n]))
    main()
'''

FIXTURE_VERIFY_YAML = (
    "# t260917-09 夹具声明面（场景自有；integration 道=迷你执行器单点）\n"
    # schema: v1 与 lanes.code.write_allow 均必备——_validate_cfg 对缺 schema/
    # write_allow 各层 fail-closed（实测 260918：缺失时闸「版本不支持/write_allow
    # 结构不合法」拒绝 → cur_integ 恒空 → 三腿零豁免全退化成普通计轮）
    "schema: v1\n"
    "lanes:\n"
    "  code:\n"
    "    write_allow:\n"
    "      - docs/\n"
    "integration:\n"
    "  cmd: python3 integration/run_scenarios.py\n"
)


def git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   capture_output=True, text=True)


def make_fixture_repo(tmp, name="fixture-repo", with_integration=False):
    """夹具项目仓：git init + 首 commit（骨架同 lib_ki061.make_fixture_repo）。
    with_integration=True 时落 verify.yaml + integration/run_scenarios.py
    （mini 执行器）并入库——基线重跑在临时 worktree 上需要它们在库。"""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)

    def g(*a):
        git(repo, *a)

    g("init", "-q")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("fixture\n")
    if with_integration:
        with open(os.path.join(repo, "verify.yaml"), "w") as f:
            f.write(FIXTURE_VERIFY_YAML)
        integ = os.path.join(repo, "integration")
        os.makedirs(integ)
        with open(os.path.join(integ, "run_scenarios.py"), "w") as f:
            f.write(MINI_RUNNER)
    g("add", "-A")
    g("commit", "-qm", "init")
    return repo


def write_stub(tmp, tag="shared"):
    """落桩文件，返回 (stub_path, stub_log)。tag=每相独立账本——桩的判决序号按
    账本行数计数，跨相共享会串相（相二首判即读到相一的行数→回落 pass）。"""
    stub_path = os.path.join(tmp, "t09_stub-%s.py" % tag)
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(ARB_STUB)
    stub_log = os.path.join(tmp, "stub-%s.jsonl" % tag)
    return stub_path, stub_log


def arb_seq_env(env, seq):
    """在 worker 环境里注入判决序列（spawn_worker 会整体拷贝 env）。"""
    env = dict(env)
    env[ENV_ARB_SEQ] = ",".join(seq)
    return env


def fixture_mode_env(env, mode):
    env = dict(env)
    env[ENV_FIXTURE_MODE] = mode
    return env


def arb_rounds(stub_log):
    """arbitrate 边的判决调用次数（stub 账本行数口径，供 gens 断言）。"""
    n = 0
    try:
        with open(stub_log, encoding="utf-8") as f:
            for ln in f:
                if '"stage": "arbitrate"' in ln:
                    n += 1
    except FileNotFoundError:
        pass
    return n


def stages_seen(stub_log):
    """桩账本里出现过的段名集合（rework 重入证据：implement 在第 N 次 arbitrate
    之后再现＝真重入，非读陈旧快照）。"""
    out = []
    try:
        with open(stub_log, encoding="utf-8") as f:
            for ln in f:
                try:
                    row = json.loads(ln)
                except Exception:
                    continue
                if row.get("stage"):
                    out.append(str(row["stage"]))
    except FileNotFoundError:
        pass
    return out


def snap_text(snap):
    return json.dumps(snap or {}, ensure_ascii=False)


def handoff_text(snap):
    return json.dumps((snap or {}).get("handoffs") or [], ensure_ascii=False)


def kill_tree(worker):
    """worker 进程组全终态回收（同 sc_authz.kill_worker_tree：只碰自spawn的组）。"""
    import signal
    import time
    if worker is None or worker.poll() is not None:
        return
    try:
        os.killpg(worker.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        worker.wait(timeout=10)
    except Exception:  # noqa: BLE001 —— 兜底再 kill 一次，绝不干等
        try:
            worker.kill()
        except Exception:  # noqa: BLE001
            pass
    time.sleep(0.2)


def cleanup_tmp(tmp):
    import shutil
    import time
    last = ""
    for _ in range(5):
        try:
            shutil.rmtree(tmp)
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(1)
    print("  · 警告：tmp 未能回收（%s）：%s" % (last, tmp), flush=True)
    return False


def re_search_any(text, words):
    return any(w in (text or "") for w in words)
