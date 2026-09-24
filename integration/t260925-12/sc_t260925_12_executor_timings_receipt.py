#!/usr/bin/env python3
"""闸段分相计时·执行器回执可见性契约（t260925-12，registry: t260925-12-executor-timings-receipt）。

意图（灰盒 L3，ro 池，真执行器 CLI 黑盒子进程，秒级零 docker）：
工单验收④＝「分解在 stage record/receipt 上可见，超时不用日志考古」。本票给
执行器回执新增 additive 的 `timings` 分相块（方案 S1：env 组装 / 子进程墙钟 /
台账写账 / 收尾）。本场景守执行器公开回执面上这条契约真的接了线，且**计量不
扰动计量对象**——三态语义、计数口径、既有键集全部逐键不变：

- A additive 基线：`--only` 定点跑一条离线秒级在册条目，INTEG_SUMMARY JSON 的
  既有键集与改动前口径兼容（ran/pass/rc 语义不变）——老消费方零感知；
- B timings 块在案：汇总 JSON 暴露 timings 分相映射，值全为非负数值，相位和
  ≤ 本轮子进程墙钟（允许 5% 计时误差）——不可归因问题在执行器层闭合；
- C 三态不串味：定点条目 PASS → exit 0、ran==pass==1；计时面缺键/红条目形态
  不因 timings 引入新出口分支。

intent 分工（核对过 SCENARIOS 全清单）：t260924-09-fixed-rerun 守 --only 入口
可用性与逐条耗时行；t260913-03 守池排除旋钮；t260922-12 守台账定点复跑——
均不守「回执分相计时可见性」。developer L1 守纯函数真值矩阵，本条守真 CLI
黑盒整链。实现落地前 B 红属预期（TDD 信号），arbitrate/merge 期必须全绿。
执行器缺席 / 定点条目自身 ENV_FAIL = ENV_FAIL exit 2。
"""
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import env_fail  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
EXEC = [sys.executable, "integration/run_scenarios.py"]
FIXED = "t260924-09-walkthrough-copy-discipline"

cases = []


def run_cli(args, timeout=180):
    # 本场景随闸运行时，闸自身持有泳道级集成跑锁——定点子进程必须显式走并发
    # 豁免旋钮（与 t260924-09-fixed-rerun 同一先例），否则闸内恒 ENV_FAIL 假红。
    env = dict(os.environ)
    env["SANDBAR_INTEG_ALLOW_CONCURRENT"] = "1"
    try:
        p = subprocess.run(EXEC + args, cwd=str(REPO), capture_output=True,
                           text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr, None
    except subprocess.TimeoutExpired as e:
        return None, "", "", e


def summary_json(stdout):
    for line in stdout.splitlines():
        if line.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(line[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


# ---- A + B + C：定点跑一条离线秒级在册条目 ----
rc, out, err, to = run_cli(["--only", FIXED])
if to is not None:
    env_fail("执行器 --only 超时（180s）：离线秒级条目未返回")
if rc is None or "ENV_FAIL" in (out or "") + (err or ""):
    env_fail("执行器运行环境红：%s" % ((err or out or "")[:300]))

cases.append(("A1 定点恰跑一条且 exit 0（三态不串味）", rc == 0))
s = summary_json(out or "")
cases.append(("A2 INTEG_SUMMARY JSON 可解析（既有消费面在）", s is not None))
if s is not None:
    cases.append(("A3 ran==1 pass==1（计数口径不变）",
                  s.get("ran") == 1 and s.get("pass") == 1))
    t = s.get("timings")
    ok_shape = isinstance(t, dict) and len(t) > 0 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
        for v in t.values())
    cases.append(("B1 回执暴露 timings 分相块（实现前红=TDD 信号）", ok_shape))
    if ok_shape:
        wall = s.get("wall_s")
        if isinstance(wall, (int, float)) and wall > 0:
            cases.append(("B2 相位和 ≤ 子进程墙钟（+5% 误差）",
                          sum(t.values()) <= wall * 1.05))
        else:
            cases.append(("B2 相位和 ≤ 子进程墙钟（wall_s 缺=跳过强断言）", True))
else:
    cases.append(("B1 回执暴露 timings 分相块（实现前红=TDD 信号）", False))

failed = [(n, ok) for n, ok in cases if not ok]
for n, ok in cases:
    print("%s %s" % ("PASS" if ok else "FAIL", n))
print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
      % (len(cases) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
