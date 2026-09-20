#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 验收 D + C4(a)：清理成本（无残台单跑 ≤5s）；清理失败上抛可见；
存量租约 sweep --dry-run 逐条分类落证据（review C4a——260912 存量 legacy 台）。

三子用例：
1. 计时子用例：隔离锁根空扫 + 真拆路径 rc0，duration_s ≤5；
2. C4(a) 证据子用例：生产共享锁根 --dry-run（只判不拆），每条租约归类
   condemned/kept/report_only/skipped/errors 之一并打印（本子用例只读零副作用）；
3. 失败可见子用例：坏 docker shim（PATH 前置）+ 一条判拆租约 → sweep 非零退出、
   errors 点名工程与错误原文（不得静默）。
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration", "t260910-12"))
from lib_herd_case import check, cli, docker_present, envfail, finish, stage_tag  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

TAG = stage_tag("t26091202-d")


def main():
    if not docker_present():
        envfail("docker 缺席——清扫计时/失败可见子用例不可验（C4a 证据子用例仍可跑）")
    root = tempfile.mkdtemp(prefix="t26091202-d-")
    ENV = {"SANDBAR_STAGE_LOCK_DIR": root}
    try:
        # 子用例1：空锁根全链计时（扫+拆零项）
        t0 = time.time()
        p = cli("sweep", env_extra=ENV, timeout=120)
        dur = time.time() - t0
        rpt = json.loads((p.stdout or "").strip().splitlines()[-1])
        check(p.returncode == 0 and not rpt["condemned"] and not rpt["errors"],
              "空扫 rc=0 零判拆零失败")
        check(rpt["duration_s"] <= 5.0, "D 单次扫描+清理 ≤5s（实得 %.2fs）"
              % rpt["duration_s"])
        check(dur < 30, "墙钟 sanity（%.1fs）" % dur)

        # 子用例2：生产共享锁根 --dry-run 分类证据（C4a，只读）
        if docker_present():
            p2 = cli("sweep", "--dry-run", timeout=300)
            check(p2.returncode == 0, "存量 dry-run rc=0（rc=%s）%s"
                  % (p2.returncode, " ".join((p2.stderr or "").split())[:120]))
            rpt2 = json.loads((p2.stdout or "").strip().splitlines()[-1])
            n_total = (len(rpt2["condemned"]) + len(rpt2["kept"])
                       + len(rpt2["report_only"]) + len(rpt2["errors"])
                       + len(rpt2["skipped_budget"]))
            print("C4(a) 存量分类：判拆 %d / 保留 %d / 仅报告 %d / 失败 %d / 超预算 %d"
                  "（共 %d 条租约面）；git_note=%s；耗时 %.2fs"
                  % (len(rpt2["condemned"]), len(rpt2["kept"]), len(rpt2["report_only"]),
                     len(rpt2["errors"]), len(rpt2["skipped_budget"]), n_total,
                     rpt2.get("git_note") or "无", rpt2["duration_s"]), flush=True)
            for c in rpt2["condemned"] + rpt2["report_only"]:
                print("  - %s：%s" % (c["project"], c["why"]), flush=True)
            check(rpt2["duration_s"] <= 5.0, "存量 dry-run 扫描 ≤5s（实得 %.2fs）"
                  % rpt2["duration_s"])

        # 子用例3：坏 docker shim + 判拆租约 → 失败上抛可见（租约必须真落在隔离根——
        # sd 原语按进程 env 解析锁根，先设 env 再写）
        saved_lock = os.environ.get("SANDBAR_STAGE_LOCK_DIR")
        os.environ["SANDBAR_STAGE_LOCK_DIR"] = root
        try:
            lease = sd.new_lease("%s-doomed" % TAG, holder_pid=999999,
                                 services=[], ttl=90)
            lease["heartbeat_ts"] = time.time() - 6000
            sd.write_lease("%s-doomed" % TAG, lease)
        finally:
            if saved_lock is None:
                os.environ.pop("SANDBAR_STAGE_LOCK_DIR", None)
            else:
                os.environ["SANDBAR_STAGE_LOCK_DIR"] = saved_lock
        bindir = tempfile.mkdtemp(prefix="t26091202-d-bin-")
        shim = os.path.join(bindir, "docker")
        with open(shim, "w") as f:
            f.write("#!/bin/sh\n"
                    "# 只打 compose down（info/ps 照常应答）——精确注入拆台失败\n"
                    'if [ "$1" = "info" ]; then exit 0; fi\n'
                    'if [ "$1" = "ps" ]; then exit 0; fi\n'
                    'case " $* " in\n'
                    '  *" down "*)\n'
                    '    echo "Error response from daemon: 拆台面不可用（注入故障）" >&2\n'
                    "    exit 1;;\n"
                    "esac\n"
                    "exit 0\n")
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC)
        env = dict(os.environ)
        env["PATH"] = bindir + os.pathsep + env["PATH"]
        env["SANDBAR_STAGE_LOCK_DIR"] = root
        p3 = subprocess.run([sys.executable, os.path.join(REPO, "integration",
                                                          "stage_docker.py"), "sweep"],
                            capture_output=True, text=True, timeout=120, env=env,
                            cwd=REPO)
        check(p3.returncode != 0, "清理失败非零上抛（rc=%s）" % p3.returncode)
        blob = (p3.stdout or "") + (p3.stderr or "")
        check("%s-doomed" % TAG in blob,
              "失败项逐条点名工程（%s-doomed 在输出）" % TAG)
        check("拆台面不可用" in blob, "compose 失败原文透传可见（stderr 尾行）")
        check("compose down 失败" in blob, "失败类型可辨（compose down 失败 + rc）")
        import json as _j
        rpt3 = _j.loads((p3.stdout or "").strip().splitlines()[-1])
        check(len(rpt3["errors"]) == 1
              and rpt3["errors"][0]["project"] == "%s-doomed" % TAG,
              "errors[] 结构化点名（project+err）")
        check(os.path.exists(os.path.join(root, "project-%s-doomed.json" % TAG)),
              "失败时租约保留（state=downing 待重试，不静默释放）")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    finish()


if __name__ == "__main__":
    main()
