#!/usr/bin/env python3
"""t260913-04 实现段 Step 6 驱动：F 成本腿（恒跑）+ A 真票端到端腿（门控）。

设计段把 A/F 判据钉死、留给实现段（见 `.sandbar/stage_design_integration_tests_gen0.json`
「A/F 判据钉死」节）。本脚本是那条判据的唯一落点，防落地时被削弱。

F（成本，验收 F）：
  基线=同宿主 host runtime 下 `dsh --profile sandbar-headless --version` 进程就绪耗时
       （N=3 取中位；另附 `--dump-config`（真装载 profile 栈）作参考口径）；
  被测=`ensure_container`（docker run -d 到就绪）+ 首 `docker exec … dsh --version`
       （N=3 取中位；每次冷起，先拆旧）；
  判定=被测 ≤ 基线×3 **且** ≤10s（两条臂各自出结论，不合并成一句「PASS」）。
  time.monotonic 三时点打点：ensure 起 / 容器就绪 / 首 exec 完成。

A（端到端，验收 A，门控 SANDBAR_E2E_REAL=1）：
  真票经**真引擎链**（测试台 Temporal 17233 + 本票专属 lane worker）：
    ① 前段用桩（`SANDBAR_AGENT_STUB=1`，秒级推进；桩只覆盖不验执行面的段）
    ② **暂停门**（`ticket op=pause`，t260908-01 正规通道）逐段停在段间门口，
       循环到「下一段=implement」为止——确保 implement 段**不会**被桩吃掉
    ③ 摘下桩、换 `SANDBAR_AGENT_RUNTIME=docker` 的真 worker，`resume` →
       implement 段由**真 agent 在容器里**跑完整一段（改文件 + 跑该票测试）
  断言：段内容器 `sandbar-agent-<票>` 真在场 / 结果文件落泳道原位形状不变（验收 D）/
  写集文件由容器内 agent 真写出且宿主可见（D1 同路径挂载）/ worker 代落盘 commit 含该
  文件（验收 A 收口）/ agent 日志含 docker spawn 行（可审计）/ 收尾零残留（验收 G）。
  模型成本=一个真 agent 段。

用法：
  python3 integration/t260913-04/run_real_ticket_e2e.py                # F 腿（默认，零模型成本）
  SANDBAR_E2E_REAL=1 python3 integration/t260913-04/run_real_ticket_e2e.py --leg a
出口码三态：0=PASS / 1=FAIL（产品红） / 2=ENV_FAIL（环境红，点名）。
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INTEG = REPO / "integration"
POC = REPO / "server" / "engine"
PROJ = "t26091304-e2e"
TID = "t260913-04-e2e"
WS_FILE = "E2E_PROBE_t260913_04.md"   # 写集禁含 notes/（宿主令 260904 机械闸）
SEG_TIMEOUT_SEC = int(os.environ.get("SANDBAR_E2E_SEG_TIMEOUT_SEC", "1800"))
N = 3

PASS = 0
FAIL = 0
ENV_FAIL = 0
NA = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label, flush=True)
    else:
        FAIL += 1
        print("  FAIL %s%s" % (label, ("  | " + str(detail)[:400]) if detail else ""), flush=True)


def na(label, why=""):
    global NA
    NA += 1
    print("  na   %s%s" % (label, ("  | " + str(why)[:300]) if why else ""), flush=True)


def env_fail(msg):
    global ENV_FAIL
    ENV_FAIL += 1
    print("  ENV_FAIL %s" % msg, flush=True)


def finish():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (PASS, FAIL, ENV_FAIL, NA),
          flush=True)
    return 1 if FAIL else (2 if ENV_FAIL else 0)


def med(xs):
    return statistics.median(xs)


def env_for(extra):
    """子进程 env：剥掉调用语境里的 SANDBAR_*（本脚本自身可能在泳道内被跑），
    只保留台面三键 + 显式 extra（抄 t260910-08 env_for 同款纪律）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SANDBAR_")}
    for k in ("SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE", "SANDBAR_PROJECTS_DIR"):
        if k in os.environ:
            env[k] = os.environ[k]
    env.update(extra)
    return env


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True)


# ---------------- F：成本腿 ----------------

def f_leg():
    print("\n== F 成本腿（验收 F）==", flush=True)
    sys.path.insert(0, str(POC))
    import agent_runtime as ar
    lane = Path(tempfile.mkdtemp(prefix="t26091304-f-leg-"))
    try:
        base, base_dump = [], []
        for _ in range(N):
            t0 = time.monotonic()
            p = subprocess.run(["dsh", "--profile", "sandbar-headless", "--version"],
                               capture_output=True, text=True, timeout=180)
            base.append(time.monotonic() - t0)
            if p.returncode != 0:
                env_fail("宿主 dsh 基线不可得：rc=%s %s" % (p.returncode, p.stderr[:160]))
                return
            t0 = time.monotonic()
            subprocess.run(["dsh", "--profile", "sandbar-headless", "--dump-config"],
                           capture_output=True, text=True, timeout=180)
            base_dump.append(time.monotonic() - t0)
        meas, pts = [], []
        for _ in range(N):
            ar.remove_container(TID)
            t0 = time.monotonic()
            name = ar.ensure_container(TID, lane)
            t1 = time.monotonic()
            r = subprocess.run([ar.docker_bin(), "exec", "-w", str(lane), name,
                                "dsh", "--version"], capture_output=True, text=True, timeout=180)
            t2 = time.monotonic()
            if r.returncode != 0:
                env_fail("容器内 dsh 不可得：rc=%s %s" % (r.returncode, r.stderr[:160]))
                return
            meas.append(t2 - t0)
            pts.append((t1 - t0, t2 - t1))
        print("  基线 dsh --version        N=%d median=%.3fs  %s"
              % (N, med(base), ["%.3f" % x for x in base]))
        print("  参考 dsh --dump-config    N=%d median=%.3fs  %s"
              % (N, med(base_dump), ["%.3f" % x for x in base_dump]))
        print("  被测 ensure+首 exec       N=%d median=%.3fs  %s"
              % (N, med(meas), ["%.3f" % x for x in meas]))
        print("  打点 ensure 段=%s 首 exec 段=%s"
              % (["%.3f" % a for a, _ in pts], ["%.3f" % b for _, b in pts]))
        ratio = med(meas) / med(base)
        print("  比值臂：%.2fx（判据 ≤3x）→ %s；绝对臂：%.3fs（判据 ≤10s）→ %s"
              % (ratio, "PASS" if ratio <= 3 else "FAIL",
                 med(meas), "PASS" if med(meas) <= 10 else "FAIL"))
        ok(med(meas) <= 10, "F 绝对臂：容器 ensure+首 exec ≤10s（起容器到 agent 可用=亚秒级）",
           "median=%.3fs" % med(meas))
        ok(ratio <= 3, "F 比值臂：被测 ≤ 宿主基线×3（R6 字面判据）",
           "ratio=%.2fx（基线 median=%.3fs=`dsh --version`：只打印版本、不装载 profile 栈）"
           % (ratio, med(base)))
    finally:
        try:
            import agent_runtime as ar2
            ar2.remove_container(TID)
        except Exception:
            pass
        shutil.rmtree(lane, ignore_errors=True)


# ---------------- A：真票端到端腿 ----------------

def build_project(tmp):
    """临时项目（单仓）：真 git 仓（有 HEAD）+ 写集目标位；票泳道落 <proj>/.lane/。"""
    proj = Path(tmp) / "proj"
    proj.mkdir(parents=True)
    (proj / "README.md").write_text("# e2e project\n", "utf-8")
    git("init", "-q", "-b", "main", cwd=proj)
    git("config", "user.email", "e2e@localhost", cwd=proj)
    git("config", "user.name", "e2e", cwd=proj)
    git("add", "-A", cwd=proj)
    git("commit", "-qm", "seed", cwd=proj)
    regroot = Path(tmp) / "reg"
    (regroot / PROJ).mkdir(parents=True)
    (regroot / PROJ / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: t260913-04 e2e\n    dirs:\n      - %s\n"
        % (PROJ, proj), "utf-8")
    return proj, regroot


def containers_for_ticket():
    p = subprocess.run(["docker", "ps", "-a", "--filter",
                        "label=sandbar.agent.ticket=%s" % TID, "--format", "{{.Names}}"],
                       capture_output=True, text=True, timeout=60)
    return [x for x in (p.stdout or "").split() if x]


def a_leg():
    print("\n== A 真票端到端腿（验收 A；前段桩 + 暂停门 + implement 段真 agent）==", flush=True)
    if os.environ.get("SANDBAR_E2E_REAL") != "1":
        env_fail("SANDBAR_E2E_REAL=1 未设——真模型腿按成本纪律门控")
        return
    if not (Path.home() / ".dsh" / ".credentials.yaml").exists():
        env_fail("凭据缺席（~/.dsh/.credentials.yaml）——真 agent 腿无法认证")
        return
    sys.path.insert(0, str(POC))
    import agent_runtime as ar
    if not ar._docker_present():
        env_fail("docker 不可用（容器执行面无法起）")
        return
    probe_lane = Path(tempfile.mkdtemp(prefix="t26091304-probe-"))
    try:
        ar.ensure_container(TID + "-probe", probe_lane)
        ar.remove_container(TID + "-probe")
    except ar.AgentRuntimeError as e:
        env_fail("镜像/容器面不可用：%s" % e)
        return
    finally:
        shutil.rmtree(probe_lane, ignore_errors=True)

    sys.path.insert(0, str(INTEG))
    sys.path.insert(0, str(INTEG / "t260904-02"))

    class _Fail:
        def bail(self, msg, code):
            env_fail(msg)
            raise SystemExit(2)

    from lib_gate import require_bench, require_stage, stage_down, run_poc_client

    tmp = tempfile.mkdtemp(prefix="t26091304-e2e-")
    worker = None
    stage = stage_mod = None
    saved = {}
    try:
        proj, regroot = build_project(tmp)
        bench = require_bench(_Fail())
        py = bench.poc_python()
        # 舞台名唯一（带 pid）：本机常有兄弟泳道的舞台在跑（实测 8 台），固定名会撞端口
        # 租约（21051「port is already allocated」实锤）；唯一名=各自独立档位，互不干扰。
        stage_proj = "%s-%d" % (PROJ, os.getpid())
        stage_mod, stage = require_stage(_Fail(), stage_proj, stage_proj)
        for k in ("SANDBAR_PROJECTS_DIR", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE"):
            saved[k] = os.environ.get(k)
        os.environ["SANDBAR_PROJECTS_DIR"] = str(regroot)
        os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
        os.environ["SANDBAR_NAMESPACE"] = stage["namespace"]
        import shared

        def cli(sub, args, timeout=180):
            _rc, out = run_poc_client(py, sub, args, env_for({}), timeout=timeout)
            s = out or ""
            i, j = s.find("{"), s.rfind("}")
            try:
                return json.loads(s[i:j + 1]) if i >= 0 and j > i else {}
            except Exception:  # noqa: BLE001
                return {}

        def snap():
            body = cli("ticket-query", {"ticket_id": TID})
            return (body.get("result") or {}).get("snapshot") or {}

        def pause(who="e2e"):
            return cli("ticket", {"op": "pause", "ticket_id": TID,
                                  "input": {"who": who, "note": "A 腿暂停门"}})

        def resume(who="e2e"):
            return cli("ticket", {"op": "resume", "ticket_id": TID,
                                  "input": {"who": who, "note": "A 腿放行"}})

        def wait(pred, deadline_s, label, poll=3.0):
            end = time.monotonic() + deadline_s
            last = {}
            while time.monotonic() < end:
                last = snap()
                if pred(last):
                    return last
                time.sleep(poll)
            print("  (%s 等待超时，末态=%s)" % (label, json.dumps(last)[:300]), flush=True)
            return None

        def start_worker(extra, logname):
            wenv = env_for({"SANDBAR_TASK_QUEUES": shared.ticket_task_queue(TID),
                            "SANDBAR_WATCH_WORKFLOW": TID,
                            "SANDBAR_WATCH_INTERVAL_SEC": "4",
                            **extra})
            log = open(Path(tmp) / logname, "w")
            return subprocess.Popen([py, str(POC / "worker.py")], env=wenv,
                                    stdout=log, stderr=subprocess.STDOUT)

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_t26091304_ticket", str(REPO / "server" / "tools" / "ticket.py"))
        tk = importlib.util.module_from_spec(spec)
        sys.modules["_t26091304_ticket"] = tk
        spec.loader.exec_module(tk)

        # ---- ① 先开票（此时无 worker：工作流不推进，桩吃不到 implement）----
        res = tk.run({"op": "create", "project": PROJ, "workflow": "dev-lane",
                      "title": "e2e 探针：写一行说明文件（无副作用）",
                      "write_set": [WS_FILE], "id": TID})
        ok(isinstance(res, dict) and res.get("id") == TID, "A1 真票受理（ticket.py create）",
           res if not isinstance(res, dict) else res.get("id"))
        lane = proj / shared.default_lane_paths(TID)[0]
        print("  泳道=%s" % lane, flush=True)

        # ---- ② 先武装暂停门，再起桩 worker：门在第一个 workflow task 即被处理，
        #          桩至多推一段就停在段间门口（确定性，不赌 stub 速度）----
        pause()
        worker = start_worker({"SANDBAR_AGENT_STUB": "1", "SANDBAR_SUGGEST_STUB": "ok",
                               "SANDBAR_UI_CAPTURE_STUB": "1"}, "worker-stub.log")
        s = wait(lambda x: x.get("paused") is True, 240, "first-pause")
        ok(s is not None, "A2 暂停门在桩链上确定性关合（implement 未被桩吃掉）",
           "paused=%s" % (s or {}).get("paused"))

        # ---- ③ 门口发 rework（暂停中压在门口不执行；恢复后先打回目标段）----
        rw = tk.run({"op": "rework", "id": TID, "to_stage": "implement",
                     "note": "t260913-04 A 腿：implement 段改由真 agent 在容器内跑",
                     "by": "e2e"})
        ok(isinstance(rw, dict), "A2b 门口注入 rework(to_stage=implement)（引擎正规通道）",
           str(rw)[:200])

        # ---- ④ 摘桩 → 换 docker runtime 真 worker → 放行门口 ----
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                worker.kill()
        before = set(p.name for p in (lane / ".sandbar").glob("stage_implement_gen*.json"))
        worker = start_worker({"SANDBAR_AGENT_RUNTIME": "docker"}, "worker-real.log")
        resume()

        seen_container = False
        new_result = None
        quota_hit = ""
        end = time.monotonic() + SEG_TIMEOUT_SEC
        while time.monotonic() < end:
            if containers_for_ticket():
                seen_container = True
            cand = sorted(set(p.name for p in (lane / ".sandbar").glob("stage_implement_gen*.json"))
                          - before)
            if cand:
                new_result = lane / ".sandbar" / cand[-1]
                break
            # 模型账户配额耗尽（429）＝环境红不是产品红：早停，不空等到段超时（实测：
            # 账户耗尽时 agent 每次模型调用都被拒，段永远不会产出结果文件）。
            for lf in sorted((lane / ".sandbar").glob("agent_implement_gen*.log")):
                try:
                    txt = lf.read_text("utf-8", errors="replace")
                except OSError:
                    continue
                if "QUOTA: 429" in txt or "Insufficient balance" in txt:
                    hits = [l for l in txt.splitlines()
                            if "QUOTA" in l or "Insufficient balance" in l]
                    quota_hit = hits[-1][:200] if hits else "429"
                    break
            if quota_hit:
                break
            time.sleep(3)
        if quota_hit:
            env_fail("模型账户配额耗尽（429）：%s —— 真 agent 段无法跑完，属环境红；"
                     "容器执行面本身已验通到「真 dsh 在容器内启动 + 会话恢复成功」"
                     % quota_hit)
        ok(seen_container, "A3 implement 段运行期容器 sandbar-agent-<票> 真在场（每票一容器）")
        if quota_hit:
            na("A4 结果文件落泳道原位（验收 D）", "配额 429，真段未产出结果文件")
            na("A5 写集文件宿主可见（D1）", "配额 429，真段未跑")
            na("A6 worker 代落盘 commit（验收 A 收口）", "配额 429，真段未跑")
            na("A7 worker 日志含容器 spawn 行", "配额 429，真段未跑")
            head = ""
        else:
            rf = json.loads(new_result.read_text("utf-8")) if new_result else None
            ok(bool(rf) and rf.get("status") == "ok",
               "A4 结果文件落泳道原位、形状不变（验收 D 读方零改动）",
               str(new_result) if rf is None else rf.get("status"))

            # ---- ④ 容器内真改文件 + worker 代落盘 ----
            target = lane / WS_FILE
            ok(target.is_file(),
               "A5 写集文件由容器内 agent 真写出、宿主可见（D1 同路径挂载）",
               target.read_text("utf-8", errors="replace")[:140] if target.is_file()
               else "缺 %s" % target)
            end = time.monotonic() + 420
            head = ""
            while time.monotonic() < end:
                head = git("log", "-1", "--format=%s", "--name-only", cwd=lane).stdout or ""
                if WS_FILE in head:
                    break
                time.sleep(5)
            ok(WS_FILE in head, "A6 worker 代落盘：泳道最近提交含写集文件（验收 A 收口）",
               head[:200])

        # ---- ⑤ 真链上的 spawn 落痕（runtime=docker 可审计）----
        # 落痕走 activity.logger → worker stdout（worker-real.log）；agent 转录里没有。
        if not quota_hit:
            wlog = Path(tmp) / "worker-real.log"
            text = wlog.read_text("utf-8", errors="replace") if wlog.is_file() else ""
            line = [ln for ln in text.splitlines()
                    if "docker 形态 spawn" in ln or "ensure+exec" in ln]
            ok(bool(line), "A7 worker 日志含容器 spawn 行（runtime=docker 落痕，可审计）",
               "\n".join(line)[:300])
            print("  [A] spawn 行：%s" % ("\n".join(line)[:400] or "(无)"), flush=True)
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.kill()
        for name in containers_for_ticket():
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        ok(not containers_for_ticket(), "A8 收尾零残留：本票容器清零（验收 G）")
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if stage is not None and stage_mod is not None:
            try:
                print("  stage_down: %s" % str(stage_down(stage_mod, stage_proj))[:200],
                      flush=True)
            except Exception as e:  # noqa: BLE001
                print("  (stage_down 容错：%s)" % str(e)[:120], flush=True)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", choices=("f", "a", "both"), default="f")
    args = ap.parse_args()
    if args.leg in ("f", "both"):
        f_leg()
    if args.leg in ("a", "both"):
        a_leg()
    return finish()


if __name__ == "__main__":
    sys.exit(main())
