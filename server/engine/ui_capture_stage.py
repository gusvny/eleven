#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 截图的台生命周期原语（t260915-18 工单①③：引擎单所有者模型）。

## 根因（为什么这个模块必须存在）
此前 capture-lane.mjs 自起隔离台→截图→自拆（~167s 全流程），而引擎侧
UI_CAPTURE_TIMEOUT 到点 `proc.kill()` 只杀 node 进程——stage_docker 的拆台
钩子活在同一个被杀进程树里，从未运行；台面泄漏 16→50 只容器、负载 16、
四张 UI 工单被 38h 旧台阻塞（KI-077）。放宽超时只是买时间，根治=所有权搬家：
**引擎起台、引擎用台、引擎拆台**；capture-lane 只当无拆权消费者（--stage-json，
现有契约：消费者绝不拆外部台）。

## 契约
- up_stage：`stage_docker.py up --project <p> --services full --timeout <cap>`，
  幕后 stage_docker 自起 hold 保持腿（租约+心跳），本进程退出后台不死；
  回执取 stdout 末行 JSON（project/ports.console），写盘前先本地校验
  （capture-lane 对畸形 stage-json 是 ENV_FAIL 退出 2，不回落——交付畸形回执
  只会把失败后移且更难排查）。
- down_stage：幂等、**绝不 raise**（终态清理路径的最后一环必须走完），失败
  响亮（logging + 返回 ok=False + detail 点名）——租约保留语义由 stage_docker
  侧兜底（C4:2078），sweep/巡检可接手。
- 错误分档（C2 语义的原料）：
  - UiStageEnvError：环境面（rc=2/ENV_FAIL、docker 缺席、起台超时）——调用方
    降级继续（截图证据降质，不拦主流程）；
  - UiStageError：契约面（回执畸形、未知 rc）——调用方直红（工具链坏了该停）。
- 旋钮：SANDBAR_CAPTURE_STAGE_UP_CAP_S（默认 180，上限非预期——起台常态
  ~100s）、SANDBAR_CAPTURE_STAGE_DOWN_CAP_S（默认 150，拆台常态 ~20s）；
  畸形旋钮=usage 红（与 stage_docker 同口径，不静默吞）。

全部外部交互经 `runner` 注入面——UT 用假 runner 覆盖（含畸形回执/死台/超时
分支，桩/固定文件复现，不靠真 docker）。
"""
import asyncio
import json
import logging
import math
import os
import re
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("ui_capture_stage")

STAGE_CLI_REL = os.path.join("integration", "stage_docker.py")
_ENV_FAIL_RC = 2
_DEAD_MARKER = "外部舞台已死"   # capture-lane 对死台的 ENV_FAIL 点名词（消费其 stderr）
_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class UiStageError(Exception):
    """契约面错误（回执畸形/未知 rc/CLI 缺失）——调用方直红不降级。"""


class UiStageEnvError(Exception):
    """环境面错误（docker 缺席/ENV_FAIL/起台超时）——调用方降级继续。"""


def _cap_s(env_key: str, default_s: float) -> float:
    """上限旋钮：缺省/空=默认值；畸形=usage 红（三态诚实，不静默回默认）。"""
    raw = (os.environ.get(env_key) or "").strip()
    if not raw:
        return float(default_s)
    try:
        val = float(raw)
    except ValueError:
        raise UiStageError("usage 红：%s 必须是秒数（浮点），得 %r" % (env_key, raw))
    if not math.isfinite(val) or val <= 0:   # inf/nan/零/负=usage 红（畸形不静默）
        raise UiStageError("usage 红：%s 必须为正有限秒数，得 %r" % (env_key, raw))
    return val


def up_cap_s() -> float:
    """起台上限（SANDBAR_CAPTURE_STAGE_UP_CAP_S，默认 180s）。"""
    return _cap_s("SANDBAR_CAPTURE_STAGE_UP_CAP_S", 180)


def down_cap_s() -> float:
    """拆台上限（SANDBAR_CAPTURE_STAGE_DOWN_CAP_S，默认 150s）。"""
    return _cap_s("SANDBAR_CAPTURE_STAGE_DOWN_CAP_S", 150)


def stage_cli_path(repo_root: Optional[str] = None) -> str:
    """stage_docker CLI 绝对路径：repo_root 缺省=由本模块位置反推（server/engine/
    .. 上两级=仓根）。缺失=UiStageEnvError（环境面——树不完整不该直红拦流程）。"""
    root = repo_root or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    path = os.path.join(root, STAGE_CLI_REL)
    if not os.path.isfile(path):
        raise UiStageEnvError("stage_docker CLI 不存在：%s（本树非全仓布局？）" % path)
    return path


def capture_stage_project(ticket: str, gen: int = 0) -> str:
    """attempt→project 映射名：`ui-shot-<ticket>-g<gen>`。ticket 归一（小写、
    非法字符→'-'、超长截断+短哈希保唯一）——project 名要过 stage_docker 的
    `^[a-z][a-z0-9-]{1,40}$` 闸；归一后不合法=UiStageError（票号全空等畸形）。"""
    raw = re.sub(r"[^a-z0-9-]+", "-", str(ticket).strip().lower()).strip("-")
    if not raw:
        raise UiStageError("usage 红：ticket 归一后为空（得 %r）——无法映射 project 名"
                           % ticket)
    name = "ui-shot-%s-g%d" % (raw, max(0, int(gen)))
    if len(name) > 45:
        import hashlib
        h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        name = "ui-shot-%s-g%d" % (h, max(0, int(gen)))
    if not _PROJECT_RE.match(name):
        raise UiStageError("usage 红：project 名 %r 不过 stage 闸（正则 %s）"
                           % (name, _PROJECT_RE.pattern))
    return name


def validate_stage_receipt(text: str, services: Optional[List[str]] = None
                           ) -> Dict[str, Any]:
    """up 回执校验（纯函数）：stdout 末个非空行=JSON 且 project 非空 str、
    回执声明 services 里每个服务的端口都是正 int（services="temporal" 的台
    没有 console——按需校验，不把 full 台的端口面强加给精简台；回执没带
    services 列表时保守要求 console，兼容旧格式）。畸形=UiStageError（契约
    面直红——回执是我们自己写给消费者的，交付前必须自证，不能等消费侧
    ENV_FAIL 才暴露）。"""
    lines = [ln for ln in str(text or "").strip().splitlines() if ln.strip()]
    if not lines:
        raise UiStageError("up 回执为空（stdout 无输出）")
    try:
        receipt = json.loads(lines[-1])
    except ValueError as e:
        raise UiStageError("up 回执末行非 JSON（%s…）：%s" % (lines[-1][:80], e))
    if not isinstance(receipt, dict):
        raise UiStageError("up 回执末行非对象：%r" % (receipt,))
    project = receipt.get("project")
    if not isinstance(project, str) or not project.strip():
        raise UiStageError("up 回执缺 project 字段：%r" % (receipt,))
    ports = receipt.get("ports") if isinstance(receipt.get("ports"), dict) else {}
    wanted = receipt.get("services")
    if not isinstance(wanted, list) or not wanted:
        wanted = list(services) if services else ["console"]
    for svc in wanted:
        v = ports.get(str(svc))
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise UiStageError("up 回执缺 ports.%s（正整数）：%r" % (svc, receipt))
    return receipt


def stage_dead_marker(stderr_text: str) -> bool:
    """capture-lane 的「外部舞台已死」ENV_FAIL 点名词（消费其 stderr，驱动
    C2 的死台→down+冷重试分支）。词面改动属 capture-lane 契约变更，同步改这里。"""
    return _DEAD_MARKER in str(stderr_text or "")


# runner 注入面：callable(cmd: List[str], cap_s: float, env_extra: Dict) ->
#   (returncode: int, stdout: str, stderr: str)。同步实现——活动侧经
# asyncio.to_thread 调用（子进程阻塞不进事件循环）。
Runner = Callable[[List[str], float, Dict[str, str]], Tuple[int, str, str]]


def _default_runner(cmd: List[str], cap_s: float,
                    env_extra: Dict[str, str]) -> Tuple[int, str, str]:
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=cap_s, env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        raise UiStageEnvError("stage 子进程超上限 %ss 被杀：%s" % (cap_s, " ".join(cmd)))


def up_stage(project: str, *, repo_root: Optional[str] = None,
             up_cap: Optional[float] = None, services: str = "full",
             env_extra: Optional[Dict[str, str]] = None,
             runner: Optional[Runner] = None) -> Dict[str, Any]:
    """起台并回校验回执。成功→回执 dict；env 面→UiStageEnvError（降级）；
    契约面→UiStageError（直红）。超上限被杀=UiStageEnvError（stage_docker
    自身的起台失败清理腿负责就地拆；外部击杀的残面交 down_stage 幂等补刀
    + sweep crit_iii 兜底——三层都响亮，不静默）。"""
    if not project or not str(project).strip():
        raise UiStageError("usage 红：project 为空")
    run = runner or _default_runner
    cap = float(up_cap) if up_cap is not None else up_cap_s()
    cli = stage_cli_path(repo_root)
    extra = dict(env_extra or {})
    rc, out, err = run([ "python3", cli, "up", "--project", str(project).strip(),
                         "--services", str(services or "full"),
                         "--timeout", str(int(cap)) ],
                       cap, extra)
    if rc == _ENV_FAIL_RC:
        named = [ln for ln in err.splitlines() if ln.startswith("STAGE_")]
        raise UiStageEnvError("起台 ENV_FAIL（rc=2）：%s"
                              % (named[-1] if named else err[-300:] or "（无 stderr）"))
    if rc != 0:
        named = [ln for ln in err.splitlines() if ln.startswith("STAGE_")]
        raise UiStageError("起台失败 rc=%s：%s" % (rc, named[-1] if named else err[-300:]))
    # 端口面以回执自带 services 列表为准（租约真源）；旧格式回执无列表时
    # 校验器保守要求 console（full 台语义）。
    return validate_stage_receipt(out)


def down_stage(project: str, *, repo_root: Optional[str] = None,
               down_cap: Optional[float] = None,
               runner: Optional[Runner] = None) -> Dict[str, Any]:
    """拆台（幂等）：**绝不 raise**——终态清理路径的最后一环必须走完；失败
    响亮返回（ok=False + detail 点名，调用方落日志/详情，sweep 巡检可接手）。"""
    detail = ""
    if not project or not str(project).strip():
        log.error("[down_stage] project 为空——无从拆（usage 红不静默）")
        return {"ok": False, "detail": "usage 红：project 为空"}
    run = runner or _default_runner
    cap = float(down_cap) if down_cap is not None else down_cap_s()
    try:
        cli = stage_cli_path(repo_root)
    except UiStageEnvError as e:
        log.error("[down_stage] %s", e)
        return {"ok": False, "detail": str(e)}
    try:
        rc, out, err = run(["python3", cli, "down", "--project", str(project).strip()],
                           cap, {})
    except UiStageEnvError as e:   # runner 超上限被杀——拆台未证实完成，响亮
        log.error("[down_stage] 拆台超上限 %ss：%s", cap, e)
        return {"ok": False, "detail": "拆台超上限 %ss：%s" % (cap, e)}
    if rc == 0:
        log.info("[down_stage] 台 %s 已拆", project)
        return {"ok": True, "detail": (out.strip().splitlines() or [""])[-1][:200]}
    named = [ln for ln in err.splitlines() if ln.startswith("STAGE_")]
    detail = "拆台 rc=%s：%s" % (rc, named[-1] if named else err[-300:] or out[-200:])
    log.error("[down_stage] %s", detail)
    return {"ok": False, "detail": detail}


# ---------------------------------------------------------------------------
# 编排入口（场景/活动共用的公开协程；方案 §1b「编排抽纯函数」的公开形态）
# ---------------------------------------------------------------------------

async def run_capture_stage(*, project: str, services: str = "temporal",
                            capture_cmd: List[str],
                            capture_timeout_s: float,
                            stage_up_timeout_s: float,
                            repo_root: Optional[str] = None,
                            env_extra: Optional[Dict[str, str]] = None,
                            down_cap: Optional[float] = None) -> Dict[str, Any]:
    """引擎单所有者的一整拍：起台→写 stage-json→跑 capture→**四条终态路径全
    拆台**（成功/超时/取消/异常）。取消语义=先拆台再按 Temporal 惯例重抛
    （取消不是免拆台牌照）；超时/失败回执点名（fail-visible 不静默）。

    capture_cmd 收**可注入桩**（场景用 `python3 -c sleep` 桩，引擎用 node
    capture-lane）；本协程把 up 回执落 stage-json 临时文件并追加 `--stage-json`
    参数——消费者按既有契约读它（不读=多一个无害参数），生命周期全归本协程。

    起台腿经 asyncio.shield 保护：取消若落在起台进行中，等起台线程收尾（有
    stage_up_timeout_s 帽）再拆台——半途 down 会跟在飞 compose up 互踩（账号
    与容器面互斥窗），宁可慢不可撕账。

    返回 dict：{ok, detail, project, capture_rc, capture_out, capture_err,
    up(receipt), reclaimed, note}。up 失败不吞进回执——原样抛
    UiStageEnvError/UiStageError（降级/直红分档归调用方策略）。"""
    up_task = asyncio.ensure_future(asyncio.to_thread(
        up_stage, project, repo_root=repo_root, up_cap=float(stage_up_timeout_s),
        services=services, env_extra=env_extra))
    try:
        receipt = await asyncio.shield(up_task)
    except UiStageError:
        # 契约红（up rc=0 但回执畸形，或 rc≠0）——回执畸形时台**大概率在场**
        # （up 成功后校验才失败）：幂等补一刀 down 再重抛（台不在场时 down
        # 是无害 no-op）。260915 实证：这条缝漏拆会留孤儿台（services 校验
        # 红那次，80202 台在场无人认领）。env 面错误不在此补刀（up 进程自身
        # 失败腿已清 + docker 不可用时 down 只会添噪音）。
        await asyncio.to_thread(down_stage, project, repo_root=repo_root,
                                down_cap=down_cap)
        raise
    except asyncio.CancelledError:
        # 取消落在起台窗内：shield 保 up_task 收尾（线程不可中断，帽在
        # stage_up_timeout_s），随后补拆再重抛——绝不把半起的台丢给兜底链。
        try:
            receipt = await up_task
        except Exception:            # noqa: BLE001  起台本就失败=无台可拆
            receipt = None
        if receipt is not None:
            down = await asyncio.to_thread(down_stage, project,
                                           repo_root=repo_root, down_cap=down_cap)
            log.info("[run_capture_stage] 取消（起台窗内）：台 %s 收尾后拆台 %s",
                     project, "完成" if down.get("ok") else "失败：" + down.get("detail", ""))
        raise
    loop = asyncio.get_running_loop()
    fd, json_path = tempfile.mkstemp(prefix="stage-%s-" % project, suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    cmd = list(capture_cmd) + ["--stage-json", json_path]
    proc: Optional[asyncio.subprocess.Process] = None
    note = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(),
                                                  timeout=float(capture_timeout_s))
            capture_rc = proc.returncode
            capture_out = (out_b or b"").decode("utf-8", "replace")[-2000:]
            capture_err = (err_b or b"").decode("utf-8", "replace")[-2000:]
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            capture_rc = None
            capture_out, capture_err = "", "capture 超时（>%ss），进程已 kill" % capture_timeout_s
        down = await loop.run_in_executor(
            None, lambda: down_stage(project, repo_root=repo_root, down_cap=down_cap))
        reclaimed = bool(down.get("ok"))
        if not reclaimed:
            note = "拆台失败（响亮不静默，交 sweep/巡检接手）：%s" % down.get("detail", "")
            log.error("[run_capture_stage] %s", note)
        if capture_rc is None:
            return {"ok": False, "timed_out": True, "reclaimed": reclaimed,
                    "detail": "%s capture 超时（>%ss），进程已 kill；台已拆（终态回收）"
                              % (project, capture_timeout_s),
                    "project": project, "capture_rc": None,
                    "capture_out": capture_out, "capture_err": capture_err,
                    "up": receipt, "note": note}
        if capture_rc == 0:
            return {"ok": True, "timed_out": False, "reclaimed": reclaimed,
                    "detail": "capture 成功；台已拆（终态回收）", "project": project,
                    "capture_rc": 0, "capture_out": capture_out,
                    "capture_err": capture_err, "up": receipt, "note": note}
        return {"ok": False, "timed_out": False, "reclaimed": reclaimed,
                "detail": "%s capture 退出码 %s：%s" % (project, capture_rc,
                                                        (capture_err or capture_out)[-400:]),
                "project": project, "capture_rc": capture_rc,
                "capture_out": capture_out, "capture_err": capture_err,
                "up": receipt, "note": note}
    except asyncio.CancelledError:
        # 取消路（capture 窗内）：捕获进程回收 + 台拆完再重抛（Temporal 语义）。
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001  收尾尽力——重抛优先
                pass
        down = await loop.run_in_executor(
            None, lambda: down_stage(project, repo_root=repo_root, down_cap=down_cap))
        log.info("[run_capture_stage] 取消路：台 %s 拆台 %s（终态回收）",
                 project, "完成" if down.get("ok") else "失败：" + down.get("detail", ""))
        raise
    finally:
        try:
            os.unlink(json_path)
        except OSError:
            pass
        if proc is not None and proc.returncode is None:   # backstop 不留孤儿
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
