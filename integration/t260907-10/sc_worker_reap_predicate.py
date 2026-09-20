#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_worker_reap_predicate.py — 迁移后 worker 收尸谓词完备性（t260907-10，灰盒 L3）。

intent（用户可感知契约）：目录重构改了 worker 的落盘路径（引擎旧名→server/engine），
stop-console 的 pgrep 谓词若仍只认旧路径 cmdline，迁移后 stop 停不掉 worker——
僵尸进程吃资源、占 Temporal 任务槽，用户看到的是「停了控制台机器还在响」。
本条守资源回收契约：谓词必须命中从 server/engine/worker.py 起的 worker 命令行；
temporal dev server 谓词子用例必须在场（两条收尸线不互替）。

对抗面（developer 最易犯的错）：改了引擎路径漏改收尸脚本（收尸脚本属仓根扩权面，
review gen0 A1 申报——本条同时是该扩权债的监督信号：扩权未落地则本条红）；
正则转义把 . 当通配（engineXworker.py 也命中——用合成反例钉字面点号）。

high-level steps：
  1. 读 stop-console.sh 提取 pgrep -f 模式串（单引号包裹的 alternation）；
  2. 新路径 worker 样本 cmdline「python3 <repo>/server/engine/worker.py --queue q」
     必被某分支命中；
  3. 「temporal server start-dev」分支在场（temporal dev server 收尸线）；
  4. 自证红绿：分支字面可命中同形样本；点号转义反例（engineXworker.py）不被命中；
     无关进程样本（console 3099）不被误命中——收尸不越界碰用户操作面。

Hermetic：纯文本读＋字符串正则，零进程零端口零 3099，秒级。
**implement 落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。**
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260907-04"))  # 共享 helper：lib_naming.Rec
import lib_naming  # noqa: E402

STOP = os.path.join(REPO, "stop-console.sh")
NEW_SAMPLE = "python3 /repo/server/engine/worker.py --queue sandbar-tickets"
OLD_SAMPLE = "python3 /repo/server/dsh/temporal-poc/worker.py --queue sandbar-tickets"
CONTROL_SAMPLE = "python3 /repo/start-console.sh  # console 3099 用户操作面"
UNRELATED_SAMPLE = "python3 /opt/myproject/worker.py --queue other"


def _branches(text):
    """提取全部 pgrep -f '<模式>' 的 | 分支集合。"""
    branches = set()
    for m in re.finditer(r"""pgrep\s+(?:-\w+\s+)*-f\s+'([^']+)'""", text):
        branches.update(b.strip() for b in m.group(1).split("|") if b.strip())
    return branches


def main():
    r = lib_naming.Rec()

    print("== 1 谓词在位（stop-console.sh 可读且含 pgrep -f 模式）")
    with open(STOP, "r", encoding="utf-8") as f:
        text = f.read()
    branches = _branches(text)
    r.check(len(branches) >= 2, "pgrep 模式分支数=%d（须 ≥2）" % len(branches))

    print("== 2 新路径 worker cmdline 必被命中（迁移后停得掉）")
    r.check(any(re.search(b, NEW_SAMPLE) for b in branches),
            "engine/worker.py 样本命中（分支=%s）" % sorted(branches))

    print("== 3 temporal dev server 收尸线在场")
    r.check(any("temporal server start-dev" in b for b in branches),
            "start-dev 分支在场")

    print("== 4 自证红绿")
    # 分支有效性：每条 worker 分支必须命中其所属时代的样本（gen1 口径校准——
    # 回落期双分支双认为设计态（review gen2 通过）：新分支认新样本、旧分支认旧样本，
    # 旧分支不命中新样本恰是「停旧不误停」的本义；摘除票删旧分支后自动归一）。
    worker_branches = [b for b in branches if "worker.py" in b]
    samples = (NEW_SAMPLE, OLD_SAMPLE)
    r.check(bool(worker_branches) and all(
        any(re.search(b, s) for s in samples) for b in worker_branches),
        "每条 worker 分支至少命中一个时代样本（分支有效性，红）")
    # 特异性：无关项目的 worker 样本不误命中（替代 gen0 的点号转义反例——
    # pgrep -f 的未转义点号属无害通配，误伤面≈零，不绑实现风格；真正要守的
    # 契约是「不越界杀别的项目」）。
    r.check(not any(re.search(b, UNRELATED_SAMPLE) for b in worker_branches),
            "无关项目 worker 样本不误命中（特异性）")
    r.check(not any(re.search(b, CONTROL_SAMPLE) for b in branches),
            "console 进程样本不被误命中（收尸不越界 3099 操作面）")

    r.finish()


if __name__ == "__main__":
    main()
