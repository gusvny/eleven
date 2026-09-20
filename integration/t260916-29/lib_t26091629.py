# -*- coding: utf-8 -*-
"""t260916-29 共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

两场景共用：SDK 停机日志 grace 秒数解析（工单取证日志逐字锚的正则面）、
起跑/自退/点名语义标记。

红线纪律（沿 t260904-02 lib_gate / t260905-02 lib_t26090502）：
- 绝不向真环境（3099/7233/8233 现有占用者）发任何信号；
- 被测子进程一律审计钩子护体；一切状态写临时目录；spawn 的进程收尾 TERM→KILL 兜底；
- 断言锚公开行为输出（进程终态/stderr 日志行），日志锚用兼容正则锚语义不锁
  措辞（KI-051 教训）；「停机点名」为本票方案承诺的新日志面，锚其存在不锁全句。
"""
import re
import subprocess
import time

# SDK 停机日志（temporalio _worker.py:750-753，工单取证日志的逐字来源）：
# 「Beginning worker shutdown, will wait 0:00:00 before cancelling activities」
# ——0:00:00 即「立即取消在飞活动」，本票修复把这里的值变成可配置的非零宽限。
GRACE_RX = re.compile(
    r"Beginning worker shutdown, will wait ([0-9:]+) before cancelling activities")
# 本票方案承诺的新日志面：收到停止信号时点名在飞 agent 活动（票/段/gen/attempt）。
NAMED_RX = re.compile(r"停机点名")
# watch 自退语义标记（worker.py ppid 守卫/收口自退日志）。
SELF_EXIT_RX = re.compile(r"专属 worker 自退")
# 起跑标记（worker.py 起跑日志，两形态皆有）。
BOOT_RX = re.compile(r"worker 起来了")


def grace_seconds(log_text):
    """解析 SDK 停机日志的宽限秒数（取最后一次匹配；无匹配=None）。

    「0:30:00」→1800、「0:00:02」→2、「0:00:00」→0；畸形段（不可拆整数）跳过。"""
    vals = GRACE_RX.findall(log_text or "")
    total = None
    for v in vals:
        try:
            nums = [int(p) for p in v.split(":")]
        except ValueError:
            continue
        sec = 0
        for n in nums:
            sec = sec * 60 + n
        total = sec
    return total


def _ppid_is_one(pid):
    """ppid==1 判定（收养观测）：ps 主通道；ps 被拒的沙箱（20260905 泳道实测
    Operation not permitted）回落 `pgrep -P 1` 成员判定（父为 1 的进程集）。
    返回 True/False；双通道皆不可得=None（N/A 折算依据）。"""
    try:
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=10).stdout.split()
        if out:
            return int(out[0]) == 1
    except Exception:
        pass
    try:
        r = subprocess.run(["pgrep", "-P", "1"],
                           capture_output=True, text=True, timeout=10)
        pids = {int(x) for x in r.stdout.split() if x.strip().isdigit()}
        return pid in pids
    except Exception:
        return None


def wait_ppid_one(pid, timeout_s, interval=0.5):
    """等 worker 被收养（ppid==1）。返回 (达到与否, 末次观测描述)。

    收养目标 ppid 随环境（macOS=launchd(1)；Linux 容器内 subreaper 可≠1）——
    达不到时调用方按 N/A 条件子用例处置，不算被测行为红（沿 t260905-02 口径）。"""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = _ppid_is_one(pid)
        if last is True:
            return True, "ppid=1"
        time.sleep(interval)
    if last is None:
        return False, "ppid 观测不可得（ps 被拒且 pgrep 不可用）"
    return False, "末观测 ppid≠1（收养目标非 1 的环境形态）"
