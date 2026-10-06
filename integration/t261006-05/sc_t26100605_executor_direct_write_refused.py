#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-05 场景①：执行器直写账本被点名拒收（灰盒 L3，integration 岗）。

intent（登记于 run_scenarios.py SCENARIOS）——KI-208 事故旅程的引擎半面：
watchdog 代建的执行器会话（cwd 推导通道，真 dsh 注入链）调用
executor_requests.py 直写 ~/.sandbar/projects/<key>/requests.jsonl，沙箱一拒
就只剩「升权」一条路，而执行器部署形态没有审批应答者 ⇒ 永久停摆（261006
03:29 实证，4 小时）。修复定稿（常驻执行器通道直写收闸）下，本场景钉在
**真 CLI 子进程**这条公开缝上，断言只落在公开契约（退出码/结构化拒收/点名
文案/账本零副作用）：

- C1（主修，事故形态）：cwd 推导通道（注册项目目录作 cwd、无 caller_project
  env、会话 id 真注入）+ 合法请求体 → 拒收 rc=2、结构化回执（ok=false 带
  field/error），error 点名引擎侧投递面（client.py deliver）与「无审批应答
  者」事实；且**账本零写入**（拒收先于任何文件写入——拒收是具名错误，不是
  一次提问，执行器不会再撞出 approval/asked）。拒收必须有界（subprocess
  timeout），绝不挂起。
- C2（拒收排序）：cwd 通道 + 畸形体 → 同样是通道拒收并点名 deliver，不是体
  形状错误——执行器不该被引去修一个它根本不该发的体。
- C3（零回归红线控制，executor_grants 豁免档）：env 通道 + lane-agent 面
  （引擎 spawn 链的泳道 agent）→ 行为保持原样：合法体照常落账一行
  （surface=engine）——闸不许扩大。
- C4（出口可执行）：拒收 error 里出现可 greppable 的替代面指名
  （client.py deliver），执行器照着文案能换到活路。

intent 分工：拒收真值表/身份三关逐畸形矩阵归 developer L1（随实现交付，
server/engine/tests/test_t261004_23_executor_requests.py 延伸）；deliver 有界
等待与拒收分类归 t261004-44-deliver-bounded-refusal；liveness 观测面归
t261006-05-awaiting-approval-liveness。本条只钉「执行器形状的调用从此在
直写口拿到一条有界的、点名换路的拒收」这一旅程。

零 docker、零网络、零 3099；SANDBAR_PANEL_DIR/SANDBAR_PROJECTS_DIR 全部
钉进临时目录（KI-161：绝不写生产请求账）。引擎树缺席 = ENV_FAIL exit 2。
实现前 C1/C2/C4 红属预期（TDD 信号）；arbitrate/merge 必须绿。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    from lib_result import emit_case
    import shared as engine_shared
    import executor_requests as er
except Exception as e:
    print("ENV_FAIL: integration lib_result/engine shared import failed: %r" % (e,))
    sys.exit(2)

ENGINE_CLI = os.path.join(REPO, "server", "engine", "executor_requests.py")
if not os.path.isfile(ENGINE_CLI):
    print("ENV_FAIL: engine executor_requests.py missing at %s" % ENGINE_CLI)
    sys.exit(2)

SUITE = "t261006-05-executor-direct-write-refused"
SESSION = "sess-exec-sc05"
PROJECT_KEY = "proj-alpha"
BODY_LAWFUL = json.dumps({
    "op": "file", "project": PROJECT_KEY, "kind": "question",
    "question": "which delivery face should I use?",
    "detail": "evidence: sandbox denied the ledger append",
    "options": ["engine deliver", "keep direct"],
    "default_action": "engine deliver",
    "raised_by": SESSION,
})
BODY_MALFORMED = json.dumps({"op": "file", "project": PROJECT_KEY, "kind": 7})
FAILS = []


def _emit(case, ok, reason, evidence):
    emit_case(name=case, suite=SUITE, status=("pass" if ok else "fail"),
              cause="self", reason=reason, evidence=evidence)
    if not ok:
        FAILS.append(case)


def build_fixture(tmp):
    """Incident-shape fixture: a registered project whose main dir is the caller
    cwd (the only machine-observable seam a watchdog-created executor session
    has), a declaration naming the injected session id, all inside tmp."""
    workdir = tmp / "workdir"
    workdir.mkdir()
    reg_key = tmp / "reg" / PROJECT_KEY
    reg_key.mkdir(parents=True)
    (reg_key / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: sc05 fixture\n    dirs:\n      - %s\n"
        % (PROJECT_KEY, workdir))
    (reg_key / "executor-grants.json").write_text(json.dumps(
        {"version": 1, "grants": {}, "executor_sessions": [SESSION]}))
    return workdir


def run_cli(tmp, workdir, body, extra_env):
    env = dict(os.environ)
    env.update({
        "SANDBAR_PANEL_DIR": str(tmp),
        "SANDBAR_PROJECTS_DIR": str(tmp / "reg"),
        "DSH_SESSION_ID": SESSION,
        "DSH_HEADLESS_SESSION": "",
        engine_shared.CALLER_PROJECT_ENV: "",
        engine_shared.CALLER_IDENTITY_SRC_ENV: "",
        engine_shared.CALLER_SURFACE_ENV: "",
    })
    env.update(extra_env)
    try:
        p = subprocess.run(
            [sys.executable, ENGINE_CLI, body],
            capture_output=True, text=True, env=env, cwd=str(workdir), timeout=30)
        return {"rc": p.returncode, "out": p.stdout.strip(), "err": p.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"rc": "timeout", "out": "", "err": ""}


def ledger_rows(tmp):
    f = tmp / PROJECT_KEY / "requests.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def main():
    with tempfile.TemporaryDirectory(prefix="sandbar-sc05-") as td:
        tmp = Path(td)
        workdir = build_fixture(tmp)

        # C1 incident shape: cwd-derived resident-executor channel, lawful body ->
        # bounded named refusal pointing at the engine-side face, zero side effect.
        r = run_cli(tmp, workdir, BODY_LAWFUL, {})
        ev = "rc=%r out=%r err=%r" % (r["rc"], r["out"][:250], r["err"][:150])
        combined = r["out"] + r["err"]
        structured = r["rc"] == 2 and '"ok":false' in r["out"].replace(" ", "").lower()
        named = ("deliver" in combined) and ("client.py" in combined)
        bounded = r["rc"] != "timeout"
        _emit("C1-executor-direct-write-refused-bounded-named",
              structured and named and bounded,
              "cwd-channel file op must be a bounded rc=2 structured refusal naming client.py deliver",
              ev)
        _emit("C1b-ledger-zero-side-effect",
              len(ledger_rows(tmp)) == 0,
              "the refusal must precede any write (the park trigger removed at the source)",
              "rows_after=%d" % len(ledger_rows(tmp)))
        _emit("C1c-refusal-states-no-answerer-fact",
              ("answerer" in combined.lower()) or ("approval" in combined.lower()),
              "the refusal must state the no-answerer fact, not a bare refusal",
              combined[:300])

        # C2 refusal ordering: malformed body under the cwd channel -> the channel
        # refusal naming deliver, never a body-shape error.
        r2 = run_cli(tmp, workdir, BODY_MALFORMED, {})
        ev2 = "rc=%r out=%r" % (r2["rc"], r2["out"][:250])
        body_shape_err = ("question" in r2["out"]) and ("deliver" not in r2["out"])
        _emit("C2-channel-refusal-precedes-body-validation",
              r2["rc"] == 2 and "deliver" in r2["out"] and not body_shape_err,
              "channel refusal must win over body-shape validation",
              ev2)

        # C3 zero-regression control: the engine-side delivery face (the path the
        # refusal points to, client.py deliver -> executor_delivery, append performed
        # in the ENGINE process with delivered_via stamped) still appends for the
        # same resident-executor caller — the closure must close only the DIRECT write.
        er_out = er.append_request(json.loads(BODY_LAWFUL), 1000,
                                   env={"SANDBAR_PANEL_DIR": str(tmp),
                                        "DSH_SESSION_ID": SESSION,
                                        "DSH_HEADLESS_SESSION": "",
                                        engine_shared.CALLER_PROJECT_ENV: "",
                                        engine_shared.CALLER_IDENTITY_SRC_ENV: "",
                                        engine_shared.CALLER_SURFACE_ENV: ""},
                                   cwd=str(workdir),
                                   projects=[{"key": PROJECT_KEY, "dirs": [str(workdir)]}],
                                   exclude_trees=(), delivered_via="engine-process")
        rows = ledger_rows(tmp)
        stamped = [x for x in rows if x.get("delivered_via") == "engine-process"]
        _emit("C3-engine-delivery-face-still-appends",
              bool(er_out.get("ok")) and len(stamped) == 1,
              "the engine-performed delivery (delivered_via stamped) must keep appending for the same caller",
              "receipt_ok=%r rows=%d" % (er_out.get("ok"), len(rows)))

    if FAILS:
        print("SUMMARY: %s FAIL=%s" % (SUITE, ",".join(FAILS)))
        sys.exit(1)
    print("SUMMARY: %s all pass" % SUITE)


if __name__ == "__main__":
    main()
