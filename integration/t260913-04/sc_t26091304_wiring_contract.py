#!/usr/bin/env python3
"""t260913-04 场景①：agent 执行面容器化的引擎接线契约（灰盒 L2/L3，hermetic）。

intent（用户可感知）：引擎起 agent 的路径在 docker 形态下必须把「容器看到的世界」
钉死在该票泳道——红线 1/2 的机械面：
  A 挂载面＝恰好该票泳道一项（无主树、无 ~/.dsh 全量、无 docker.sock、无其他票路径）；
  B env 面＝白名单（DSH_HOME/DSH_HEADLESS_SESSION/TERM/…），沙箱旋钮
    （DSH_PERMISSION_MODE 等）结构性禁入；
  C user 面＝--user <宿主worker uid>:<gid>（容器内新建文件宿主 worker 可提交，验收 D）；
  D 无特权面＝无 --privileged/--cap-add/--pid=host/--network=host；
  E sandbox_pin 一次性 patch＝字面量 mode:'danger-full-access' + permission
    defaultPreset:'danger-full-access'（宿主 260914 A 案：容器内全权、隔离由挂载面
    承担；字面量仍封「模式被 env/profile 篡改」面；缺 defaultPreset 时 dsh boot
    拒启——合成缺省不匹配任何预设）+ bash-sandbox 900000（D8，仅 docker 形态）；
  F 收割链＝容器内 sandbar-exec supervisor + 按组 kill 协议（D3，KI-009 语义 1:1）；
  G host 冻结＝缺省（不设旋钮）形态零 docker 调用、agent 直接宿主直跑、结果文件/日志
    形状不变、无 pin 文件（红线 3/4：存量语义零漂移）；
  H 生产接线棒＝run_worker.sh 显式 export SANDBAR_AGENT_RUNTIME=docker（缺它本票不交付）。

依据：工单验收 B/C/D/G ＋ 红线 1/2/3/4 ＋ 方案 gen1 D3/D4/D5/D6/D8（review gen1 C4 白名单
等值断言收编）。与 developer L1（fake-docker 单测）intent 分工：本条锁「真引擎 spawn 链
传给 docker 的完整 argv 契约」，L1 锁函数级分支。

high-level steps：tmp 主仓+真注册泳道 → SANDBAR_AGENT_RUNTIME=docker +
SANDBAR_DOCKER_BIN=fake 桩（只记录 argv）+ SANDBAR_AGENT_CMD=泳道内 spy 桩 → 直调
_run_agent_stage_impl（max_polls 小、超时路径有界）→ 断言记录里的 run/exec/kill argv 契约；
换 host 缺省形态重跑同一片 → 断言零 docker 调用 + 桩宿主直跑 + 结果形状不变。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现段落地前 A–F 红属预期（TDD 验收棒），
G/H 同期应绿（冻结面）；arbitrate/merge 期必须全绿。
"""
import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_container_case as F  # noqa: E402

C = F.Checker("t260913-04-scenario-1-wiring-contract")
TICKET = "t260913-04-itest-wiring"
UID, GID = os.getuid(), os.getgid()


def slice_env(tmp, runtime, fake, stub):
    """受控 env：黑掉 Temporal 目标（_fetch_ticket_project 软降级，绝不碰 7233 生产）、
    压掉桩模式、给 docker 旋钮。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:1"          # 连接拒绝即软降级 project=""
    env["SANDBAR_NAMESPACE"] = "sandbar-itest-wiring"
    env["SANDBAR_AGENT_STUB"] = "0"                      # 压掉引擎桩模式（要真走 spawn 链）
    env["SANDBAR_AGENT_RESUME"] = "0"
    env["SANDBAR_AGENT_CMD"] = str(stub)
    env["DSH_HOME"] = str(tmp / "dsh-home")              # 空 home：profile/凭据拷贝软跳过
    (tmp / "dsh-home").mkdir(parents=True, exist_ok=True)
    if runtime:
        env[F.RUNTIME_ENV] = runtime
    else:
        env.pop(F.RUNTIME_ENV, None)
    if fake:
        env[F.DOCKER_BIN_ENV] = str(fake)
    else:
        env.pop(F.DOCKER_BIN_ENV, None)
    return env


def run_slice(aa, lane, mode_env):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(mode_env)
    try:
        import importlib
        aa = importlib.reload(aa)   # DSH_CMD 等 import 期常量按本 slice env 重取
        A = getattr(aa, "AgentStageArgs", None)
        if A is None:
            import shared  # noqa: F401
            A = sys.modules["shared"].AgentStageArgs
        args = A(ticket_id=TICKET, stage_id="implement", role="developer",
                 prompt="（场景桩任务）结果文件写到指定路径后结束。",
                 workspace={"path": str(lane), "type": "worktree"},
                 result_file=str(lane / ".sandbar" / "stage_implement_gen0.json"),
                 log_file=str(lane / ".sandbar" / "agent_stub.log"),
                 gen=0, max_polls=2, workflow_id="dev-lane")
        try:
            res = asyncio.run(aa._run_agent_stage_impl(args))
            return res, None
        except Exception as e:  # noqa: BLE001
            return None, "%s: %s" % (type(e).__name__, str(e)[:220])
    finally:
        os.environ.clear()
        os.environ.update(old)


def find_pin(lane):
    d = lane / ".sandbar"
    if not d.is_dir():
        return None
    hits = sorted(d.glob(F.PIN_GLOB))
    return hits[0] if hits else None


def main():
    aa = F.load_engine(C)

    # ---------------- docker 形态：argv 契约 ----------------
    print("\n== docker 形态：传给 docker 的 argv 契约（红线 1/2 机械面）==")
    tmp = Path(tempfile.mkdtemp(prefix="t26091304-wiring-"))
    try:
        main_repo, lane = F.mk_repo_lane(tmp, TICKET)
        fake, log = F.make_fake_docker(tmp)
        spy = lane / ".sandbar" / "spy-docker.log"
        stub = F.write_stub(lane, "instant", spy,
                     result_file=str(lane / ".sandbar" / "stage_implement_gen0.json"))
        res, err = run_slice(aa, lane, slice_env(tmp, "docker", fake, stub))
        entries = F.read_log(log)
        # run 记录二分类取样（t260921-14 起 docker 流里多了一类观测 run）：worker
        # spawn 面（sandbar-agent-<ticket>，本节 argv 契约的对象）与三面自检探针面
        # （sandbar-dsh-probe-*，prepare 阶段落账、先于 spawn）。混采会把探针记录
        # 误当 spawn 契约面判（t260921-14 仲裁实证的假红根因）；契约断言只咬
        # worker 类，探针类另立形状锚，两类之外不许有匿名 run。
        worker_name = F.CONTAINER_FMT % TICKET
        run_e = [e for e in entries if e.split(" ")[:1] == ["run"]
                 and worker_name in e.split(" ")]
        probe_e = [e for e in entries if e.split(" ")[:1] == ["run"]
                   and any(t.startswith("sandbar-dsh-probe-") for t in e.split(" "))]
        other_run = [e for e in entries if e.split(" ")[:1] == ["run"]
                     and e not in run_e and e not in probe_e]
        exec_e = [e for e in entries if e.split(" ")[:1] == ["exec"]]
        C.check(bool(entries), "docker 桩被调用（执行面已接线，SANDBAR_AGENT_RUNTIME 消费）",
                "log=%s | slice err=%s" % (entries[:3], (err or "无")[:200]))
        C.check(not other_run, "run 记录二分类完备（worker/探针外无匿名 run）",
                "other=%s" % [e[:120] for e in other_run[:2]])
        C.check(bool(run_e), "worker spawn run 在账（sandbar-agent-<ticket>，每票一容器创建面）",
                "entries=%d run_all=%d worker=%d probe=%d"
                % (len(entries), len(run_e) + len(probe_e) + len(other_run),
                   len(run_e), len(probe_e)))
        if run_e:
            tok = run_e[0].split(" ")
            C.check(F.CONTAINER_FMT % TICKET in tok, "容器名=sandbar-agent-<ticket>（确定性票锚）",
                    "tok=%s" % tok[:8])
            C.check(("label=%s=%s" % (F.LABEL_TICKET, TICKET)) in tok
                    or ("%s=%s" % (F.LABEL_TICKET, TICKET)) in tok,
                    "label 锚票（gc/零残留的过滤面）", "tok=%s" % [t for t in tok if "sandbar." in t])
            binds = F.bind_sources(tok)
            C.check(any(b == str(lane) for b in binds),
                    "挂载面含该票泳道（同路径挂载）", "binds=%s" % binds)
            C.check(all(b == str(lane) or str(lane) in b for b in binds),
                    "挂载面=仅泳道（红线 2：无主树/~/.dsh 全量/他票路径）", "binds=%s" % binds)
            C.check(not any(F.DOCKER_SOCK in t for t in tok), "无 docker.sock 进容器")
            bad = [t for t in tok if t in ("--privileged", "--cap-add", "--pid=host",
                                           "--network=host", "--userns=host")]
            C.check(not bad, "无特权面（无 privileged/cap-add/pid=host/network=host）", "bad=%s" % bad)
            ui = [i for i, t in enumerate(tok) if t in ("--user", "-u")]
            C.check(bool(ui) and ui[0] + 1 < len(tok)
                    and tok[ui[0] + 1] == "%d:%d" % (UID, GID),
                    "user 面=宿主 worker uid:gid（容器内新建文件宿主可提交，验收 D）",
                    "tok=%s" % ([tok[ui[0]:ui[0] + 2]] if ui else [])[:1])
        C.check(all("--rm" in e.split(" ") for e in probe_e)
                and all(not F.bind_sources(e.split(" ")) for e in probe_e),
                "探针 run 恒 --rm 自清且零挂载（观测面零残留、不碰泳道，t260921-14 面）",
                "probe_n=%d 样例=%s" % (len(probe_e), [e[:120] for e in probe_e[:1]]))
        C.check(bool(exec_e), "exec 调用在记录里（每段 docker exec 面）", "exec_n=%d" % len(exec_e))
        if exec_e:
            tok = exec_e[0].split(" ")
            wi = [i for i, t in enumerate(tok) if t == "-w"]
            C.check(bool(wi) and wi[0] + 1 < len(tok) and tok[wi[0] + 1] == str(lane),
                    "exec cwd=泳道（sandbox-policy.workspaceRoot=process.cwd() 的根）",
                    "tok=%s" % tok[:8])
            envs = F.env_assignments(tok)
            C.check(any(e.startswith("DSH_HOME=") for e in envs), "env 白名单带 DSH_HOME",
                    "envs=%s" % envs)
            keys = {e.split("=", 1)[0] for e in envs}
            C.check(keys <= {"DSH_HOME", "HOME", "TMPDIR", "DSH_HEADLESS_SESSION"},
                    "exec env 键集⊆白名单∪容器本地 HOME/TMPDIR（白名单等值：多一个键都算泄）",
                    "keys=%s" % sorted(keys))
            C.check("HOME=/tmp/agent-home" in envs and "TMPDIR=/tmp" in envs,
                    "容器本地 HOME/TMPDIR（review C4：不落宿主家目录）", "envs=%s" % sorted(set(envs)))
            leak = [e for e in envs for k in F.FORBIDDEN_ENV_KEYS
                    if e.split("=", 1)[0] == k]
            C.check(not leak, "沙箱旋钮结构性禁入（红线 1：env 面无 DSH_PERMISSION_MODE 族）",
                    "leak=%s" % leak)
            C.check(any("sandbar-exec" in t for t in tok),
                    "容器内 supervisor sandbar-exec 在调用链（pgid 协议前提，D3）",
                    "tok=%s" % tok[-4:])
            C.check(any("agent_stub.sh" in t for t in tok),
                    "agent 命令透传（cmd[0]=SANDBAR_AGENT_CMD 桩，容器内可寻址）",
                    "tok=%s" % tok[-6:])
        pin = find_pin(lane)
        C.check(pin is not None, "sandbox_pin 一次性 patch 落泳道 artifacts（D5/D8）",
                "pin=%s" % pin)
        if pin is not None:
            text = pin.read_text(encoding="utf-8")
            import re as _re
            C.check(bool(_re.search(r"id:\s*sandbox-policy", text))
                    and bool(_re.search(r"mode:\s*'danger-full-access'", text))
                    and bool(_re.search(r"id:\s*permission", text))
                    and bool(_re.search(r"defaultPreset:\s*'danger-full-access'", text))
                    and "workspaceRoot" in text
                    and not _re.search(r"mode:\s*['\"]?workspace-write", text)
                    and not _re.search(r"mode:\s*process\.env", text),
                    "pin 用字面量钉死 danger-full-access + defaultPreset=danger-full-access"
                    "+workspaceRoot（宿主 A 案：容器内全权、隔离靠挂载面；字面量封 env/篡改"
                    "面；defaultPreset 缺位时 dsh boot 拒启——合成缺省不匹配任何预设）",
                    "text=%s" % text[:240])
            C.check("bash-sandbox" in text and "900000" in text,
                    "pin 覆盖 bash-sandbox 超时=900000（D8，>60s 分钟级命令面）",
                    "text=%s" % text[:160])
            if exec_e:
                C.check(any(str(pin) in e for e in exec_e),
                        "exec argv 引用 pin patch（--patch 链生效位）")

        # ---------------- host 缺省形态：冻结面（红线 3/4）----------------
        print("\n== host 缺省形态：零 docker 化 + 存量语义冻结（红线 3/4）==")
        tmp2 = Path(tempfile.mkdtemp(prefix="t26091304-hostfreeze-"))
        try:
            main2, lane2 = F.mk_repo_lane(tmp2, TICKET + "-host")
            fake2, log2 = F.make_fake_docker(tmp2)
            spy2 = lane2 / ".sandbar" / "spy-host.log"
            stub2 = F.write_stub(lane2, "instant", spy2,
                         result_file=str(lane2 / ".sandbar" / "stage_implement_gen0.json"))
            res, err = run_slice(aa, lane2, slice_env(tmp2, None, fake2, stub2))
            C.check(F.read_log(log2) == [], "缺省形态零 docker 调用（不设旋钮=今日行为）",
                    "log=%s" % F.read_log(log2)[:3])
            C.check(spy2.exists(), "agent 桩宿主直跑（spy 落盘）",
                    "slice err=%s" % (err or "无")[:200])
            rf = lane2 / ".sandbar" / "stage_implement_gen0.json"
            ok_shape = False
            if rf.exists():
                try:
                    raw = json.loads(rf.read_text(encoding="utf-8"))
                    ok_shape = raw.get("status") == "ok" and "summary" in raw
                except Exception:
                    ok_shape = False
            C.check(ok_shape, "结果文件位置与形状与今日一致（验收 D 读方零改动）",
                    "rf=%s | slice err=%s" % (rf.read_text(encoding="utf-8")[:120]
                                              if rf.exists() else "缺", (err or "无")[:160]))
            C.check(find_pin(lane2) is None, "host 形态不写 sandbox_pin（D8 作用域=仅 docker）")
            try:
                leftovers = F.containers_by_label(F.LABEL_TICKET, TICKET + "-host")
                C.check(not leftovers, "host 形态零容器残留")
            except Exception as e:  # noqa: BLE001
                C.na("docker 查询不可用（%s）" % str(e)[:80])
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- 生产接线棒 ----------------
    print("\n== 生产接线棒 ==")
    wsh = F.REPO / F.WORKER_SH
    wtxt = wsh.read_text(encoding="utf-8") if wsh.exists() else ""
    C.check(F.RUNTIME_ENV + "=docker" in wtxt,
            "run_worker.sh 显式 export SANDBAR_AGENT_RUNTIME=docker（生产接线，缺=本票不交付）",
            "run_worker.sh=%s" % wtxt[-160:])

    C.finish()


if __name__ == "__main__":
    main()
