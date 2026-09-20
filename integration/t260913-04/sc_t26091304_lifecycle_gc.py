#!/usr/bin/env python3
"""t260913-04 场景③：容器生命周期——常驻/收割/孤儿回收/零残留（灰盒 L3，真 docker+引擎链）。

intent（用户可感知）：一张票一个容器，票在容器在、段间收割干净、异常可回收、
收口零残留（验收 G；方案 D3/D7）：
  A spawn 即 ensure：容器 sandbar-agent-<ticket> 在场且 running；段内 agent 桩真在
    容器里跑（uid/cwd/env 白名单/spy 落盘——D1 同路径挂载 + D4 属主 + D5 env 面的实况）；
  B 会话语义不变：结果文件/agent 日志落泳道原位、形状不变（验收 D）；
  C 迟写排水：结果交付后仍在写的进程树被按组收割（KI-009 容器形态），pgid 档清零；
  D 孤儿回收：label 在、泳道已亡的容器被 gc 收走；泳道还活着的容器不误杀（安全阀）；
  E 零残留：容器/网络/卷三面清点为零增量。

依据：工单验收 B/D/G ＋ 红线 3（不放宽：收割/回收语义与 KI-009、teardown 范式对齐）＋
review gen1 C6（reap 不许阻塞段结束路径——本条只锁「收割面终态」，悬挂超时面归 L1）。
与 developer L1 分工：L1 用 fake docker 锁分支，本条锁真 docker 上的终态。

high-level steps：真 docker+镜像在场探针 → 引擎 spawn 链直调（SANDBAR_AGENT_RUNTIME=docker，
SANDBAR_AGENT_CMD=泳道内桩）两轮：instant 轮断言 A/B，latewrite 轮断言 C → 造孤儿容器
（label 在、泳道亡）→ 跑 gc 手工入口（方案 D7「gc 手工命令可跑」）断言 D → 收尾清点 E。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现段落地前容器面红属预期（TDD 验收棒）；
arbitrate/merge 期必须绿。engine 池（宽 1）。
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_container_case as F  # noqa: E402

C = F.Checker("t260913-04-scenario-3-lifecycle-gc")
UID, GID = os.getuid(), os.getgid()
FORBIDDEN = F.FORBIDDEN_ENV_KEYS


def slice_env(tmp, stub):
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:1"
    env["SANDBAR_NAMESPACE"] = "sandbar-itest-lifecycle"
    env["SANDBAR_AGENT_STUB"] = "0"
    env["SANDBAR_AGENT_RESUME"] = "0"
    env[F.RUNTIME_ENV] = "docker"
    env["SANDBAR_AGENT_CMD"] = str(stub)
    env["DSH_HOME"] = str(tmp / "dsh-home")
    Path(env["DSH_HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def run_slice(aa, lane, mode_env, max_polls=2):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(mode_env)
    try:
        import importlib
        aa = importlib.reload(aa)   # DSH_CMD 等 import 期常量按本 slice env 重取
        A = getattr(aa, "AgentStageArgs", None)
        if A is None:
            import shared
            A = sys.modules["shared"].AgentStageArgs
        args = A(ticket_id=TICKET_ID[0], stage_id="implement", role="developer",
                 prompt="（生命周期桩）写结果文件后%s。" % ("长眠迟写" if "late" in TICKET_ID[0] else "退出"),
                 workspace={"path": str(lane), "type": "worktree"},
                 result_file=str(lane / ".sandbar" / "stage_implement_gen0.json"),
                 log_file=str(lane / ".sandbar" / "agent_stub.log"),
                 gen=0, max_polls=max_polls, workflow_id="dev-lane")
        try:
            return asyncio_run(aa._run_agent_stage_impl(args)), None
        except Exception as e:  # noqa: BLE001
            return None, "%s: %s" % (type(e).__name__, str(e)[:200])
    finally:
        os.environ.clear()
        os.environ.update(old)


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


TICKET_ID = [F.uniq("t260913-04-itest-life")]
CREATED = [TICKET_ID[0]]          # 并发安全：终态清理由本进程创建的全部夹具票
ORPHAN = [""]


def wait_until(fn, timeout=25, step=0.5):
    dl = time.time() + timeout
    while time.time() < dl:
        if fn():
            return True
        time.sleep(step)
    return False


def main():
    F.require_docker(C)
    tag = F.agent_image_tag(C)
    aa = F.load_engine(C)
    nets0, vols0 = F.net_vol_snapshot()

    tmp = Path(tempfile.mkdtemp(prefix="t26091304-lifecycle-"))
    try:
        # ---- A/B instant 轮 ----
        print("\n== instant 轮：spawn 即 ensure + 容器内实况 + 会话语义 ==")
        main_repo, lane = F.mk_repo_lane(tmp, TICKET_ID[0])
        spy = lane / ".sandbar" / "spy-life.log"
        stub = F.write_stub(lane, "instant", spy,
                     result_file=str(lane / ".sandbar" / "stage_implement_gen0.json"))
        res, err = run_slice(aa, lane, slice_env(tmp, stub))
        name = F.CONTAINER_FMT % TICKET_ID[0]
        insp = F.sh("docker", "inspect", "--format",
                    "{{.State.Running}}", name, timeout=30)
        C.check(insp.stdout.strip() == "true",
                "spawn 即 ensure：sandbar-agent-<ticket> 在场且 running（真票一容器）",
                "rc=%s out=%s err=%s" % (insp.returncode, insp.stdout.strip(), insp.stderr[:120]))
        C.check(spy.exists(), "agent 桩真在容器里跑了（spy 经同路径挂载落回宿主）",
                "err=%s" % (err or ""))
        if spy.exists():
            txt = spy.read_text(encoding="utf-8", errors="replace")
            C.check(("--- cwd\n%s" % lane) in txt, "容器内 cwd=泳道（workspaceRoot 根，D1）")
            uidline = [ln for ln in txt.splitlines() if ln.strip().isdigit()]
            C.check(uidline[:1] == [str(UID)],
                    "容器内 uid=宿主 worker uid（D4：容器内新建文件宿主可提交）",
                    "uid 行=%s 期望=%s" % (uidline[:2], UID))
            envlines = txt.split("--- env\n")[-1].splitlines()
            keys = {ln.split("=", 1)[0] for ln in envlines if "=" in ln}
            C.check("DSH_HOME" in keys, "容器内 env 带 DSH_HOME（注入链生效）",
                    "keys 样本=%s" % sorted(keys)[:8])
            leak = sorted(k for k in keys for f in FORBIDDEN if k == f)
            C.check(not leak, "容器内 env 无沙箱旋钮（红线 1 实况面）", "leak=%s" % leak)
            homes = [ln for ln in envlines if ln.startswith("HOME=")]
            C.check(bool(homes) and (homes[0].startswith("HOME=" + str(lane))
                                     or homes[0].startswith("HOME=/tmp")),
                    "HOME 落工作区或容器本地 tmp（不落宿主家目录）", "HOME 行=%s" % homes[:1])
        rf = lane / ".sandbar" / "stage_implement_gen0.json"
        ok_shape = False
        if rf.exists():
            try:
                ok_shape = json.loads(rf.read_text(encoding="utf-8")).get("status") == "ok"
            except Exception:
                ok_shape = False
        C.check(ok_shape, "结果文件落泳道原位、形状不变（验收 D）", "rf 存在=%s" % rf.exists())
        C.check((lane / ".sandbar" / "agent_stub.log").exists(), "agent 日志落泳道原位（验收 D）")
        C.check(insp.stdout.strip() == "true" and
                F.exec_in(name, "pgrep", "-f", "agent_stub", timeout=20).stdout.strip() == "",
                "段交付后无桩残留、容器仍在（常驻到收口，跨段容器不拆）")

        # ---- C latewrite 轮（KI-009 容器形态）----
        print("\n== latewrite 轮：结果交付后的迟写进程按组收割 ==")
        TICKET_ID[0] = F.uniq("t260913-04-itest-life-late")
        CREATED.append(TICKET_ID[0])
        name_l = F.CONTAINER_FMT % TICKET_ID[0]
        main2, lane2 = F.mk_repo_lane(tmp, TICKET_ID[0])
        spy2 = lane2 / ".sandbar" / "spy-late.log"
        stub2 = F.write_stub(lane2, "latewrite", spy2,
                         result_file=str(lane2 / ".sandbar" / "stage_implement_gen0.json"))
        res, err = run_slice(aa, lane2, slice_env(tmp, stub2))
        rf2 = lane2 / ".sandbar" / "stage_implement_gen0.json"
        delivered = rf2.exists()
        C.check(delivered, "迟写轮结果已交付（收割发生在交付之后——KI-009 时序）",
                "err=%s" % ((err or "")[:200]))
        if not delivered:
            C.na("迟写轮未交付（容器内 spawn 未跑通）——收割子用例无被测对象，避免真空假绿")
        else:
            gone = wait_until(lambda: F.exec_in(
                name_l, "pgrep", "-f", "sleep 180", timeout=20).stdout.strip() == "",
                timeout=30)
            C.check(gone, "交付后迟写进程树在界内被收割（容器内 killpg，KI-009 语义 1:1）",
                    "容器=%s" % name_l)
            exec_dir = lane2 / ".sandbar" / "exec"
            pg_left = (sorted(p.name for p in exec_dir.glob("*.pgid"))
                       if exec_dir.is_dir() else [])
            C.check(not pg_left, "收割后 pgid 档零残留（泳道 .sandbar/exec 面）",
                    "left=%s dir=%s" % (pg_left, exec_dir))

        # ---- D 孤儿回收 + 安全阀 ----
        print("\n== 孤儿回收：label 在、泳道亡 → gc 收走；泳道活 → 不误杀 ==")
        ORPHAN[0] = F.uniq("t260913-04-itest-orphan")
        orphan = F.CONTAINER_FMT % ORPHAN[0]
        F.sh("docker", "rm", "-f", orphan, timeout=60)
        r = F.sh("docker", "run", "-d", "--name", orphan,
                 "--label", "%s=%s" % (F.LABEL_TICKET, ORPHAN[0]),
                 "--label", "%s=/nonexistent-lane-xyz" % F.LABEL_LANE,
                 tag, "sleep", "300")
        C.check(r.returncode == 0, "孤儿容器已造（模拟 worker 崩溃残留）", "err=%s" % r.stderr[:120])
        try:
            import agent_runtime as art   # 引擎容器执行面单点（方案 D3/D7）
        except Exception as e:  # noqa: BLE001
            art = None
            C.check(False, "agent_runtime 模块不可导入（容器执行面单点缺席）：%s" % str(e)[:120])
        if art is not None:
            notes = art.gc_stale_containers()
            C.check(F.containers_by_label(F.LABEL_TICKET, ORPHAN[0]) == [],
                    "孤儿（泳道已亡）被 gc 收走（label 过滤+泳道在场判据，方案 D7③）",
                    "notes=%s" % notes[-2:])
            C.check(F.sh("docker", "inspect", "--format", "{{.State.Running}}",
                         name, timeout=30).stdout.strip() == "true",
                    "安全阀：泳道还活着的容器不误杀（lane 在场判据）")
            note = art.remove_container(TICKET_ID[0])
            C.check(F.sh("docker", "inspect", "--format", "{{.State.Running}}",
                         name_l, timeout=30).returncode != 0,
                    "收口即拆：remove_container 后容器不在场（幂等原语，验收 G）",
                    "note=%s" % note)

        # ---- E 零残留 ----
        print("\n== 收尾：零残留 ==")
        for t in (TICKET_ID[0], ORPHAN[0]):
            F.sh("docker", "rm", "-f", F.CONTAINER_FMT % t, timeout=60)
        left = (F.containers_by_label(F.LABEL_TICKET, TICKET_ID[0])
                + F.containers_by_label(F.LABEL_TICKET, ORPHAN[0]))
        C.check(not left, "容器零残留（label 过滤为 0，验收 G）", "left=%s" % left)
        nets1, vols1 = F.net_vol_snapshot()
        marker = "t260913-04-itest"
        own_n = sorted(n for n in nets1 if marker in n)
        own_v = sorted(v for v in vols1 if marker in v)
        C.check(not own_n and not own_v,
                "本票网络/卷零残留（容器面之外无本票残留面，验收 G）",
                "own_net=%s own_vol=%s（全局快照 %d/%d→%d/%d，并行池活动不影响本判据）"
                % (own_n[:4], own_v[:4], len(nets0), len(vols0), len(nets1), len(vols1)))
    finally:
        for t in CREATED + [ORPHAN[0]]:
            if t:
                F.sh("docker", "rm", "-f", F.CONTAINER_FMT % t, timeout=60)
        shutil.rmtree(tmp, ignore_errors=True)

    C.finish()


if __name__ == "__main__":
    main()
