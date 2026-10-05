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
  幕后 stage_docker 自起 hold 保持分支（租约+心跳），本进程退出后台不死；
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
        raise UiStageError("usage red: %s must be a number of seconds (float), got %r" % (env_key, raw))
    if not math.isfinite(val) or val <= 0:   # inf/nan/零/负=usage 红（畸形不静默）
        raise UiStageError("usage red: %s must be a positive finite number of seconds, got %r" % (env_key, raw))
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
        raise UiStageError("usage red: ticket normalizes to empty (got %r) — cannot map the project name"
                           % ticket)
    name = "ui-shot-%s-g%d" % (raw, max(0, int(gen)))
    if len(name) > 45:
        import hashlib
        h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        name = "ui-shot-%s-g%d" % (h, max(0, int(gen)))
    if not _PROJECT_RE.match(name):
        raise UiStageError("usage red: project name %r fails the stage gate (regex %s)"
                           % (name, _PROJECT_RE.pattern))
    return name


# service→port-key contract map (t261005-13): stage_docker receipts carry port
# keys temporal/ui/console (_flip_lease_up); ports.dsh does not exist — the dsh
# service exposes the console port (capture-lane reads st.ports.console,
# ns_acquire reads ports.temporal; one contract repo-wide). Two incidents
# (260929, 261005): the validator looked up ports.dsh 1:1 by service name and
# red-flagged a valid full-bench receipt ("up receipt missing ports.dsh" — the
# legacy red text, paraphrased in English so this line carries no marker). Fix the
# consumer mapping; the producer contract stands. Unknown service names keep
# the 1:1 mapping (fail-closed: they demand their own port key).
SERVICE_PORT_KEY = {"temporal": "temporal", "dsh": "console"}


def validate_stage_receipt(text: str, services: Optional[List[str]] = None
                           ) -> Dict[str, Any]:
    """Boot-receipt check (pure function): last non-blank stdout line = JSON
    with a non-empty str project, and every declared service maps through
    SERVICE_PORT_KEY to a positive-int port (dsh→console; a services="temporal"
    bench has no console — validate on demand, never force the full-bench port
    face onto a slim bench; a receipt without a services list conservatively
    requires console, for legacy-format compatibility). Malformed =
    UiStageError (contract red — we write this receipt for our own consumers;
    it must prove itself before delivery, not surface as a consumer-side
    ENV_FAIL). Fail-closed is unchanged: a full-bench receipt still missing
    ports.console or ports.temporal stays red (t261005-13 regression pins)."""
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
        port_key = SERVICE_PORT_KEY.get(str(svc), str(svc))
        v = ports.get(port_key)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise UiStageError("up receipt missing ports.%s (required by "
                               "service %s, positive int): %r"
                               % (port_key, svc, receipt))
    return receipt


def stage_dead_marker(stderr_text: str) -> bool:
    """capture-lane 的「外部舞台已死」ENV_FAIL 点名词（消费其 stderr，驱动
    C2 的死台→down+冷重试分支）。词面改动属 capture-lane 契约变更，同步改这里。"""
    return _DEAD_MARKER in str(stderr_text or "")


# Host-side temp dirs holding the bench registry (project -> dir, t261005-16):
# created by up_stage, reclaimed by down_stage; after a successful up the
# container bind mount still reads the dir, so it must live until teardown.
_BENCH_TMP_DIRS: Dict[str, str] = {}

# Same value as capture-lane.mjs BENCH_PROJECT_KEY (the shape true source is the
# JS side; the two comment blocks point at each other).
_BENCH_PROJECT_KEY = "capture-bench"


def _write_bench_registry(fixtures_dir: str) -> str:
    """Write the bench registry (a Python mirror; the shape true source is
    capture-lane.mjs buildBenchRegistry — schema v1 top-level `project:` LIST
    form; never fall back to a flat top-level key:/name:/dirs: block, both
    parsers quarantine that shape, t261005-16 arbitrate round 1). Returns the
    registry root (the projects/ dir under the --fixtures-dir mount point,
    i.e. /fixtures/projects inside the container).

    The workspace is created INSIDE the mounted tree and declared as its
    container path (/fixtures/workspace, t261005-16 arbitrate round 3): the
    container can only see/create paths under the mount — declaring the host
    temp absolute path re-creates the KI-204 dead-dir defect one path away."""
    root = os.path.join(fixtures_dir, "projects")
    proj = os.path.join(root, _BENCH_PROJECT_KEY)
    ws = os.path.join(fixtures_dir, "workspace")
    declared_ws = "/fixtures/workspace"
    os.makedirs(proj, exist_ok=True)
    os.makedirs(ws, exist_ok=True)
    pyaml = os.path.join(proj, "project.yaml")
    pyaml_text = ("schema: v1\n"
                  "project:\n"
                  "  - key: %s\n"
                  "    name: Capture Bench\n"
                  "    dirs:\n"
                  "      - %s\n" % (_BENCH_PROJECT_KEY, declared_ws))
    fd = os.open(pyaml, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # occupied target = fail-loud
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(pyaml_text)
    with open(os.path.join(root, ".migrated"), "x", encoding="utf-8") as fh:
        fh.write("source: ui_capture_stage bench registry (t261005-16)\n")
    return root


def _cleanup_bench_dir(project: str) -> None:
    """Reclaim the host bench-registry dir (best-effort: a teardown path must
    never raise in front of the stage teardown itself)."""
    import shutil
    d = _BENCH_TMP_DIRS.pop(str(project), None)
    if d:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception as e:  # noqa: BLE001 — best-effort, named, never blocking
            log.warning("[_cleanup_bench_dir] bench registry dir reclaim failed for stage %s "
                        "(left for system tmp cleanup): %s", project, e)


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
    自身的起台失败清理分支负责就地拆；外部击杀的残面交 down_stage 幂等补刀
    + sweep crit_iii 兜底——三层都响亮，不静默）。"""
    if not project or not str(project).strip():
        raise UiStageError("usage red: project is empty")
    run = runner or _default_runner
    cap = float(up_cap) if up_cap is not None else up_cap_s()
    cli = stage_cli_path(repo_root)
    extra = dict(env_extra or {})
    key = str(project).strip()
    # Bench registry injection (t261005-16, KI-204 acceptance-rework face): with
    # the compose default SANDBAR_PROJECTS_DIR=/nonexistent, the loader replays
    # the in-repo legacy seed (the retired project with its dead host path) and
    # session/workspace creation keeps failing with ENOENT — on the production
    # pathway, since merge_check boots exactly this stage. Same fix shape as the
    # capture-lane boot-local/docker pathways (shape true source =
    # buildBenchRegistry; this is the Python mirror): build a registry carrying
    # the .migrated marker on the host, inject it via --fixtures-dir (mounted at
    # /fixtures) + SANDBAR_TEST_PROJECTS_DIR=/fixtures/projects (compose passes
    # it into the container as SANDBAR_PROJECTS_DIR); the loader sees the marker
    # and skips the seed. The host temp dir is registered in _BENCH_TMP_DIRS and
    # reclaimed idempotently by down_stage.
    try:
        bench_dir = tempfile.mkdtemp(prefix="sandbar-bench-registry-")
    except OSError as e:
        raise UiStageEnvError("failed to create the host bench-registry dir (%s) — "
                              "never silently fall back to a registry-less stage" % e)
    bench_fixtures = _write_bench_registry(bench_dir)
    _BENCH_TMP_DIRS[key] = bench_dir
    rc, out, err = run([ "python3", cli, "up", "--project", key,
                         "--services", str(services or "full"),
                         "--timeout", str(int(cap)),
                         "--fixtures-dir", bench_fixtures ],
                       cap, {**extra, "SANDBAR_TEST_PROJECTS_DIR": "/fixtures/projects"})
    if rc != 0:
        # A failed up means no stage is mounted; reclaim the host registry dir
        # right here (the success path hands it to down_stage).
        _cleanup_bench_dir(key)
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
        return {"ok": False, "detail": "usage red: project is empty"}
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
        return {"ok": False, "detail": "teardown exceeded cap %ss: %s" % (cap, e)}
    if rc == 0:
        # Stage down: the container bind mount no longer reads; reclaim the host
        # registry dir here (t261005-16).
        _cleanup_bench_dir(str(project))
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

    起台分支经 asyncio.shield 保护：取消若落在起台进行中，等起台线程收尾（有
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
        # 失败分支已清 + docker 不可用时 down 只会添噪音）。
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
            capture_out, capture_err = "", "capture timed out (>%ss), process killed" % capture_timeout_s
        down = await loop.run_in_executor(
            None, lambda: down_stage(project, repo_root=repo_root, down_cap=down_cap))
        reclaimed = bool(down.get("ok"))
        if not reclaimed:
            note = "拆台失败（响亮不静默，交 sweep/巡检接手）：%s" % down.get("detail", "")
            log.error("[run_capture_stage] %s", note)
        if capture_rc is None:
            return {"ok": False, "timed_out": True, "reclaimed": reclaimed,
                    "detail": "%s capture timed out (>%ss), process killed; stage torn down (final-state reclaim)"
                              % (project, capture_timeout_s),
                    "project": project, "capture_rc": None,
                    "capture_out": capture_out, "capture_err": capture_err,
                    "up": receipt, "note": note}
        if capture_rc == 0:
            return {"ok": True, "timed_out": False, "reclaimed": reclaimed,
                    "detail": "capture succeeded; stage torn down (final-state reclaim)", "project": project,
                    "capture_rc": 0, "capture_out": capture_out,
                    "capture_err": capture_err, "up": receipt, "note": note}
        return {"ok": False, "timed_out": False, "reclaimed": reclaimed,
                "detail": "%s capture exit code %s: %s" % (project, capture_rc,
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
