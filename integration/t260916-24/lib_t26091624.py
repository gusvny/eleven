# -*- coding: utf-8 -*-
"""t260916-24 共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

两场景（sc_t260916_24_dsh_face_meta / sc_t260916_24_dsh_expected_loud）共用：
dsh 版本桩（--version 应答 + agent 回执 + 调用账本）、舞台 env 装配、worker 拉起、
meta 限期等待、JSONL 读取、进程收尾。真源票=t260916-24（dsh 升级 T4：版本钉路径
+ 探针对账），断言契约=run_scenarios.py 登记 intent + 方案 gen1（已过 integration
review，verdict=pass）。

红线纪律（沿 t260904-02 lib_gate / t260905-02 lib_t26090502 惯例）：
- 被测 worker/client 子进程一律 bench.audit_hook_env 审计钩子护体（连生产
  7233/8233=先记后抛），终局断言审计账本为空；
- 一切状态写临时目录；spawn 的进程收尾 TERM→KILL 兜底；
- 断言锚公开行为产物（meta JSON / worker 日志行 / 桩调用账本），日志锚不锁
  措辞、锚版本字面量与同现性（KI-051 教训）。
"""
import json
import os
import re
import subprocess
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "server", "engine")
WORKER_PY = os.path.join(ENGINE, "worker.py")

# 缺省 dsh 命令口径（agent_activities.py DSH_CMD 的文档化缺省；「缺省不破现状」
# 的对账锚——实现改缺省必须同步改这里，改动本身就是要人审的契约变化）。
DEFAULT_DSH_CMD_STR = "dsh --profile sandbar-headless"

# 桩自报的假版本（与真 dsh 版本 0.1.1-rc.2 可辨；expected 不符子用例用 0.1.1-rc.2）。
STUB_VERSION = "9.9.9-stub"

# dsh 版本桩（SANDBAR_AGENT_CMD 指向本脚本）：
# - `--version` 在 argv 任意位（引擎 face 探测形态）→ 打印假版本行退出；
# - agent 形态（引擎按 dsh CLI 组装：flag 在前、prompt 恒末位 argv）→ 调用落
#   账本（mode=agent）+ 按交付契约写回结果文件（status=ok；summary 无 verdict=
#   标记 → arbitrate 段会走引擎既有 blocked 路径，与本票断言无冲突）。
# 两种调用都记账（mode 区分），账本=「被钉二进制真的被调了」的机制证据。
STUB_SOURCE = r"""
import json, os, re, sys, time
argv = sys.argv[1:]
mode = "version" if ("--version" in argv) else "agent"
prompt = argv[-1] if argv else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
with open(os.environ["DSH_STUB_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"mode": mode, "stage": stage, "ts": time.time()},
                       ensure_ascii=False) + "\n")
if mode == "version":
    print("9.9.9-stub")
    sys.exit(0)
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    with open(m.group(1), "w", encoding="utf-8") as f:
        json.dump({"status": "ok", "summary": "[dsh-stub] %s 完成" % stage,
                   "report": "[dsh-stub] 桩回执（无 verdict 标记）",
                   "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
                   "files_changed_shape": "ok", "evidence": "dsh-stub"}, f,
                  ensure_ascii=False)
"""


def make_stub(tmp):
    """写版本桩到临时目录（自执行单 token——引擎 face 探测/spawn 都以 cmd[0] 为
    二进制：`<stub> --version`；shebang+chmod 让 SANDBAR_AGENT_CMD 直接指桩文件），
    返回 (stub_path, 账本路径)。调用方须在 worker env 里给 DSH_STUB_LOG=账本路径
    （桩两种调用都记账，缺 env 桩会 KeyError——探针得 error 而非版本）。"""
    stub = os.path.join(tmp, "dsh_stub.py")
    with open(stub, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env python3\n" + STUB_SOURCE)
    os.chmod(stub, 0o755)
    log = os.path.join(tmp, "dsh_stub_calls.jsonl")
    return stub, log


def stub_calls(log_path):
    """读桩调用账本（坏行跳过——账本是观测面不是被测契约）。"""
    rows = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return rows


def make_fixture_repo(tmp):
    """fixture 项目仓（沿 t260905-10 同款：git init + 身份 + 首 commit）。"""
    repo = os.path.join(tmp, "fixture-repo")
    os.makedirs(repo)

    def g(*a):
        subprocess.run(["git", "-C", repo] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("fixture\n")
    g("add", "-A")
    g("commit", "-qm", "init")
    return repo


def stage_env(state, registry_dir=None, audit_env=None, extra=None):
    """子进程 env：舞台 temporal/namespace 指路（+注册表/审计钩子/追加项）。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = state["namespace"]
    if registry_dir:
        env["SANDBAR_PROJECTS_DIR"] = registry_dir
    if audit_env:
        env.update(audit_env)
    env.update(extra or {})
    return env


def spawn_worker(py, env, log_path):
    """前台拉起 worker.py（stdout/stderr→日志文件：证据留档+语义等待面）。"""
    logf = open(log_path, "a", buffering=1)
    try:
        p = subprocess.Popen([py, WORKER_PY], cwd=ENGINE, env=env,
                             stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        logf.close()
        raise
    p._dsh_logf = logf
    return p


def close_worker_log(p):
    f = getattr(p, "_dsh_logf", None)
    if f is not None:
        try:
            f.close()
        except Exception:
            pass


def terminate_worker(p, timeout=15):
    """TERM→KILL 兜底收尾（资源回收纪律：正常/超时两终态都有归宿）。"""
    if p is None or p.poll() is not None:
        close_worker_log(p)
        return
    p.terminate()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=10)
    close_worker_log(p)


def wait_meta(meta_path, timeout_s=25.0, interval=0.3):
    """限期等归属 meta 落盘并可解析（返回 dict|None；坏 JSON 视为未就绪继续等）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            time.sleep(interval)
    return None


def poll(fn, timeout_s, interval=1.0):
    """限期轮询（fn()→真值即返回该值）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    return None


def read_tail(path, n=800):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except OSError:
        return "<log 不可读>"


def log_hits_literal_pair(log_path, literal_a, literal_b):
    """日志中「同一行同时含两个版本字面量」的行集（mismatch 响亮的点名锚：
    锚 actual/expected 字面量同现，不锁措辞——KI-051）。"""
    hits = []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if literal_a in ln and literal_b in ln:
                    hits.append(ln.rstrip())
    except OSError:
        pass
    return hits


def parse_json_loose(out):
    """宽松 JSON 提取（client 回执多行杂行——取首 { 到末 } 整段；沿 t260905-10）。"""
    s = out or ""
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return {}
