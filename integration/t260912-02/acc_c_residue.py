#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 验收 C：注入三残台形态全拆（容器+网络+卷）+ 逐条点名；两对照原封
不动；γ 负锁（C4b：活台+owner 目录在+心跳新鲜+非工作树 → 不拆只报告）。

真 docker 面：判拆项的容器/网络/卷用真 compose label 预造（停止态），拆后必须
全部消失；对照项同款预造，拆后必须原样健在（误拆在容器级可判，不只看租约）。
隔离锁根（注入租约不与生产混跑）；对照 α/β/γ 的 holder=独立 sleep 进程。
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration", "t260910-12"))
from lib_herd_case import (  # noqa: E402
    check, cli, docker_present, envfail, finish, guarded_down, stage_tag,
)

TAG = stage_tag("t26091202-c")
ROOT = "/tmp/sandbar-t26091202-c"
ENV = {"SANDBAR_STAGE_LOCK_DIR": ROOT}
NET = os.path.join(ROOT, "net")          # 承载「已删工作目录」的父目录
C4B_DIR = os.path.join(ROOT, "c4b-owner")  # 在、但非工作树（γ 与…共用形态）


def sleeper():
    return subprocess.Popen(["/bin/sleep", "600"]).pid


def main():
    if not docker_present():
        envfail("docker 缺席——残台清理注入面不可验")
        finish()
    os.makedirs(ROOT, exist_ok=True)
    os.makedirs(NET, exist_ok=True)
    os.makedirs(C4B_DIR, exist_ok=True)
    # 锁根纪律（acc_d 同款教训）：sd 原语按**进程 env**解析锁根——必须在进程级
    # 设隔离根，租约才写得进注入面；子进程经 ENV 再设一遍（双保险，非幂等源）。
    os.environ["SANDBAR_STAGE_LOCK_DIR"] = ROOT
    holders = []
    try:
        sys.path.insert(0, os.path.join(REPO, "integration"))
        import stage_docker as sd
        now = time.time()

        def write(project, state, hb_age, holder_pid, owner, drop_owner=False):
            lease = sd.new_lease(project, holder_pid=holder_pid, services=["temporal"], ttl=90)
            lease.update({"state": state, "heartbeat_ts": now - hb_age})
            if owner is not None:
                lease["owner_root"] = owner
            if drop_owner:
                del lease["owner_root"]      # 旧格式：无 owner_root（repo_dir 回落）
            sd.write_lease(project, lease)

        gone_dir = os.path.join(NET, "doomed-lane")
        os.makedirs(gone_dir)
        res_i_holder = sleeper(); holders.append(res_i_holder)   # holder 活、心跳新鲜——仍拆
        write("%s-i" % TAG, "up", 1, res_i_holder, gone_dir)
        shutil.rmtree(gone_dir)                                   # (i) 工作目录已删
        # (ii) 泳道已从 worktree list 移除：目录在、非工作树、holder 死
        res_ii_holder = 999999
        write("%s-ii" % TAG, "up", 1, res_ii_holder, C4B_DIR)
        # (iii) 心跳陈旧超阈（锚 legacy 缺省 repo_dir 亦不影响——crit_iii 直判）
        write("%s-iii" % TAG, "up", 6000, 999999, None, drop_owner=True)
        # 对照 α：booting+心跳新鲜（阀1）
        a_holder = sleeper(); holders.append(a_holder)
        write("%s-alpha" % TAG, "booting", 1, a_holder, C4B_DIR)
        # 对照 β：owner=本仓（在 git worktree list）+ 新鲜闲置（阀2）
        b_holder = sleeper(); holders.append(b_holder)
        write("%s-beta" % TAG, "up", 1, b_holder, REPO)
        # γ 负锁（C4b）：活台+目录在+新鲜+非工作树 → 只报告
        g_holder = sleeper(); holders.append(g_holder)
        write("%s-gamma" % TAG, "up", 1, g_holder, C4B_DIR)

        # 真容器面：判拆 3 项 + 对照 3 项各起一个真 compose 台（temporal-only，
        # 唯一端口/网段）——判拆项=「容器在跑+主人已死」的真实 260912 形态，拆后
        # 容器+网络+卷必须消失；对照项 sweep 后必须原样健在（误拆容器级可判）。
        COMPOSE = os.path.join(REPO, "server", "docker-compose.test.yml")

        def fabricate(project, idx):
            env = dict(os.environ)
            env.update({
                "SANDBAR_TEST_TEMPORAL_PORT": str(31210 + idx * 10),
                "SANDBAR_TEST_TEMPORAL_UI_PORT": str(31211 + idx * 10),
                "SANDBAR_TEST_TEMPORAL_NAME": "%s-temporal" % project,
                "SANDBAR_TEST_DSH_NAME": "%s-dsh" % project,
                "SANDBAR_TEST_NAMESPACE": "ns-%s" % project,
                # 受管表内非保留槽（idx+200 → 10.213.200-205.0/24），down 自拆
                "SANDBAR_TEST_SUBNET": "10.213.%d.0/24" % (200 + idx),
            })
            p = subprocess.run(
                ["docker", "compose", "-f", COMPOSE, "-p", project,
                 "up", "-d", "--quiet-pull", "--no-deps", "temporal"],
                capture_output=True, text=True, timeout=180, env=env, cwd=REPO)
            if p.returncode != 0:
                envfail("预制 compose 台失败（%s）：%s" % (project, p.stderr[-200:]))

        doomed = ["%s-i" % TAG, "%s-ii" % TAG, "%s-iii" % TAG]
        controls = ["%s-alpha" % TAG, "%s-beta" % TAG, "%s-gamma" % TAG]
        for i, p in enumerate(doomed + controls):
            fabricate(p, i)

        out = cli("sweep", env_extra=ENV, timeout=300)
        check(out.returncode == 0, "sweep rc=0（rc=%s）%s"
              % (out.returncode, " ".join((out.stderr or "").split())[:160]))
        import json as _json
        rpt = _json.loads((out.stdout or "").strip().splitlines()[-1])
        check(rpt.get("scanned") == 6, "sweep 扫到 6 条注入租约（实得 %s——写错锁根会得 0）"
              % rpt.get("scanned"))
        cond = {c["project"]: c["why"] for c in rpt["condemned"]}
        kept = {c["project"]: c["why"] for c in rpt["kept"]}
        rep = {c["project"]: c["why"] for c in rpt["report_only"]}
        check(set(doomed) <= set(cond), "三残台全判拆（点名=%s）" % sorted(cond))
        check("crit_i" in cond.get("%s-i" % TAG, ""), "形态(i) 判据=crit_i：%s"
              % cond.get("%s-i" % TAG, ""))
        check("crit_ii" in cond.get("%s-ii" % TAG, ""), "形态(ii) 判据=crit_ii：%s"
              % cond.get("%s-ii" % TAG, ""))
        check("crit_iii" in cond.get("%s-iii" % TAG, ""), "形态(iii) 判据=crit_iii：%s"
              % cond.get("%s-iii" % TAG, ""))
        check("%s-alpha" % TAG in kept, "对照 α（booting 新鲜）原封不动：%s"
              % kept.get("%s-alpha" % TAG, ""))
        check("%s-beta" % TAG in kept, "对照 β（在册泳道）原封不动：%s"
              % kept.get("%s-beta" % TAG, ""))
        check("%s-gamma" % TAG in rep and "C4b" in rep.get("%s-gamma" % TAG, ""),
              "γ 负锁（C4b）只报告不拆：%s" % rep.get("%s-gamma" % TAG, ""))
        for line in (out.stdout or "").splitlines() + (out.stderr or "").splitlines():
            if line.startswith("[stage-sweep]") and "判拆 3" in line:
                check(True, "sweep 输出点名判拆 3 条：%s" % line)
                break
        else:
            check(False, "sweep 输出点名判拆 3 条（stdout 未见计数行）")

        # 容器面终局：判拆三项的容器/网络/卷全消失；对照三项全健在
        def objects(project):
            kinds = {}
            kinds["container"] = subprocess.run(
                ["docker", "ps", "-a", "--filter", "name=^%s-temporal" % project,
                 "--format", "{{.ID}}"], capture_output=True, text=True, timeout=15).stdout.split()
            kinds["network"] = subprocess.run(
                ["docker", "network", "ls", "--filter", "name=^%s_default$" % project,
                 "--format", "{{.ID}}"], capture_output=True, text=True, timeout=15).stdout.split()
            kinds["volume"] = subprocess.run(
                ["docker", "volume", "ls", "--filter", "name=^%s_temporal-data$" % project,
                 "--format", "{{.Name}}"], capture_output=True, text=True, timeout=15).stdout.split()
            return kinds
        for p in doomed:
            left = {k: v for k, v in objects(p).items() if v}
            check(not left, "%s 容器+网络+卷全拆（剩 %s）" % (p, left or "无"))
        for p in controls:
            left = {k: v for k, v in objects(p).items() if not v}
            check(not left, "%s 对照对象零误拆（缺 %s）" % (p, left or "无"))
        for p in controls:
            import json as _j
            lp = os.path.join(ROOT, "project-%s.json" % p)
            check(os.path.exists(lp), "%s 租约原封不动" % p)
    finally:
        # 现场清场：对照 compose 台兜底拆、租约清、holder 收割（G 口径自查）
        try:
            COMPOSE = os.path.join(REPO, "server", "docker-compose.test.yml")
            for s in ("alpha", "beta", "gamma", "i", "ii", "iii"):
                proj = "%s-%s" % (TAG, s)
                subprocess.run(["docker", "compose", "-f", COMPOSE, "-p", proj,
                                "down", "-v", "--remove-orphans", "--timeout", "10"],
                               capture_output=True, timeout=120, cwd=REPO)
                try:
                    os.unlink(os.path.join(ROOT, "project-%s.json" % proj))
                except OSError:
                    pass
            for pid in holders:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
            shutil.rmtree(ROOT, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 兜底不掩盖原异常
            print("WARN 清场异常（原异常继续）：%r" % (exc,), flush=True)
    finish()


if __name__ == "__main__":
    main()
