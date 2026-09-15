#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-18 场景①：被砍/异常路径的舞台回收（灰盒 L3，工单「怎么算好①」机械入口，
integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）——工单①的
「四条终态路径都必须显式 down、回收失败响亮」契约，钉在**编排公开协程**
`ui_capture_stage.run_capture_stage`（方案 §1b「编排纯函数、capture_cmd 注入
可桩」的落地形态；agent_activities 即经它驱动截图流程；其 docstring 明文
「场景用 python3 -c sleep 桩」）与 stage_docker 公开 CLI 上：

- 腿 A1（超时路，主修）：capture 桩（sleep 120）+ capture_timeout_s=4 →
  wait_for 先响（超时分支确定性触发，不依赖截图真跑通）→ 必须 down：容器数
  紧窗口（≤30s）回落到零、回执点名「超时」（fail-visible）。修前形态=超时
  只 kill 子进程无人拆台，本腿对主修敏感。
- 腿 A2（取消于捕获窗）：租约 state=up（起台完成）后 task.cancel() →
  取消语义=先拆台再按 Temporal 惯例重抛：容器数紧窗口回落到零。
- 腿 A3（取消于起台窗）：容器一出现（起台腿仍在跑）即 cancel——取消语义
  覆盖整个 attempt 窗口，断言容器在 down 帽级窗口（≤150s）回落到零。落地
  形态=asyncio.shield 保起台收尾再补拆重抛（「绝不把半起的台丢给兜底链」）；
  260915 读码实锚过未护形态（CancelledError 直上抛、台活到 hold ⑥ 帽 4h）
  ——本腿守该窗不退化（shield 被移除即红）。
- 腿 B（硬杀残局，兜底回归守卫）：调用方进程被 SIGKILL（引擎进程级死亡：
  worker 崩溃/OOM 形态）后，hold ③ 锚死回收这条既有兜底链最终拆台。验证
  对象=兜底不是主修，未修代码上也应绿（守卫不退化）。支架纪律：SIGKILL 后
  必须 wait() 收割——不收割则 W 成 zombie，pid_alive(zombie)=True → ③ 读锚
  「仍活」永不回收（260915 冒烟实锤；生产面=引擎对 activity 的 proc.wait()
  收割，不欠此账）。
- 腿 C（回收失败响亮，fail-visible）：注入 down 失败（
  SANDBAR_STAGE_INJECT_DOWN_FAIL=1 一次性注入）→ 拆台必须非零退出 + 输出
  点名 + 租约保留（账本不先于容器销，C4 裁决）+ 容器仍在；撤注入恢复。

与既有场景 intent 分工：t260910-12-holder-kill-reclaim 锚「hold 被杀→租约
过期判死回收」；t260912-02-sweep-owner-gone 锚「hold 活着也拆得主」的主人
存在性清道夫；本条腿 B 锚「锚进程（调用方）死而 hold 活」的 ③ 路回收（前
两者的中间形态，守卫面），腿 A/C 为本票新增的单主人显式 down 契约，均不互替。

注入面声明：capture_cmd 用 `python3 -c "sleep 120"` 桩（超时/取消路只需
「capture 仍在跑」这一事实）；经 prepare_ui_evidence 驱动的活动层全链腿
260915 试过并放弃——真跑 capture-lane 需泳道 build 产物（workbench/ 目录、
workbench/lib/client.js，两道前置校验秒退）=别的票的构建面，伪造产物是
无底洞；舞台生命周期半边由 run_capture_stage 全权承担，活动层只是把桩换
成真 node 而已。down 失败注入走 env 一次性开关；锁根经进程 env
SANDBAR_STAGE_LOCK_DIR 隔离（引擎起/拆台的子进程继承本进程 env，不触碰
生产共享锁根）。docker 缺席=ENV_FAIL exit 2（三态契约，不写 SKIP）。运行
解释器=server/engine/.venv/bin/python（回落 python3）——腿 A 导入
ui_capture_stage（编排协程 asyncio 面）建议 venv。
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, HERE)
sys.path.insert(0, ENGINE)

from lib_case import (  # noqa: E402
    check,
    cli,
    compose_containers,
    docker_present,
    envfail,
    finish,
    guarded_down,
    iso_root18,
    kill_pid,
    lease_file,
    read_lease_file,
    rm_rf,
    stage_tag,
    up_ok,
    up_stage,
    wait_until,
)

# 腿 A 的 capture 桩：活过任何短帽，保证 wait_for 先响（超时分支确定性触发）。
SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]
LEG_A_WINDOW_S = 30      # 显式 down 级紧窗口（分钟级兜底链救不了这条断言）
LEG_A3_WINDOW_S = 150    # 取消于起台窗：up 余程+down 的预算（修复形态）
LEG_B_UP_BUDGET_S = 300
LEG_B_RECLAIM_BUDGET_S = 180
LEG_C_INJECT_ENV = "SANDBAR_STAGE_INJECT_DOWN_FAIL"


def _flat_strings(obj):
    """回执里全部字符串值（不锚字段名的响亮度断言面）。"""
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flat_strings(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_flat_strings(v))
    return out


async def _leg_a(tag, root):
    """腿 A：编排公开协程 run_capture_stage 的三条超时/取消终态路。

    缝的选择（260915 gen1 收敛）：实现段把方案 §1b 的「编排纯函数」落地为
    ui_capture_stage.run_capture_stage（公开协程，agent_activities 调用，
    docstring 明文「capture_cmd 收可注入桩（场景用 python3 -c sleep 桩）」）；
    场景直驱它=sleep 桩替截图（超时/取消路只需「capture 仍在跑」事实，不依赖
    截图真跑通），services="temporal" 轻台。不再经 prepare_ui_evidence 驱动：
    真跑 capture-lane 需泳道 build 产物（workbench/lib/client.js，260915 冒烟
    实锤两道前置校验）——那是别的票的构建面，伪造产物是无底洞；工单①验收
    的舞台生命周期半边由本协程全权承担，活动层只是把 capture_cmd 换成真
    node 而已。"""
    try:
        import ui_capture_stage as uis
    except ImportError as e:
        check(False, "腿A 未过：ui_capture_stage 不可导入：%s" % e)
        return
    fn = getattr(uis, "run_capture_stage", None)
    if not callable(fn):
        check(False, "腿A 契约不符：ui_capture_stage 未暴露编排公开协程 "
                     "run_capture_stage（方案 §1b）——实现须提供场景可驱动入口")
        return

    async def _run(ticket, cap):
        return await asyncio.wait_for(
            fn(project=uis.capture_stage_project(ticket, 0), services="temporal",
               capture_cmd=list(SLEEPER), capture_timeout_s=cap,
               stage_up_timeout_s=180,
               env_extra={"SANDBAR_STAGE_TICKET": "%s/gen0" % ticket}),
            timeout=420)

    # ---- A1 超时路 ----
    proj1 = uis.capture_stage_project("t260915-18-lega1-%s" % tag, 0)
    try:
        r1 = await _run("t260915-18-lega1-%s" % tag, 4)
    except asyncio.TimeoutError:
        check(False, "腿A1 超时路：编排入口 420s 未返回（up+capture+down 全链"
                     "卡死，自身终态无帽）")
        return
    except Exception as e:  # noqa: BLE001
        check(False, "腿A1 超时路：编排入口抛 %s：%s" % (type(e).__name__, e))
        return
    flat1 = " ".join(_flat_strings(r1))
    check(isinstance(r1, dict) and r1.get("ok") is False and "超时" in flat1,
          "腿A1 超时路：回执 ok=False 且点名「超时」（fail-visible 不静默）｜%s"
          % flat1[:200])
    check(wait_until(lambda: len(compose_containers(proj1)) == 0, LEG_A_WINDOW_S),
          "腿A1 超时路：容器数紧窗口（≤%ds）回落到零——超时被砍后台被回收"
          % LEG_A_WINDOW_S)

    # ---- A2 取消于捕获窗（capture 桩长眠中）----
    proj2 = uis.capture_stage_project("t260915-18-lega2-%s" % tag, 0)
    task = asyncio.ensure_future(_run("t260915-18-lega2-%s" % tag, 90))
    upped2 = await asyncio.get_running_loop().run_in_executor(
        None, lambda: wait_until(
            lambda: (read_lease_file(root, proj2) or {}).get("state") == "up",
            240, 2))
    if not upped2:
        task.cancel()
        try:
            await task
        except BaseException:
            pass
        check(False, "腿A2 取消路：起台 240s 未到 state=up（前置未成立，"
                     "本腿没验成；不阻断腿A3）")
    else:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # 取消语义：编排层先拆台再按 Temporal 惯例重抛——**断言必须在取消
            # 分支里跑**（此前挂在 try/else 无异常分支=真取消零断言静默通过，
            # 对抗复核自摆：断言没跑=没验成，不是通过）。
            check(wait_until(lambda: len(compose_containers(proj2)) == 0,
                             LEG_A_WINDOW_S),
                  "腿A2 取消于捕获窗：容器数紧窗口（≤%ds）回落到零——取消路 "
                  "down 被执行" % LEG_A_WINDOW_S)
        except Exception as e:  # noqa: BLE001
            check(False, "腿A2 取消路：取消路径抛 %s：%s（取消不是免拆台牌照）"
                         % (type(e).__name__, e))
        else:
            check(False, "腿A2 取消路：task.cancel() 后协程未按取消语义重抛"
                         "（CancelledError 缺席=契约不符，容器清零断言不适用）")

    # ---- A3 取消于起台窗（F4 钉子：容器一出现即取消）----
    proj3 = uis.capture_stage_project("t260915-18-lega3-%s" % tag, 0)
    task3 = asyncio.ensure_future(_run("t260915-18-lega3-%s" % tag, 90))
    started3 = await asyncio.get_running_loop().run_in_executor(
        None, lambda: wait_until(lambda: len(compose_containers(proj3)) > 0,
                                 240, 2))
    if not started3:
        task3.cancel()
        try:
            await task3
        except BaseException:
            pass
        check(False, "腿A3 起台窗：240s 未见到容器（前置未成立，本腿没验成）")
    else:
        task3.cancel()   # 起台腿仍在跑——取消语义必须覆盖整个 attempt
        try:
            await task3
        except asyncio.CancelledError:
            check(wait_until(lambda: len(compose_containers(proj3)) == 0,
                             LEG_A3_WINDOW_S, 3),
                  "腿A3 取消于起台窗：容器数在 %ds 内回落到零——shield 等起台"
                  "收尾后必须补拆，不把半起的台丢给兜底链" % LEG_A3_WINDOW_S)
        except Exception as e:  # noqa: BLE001
            check(False, "腿A3 起台窗：取消路径抛 %s：%s（取消不是免拆台牌照）"
                         % (type(e).__name__, e))
        else:
            check(False, "腿A3 起台窗：task.cancel() 后协程未按取消语义重抛"
                         "（CancelledError 缺席=契约不符）")


def _leg_b(root, p):
    """腿 B：调用方进程硬杀（SIGKILL）→ hold ③ 锚死回收兜底（守卫，应绿）。"""
    ready_dir = tempfile.mkdtemp(prefix="sandbar-t26091518-b-")
    ready = os.path.join(ready_dir, "ready")
    # 中间进程 W：亲手 spawn stage_docker up（anchor=W），完成后写回执再长眠——
    # 场景等 up 成立后 SIGKILL W=「调用方树消失」形态（SIGKILL 而非 SIGTERM：
    # 钩子不跑才是本形态）。
    wrapper = (
        "import os,subprocess,sys,time,json\n"
        "root,proj,ready=sys.argv[1],sys.argv[2],sys.argv[3]\n"
        "env=dict(os.environ); env['SANDBAR_STAGE_LOCK_DIR']=root\n"
        "p=subprocess.run([sys.executable,'integration/stage_docker.py','up',"
        "'--project',proj,'--services','temporal'],env=env,capture_output=True,"
        "text=True,cwd=%r)\n"
        "json.dump({'rc':p.returncode,'tail':((p.stderr or '')+(p.stdout or ''))"
        "[-260:]},open(ready,'w'))\n"
        "time.sleep(600)\n" % REPO)
    w = subprocess.Popen([sys.executable, "-c", wrapper, root, p, ready],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_until(lambda: os.path.exists(ready), LEG_B_UP_BUDGET_S, 2):
        kill_pid(w.pid)
        w.wait()
        envfail("腿B 起台 %ds 未完成（prepare 型前置未成立）" % LEG_B_UP_BUDGET_S)
        return
    outcome = {}
    try:
        with open(ready, encoding="utf-8") as fh:
            outcome = json.load(fh)
    except (OSError, ValueError):
        outcome = {"rc": -1, "tail": "ready 文件不可解析"}
    if outcome.get("rc") != 0:
        kill_pid(w.pid)
        w.wait()
        if outcome.get("rc") in (2, 3):
            envfail("腿B 起台 rc=%s=env/conflict 档（prepare 型环境/并发面）"
                    "｜证据尾：%s" % (outcome.get("rc"), outcome.get("tail", "")))
        else:
            check(False, "腿B 起台 rc=%s（产品/契约面）｜证据尾：%s"
                  % (outcome.get("rc"), outcome.get("tail", "")))
        return
    check(len(compose_containers(p)) > 0, "腿B 前置：真台在跑（容器 %d 只）"
          % len(compose_containers(p)))
    kill_pid(w.pid)
    w.wait()   # 收割僵尸：不 wait 则 W 成 zombie，pid_alive(zombie)=True → hold ③
               # 读锚「仍活」永不回收（260915 冒烟实锤；生产面=引擎 proc.wait()
               # 收割不欠账——场景必须自收割）
    check(wait_until(lambda: len(compose_containers(p)) == 0,
                     LEG_B_RECLAIM_BUDGET_S, 3),
          "腿B 兜底链：锚死后 %ds 内容器清零（hold ③ 锚死回收，分钟级窗口）"
          % LEG_B_RECLAIM_BUDGET_S)
    check(wait_until(lambda: not os.path.exists(lease_file(root, p)), 30),
          "腿B 兜底链：拆台成功后租约文件销账（账随容器走，序正确）")


def _leg_c(root, p):
    """腿 C：down 失败注入 → 响亮非零 + 租约保留 + 容器仍在；撤注入可恢复。"""
    proc, _ = up_stage(root, p)
    if not up_ok(proc, "腿C 前置：真台起台"):
        return
    bad = cli(root, "down", "--project", p,
              env_extra={LEG_C_INJECT_ENV: "1"})
    check(bad.returncode != 0,
          "腿C 回收失败：down 非零退出（rc=%s，不假绿）" % bad.returncode)
    loud = ((bad.stderr or "") + (bad.stdout or "")).strip()
    check(bool(loud), "腿C 回收失败：stderr/stdout 点名（fail-visible 不静默吞）"
                      "｜输出尾：%s" % " ".join(loud.split())[-180:])
    check(os.path.exists(lease_file(root, p)),
          "腿C 回收失败：租约文件保留（账本不先于容器销——C4 裁决面）")
    check(len(compose_containers(p)) > 0,
          "腿C 回收失败：容器仍在场（失败的 down 不得假报拆掉）")
    ok = cli(root, "down", "--project", p)
    check(ok.returncode == 0 and wait_until(
        lambda: len(compose_containers(p)) == 0, 60),
        "腿C 恢复：撤注入后 down 成功、容器清零（可恢复性）")


def main():
    if not docker_present():
        envfail("docker 不可用（docker info 失败）——测试台一律走 docker，"
                "启动 Docker/OrbStack 后重试")
        finish()
    tag = "%d" % (int(time.time()) % 100000)
    root = iso_root18("kill-reclaim-" + tag)
    # 腿 A 的引擎起/拆台子进程继承本进程 env → 锁根隔离在这里进程级注入。
    os.environ["SANDBAR_STAGE_LOCK_DIR"] = root
    pb = stage_tag("t26091518-kc-b-" + tag)
    pd = stage_tag("t26091518-kc-d-" + tag)
    mine = [pb, pd]
    try:
        _leg_b(root, pb)
        _leg_c(root, pd)
        asyncio.run(_leg_a(tag, root))
    finally:
        os.environ.pop("SANDBAR_STAGE_LOCK_DIR", None)
        guarded_down(mine, root)
        rm_rf(root)
    finish()


if __name__ == "__main__":
    main()
