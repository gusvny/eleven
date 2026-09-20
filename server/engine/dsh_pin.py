"""dsh 版本面（钉路径）解析与自检 —— t260916-24（dsh-upgrade epic T4）。

背景：引擎 spawn 的 dsh 命令此前在 import 时静默解析（agent_activities.DSH_CMD），
「本 worker 用的 dsh 是哪个版本、从哪来」无处可查，升级切流只能靠猜。本模块把
版本面变成可观测、可对照、可响亮三件事：

- 可观测：dsh_face_payload() 产出统一 face（mode/cmd/bin/real_bin/version/来源/
  镜像/期望版本），worker 启动写进 meta JSON、首票落票面 artifacts 并进日志；
- 可对照：SANDBAR_DSH_EXPECTED_VERSION 非空时与版本比对，不符 = mismatch 响亮
  （告警级，每次 spawn 都提，票面留痕）；SANDBAR_DSH_STRICT=1 时升格硬闸
  （raise，缺省 off = 不破现状）；
- 可解耦：host 形态命令走 SANDBAR_AGENT_CMD 显式钉（既有旋钮，语义不变），docker
  形态镜像走 SANDBAR_AGENT_IMAGE（既有旋钮，agent_runtime 消费）——升级只切引擎
  侧旋钮，console(3099) 用的全局 dsh 不受影响（红线 #1 自动满足）。

旋钮一览（全部普通 env，缺省=现行为）：
- SANDBAR_AGENT_CMD           host 形态整命令（shlex），缺省 "dsh --profile sandbar-headless"
- SANDBAR_AGENT_IMAGE         docker 形态镜像 tag，缺省 agent_runtime.DEFAULT_AGENT_IMAGE
                              （由调用方传参注入；本模块刻意零仓内依赖——agent_runtime
                              禁 import shared/agent_activities 一族，反向同样不 import）
- SANDBAR_DSH_EXPECTED_VERSION 期望版本（host=实证版；docker=tag 提取版）；空=只记录不比对
- SANDBAR_DSH_STRICT          "1"=mismatch 升格硬闸（raise）；缺省只告警

docker 形态版本自镜像 tag 按 `dsh-<version>-s<seq>` 约定提取，标注 tag-derived
非实证；TODO(T3/Q3)：镜像升版票落地时补「容器内实测 dsh --version」实证子用例，
防约定漂移无人知。

fail-closed 边界（与调用方的分工）：
- 坏 SANDBAR_AGENT_CMD（shlex 解析失败/空命令）→ DshPinError 响亮点名——与旧
  import 时炸同等响亮，但文案带旋钮名与原文；
- `<dsh> --version` 跑不出来（缺文件/非零/超时/输出畸形）→ 不抛，face 里
  version_state=error + detail 照记（观测面不挡启动；真正 spawn 时的失败自有
  spawn 路径响亮）；
- mode 非法值 → face 记 "unknown" 不炸（fail-closed 归 agent_runtime.runtime_mode
  的 spawn 路径，观测面不抢职责、不静默改名）。

版本输出契约：`dsh --version` 单行版本样 token（260916 实测输出 "0.1.1-rc.2"）。
空/多行/非版本样 = error（升级对账语境宁红勿漏：输出形态漂移本身就是接缝信号）。
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional

DEFAULT_DSH_CMD_TEXT = "dsh --profile sandbar-headless"
ENV_AGENT_CMD = "SANDBAR_AGENT_CMD"
ENV_AGENT_IMAGE = "SANDBAR_AGENT_IMAGE"
ENV_EXPECTED = "SANDBAR_DSH_EXPECTED_VERSION"
ENV_STRICT = "SANDBAR_DSH_STRICT"
ENV_RUNTIME = "SANDBAR_AGENT_RUNTIME"
RUNTIME_MODES = ("host", "docker")
PROBE_TIMEOUT_DEFAULT_SEC = 10.0

# 镜像 tag 约定：sandbar-agent:dsh-<version>-s<seq>（build_agent_image.sh 产出）；
# 贪婪捕获让「版本段自身含 -s」时仍锚定最后一个 -s<数字> 为序号
_IMAGE_TAG_RE = re.compile(r"^sandbar-agent:dsh-(.+)-s\d+$")
# 版本样 token：semver 带预发布段（0.1.1-rc.2）
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class DshPinError(RuntimeError):
    """版本面解析/硬闸失败（响亮点名，绝不静默回落）。"""


def _env(env) -> Dict[str, str]:
    return os.environ if env is None else env


def resolve_dsh_cmd(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """解析 host 形态 dsh 命令。返回 {"cmd": [...], "source": "env"|"default", "raw": str}。

    缺省（env 未设/空串）= 与 agent_activities.DSH_CMD 的旧缺省逐元素等值（不破现状）。
    坏 shlex / 空命令 → DshPinError（点名旋钮名与原文）。
    """
    env = _env(env)
    raw = (env.get(ENV_AGENT_CMD) or "").strip()
    if not raw:
        return {"cmd": shlex.split(DEFAULT_DSH_CMD_TEXT),
                "source": "default", "raw": DEFAULT_DSH_CMD_TEXT}
    try:
        cmd = shlex.split(raw)
    except ValueError as e:
        raise DshPinError("%s 解析失败（shlex：%s）：%r" % (ENV_AGENT_CMD, e, raw))
    if not cmd or not cmd[0]:
        raise DshPinError("%s 解析为空命令：%r" % (ENV_AGENT_CMD, raw))
    return {"cmd": cmd, "source": "env", "raw": raw}


def probe_dsh_version(cmd0: str, timeout: float = PROBE_TIMEOUT_DEFAULT_SEC,
                      env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """跑 `<dsh> --version` 实证版本。

    返回 {"version": str|None, "state": "ok"|"error", "detail": str}。
    失败（缺文件/非零退出/超时/输出非单行版本样）= error + detail 点名；
    三条路径（正常/超时/调用方异常）都全终态回收（kill 进程组 + wait 收割）。
    """
    full_env = dict(_env(env))
    try:
        proc = subprocess.Popen(
            [cmd0, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=full_env, start_new_session=True)
    except OSError as e:
        return {"version": None, "state": "error",
                "detail": "起不了 %s --version：%s" % (cmd0, e)}
    killed = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_proc_group(proc)
        killed = True
        return {"version": None, "state": "error",
                "detail": "%s --version 超时（>%ss），进程组已收割" % (cmd0, timeout)}
    except BaseException:
        _kill_proc_group(proc)
        raise
    text = (out or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        return {"version": None, "state": "error",
                "detail": "%s --version 退出码 %s，输出=%r" % (cmd0, proc.returncode, text[:200])}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 1 or not _VERSION_RE.match(lines[0]):
        return {"version": None, "state": "error",
                "detail": "%s --version 输出非单行版本样（%d 行）：%r" % (cmd0, len(lines), text[:200])}
    if killed:  # pragma: no cover - 防御位，communicate 正常返回时不会置位
        return {"version": None, "state": "error", "detail": "进程被收割，输出不可信"}
    return {"version": lines[0], "state": "ok",
            "detail": "%s 实证 %s" % (cmd0, lines[0])}


def _kill_proc_group(proc: subprocess.Popen) -> None:
    """进程组级终止 + 等待收割（全终态：正常/超时/异常三路共用）。"""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL 后不该发生
        pass


def image_tag_version(image: str) -> Dict[str, Any]:
    """从镜像 tag 提取 dsh 版本（约定 sandbar-agent:dsh-<version>-s<seq>）。

    返回 {"version": str|None, "state": "ok"|"unknown", "detail": str}；
    异形 tag = unknown 不炸（tag 只是弱证据，异形仅意味着「无法从 tag 判版」）。
    """
    m = _IMAGE_TAG_RE.match(image or "")
    if not m:
        return {"version": None, "state": "unknown",
                "detail": "镜像 tag %r 不含 dsh-<version>-s<seq> 约定，无法从 tag 判版"
                          "（tag-derived 非实证；TODO(T3/Q3)：补容器内实测 --version 实证子用例）" % image}
    ver = m.group(1)
    if not _VERSION_RE.match(ver):
        return {"version": None, "state": "unknown",
                "detail": "镜像 tag %r 提取段 %r 非版本样" % (image, ver)}
    return {"version": ver, "state": "ok",
            "detail": "镜像 tag 提取 %s（tag-derived 非实证；TODO(T3/Q3)：补容器内实测实证子用例）" % ver}


def expected_state_of(version: Optional[str], env: Optional[Dict[str, str]] = None) -> str:
    """期望版本比对（纯函数）：unset（未配）/ match / mismatch。"""
    env = _env(env)
    expected = (env.get(ENV_EXPECTED) or "").strip()
    if not expected:
        return "unset"
    return "match" if version == expected else "mismatch"


def enforce_expected(face: Dict[str, Any], env: Optional[Dict[str, str]] = None) -> str:
    """对已算好的 face 做期望对照与硬闸判定。返回一行人读 note（供日志/票面）。

    mismatch 且 SANDBAR_DSH_STRICT=1 → raise DshPinError（硬闸，升级切错版本时
    宁可整段失败也不静默跑错版本）；缺省只返回 note 由调用方 warning。
    """
    env = _env(env)
    state = face.get("expected_state") or expected_state_of(face.get("version"), env)
    expected = (env.get(ENV_EXPECTED) or "").strip()
    note = face_note(face)
    if state == "mismatch":
        if (env.get(ENV_STRICT) or "").strip() == "1":
            raise DshPinError(
                "dsh 版本与预期不符（硬闸）：实际=%r 期望=%r（%s=%r）。升级切流走错版本，"
                "拒绝开工；核对本 worker 的 %s/%s" % (face.get("version"), expected,
                                                     ENV_EXPECTED, expected,
                                                     ENV_AGENT_CMD, ENV_AGENT_IMAGE))
        return note + " 【mismatch】期望=%s 不符——响亮告警（设 %s=1 升格硬闸）" % (expected, ENV_STRICT)
    if state == "match":
        return note
    return note


def face_note(face: Dict[str, Any]) -> str:
    """版本面一行人读文案（日志/票面用，可查询字段全部在场）。"""
    version = face.get("version")
    vstate = face.get("version_state")
    vtag = {("ok", "host"): "实证", ("ok", "docker"): "tag-derived"}.get((vstate, face.get("mode")), vstate)
    cmd = " ".join(face.get("cmd") or [])
    image = face.get("image")
    est = face.get("expected_state")
    parts = ["mode=%s" % face.get("mode")]
    if face.get("mode") == "docker":
        parts.append("image=%s(来源=%s) 版本=%s(%s)"
                     % (image, face.get("image_source"), version or "?", vtag))
    else:
        parts.append("cmd='%s'(来源=%s) bin=%s(→%s) 版本=%s(%s)"
                     % (cmd, face.get("cmd_source"), face.get("bin"),
                        face.get("real_bin") or "?", version or "?", vtag))
    if vstate == "error" and face.get("version_detail"):
        parts.append("细节=%s" % face["version_detail"])
    parts.append("期望=%s(%s)" % ((env_expected(face)) or "未配", est))
    return "dsh 版本面：" + " ".join(parts)


def env_expected(face: Dict[str, Any]) -> str:
    """face 携带的期望值（便于文案拼装；不读 env）。"""
    return face.get("expected") or ""


def dsh_face_payload(mode: Optional[str] = None,
                     env: Optional[Dict[str, str]] = None,
                     default_image: Optional[str] = None,
                     probe_timeout: float = PROBE_TIMEOUT_DEFAULT_SEC,
                     probe: bool = True) -> Dict[str, Any]:
    """统一版本面。worker 启动 / 首票 spawn 各取一次（调用方自做 once 缓存）。

    mode：host|docker；None → 读 SANDBAR_AGENT_RUNTIME（缺省 host；非法值记
    "unknown" 不炸——fail-closed 归 agent_runtime 的 spawn 路径）。
    default_image：docker 形态的缺省镜像（调用方传 agent_runtime.DEFAULT_AGENT_IMAGE，
    保持本模块零仓内依赖）。
    probe=False：跳过 `--version` 子进程（docker 形态天然跳过；供纯形状 UT）。
    坏 SANDBAR_AGENT_CMD → DshPinError（响亮，对齐旧 import 行为）。
    """
    env = _env(env)
    if mode is None:
        raw = (env.get(ENV_RUNTIME) or "").strip().lower()
        mode = raw if raw in RUNTIME_MODES else ("host" if not raw else "unknown")
    elif mode not in RUNTIME_MODES:
        mode = "unknown"  # 显式非法值同样归 unknown（观测面不抢 spawn 路径的 fail-closed）
    face: Dict[str, Any] = {
        "mode": mode,
        "cmd": None, "cmd_source": None, "bin": None, "real_bin": None,
        "version": None, "version_state": "not-probed", "version_detail": "",
        "image": None, "image_source": None,
        "expected": (env.get(ENV_EXPECTED) or "").strip(),
        "ts": int(time.time()),
    }
    if mode == "docker":
        image = (env.get(ENV_AGENT_IMAGE) or "").strip()
        face["image"] = image or default_image
        face["image_source"] = "env" if image else ("default" if face["image"] else None)
        if face["image"]:
            tag = image_tag_version(face["image"])
            face["version"] = tag["version"]
            face["version_state"] = tag["state"] if tag["state"] == "ok" else "unknown"
            face["version_detail"] = tag["detail"]
        else:
            face["version_state"] = "unknown"
            face["version_detail"] = "无镜像可判（env 与缺省皆空）"
    else:
        resolved = resolve_dsh_cmd(env)  # 坏 shlex 在此响亮抛出
        face["cmd"] = resolved["cmd"]
        face["cmd_source"] = resolved["source"]
        face["bin"] = resolved["cmd"][0]
        if os.path.sep in face["bin"] or "/" in face["bin"]:
            real = os.path.realpath(face["bin"])
            face["real_bin"] = real if os.path.exists(real) else None
        else:
            import shutil
            face["real_bin"] = shutil.which(face["bin"])  # PATH 内二进制：解析真实落点
        if probe:
            pv = probe_dsh_version(face["bin"], timeout=probe_timeout, env=env)
            face["version"] = pv["version"]
            face["version_state"] = pv["state"]
            face["version_detail"] = pv["detail"]
    face["expected_state"] = expected_state_of(face["version"], env)
    return face
