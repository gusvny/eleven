#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_integ_run_singleflight.py — 同泳道集成跑单飞锁契约（t260913-02 arbitrate gen10）。

intent（用户可感知契约，锚 CLI 行为不锚实现；灰盒 L2）：
  同一泳道的集成跑**不许并发**——两次并发全轮共用泳道级舞台工程名（
  stage-console-<泳道指纹> / t26090704-sched-<指纹>），会互相拆台：拆在飞的台
  （中段「连接被拒」）、旧 ID 串台（把夹具残留报成产品红）、console 族瞬时环境红。
  实况 260914 21:08-21:10：两个 199 条全轮重叠 85s，闸录得 1 败 + 17 环境红。
  故第二次发车必须在**开跑任何场景之前**收口：
    子用例1 无锁发车照跑（不误伤——今天唯一发车姿态）；
    子用例2 有锁时 CLI 退出码=2（环境红，零场景开跑）且**点名持有者**（pid/起租时间可读）；
    子用例3 显式 knob SANDBAR_INTEG_ALLOW_CONCURRENT=1 时放行并留痕（人可承担风险）；
    子用例4 只读资产查询面 --print-pool-assets 不占锁（闸会与在跑的轮并行查资产面，
         把它挡出去=闸自己瞎）。
  与 t260904-12-executor-three-state（三态计数/汇总自证）intent 不同面：彼守执行器
  计数语义，本条守「并发发车门」。设备：SANDBAR_INTEG_RUN_LOCK_PATH 指向临时锁档
  （缺省锁档=泳道键，本场景**不碰它**——免得与在跑的轮互扰）；「照跑」子用例用「排除
  全部在册池」把全轮收成零条目（ran=0 与在册 0 一致，三态 rc=0），秒级、零 docker。
  实现段落地前红属预期（锁缺席=子用例2 照跑=红），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import fcntl
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
RUNNER = os.path.join(INTEG, "run_scenarios.py")
sys.path.insert(0, INTEG)
import lib_env  # noqa: E402


class Rec(object):
    """子用例级计数与退出收口（三态：0 全过 / 1 产品红 / 2 环境红）。"""

    def __init__(self):
        self.passed = self.failed = self.env_failed = 0

    def check(self, cond, label):
        if cond:
            self.passed += 1
            print("  ok %s" % label, flush=True)
        else:
            self.failed += 1
            print("  FAIL %s" % label, flush=True)

    def env_fail(self, reason):
        self.env_failed += 1
        print("  ENV_FAIL: %s" % reason, flush=True)

    def finish(self):
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0"
              % (self.passed, self.failed, self.env_failed), flush=True)
        if self.failed:
            sys.exit(lib_env.EXIT_FAIL)
        if self.env_failed:
            sys.exit(lib_env.EXIT_ENV_FAIL)
        sys.exit(lib_env.EXIT_PASS)


def _all_pools():
    """全部在册池名（排除面用；读注册表数据，不猜）。"""
    spec = importlib.util.spec_from_file_location("rs_pools", RUNNER)
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)

    def pool(e):
        opt = e[3] if len(e) > 3 else None
        return opt if (opt and opt != "serial") else "main"

    return sorted({pool(e) for e in rs.SCENARIOS})


def _cli(lock_path, extra_env=None, args=("--exclude-pools",)):
    env = dict(os.environ)
    env["SANDBAR_INTEG_RUN_LOCK_PATH"] = lock_path
    env.pop("SANDBAR_INTEG_ALLOW_CONCURRENT", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, RUNNER] + list(args),
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=600)


def main():
    r = Rec()
    zero = ",".join(_all_pools())          # 排除全部池 → 零条目全轮（秒级）
    tmpd = tempfile.mkdtemp(prefix="integ-singleflight-")
    lock_path = os.path.join(tmpd, "run.lock")
    hold_fd = None
    try:
        print("== 子用例1 无锁发车 → 照跑（零条目全轮收成 rc=0，不误伤正常发车）")
        p = _cli(lock_path, args=["--exclude-pools", zero])
        r.check(p.returncode == 0,
                "无锁时 CLI 正常收口（rc=%s｜尾：%s）"
                % (p.returncode, (p.stdout or p.stderr).strip().splitlines()[-1:]))

        print("== 子用例2 有锁发车 → 环境红收口且点名持有者（零场景开跑）")
        # 持锁方=本进程（走同一条 _acquire_run_lock——锁档格式与生产同源）
        # 260928 修（本场景在「调用方置了并发旋钮」时必红的真因）：`_acquire_run_lock` 会读
        # `SANDBAR_INTEG_ALLOW_CONCURRENT`——旋钮在场即**不持锁**（风险由调用方承担，fd=None），
        # 于是子用例2 的「并发发车被拒」全条失效（实测：本进程 fd=None、并发发车 rc=0）。
        # 子用例1/2/4 判的是**缺省语义**，故本进程显式中立化该旋钮（子用例3 仍显式置位测放行面）；
        # 与 t260915-12 处理 SANDBAR_UNDECLARED_POLICY、t260924-05 处理批次超时旋钮同款手法。
        os.environ.pop("SANDBAR_INTEG_ALLOW_CONCURRENT", None)
        os.environ["SANDBAR_INTEG_RUN_LOCK_PATH"] = lock_path
        spec = importlib.util.spec_from_file_location("rs_lock", RUNNER)
        rs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rs)
        hold_fd = rs._acquire_run_lock()
        r.check(isinstance(hold_fd, int) and hold_fd >= 0,
                "本进程持锁成功（fd=%s）" % hold_fd)
        p = _cli(lock_path, args=["--exclude-pools", zero])
        out = (p.stdout or "") + (p.stderr or "")
        r.check(p.returncode == 2, "并发发车退出码=2（环境红，实测 rc=%s）" % p.returncode)
        r.check("已在进行中" in out and ("pid=%d" % os.getpid()) in out,
                "拒收文案点名持有者 pid 与锁档（%s）" % out.strip().splitlines()[:1])
        r.check("本次未开跑任何场景" in out, "文案声明零场景开跑（不谎报已跑）")
        r.check("ran=" not in out, "拒收面零场景计数行（不开跑就无计数）")

        print("== 子用例3 显式 knob 放行 → 照跑且留痕（风险由调用方承担）")
        p = _cli(lock_path, args=["--exclude-pools", zero],
                 extra_env={"SANDBAR_INTEG_ALLOW_CONCURRENT": "1"})
        out = (p.stdout or "") + (p.stderr or "")
        r.check(p.returncode == 0, "knob 置位后照跑（rc=%s）" % p.returncode)
        r.check("已显式关闭" in out, "放行留痕在文（显式关闭行）")
        r.check("已在进行中" not in out, "放行面不再报并发拒收")

        print("== 子用例4 只读资产查询面不占锁（闸并行查资产面不被挡）")
        p = _cli(lock_path, args=["--print-pool-assets", "main"])
        r.check(p.returncode == 0,
                "持锁时资产查询照常（rc=%s）" % p.returncode)
        r.check("已在进行中" not in ((p.stdout or "") + (p.stderr or "")),
                "资产查询面不报并发拒收")
    finally:
        # 兜底：持锁线程崩也要放锁（flock 随 fd 关闭自释放）
        try:
            if hold_fd is not None and hold_fd >= 0:
                os.close(hold_fd)
        except OSError:
            pass
        try:
            os.unlink(lock_path)
        except OSError:
            pass
        try:
            os.rmdir(tmpd)
        except OSError:
            pass

    r.finish()


if __name__ == "__main__":
    main()
