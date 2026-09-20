#!/usr/bin/env python3
"""t260913-04 场景②：agent 工程镜像与容器内 supervisor 的契约（灰盒 L3，真 docker）。

intent（用户可感知）：工单票一进容器就能干活——镜像预装 agent 段必需环境
（node+dsh 本体、python3+pytest/temporalio/pyyaml、git、zstd），且容器内收割协议
（sandbar-exec：落 pgid → 按组 TERM → 退出清档 → 坏参 fail-closed）真实可用。
这是验收 G（零残留）与 KI-009（进程组收割）在容器形态里的物理前提。

依据：工单块 1（镜像预装依赖；工单源事故附带发现①：容器原型内无 pytest、pip 被 PEP 668 拒）＋
方案 gen1 §2 清单 #1-#4、D3 supervisor 协议。与 developer L1 分工：L1 锁模块函数，
本条锁**真镜像里真跑**的终态（版本在场、协议可收割、坏参不静默）。

high-level steps：docker 在场探针 → 镜像在场探针（Dockerfile.agent 在场而镜像缺席=
ENV_FAIL 点名构建命令；声明面整体缺席=FAIL 验收棒）→ 起契约形容器 → 逐项探镜像依赖
版本 → sandbar-exec 协议三子用例（pgid 落盘/按组 TERM 收割/退出清档/坏参非零）→ 清理零残留。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现段落地前红属预期（TDD 验收棒）；
arbitrate/merge 期必须绿。engine 池（docker 舞台，宽 1；本票写集命中
server/docker-compose.test.yml 时被 force-assets 强制回册）。
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_container_case as F  # noqa: E402

C = F.Checker("t260913-04-scenario-2-image-supervisor")
TICKET = F.uniq("t260913-04-itest-image")
CONT = F.CONTAINER_FMT % TICKET


def probe(img, script, timeout=120):
    return F.sh("docker", "run", "--rm", img, "sh", "-c", script, timeout=timeout)


def wait_file(container, path, timeout=15):
    dl = time.time() + timeout
    while time.time() < dl:
        if F.exec_in(container, "test", "-s", path).returncode == 0:
            return True
        time.sleep(0.5)
    return False


def main():
    F.require_docker(C)
    tag = F.agent_image_tag(C)   # 镜像缺席=ENV_FAIL 点名构建；声明面缺席=FAIL 棒

    print("\n== 镜像依赖面（agent 一进去就能干活）==")
    p = probe(tag, "dsh --version")
    C.check(p.returncode == 0 and p.stdout.strip(), "dsh 本体在镜像内可用（PATH 可解析裸名）",
            "rc=%s out=%s" % (p.returncode, (p.stdout + p.stderr)[:120]))
    p = probe(tag, "node --version")
    major = p.stdout.strip().lstrip("v").split(".")[0] if p.returncode == 0 else ""
    C.check(major.isdigit() and int(major) >= 22,
            "node >= 22（dsh 传递依赖要求，node20 运行期真炸——§2 清单 #1）",
            "out=%s" % p.stdout.strip()[:40])
    p = probe(tag, "python3 --version && python3 -c \"import pytest, temporalio, yaml\"")
    C.check(p.returncode == 0, "python3 + pytest/temporalio/pyyaml 预装（工单源事故附带发现①："
            "无 pytest、PEP 668 拒 pip 的教训）", "rc=%s %s" % (p.returncode, p.stderr[:160]))
    p = probe(tag, "git --version && zstd --version")
    C.check(p.returncode == 0, "git 与 zstd 在镜像内（取证/会话档面）",
            "rc=%s %s" % (p.returncode, p.stderr[:120]))

    print("\n== supervisor sandbar-exec 协议（收割协议的物理前提，D3/KI-009）==")
    sup = probe(tag, "test -x /usr/local/bin/sandbar-exec && echo present")
    C.check(sup.returncode == 0 and "present" in sup.stdout,
            "/usr/local/bin/sandbar-exec 在场且可执行", "out=%s" % sup.stdout.strip()[:40])

    # 契约形容器（挂载面/user 面与引擎声明一致；本场景只考镜像与 supervisor）
    scratch = Path(tempfile.mkdtemp(prefix="t26091304-img-"))
    lane = scratch / "lane"
    lane.mkdir(parents=True, exist_ok=True)
    r = F.sh("docker", "run", "-d", "--name", CONT,
             "--label", "%s=%s" % (F.LABEL_TICKET, TICKET),
             "--label", "%s=%s" % (F.LABEL_LANE, str(lane)),
             "-v", "%s:%s" % (lane, lane), "-w", str(lane),
             "--user", "%d:%d" % (os.getuid(), os.getgid()),
             tag, "sleep", "infinity")
    up = r.returncode == 0
    C.check(up, "契约形容器起得来（label/name/挂载/user 面）", "err=%s" % r.stderr[:160])
    try:
        if up:
            # 非 root 可执行面（引擎真配置 = --user 宿主 uid:gid；0711 之类的
            # 无 world-read 模式会让 shebang 脚本直接 EACCES——本项目 260913 实测）
            nre = F.exec_in(CONT, "/usr/local/bin/sandbar-exec")
            C.check("Permission denied" not in (nre.stderr or ""),
                    "契约 user 身份可执行 supervisor（world-readable+exec，非仅 root 可跑）",
                    "rc=%s stderr=%s" % (nre.returncode, (nre.stderr or "")[:160]))
            pgid = "/tmp/itest-%s.pgid" % TICKET
            F.exec_in(CONT, "rm", "-f", pgid)
            d = F.sh("docker", "exec", "-d", CONT, "/usr/local/bin/sandbar-exec",
                     pgid, "sh", "-c", "sleep 300")
            started = d.returncode == 0 and wait_file(CONT, pgid)
            C.check(d.returncode == 0, "supervisor 能拉起长命命令（detached）",
                    "err=%s" % d.stderr[:120])
            C.check(started, "pgid 文件落盘（收割协议的寻址面）", "path=%s" % pgid)
            if not started:
                C.na("supervisor 未成功拉起长命命令——后续收割子用例无被测对象（避免真空假绿）")
            else:
                pg = F.exec_in(CONT, "cat", pgid).stdout.strip()
                C.check(pg.isdigit(), "pgid 是数字进程组 id", "pgid=%r" % pg[:20])
                before = F.exec_in(CONT, "pgrep", "-f", "sleep 300").stdout.strip()
                C.check(bool(before), "被拉起命令真实在跑（正锁：不是空转协议）")
                k = F.exec_in(CONT, "kill", "-TERM", "--", "-%s" % pg)
                C.check(k.returncode == 0, "按组 kill -TERM -- -<pgid> 可执行（KI-009 语义）",
                        "err=%s" % k.stderr[:120])
                gone, dl = False, time.time() + 20
                while time.time() < dl:
                    if F.exec_in(CONT, "pgrep", "-f", "sleep 300").stdout.strip() == "":
                        gone = True
                        break
                    time.sleep(0.5)
                C.check(gone, "TERM 后整组进程在界内消失（迟写排水窗口关死）")
                C.check(F.exec_in(CONT, "test", "-e", pgid).returncode != 0,
                        "supervisor 退出清 pgid 文件（全终态回收）")
            bad = F.exec_in(CONT, "/usr/local/bin/sandbar-exec")
            C.check(bad.returncode != 0 and "Permission denied" not in (bad.stderr or "")
                    and (bad.stderr or bad.stdout).strip() != "",
                    "坏参 fail-closed（非零退出且点名用法，不静默）",
                    "rc=%s out=%s" % (bad.returncode, (bad.stdout + bad.stderr)[:120]))
    finally:
        F.sh("docker", "rm", "-f", CONT, timeout=60)
        left = F.containers_by_label(F.LABEL_TICKET, TICKET)
        C.check(not left, "清理零残留（label 过滤为 0，验收 G）", "left=%s" % left)
        shutil.rmtree(scratch, ignore_errors=True)

    C.finish()


if __name__ == "__main__":
    main()
